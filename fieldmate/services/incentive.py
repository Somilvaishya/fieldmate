"""Incentives: which slab a rep landed in, and what that is worth.

Gate 7 criterion 3 asks that three reps match a hand-built spreadsheet to the rupee. That is a
statement about arithmetic, so the arithmetic is here, in one pure-ish function, in integer
paise - the same rule the scheme engine works under (ADR-022). A percentage of a rupee figure
computed in floats and rounded at the end differs from the spreadsheet in the third case out of
ten, and the third case is always somebody's salary.

The order of operations is fixed and is part of the contract:

    1. qualify   - below the qualifying percentage, nothing is earned, whatever the slabs say
    2. slab      - inclusive at the bottom, exclusive at the top, open ended at the end
    3. earn      - a flat amount, or a percentage of the ACTUAL value, never of the target
    4. cap       - applied last, and what it took off is recorded rather than absorbed

Swapping 3 and 4 - capping the rate instead of the result - is the mistake that looks identical
on a good month.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from fieldmate.services import scope as scope_service
from fieldmate.services import target as target_service


def to_paise(rupees) -> int:
	"""The one place rupees become integers. Floor of (x*100 + 0.5), never round().

	Python's `round()` is banker's: it sends 2.5 to 2 and 3.5 to 4. On a payout table that is a
	rupee here and a rupee there, in a direction nobody can predict, against a spreadsheet that
	rounds half up like every spreadsheet does.
	"""
	return int(flt(rupees) * 100 + 0.5)


def in_rupees(paise: int) -> float:
	return round(paise / 100, 2)


def round_half_up_div(numerator: int, denominator: int) -> int:
	"""floor((2n + d) / 2d) — half up, in integers, for positive denominators."""
	if denominator == 0:
		return 0
	return (2 * numerator + denominator) // (2 * denominator)


# --------------------------------------------------------------------------------------
# the arithmetic
# --------------------------------------------------------------------------------------


def award(scheme, achievement_pct, actual_value) -> dict:
	"""What this scheme pays for this achievement. No database, no clock, no document saved.

	Returns the working as well as the figure, because the fastest way to settle a disagreement
	with a spreadsheet is to read what the machine thought it was doing.
	"""
	pct = flt(achievement_pct)
	qualifying = flt(scheme.qualifying_pct)

	if pct < qualifying:
		return {
			"qualified": False, "slab": None, "slab_idx": 0, "slab_label": None,
			"payout_kind": None, "gross_paise": 0, "capped_paise": 0, "payout_paise": 0,
			"working": f"{pct:g}% is below the qualifying {qualifying:g}%. Nothing earned.",
		}

	slab = scheme.slab_for(pct)
	if not slab:
		return {
			"qualified": True, "slab": None, "slab_idx": 0, "slab_label": None,
			"payout_kind": None, "gross_paise": 0, "capped_paise": 0, "payout_paise": 0,
			"working": f"{pct:g}% qualified but landed in no slab.",
		}

	if slab.payout_kind == "Percent Of Value":
		# Of what was actually sold, never of the target. A percentage of the target pays a rep
		# at 81% exactly what it pays one at 119%.
		base = to_paise(actual_value)
		gross = round_half_up_div(base * to_paise(slab.payout_pct), 100 * 100)
		how = (f"{flt(slab.payout_pct):g}% of {in_rupees(base):,.2f} actual "
		       f"= {in_rupees(gross):,.2f}")
	else:
		gross = to_paise(slab.payout_amount)
		how = f"flat {in_rupees(gross):,.2f} for the slab"

	cap = to_paise(scheme.cap_amount)
	if cap and gross > cap:
		cut = gross - cap
		payout = cap
		how += f", capped at {in_rupees(cap):,.2f} (cut {in_rupees(cut):,.2f})"
	else:
		cut = 0
		payout = gross

	label = slab.label or f"Slab {slab.slab_idx}"
	working = (f"{pct:g}% achieved lands in {label} "
	           f"({flt(slab.from_pct):g}%"
	           + ("+" if cint(slab.is_open_ended) else f"-{flt(slab.to_pct):g}%")
	           + f"): {how}.")

	return {
		"qualified": True, "slab": slab, "slab_idx": cint(slab.slab_idx), "slab_label": label,
		"payout_kind": slab.payout_kind, "gross_paise": gross, "capped_paise": cut,
		"payout_paise": payout, "working": working,
	}


def next_slab(scheme, achievement_pct) -> dict | None:
	"""The rung above, for the line on the rep's screen that says what the next one is worth."""
	pct = flt(achievement_pct)
	for row in scheme.slabs or []:
		if flt(row.from_pct) > pct:
			return {
				"label": row.label or f"Slab {row.slab_idx}",
				"from_pct": flt(row.from_pct),
				"payout_kind": row.payout_kind,
				"payout_amount": flt(row.payout_amount),
				"payout_pct": flt(row.payout_pct),
				"gap_pct": round(flt(row.from_pct) - pct, 2),
			}
	return None


# --------------------------------------------------------------------------------------
# which schemes apply
# --------------------------------------------------------------------------------------


def schemes_for(field_user: str, on_date=None) -> list:
	"""Every live scheme this rep is inside, cheapest filters first."""
	on_date = getdate(on_date or nowdate())
	rep = frappe.db.get_value("FieldMate Field User", field_user,
	                          ["designation", "territory", "sales_person", "company"],
	                          as_dict=True)
	if not rep:
		return []

	candidates = frappe.get_all(
		"FieldMate Incentive Scheme",
		filters={"is_active": 1, "docstatus": 1, "valid_from": ["<=", on_date]},
		fields=["name", "priority"],
		order_by="priority asc, name asc",
		limit_page_length=0,
	)

	live = []
	for row in candidates:
		scheme = frappe.get_doc("FieldMate Incentive Scheme", row.name)
		if scheme.valid_to and getdate(scheme.valid_to) < on_date:
			continue
		if scheme.company and rep.company and scheme.company != rep.company:
			continue
		if scheme.designation and scheme.designation != rep.designation:
			continue
		# Territory is a tree, and a scheme set on North must reach a rep in North / Delhi.
		# `scope.territory_covers` is the one place that comparison lives.
		if not scope_service.territory_covers(scheme.territory, rep.territory):
			continue
		if scheme.sales_person and not _under(rep.sales_person, scheme.sales_person):
			continue
		live.append(scheme)
	return live


def _under(node: str | None, ancestor: str) -> bool:
	if not node:
		return False
	if node == ancestor:
		return True
	seen = set()
	while node and node not in seen:
		seen.add(node)
		node = frappe.db.get_value("Sales Person", node, "parent_sales_person")
		if node == ancestor:
			return True
	return False


# --------------------------------------------------------------------------------------
# computing payouts
# --------------------------------------------------------------------------------------


def _achievement_line(achievement, measured_on: str, item_group=None, brand=None):
	# The scheme's side gets the same treatment the achievement row already had: a blank category
	# that Frappe filled with the root is not a narrower scheme, and matching the two literally
	# left a scheme skipped for want of a target that was sitting right there.
	# Both sides, because the row cannot be trusted to have kept the blank either: writing None
	# into a Link field only invites the same default back on the next save.
	item_group = target_service.narrowing(item_group)
	for row in achievement.lines:
		if (row.target_type == measured_on
		        and target_service.narrowing(row.item_group) == item_group
		        and (row.brand or None) == (brand or None)):
			return row
	return None


def compute_for(field_user: str, plan_name: str, dry_run: bool = False) -> list[dict]:
	"""Every payout this rep earned on this plan. Idempotent per rep, scheme and period."""
	plan = frappe.get_doc("FieldMate Target Plan", plan_name)
	achievement_name = frappe.db.get_value("FieldMate Achievement",
	                                       {"target_plan": plan.name}, "name")
	if not achievement_name:
		frappe.throw(
			frappe._("{0} has not been measured yet, so there is nothing to pay on.")
			.format(plan.name))
	achievement = frappe.get_doc("FieldMate Achievement", achievement_name)

	results = []
	for scheme in schemes_for(field_user, plan.to_date):
		line = _achievement_line(achievement, scheme.measured_on,
		                         scheme.item_group, scheme.brand)
		if not line:
			# The scheme pays on something this rep was never given a target for. Skipped and
			# said out loud, rather than paid at zero - the two look identical on a report and
			# only one of them is somebody forgetting to set a target.
			results.append({
				"scheme": scheme.name, "skipped": True,
				"reason": f"no {scheme.measured_on} target on {plan.name}",
			})
			continue

		outcome = award(scheme, line.achievement_pct, line.actual_value)
		payload = {
			"scheme": scheme.name,
			"skipped": False,
			"measured_on": scheme.measured_on,
			"item_group": scheme.item_group,
			"target_value": flt(line.target_value),
			"actual_value": flt(line.actual_value),
			"achievement_pct": flt(line.achievement_pct),
			"slab_idx": outcome["slab_idx"],
			"slab_label": outcome["slab_label"],
			"payout_kind": outcome["payout_kind"],
			"gross_amount": in_rupees(outcome["gross_paise"]),
			"capped_amount": in_rupees(outcome["capped_paise"]),
			"payout_amount": in_rupees(outcome["payout_paise"]),
			"working": outcome["working"],
		}
		if not dry_run:
			payload["payout"] = _upsert_payout(plan, achievement, field_user, scheme, payload)
		results.append(payload)

	return results


def _upsert_payout(plan, achievement, field_user: str, scheme, payload: dict) -> str:
	existing = frappe.db.get_value("FieldMate Incentive Payout", {
		"field_user": field_user, "scheme": scheme.name,
		"from_date": plan.from_date, "to_date": plan.to_date,
		"docstatus": ["<", 2],
	}, ["name", "docstatus", "payout_status"], as_dict=True)

	if existing:
		if existing.docstatus == 1:
			# A submitted payout is a decision already taken. Recomputing must not quietly
			# change what somebody was told they had earned; it says so and leaves it alone.
			return existing.name
		doc = frappe.get_doc("FieldMate Incentive Payout", existing.name)
	else:
		doc = frappe.new_doc("FieldMate Incentive Payout")

	doc.field_user = field_user
	doc.scheme = scheme.name
	doc.company = plan.company
	doc.from_date = plan.from_date
	doc.to_date = plan.to_date
	doc.target_plan = plan.name
	doc.achievement = achievement.name
	doc.measured_on = payload["measured_on"]
	doc.item_group = payload["item_group"]
	doc.target_value = payload["target_value"]
	doc.actual_value = payload["actual_value"]
	doc.achievement_pct = payload["achievement_pct"]
	doc.slab_idx = payload["slab_idx"]
	doc.slab_label = payload["slab_label"]
	doc.payout_kind = payload["payout_kind"]
	doc.gross_amount = payload["gross_amount"]
	doc.capped_amount = payload["capped_amount"]
	doc.payout_amount = payload["payout_amount"]
	doc.working = payload["working"]
	doc.payout_status = "Draft"

	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def compute_period(from_date, to_date, dry_run: bool = False) -> dict:
	"""Every rep with a leaf plan in this period. The month-end run."""
	plans = frappe.get_all(
		"FieldMate Target Plan",
		filters={"docstatus": 1, "from_date": from_date, "to_date": to_date,
		         "field_user": ["is", "set"]},
		fields=["name", "field_user"],
		order_by="name asc",
		limit_page_length=0,
	)

	made, skipped, failed = 0, 0, []
	for plan in plans:
		try:
			for result in compute_for(plan.field_user, plan.name, dry_run=dry_run):
				if result.get("skipped"):
					skipped += 1
				elif result.get("payout") or dry_run:
					made += 1
		except Exception:
			frappe.log_error(title=f"fieldmate incentive.compute_for {plan.name}")
			failed.append(plan.name)
		if not dry_run:
			frappe.db.commit()

	return {"plans": len(plans), "payouts": made, "skipped": skipped, "failed": failed}


def approve(name: str, decision: str, remarks: str | None = None) -> dict:
	doc = frappe.get_doc("FieldMate Incentive Payout", name)
	if doc.docstatus != 1:
		frappe.throw(frappe._("Submit the payout before deciding on it."))
	if doc.payout_status not in ("Pending Approval", "Approved"):
		frappe.throw(
			frappe._("This payout is {0} and is no longer waiting on a decision.")
			.format(doc.payout_status.lower()))

	if decision == "Rejected":
		if not remarks:
			frappe.throw(frappe._("Say why. A rejected incentive with no reason is a grievance."))
		doc.db_set("payout_status", "Rejected", update_modified=False)
		doc.db_set("remarks", remarks, update_modified=False)
	elif decision == "Approved":
		doc.db_set("payout_status", "Approved", update_modified=False)
		if remarks:
			doc.db_set("remarks", remarks, update_modified=False)
	else:
		frappe.throw(frappe._("A payout is either Approved or Rejected."))

	doc.db_set("approved_by", frappe.session.user, update_modified=False)
	doc.db_set("approved_on", now_datetime(), update_modified=False)
	return summarise(doc.reload() or doc)


def mark_paid(name: str, reference: str, paid_on=None) -> dict:
	doc = frappe.get_doc("FieldMate Incentive Payout", name)
	if doc.payout_status != "Approved":
		frappe.throw(
			frappe._("Only an approved payout can be marked paid. This one is {0}.")
			.format(doc.payout_status.lower()))
	if not reference:
		frappe.throw(
			frappe._("Record where it was paid. FieldMate does not pay anybody; it says what "
			         "is owed and records where the payment happened."))
	doc.db_set("payout_status", "Paid", update_modified=False)
	doc.db_set("paid_on", paid_on or nowdate(), update_modified=False)
	doc.db_set("payment_reference", reference, update_modified=False)
	return summarise(doc.reload() or doc)


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------


def mine(field_user: str | None = None, limit: int = 12) -> list[dict]:
	from fieldmate.services import field_user as field_user_service

	field_user = field_user or field_user_service.for_user()
	return frappe.get_all(
		"FieldMate Incentive Payout",
		filters={"field_user": field_user, "docstatus": ["<", 2]},
		fields=["name", "scheme", "from_date", "to_date", "measured_on", "achievement_pct",
		        "slab_label", "payout_amount", "payout_status", "paid_on", "working"],
		order_by="from_date desc, creation desc",
		limit_page_length=limit,
	)


def on_track(field_user: str | None = None, as_on=None) -> dict:
	"""What this month looks like worth so far, and what the next rung pays.

	Deliberately not a promise, and the wording on the screen says so. It is computed from a
	snapshot that will move again tonight.
	"""
	from fieldmate.services import field_user as field_user_service
	from fieldmate.services import target as target_service

	field_user = field_user or field_user_service.for_user()
	standing = target_service.mine(field_user, as_on=as_on)
	if not standing.get("has_target"):
		return {"has_target": False, "schemes": []}

	plan = frappe.get_doc("FieldMate Target Plan", standing["plan"])
	achievement_name = frappe.db.get_value("FieldMate Achievement",
	                                       {"target_plan": plan.name}, "name")
	if not achievement_name:
		return {"has_target": True, "measured": False, "schemes": []}
	achievement = frappe.get_doc("FieldMate Achievement", achievement_name)

	entries, total = [], 0
	for scheme in schemes_for(field_user, plan.to_date):
		line = _achievement_line(achievement, scheme.measured_on,
		                         scheme.item_group, scheme.brand)
		if not line:
			continue
		outcome = award(scheme, line.achievement_pct, line.actual_value)
		total += outcome["payout_paise"]
		entries.append({
			"scheme": scheme.name,
			"description": scheme.description,
			"measured_on": scheme.measured_on,
			"achievement_pct": flt(line.achievement_pct),
			"slab_label": outcome["slab_label"],
			"amount": in_rupees(outcome["payout_paise"]),
			"working": outcome["working"],
			"next": next_slab(scheme, line.achievement_pct),
		})

	return {
		"has_target": True,
		"measured": True,
		"as_on": standing["as_on"],
		"computed_on": standing["computed_on"],
		"total": in_rupees(total),
		"schemes": entries,
	}


def summarise(doc) -> dict:
	if isinstance(doc, str):
		doc = frappe.get_doc("FieldMate Incentive Payout", doc)
	return {
		"name": doc.name,
		"field_user": doc.field_user,
		"scheme": doc.scheme,
		"from_date": str(doc.from_date),
		"to_date": str(doc.to_date),
		"measured_on": doc.measured_on,
		"target_value": flt(doc.target_value),
		"actual_value": flt(doc.actual_value),
		"achievement_pct": flt(doc.achievement_pct),
		"slab_label": doc.slab_label,
		"gross_amount": flt(doc.gross_amount),
		"capped_amount": flt(doc.capped_amount),
		"payout_amount": flt(doc.payout_amount),
		"payout_status": doc.payout_status,
		"paid_on": str(doc.paid_on) if doc.paid_on else None,
		"payment_reference": doc.payment_reference,
		"working": doc.working,
	}
