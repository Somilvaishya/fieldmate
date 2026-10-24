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

from fieldmate.services import credit as credit_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import paging

# What a rep is allowed to change from the app. Anything else is ignored silently on update
# rather than rejected, so a newer app build sending an extra field never breaks an old server.
REP_EDITABLE = {
	"outlet_name", "owner_name", "mobile_no", "alternate_mobile", "email_id",
	"address_line1", "address_line2", "city", "district", "state", "pincode",
	"latitude", "longitude",
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


def _search_filters(query: str | None, beat: str | None) -> tuple[dict, dict | None]:
	filters = {}
	if beat:
		filters["primary_beat"] = beat
	or_filters = None
	if query:
		like = f"%{query}%"
		or_filters = {"outlet_name": ["like", like], "city": ["like", like],
		              "mobile_no": ["like", like], "name": ["like", like]}
	return filters, or_filters


def count_search(query: str | None = None, beat: str | None = None,
                 user: str | None = None) -> int:
	"""How many shops this user may see under the same search. Permission-aware: a rep's count
	is their own territory's, never the site's."""
	filters, or_filters = _search_filters(query, beat)
	return paging.count("FieldMate Outlet", filters=filters, or_filters=or_filters,
	                    user=user or frappe.session.user)


def search(query: str | None = None, beat: str | None = None, limit: int = 50,
           user: str | None = None, start: int = 0) -> list[dict]:
	"""Outlets this user may see, newest first, optionally filtered.

	For a rep whose territory is too large to mirror on the device, this is the fallback path.
	"""
	filters, or_filters = _search_filters(query, beat)
	start, limit = paging.window(start, limit)

	return frappe.get_list(
		"FieldMate Outlet",
		filters=filters,
		or_filters=or_filters,
		fields=LIST_FIELDS,
		limit_start=start,
		limit_page_length=limit,
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

	# The company is resolved inside `credit.check` now, from the rep and then from settings,
	# which is how the rest of the app does it. It was resolved here as well until this function
	# stopped computing credit of its own - and the lesson is worth keeping: the version before
	# that read `doc.get("company")` first, a field FieldMate Outlet does not have, so the whole
	# expression fell through to `default_company`. On any site where nobody had set that, every
	# shop came back with no credit at all, and the phone read the empty block as "not on this
	# phone" while `credit.check()` answered "Within Limit, 50,000" for the same shop a function
	# away.

	# One credit answer for the whole app. This used to call `compat.get_credit_status`, which
	# was a third way of asking - `credit.check` for the order path, `collection.outstanding_for`
	# for the money screens, and this for the shop screen - and the three disagreed by
	# construction: this one measured the distributor and labelled it as the shop's.
	#
	# The four keys three screens already read keep their names and their meaning, so nothing on
	# a phone that has not been updated changes. What is added is the rest of the verdict, and
	# the shop's own position with its distributor, which no screen could see before.
	verdict = credit_service.check(doc.name, field_user_service.for_user(user), 0)
	credit = {
		"credit_limit": verdict["limit"],
		"outstanding": verdict["outstanding"],
		"headroom": verdict["headroom"],
		"unlimited": not bool(verdict["limit"]),
		"status": verdict["status"],
		"message": verdict["message"],
		"party": verdict["party"],
		"party_name": verdict["party_name"],
		# What this shop owes its distributor - our own count, and it says so. None on a party
		# we bill ourselves, where there is only one debt.
		"shop": verdict.get("shop"),
	}

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
	"""What this shop owes its distributor. Stored only so a list view has something to show.

	It used to read `compat.get_outstanding(billing_party)` - the **distributor's** balance with
	us - and write it onto the shop. Every shop under one distributor therefore showed the same
	number, that distributor's whole debt to this company, labelled as what the shop owed. A rep
	opening three kiranas on one beat saw the same five lakh against all three.

	The right figure is `collection.outstanding_for`, which counts the orders booked at this shop
	and subtracts the money collected against them. It is an estimate and says so - we are not a
	party to that sale and no receivable for it exists anywhere - but it is this shop's estimate
	rather than somebody else's fact.
	"""
	from fieldmate.services import collection as collection_service

	amount = flt(collection_service.outstanding_for(outlet).get("outstanding"))
	frappe.db.set_value("FieldMate Outlet", outlet, "outstanding_amount", amount,
	                    update_modified=False)
	frappe.clear_document_cache("FieldMate Outlet", outlet)
	return amount
