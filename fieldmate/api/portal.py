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
from fieldmate.services import portal as portal_service


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
	profile = frappe.db.get_value(
		"FieldMate Distributor Profile", row.distributor,
		["distributor_code", "customer", "territory", "credit_days", "delivery_days"],
		as_dict=True) or {}
	return ok({
		"user": row.user,
		"full_name": frappe.db.get_value("User", row.user, "full_name"),
		"distributor": row.distributor,
		"distributor_name": frappe.db.get_value("Customer", profile.get("customer"),
		                                        "customer_name") or row.distributor,
		"designation": row.designation,
		"can_accept_orders": bool(row.can_accept_orders),
		"can_raise_claims": bool(row.can_raise_claims),
		**profile,
	})


# --------------------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def distributor_orders(status: str | None = None, search: str | None = None, limit: int = 100):
	row = _session()
	return ok({
		"orders": portal_service.orders(status=status, search=search, limit=int(limit), row=row),
		"totals": portal_service.queue_totals(row=row),
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
