"""The version boundary.

This is the ONLY module in FieldMate that imports from `erpnext` or `hrms`, and the only one
that branches on a host version. Everything else — api, services, doctypes — goes through here.

Two rules when adding an adapter:

1. Never leak a host object out of this module. Return plain dicts, floats and lists so that a
   change in an ERPNext class shape is invisible to the rest of the app.
2. Prefer a capability probe over a version number. Probes survive backports; version checks do
   not. Only branch on version when a probe is impossible.

Where a value is plain data rather than business logic, query it with `frappe.get_all` instead of
importing an ERPNext helper — fewer imports is fewer things that can move in a later version.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, nowdate
from frappe.utils.caching import request_cache
from frappe.utils.nestedset import get_ancestors_of

# Minimum host versions, enforced at install time by fieldmate.setup.install.
#
# hrms is OPTIONAL by design. FieldMate mirrors the day's open and close into Employee Checkin when it
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


def get_outstanding(customer: str, company: str, include_open_orders: bool = False) -> float:
	"""What a party owes. Submitted Sales Invoices by default, plus live orders on request.

	A credit check has to ask for the orders. A rep can book a month of business in a morning
	and none of it is an invoice yet, so a limit measured on invoices alone does not bite until
	the goods have already left the warehouse. The collection screen deliberately does not ask
	for them: a shopkeeper cannot pay against an order nobody has billed.
	"""
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
	outstanding = flt(sum(flt(r) for r in rows))

	if include_open_orders:
		outstanding += _unbilled_order_value(customer, company)
	return outstanding


def _unbilled_order_value(customer: str, company: str) -> float:
	"""The part of every live Sales Order that has not been billed yet.

	ERPNext's own credit check counts this, so ours has to as well or the two disagree about
	the same customer on the same afternoon. Taken from `per_billed`, which the Sales Order
	maintains itself, rather than by re-adding the invoices behind it.
	"""
	orders = frappe.get_all(
		"Sales Order",
		filters={
			"customer": customer,
			"company": company,
			"docstatus": 1,
			"status": ["!=", "Closed"],
			"per_billed": ["<", 100],
		},
		fields=["base_grand_total", "per_billed"],
	)
	return flt(sum(flt(o.base_grand_total) * (100 - flt(o.per_billed)) / 100 for o in orders))


def get_outstanding_invoices(customer: str, company: str, limit: int = 100) -> list[dict]:
	"""Open invoices with ageing, oldest first. Feeds the collection screen."""
	from frappe.utils import date_diff

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


def _pricing_helper():
	"""ERPNext's own rate resolver, if this host carries the shape we know how to call.

	Nothing we depend on has moved as often as this one. The rate has been reachable through
	`get_price_list_rate`, then `get_price_list_rate_for` taking a single args dict, then the
	same name taking `(args, item_code)`; the row-level `get_item_price` under it returns bare
	tuples on some builds and dicts on others. So we probe for the name, call it inside a
	guard, and read Item Price ourselves when either the name or the call shape is not what we
	expect. A wrong answer here does not fail loudly - it prices a cart at a number nobody
	agreed to, and the rep has already read that number out.
	"""
	try:
		from erpnext.stock import get_item_details as pricing
	except Exception:
		return None

	helper = getattr(pricing, "get_price_list_rate_for", None)
	return helper if callable(helper) else None


def _qty_break_field() -> str | None:
	"""Which column carries the quantity break on this host's Item Price.

	`min_qty` was how a quantity price was expressed until ERPNext replaced it with
	`packing_unit`, and the two mean opposite things: a floor to reach against a multiple to
	respect. Reading one as the other prices half a case at the full-case rate, so the probe
	says which is here and the caller applies the matching rule.
	"""
	for column in ("min_qty", "packing_unit"):
		if _has_column("Item Price", column):
			return column
	return None


# Where a site keeps the printed price. ERPNext has no MRP of its own - it is a legal marking on
# the pack rather than an accounting figure - so every company that tracks one has added a field
# for it, and the two names in the wild are our own `fm_` fixture convention and the bare `mrp`
# that Indian installs have used for years. Probed, never assumed: a catalogue that invented an
# MRP would print a number on a phone that nobody in the company ever agreed to, and the rep
# would read it out to a shopkeeper who can check the pack in his own hand.
MRP_FIELDS = ("fm_mrp", "mrp")


@request_cache
def _item_mrp_field() -> str | None:
	for column in MRP_FIELDS:
		if _has_column("Item", column):
			return column
	return None


def _item_price_rows(item_codes: list[str], price_list: str) -> dict[str, list]:
	"""Every selling price row for these items, in one query however long the list is.

	Validity and quantity breaks are applied afterwards in Python rather than in SQL, because
	both date columns are nullable: `valid_from <= today` is NULL wherever nobody filled the
	date in, which is most rows, and NULL is not true. The SQL version therefore returns no
	price at all for the ordinary case, which reads on the phone as an unsellable item.
	"""
	fields = ["item_code", "price_list_rate", "uom", "customer", "valid_from", "valid_upto"]
	qty_break = _qty_break_field()
	if qty_break:
		fields.append(qty_break)

	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": price_list, "selling": 1},
		fields=fields,
	)

	grouped: dict[str, list] = {}
	for row in rows:
		grouped.setdefault(row.item_code, []).append(row)
	return grouped


def _pick_price_row(rows: list, qty=None, customer: str | None = None, stock_uom: str | None = None):
	"""The one row that applies today, out of everything sitting on that price list."""
	on = getdate(nowdate())
	qty = flt(qty)
	qty_break = _qty_break_field()

	applicable = []
	for row in rows:
		if row.valid_from and getdate(row.valid_from) > on:
			continue
		if row.valid_upto and getdate(row.valid_upto) < on:
			continue
		# A row pinned to another customer is not ours to use. An unpinned one serves everyone.
		if row.customer and row.customer != customer:
			continue
		# A rate quoted per case cannot be multiplied by a count of pieces.
		if row.uom and stock_uom and row.uom != stock_uom:
			continue

		step = flt(row.get(qty_break)) if qty_break else 0
		if qty and step:
			if qty_break == "min_qty" and qty < step:
				continue
			if qty_break == "packing_unit" and qty % step:
				continue

		applicable.append(row)

	if not applicable:
		return None

	# Most specific wins: a customer's own rate over the shelf rate, a bigger qualifying break
	# over a smaller one, and the most recently started row over an older one.
	applicable.sort(
		key=lambda row: (
			1 if row.customer else 0,
			flt(row.get(qty_break)) if qty_break else 0,
			str(row.valid_from or ""),
		),
		reverse=True,
	)
	return applicable[0]


def get_item_price(
	item_code: str,
	price_list: str,
	qty=None,
	customer: str | None = None,
	company: str | None = None,
) -> float | None:
	"""The selling rate for one item, or None when nobody has priced it.

	None and 0.0 are different answers and the caller has to be able to tell them apart. An
	item nobody has priced must stop the line and be asked about; an item deliberately priced
	at zero - a sample, a trial pack - is a real rate. Collapse the two and an order goes out
	free, which nobody finds until somebody reconciles the invoice weeks later.
	"""
	if not (item_code and price_list):
		return None

	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")

	helper = _pricing_helper()
	if helper:
		args = frappe._dict({
			"price_list": price_list,
			"customer": customer,
			"company": company,
			"qty": flt(qty) or 1,
			"uom": stock_uom,
			"stock_uom": stock_uom,
			# Never None. ERPNext multiplies the rate by whatever this holds and flt(None) is
			# 0.0, so an unset conversion factor hands the shop the whole line for nothing.
			"conversion_factor": 1,
			# Without a date the validity window is not applied at all, and a price that
			# expired last quarter comes back looking current.
			"transaction_date": nowdate(),
		})
		try:
			rate = helper(args, item_code)
		except Exception:
			# A call shape we do not recognise. Read Item Price ourselves rather than guess.
			frappe.logger("fieldmate").warning(
				"erpnext price helper refused the call; reading Item Price directly", exc_info=True
			)
		else:
			# The helper is the books' own answer, including when that answer is "no price".
			return flt(rate) if rate is not None else None

	row = _pick_price_row(
		_item_price_rows([item_code], price_list).get(item_code, []),
		qty=qty,
		customer=customer,
		stock_uom=stock_uom,
	)
	return flt(row.price_list_rate) if row else None


def _price_currency(price_list: str | None, company: str | None) -> str | None:
	"""What the catalogue's numbers are denominated in. The price list owns this."""
	currency = frappe.db.get_value("Price List", price_list, "currency") if price_list else None
	if not currency and company:
		currency = frappe.get_cached_value("Company", company, "default_currency")
	return currency


def get_item_details(
	item_codes: list[str],
	price_list: str | None = None,
	company: str | None = None,
	customer: str | None = None,
	quantities: dict | None = None,
) -> list[dict]:
	"""Everything the catalogue screen shows about a list of items.

	Four queries whatever the length of the list. The catalogue asks for hundreds of items at
	once, over a market-street connection, and a per-item round trip is the difference between
	a screen that opens and one a rep stops waiting for. That is why the party and the
	quantities are arguments here rather than a reason to fall back to `get_item_price`: a cart
	of forty lines re-priced one call at a time is forty round trips through the same tables.

	`customer` is the billing party, which decides whether a rate somebody pinned to one
	distributor applies. `quantities` maps an item code to a quantity in **base units**, which
	decides which quantity break applies. Leave both out and the answer is the shelf price:
	one unit, no party, no break.

	`price_list_rate` is per **stock UOM**, because that is the only unit every other number
	here agrees with. A caller quoting in cases multiplies by `conversion_factor` itself.
	"""
	codes = [code for code in (item_codes or []) if code]
	if not codes:
		return []

	mrp_field = _item_mrp_field()
	fields = ["name as item_code", "item_name", "stock_uom", "sales_uom", "item_group",
	          "brand", "is_stock_item", "disabled"]
	if mrp_field:
		fields.append(f"{mrp_field} as mrp")

	items = frappe.get_all("Item", filters={"name": ["in", codes]}, fields=fields)

	# The conversion factors live on a child table, so they need a read of their own - still one
	# query for the whole list rather than one per item. Every UOM the item carries is kept,
	# not only the sales one: a catalogue may ask a rep to order in cases while the price list
	# quotes pieces, and looking that factor up later would be the per-item read this whole
	# function exists to avoid.
	conversions: dict[str, dict] = {}
	for row in frappe.get_all(
		"UOM Conversion Detail",
		filters={"parenttype": "Item", "parent": ["in", codes]},
		fields=["parent", "uom", "conversion_factor"],
	):
		conversions.setdefault(row.parent, {})[row.uom] = flt(row.conversion_factor)

	prices = _item_price_rows(codes, price_list) if price_list else {}
	currency = _price_currency(price_list, company)
	quantities = quantities or {}

	details = []
	for item in items:
		sales_uom = item.sales_uom or item.stock_uom
		factors = conversions.get(item.item_code, {})
		row = _pick_price_row(
			prices.get(item.item_code, []),
			qty=quantities.get(item.item_code),
			customer=customer,
			stock_uom=item.stock_uom,
		)
		details.append({
			"item_code": item.item_code,
			"item_name": item.item_name,
			"stock_uom": item.stock_uom,
			"sales_uom": sales_uom,
			# A sales UOM that is the stock UOM carries no conversion row and needs none.
			"conversion_factor": factors.get(sales_uom) or 1.0,
			"uom_conversions": factors,
			# A Currency column is NOT NULL DEFAULT 0, so a zero here is a field nobody filled
			# in rather than a pack that costs nothing. None says "we do not hold one", which
			# is the only honest thing to print next to a price.
			"mrp": (flt(item.get("mrp")) or None) if mrp_field else None,
			"item_group": item.item_group,
			"brand": item.brand,
			"is_stock_item": bool(item.is_stock_item),
			"disabled": bool(item.disabled),
			"price_list_rate": flt(row.price_list_rate) if row else None,
			"currency": currency,
		})
	return details


# --------------------------------------------------------------------------------------
# tax — ERPNext's own templates, resolved in bulk because this feeds a 400-SKU screen
# --------------------------------------------------------------------------------------
#
# GST comes from `Item Tax Template`, which is ERPNext core and present whether or not
# india_compliance is installed. That matters: neither bench this was built against has
# india_compliance, and a FieldMate that could only compute tax with it would be a FieldMate that
# computes no tax on most sites.
#
# **One effective rate per item, as basis points.** The templates hold account-and-rate pairs -
# CGST 9 and SGST 9, or IGST 18 - and what a rep reads out at a counter is their sum. FieldMate
# deliberately does not split them: the split depends on the supplier's state and the buyer's,
# the supplier on a secondary sale is the distributor rather than us, and the document that has
# to carry the split is the distributor's own invoice. Basis points rather than a float because
# the phone has to reach the same figure offline, and ADR-022 keeps money arithmetic integral.


def item_tax_rates(
	item_codes: list[str],
	company: str | None,
	tax_category: str | None = None,
	posting_date=None,
	net_rates: dict | None = None,
	item_groups: dict | None = None,
) -> dict[str, int]:
	"""Effective tax rate per item code, in basis points. Absent means nobody has set one.

	Resolved the way ERPNext resolves it - the item's own `Item Tax` rows first, then its Item
	Group's and that group's ancestors' - and by calling ERPNext's matcher rather than restating
	its rules, which cover a tax category, a validity date and a net-rate band each.

	That matcher is `_get_item_tax_template`, which is private. Calling one underscore-prefixed
	function from this module is the lesser evil: the alternative is a second copy of three
	selection rules that would drift from the first, and absorbing exactly this kind of coupling
	is what `compat` is for. `test_compat` pins the dependency so a signature change fails loudly
	here instead of quietly mispricing tax.

	Reads do not grow with the item list: the tax rows come back in two queries however long it
	is, and the matcher runs over rows already in hand.
	"""
	codes = [code for code in (item_codes or []) if code]
	if not codes or not company:
		return {}
	if not frappe.db.exists("DocType", "Item Tax Template"):
		return {}
	# The ordinary case on a site nobody has set tax up on, answered without touching the item
	# list at all.
	if not frappe.db.count("Item Tax Template", {"company": company, "disabled": 0}):
		return {}

	try:
		from erpnext.stock.get_item_details import _get_item_tax_template, get_item_tax_map
	except ImportError:
		return {}

	own = _tax_rows_for("Item", codes)
	groups = item_groups or dict(frappe.get_all(
		"Item", filters={"name": ["in", codes]}, fields=["name", "item_group"],
		limit_page_length=0, as_list=True))

	# Every group an item might inherit from, so the rows for all of them come back together.
	lineage: dict[str, list[str]] = {}
	for group in {g for g in groups.values() if g}:
		lineage[group] = [group, *get_ancestors_of("Item Group", group)]
	group_rows = _tax_rows_for("Item Group", sorted({g for line in lineage.values() for g in line}))

	net_rates = net_rates or {}
	templates: dict[str, int] = {}
	out: dict[str, int] = {}

	for code in codes:
		taxes = own.get(code)
		if not taxes:
			for group in lineage.get(groups.get(code), []):
				if group_rows.get(group):
					taxes = group_rows[group]
					break
		if not taxes:
			continue

		args = {
			"company": company,
			"tax_category": tax_category or "",
			"posting_date": posting_date or nowdate(),
			"base_net_rate": flt(net_rates.get(code)),
		}
		template = _get_item_tax_template(args, taxes)
		if not template:
			continue

		if template not in templates:
			rates = get_item_tax_map(company, template, as_json=False) or {}
			# Summed, and rounded to the basis point. A template holding 9 and 9 answers 1800.
			templates[template] = round(sum(flt(r) for r in rates.values()) * 100)
		if templates[template]:
			out[code] = templates[template]

	return out


def _tax_rows_for(parenttype: str, parents: list[str]) -> dict[str, list]:
	"""`Item Tax` rows for these parents, keyed by parent, in one query.

	Returned as `_dict`s because ERPNext's matcher reads them as attributes.
	"""
	if not parents:
		return {}
	rows: dict[str, list] = {}
	for row in frappe.get_all(
		"Item Tax",
		filters={"parenttype": parenttype, "parent": ["in", parents]},
		fields=["parent", "item_tax_template", "tax_category", "valid_from",
		        "minimum_net_rate", "maximum_net_rate"],
		limit_page_length=0,
	):
		rows.setdefault(row.parent, []).append(frappe._dict(row))
	return rows


def get_conversion_factor(item_code: str, uom: str | None) -> float | None:
	"""How many stock units make up one `uom` of this item, or None when nobody has said.

	None and 1.0 are different answers and the caller has to be able to tell them apart. An item
	whose case size was never entered must not be measured as though a case were a single piece:
	a scheme written for two cases would then fire on two bars of soap, and the shopkeeper is
	owed a discount nobody budgeted for. The gap is reported rather than papered over.
	"""
	if not (item_code and uom):
		return None

	if uom == frappe.db.get_value("Item", item_code, "stock_uom"):
		return 1.0

	factor = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parenttype": "Item", "parent": item_code, "uom": uom},
		"conversion_factor",
	)
	return flt(factor) or None


def find_item_codes(item_group: str | None = None, brand: str | None = None) -> list[str]:
	"""Every sellable item filed under an item group or a brand, descendant groups included.

	Item Group is a tree for the same reason Territory is. A scheme written for *Detergents* is
	meant for the powders and the bars filed underneath it, not for the handful of items somebody
	happened to file on the group node itself - and matching the name alone would quietly exclude
	almost the whole catalogue, which is the failure ADR-020 describes for territories.

	Disabled items and anything not sold are left out. A slab that can only be reached by ordering
	a raw material is a tier no rep can ever reach.
	"""
	if not (item_group or brand):
		return []

	filters = {"disabled": 0, "is_sales_item": 1}
	if item_group:
		filters["item_group"] = ["in", _item_group_tree(item_group)]
	if brand:
		filters["brand"] = brand

	# Sorted so that two compiles of the same scheme produce the same list in the same order -
	# the phone and the server have to be handed the identical artifact, not an equivalent one.
	return sorted(frappe.get_all("Item", filters=filters, pluck="name"))


def _item_group_tree(item_group: str) -> list[str]:
	"""An item group and every group beneath it, by nested set bounds."""
	bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return [item_group]
	return frappe.get_all(
		"Item Group",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		pluck="name",
	)


# --------------------------------------------------------------------------------------
# sales orders — posted by the server on a rep's behalf, never by the rep
# --------------------------------------------------------------------------------------

# Where a caller's idempotency key is kept. A field order pushed twice, or retried after a
# dropped connection, must not become two company commitments - and the only place that
# survives a restart, a redeploy and a second web worker is the Sales Order itself.
SALES_ORDER_KEY_FIELD = "fm_source_key"


def _sales_order_key_column() -> str | None:
	return SALES_ORDER_KEY_FIELD if _has_column("Sales Order", SALES_ORDER_KEY_FIELD) else None


def sales_order_for_key(key: str) -> str | None:
	"""The Sales Order already posted for this key, if there is one."""
	column = _sales_order_key_column()
	if not (key and column):
		return None
	return frappe.db.get_value("Sales Order", {column: key, "docstatus": ["<", 2]}, "name")


def apply_dimension_defaults(doc) -> None:
	"""Fill the accounting dimensions a person's browser would have filled.

	**ERPNext applies a dimension's per-company default in the form, and nowhere else.**
	`dimension_tree_filter.js` calls `frm.set_value(fieldname, default_dimension)` when a document
	is opened in Desk; no server-side path does the same. So every document this app creates is
	missing defaults that the identical document typed into Desk would carry - the company's
	Location, its Branch, whatever dimensions that site has configured.

	That is invisible until something depends on it, and then it is not invisible at all. A bench
	carrying `location_based_series` makes `location` mandatory on every Sales Order, Sales Invoice
	and Delivery Note and refuses the save without it; every primary order FieldMate posted on such
	a site failed with "Select Location before Saving", a message about a field the rep has never
	heard of, on a screen that offers no way to supply it.

	**Nothing here is invented and nothing is site-specific.** It reads the dimensions the site
	itself enabled and the defaults the site itself set, fills only fields the document actually
	has, and only where they are empty - so a caller that already decided a dimension keeps its
	answer. On a site with no dimensions configured it does nothing at all.

	Header only. ERPNext reads an item row's dimension where one is set and falls back to the
	header, so the header is the faithful minimum; pushing values onto every child row would be
	this layer deciding more than the browser does.
	"""
	company = doc.get("company")
	if not company:
		return

	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_dimensions,
		)

		dimensions, defaults = get_dimensions()
	except Exception:
		# A site mid-migration can have the DocType without its table, and an older ERPNext may
		# not export this at all. A missing default is not worth failing a sale over.
		frappe.log_error(title="fieldmate: reading accounting dimension defaults")
		return

	for_company = (defaults or {}).get(company) or {}
	if not for_company:
		return

	meta = doc.meta
	for dimension in dimensions or []:
		field = dimension.get("fieldname")
		value = for_company.get(field)
		if not field or not value:
			continue
		if not meta.has_field(field) or doc.get(field):
			continue
		doc.set(field, value)


def make_sales_order(payload: dict) -> str:
	"""Turn a field order into a real company commitment. Safe to call twice with one key.

	Never reached from a rep's own session. A Field Rep holds no write permission on any
	accounting document and must not be given one (ADR-004); the server decides whether the
	order is allowed and then posts it on their behalf.
	"""
	payload = dict(payload or {})
	key = payload.get("key")
	if not key:
		frappe.throw(frappe._("A Sales Order cannot be posted without an idempotency key."))

	column = _sales_order_key_column()
	if not column:
		# Refusing is the smaller failure. With nowhere to record the key, a retried sync posts
		# a second Sales Order against the same field order, and duplicate commitments are not
		# found by us - they are found at month end by somebody reconciling a ledger.
		frappe.throw(
			frappe._("Sales Order has no {0} field on this site, so an order cannot be posted "
			         "without risking a duplicate. Install the FieldMate fixtures and run "
			         "bench migrate.").format(SALES_ORDER_KEY_FIELD)
		)

	existing = sales_order_for_key(key)
	if existing:
		return existing

	doc = frappe.new_doc("Sales Order")
	doc.set(column, key)
	doc.customer = payload.get("customer")
	doc.company = payload.get("company")
	doc.transaction_date = payload.get("transaction_date") or nowdate()
	doc.delivery_date = payload.get("delivery_date") or doc.transaction_date
	doc.order_type = payload.get("order_type") or "Sales"
	# `payment_terms_template` is here for a season booking: ERPNext builds the Sales Order's
	# payment schedule from it, which is where an advance and a balance due date come from.
	for field in ("currency", "selling_price_list", "po_no", "set_warehouse", "taxes_and_charges",
	              "payment_terms_template"):
		if payload.get(field):
			doc.set(field, payload[field])

	# Accounting dimensions the caller settled itself, written only where the site actually has
	# the column. A dimension is a Custom Field that exists because somebody enabled it, so on a
	# site that never did, `location` is not a field at all - setting it would put a stray key on
	# the document and say nothing, which is the quiet kind of wrong.
	#
	# Set before `apply_dimension_defaults` runs, so a choice always beats a default.
	for field in ("location",):
		if payload.get(field) and doc.meta.has_field(field):
			doc.set(field, payload[field])

	# Naming a tax template does not fill the tax rows. The Desk form fetches them when somebody
	# picks one in the field; a document inserted from the server gets the name written, no rows,
	# and a grand total equal to the net - a Sales Order that says it is taxed and is not, which
	# is worse than one that refuses. ERPNext's own expander is called rather than a copy of it.
	if doc.get("taxes_and_charges") and not doc.get("taxes"):
		from erpnext.controllers.accounts_controller import get_taxes_and_charges
		for row in get_taxes_and_charges(
			"Sales Taxes and Charges Template", doc.taxes_and_charges) or []:
			doc.append("taxes", row)

	# Every rupee in this cart was already settled by the scheme engine, from a spec the rep
	# saw on the phone (SCHEME_SPEC). Letting ERPNext's Pricing Rules run again would discount
	# the same cart a second time, and the invoice would not be the number that was promised.
	doc.ignore_pricing_rule = 1

	for line in payload.get("items") or []:
		rate = flt(line.get("rate"))
		doc.append("items", {
			"item_code": line.get("item_code"),
			"qty": flt(line.get("qty")),
			"uom": line.get("uom"),
			"conversion_factor": flt(line.get("conversion_factor")) or 1,
			"rate": rate,
			"price_list_rate": flt(line.get("price_list_rate")) or rate,
			"warehouse": line.get("warehouse"),
			"delivery_date": line.get("delivery_date") or doc.delivery_date,
			# Free goods bill at zero and stay visible as free goods, rather than arriving as a
			# hundred-percent discount that nobody downstream can explain.
			"is_free_item": cint(line.get("is_free_item")),
		})

	# Posted by the server, as the server. The docstring above has always said this happens "on
	# the rep's behalf"; until now it happened in the rep's own session, and did not work.
	#
	# `doc.flags.ignore_permissions` covers the Sales Order and nothing else. ERPNext checks
	# permissions again *inside* validation: `set_missing_item_details` calls `get_item_details`,
	# which calls `check_permission()` on the **Item** - a different document, with flags of its
	# own that nothing here can reach. A Field Rep holds no read on Item, so submitting an order
	# for a directly-billed outlet raised a bare `PermissionError` out of the framework. That is
	# the failure this codebase keeps calling out by name: a framework error on a rep's screen,
	# with nothing on it that names a cause or a remedy.
	#
	# `frappe.flags.ignore_permissions` does not help either - `frappe.permissions.has_permission`
	# never consults it. Administrator is the only short-circuit it has, so the session is swapped
	# for the posting and put back in a `finally`. The Sales Order's `owner` is then the server
	# rather than the rep, which is the truth: the rep proposed it and the server committed it,
	# and `fm_source_key` names the FieldMate Order that says who proposed it.
	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc.flags.ignore_permissions = True
		apply_dimension_defaults(doc)
		doc.insert()
		doc.submit()
	finally:
		frappe.set_user(was)
	return doc.name


# --------------------------------------------------------------------------------------
# dispatch — the goods leaving, and the bill that follows them
# --------------------------------------------------------------------------------------
#
# **Not a Pick List.** The plan this phase follows says "Pick List and Delivery Trip from the
# reserved Sales Orders", and ERPNext will not do that: `create_pick_list` refuses outright for a
# Sales Order carrying reserved stock -
#
#     "Cannot create a pick list for Sales Order {0} because it has reserved stock.
#      Please unreserve the stock in order to create a pick list."
#
# Reservation and picking are two *alternative* ways of promising stock in ERPNext, not two steps
# of one. The reserved path goes straight to a Delivery Note built from the reservations, which is
# what `for_reserved_stock` does: it reads the Stock Reservation Entries and sets the line
# quantities from what was actually held. Allocating and then picking would mean giving the
# allocation back first, which is the one thing a dispatch must not do.


def _key_column(doctype: str) -> str | None:
	"""Where this doctype keeps our idempotency key, if the field has been installed."""
	return SALES_ORDER_KEY_FIELD if _has_column(doctype, SALES_ORDER_KEY_FIELD) else None


def posted_for_key(doctype: str, key: str) -> str | None:
	"""The document already posted for this key, if there is one. Not a cancelled one."""
	column = _key_column(doctype)
	if not (key and column):
		return None
	return frappe.db.get_value(doctype, {column: key, "docstatus": ["<", 2]}, "name")


def _assert_keyed(doctype: str) -> str:
	column = _key_column(doctype)
	if not column:
		frappe.throw(
			frappe._("{0} has no {1} field on this site, so it cannot be posted without risking "
			         "a duplicate. Install the FieldMate fixtures and run bench migrate.")
			.format(doctype, SALES_ORDER_KEY_FIELD)
		)
	return column


def make_delivery_note(sales_order: str, key: str, posting_date=None) -> str | None:
	"""Ship what is reserved against this Sales Order. Safe to call twice with one key.

	Returns the Delivery Note, or None where there is nothing left to ship - an order already
	delivered in full is the ordinary state of a dispatch run somebody restarted, not an error.

	Built `for_reserved_stock`, so the quantities are the ones allocation actually held rather
	than the ones the party asked for. A booking served short gets a Delivery Note for what it
	was given, which is the whole point of having allocated.
	"""
	column = _assert_keyed("Delivery Note")

	existing = posted_for_key("Delivery Note", key)
	if existing:
		return existing

	if not reserved_for_sales_order(sales_order):
		return None

	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note as _from_so

	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		note = _from_so(sales_order, kwargs={"for_reserved_stock": True})
		if not note.get("items"):
			return None
		note.set(column, key)
		if posting_date:
			note.set_posting_time = 1
			note.posting_date = posting_date
		note.flags.ignore_permissions = True
		apply_dimension_defaults(note)
		note.insert()
		note.submit()
	finally:
		frappe.set_user(was)

	return note.name


def make_sales_invoice(delivery_note: str, key: str, allocate_advances: bool = False) -> str | None:
	"""Bill a Delivery Note. Safe to call twice with one key.

	Submitted, because an invoice sitting in draft is a sale nobody has recorded - and the
	whole reason a primary sale is ours is that it reaches the ledger.

	`allocate_advances` sets **ERPNext's own switch**, which makes it run `set_advances()` during
	validate and put the party's outstanding advance Payment Entries against this invoice. Off by
	default, so nothing that bills without asking changes behaviour; a season dispatch asks,
	because a party that paid an advance in November and is billed in February would otherwise
	receive an invoice for the whole amount with their own money sitting unallocated on their
	account - an overstated receivable that somebody has to journal by hand.

	Deliberately ERPNext's switch rather than advance rows of our own: which advance covers which
	invoice, in which currency, to what exchange gain, is accounting ERPNext already does, and a
	second implementation of it here would be a second answer to reconcile.
	"""
	column = _assert_keyed("Sales Invoice")

	existing = posted_for_key("Sales Invoice", key)
	if existing:
		return existing

	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as _from_dn

	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		invoice = _from_dn(delivery_note)
		if not invoice.get("items"):
			return None
		invoice.set(column, key)
		if allocate_advances:
			invoice.allocate_advances_automatically = 1
		invoice.flags.ignore_permissions = True
		apply_dimension_defaults(invoice)
		invoice.insert()
		invoice.submit()
	finally:
		frappe.set_user(was)

	return invoice.name


def make_delivery_trip(delivery_notes: list[str], key: str, vehicle: str, departure_time,
                       **fields) -> str | None:
	"""One vehicle, several drops. Safe to call twice with one key.

	`vehicle` and `departure_time` are required because ERPNext requires them - a Delivery Trip
	will not save without them, draft or not. That is the right rule and worth passing on rather
	than working around: a trip is a specific van leaving at a specific time, and one without
	either is a list of addresses.

	Left as a **draft**, unlike everything else here. The route is still being planned, the
	driver may not be assigned, and submitting it says the trip is happening when nobody has
	agreed to drive it.
	"""
	column = _assert_keyed("Delivery Trip")

	existing = posted_for_key("Delivery Trip", key)
	if existing:
		return existing

	notes = [name for name in (delivery_notes or []) if name]
	if not notes:
		return None

	if not (vehicle and departure_time):
		frappe.throw(frappe._(
			"A delivery trip needs a vehicle and a departure time. ERPNext will not save one "
			"without them, and neither should we - a trip without either is a list of "
			"addresses."))

	from erpnext.stock.doctype.delivery_note.delivery_note import make_delivery_trip as _from_dn

	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		trip = _from_dn(notes[0])
		for extra in notes[1:]:
			other = _from_dn(extra)
			for stop in other.get("delivery_stops") or []:
				trip.append("delivery_stops", stop.as_dict(no_default_fields=True))
		trip.set(column, key)
		trip.vehicle = vehicle
		trip.departure_time = departure_time
		for field, value in fields.items():
			if value:
				trip.set(field, value)
		trip.flags.ignore_permissions = True
		apply_dimension_defaults(trip)
		trip.insert()
	finally:
		frappe.set_user(was)

	return trip.name


# --------------------------------------------------------------------------------------
# stock reservation — ERPNext holds the stock, we only say who gets it
# --------------------------------------------------------------------------------------
#
# A season's allocation is a FieldMate decision; the **record** of it is ERPNext's. There is no
# FieldMate Allocation doctype and there should not be one: a second table of who-gets-what would
# be a second answer to a question the warehouse already answers, and the two would disagree the
# first time somebody delivered something. The Stock Reservation Entry is the record, reverting
# is cancelling it, and a figure nobody can tie back to a reservation is not an allocation.
#
# Everything below is guarded on the feature being switched on. `enable_stock_reservation` is off
# on a fresh ERPNext, and a site that has not switched it on should be told that plainly rather
# than find allocation quietly doing nothing.


def stock_reservation_enabled() -> bool:
	"""Is ERPNext's stock reservation switched on for this site?"""
	try:
		return bool(cint(frappe.db.get_single_value("Stock Settings", "enable_stock_reservation")))
	except Exception:
		# A version of ERPNext without the setting at all. Treated as off rather than as an
		# error: the rest of the app has nothing to do with reservation and must keep working.
		return False


def available_to_reserve(item_code: str, warehouse: str) -> float:
	"""Actual qty less what is already reserved, for one item in one warehouse.

	ERPNext's own figure, not a count of our own. What is physically there and what is already
	promised are both its business, and a second opinion about either is how an allocation comes
	to promise stock twice.
	"""
	if not (item_code and warehouse) or not stock_reservation_enabled():
		return 0.0

	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		get_available_qty_to_reserve,
	)

	return flt(get_available_qty_to_reserve(item_code, warehouse))


def reserve_for_sales_order(sales_order: str, lines: list[dict]) -> int:
	"""Reserve stock against named Sales Order lines. Returns how many entries were made.

	`lines` is `[{"sales_order_item": ..., "warehouse": ..., "qty": ...}]`. ERPNext decides
	whether each one can be met; a line it cannot meet is simply not reserved, which is the
	right behaviour for an allocation - the point of allocating short stock is that somebody
	gets less than they asked for.

	Posted as Administrator for the same reason a Sales Order is: reserving stock is a warehouse
	action and no field role holds write on it (ADR-004).
	"""
	if not lines or not stock_reservation_enabled():
		return 0

	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		create_stock_reservation_entries_for_so_items,
	)

	details = [
		{"sales_order_item": row["sales_order_item"], "warehouse": row["warehouse"],
		 "qty_to_reserve": flt(row["qty"])}
		for row in lines if flt(row.get("qty")) > 0
	]
	if not details:
		return 0

	before = len(reserved_for_sales_order(sales_order))
	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Sales Order", sales_order)
		doc.flags.ignore_permissions = True
		create_stock_reservation_entries_for_so_items(doc, items_details=details, notify=False)
	finally:
		frappe.set_user(was)

	return len(reserved_for_sales_order(sales_order)) - before


def reserved_for_sales_order(sales_order: str) -> list[dict]:
	"""What is reserved against this Sales Order right now, per line."""
	if not sales_order or not stock_reservation_enabled():
		return []

	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		get_sre_details_for_voucher,
	)

	return get_sre_details_for_voucher("Sales Order", sales_order) or []


def release_reservations(sales_order: str) -> int:
	"""Cancel every reservation against this Sales Order. Returns how many went.

	Safe to call on an order with none - reverting an allocation that was never applied is the
	ordinary state of a Desk button somebody pressed twice, not an error worth raising.

	Anything already delivered is left alone: ERPNext excludes a Delivered entry from the list,
	and stock that has gone out of the door is not something an allocation can take back.
	"""
	if not sales_order or not stock_reservation_enabled():
		return 0

	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		cancel_stock_reservation_entries,
	)

	held = reserved_for_sales_order(sales_order)
	if not held:
		return 0

	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		cancel_stock_reservation_entries(
			voucher_type="Sales Order", voucher_no=sales_order, notify=False)
	finally:
		frappe.set_user(was)

	return len(held)


def _cancel_if_submitted(doctype: str, name: str) -> None:
	"""Cancel a submitted ERPNext document, and say nothing if there is nothing to cancel.

	A cancel that has already happened is the ordinary state after a retried sync, not an error
	worth raising at anybody - so a missing document and a draft or already-cancelled one are
	both answered with silence.
	"""
	if not name or not frappe.db.exists(doctype, name):
		return
	if frappe.db.get_value(doctype, name, "docstatus") != 1:
		return

	doc = frappe.get_doc(doctype, name)
	doc.flags.ignore_permissions = True
	doc.cancel()


def cancel_sales_order(name: str) -> None:
	"""Cancel the commitment behind a cancelled field order. Safe to call twice.

	Gate 4 asks that cancelling a FieldMate Order leaves no orphan Sales Order behind.
	"""
	_cancel_if_submitted("Sales Order", name)


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
	"""Mirror the open or close of a FieldMate Day into HRMS attendance.

	Returns the Employee Checkin name, or None when hrms is absent — FieldMate must keep working
	on a bench without it.
	"""
	if not is_installed("hrms"):
		return None

	# An Employee Checkin whose employee does not exist is worse than no checkin at all: it
	# lands in HR reporting as a real attendance row that nobody can trace back to a person.
	# A stale link on a field user must degrade to silence, not to garbage.
	if not employee or not frappe.db.exists("Employee", employee):
		frappe.logger("fieldmate").warning(
			f"skipped attendance mirror: employee {employee!r} does not exist"
		)
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
# expense claims — the only crossing that pays a person rather than a party
# --------------------------------------------------------------------------------------

EXPENSE_CLAIM_KEY_FIELD = "fm_source_key"


def _expense_key_column() -> str | None:
	if not is_installed("hrms") or not frappe.db.exists("DocType", "Expense Claim"):
		return None
	return EXPENSE_CLAIM_KEY_FIELD \
		if _has_column("Expense Claim", EXPENSE_CLAIM_KEY_FIELD) else None


def expense_claim_for_key(key: str) -> str | None:
	column = _expense_key_column()
	if not (key and column):
		return None
	return frappe.db.get_value("Expense Claim", {column: key, "docstatus": ["<", 2]}, "name")


def _expense_claim_type(name: str) -> str | None:
	"""An Expense Claim Type matching ours, or any that exists.

	Falling back rather than creating one: an Expense Claim Type carries account defaults per
	company, and a row this app invented would post to whatever Frappe guessed. Better to use
	what the site's finance people already set up, and to say so when there is nothing.
	"""
	if frappe.db.exists("Expense Claim Type", name):
		return name
	return frappe.db.get_value("Expense Claim Type", {}, "name")


def make_expense_claim(payload: dict) -> str | None:
	"""Pay a rep for a day in the market. Safe to call twice with one key.

	Returns None where HRMS is not installed, rather than throwing. A site running FieldMate
	before HRMS still has reps owed money; the FieldMate claim records that it was approved and
	settled, and somebody pays it by hand. Refusing would be the worse answer - it would make
	the app unusable on exactly the sites that adopt it first.
	"""
	payload = dict(payload or {})
	key = payload.get("key")
	if not key:
		frappe.throw(frappe._("An expense claim cannot be posted without an idempotency key."))

	if not is_installed("hrms") or not frappe.db.exists("DocType", "Expense Claim"):
		return None

	column = _expense_key_column()
	if not column:
		frappe.throw(
			frappe._("Expense Claim has no {0} field on this site, so a settlement cannot be "
			         "posted without risking a duplicate. Run bench migrate.")
			.format(EXPENSE_CLAIM_KEY_FIELD))

	existing = expense_claim_for_key(key)
	if existing:
		return existing

	employee = payload.get("employee")
	if not employee:
		# No Employee, no HR document. The FieldMate claim still settles and says so.
		return None

	claim_type = _expense_claim_type(payload.get("expense_type") or "Travel")
	if not claim_type:
		frappe.throw(
			frappe._("This site has no Expense Claim Type set up, so an approved claim has "
			         "nothing to post against. Create one before settling claims."))

	amount = flt(payload.get("amount"))
	if amount <= 0:
		frappe.throw(frappe._("An expense claim for nothing is not an expense claim."))

	doc = frappe.new_doc("Expense Claim")
	doc.set(column, key)
	doc.employee = employee
	doc.company = payload.get("company")
	doc.posting_date = payload.get("posting_date") or nowdate()
	doc.expense_approver = payload.get("approver")
	doc.append("expenses", {
		"expense_date": payload.get("posting_date") or nowdate(),
		"expense_type": claim_type,
		"amount": amount,
		"sanctioned_amount": amount,
		"description": payload.get("description"),
	})

	doc.flags.ignore_permissions = True
	apply_dimension_defaults(doc)
	doc.insert()
	# Left as a draft on purpose. Submitting an Expense Claim books a liability and, on many
	# sites, runs an approval workflow of its own that this app has no business short-circuiting.
	# FieldMate says what is owed; HR decides when it is payable.
	return doc.name


def cancel_expense_claim(name: str) -> None:
	"""Withdraw a settlement. Safe to call twice."""
	if not name or not frappe.db.exists("Expense Claim", name):
		return
	doc = frappe.get_doc("Expense Claim", name)
	doc.flags.ignore_permissions = True
	if doc.docstatus == 1:
		doc.cancel()
	elif doc.docstatus == 0:
		frappe.delete_doc("Expense Claim", name, force=True, ignore_permissions=True)


# --------------------------------------------------------------------------------------
# credit notes — the one accounting document an approved distributor claim produces
# --------------------------------------------------------------------------------------

CREDIT_NOTE_KEY_FIELD = "fm_source_key"


def _credit_note_key_column() -> str | None:
	return CREDIT_NOTE_KEY_FIELD if _has_column("Sales Invoice", CREDIT_NOTE_KEY_FIELD) else None


def credit_note_for_key(key: str) -> str | None:
	"""The credit note already raised for this key, if there is one."""
	column = _credit_note_key_column()
	if not (key and column):
		return None
	return frappe.db.get_value(
		"Sales Invoice", {column: key, "is_return": 1, "docstatus": ["<", 2]}, "name")


def make_credit_note(payload: dict) -> str:
	"""Credit an approved claim to the distributor. Safe to call twice with one key.

	One line, not one per SKU. The goods went to the distributor at full price and that sale
	stands; what is being settled here is the cost of a promise a rep made at a shop counter out
	of the distributor's stock. Crediting the SKUs would restate product revenue for a return
	that never happened, and - with `update_stock` off - would do it while putting no goods back,
	which is the worst of both readings.

	`update_stock` is off for the same reason every other secondary document in this app posts no
	stock (ADR-023, ADR-024): the stock was the distributor's from primary billing onward.
	"""
	payload = dict(payload or {})
	key = payload.get("key")
	if not key:
		frappe.throw(frappe._("A credit note cannot be posted without an idempotency key."))

	column = _credit_note_key_column()
	if not column:
		# Same refusal as the other two adapters, for the same reason: with nowhere to keep the
		# key, an approval clicked twice credits the distributor twice, and nobody at our end
		# finds it until a month-end reconciliation does.
		frappe.throw(
			frappe._("Sales Invoice has no {0} field on this site, so a claim cannot be settled "
			         "without risking a duplicate credit. Run bench migrate.")
			.format(CREDIT_NOTE_KEY_FIELD)
		)

	existing = credit_note_for_key(key)
	if existing:
		return existing

	item_code = payload.get("item_code")
	if not item_code:
		frappe.throw(
			frappe._("No settlement item is set in FieldMate Settings, so an approved claim has "
			         "nothing to credit against. Set one before settling claims.")
		)

	amount = flt(payload.get("amount"))
	if amount <= 0:
		frappe.throw(frappe._("A credit note for nothing is not a credit note."))

	doc = frappe.new_doc("Sales Invoice")
	doc.set(column, key)
	doc.is_return = 1
	doc.customer = payload.get("customer")
	doc.company = payload.get("company")
	doc.posting_date = payload.get("posting_date") or nowdate()
	doc.set_posting_time = 1
	doc.update_stock = 0
	# The scheme engine already decided every rupee of this (SCHEME_SPEC). A Pricing Rule running
	# over the settlement line would discount a discount.
	doc.ignore_pricing_rule = 1
	for field in ("currency", "cost_center", "remarks", "po_no"):
		if payload.get(field):
			doc.set(field, payload[field])

	# A return carries negative quantities. Rate stays positive: ERPNext multiplies the two, and
	# a negative rate on a negative qty credits nobody.
	line = {
		"item_code": item_code,
		"qty": -1,
		"rate": amount,
		"description": payload.get("description") or "FieldMate scheme claim settlement",
	}
	for field in ("income_account", "cost_center"):
		if payload.get(field):
			line[field] = payload[field]
	doc.append("items", line)

	doc.flags.ignore_permissions = True
	apply_dimension_defaults(doc)
	doc.insert()
	doc.submit()
	return doc.name


def cancel_credit_note(name: str) -> None:
	"""Reverse a settled claim. Safe to call twice."""
	_cancel_if_submitted("Sales Invoice", name)


# --------------------------------------------------------------------------------------
# payments — posted only when a deposit is confirmed, and only for money that was ours
# --------------------------------------------------------------------------------------

PAYMENT_ENTRY_KEY_FIELD = "fm_source_key"


def _payment_key_column() -> str | None:
	return PAYMENT_ENTRY_KEY_FIELD if _has_column("Payment Entry", PAYMENT_ENTRY_KEY_FIELD) else None


def payment_entry_for_key(key: str) -> str | None:
	"""The Payment Entry already posted for this key, if there is one."""
	column = _payment_key_column()
	if not (key and column):
		return None
	return frappe.db.get_value("Payment Entry", {column: key, "docstatus": ["<", 2]}, "name")


def make_payment_entry(payload: dict) -> str:
	"""Credit a customer for money that has actually arrived. Safe to call twice with one key.

	Reached only from `collection.confirm_deposit`, and only for a collection taken from a
	**distributor** (ADR-025). A shop's cash belongs to its distributor and never becomes a
	receipt of ours, so it never reaches this function at all.

	Never called from a rep's session either. A Field Rep holds no permission on Payment Entry
	and must not be given one (ADR-004) - Gate 6 criterion 2 checks exactly that.
	"""
	payload = dict(payload or {})
	# Either name. `make_sales_order`, `make_credit_note` and `make_expense_claim` all read
	# `key`; this one alone read `fm_source_key`, which is the name of the column the key ends up
	# in rather than the name of the argument. A caller that copied the wrong sibling got a
	# throw, and that is exactly how every directly-billed Sales Order failed for a whole phase.
	key = payload.pop("key", None) or payload.pop("fm_source_key", None)
	if not key:
		frappe.throw(frappe._("A Payment Entry cannot be posted without an idempotency key."))

	column = _payment_key_column()
	if not column:
		# Refused rather than posted blind. Without somewhere to keep the key, a retried
		# confirmation pays the same money twice and nothing on the site can tell.
		frappe.throw(
			frappe._("Payment Entry has no {0} field on this site, so a retried deposit could "
			         "pay twice. Install the FieldMate custom fields and try again.")
			.format(PAYMENT_ENTRY_KEY_FIELD)
		)

	existing = payment_entry_for_key(key)
	if existing:
		return existing

	references = payload.pop("references", None) or []
	doc = frappe.new_doc("Payment Entry")
	doc.payment_type = "Receive"
	doc.party_type = payload.get("party_type") or "Customer"
	doc.party = payload["party"]
	doc.company = payload.get("company")
	doc.posting_date = payload.get("posting_date")
	doc.paid_amount = flt(payload.get("paid_amount"))
	doc.received_amount = flt(payload.get("paid_amount"))
	doc.reference_no = payload.get("reference_no")
	doc.reference_date = payload.get("reference_date")
	if payload.get("mode_of_payment") and frappe.db.exists(
		"Mode of Payment", payload["mode_of_payment"]
	):
		doc.mode_of_payment = payload["mode_of_payment"]
	doc.set(column, key)

	for reference in references:
		doc.append("references", {
			"reference_doctype": reference["reference_doctype"],
			"reference_name": reference["reference_name"],
			"allocated_amount": flt(reference.get("allocated_amount")),
		})

	# Where the money landed. ERPNext fills the party side itself but not this one, and without
	# it the document fails on an exchange rate that has nothing to do with the real problem.
	doc.paid_to = payload.get("paid_to") or _deposit_account(doc.company, payload.get("bank_account"))
	if not doc.paid_to:
		frappe.throw(
			frappe._("{0} has no default bank or cash account, so there is nowhere to record the "
			         "money as having arrived.").format(doc.company)
		)

	doc.setup_party_account_field()
	doc.set_missing_values()

	# One currency on both sides is the ordinary case and ERPNext still wants the rates stated.
	# Left at zero it refuses with "Target Exchange Rate is mandatory", which names neither the
	# account nor the currency and sends whoever reads it looking in the wrong place.
	company_currency = frappe.db.get_value("Company", doc.company, "default_currency")
	if doc.get("paid_from_account_currency") == company_currency:
		doc.source_exchange_rate = doc.source_exchange_rate or 1
	if doc.get("paid_to_account_currency") == company_currency:
		doc.target_exchange_rate = doc.target_exchange_rate or 1

	doc.flags.ignore_permissions = True
	apply_dimension_defaults(doc)
	doc.insert()
	doc.submit()
	return doc.name


def _deposit_account(company: str, bank_account: str | None = None) -> str | None:
	"""The GL account the money arrived in.

	A named Bank Account first, because that is what the rep actually declared; then the
	company's own defaults. Queried rather than imported - this is plain data and an ERPNext
	helper here would be one more thing that can move between majors (compat rule 4).
	"""
	if bank_account:
		account = frappe.db.get_value("Bank Account", bank_account, "account")
		if account:
			return account

	for field in ("default_bank_account", "default_cash_account"):
		account = frappe.db.get_value("Company", company, field)
		if account:
			return account

	return frappe.db.get_value(
		"Account",
		{"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
		"name",
	)


def cancel_payment_entry(name: str) -> None:
	"""Reverse a posted receipt - a bounced cheque, or a deposit withdrawn.

	Quiet where the document is already gone or already cancelled: a bounce recorded twice is a
	rep pressing a button twice, not an error worth showing anybody.
	"""
	if not name or not frappe.db.exists("Payment Entry", name):
		return
	doc = frappe.get_doc("Payment Entry", name)
	if doc.docstatus != 1:
		return
	doc.flags.ignore_permissions = True
	doc.cancel()


# --------------------------------------------------------------------------------------
# Deliberately not yet implemented
# --------------------------------------------------------------------------------------
# make_credit_note() -> Phase 9, added with FieldMate Claim
#
# Left out rather than stubbed. An adapter written against a signature nobody has verified is
# worse than no adapter: it looks finished and fails at the worst moment.
