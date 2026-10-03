"""Outlet reads and writes, with the field's constraints rather than the Desk's.

Two things differ from ordinary CRUD:

- **Reads are territory-scoped by construction.** Everything here goes through `frappe.get_list`,
  never `frappe.get_all`, because the latter forces `ignore_permissions=True` and would hand a rep
  every shop on the site.
- **Writes are field-shaped.** A rep may correct what they can see standing in front of the shop -
  a phone number, a pin on the map - and nothing else. Approval, credit and provenance are not
  theirs to set, whatever the payload says.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, now_datetime

from fieldmate import compat
from fieldmate.services import catalogue as catalogue_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import settings as settings_service

# What a rep is allowed to change from the app. Anything else is ignored silently on update
# rather than rejected, so a newer app build sending an extra field never breaks an old server.
REP_EDITABLE = {
	"outlet_name", "owner_name", "mobile_no", "alternate_mobile", "email_id",
	"address_line1", "address_line2", "city", "district", "state", "pincode",
	"latitude", "longitude", "geo_accuracy_m",
	"opening_time", "closing_time", "weekly_off",
	"channel", "outlet_type", "monthly_potential",
	"gstin", "pan", "fssai_no",
	"shop_photo", "shop_board_photo",
}

LIST_FIELDS = [
	"name", "outlet_name", "outlet_status", "approval_status", "channel", "outlet_class",
	"territory", "primary_beat", "distributor", "city", "mobile_no",
	"latitude", "longitude", "geo_fence_radius_m", "monthly_potential", "modified",
]

# What one shop's own screen shows, on top of the list row. Kept separate because
# LIST_FIELDS is sent for every shop a rep holds - widening it put 5,000 outlets at
# 6.6 MB against a 2.5 MB budget, which is what Gate 1 caught. This list is fetched
# one shop at a time, so it can afford to be generous.
DETAIL_FIELDS = [
	*LIST_FIELDS,
	"outlet_type", "owner_name", "alternate_mobile", "email_id",
	"address_line1", "address_line2", "district", "state", "pincode",
	"gstin", "fssai_no", "pan", "kyc_verified",
	"credit_limit", "credit_days", "outstanding_amount",
	"opening_time", "closing_time", "weekly_off",
	"shop_photo", "shop_board_photo", "onboarding_date", "enable_geo_fence",
]


def search(query: str | None = None, beat: str | None = None, limit: int = 50,
           user: str | None = None) -> list[dict]:
	"""Outlets this user may see, newest first, optionally filtered.

	For a rep whose territory is too large to mirror on the device, this is the fallback path.
	"""
	filters = {}
	if beat:
		filters["primary_beat"] = beat

	or_filters = None
	if query:
		like = f"%{query}%"
		or_filters = {"outlet_name": ["like", like], "city": ["like", like],
		              "mobile_no": ["like", like], "name": ["like", like]}

	return frappe.get_list(
		"FieldMate Outlet",
		filters=filters,
		or_filters=or_filters,
		fields=LIST_FIELDS,
		limit_page_length=min(cint(limit) or 50, 200),
		order_by="modified desc",
		user=user or frappe.session.user,
	)


def detail(outlet: str, user: str | None = None) -> dict:
	"""Everything the Outlet 360 screen shows, in one call.

	`frappe.get_doc` does not apply user permissions on its own, so the read is gated here
	explicitly. Skipping that would let a rep fetch any shop by guessing its name.
	"""
	user = user or frappe.session.user
	if not frappe.has_permission("FieldMate Outlet", "read", doc=outlet, user=user):
		raise frappe.PermissionError(frappe._("This outlet is not in your territory."))

	doc = frappe.get_doc("FieldMate Outlet", outlet)
	allowed, reason = doc.can_take_order()
	party = doc.billing_party()

	# Whose books, resolved the way the rest of the app resolves it: from the rep, then from
	# settings. This used to read `doc.get("company")` first - a field FieldMate Outlet does not
	# have - so the whole expression fell through to `default_company`, and on any site where
	# nobody had set that, every shop came back with no credit at all. The phone read the empty
	# block as "not on this phone" while `credit.check()`, which asks the rep, was answering
	# "Within Limit, 50,000" for the same shop a function away.
	company = catalogue_service.resolve_company(field_user_service.for_user(user))

	credit = {}
	if party and company:
		credit = compat.get_credit_status(party, company)

	return {
		"outlet": {f: doc.get(f) for f in DETAIL_FIELDS if f != "name"} | {"name": doc.name},
		"contacts": [
			{"person_name": c.person_name, "role_at_outlet": c.role_at_outlet,
			 "mobile_no": c.mobile_no, "is_primary": bool(c.is_primary)}
			for c in (doc.contacts or [])
		],
		"can_take_order": allowed,
		"blocked_reason": reason,
		"billing_party": party,
		"credit": credit,
		"geo_fence_radius_m": doc.effective_geo_fence_radius(),
	}


def resolve_distributor(payload: dict, rep) -> str:
	"""Which distributor this new shop belongs to.

	A rep standing at a doorstep is not asked to pick one - they should not have to know, and a
	dropdown of every customer in the company is the wrong thing to hand somebody on a phone.
	So it is inferred, in order of how sure we can be:

	  1. what the app sent, if it sent anything
	  2. the distributor on the rep's own record
	  3. the one distributor serving the rep's territory, but only if there is exactly one

	If none of those settle it, we stop here with a sentence a rep can act on. Letting it fall
	through produced `[FieldMate Outlet, FM-OUT-05153]: distributor` on a phone screen - a raw
	framework error naming a document that was never saved.
	"""
	explicit = payload.get("distributor") or (rep.distributor if rep else None)
	if explicit:
		return explicit

	territory = payload.get("territory") or (rep.territory if rep else None)
	if territory:
		# Tier "Distributor" exactly, not any channel party: a CFA is our own depot and a super
		# stockist bills distributors rather than shops, so neither is an answer to "who supplies
		# this kirana". It is also what every retired FieldMate Distributor Profile became, so
		# this asks the same question the profile's `status: Active` filter used to ask. A site
		# that starts attaching shops to sub-stockists will want this widened, and that is a
		# decision for whoever sets those up.
		serving = frappe.get_all(
			"Customer",
			filters={"territory": territory, "fm_tier": "Distributor", "disabled": 0},
			pluck="name",
			limit_page_length=2,
		)
		if len(serving) == 1:
			return serving[0]
		if len(serving) > 1:
			frappe.throw(frappe._(
				"More than one distributor covers your area, so we cannot tell which one this "
				"shop belongs to. Ask your manager to set yours."
			))

	frappe.throw(frappe._(
		"Your account is not linked to a distributor yet, so a new shop has nowhere to belong. "
		"Ask your manager to set it on your FieldMate user."
	))


def create(payload: dict, user: str | None = None) -> dict:
	"""Field onboarding. Always lands unapproved, whatever the payload claims."""
	user = user or frappe.session.user
	rep = field_user_service.get(user)
	if rep and not rep.can_create_outlet:
		raise frappe.PermissionError(frappe._("You are not set up to add new shops."))

	client_uuid = payload.get("client_uuid")
	if client_uuid:
		existing = frappe.db.get_value("FieldMate Outlet", {"client_uuid": client_uuid}, "name")
		if existing:
			# Idempotent: a retried onboarding returns the shop it already created.
			return {"name": existing, "created": False}

	data = {k: v for k, v in payload.items() if k in REP_EDITABLE}
	data.update({
		"doctype": "FieldMate Outlet",
		"distributor": resolve_distributor(payload, rep),
		"territory": payload.get("territory") or (rep.territory if rep else None),
		"client_uuid": client_uuid,
		"created_offline": cint(payload.get("created_offline")),
		"device_id": payload.get("device_id"),
		"approval_status": "Pending Approval",
	})

	doc = frappe.get_doc(data)
	doc.insert()
	return {"name": doc.name, "created": True, "approval_status": doc.approval_status}


def update(outlet: str, payload: dict, user: str | None = None) -> dict:
	"""Correct what a rep can see from the doorstep. Nothing else."""
	user = user or frappe.session.user
	# Read permission, not write. A rep holds no write access on the DocType at all, which
	# keeps generic endpoints like frappe.client.set_value closed to them. The read check
	# proves the shop is in their territory; REP_EDITABLE decides what may change; the server
	# then saves on their behalf. Same shape as ADR-004 keeps for the ledger.
	if not frappe.has_permission("FieldMate Outlet", "read", doc=outlet, user=user):
		raise frappe.PermissionError(frappe._("This outlet is not in your territory."))

	doc = frappe.get_doc("FieldMate Outlet", outlet)
	changed = []
	for key, value in payload.items():
		if key in REP_EDITABLE and doc.get(key) != value:
			doc.set(key, value)
			changed.append(key)

	if not changed:
		return {"name": doc.name, "changed": []}

	if {"latitude", "longitude"} & set(changed):
		doc.geo_captured_on = now_datetime()

	doc.save(ignore_permissions=True)
	return {"name": doc.name, "changed": changed}


def approve(outlet: str, decision: str, notes: str | None = None, user: str | None = None) -> dict:
	"""A manager's decision on a shop a rep onboarded."""
	if decision not in ("Approved", "Rejected"):
		raise ValueError("decision must be Approved or Rejected")

	user = user or frappe.session.user

	rep = field_user_service.get(user)
	if rep and rep.designation == "Field Rep":
		# A rep approving their own onboarding would make the queue decorative.
		raise frappe.PermissionError(frappe._("Only a manager can approve a new shop."))

	if not frappe.has_permission("FieldMate Outlet", "read", doc=outlet, user=user):
		raise frappe.PermissionError(frappe._("This outlet is not in your territory."))

	doc = frappe.get_doc("FieldMate Outlet", outlet)
	doc.approval_status = decision
	if notes:
		doc.add_comment("Comment", notes)
	doc.save(ignore_permissions=True)

	return {"name": doc.name, "approval_status": doc.approval_status,
	        "approved_by": doc.approved_by}


def refresh_outstanding(outlet: str) -> float:
	"""Live from the ledger. Stored only so a list view has something to show."""
	doc = frappe.get_doc("FieldMate Outlet", outlet)
	party = doc.billing_party()
	company = doc.get("company") or settings_service.value("default_company")
	amount = flt(compat.get_outstanding(party, company)) if (party and company) else 0.0
	doc.db_set("outstanding_amount", amount, update_modified=False)
	return amount
