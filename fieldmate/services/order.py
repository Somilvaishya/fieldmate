"""Orders: pricing a cart, recording it, and handing it to whoever actually fulfils it.

The thing to understand before changing anything here is **where an order goes**. A rep booking
at a kirana shop is making a *secondary* sale: the distributor delivers it out of their own stock
and bills the shop themselves. Our books never see it. So submitting a `FieldMate Order` routes it
to that distributor's queue and stops — no Sales Order, no Sales Invoice, no GL Entry, no stock
movement (ADR-023). The company's own revenue event happens one step later, when the distributor
places a *primary* order on us, and that is a different document entirely.

One case puts us on the other side of the counter — an outlet we genuinely invoice direct — and
there an ERPNext document is correct. That question is asked once, of
`credit.we_are_the_seller()`, and branched on once, in `route()`. There is deliberately no second
place in this module that decides who sells.

The second thing to understand is **who computes the money**. The phone does, at the counter, with
no signal, because the rep has to say a number out loud before there is anything to ask. The server
then computes it again from its own prices and its own compiled schemes, and overwrites. It keeps
what the phone said in `proposed_net_total` and records agreement in `totals_match`. Divergence is
never blocked — the shopkeeper already heard a figure, and what we need is to know which shop heard
which one, not to fail a sync in a market.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from fieldmate import compat
from fieldmate.services import credit as credit_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import scheme_compile
from fieldmate.services import season as season_service

# A booking that has been taken and is waiting for the money that releases it. Its own status
# rather than Pending Approval: nobody is deciding anything, and a manager looking at a queue of
# things to approve should not find orders in it that they cannot act on.
AWAITING_ADVANCE = "Awaiting Advance"

# What the rep is told when their own order needs a manager. Never an exception: a rep refused in
# front of a shopkeeper stops booking in the app at all, and then we lose the data as well as the
# order.
BREACH_ROUTED = ("This shop is over its credit limit, so your order needs your manager's "
                 "approval. It has been recorded and sent to them.")


# --------------------------------------------------------------------------------------
# pricing — pure read, writes nothing
# --------------------------------------------------------------------------------------


def estimate(outlet, lines, field_user: str | None = None, payment_term: str | None = None,
             party_type: str | None = None) -> dict:
	"""What this cart comes to, and what it does to the shop's credit. Creates no document.

	The cart screen calls this on every quantity change, so it stays a read. The phone runs the
	same arithmetic locally through `frontend/src/scheme/engine.js` and only calls this when it
	has a signal — the two agreeing to the paise is what Gate 4 measures.
	"""
	field_user = field_user or field_user_service.for_user()
	result = scheme_compile.evaluate_for(outlet, field_user, lines, party_type=party_type)

	# Cash and UPI on delivery are settled at the door, so they consume no credit. Treating them
	# as exposure blocks orders that were never a risk in the first place.
	on_credit = (payment_term or "Credit") == "Credit"
	result["credit"] = credit_service.check(
		outlet, field_user, result["totals"]["net"] if on_credit else 0, party_type
	)
	result["payment_term"] = payment_term or "Credit"
	return result


# --------------------------------------------------------------------------------------
# creating and submitting
# --------------------------------------------------------------------------------------


def create(payload: dict, field_user: str | None = None) -> dict:
	"""Record the order as a draft, priced by the server rather than by the phone."""
	field_user = field_user or field_user_service.for_user()
	if not field_user:
		frappe.throw("You are not set up as a field user yet. Ask your manager.")

	data = dict(payload or {})
	# A shop, or a party we bill ourselves. `party_type` is inferred rather than demanded, so
	# that every build of the phone already in a pocket goes on sending `outlet` and goes on
	# working; the controller settles the pair either way.
	outlet, customer = data.get("outlet"), data.get("customer")
	party_type = data.get("party_type") or ("Customer" if customer and not outlet else "Outlet")
	if party_type == "Customer":
		if not customer:
			frappe.throw("A primary order needs a party.")
	elif not outlet:
		frappe.throw("An order needs a shop.")

	# A push that already landed comes back as itself. The phone assigns identity and the server
	# honours it - the rule the whole sync spine is built on - and this was the one create in the
	# app that did not honour it. `sync.push` upserts on the uuid, so an offline order was always
	# safe; an ONLINE submit whose answer never arrived raised a raw duplicate-key error instead,
	# and the rep, told only that it had failed, retyped the cart.
	uuid = data.get("client_uuid")
	if uuid:
		existing = frappe.db.get_value("FieldMate Order", {"client_uuid": uuid}, "name")
		if existing:
			return summarise(frappe.get_doc("FieldMate Order", existing))

	lines = data.get("lines") or data.get("items") or []
	if not lines:
		frappe.throw("There is nothing in this order yet.")

	doc = frappe.new_doc("FieldMate Order")
	doc.party_type = party_type
	doc.outlet = outlet
	doc.customer = customer
	doc.field_user = field_user
	doc.order_date = data.get("order_date") or nowdate()
	doc.visit = data.get("visit")
	doc.payment_term = data.get("payment_term") or "Credit"
	doc.credit_days = cint(data.get("credit_days"))
	doc.expected_delivery_date = data.get("expected_delivery_date")
	doc.delivery_instructions = data.get("delivery_instructions")
	doc.confirmed_with = data.get("confirmed_with")
	doc.remarks = data.get("remarks")
	doc.client_uuid = data.get("client_uuid")
	doc.created_offline = cint(data.get("created_offline"))
	doc.device_id = data.get("device_id")
	doc.app_version = data.get("app_version")

	# Kept exactly as the phone sent it, and never recomputed. This is the rep's own statement of
	# what they told the shopkeeper, and it is only worth anything unedited.
	doc.proposed_net_total = flt(data.get("proposed_net_total") or data.get("net_total") or 0)

	price(doc, lines)
	doc.insert()
	return summarise(doc)


def price(doc, lines=None) -> dict:
	"""Recompute every figure on the order from the server's prices and schemes.

	Called from `create` and again from the controller's `validate`, because an order that
	arrives through the offline sync push never passes through this service at all — the push
	inserts the document directly. Without the controller path, a day of orders captured in a
	village would land with every total at zero. That exact bug shipped once on Day End.
	"""
	# A booking that has been submitted is not repriced, at all.
	#
	# Pinning the price *list* was not enough and is the wrong idea: the list is corrected between
	# November and February, so re-pricing off the same list hands the party February's rate for
	# an order they were read out in November. A commitment is a commitment - the figures on it
	# were settled when it was submitted, and `rates_locked_on` is the record of that.
	#
	# This is also why the controller can go on calling `price` from `validate` without a special
	# case: cancelling or amending a booking re-validates it, and re-validating must not quietly
	# rewrite what the party agreed to.
	if doc.rates_locked_on:
		return {}

	# Read what the rep actually entered - a count of cases against the UOM they chose - and let
	# `cart_for` convert it to base units. Reading `qty` instead would be reading a column the
	# server fills, which is empty on the way in and silently dropped the whole line.
	source = lines if lines is not None else [
		{
			"item": row.item_code,
			"qty": flt(row.qty_display) or flt(row.qty),
			"uom": row.display_uom or row.uom,
			# Carried, or a booking loses when each line was wanted every time it is repriced -
			# and the controller reprices on every save.
			"delivery_date": row.delivery_date,
		}
		for row in (doc.items or [])
		# Free goods are the engine's to grant, never an input. A line arriving already flagged
		# free is a replay of an earlier grant, and counting it here would bill the gift and then
		# hand it over a second time.
		if not cint(row.is_free_item)
	]
	party = doc.customer if doc.party_type == "Customer" else doc.outlet
	# The order date, not today, and the list this order was locked at if it has one.
	#
	# A season is booked months before it is delivered, so by delivery the season's price list
	# will have moved - and a party that booked in November is owed November's price. Once a
	# booking is submitted its list is pinned, so a later pricing pass re-states the same cart at
	# the same rates instead of quietly repricing a commitment.
	result = scheme_compile.evaluate_for(
		party, doc.field_user, source, party_type=doc.party_type, on=doc.order_date)

	doc.price_list = result.get("price_list")
	channel = result.get("channel") or {}

	# What kind of sale this is, and whether this company makes that kind at all. Until now the
	# `enable_primary_sales` and `enable_secondary_sales` settings were written, were read by
	# `channel.resolve` and gated nothing, because nothing called it. This is where they bite.
	#
	# Refused at the commit rather than earlier, like every other refusal here: a rep should see a
	# catalogue and prices at a shop they cannot currently book for, and be told why when they
	# try - not handed an empty screen with nothing on it to explain itself.
	if channel and not channel.get("allowed", True):
		frappe.throw(channel.get("reason") or frappe._("This order cannot be booked here."))

	# Who gets the bill, which `channel.resolve` has already decided: the shop's distributor on a
	# retailer order, and the party itself on a primary one. `_distributor_for` stays as the
	# fallback for an order assembled without a channel answer - a fixture, or a push from a
	# build that predates this.
	doc.distributor = doc.distributor or channel.get("party") or _distributor_for(doc.outlet)
	doc.company = doc.company or channel.get("company")

	# What kind of order this is, written onto the document. Derived here and nowhere else: the
	# party decides Secondary or Primary, and a primary order dated inside an open season is a
	# Booking of it (Phase 2). The field is read-only on the form for the same reason the totals
	# are - a rep does not get to say what kind of sale they made.
	#
	# Recomputed on every pricing pass rather than set once at insert, because an order amended
	# across a season's opening date would otherwise keep the kind it was created with.
	doc.order_kind, doc.season = season_service.kind_for(
		{**channel, "company": doc.company}, doc.order_date)

	doc.currency = doc.currency or frappe.db.get_value("Company", doc.company, "default_currency")

	if result.get("unpriced_items"):
		frappe.throw(
			"These have no price yet, so they cannot go on an order: "
			f"{', '.join(result['unpriced_items'])}. Take them out, or ask your manager to "
			"have them priced."
		)

	# Above the printed price on the pack. Refused rather than warned about: a shopkeeper cannot
	# resell at a profit above the MRP, and in India selling over it is an offence under the
	# Legal Metrology Act. It is a price list somebody has set wrong, not a decision for the rep
	# standing at the counter, so the message names the party who can fix it.
	if result.get("above_mrp_items"):
		frappe.throw(
			"These are priced above their MRP, so they cannot go on an order: "
			f"{', '.join(result['above_mrp_items'])}. Ask your manager to correct the price "
			"list."
		)

	_write_items(doc, result, source)
	# After the lines exist, not before: `_write_items` rebuilds them from the engine's answer,
	# so anything written on a row ahead of it is thrown away. Only a booking carries a date,
	# and it has to fall inside the season's delivery window - a date outside it is a promise
	# the company has not made.
	check_delivery_dates(doc)
	_write_schemes(doc, result)
	_write_totals(doc, result)
	_write_credit(doc, result)
	return result


def _write_items(doc, result: dict, source: list | None = None) -> None:
	# When each line was asked for, kept from what came in. The engine answers quantities and
	# rates and has no opinion about dates (ADR-021), so this is the only place the rep's own
	# answer survives the rebuild.
	wanted = {
		(line.get("item") or line.get("item_code")): line.get("delivery_date")
		for line in (source or [])
		if (line.get("item") or line.get("item_code")) and line.get("delivery_date")
	}

	doc.set("items", [])
	for line in result.get("lines") or []:
		row = doc.append("items", {})
		row.item_code = line["item"]
		row.item_name = line.get("item_name") or frappe.db.get_value("Item", line["item"], "item_name")
		row.qty = line["qty"]
		stock_uom = frappe.db.get_value("Item", line["item"], "stock_uom")
		row.stock_uom = stock_uom
		row.uom = line.get("uom") or stock_uom
		row.conversion_factor = flt(line.get("conversion_factor") or 1)
		row.qty_display = flt(line.get("qty_display") or line["qty"])
		# What the rep typed, which is what they will read back off the printed order. A cart
		# line is in base units by then, so with nothing to restate this is the base UOM.
		row.display_uom = line.get("display_uom") or line.get("uom") or stock_uom
		row.rate = scheme_compile.in_rupees(line["rate_paise"])
		row.price_list_rate = scheme_compile.in_rupees(line.get("price_list_paise") or line["rate_paise"])
		row.amount = scheme_compile.in_rupees(line["qty"] * line["rate_paise"])
		row.delivery_date = wanted.get(line["item"])
		row.is_free_item = 0

	# A line the rep set to zero is kept, though the engine dropped it. "Asked and declined" and
	# "never stocked here" are opposite instructions to whoever walks this route next - the first
	# is a line to stop pitching, the second is a line to pitch - and a Float cannot tell them
	# apart. This row is how the repeat-order prefill can (DESIGN.md UX requirement 8).
	priced = {row.item_code for row in (doc.items or [])}
	for line in source or []:
		code = line.get("item") or line.get("item_code")
		if not code or code in priced or flt(line.get("qty")) > 0:
			continue
		row = doc.append("items", {})
		row.item_code = code
		row.item_name = frappe.db.get_value("Item", code, "item_name")
		stock_uom = frappe.db.get_value("Item", code, "stock_uom")
		row.qty = 0
		row.qty_display = 0
		row.stock_uom = stock_uom
		row.uom = line.get("uom") or stock_uom
		row.display_uom = line.get("uom") or stock_uom
		row.conversion_factor = 1
		row.rate = 0
		row.amount = 0
		row.is_free_item = 0
		priced.add(code)

	# Free goods are their own rows at zero, never a discount folded into the bill. Netting their
	# value off would pay the shop twice for one scheme - once in stock, once in cash - and the
	# distributor would later claim for the half nobody authorised. See SCHEME_SPEC.md S9.
	doc.set("free_goods", [])
	for free in result.get("free_goods") or []:
		row = doc.append("free_goods", {})
		row.item_code = free["item"]
		row.item_name = frappe.db.get_value("Item", free["item"], "item_name")
		row.qty = free["qty"]
		row.scheme = free.get("scheme")
		row.valuation_amount = scheme_compile.in_rupees(free.get("value_paise") or 0)


def _write_schemes(doc, result: dict) -> None:
	doc.set("schemes_applied", [])
	for applied in result.get("applied") or []:
		row = doc.append("schemes_applied", {})
		row.scheme = applied["scheme"]
		row.scheme_name = applied.get("scheme_name")
		row.slab_idx = cint(applied.get("slab_idx"))
		row.benefit_amount = scheme_compile.in_rupees(applied.get("benefit_paise") or 0)
		row.budget_warning = cint(applied.get("budget_warning"))
		row.free_qty = sum(
			cint(b.get("qty")) for b in (applied.get("benefits") or [])
			if b.get("kind") == "Free Goods"
		)
		kinds = [b.get("kind") for b in (applied.get("benefits") or [])]
		row.benefit_kind = kinds[0] if kinds else None
		row.benefit_description = describe(applied)


def describe(applied: dict) -> str:
	"""The scheme in words, as the rep will say it across the counter.

	"Why did I get this discount" is the single most common field support call, and a row of
	codes answers it for nobody. DESIGN.md UX requirement 10.
	"""
	parts = []
	for benefit in applied.get("benefits") or []:
		kind, amount = benefit.get("kind"), scheme_compile.in_rupees(benefit.get("amount_paise") or 0)
		if kind == "Free Goods":
			parts.append(f"{cint(benefit.get('qty'))} free {benefit.get('item')}")
		elif kind == "Incentive":
			parts.append(f"₹{amount:,.2f} incentive")
		elif amount:
			parts.append(f"₹{amount:,.2f} off")
	return ", ".join(parts) or (applied.get("scheme_name") or "")


def _write_totals(doc, result: dict) -> None:
	totals = result["totals"]
	doc.gross_total = totals["gross"]
	doc.discount_total = totals["discount"]
	doc.net_total = totals["net"]
	doc.incentive_amount = totals["incentive"]
	# Tax is the distributor's, and FieldMate posts none of it. It is written here anyway, and
	# this is a reversal: the line used to be pinned at zero "rather than pretending to a number
	# we have no authority over". That was right about authority and wrong about silence. We have
	# no authority to *charge* it; we have every reason to say it, because `stores/order.js` sets
	# the cart one job - the number the rep says out loud has to be the number on the invoice the
	# distributor raises that evening - and that invoice carries GST. A rep quoting the net and a
	# shopkeeper receiving a bill eighteen per cent higher are having an argument nobody can
	# settle, about a figure this app had and did not show. See `services/tax`.
	doc.tax_total = totals.get("tax") or 0
	doc.grand_total = flt(doc.net_total) + flt(doc.tax_total)
	doc.total_lines = len(doc.items or [])
	doc.total_qty = sum(flt(row.qty) for row in (doc.items or []))

	# The phone and the server are supposed to agree to the paise. When they do not, the order
	# still stands at the server's figure - but this flag plus app_version is what turns "a build
	# in the field has drifted" from a rumour into a report a manager can run.
	proposed = flt(doc.proposed_net_total or 0)
	doc.totals_match = 1 if (not proposed or abs(proposed - flt(doc.net_total)) < 0.005) else 0


def _write_credit(doc, result: dict) -> None:
	on_credit = (doc.payment_term or "Credit") == "Credit"
	party = doc.customer if doc.party_type == "Customer" else doc.outlet
	position = credit_service.check(party, doc.field_user,
	                                doc.net_total if on_credit else 0, doc.party_type)

	doc.credit_limit_at_order = flt(position.get("limit") or 0)
	doc.outstanding_at_order = flt(position.get("outstanding") or 0)

	breached = position.get("status") == credit_service.BREACH
	if doc.credit_status not in ("Overridden", "Approved"):
		doc.credit_status = "Breach" if breached else "Within Limit"

	rule = pick_approval_rule(doc) if breached or _over_value(doc) else None
	doc.approval_required = 1 if rule else 0
	doc.approval_rule = rule
	if rule and doc.approval_status in (None, "", "Not Required"):
		doc.approval_status = "Pending"
	elif not rule and doc.approval_status in (None, ""):
		doc.approval_status = "Not Required"


def _over_value(doc) -> bool:
	return False if not doc.net_total else bool(pick_approval_rule(doc))


def pick_approval_rule(doc) -> str | None:
	"""The first rule that catches this order, lowest priority number first.

	Priority ascends the same way the scheme engine's does. Holding two opposite conventions in
	one app is how somebody eventually reads one of them backwards.
	"""
	outlet = frappe.db.get_value(
		"FieldMate Outlet", doc.outlet, ["territory", "channel", "outlet_class"], as_dict=True
	) or frappe._dict()

	for rule in frappe.get_all(
		"FieldMate Order Approval Rule",
		filters={"is_active": 1},
		fields=["name", "priority", "territory", "channel", "outlet_class",
		        "check_order_value", "min_order_value", "on_credit_breach"],
		order_by="priority asc, name asc",
	):
		if rule.territory and rule.territory != outlet.territory:
			continue
		if rule.channel and rule.channel != outlet.channel:
			continue
		if rule.outlet_class and rule.outlet_class != outlet.outlet_class:
			continue
		if cint(rule.on_credit_breach) and doc.credit_status == "Breach":
			return rule.name
		# The paired check_* switch matters: a Currency column stores 0 for "never set", so an
		# unswitched threshold would otherwise catch every order ever booked.
		if cint(rule.check_order_value) and flt(doc.net_total) >= flt(rule.min_order_value) > 0:
			return rule.name
	return None


def submit_order(name: str) -> dict:
	"""Commit the order and hand it to whoever fulfils it.

	A rep holds create and read on their own orders and never write or submit (ADR-004), which is
	what keeps generic endpoints like `frappe.client.save` closed to them. Ownership is checked
	here and the server submits on their behalf.
	"""
	doc = frappe.get_doc("FieldMate Order", name)
	assert_owner(doc)

	if doc.docstatus == 1:
		return summarise(doc)

	doc.flags.ignore_permissions = True
	doc.submit()
	return summarise(frappe.get_doc("FieldMate Order", name))


def advance_position(doc) -> dict:
	"""What this booking needs up front, and what has actually arrived.

	Returned whole rather than raised, like every other verdict in this module: a rep is asked
	for an advance at a counter and has to be able to say how much, not be refused after the
	fact.

	`in_hand`, not `paid`: a post-dated cheque is allocated to the order and visible as a PDC,
	and it is not money until its date. Releasing a season booking against one means reserving
	stock and planning a dispatch on a promise.
	"""
	from fieldmate.services import collection as collection_service

	required = season_service.advance_required(doc.season, doc.net_total)
	if not required:
		return {"required": 0.0, "in_hand": 0.0, "short": 0.0, "held": False,
		        "pdc_total": 0.0, "message": ""}

	in_hand = flt(collection_service.in_hand_by_order([doc.name]).get(doc.name) or 0)
	pdc_total = sum(flt(row["amount"]) for row in collection_service.pdcs_for(doc.name))
	short = flt(max(0.0, required - in_hand), 2)

	message = ""
	if short:
		message = frappe._(
			"This booking needs {0} up front and {1} has been received. It is held until the "
			"balance of {2} is collected."
		).format(_money(required, doc.currency), _money(in_hand, doc.currency),
		         _money(short, doc.currency))
		if pdc_total:
			# Said out loud, because a rep who has taken a cheque will otherwise read the hold
			# as the office losing their paperwork.
			message += " " + frappe._(
				"{0} of post-dated cheques is held against it and does not count until it falls "
				"due.").format(_money(pdc_total, doc.currency))

	return {"required": required, "in_hand": in_hand, "short": short, "held": bool(short),
	        "pdc_total": flt(pdc_total, 2), "message": message}


def _money(value, currency: str | None) -> str:
	return frappe.utils.fmt_money(flt(value), currency=currency)


def release_if_paid(order: str) -> bool:
	"""Try the gate again for a booking that was held. Called when money lands against it.

	An advance hold is not an approval: nobody decides it, and the only thing that clears it is
	the money arriving. So this is called from the collection path rather than from the approval
	path, and it routes the order the moment the gate opens.

	Returns whether it released, so a caller can say so. Safe to call on anything - an order that
	is not a held booking is left exactly as it is.
	"""
	doc = frappe.get_doc("FieldMate Order", order)
	if doc.docstatus != 1 or doc.order_kind != season_service.BOOKING:
		return False
	if doc.order_status != AWAITING_ADVANCE:
		return False
	if advance_position(doc)["held"]:
		return False

	route(doc)
	return frappe.db.get_value("FieldMate Order", order, "order_status") != AWAITING_ADVANCE


def route(doc) -> None:
	"""Where a submitted order goes. Called from the controller's `on_submit`.

	Living in the controller and not only in `submit_order` is deliberate: an order captured with
	no signal arrives through `sync.push`, which inserts and submits the document directly and
	never touches this service. Anything that only ran here would simply not happen for the
	offline majority.
	"""
	# An order waiting on a manager goes nowhere yet.
	#
	# `_write_credit` had been recording the breach, picking the approval rule and setting
	# `approval_status` to Pending - and then this function handed the order to the distributor
	# anyway. The approval existed on the document and stopped nothing, which is the worst shape
	# a control can have: it reads as enforced in Desk and is not.
	#
	# Held before the accrual too. A rejected order that had already consumed scheme budget
	# would overstate trade spend for a sale that never happened.
	if cint(doc.approval_required) and doc.approval_status != "Approved":
		doc.db_set("order_status", "Pending Approval", update_modified=False)
		return

	# A booking waiting on its advance goes nowhere either, and it is a different kind of waiting
	# from the one above. An approval is a judgement somebody makes; an advance is money that has
	# either arrived or has not, so no manager clears this - `release_if_paid` does, when the
	# collection lands. Held before the accrual for the same reason an approval is: a booking
	# that never gets paid for must not consume scheme budget on its way past.
	waiting = advance_position(doc)
	if waiting["held"]:
		doc.db_set("order_status", AWAITING_ADVANCE, update_modified=False)
		return

	party = doc.customer if doc.party_type == "Customer" else doc.outlet
	seller = credit_service.we_are_the_seller(party, doc.field_user, doc.party_type)

	if seller["routes_to_distributor"]:
		# ADR-023. This is the whole of fulfilment in order booking: the distributor bills the
		# shop out of their own stock, and nothing about it belongs in our ledger.
		doc.db_set("order_status", "Sent To Distributor", update_modified=False)
		doc.db_set("sent_to_distributor_on", now_datetime(), update_modified=False)
	else:
		doc.db_set("order_status", "Approved", update_modified=False)
		_raise_sales_order(doc, seller)

	accrue(doc)
	roll_up_to_visit(doc)


def roll_up_to_visit(doc) -> None:
	"""Put what was ordered onto the visit it came out of.

	`FieldMate Visit.order_value` and `lines_sold` were built in Phase 3 and left at zero waiting
	for this. Leaving them there costs more than it looks: productive-call rate, strike rate and
	every coverage figure a manager reads are computed off the visit, not off the order, so a rep
	who booked all day would report as having sold nothing.

	Server-owned on the visit, so it is written directly rather than through a save - the visit
	is submitted by now and the rep holds no write on it at all.
	"""
	if not doc.visit:
		return
	orders = frappe.get_all(
		"FieldMate Order",
		filters={"visit": doc.visit, "docstatus": 1},
		fields=["net_total", "total_lines"],
	)
	frappe.db.set_value("FieldMate Visit", doc.visit, {
		"order_value": sum(flt(o.net_total) for o in orders),
		"lines_sold": sum(cint(o.total_lines) for o in orders),
	}, update_modified=False)


def check_delivery_dates(doc) -> None:
	"""A booking line is delivered inside its season's window, or not promised at all.

	Blank is allowed and means the season's first delivery day: most lines of most bookings are
	wanted as early as they can be had, and making a rep type the same date on forty lines is how
	a form stops being filled in honestly.

	An ordinary order has no window to be inside, so its lines are left alone.
	"""
	if doc.order_kind != season_service.BOOKING or not doc.season:
		return

	opens, closes = season_service.delivery_window(doc.season)
	if not opens:
		return

	for row in doc.items or []:
		if not row.delivery_date:
			row.delivery_date = opens
			continue
		if not (getdate(opens) <= getdate(row.delivery_date) <= getdate(closes)):
			frappe.throw(frappe._(
				"{0} is wanted on {1}, which is outside this season's delivery window "
				"({2} to {3})."
			).format(row.item_code, frappe.utils.formatdate(row.delivery_date),
			         frappe.utils.formatdate(opens), frappe.utils.formatdate(closes)))


def lock_rates(doc) -> None:
	"""Stop repricing this booking. Called once, when it is submitted.

	The rates are already on the lines; this records that they are now final, and `price` reads
	it to decide whether to look the list up again. Nothing is copied or recomputed here - a
	lock that recomputed would be the thing it is meant to prevent.
	"""
	if doc.order_kind != season_service.BOOKING or doc.rates_locked_on:
		return
	doc.db_set("rates_locked_on", now_datetime(), update_modified=False)


def assert_may_amend(doc) -> None:
	"""A booking stops moving at its season's change cutoff.

	The commercial point of a season is that the company can plan against the book, so after the
	cutoff the book is what it is. Checked on amend rather than on every save: the order has to
	be allowed to reach a final state on the day it is taken.
	"""
	if doc.order_kind != season_service.BOOKING or not doc.season:
		return
	allowed, why = season_service.may_amend(doc.season)
	if not allowed:
		frappe.throw(why)


def _warehouse_for(customer: str | None) -> str | None:
	"""The depot that serves this party, from `Customer.fm_warehouse`.

	A group warehouse is refused rather than passed on: ERPNext cannot reserve stock in one and
	says so with a message about group warehouses that names nothing a manager can act on. Left
	blank here, ERPNext defaults per line instead, which at least works.
	"""
	if not customer:
		return None
	warehouse = frappe.db.get_value("Customer", customer, "fm_warehouse")
	if not warehouse:
		return None
	return None if cint(frappe.get_cached_value("Warehouse", warehouse, "is_group")) else warehouse


def _earliest_delivery(doc):
	"""The header delivery date: the soonest any line is wanted, falling back to the order's own.

	ERPNext refuses a Sales Order whose header date is later than a line's, and a booking is
	exactly the document where the lines differ.
	"""
	dates = [getdate(r.delivery_date) for r in (doc.items or []) if r.delivery_date]
	fallback = getdate(doc.expected_delivery_date or doc.order_date)
	return min([*dates, fallback]) if dates else fallback


def _raise_sales_order(doc, seller: dict) -> None:
	"""The one path where an ERPNext document is correct: we are billing the shop ourselves."""
	if doc.sales_order:
		return
	name = compat.make_sales_order({
		"customer": seller["party"],
		"company": doc.company,
		"transaction_date": getdate(doc.order_date),
		# The order's own date is the earliest its lines ask for, so ERPNext's header date does
		# not sit after a line that is wanted sooner.
		"delivery_date": _earliest_delivery(doc),
		"currency": doc.currency,
		"selling_price_list": doc.price_list,
		# `compat.make_sales_order` reads this as `key` and refuses without it. Sending it under
		# the name of the column it eventually lands in meant every directly-billed order threw
		# "A Sales Order cannot be posted without an idempotency key" and none ever posted.
		"key": doc.name,
		# A season's payment terms, which ERPNext turns into the Sales Order's own payment
		# schedule. Named rather than copied: the schedule finance maintains is the one on the
		# template, and a second copy of it here is a second thing to keep in step.
		"payment_terms_template": season_service.payment_terms(doc.season),
		# Which depot serves this party. `fm_warehouse` has been on Customer since Phase 1 and
		# nothing read it; allocation is what needs it, because reserving stock means reserving
		# it *somewhere* and the somewhere is the warehouse that will actually ship.
		#
		# Blank leaves ERPNext to default per line from the Item, which is its ordinary
		# behaviour and the right fallback for a company running one warehouse.
		"set_warehouse": _warehouse_for(seller.get("party")),
		"items": [
			{"item_code": row.item_code, "qty": row.qty, "uom": row.uom, "rate": row.rate,
			 # Per line, because that is the whole point of booking a season: a party asks for
			 # part of its order in January and the rest in February, and ERPNext plans and
			 # reserves against the date it was actually asked for.
			 "delivery_date": row.delivery_date}
			for row in (doc.items or [])
		] + [
			{"item_code": row.item_code, "qty": row.qty, "uom": row.uom,
			 "rate": 0, "is_free_item": 1}
			for row in (doc.free_goods or [])
		],
	})
	doc.db_set("sales_order", name, update_modified=False)


# --------------------------------------------------------------------------------------
# the scheme ledger
# --------------------------------------------------------------------------------------


def accrue(doc) -> None:
	"""One ledger row per benefit granted, so budgets and claims reconcile to the rupee.

	A rep holds no create right on the ledger at all — it is money, and no field role writes to an
	accounting document (ADR-004). The server accrues on their behalf after the owner check that
	`submit_order` already did.
	"""
	for applied in doc.schemes_applied or []:
		if frappe.db.exists("FieldMate Scheme Ledger", {"order": doc.name, "scheme": applied.scheme}):
			continue
		entry = frappe.get_doc({
			"doctype": "FieldMate Scheme Ledger",
			"posting_date": doc.order_date,
			"scheme": applied.scheme,
			"order": doc.name,
			"outlet": doc.outlet,
			"field_user": doc.field_user,
			"distributor": doc.distributor,
			"company": doc.company,
			"currency": doc.currency,
			"benefit_kind": applied.benefit_kind,
			"benefit_amount": applied.benefit_amount,
			"free_qty": applied.free_qty,
			"status": "Accrued",
			# The order name is a natural idempotency key: a replayed push that lands the same
			# order twice must not accrue the same benefit twice.
			"client_uuid": f"{doc.name}:{applied.scheme}",
		})
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()
		_consume_budget(applied.scheme, applied.benefit_amount)


def _consume_budget(scheme: str, amount) -> None:
	"""Charge the scheme's budget, in the database rather than in Python.

	Read-modify-write loses a write the moment two reps submit against one scheme at the same
	second: both read 33, both write 66, and the scheme has paid out 66 while reporting 33. Two
	orders at one moment is not an exotic case for a field force of any size - it is a Monday
	morning. `UPDATE ... SET consumed = consumed + x` leaves the arithmetic to the row lock that
	is already there.

	The floor at zero belongs here too: a refund for a row whose scheme was reset underneath it
	must not leave a negative budget, which would then read as headroom nobody granted.
	"""
	frappe.db.sql(
		"""
		update `tabFieldMate Scheme`
		   set consumed_amount = greatest(0, ifnull(consumed_amount, 0) + %(amount)s)
		 where name = %(scheme)s
		""",
		{"amount": flt(amount), "scheme": scheme},
	)

	# Raw SQL goes round the document cache, and the scheme is read back through it: the compiled
	# spec the engine prices against carries `consumed_paise` straight off the cached document.
	# Without this the second order of the morning is priced against the first one's stale figure
	# and the budget is spent twice. Gate 4 criterion 4 caught exactly that.
	frappe.clear_document_cache("FieldMate Scheme", scheme)


def reverse(doc) -> None:
	"""Undo the accrual, and cancel the entries rather than relabelling them.

	A cancelled order that leaves its benefits behind overstates trade spend every month until
	somebody reconciles by hand. Cancelling rather than setting a status word matters for a
	second reason: a submitted ledger row LINKS to the order, so Frappe refuses to cancel the
	order while one still stands. A "Reversed" row at docstatus 1 is both a lie and a lock.

	Called before the order's own cancel, never only from `on_cancel` - by then the back-link
	check has already refused.

	The refund itself is not done here. It lives on the ledger row's own `on_cancel`, so that a
	row cancelled by Desk's linked-document cascade - which is what actually happens when
	somebody cancels an order from the desk - gives the budget back too. Doing it in both places
	would hand it back twice.
	"""
	for entry in frappe.get_all(
		"FieldMate Scheme Ledger",
		filters={"order": doc.name, "docstatus": 1},
		fields=["name"],
	):
		row = frappe.get_doc("FieldMate Scheme Ledger", entry.name)
		row.flags.ignore_permissions = True
		row.cancel()


# --------------------------------------------------------------------------------------
# cancel and approve
# --------------------------------------------------------------------------------------


# Once the depot has billed or delivered, the goods and the paperwork have moved and this is no
# longer the rep's to undo. ERPNext would refuse the underlying Sales Order anyway, but it would
# say so in its own words, about a document the rep has never seen.
DEPOT_HAS_ACTED = ("Invoiced", "Delivered")


def cancel(name: str, reason: str | None = None) -> dict:
	"""Withdraw the order from the distributor's queue and give the budget back."""
	doc = frappe.get_doc("FieldMate Order", name)
	assert_owner(doc)

	if doc.docstatus == 2:
		return summarise(doc)

	if doc.order_status in DEPOT_HAS_ACTED:
		frappe.throw(
			frappe._("The depot has already {0} this order. Ask them to raise a return - "
			         "cancelling it here would leave their paperwork with nothing behind it.")
			.format("billed" if doc.order_status == "Invoiced" else "delivered")
		)

	# Before the cancel, not after: a submitted ledger row links to this order and
	# Frappe checks for back-links before `on_cancel` ever runs.
	reverse(doc)

	doc.flags.ignore_permissions = True
	if reason:
		doc.db_set("remarks", f"{doc.remarks or ''}\nCancelled: {reason}".strip(),
		           update_modified=False)
	doc.cancel()
	return summarise(frappe.get_doc("FieldMate Order", name))


def withdraw(doc) -> None:
	"""Called from the controller's `on_cancel`, for the same reason `route` lives there."""
	doc.db_set("order_status", "Cancelled", update_modified=False)
	reverse(doc)
	roll_up_to_visit(doc)
	if doc.sales_order:
		compat.cancel_sales_order(doc.sales_order)


# The only people who may decide a breached order, over and above the rule that it is never the
# rep who booked it. Anyone holding one of these is trusted with any order in the company.
APPROVER_ROLES = ("FieldMate Admin", "FieldMate Sales Head", "System Manager")


def assert_may_approve(doc, approver: str) -> None:
	"""Who may decide an order that breached: the rep's own manager, their depot, or an admin.

	Until this existed, `approve` checked one thing - that the approver was not the rep who booked
	the order - and let any other signed-in session through. A rep could release a colleague's
	breached order, which is the whole of what the credit hold is for.

	Deliberately **their own** manager and not any manager: somebody three territories away has no
	business deciding whether this shop is good for the money. The chain is walked rather than
	taking one step, so a regional manager can act when the area manager is away.
	"""
	roles = set(frappe.get_roles(approver))
	if roles & set(APPROVER_ROLES):
		return

	mine = field_user_service.for_user(approver)
	if mine and mine in field_user_service.managers_of(doc.field_user):
		return

	# The depot the order was routed to. They carry the stock and the receivable, so they are
	# entitled to say yes to a shop they know and no to one they do not.
	from fieldmate.services import portal as portal_service

	if doc.distributor and portal_service.distributor_of(approver) == doc.distributor:
		return

	# The message names the likeliest cause. A site that has never filled in `reports_to` - which
	# is most of them on day one - would otherwise see nothing but a refusal and no way to act.
	if not field_user_service.managers_of(doc.field_user):
		frappe.throw(
			frappe._("Nobody is recorded as {0}'s manager, so there is nobody to approve this. "
			         "Set Reports To on their FieldMate Field User, or ask the distributor or an "
			         "administrator to decide.").format(doc.field_user),
			frappe.PermissionError,
		)

	frappe.throw(
		frappe._("Only {0}'s own manager, their distributor or an administrator can decide this "
		         "order.").format(doc.field_user),
		frappe.PermissionError,
	)


def approve(name: str, decision: str, remarks: str | None = None,
            approver: str | None = None) -> dict:
	"""A manager's answer on an order that breached. Never the rep's own."""
	doc = frappe.get_doc("FieldMate Order", name)
	if decision not in ("Approved", "Rejected"):
		frappe.throw("An approval is either Approved or Rejected.")

	approver = approver or frappe.session.user
	if doc.field_user == field_user_service.for_user(approver):
		frappe.throw("An order cannot be approved by the person who booked it.")

	assert_may_approve(doc, approver)

	doc.db_set("approval_status", decision, update_modified=False)
	doc.db_set("approved_by", approver, update_modified=False)
	doc.db_set("approved_on", now_datetime(), update_modified=False)
	if remarks:
		doc.db_set("approval_remarks", remarks, update_modified=False)
	doc.db_set("credit_status", "Approved" if decision == "Approved" else doc.credit_status,
	           update_modified=False)

	if decision == "Approved":
		# Release it through `route`, not by setting a status here. Routing is where the order
		# reaches the distributor's queue, where the scheme benefits accrue and where the visit
		# is rolled up - all of which were held while it waited. Writing "Approved" onto the
		# field instead would leave an approved order that nobody was ever handed.
		route(frappe.get_doc("FieldMate Order", name))
	else:
		doc.db_set("order_status", "Rejected", update_modified=False)

	return summarise(frappe.get_doc("FieldMate Order", name))


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------


def mine(field_user: str | None = None, limit: int = 50) -> list[dict]:
	field_user = field_user or field_user_service.for_user()
	return frappe.get_list(
		"FieldMate Order",
		filters={"field_user": field_user},
		# `customer` and `party_type` as well as `outlet`: a primary order has no outlet at all
		# (ADR-033), so a list selecting only the outlet drew a card with a blank name on it.
		# `tax_total` and `grand_total` because the phone's list showed `net_total` as the order's
		# value - a figure short by the whole of the GST on the bill the party actually receives.
		fields=["name", "order_date", "outlet", "party_type", "customer", "net_total",
		        "tax_total", "grand_total", "order_status", "credit_status",
		        "docstatus", "client_uuid"],
		order_by="order_date desc, creation desc",
		limit_page_length=limit,
		user=frappe.session.user,
		ignore_permissions=False,
	)


def for_distributor(distributor: str, status: str | None = None) -> list[dict]:
	"""The distributor's queue — the other end of ADR-023's pipe.

	Until the Phase 9 portal ships this is what a Desk list view and the distributor's own report
	read. It is deliberately a plain query: nothing here decides anything, it only shows what was
	already routed.
	"""
	filters = {"distributor": distributor, "docstatus": 1}
	if status:
		filters["order_status"] = status
	return frappe.get_all(
		"FieldMate Order",
		filters=filters,
		fields=["name", "order_date", "outlet", "field_user", "net_total", "total_qty",
		        "order_status", "payment_term", "expected_delivery_date", "sent_to_distributor_on"],
		order_by="sent_to_distributor_on asc",
	)


def summarise(doc) -> dict:
	return {
		"name": doc.name,
		"client_uuid": doc.client_uuid,
		"outlet": doc.outlet,
		# Which party, and which kind. An empty `outlet` is not missing data on a primary order -
		# it is what a primary order looks like.
		"party_type": doc.party_type,
		"customer": doc.customer,
		"order_date": str(doc.order_date) if doc.order_date else None,
		"order_status": doc.order_status,
		"docstatus": cint(doc.docstatus),
		"gross_total": flt(doc.gross_total),
		"discount_total": flt(doc.discount_total),
		"net_total": flt(doc.net_total),
		# The tax and the total it makes. Both were stored and neither was sent, so every screen
		# downstream could only quote the net and none could show what the party is billed.
		"tax_total": flt(doc.tax_total),
		"grand_total": flt(doc.grand_total),
		"incentive_amount": flt(doc.incentive_amount),
		"totals_match": cint(doc.totals_match),
		"proposed_net_total": flt(doc.proposed_net_total),
		"credit_status": doc.credit_status,
		"approval_required": cint(doc.approval_required),
		"approval_status": doc.approval_status,
		"distributor": doc.distributor,
		"sent_to_distributor_on": str(doc.sent_to_distributor_on) if doc.sent_to_distributor_on else None,
		# Empty on an ordinary retailer order, and that is the point. Only a directly-billed
		# outlet ever puts a name here.
		"sales_order": doc.sales_order,
		"lines": len(doc.items or []),
		"free_goods": [{"item": r.item_code, "qty": flt(r.qty)} for r in (doc.free_goods or [])],
		"schemes": [
			{"scheme": r.scheme, "name": r.scheme_name, "benefit": flt(r.benefit_amount),
			 "description": r.benefit_description}
			for r in (doc.schemes_applied or [])
		],
	}


def assert_owner(doc) -> None:
	if doc.field_user == field_user_service.for_user():
		return
	frappe.throw("That order belongs to another rep.", frappe.PermissionError)


def _distributor_for(outlet) -> str | None:
	"""Who bills this shop. One read now that a distributor is a Customer (Phase 1, step 2d).

	This used to read the outlet's Customer and then look up the FieldMate Distributor Profile
	behind it, twice, because the two documents could in principle be named differently. They
	never were - the profile was named after its Customer - so the second read was the identity
	function wearing a lookup, and the fallback beside it was the same lookup spelled the other
	way round.
	"""
	return frappe.db.get_value("FieldMate Outlet", outlet, "distributor")
