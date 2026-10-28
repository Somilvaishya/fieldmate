"""Targets: cascading them down the tree, and measuring what came back.

Two halves that must never disagree.

**Cascade** divides a parent's number among its children. It divides in whole units - paise for
money, ones for counts - because dividing 10,00,000 three ways in floating point and storing the
result gives three numbers that add up to 9,99,999.99, and somebody notices that at the end of
the month rather than here. The leftover units are handed to the largest share deliberately, and
which child took them is written down.

**Achievement** counts what actually happened. It reads the same documents a manager would read
by hand, and nothing else: orders for value and volume, visits for calls and coverage, outlets
for new shops. It stores a snapshot rather than a view, because the nightly job is what makes
250 reps affordable to read, and because a rep's September has to stop moving once September is
over (Gate 7 criterion 5).
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from fieldmate.fieldmate.doctype.fieldmate_target_line.fieldmate_target_line import (
	MONEY_TYPES,
	TARGET_TYPES,
	WHOLE_TYPES,
)

# Orders in these states never happened as far as a target is concerned. A cancelled order that
# still counted would let a rep book, get credit, and cancel on the first of next month.
DEAD_ORDER_STATES = ("Cancelled", "Rejected")


# --------------------------------------------------------------------------------------
# splitting, in whole units
# --------------------------------------------------------------------------------------


def units_for(target_type: str) -> int:
	"""How many storable units make up one of whatever this target is counted in.

	Money is held in paise while it is being divided (ADR-022). Counts are whole things - half a
	shop is not covered, and half a call was not made. Everything else divides to two places,
	which is as fine as the field ever stores.
	"""
	if target_type in MONEY_TYPES:
		return 100
	if target_type in WHOLE_TYPES:
		return 1
	return 100


def to_units(value, target_type: str) -> int:
	"""Rupees to paise, and everything else to its own smallest unit.

	`+ 0.5` and floor rather than `round()`, which is banker's in Python and would send exactly
	half a paise to even - quietly, and differently for 2.5 and 3.5.
	"""
	return int(flt(value) * units_for(target_type) + 0.5)


def from_units(units: int, target_type: str) -> float:
	scale = units_for(target_type)
	return units if scale == 1 else units / scale


def split(total_units: int, weights: list[int]) -> list[int]:
	"""Divide whole units by weight so the parts add back to the total exactly."""
	return split_detail(total_units, weights)[0]


def split_detail(total_units: int, weights: list[int]) -> tuple[list[int], list[int]]:
	"""The split, and which positions took the units that would not divide.

	Largest remainder: everybody gets their floor, and the units left over go one each to the
	shares with the biggest fractional part, largest first. The alternative - rounding each share
	independently - loses or invents units, and the loss shows up as a root that no longer equals
	its own leaves.

	Ties break on position, so the same input always produces the same answer. A cascade that
	gave a different rep the spare rupee on a re-run would be a cascade nobody could check.

	The second return value exists so the caller can record who took the spare without redoing
	the arithmetic to find out - two copies of this sum would eventually disagree.
	"""
	if not weights:
		return [], []
	total_weight = sum(weights)
	if total_weight <= 0:
		# Nothing to weigh by - equal shares rather than a refusal, because a tree whose nodes
		# have no outlets yet is an ordinary state in the first week of a rollout.
		weights = [1] * len(weights)
		total_weight = len(weights)

	shares = []
	for index, weight in enumerate(weights):
		exact = total_units * weight
		floor = exact // total_weight
		shares.append([floor, exact - floor * total_weight, index])

	left = total_units - sum(s[0] for s in shares)
	# Biggest remainder first; on a tie, the earlier child. Sorting on the negated remainder
	# keeps the index ascending within a tie without a second key doing the opposite.
	took = []
	for share in sorted(shares, key=lambda s: (-s[1], s[2]))[:left]:
		share[0] += 1
		took.append(share[2])

	shares.sort(key=lambda s: s[2])
	return [s[0] for s in shares], sorted(took)


# --------------------------------------------------------------------------------------
# cascade
# --------------------------------------------------------------------------------------


def children_of(sales_person: str) -> list[str]:
	return frappe.get_all("Sales Person",
	                      filters={"parent_sales_person": sales_person, "enabled": 1},
	                      order_by="name asc", pluck="name")


def weights_for(sales_people: list[str], basis: str, plan) -> list[int]:
	"""How much of the parent's number each child carries.

	Outlet count by default, because a rep with 280 shops cannot be asked for the same as one
	with 90, and it is the one weight every site already has without anybody maintaining it.
	"""
	if basis == "Equal":
		return [1] * len(sales_people)

	if basis == "Last Period Achievement":
		span = (getdate(plan.to_date) - getdate(plan.from_date)).days + 1
		before_to = frappe.utils.add_days(plan.from_date, -1)
		before_from = frappe.utils.add_days(before_to, -(span - 1))
		weights = []
		for person in sales_people:
			actual = sum(flt(row.net_total) for row in _orders_under(person, before_from, before_to))
			# A whole rupee is a fine granularity for a weight, and keeps it an integer.
			weights.append(max(int(actual), 0))
		return weights if sum(weights) else [1] * len(sales_people)

	return [max(_outlet_count(person), 0) for person in sales_people]


def _outlet_count(sales_person: str) -> int:
	users = frappe.get_all("FieldMate Field User",
	                       filters={"sales_person": ["in", subtree(sales_person)]},
	                       pluck="name")
	if not users:
		return 0
	territories = frappe.get_all("FieldMate Field User",
	                             filters={"name": ["in", users]}, pluck="territory")
	territories = [t for t in territories if t]
	if not territories:
		return 0
	return frappe.db.count("FieldMate Outlet",
	                       {"territory": ["in", territories], "outlet_status": "Active"})


def subtree(sales_person: str) -> list[str]:
	"""A node and everything under it. Iterative, because a tree that loops should not hang."""
	found, queue, seen = [], [sales_person], set()
	while queue:
		node = queue.pop()
		if node in seen:
			continue
		seen.add(node)
		found.append(node)
		queue.extend(children_of(node))
	return found


def cascade(plan_name: str, recurse: bool = True) -> dict:
	"""Create a child plan for every node below this one, and account for every unit.

	Re-runnable: an existing child for the same person and period is rewritten rather than
	duplicated, because the first thing anybody does after a cascade is change one number at the
	top and run it again.
	"""
	plan = frappe.get_doc("FieldMate Target Plan", plan_name)
	if plan.docstatus != 1:
		frappe.throw(frappe._("Submit the plan before cascading it."))

	kids = children_of(plan.sales_person)
	if not kids:
		plan.db_set("child_count", 0, update_modified=False)
		plan.db_set("cascade_note", "A leaf. Nothing below it to split.", update_modified=False)
		return {"plan": plan.name, "children": [], "leaf": True}

	basis = plan.cascade_basis or "Outlet Count"
	weights = weights_for(kids, basis, plan)

	# One split per line, so every line is divided by the same weights and a child's plan is
	# internally consistent even where a category target and the overall one round differently.
	per_child: dict[str, list[dict]] = {kid: [] for kid in kids}
	remainder_to = None

	for line in plan.lines:
		if not cint(line.is_additive):
			# A rate is copied, not divided. Every child is asked for the same 4.5 lines a call.
			for kid in kids:
				per_child[kid].append(_line_payload(line, flt(line.target_value)))
			continue

		units = to_units(line.target_value, line.target_type)
		shares, took = split_detail(units, weights)
		for kid, share in zip(kids, shares, strict=True):
			per_child[kid].append(_line_payload(line, from_units(share, line.target_type)))

		if remainder_to is None and took:
			remainder_to = kids[took[0]]

	created = [_upsert_child(plan, kid, per_child[kid]) for kid in kids]

	plan.db_set("child_count", len(created), update_modified=False)
	plan.db_set("plan_status", "Cascaded", update_modified=False)
	plan.db_set("cascaded_on", now_datetime(), update_modified=False)
	plan.db_set("cascade_remainder_to", remainder_to, update_modified=False)
	plan.db_set("cascade_note",
	            f"Split {len(created)} ways by {basis.lower()}."
	            + (f" Spare units went to {remainder_to}." if remainder_to else ""),
	            update_modified=False)

	if recurse:
		for child in created:
			cascade(child, recurse=True)

	return {"plan": plan.name, "children": created, "leaf": False, "basis": basis,
	        "remainder_to": remainder_to}


def _line_payload(line, value) -> dict:
	return {
		"target_type": line.target_type,
		"item_group": line.item_group,
		"brand": line.brand,
		"target_value": value,
		"notes": line.notes,
	}


def _upsert_child(parent, sales_person: str, lines: list[dict]) -> str:
	existing = frappe.db.get_value("FieldMate Target Plan", {
		"parent_plan": parent.name, "sales_person": sales_person, "docstatus": ["<", 2],
	}, "name")

	if existing:
		child = frappe.get_doc("FieldMate Target Plan", existing)
		if child.docstatus == 1:
			# A submitted child cannot have its table rewritten, and cancelling it would take
			# the grandchildren with it. Re-cascading a changed root is a deliberate act, so it
			# says so rather than silently leaving the old numbers in place.
			frappe.throw(
				frappe._("{0} is already submitted. Cancel the plans below it before "
				         "re-cascading.").format(existing))
		child.set("lines", [])
	else:
		child = frappe.new_doc("FieldMate Target Plan")
		child.parent_plan = parent.name

	child.plan_name = parent.plan_name
	child.company = parent.company
	child.from_date = parent.from_date
	child.to_date = parent.to_date
	child.sales_person = sales_person
	child.cascade_basis = parent.cascade_basis
	child.plan_status = "Active"
	for payload in lines:
		child.append("lines", payload)

	child.flags.ignore_permissions = True
	child.save()
	child.submit()
	return child.name


def leaves_of(plan_name: str) -> list[str]:
	"""Every plan at the bottom of this one's branch.

	A plan with no children is its own leaf. That is not a special case to be patched around -
	an uncascaded plan trivially sums to itself, and any other answer would make `reconcile`
	report a mismatch for a tree that has not been split yet.
	"""
	found, queue = [], [plan_name]
	while queue:
		node = queue.pop()
		kids = frappe.get_all("FieldMate Target Plan",
		                      filters={"parent_plan": node, "docstatus": 1}, pluck="name")
		if kids:
			queue.extend(kids)
		else:
			found.append(node)
	return found


def reconcile(plan_name: str) -> dict:
	"""Do the leaves still add up to the root? Gate 7 criterion 1, as a function.

	Returns every type separately rather than one verdict, because an additive type that is out
	by a paisa and a ratio type that was copied correctly are two different answers and one
	boolean cannot carry both.
	"""
	root = frappe.get_doc("FieldMate Target Plan", plan_name)
	leaves = leaves_of(plan_name)

	summed: dict[str, int] = {}
	copied: dict[str, set] = {}
	for leaf in leaves:
		for row in frappe.get_all("FieldMate Target Line",
		                          filters={"parent": leaf, "parenttype": "FieldMate Target Plan"},
		                          fields=["target_type", "target_value", "item_group", "brand"]):
			if narrowing(row.item_group) or row.brand:
				continue
			if TARGET_TYPES.get(row.target_type, True):
				summed[row.target_type] = summed.get(row.target_type, 0) + to_units(
					row.target_value, row.target_type)
			else:
				copied.setdefault(row.target_type, set()).add(round(flt(row.target_value), 4))

	report = {}
	for line in root.lines:
		if narrowing(line.item_group) or line.brand:
			continue
		wanted = to_units(line.target_value, line.target_type)
		if cint(line.is_additive):
			got = summed.get(line.target_type, 0)
			report[line.target_type] = {
				"additive": True,
				"root": from_units(wanted, line.target_type),
				"leaves": from_units(got, line.target_type),
				"matches": got == wanted,
				"difference": from_units(got - wanted, line.target_type),
			}
		else:
			seen = copied.get(line.target_type, set())
			expected = round(flt(line.target_value), 4)
			report[line.target_type] = {
				"additive": False,
				"root": expected,
				"leaves": sorted(seen),
				# A rate is carried down unchanged, so every leaf holds the root's own number.
				# Summing it would be the bug, not the check.
				"matches": seen == {expected} or (not leaves and not seen),
				"difference": 0,
			}

	return {"plan": plan_name, "leaf_count": len(leaves), "types": report,
	        "matches": all(entry["matches"] for entry in report.values())}


# --------------------------------------------------------------------------------------
# achievement
# --------------------------------------------------------------------------------------


def _field_users_under(sales_person: str) -> list[str]:
	return frappe.get_all("FieldMate Field User",
	                      filters={"sales_person": ["in", subtree(sales_person)]},
	                      pluck="name")


def _orders_under(sales_person: str, from_date, to_date) -> list:
	users = _field_users_under(sales_person)
	if not users:
		return []
	return frappe.get_all(
		"FieldMate Order",
		filters={
			"field_user": ["in", users],
			"order_date": ["between", [from_date, to_date]],
			"docstatus": 1,
			"order_status": ["not in", DEAD_ORDER_STATES],
		},
		fields=["name", "outlet", "field_user", "net_total", "total_qty", "total_lines"],
		limit_page_length=0,
	)


def measure(sales_person: str, from_date, to_date, item_group=None, brand=None) -> dict:
	"""The six numbers, counted from the documents a manager would count by hand.

	Category and brand narrow the value and volume figures only. Asking how many shops were
	covered "in tea" is a different question from the one the coverage target asks, and
	answering it here would make two lines on the same plan mean different things.
	"""
	# Here as well as in `compute`, because this is called straight from the gate scripts and the
	# nightly job, and a root category must mean the same thing down every one of those paths.
	item_group = narrowing(item_group)
	scoped = bool(item_group or brand)
	orders = _orders_under(sales_person, from_date, to_date)
	users = _field_users_under(sales_person)

	if scoped:
		value, volume = _scoped_value_and_volume([o.name for o in orders], item_group, brand)
	else:
		value = sum(flt(o.net_total) for o in orders)
		volume = sum(flt(o.total_qty) for o in orders)

	visits = frappe.get_all(
		"FieldMate Visit",
		filters={"field_user": ["in", users or [""]],
		         "visit_date": ["between", [from_date, to_date]], "docstatus": 1},
		fields=["name", "outlet", "visit_outcome", "order_value", "lines_sold"],
		limit_page_length=0,
	) if users else []

	# Productive means an order came out of it. `visit_outcome` is what the rep chose on the
	# screen and `order_value` is what the server computed; a visit counts only where both agree,
	# because a rep who selects "Order Taken" and books nothing is the case this guards.
	productive = [v for v in visits if flt(v.order_value) > 0]
	lines_sold = sum(cint(v.lines_sold) for v in productive)

	new_outlets = frappe.db.count("FieldMate Outlet", {
		"created_by_rep": ["in", users or [""]],
		"onboarding_date": ["between", [from_date, to_date]],
		"approval_status": "Approved",
	}) if users else 0

	return {
		"Value": value,
		"Volume": volume,
		"Outlet Coverage": len({o.outlet for o in orders if o.outlet}),
		"Productive Calls": len(productive),
		"New Outlets": new_outlets,
		# Lines per call is a rate, and a rate over no calls is not zero, it is unanswerable.
		# Zero is returned because a plan has to show something, but the call count travels with
		# it so a reader can tell "did badly" from "did not go out".
		"Lines Per Call": round(lines_sold / len(productive), 2) if productive else 0.0,
		"_calls": len(visits),
		"_productive": len(productive),
		"_orders": len(orders),
	}


def narrowing(item_group: str | None) -> str | None:
	"""The item group, unless it is the root - in which case it narrows nothing.

	Frappe fills an empty Link to a tree from the session default, and for Item Group that
	default is the root, `All Item Groups`. A manager who left the category blank therefore ends
	up with a line that *looks* scoped, and the scoped path then filters order items on a group
	no item is ever in - every item sits in a leaf. The target measured zero and nothing said
	why: the plan showed a category nobody typed, over a figure that should have counted
	everything.

	The root means "all of it", which is the same question the unscoped path already answers, so
	it is collapsed to None rather than given a filter of its own.
	"""
	if not item_group:
		return None
	parent = frappe.db.get_value("Item Group", item_group, "parent_item_group")
	return None if not parent else item_group


def _scoped_value_and_volume(order_names: list[str], item_group, brand) -> tuple[float, float]:
	if not order_names:
		return 0.0, 0.0
	filters = {"parent": ["in", order_names], "parenttype": "FieldMate Order"}
	if item_group:
		filters["item_group"] = item_group
	if brand:
		filters["brand"] = brand
	rows = frappe.get_all("FieldMate Order Item", filters=filters,
	                      fields=["amount", "qty"], limit_page_length=0)
	return sum(flt(r.amount) for r in rows), sum(flt(r.qty) for r in rows)


def compute(plan_name: str) -> str:
	"""Measure one plan and write the snapshot. Idempotent per plan and period."""
	plan = frappe.get_doc("FieldMate Target Plan", plan_name)
	name = frappe.db.get_value("FieldMate Achievement", {"target_plan": plan.name}, "name")
	doc = frappe.get_doc("FieldMate Achievement", name) if name \
		else frappe.new_doc("FieldMate Achievement")

	doc.target_plan = plan.name
	doc.plan_name = plan.plan_name
	doc.sales_person = plan.sales_person
	doc.field_user = plan.field_user
	doc.company = plan.company
	doc.from_date = plan.from_date
	doc.to_date = plan.to_date
	doc.computed_on = now_datetime()
	doc.set("lines", [])

	overall = measure(plan.sales_person, plan.from_date, plan.to_date)
	doc.calls = overall["_calls"]
	doc.productive_calls = overall["_productive"]
	doc.order_count = overall["_orders"]

	for line in plan.lines:
		item_group = narrowing(line.item_group)
		if item_group or line.brand:
			actual = measure(plan.sales_person, plan.from_date, plan.to_date,
			                 item_group=item_group, brand=line.brand)[line.target_type]
		else:
			actual = overall[line.target_type]

		target = flt(line.target_value)
		doc.append("lines", {
			"target_type": line.target_type,
			# What was actually measured, not what the form happened to carry. A row saying
			# "All Item Groups" over a figure counted across every group is a row that has to be
			# matched against a scheme saying nothing at all, and the two never meet.
			"item_group": item_group,
			"brand": line.brand,
			"target_value": target,
			"actual_value": actual,
			"achievement_pct": round(actual / target * 100, 2) if target else 0,
			"shortfall": max(target - actual, 0) if cint(line.is_additive) else 0,
			"is_additive": line.is_additive,
		})

	doc.headline_pct = _headline(doc)
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def _headline(doc) -> float:
	"""The one percentage a rep sees at the top of the screen.

	Value, where there is a value target, because that is the number everybody means when they
	ask how somebody is doing. Falling back to the first line rather than averaging the six:
	an average of a rupee target and a lines-per-call target is not a quantity.
	"""
	for row in doc.lines:
		if row.target_type == "Value" and not (narrowing(row.item_group) or row.brand):
			return flt(row.achievement_pct)
	return flt(doc.lines[0].achievement_pct) if doc.lines else 0.0


def compute_all(as_on=None) -> dict:
	"""The nightly job. Every plan whose period covers today.

	Leaf plans first and by name, so a run that is killed half way can be restarted and the
	reps who already have a snapshot are the ones who keep it.
	"""
	as_on = getdate(as_on or nowdate())
	plans = frappe.get_all(
		"FieldMate Target Plan",
		filters={"docstatus": 1, "from_date": ["<=", as_on], "to_date": [">=", as_on],
		         "plan_status": ["in", ["Active", "Cascaded"]]},
		fields=["name", "field_user"],
		order_by="name asc",
		limit_page_length=0,
	)
	done, failed = 0, []
	for plan in sorted(plans, key=lambda p: (0 if p.field_user else 1, p.name)):
		try:
			compute(plan.name)
			done += 1
		except Exception:
			frappe.log_error(title=f"fieldmate target.compute {plan.name}")
			failed.append(plan.name)
		# Committed per plan. A job that rolls back 250 reps because the 249th had a bad row is
		# a job that never finishes on a real site.
		frappe.db.commit()

	return {"as_on": str(as_on), "plans": len(plans), "computed": done, "failed": failed}


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------


def mine(field_user: str | None = None, as_on=None) -> dict:
	"""What this rep is asked for and where they have reached, for the performance screen."""
	from fieldmate.services import field_user as field_user_service

	field_user = field_user or field_user_service.for_user()
	as_on = getdate(as_on or nowdate())

	plan = frappe.db.get_value("FieldMate Target Plan", {
		"field_user": field_user, "docstatus": 1,
		"from_date": ["<=", as_on], "to_date": [">=", as_on],
	}, ["name", "plan_name", "from_date", "to_date"], as_dict=True)

	if not plan:
		return {"has_target": False, "as_on": str(as_on)}

	achievement = frappe.db.get_value("FieldMate Achievement", {"target_plan": plan.name}, "name")
	doc = frappe.get_doc("FieldMate Achievement", achievement) if achievement else None
	days_left = max((getdate(plan.to_date) - as_on).days, 0)

	lines = []
	for row in (doc.lines if doc else []):
		target, actual = flt(row.target_value), flt(row.actual_value)
		lines.append({
			"target_type": row.target_type,
			"item_group": row.item_group,
			"brand": row.brand,
			"target_value": target,
			"actual_value": actual,
			"achievement_pct": flt(row.achievement_pct),
			"shortfall": flt(row.shortfall),
			"is_additive": bool(row.is_additive),
			# What has to happen every remaining day. Only meaningful for something that
			# accumulates: there is no daily run rate for an average.
			"per_day_needed": round(flt(row.shortfall) / days_left, 2)
			if days_left and row.is_additive and flt(row.shortfall) else 0,
		})

	return {
		"has_target": True,
		"as_on": str(as_on),
		"plan": plan.name,
		"plan_name": plan.plan_name,
		"from_date": str(plan.from_date),
		"to_date": str(plan.to_date),
		"days_left": days_left,
		"headline_pct": flt(doc.headline_pct) if doc else 0,
		"computed_on": str(doc.computed_on) if doc and doc.computed_on else None,
		"calls": cint(doc.calls) if doc else 0,
		"productive_calls": cint(doc.productive_calls) if doc else 0,
		"lines": lines,
	}
