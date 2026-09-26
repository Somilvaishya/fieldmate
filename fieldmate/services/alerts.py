"""Exceptions worth somebody's morning, and nobody's afternoon.

Five conditions, evaluated against the KPI snapshot rather than against raw documents - the same
rule the rest of Phase 8 lives under (Gate 8 criterion 3). An alert that counted visits for
itself would be a second definition of every metric it mentions.

Two design choices carry the phase's own criterion, that each rule fires exactly once per
occurrence:

  * an occurrence is **rule + rep + day**, and that string is a unique column on the log, so the
    database refuses a second one however many times the job runs;
  * the evaluator is **idempotent over a window**, so re-running yesterday is free and safe.

The third choice is about whether anybody reads them. A rule fires on a ratio only when the base
under it is worth having an opinion about, and it can be told to keep quiet for a few days about
something already reported. An alert nobody reads is worse than no alert: it trains people to
filter the whole channel.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from fieldmate.services import scope as scope_service
from fieldmate.services import settings as settings_service

# Every condition below returns (crossed, value, base) or None, and the base is never optional.
# An alert saying 0% with no base cannot be acted on: a bad day and an empty one look identical.


def _rep_rows(rule, on_date) -> list:
	"""Every snapshot in this rule's scope for one day."""
	reps = frappe.get_all(
		"FieldMate Field User",
		filters={"status": "Active",
		         **({"designation": rule.designation} if rule.designation else {}),
		         **({"company": rule.company} if rule.company else {})},
		fields=["name", "territory", "sales_person", "full_name"],
		limit_page_length=0,
	)

	if rule.territory:
		# Territory is a tree, and a rule set on North must reach a rep in North / Delhi.
		reps = [r for r in reps if scope_service.territory_covers(rule.territory, r.territory)]
	if rule.sales_person:
		from fieldmate.services import target as target_service
		branch = set(target_service.subtree(rule.sales_person))
		reps = [r for r in reps if r.sales_person in branch]

	if not reps:
		return []

	by_name = {r.name: r for r in reps}
	rows = frappe.get_all(
		"FieldMate KPI Snapshot",
		filters={"field_user": ["in", list(by_name)], "snapshot_date": getdate(on_date)},
		fields=["*"], limit_page_length=0)

	for row in rows:
		row.full_name = by_name[row.field_user].full_name or row.field_user

	# A rep with no snapshot at all had no day rolled up yet. That is not silence to report on -
	# it is a job that has not run, and firing on it would blame the rep for our own lateness.
	return rows


# --------------------------------------------------------------------------------------
# the five
# --------------------------------------------------------------------------------------


def _day_not_started(rule, row) -> tuple[bool, float, float] | None:
	"""Nobody opened the app. Measured in hours past the hour the day was meant to begin."""
	if cint(row.day_started):
		return None
	expected = settings_service.value("day_start_alert_time") or "10:00:00"
	# Only meaningful once that hour has passed. Evaluated for a past day it always has.
	hours_late = _hours_past(getdate(row.snapshot_date), str(expected))
	if hours_late <= 0:
		return None
	return True, hours_late, 0


def _hours_past(day, at_time: str) -> float:
	from frappe.utils import get_datetime, time_diff_in_hours
	try:
		deadline = get_datetime(f"{day} {at_time}")
	except Exception:
		deadline = get_datetime(f"{day} 10:00:00")
	now = now_datetime()
	return round(time_diff_in_hours(now, deadline), 2) if now > deadline else 0


def _no_order_all_day(rule, row) -> tuple[bool, float, float] | None:
	"""The rep went out and sold nothing. The base is how many shops they actually saw.

	A rep with two calls and no order has not had a day yet; one with fourteen has had a bad one.
	`minimum_base` is what separates them, and a rule with none set fires on both.
	"""
	calls = cint(row.actual_visits)
	if not calls or cint(row.orders_count):
		return None
	return True, calls, calls


def _coverage_below(rule, row) -> tuple[bool, float, float] | None:
	return None if not cint(row.outlets_in_scope) else (
		True, flt(row.coverage_pct), cint(row.outlets_in_scope))


def _collection_in_hand(rule, row) -> tuple[bool, float, float] | None:
	"""Money collected and not handed over. The risk is the satchel, not the ledger."""
	carried = flt(row.collection_amount) - flt(row.deposited_amount)
	if carried <= 0:
		return None
	return True, carried, flt(row.collection_amount)


def _geo_breaches(rule, row) -> tuple[bool, float, float] | None:
	breaches = cint(row.geo_breach_visits)
	if not breaches:
		return None
	return True, breaches, cint(row.actual_visits)


CONDITIONS = {
	"Day Not Started": _day_not_started,
	"No Order All Day": _no_order_all_day,
	"Coverage Below Target": _coverage_below,
	"Collection Overdue In Hand": _collection_in_hand,
	"Geo Fence Breaches": _geo_breaches,
}

DEFAULT_MESSAGE = {
	"Day Not Started": "{rep} had not started their day on {date} ({value:g} hours past the usual time).",
	"No Order All Day": "{rep} made {value:g} calls on {date} and booked nothing.",
	"Coverage Below Target": "{rep} covered {value:g}% of {base:g} shops on {date}, against {threshold:g}%.",
	"Collection Overdue In Hand": "{rep} is carrying {value:,.0f} collected on {date} and not handed over.",
	"Geo Fence Breaches": "{rep} checked in outside the shop {value:g} times on {date}, out of {base:g} visits.",
}


# --------------------------------------------------------------------------------------
# evaluating
# --------------------------------------------------------------------------------------


def _crosses(rule, value: float) -> bool:
	threshold = flt(rule.threshold)
	return value < threshold if rule.comparison == "Below" else value > threshold


def _streak(rule, field_user: str, on_date, condition) -> int:
	"""How many days running this has held, counting back from the day in question.

	One bad day is weather; three is a pattern. Counted over snapshots rather than over previous
	alerts, so turning a rule on today can still say "and it has been like this all week".
	"""
	wanted = cint(rule.consecutive_days) or 1
	if wanted <= 1:
		return 1

	days = 0
	day = getdate(on_date)
	for _ in range(wanted):
		row = frappe.db.get_value("FieldMate KPI Snapshot",
		                          {"field_user": field_user, "snapshot_date": day},
		                          "*", as_dict=True)
		if not row:
			break
		outcome = condition(rule, row)
		if not outcome:
			break
		# The base is deliberately ignored here. `minimum_base` is a gate on whether to fire at
		# all, decided once on the day in question; re-applying it to each earlier day would
		# quietly shorten a streak because the rep had a thin Tuesday.
		fired, value, _base = outcome
		if not fired or not _crosses(rule, value):
			break
		days += 1
		day = add_days(day, -1)
	return days


def _recently_reported(rule, field_user: str, on_date) -> bool:
	cooldown = cint(rule.cooldown_days)
	if cooldown <= 0:
		return False
	since = add_days(getdate(on_date), -cooldown)
	return bool(frappe.db.exists("FieldMate Alert Log", {
		"rule": rule.name, "field_user": field_user,
		"occurred_on": ["between", [since, add_days(getdate(on_date), -1)]],
	}))


def evaluate_rule(rule_name: str, on_date=None) -> dict:
	"""Run one rule over one day. Safe to run again: the log's unique key absorbs a repeat."""
	rule = frappe.get_doc("FieldMate Alert Rule", rule_name)
	on_date = getdate(on_date or nowdate())

	if not cint(rule.is_active):
		return {"rule": rule.name, "date": str(on_date), "fired": 0, "skipped": "inactive"}

	condition = CONDITIONS[rule.exception]
	fired, repeated = [], 0

	for row in _rep_rows(rule, on_date):
		outcome = condition(rule, row)
		if not outcome:
			continue
		crossed, value, base = outcome
		if not crossed or not _crosses(rule, value):
			continue
		# A ratio over almost nothing is noise, and noise is what teaches people to filter the
		# whole channel.
		if flt(rule.minimum_base) and flt(base) < flt(rule.minimum_base):
			continue

		streak = _streak(rule, row.field_user, on_date, condition)
		if streak < (cint(rule.consecutive_days) or 1):
			continue
		if _recently_reported(rule, row.field_user, on_date):
			continue

		logged = _log(rule, row, value, base, streak)
		if logged:
			fired.append(logged)
		else:
			repeated += 1

	rule.db_set("evaluated_on", now_datetime(), update_modified=False)
	return {"rule": rule.name, "date": str(on_date), "fired": len(fired),
	        "already_logged": repeated, "logs": fired}


def _log(rule, row, value: float, base: float, streak: int) -> str | None:
	"""Write the occurrence, or return None because it was already written.

	The key is rule + rep + day and the column is unique, so two jobs racing produce one row and
	the loser learns about it from the database rather than from a check it forgot to do.
	"""
	key = f"{rule.name}|{row.field_user}|{row.snapshot_date}"
	existing = frappe.db.get_value("FieldMate Alert Log", {"occurrence_key": key}, "name")
	if existing:
		return None

	template = rule.message_template or DEFAULT_MESSAGE[rule.exception]
	try:
		message = template.format(rep=row.full_name, date=row.snapshot_date, value=value,
		                          threshold=flt(rule.threshold), base=base)
	except (KeyError, IndexError, ValueError):
		# A template somebody typed wrong must not stop the alert; the figures matter more than
		# the sentence.
		message = DEFAULT_MESSAGE[rule.exception].format(
			rep=row.full_name, date=row.snapshot_date, value=value,
			threshold=flt(rule.threshold), base=base)

	doc = frappe.get_doc({
		"doctype": "FieldMate Alert Log",
		"rule": rule.name,
		"exception": rule.exception,
		"field_user": row.field_user,
		"occurred_on": row.snapshot_date,
		"severity": rule.severity,
		"fired_on": now_datetime(),
		"observed_value": value,
		"threshold": flt(rule.threshold),
		"base_value": base,
		"consecutive_days": streak,
		"message": message,
		"occurrence_key": key,
	})
	doc.flags.ignore_permissions = True
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Two workers reached the same occurrence. Exactly one row exists, which is the point.
		#
		# Both exceptions, because Frappe raises them from different places: a unique COLUMN
		# that the database rejects surfaces as UniqueValidationError, while a duplicate primary
		# key is a DuplicateEntryError. `occurrence_key` is the first kind, and catching only
		# the second - which is what this did at first - would have let a real race escape as a
		# server error on the one path that exists to make races harmless.
		return None

	doc.db_set("notified_count", _notify(rule, row, message), update_modified=False)
	return doc.name


def _notify(rule, row, message: str) -> int:
	"""Tell whoever the rule names. Returns how many people were told.

	Frappe Notification Logs rather than email: an email nobody configured goes nowhere and
	reports success, and a manager reading this on a phone is already inside the Desk app.
	"""
	recipients = set()

	for role in rule.roles():
		recipients.update(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"},
		                                 pluck="parent"))

	if cint(rule.notify_manager):
		manager = frappe.db.get_value("FieldMate Field User", row.field_user, "reports_to")
		manager_user = frappe.db.get_value("FieldMate Field User", manager, "user") \
			if manager else None
		if manager_user:
			recipients.add(manager_user)

	recipients.discard("Administrator")
	recipients.discard("Guest")
	if not recipients:
		return 0

	told = 0
	for user in recipients:
		if not frappe.db.get_value("User", user, "enabled"):
			continue
		try:
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"document_type": "FieldMate Alert Log",
				"subject": f"{rule.severity}: {rule.rule_name}",
				"email_content": message,
			}).insert(ignore_permissions=True)
			told += 1
		except Exception:
			# One bad recipient must not swallow the rest, and must not lose the log row that
			# has already been written.
			frappe.log_error(title=f"fieldmate alerts notify {user}")
	return told


def evaluate_all(on_date=None, days_back: int = 1) -> dict:
	"""Every active rule over a short trailing window. The scheduled job.

	A window, for the same reason the rollup uses one: a day is corrected after it ends, and a
	snapshot recomputed at noon can turn an ordinary day into an exception. Re-running is free -
	the occurrence key makes a repeat a no-op.
	"""
	on_date = getdate(on_date or nowdate())
	rules = frappe.get_all("FieldMate Alert Rule", filters={"is_active": 1}, pluck="name",
	                       order_by="name asc")

	fired = repeated = 0
	failed = []
	for rule in rules:
		for back in range(max(days_back, 1)):
			day = add_days(on_date, -back)
			try:
				result = evaluate_rule(rule, day)
				fired += result.get("fired", 0)
				repeated += result.get("already_logged", 0)
			except Exception:
				frappe.log_error(title=f"fieldmate alerts.evaluate_rule {rule} {day}")
				failed.append(f"{rule}@{day}")
		frappe.db.commit()

	return {"date": str(on_date), "rules": len(rules), "fired": fired,
	        "already_logged": repeated, "failed": failed}


# --------------------------------------------------------------------------------------
# the five, as shipped
# --------------------------------------------------------------------------------------

STARTER_RULES = [
	{
		"rule_name": "Day not started by mid-morning",
		"exception": "Day Not Started",
		"severity": "Warning",
		"threshold": 2, "comparison": "Above",
		"notify_manager": 1,
	},
	{
		"rule_name": "A day out with nothing sold",
		"exception": "No Order All Day",
		"severity": "Warning",
		"threshold": 4, "comparison": "Above", "minimum_base": 4,
		"notify_manager": 1,
	},
	{
		"rule_name": "Coverage below 60%",
		"exception": "Coverage Below Target",
		"severity": "Info",
		"threshold": 60, "comparison": "Below", "minimum_base": 20,
		"consecutive_days": 3, "cooldown_days": 7,
		"notify_manager": 1,
	},
	{
		"rule_name": "Cash carried and not handed over",
		"exception": "Collection Overdue In Hand",
		"severity": "Critical",
		"threshold": 10000, "comparison": "Above",
		"notify_manager": 1,
	},
	{
		"rule_name": "Checked in away from the shop",
		"exception": "Geo Fence Breaches",
		"severity": "Warning",
		"threshold": 2, "comparison": "Above",
		"notify_manager": 1,
	},
]


def install_starter_rules() -> int:
	"""Create the five, once. Idempotent, and it never edits a rule somebody has tuned."""
	made = 0
	for payload in STARTER_RULES:
		if frappe.db.exists("FieldMate Alert Rule", payload["rule_name"]):
			continue
		doc = frappe.get_doc({"doctype": "FieldMate Alert Rule", "is_active": 1, **payload})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		made += 1
	return made


def recent(limit: int = 50, field_user: str | None = None) -> list[dict]:
	filters = {}
	if field_user:
		filters["field_user"] = field_user
	return frappe.get_all(
		"FieldMate Alert Log",
		filters=filters,
		fields=["name", "rule", "exception", "field_user", "occurred_on", "severity",
		        "observed_value", "threshold", "base_value", "consecutive_days", "message"],
		order_by="occurred_on desc, fired_on desc",
		limit_page_length=limit,
	)
