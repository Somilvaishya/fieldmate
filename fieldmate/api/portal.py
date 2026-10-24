"""Whitelisted endpoints for the distributor portal.

Thin on purpose. Each method establishes who is asking exactly once, hands the resolved row to
the service layer and returns the envelope. No method here decides anything about an order or a
claim; `services.portal` and `services.claim` do that, and they do it the same way whether the
call arrived from this module, a test or a job.

`require_device` is never set. A depot works from a desktop browser with a normal login, not
from a registered handset - the device registry is the rep's side of the app.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import claim as claim_service
from fieldmate.services import paging
from fieldmate.services import party as party_service
from fieldmate.services import portal as portal_service
from fieldmate.services import secondary_sales as secondary_sales_service


def _session():
	row = portal_service.me()
	portal_service.touch(row)
	return row


# --------------------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def whoami():
	row = _session()
	# The depot is a Customer since step 2d. Credit days are not a field on it - they are derived
	# from its Payment Terms Template, because a template with rows is what actually bills this
	# party and no single integer states one.
	party = frappe.db.get_value(
		"Customer", row.distributor,
		["customer_name", "territory", "fm_delivery_days"],
		as_dict=True) or {}
	return ok({
		"user": row.user,
		"full_name": frappe.db.get_value("User", row.user, "full_name"),
		"distributor": row.distributor,
		"distributor_name": party.get("customer_name") or row.distributor,
		"designation": row.designation,
		"can_accept_orders": bool(row.can_accept_orders),
		"can_raise_claims": bool(row.can_raise_claims),
		# Kept under the names the portal pages already read, so that retiring the profile is not
		# also a rename of everything on the screen.
		"customer": row.distributor,
		# The Customer's own id is the code. There was a `fm_distributor_code` field on Customer
		# for this, filled in by hand and unique, and it answered a question the primary key had
		# already answered - two names for one party is a reconciliation somebody does at month
		# end. Nothing on the portal ever rendered this key, so the field it used to read is now
		# unused; see the note in `setup/install.py` before removing it from a live site.
		"distributor_code": row.distributor,
		"territory": party.get("territory"),
		"credit_days": party_service.credit_days(row.distributor),
		"delivery_days": party.get("fm_delivery_days"),
	})


# --------------------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def distributor_orders(status: str | None = None, search: str | None = None, limit: int = 100,
                       start: int = 0):
	"""The depot's queue, a page at a time.

	`orders` keeps its key and its type: the portal pages are served to browsers that may have
	the old script cached, and one that has never heard of `start` reads the first page exactly
	as it always did.
	"""
	row = _session()
	start, limit = paging.window(start, limit, default=100)
	rows = portal_service.orders(status=status, search=search, limit=limit, row=row, start=start)
	return ok({
		"orders": rows,
		"totals": portal_service.queue_totals(row=row),
		**paging.envelope(rows, portal_service.count_orders(status=status, search=search, row=row),
		                  start, limit),
	})


@frappe.whitelist()
@endpoint()
def order_detail(order: str):
	row = _session()
	return ok(portal_service.order_detail(order, row=row))


@frappe.whitelist(methods=["POST"])
@endpoint()
def set_fulfilment(order: str, action: str, reference: str | None = None,
                   remarks: str | None = None):
	"""Accept, reject, invoice or deliver. The rep sees the result on their next sync."""
	row = _session()
	return ok(portal_service.act(order, action, reference=reference, remarks=remarks, row=row))


@frappe.whitelist(methods=["POST"])
@endpoint()
def set_fulfilment_bulk(orders=None, action: str = "Accepted", remarks: str | None = None):
	"""The Accept Selected button. Each order is decided on its own.

	One order failing does not fail the rest, and the caller is told which ones and why - a
	batch that rolls back silently because the fourth of twenty was already accepted is a batch
	a depot stops trusting.
	"""
	row = _session()
	names = parse_json(orders, "orders") or []
	if not isinstance(names, list):
		raise FieldMateError(Err.BAD_REQUEST, "Send a list of order names.")

	done, refused = [], []
	for name in names:
		try:
			done.append(portal_service.act(name, action, remarks=remarks, row=row))
		except Exception as e:
			refused.append({"order": name, "reason": frappe.utils.strip_html(str(e))})
	return ok({"done": done, "refused": refused})


# --------------------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def claim_status(status: str | None = None, limit: int = 50):
	row = _session()
	return ok({
		"claims": claim_service.for_distributor(row.distributor, status=status, limit=int(limit)),
		"totals": claim_service.totals_for(row.distributor),
	})


@frappe.whitelist()
@endpoint()
def claim_detail(claim: str):
	portal_service.assert_scope("FieldMate Claim", claim, _session())
	return ok(claim_service.summarise(claim))


@frappe.whitelist()
@endpoint()
def claimable(from_date: str, to_date: str, scheme: str | None = None):
	"""What could be claimed for a window, before anything is created."""
	row = _session()
	portal_service.may(row, "claim")
	return ok(claim_service.claimable(row.distributor, from_date, to_date, scheme=scheme))


# --------------------------------------------------------------------------------------
# secondary sales — the distributor's own book, sent by the distributor
# --------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@endpoint()
def upload_secondary_sales(from_date: str, to_date: str, content: str,
                           file_name: str | None = None):
	"""A depot sends its own sales file.

	Until now there was no way for them to. The reader, the per-distributor column mapping and
	the bad-row tolerance have all existed since Phase 5 and were reachable only from Desk, so a
	distributor emailed a file and somebody at this end imported it - which is a step that gets
	skipped in a busy week, and the data that depends on it simply stops arriving.

	**The distributor is taken from the session, never from the payload.** A depot sending a file
	for somebody else's sales is the one thing this endpoint must not allow, and the only way to
	be sure is not to accept the name at all.

	Posting nothing is unchanged (ADR-023): these are the distributor's sales, and FieldMate is
	recording them, not billing them.
	"""
	row = _session()
	portal_service.may(row, "secondary_sales")
	return ok(secondary_sales_service.import_file(
		row.distributor, content, from_date, to_date, file_name=file_name,
	))


@frappe.whitelist()
@endpoint()
def secondary_sales_template():
	"""The column names this reader understands, so a depot does not have to guess the header."""
	_session()
	return ok(secondary_sales_service.template())


@frappe.whitelist(methods=["POST"])
@endpoint()
def raise_claim(from_date: str, to_date: str, scheme: str | None = None,
                reference_no: str | None = None, remarks: str | None = None,
                submit: int = 1):
	row = _session()
	portal_service.may(row, "claim")
	name = claim_service.build(row.distributor, from_date, to_date, scheme=scheme,
	                           reference_no=reference_no, remarks=remarks)
	if frappe.utils.cint(submit):
		return ok(claim_service.submit_claim(name))
	return ok(claim_service.summarise(name))
