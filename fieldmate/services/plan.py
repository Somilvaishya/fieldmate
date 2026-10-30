"""A manager planning their team's month from the phone: the beats, and the journey plans.

Nothing here decides a route. `journey.build_days` already turns a rep's beats, holidays and
leave into a calendar, and the Beat controller already refuses a shop outside the territory or on
two beats at once. This is the thin layer that lets an Area Manager reach both without Desk,
held to the same reporting line as every other decision they take from the app - and to the same
Territory User Permission that bounds them everywhere else.

The flow is the one the market works to: the manager builds the window, reads it, and approves
it. Building makes a draft (replacing any earlier draft for the same window); approving submits
it, and only a submitted plan reaches the rep's Today.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, date_diff, get_first_day, get_last_day, getdate, nowdate

from fieldmate.fieldmate.doctype.fieldmate_beat.fieldmate_beat import territory_and_descendants
from fieldmate.fieldmate.doctype.fieldmate_journey_plan.fieldmate_journey_plan import MAX_PLAN_DAYS
from fieldmate.services import field_user as field_user_service
from fieldmate.services import journey as journey_service

FREQUENCIES = ("Weekly", "Fortnightly", "Monthly")
WEEK_PATTERNS = ("All", "W1", "W2", "W3", "W4")


def _window(month: str | None = None, from_date: str | None = None,
            to_date: str | None = None) -> tuple:
	"""An explicit range if one was given, otherwise the calendar month around `month`."""
	if from_date and to_date:
		start, end = getdate(from_date), getdate(to_date)
		if date_diff(end, start) < 0:
			frappe.throw(frappe._("To date is before from date."))
		if date_diff(end, start) > MAX_PLAN_DAYS:
			frappe.throw(frappe._("A plan cannot span more than {0} days. Generate one month at a "
			                      "time.").format(MAX_PLAN_DAYS))
		return start, end
	anchor = getdate(month or from_date or nowdate())
	return get_first_day(anchor), get_last_day(anchor)


def _scope_filter(scope, field="field_user") -> dict:
	return {} if scope is None else {field: ["in", scope]}


# --------------------------------------------------------------------------------------
# what this manager may plan over
# --------------------------------------------------------------------------------------


def territories(user: str | None = None) -> list[str]:
	"""The territories this login may plan in: its Territory User Permissions, with their
	children unless the permission hides them. Company-wide roles may plan anywhere.

	Read from the User Permission rows rather than from the Field User's territory, because the
	permission is the boundary the rest of the app enforces - a manager given two districts by
	permission plans both, whatever single territory their profile names.
	"""
	user = user or frappe.session.user
	if field_user_service.team_scope(user) is None:
		return frappe.get_all("Territory", order_by="lft asc", pluck="name")

	found: list[str] = []
	for row in frappe.get_all("User Permission",
	                          filters={"user": user, "allow": "Territory"},
	                          fields=["for_value", "hide_descendants"]):
		names = [row.for_value] if cint(row.hide_descendants) \
			else territory_and_descendants(row.for_value)
		found.extend(n for n in names if n not in found)

	# A manager with a Field User but no permission row yet - the row is written on save, so
	# this is a site mid-setup rather than a policy. Their own territory is what they hold.
	if not found:
		mine = field_user_service.territory_of(user)
		found = territory_and_descendants(mine) if mine else []
	return found


def _assert_territory_is_mine(territory: str, user: str | None = None) -> None:
	if not territory:
		frappe.throw(frappe._("Which territory?"))
	if territory not in territories(user):
		frappe.throw(frappe._("{0} is outside your territory.").format(territory),
		             frappe.PermissionError)


def holiday_lists(field_user: str, user: str | None = None) -> dict:
	"""The holiday lists this manager may plan a rep's month against.

	The rep's own list - off their Employee record, the one the plan uses when nobody picks - is
	always offered. Any other list is offered only if this login may read it; on most sites that
	is HR alone, so a manager sees the rep's own and nothing else, which is the HR decision.
	"""
	field_user_service.assert_in_team(field_user, user)
	default = journey_service.holiday_list_for(field_user)
	try:
		readable = frappe.get_list("Holiday List", pluck="name", order_by="name asc",
		                           limit_page_length=0, user=user)
	except frappe.PermissionError:
		readable = []
	options = ([default] if default else []) + [n for n in readable if n != default]
	return {"default": default, "options": options}


def _assert_holiday_list_allowed(field_user: str, holiday_list: str | None,
                                 user: str | None = None) -> None:
	if holiday_list and holiday_list not in holiday_lists(field_user, user)["options"]:
		frappe.throw(frappe._("You cannot plan against holiday list {0}.").format(holiday_list),
		             frappe.PermissionError)


# --------------------------------------------------------------------------------------
# the window, per rep
# --------------------------------------------------------------------------------------


def overview(month: str | None = None, user: str | None = None, territory: str | None = None,
             from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Every rep in the team - or in one territory of it - and where their plan stands."""
	start, end = _window(month, from_date, to_date)
	scope = field_user_service.team_scope(user)
	empty = {"from_date": str(start), "to_date": str(end), "members": []}
	if scope is not None and not scope:
		return empty

	filters = {"status": "Active", **_scope_filter(scope, "name")}
	if territory:
		_assert_territory_is_mine(territory, user)
		filters["territory"] = ["in", territory_and_descendants(territory)]

	members = frappe.get_all(
		"FieldMate Field User", filters=filters,
		fields=["name", "full_name", "territory", "designation"],
		order_by="full_name asc", limit_page_length=0)
	names = [m.name for m in members]
	if not names:
		return empty

	plans: dict[str, dict] = {}
	for p in frappe.get_all(
			"FieldMate Journey Plan",
			filters={"field_user": ["in", names], "docstatus": ["<", 2],
			         "from_date": ["<=", end], "to_date": [">=", start]},
			fields=["name", "field_user", "docstatus", "from_date", "to_date", "working_days",
			        "planned_days", "planned_visits", "holiday_list"],
			order_by="docstatus desc, modified desc"):
		# A submitted plan wins over a draft for the same window: it is the one the rep walks.
		plans.setdefault(p.field_user, p)

	beat_counts = dict(frappe.db.sql(
		"""select assigned_to, count(*) from `tabFieldMate Beat`
		   where is_active = 1 and assigned_to in %(names)s group by assigned_to""",
		{"names": names}))

	out = []
	for m in members:
		p = plans.get(m.name)
		out.append({
			"field_user": m.name,
			"full_name": m.full_name or m.name,
			"territory": m.territory,
			"designation": m.designation,
			"beats": cint(beat_counts.get(m.name)),
			"plan": _plan_summary(p) if p else None,
		})
	# Who needs the manager's hand first: nobody planned, then a draft waiting, then done.
	rank = lambda r: 0 if not r["plan"] else (1 if r["plan"]["state"] == "Draft" else 2)  # noqa: E731
	out.sort(key=lambda r: (rank(r), r["full_name"]))
	return {"from_date": str(start), "to_date": str(end), "members": out}


def _plan_summary(p) -> dict:
	working, planned = cint(p.working_days), cint(p.planned_days)
	return {
		"name": p.name,
		"state": "Approved" if cint(p.docstatus) == 1 else "Draft",
		"from_date": str(p.from_date),
		"to_date": str(p.to_date),
		"holiday_list": p.holiday_list,
		"working_days": working,
		"planned_days": planned,
		"planned_visits": cint(p.planned_visits),
		# Working days with no beat on them - a hole in the route design, not a day off.
		"gaps": max(0, working - planned),
	}


def days(plan: str, user: str | None = None) -> dict:
	"""One plan, day by day, with each beat's name rather than its id."""
	doc = frappe.get_doc("FieldMate Journey Plan", plan)
	field_user_service.assert_in_team(doc.field_user, user)
	beat_names = dict(frappe.get_all(
		"FieldMate Beat", filters={"name": ["in", [d.beat for d in doc.days if d.beat] or [""]]},
		fields=["name", "beat_name"], as_list=True))
	return {
		**_plan_summary(doc),
		"field_user": doc.field_user,
		"territory": doc.territory,
		"full_name": frappe.db.get_value("FieldMate Field User", doc.field_user, "full_name"),
		"can_cancel": bool(cint(doc.docstatus) == 1
		                   and frappe.has_permission("FieldMate Journey Plan", "cancel", doc=doc,
		                                             user=user)),
		"days": [{
			"plan_date": str(d.plan_date),
			"day_of_week": d.day_of_week,
			"status": d.status,
			"is_working_day": cint(d.is_working_day),
			"beat": d.beat,
			"beat_name": beat_names.get(d.beat) if d.beat else None,
			"outlet_count": cint(d.outlet_count),
			"note": d.note,
		} for d in doc.days],
	}


def build(field_user: str, month: str | None = None, user: str | None = None,
          from_date: str | None = None, to_date: str | None = None,
          holiday_list: str | None = None) -> dict:
	"""Make (or remake) the draft for a rep's window, and hand it back to be read."""
	field_user_service.assert_in_team(field_user, user)
	start, end = _window(month, from_date, to_date)
	_assert_holiday_list_allowed(field_user, holiday_list, user)

	clash = frappe.db.get_value("FieldMate Journey Plan", {
		"field_user": field_user, "docstatus": 1,
		"from_date": ["<=", end], "to_date": [">=", start]}, ["name", "from_date", "to_date"],
		as_dict=True)
	if clash:
		frappe.throw(frappe._("{0} is already approved for {1} to {2}. Cancel that plan, or pick "
		                      "dates outside it.").format(clash.name, clash.from_date, clash.to_date))

	# A draft overlapping this window but not matching it exactly would be left beside the new
	# one, and the list would show whichever was touched last. One draft per rep per window.
	for stale in frappe.get_all("FieldMate Journey Plan", pluck="name", filters={
			"field_user": field_user, "docstatus": 0,
			"from_date": ["<=", end], "to_date": [">=", start]}):
		frappe.delete_doc("FieldMate Journey Plan", stale, force=True, ignore_permissions=True)

	return days(journey_service.generate(field_user, start, end, holiday_list=holiday_list), user)


def approve(plan: str, user: str | None = None) -> dict:
	doc = frappe.get_doc("FieldMate Journey Plan", plan)
	field_user_service.assert_in_team(doc.field_user, user)
	if doc.docstatus != 0:
		frappe.throw(frappe._("This plan is not a draft."))
	doc.flags.ignore_permissions = True
	doc.submit()
	return days(doc.name, user)


def cancel(plan: str, user: str | None = None) -> dict:
	"""Withdraw an approved plan so the window can be rebuilt.

	The same right Desk gave: a Regional Manager and above may, an Area Manager may not. Their
	plans are the ones a rep has already been walking, and pulling one mid-month is a decision a
	level up.
	"""
	doc = frappe.get_doc("FieldMate Journey Plan", plan)
	field_user_service.assert_in_team(doc.field_user, user)
	if not frappe.has_permission("FieldMate Journey Plan", "cancel", doc=doc, user=user):
		frappe.throw(frappe._("Only a Regional Manager or above can withdraw an approved plan."),
		             frappe.PermissionError)
	doc.flags.ignore_permissions = True
	doc.cancel()
	return {"name": doc.name, "state": "Cancelled"}


# --------------------------------------------------------------------------------------
# the beats
# --------------------------------------------------------------------------------------


def beats(field_user: str | None = None, user: str | None = None,
          territory: str | None = None) -> list[dict]:
	"""The team's beats - or one rep's, or one territory's - with when each runs."""
	scope = field_user_service.team_scope(user)
	if field_user:
		field_user_service.assert_in_team(field_user, user)
		filters = {"assigned_to": field_user}
	elif scope is not None and not scope:
		return []
	else:
		filters = _scope_filter(scope, "assigned_to")
	if territory:
		_assert_territory_is_mine(territory, user)
		filters["territory"] = ["in", territory_and_descendants(territory)]

	rows = frappe.get_all(
		"FieldMate Beat", filters=filters,
		fields=["name", "beat_name", "assigned_to", "territory", "is_active", "visit_day",
		        "frequency", "week_pattern", "outlet_count"],
		order_by="is_active desc, beat_name asc", limit_page_length=0)
	people = dict(frappe.get_all(
		"FieldMate Field User", filters={"name": ["in", [r.assigned_to for r in rows] or [""]]},
		fields=["name", "full_name"], as_list=True))
	for r in rows:
		r["rep_name"] = people.get(r.assigned_to, r.assigned_to)
		r["is_active"] = cint(r.is_active)
	return rows


def beat(name: str, user: str | None = None) -> dict:
	doc = frappe.get_doc("FieldMate Beat", name)
	field_user_service.assert_in_team(doc.assigned_to, user)
	return _beat_payload(doc)


def _beat_payload(doc) -> dict:
	return {
		"name": doc.name,
		"beat_name": doc.beat_name,
		"territory": doc.territory,
		"assigned_to": doc.assigned_to,
		"distributor": doc.distributor,
		"effective_from": str(doc.effective_from) if doc.effective_from else None,
		"notes": doc.notes,
		"is_active": cint(doc.is_active),
		"visit_day": doc.visit_day,
		"frequency": doc.frequency,
		"week_pattern": doc.week_pattern,
		"outlet_count": cint(doc.outlet_count),
		"outlets": [{"outlet": r.outlet, "outlet_name": r.outlet_name, "sequence": r.sequence}
		            for r in doc.outlets],
	}


def beat_options(field_user: str, user: str | None = None) -> dict:
	"""What a beat for this rep may be set to: the territories, and the distributors.

	A territory has to be both the manager's (their permission) and the rep's (the Beat controller
	refuses a route the rep cannot see), so it is the overlap of the two. The distributors are the
	ones this rep already reaches - the same list an order from this rep would offer.
	"""
	from fieldmate.services import party as party_service

	field_user_service.assert_in_team(field_user, user)
	rep_territory = frappe.db.get_value("FieldMate Field User", field_user, "territory")
	reach = set(territory_and_descendants(rep_territory)) if rep_territory else set()
	allowed = [t for t in territories(user) if t in reach]

	names = party_service.distributors_of(field_user)
	titles = dict(frappe.get_all("Customer", filters={"name": ["in", names or [""]]},
	                             fields=["name", "customer_name"], as_list=True))
	return {
		"territories": allowed,
		"default_territory": rep_territory if rep_territory in allowed else (allowed[0] if allowed else None),
		"distributors": [{"name": n, "customer_name": titles.get(n) or n} for n in names],
	}


def free_outlets(territory: str, query: str | None = None, user: str | None = None,
                 limit: int = 100) -> list[dict]:
	"""Shops in a territory that no active beat covers yet - the ones a new beat can take."""
	_assert_territory_is_mine(territory, user)
	filters = {"territory": ["in", territory_and_descendants(territory)],
	           "outlet_status": ["!=", "Closed"]}
	or_filters = None
	if query:
		like = f"%{query}%"
		or_filters = {"outlet_name": ["like", like], "name": ["like", like]}
	rows = frappe.get_all("FieldMate Outlet", filters=filters, or_filters=or_filters,
	                      fields=["name", "outlet_name", "territory", "approval_status",
	                              "primary_beat"],
	                      order_by="outlet_name asc", limit_page_length=limit * 2)
	return [r for r in rows if not r.primary_beat][:limit]


def save_beat(payload: dict, user: str | None = None) -> dict:
	"""Create a beat, or change one. The Beat controller holds every rule about its shops."""
	from fieldmate.services import party as party_service

	name = payload.get("name")
	doc = frappe.get_doc("FieldMate Beat", name) if name else frappe.new_doc("FieldMate Beat")
	if name:
		# Both ends: a manager may neither edit another team's beat nor hand theirs away to one.
		field_user_service.assert_in_team(doc.assigned_to, user)

	assigned_to = payload.get("assigned_to") or doc.assigned_to
	if not assigned_to:
		frappe.throw(frappe._("Say which rep walks this beat."))
	field_user_service.assert_in_team(assigned_to, user)

	territory = payload.get("territory") or doc.territory \
		or frappe.db.get_value("FieldMate Field User", assigned_to, "territory")
	_assert_territory_is_mine(territory, user)

	distributor = payload.get("distributor", doc.distributor)
	if distributor and distributor != doc.distributor \
			and distributor not in party_service.distributors_of(assigned_to):
		frappe.throw(frappe._("{0} does not supply this rep's shops.").format(distributor))

	frequency = payload.get("frequency") or doc.frequency or "Weekly"
	pattern = payload.get("week_pattern") or doc.week_pattern or "All"
	if frequency not in FREQUENCIES or pattern not in WEEK_PATTERNS:
		frappe.throw(frappe._("That is not a schedule a beat can run on."))

	doc.update({
		"beat_name": (payload.get("beat_name") or doc.beat_name or "").strip(),
		"territory": territory,
		"assigned_to": assigned_to,
		"distributor": distributor or None,
		"effective_from": payload.get("effective_from", doc.effective_from) or None,
		"notes": payload.get("notes", doc.notes),
		"visit_day": payload.get("visit_day") or doc.visit_day or "Monday",
		"frequency": frequency,
		# A weekly beat runs every week; saying so here spares the manager the controller's
		# refusal for a pattern they never chose.
		"week_pattern": "All" if frequency == "Weekly" else pattern,
		"is_active": cint(payload.get("is_active", doc.is_active if name else 1)),
	})
	if not doc.beat_name:
		frappe.throw(frappe._("Give the beat a name the rep will recognise."))

	if "outlets" in payload:
		names = [o for o in (payload.get("outlets") or []) if o]
		titles = dict(frappe.get_all("FieldMate Outlet", filters={"name": ["in", names or [""]]},
		                             fields=["name", "outlet_name"], as_list=True))
		doc.set("outlets", [{"outlet": o, "outlet_name": titles.get(o)} for o in names])

	doc.flags.ignore_permissions = True
	doc.save() if name else doc.insert()
	return _beat_payload(doc)
