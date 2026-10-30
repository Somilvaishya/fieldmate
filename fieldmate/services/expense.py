"""What a rep spent getting through the day, and who agrees to pay it.

One rule, stated once: **the distance is the server's, the claim is the rep's, and the gap is
the manager's.** The controller holds it; this module is what the phone and the Desk call to
create, approve and settle.

A settled claim is the fourth and last crossing into somebody else's books - an HRMS Expense
Claim, and only on approval. It is the only one of the four that pays a person rather than a
party (ADR-028).
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, get_first_day, get_last_day, now_datetime, nowdate

from fieldmate import compat
from fieldmate.services import field_user as field_user_service
from fieldmate.services import paging
from fieldmate.services import settings as settings_service
from fieldmate.services import trail as trail_service


def estimate(field_user: str | None = None, claim_date=None,
             expense_type: str = "Travel") -> dict:
    """What the rep would get, before they file anything.

    This is what fills the screen: the distance the trail recorded, the rate, and the figure
    that falls out. Nothing is created, so a rep can look at it as often as they like.
    """
    field_user = field_user or field_user_service.for_user()
    claim_date = claim_date or nowdate()

    if expense_type == "Travel":
        measured = trail_service.measure(field_user, claim_date)
        distance = flt(measured["km"], 2)
        trail = frappe.db.get_value(
            "FieldMate Location Trail",
            {"field_user": field_user, "trail_date": claim_date},
            ["ping_count", "day"], as_dict=True)
        rate = flt(settings_service.value("travel_rate_per_km"))
        visits = frappe.db.count("FieldMate Visit", {
            "field_user": field_user, "visit_date": claim_date, "docstatus": 1})
        return {
            "expense_type": "Travel",
            "claim_date": str(claim_date),
            "trail_distance_km": distance,
            "claimed_distance_km": distance,
            "trail_ping_count": cint(trail.ping_count) if trail else 0,
            # "trail", "route", or nothing measured at all. The screen says which, because a
            # route figure badged as a GPS trail is a sentence the rep cannot act on.
            "distance_basis": measured["basis"],
            "check_ins": visits,
            "rate_per_km": rate,
            "amount": flt(distance * rate, 2) if rate else 0,
            "rate_is_set": bool(rate),
            "tolerance_pct": flt(settings_service.value("expense_distance_tolerance_pct")),
            "receipt_required_above": flt(
                settings_service.value("expense_receipt_required_above")),
            "already_claimed": _already_claimed(field_user, claim_date, "Travel"),
        }

    cap = flt(settings_service.value(
        {"Food": "daily_food_allowance", "Stay": "daily_stay_allowance"}.get(expense_type, "")))
    return {
        "expense_type": expense_type,
        "claim_date": str(claim_date),
        "amount": cap,
        "allowance_cap": cap,
        "receipt_required_above": flt(settings_service.value("expense_receipt_required_above")),
        "already_claimed": _already_claimed(field_user, claim_date, expense_type),
    }


def _already_claimed(field_user: str, claim_date, expense_type: str) -> str | None:
    """One claim of a type per rep per day. The second is a mistake, not a second journey."""
    return frappe.db.get_value("FieldMate Expense Claim", {
        "field_user": field_user, "claim_date": claim_date,
        "expense_type": expense_type, "docstatus": ["<", 2],
    }, "name")


def create(payload: dict, field_user: str | None = None) -> dict:
    """File a claim. Idempotent on the device's own uuid, like everything else a phone creates."""
    payload = dict(payload or {})
    field_user = field_user or field_user_service.for_user()
    if not field_user:
        frappe.throw(frappe._("You are not set up as a field user."), frappe.PermissionError)

    uuid = payload.get("client_uuid")
    if uuid:
        existing = frappe.db.get_value("FieldMate Expense Claim", {"client_uuid": uuid}, "name")
        if existing:
            return summarise(existing)

    claim_date = payload.get("claim_date") or nowdate()
    expense_type = payload.get("expense_type") or "Travel"

    duplicate = _already_claimed(field_user, claim_date, expense_type)
    if duplicate:
        frappe.throw(
            frappe._("You have already filed a {0} claim for {1} ({2}).")
            .format(expense_type.lower(), claim_date, duplicate))

    doc = frappe.new_doc("FieldMate Expense Claim")
    doc.field_user = field_user
    doc.claim_date = claim_date
    doc.expense_type = expense_type
    doc.claimed_distance_km = flt(payload.get("claimed_distance_km"))
    doc.claimed_amount = flt(payload.get("claimed_amount"))
    doc.remarks = payload.get("remarks")
    doc.receipt = payload.get("receipt")
    doc.client_uuid = uuid
    doc.created_offline = cint(payload.get("created_offline"))
    doc.device_id = payload.get("device_id")

    # A rep holds create and submit-if-owner and never write (ADR-004). The insert is theirs;
    # everything the document computes about them is the server's.
    doc.flags.ignore_permissions = True
    doc.insert()
    return summarise(doc)


def submit_claim(name: str, field_user: str | None = None) -> dict:
    doc = frappe.get_doc("FieldMate Expense Claim", name)
    assert_owner(doc, field_user)
    if doc.docstatus != 0:
        return summarise(doc)
    doc.flags.ignore_permissions = True
    doc.submit()
    return summarise(doc.reload() or doc)


def assert_owner(doc, field_user: str | None = None) -> None:
    if doc.field_user == (field_user or field_user_service.for_user()):
        return
    frappe.throw(frappe._("That claim belongs to another rep."), frappe.PermissionError)


# --------------------------------------------------------------------------------------
# approval and settlement
# --------------------------------------------------------------------------------------


def approve(name: str, decision: str, approved_amount=None, remarks: str | None = None,
            settle: bool = True) -> dict:
    """Agree, or refuse and say why."""
    doc = frappe.get_doc("FieldMate Expense Claim", name)
    if doc.docstatus != 1:
        frappe.throw(frappe._("Submit the claim before deciding on it."))
    if doc.claim_status not in ("Pending Approval", "Approved"):
        frappe.throw(
            frappe._("This claim is {0} and is no longer waiting on a decision.")
            .format(doc.claim_status.lower()))
    if doc.field_user == field_user_service.for_user():
        # The whole point of the excess rule. A rep filing over the trail and then approving it
        # is the same as a rep stating their own mileage.
        frappe.throw(
            frappe._("You cannot approve your own claim."), frappe.PermissionError)
    # Somebody else's team is not yours to pay. This used to stop only at the claimant's own
    # name, so any Area Manager could approve any rep's mileage anywhere in the company - hidden
    # while managers worked in Desk lists filtered by territory, and in plain view once the app
    # shows a manager a queue.
    field_user_service.assert_in_team(doc.field_user)

    if decision == "Rejected":
        if not remarks:
            frappe.throw(frappe._("Say why. A rejected expense with no reason is a grievance."))
        doc.db_set("claim_status", "Rejected", update_modified=False)
        doc.db_set("rejection_reason", remarks, update_modified=False)
        doc.db_set("approved_amount", 0, update_modified=False)
    elif decision == "Approved":
        amount = flt(approved_amount) if approved_amount is not None else flt(doc.claimed_amount)
        if amount <= 0:
            frappe.throw(frappe._("An approved claim has to be worth something."))
        if amount > flt(doc.claimed_amount) + 0.005:
            frappe.throw(
                frappe._("You cannot approve {0} against a claim for {1}.")
                .format(amount, doc.claimed_amount))
        doc.db_set("approved_amount", amount, update_modified=False)
        doc.db_set("claim_status", "Approved", update_modified=False)
    else:
        frappe.throw(frappe._("A claim is either Approved or Rejected."))

    doc.db_set("approved_by", frappe.session.user, update_modified=False)
    doc.db_set("approved_on", now_datetime(), update_modified=False)

    if decision == "Approved" and settle:
        return settle_claim(doc.name)
    return summarise(doc.reload() or doc)


def settle_claim(name: str) -> dict:
    """Raise the HRMS Expense Claim, where that app is installed.

    Where it is not, the claim is marked settled with no document behind it and says so. A site
    running FieldMate before HRMS still has reps owed money, and refusing to record that they
    were paid would be worse than recording it plainly.
    """
    doc = frappe.get_doc("FieldMate Expense Claim", name)
    # Already settled is the ordinary state after a retried click, not an error. Checked before
    # the status guard, because by then the status IS "Settled" and the guard would refuse the
    # one call that has to be free. Tested on `claim_status`, not on the HR document: where
    # HRMS is absent or the rep has no Employee there is no document, and the claim is settled
    # all the same.
    if doc.claim_status == "Settled":
        return summarise(doc)
    if doc.claim_status != "Approved":
        frappe.throw(
            frappe._("Only an approved claim can be settled. This one is {0}.")
            .format(doc.claim_status.lower()))

    posted = compat.make_expense_claim({
        "key": f"EXPENSE:{doc.name}",
        "employee": doc.employee,
        "company": doc.company,
        "posting_date": doc.claim_date,
        "expense_type": doc.expense_type,
        "amount": flt(doc.approved_amount),
        "description": _describe(doc),
    })

    if posted:
        doc.db_set("hrms_expense_claim", posted, update_modified=False)
    doc.db_set("settled_on", nowdate(), update_modified=False)
    doc.db_set("claim_status", "Settled", update_modified=False)
    return summarise(doc.reload() or doc)


def _describe(doc) -> str:
    if doc.expense_type == "Travel":
        return (f"FieldMate travel claim {doc.name}: {flt(doc.claimed_distance_km):g} km on "
                f"{doc.claim_date} at {flt(doc.rate_per_km):,.2f}/km"
                + (f". {doc.remarks}" if doc.remarks else ""))
    return (f"FieldMate {doc.expense_type.lower()} claim {doc.name} for {doc.claim_date}"
            + (f". {doc.remarks}" if doc.remarks else ""))


def reverse(name: str) -> dict:
    """Undo a settlement: cancel the HR document, then release the link.

    The same order as every other reversal in this app, and for the same reason - Frappe checks
    back-links before it runs on_cancel.
    """
    doc = frappe.get_doc("FieldMate Expense Claim", name)
    posted = doc.hrms_expense_claim
    if posted:
        doc.db_set("hrms_expense_claim", None, update_modified=False)
        compat.cancel_expense_claim(posted)
    doc.db_set("settled_on", None, update_modified=False)
    doc.db_set("claim_status", "Approved", update_modified=False)
    return summarise(doc.reload() or doc)


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------


def mine(field_user: str | None = None, limit: int = 30, start: int = 0) -> dict:
    field_user = field_user or field_user_service.for_user()
    claims, total = paging.page(
        "FieldMate Expense Claim",
        fields=["name", "claim_date", "expense_type", "claimed_distance_km",
                "trail_distance_km", "claimed_amount", "approved_amount", "claim_status",
                "needs_approval", "approval_reason", "rejection_reason", "remarks", "docstatus"],
        filters={"field_user": field_user, "docstatus": ["<", 2]},
        order_by="claim_date desc, creation desc",
        start=start, limit=limit,
    )

    today = nowdate()
    month = today[:7]

    # Summed over the rep's claims, not over the page.
    #
    # These were folded out of `claims` while `claims` was "the last thirty" - already an
    # approximation, and one that became plainly wrong the moment the list started paging: a rep
    # on page two would have been shown a month's total made of the second page only. A figure a
    # rep is answerable for has to count everything it claims to count.
    # A range, not a `like`. `claim_date` is a Date column, and Frappe parses the right-hand
    # side of a filter against the column's own type - so "2026-10%" went to the date parser
    # and raised there rather than matching anything.
    approved = frappe.get_all(
        "FieldMate Expense Claim",
        filters={"field_user": field_user, "docstatus": ["<", 2],
                 "claim_status": ["in", ["Approved", "Settled"]],
                 "claim_date": ["between", [get_first_day(today), get_last_day(today)]]},
        fields=["sum(approved_amount) as total"],
    )
    pending = frappe.get_all(
        "FieldMate Expense Claim",
        filters={"field_user": field_user, "docstatus": ["<", 2],
                 "claim_status": "Pending Approval"},
        fields=["sum(claimed_amount) as total"],
    )

    return {
        "claims": claims,
        "total": total,
        "month": month,
        "approved_this_month": flt(approved[0].total if approved else 0, 2),
        "awaiting_decision": flt(pending[0].total if pending else 0, 2),
    }


PENDING_FIELDS = ["name", "field_user", "claim_date", "expense_type", "trail_distance_km",
                  "claimed_distance_km", "distance_variance_km", "distance_variance_pct",
                  "trail_ping_count", "claimed_amount", "computed_amount", "approval_reason",
                  "receipt", "remarks"]


def pending_for_manager_page(limit: int = 100, start: int = 0,
                             user: str | None = None) -> tuple[list[dict], int]:
    """A page of what is waiting on this manager, oldest first, and how much there is.

    Their own team's, not the company's - the same line `approve` now holds.
    """
    filters = {"claim_status": "Pending Approval", "docstatus": 1}
    scope = field_user_service.team_scope(user)
    if scope is not None:
        if not scope:
            return [], 0
        filters["field_user"] = ["in", scope]
    return paging.page("FieldMate Expense Claim", fields=PENDING_FIELDS, filters=filters,
                       order_by="claim_date asc", start=start, limit=limit)


def pending_for_manager(limit: int = 100) -> list[dict]:
    rows, _ = pending_for_manager_page(limit)
    return rows


def summarise(doc) -> dict:
    if isinstance(doc, str):
        doc = frappe.get_doc("FieldMate Expense Claim", doc)
    return {
        "name": doc.name,
        "client_uuid": doc.client_uuid,
        "field_user": doc.field_user,
        "claim_date": str(doc.claim_date),
        "expense_type": doc.expense_type,
        "claim_status": doc.claim_status,
        "docstatus": cint(doc.docstatus),
        "trail_distance_km": flt(doc.trail_distance_km),
        "claimed_distance_km": flt(doc.claimed_distance_km),
        "distance_variance_km": flt(doc.distance_variance_km),
        "distance_variance_pct": flt(doc.distance_variance_pct),
        "trail_ping_count": cint(doc.trail_ping_count),
        "rate_per_km": flt(doc.rate_per_km),
        "computed_amount": flt(doc.computed_amount),
        "claimed_amount": flt(doc.claimed_amount),
        "approved_amount": flt(doc.approved_amount),
        "allowance_cap": flt(doc.allowance_cap),
        "needs_approval": bool(doc.needs_approval),
        "approval_reason": doc.approval_reason,
        "rejection_reason": doc.rejection_reason,
        "receipt": doc.receipt,
        "receipt_required": bool(doc.receipt_required),
        "remarks": doc.remarks,
        "hrms_expense_claim": doc.hrms_expense_claim,
        "settled_on": str(doc.settled_on) if doc.settled_on else None,
    }
