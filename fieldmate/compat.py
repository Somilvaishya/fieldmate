"""The version boundary.

This is the ONLY module in FieldMate that imports from `erpnext` or `hrms`, and the only one
that branches on a host version. Everything else — api, services, doctypes — goes through here.

Two rules when adding an adapter:

1. Never leak a host object out of this module. Return plain dicts, floats and lists so that a
   change in an ERPNext class shape is invisible to the rest of the app.
2. Prefer a capability probe over a version number. Probes survive backports; version checks do
   not. Only branch on version when a probe is impossible.

Where a value is plain data rather than business logic, query it with `frappe.get_all` instead of
importing an ERPNext helper — fewer imports is fewer things that can move in v16/v17.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt
from frappe.utils.caching import request_cache

# Minimum host versions, enforced at install time by fieldmate.setup.install.
#
# hrms is OPTIONAL by design. FieldMate mirrors Day Start / Day End into Employee Checkin when it
# is present and skips that quietly when it is not (see create_employee_checkin). Making it a hard
# dependency would contradict that and would block installs on benches that never use HR.
REQUIRED_APPS = {"frappe": (15, 0), "erpnext": (15, 0)}
OPTIONAL_APPS = {"hrms": (15, 0)}
MIN_VERSIONS = {**REQUIRED_APPS, **OPTIONAL_APPS}


# --------------------------------------------------------------------------------------
# version / capability
# --------------------------------------------------------------------------------------


def app_version(app: str) -> tuple[int, ...]:
	"""Version of an app *present on the bench*, e.g. (15, 119, 1). Empty tuple if absent.

	Note this is bench presence, not site installation — an app can sit in `apps/` without being
	installed on this site. Pair it with `is_installed()` when you need to know whether its tables
	actually exist here.
	"""
	try:
		module = frappe.get_module(app)
	except Exception:
		return ()
	raw = getattr(module, "__version__", "") or ""
	parts: list[int] = []
	for chunk in raw.split("."):
		digits = "".join(c for c in chunk if c.isdigit())
		if not digits:
			break
		parts.append(int(digits))
	return tuple(parts)


def major(app: str) -> int:
	"""Major version of an app, or 0 if it is not installed."""
	version = app_version(app)
	return version[0] if version else 0


def is_installed(app: str) -> bool:
	return app in frappe.get_installed_apps()


@request_cache
def capabilities() -> dict:
	"""What this host actually supports, probed rather than assumed.

	Cached per request. `SFA Settings`-style feature flags resolve against this at boot so a
	feature needing a newer host lights up there and degrades quietly elsewhere.
	"""
	has_hrms = is_installed("hrms")
	return {
		"frappe_major": major("frappe"),
		"erpnext_major": major("erpnext"),
		"hrms_major": major("hrms") if has_hrms else 0,
		"has_erpnext": is_installed("erpnext"),
		"has_hrms": has_hrms,
		# Phase 2 writes geo into Employee Checkin; older hrms builds lack the columns.
		"checkin_has_geo": (
			has_hrms
			and _has_column("Employee Checkin", "latitude")
			and _has_column("Employee Checkin", "longitude")
		),
		"checkin_has_geolocation": has_hrms and _has_column("Employee Checkin", "geolocation"),
	}


def _has_column(doctype: str, column: str) -> bool:
	"""`frappe.db.has_column` raises when the table does not exist at all.

	That happens whenever an optional app is on the bench but not installed on this site, which is
	a normal state, not an error. Probing must never take the app down.
	"""
	try:
		return bool(frappe.db.has_column(doctype, column))
	except Exception:
		return False


def version_report() -> dict:
	"""Human-readable host summary, for the bootstrap payload and install diagnostics.

	Distinguishes the three states that actually matter: installed here, sitting on the bench but
	not installed on this site, and absent entirely. Collapsing the middle case into "installed"
	is how you end up calling into tables that do not exist.
	"""
	report = {}
	for app in ("frappe", "erpnext", "hrms"):
		version = ".".join(str(p) for p in app_version(app))
		if not version:
			report[app] = "absent"
		elif app == "frappe" or is_installed(app):
			report[app] = version
		else:
			report[app] = f"{version} (on bench, not installed on this site)"
	return report


# --------------------------------------------------------------------------------------
# credit — ERPNext owns this logic, so we wrap rather than reimplement
# --------------------------------------------------------------------------------------


def get_credit_limit(customer: str, company: str) -> float:
	"""Effective credit limit for a customer.

	Wraps ERPNext because the real logic falls back Customer -> Customer Group -> Company, and
	duplicating that would drift from the books.
	"""
	from erpnext.selling.doctype.customer.customer import get_credit_limit as _erpnext_credit_limit

	return flt(_erpnext_credit_limit(customer, company))


# --------------------------------------------------------------------------------------
# outstanding — plain data, so query it directly and import nothing
# --------------------------------------------------------------------------------------


def get_outstanding(customer: str, company: str) -> float:
	"""Total unpaid amount across submitted Sales Invoices for a party."""
	rows = frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": customer,
			"company": company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		pluck="outstanding_amount",
	)
	return flt(sum(flt(r) for r in rows))


def get_outstanding_invoices(customer: str, company: str, limit: int = 100) -> list[dict]:
	"""Open invoices with ageing, oldest first. Feeds the collection screen."""
	from frappe.utils import date_diff, nowdate

	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": customer,
			"company": company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
		},
		fields=[
			"name",
			"posting_date",
			"due_date",
			"grand_total",
			"outstanding_amount",
			"currency",
		],
		order_by="posting_date asc",
		limit=limit,
	)
	today = nowdate()
	for inv in invoices:
		inv["age_days"] = date_diff(today, inv["posting_date"])
		inv["overdue_days"] = max(0, date_diff(today, inv["due_date"])) if inv.get("due_date") else 0
	return invoices


def get_credit_status(customer: str, company: str) -> dict:
	"""Headroom, shown to the rep BEFORE they build a cart rather than as a rejection after."""
	limit = get_credit_limit(customer, company)
	outstanding = get_outstanding(customer, company)
	return {
		"credit_limit": limit,
		"outstanding": outstanding,
		# A zero limit means "no limit configured" in ERPNext, not "no credit".
		"headroom": flt(limit - outstanding) if limit else None,
		"unlimited": not bool(limit),
	}


# --------------------------------------------------------------------------------------
# pricing
# --------------------------------------------------------------------------------------


def get_item_price(item_code: str, price_list: str, uom: str | None = None) -> float:
	"""Effective Item Price for an item on a price list.

	Deliberately a plain query: `erpnext.stock.get_item_details.get_price_list_rate` needs a full
	transaction context we do not have when pricing an offline cart line.
	"""
	filters = {"item_code": item_code, "price_list": price_list, "selling": 1}
	if uom:
		filters["uom"] = uom
	rate = frappe.db.get_value("Item Price", filters, "price_list_rate")
	if rate is None and uom:
		rate = frappe.db.get_value(
			"Item Price", {"item_code": item_code, "price_list": price_list, "selling": 1}, "price_list_rate"
		)
	return flt(rate)


# --------------------------------------------------------------------------------------
# hrms — attendance
# --------------------------------------------------------------------------------------


def create_employee_checkin(
	employee: str,
	log_type: str,
	timestamp,
	latitude: float | None = None,
	longitude: float | None = None,
	device_id: str | None = None,
) -> str | None:
	"""Mirror a FieldMate Day Start / Day End into HRMS attendance.

	Returns the Employee Checkin name, or None when hrms is absent — FieldMate must keep working
	on a bench without it.
	"""
	if not is_installed("hrms"):
		return None

	doc = frappe.new_doc("Employee Checkin")
	doc.employee = employee
	doc.log_type = log_type
	doc.time = timestamp
	if device_id:
		doc.device_id = device_id
	if capabilities()["checkin_has_geo"] and latitude is not None and longitude is not None:
		doc.latitude = latitude
		doc.longitude = longitude
	doc.insert(ignore_permissions=True)
	return doc.name


# --------------------------------------------------------------------------------------
# Deliberately not yet implemented
# --------------------------------------------------------------------------------------
# make_sales_order()   -> Phase 4, added with FieldMate Order
# make_payment_entry() -> Phase 6, added with FieldMate Collection
# make_credit_note()   -> Phase 9, added with FieldMate Claim
#
# These are left out rather than stubbed. An adapter written against a signature nobody has
# verified is worse than no adapter: it looks finished and fails at the worst moment.
