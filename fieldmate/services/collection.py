"""Collections: what is owed, what was taken, and the one place it reaches the ledger.

The rule that shapes this module, asked once and branched on once (ADR-025):

    collected from a shop        -> the distributor's money  -> posts nothing, ever
    collected from a distributor -> our money                -> posts on deposit confirmation

`ours()` is that question. There is no `if party_type == "Outlet":` anywhere else, for the same
reason `credit.we_are_the_seller()` exists: the alternative is one app quietly becoming two.

A shop's outstanding is ours to hold because nobody else does. It is a **soft** ledger — it
accrues from submitted orders and is reduced by collections, and it posts nothing. A distributor's
outstanding is real and comes from ERPNext through `compat`.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

from fieldmate import compat
from fieldmate.services import field_user as field_user_service
from fieldmate.services import settings as settings_service

# Ageing buckets, in days. The last one is separate rather than folded into a total because it is
# the one that decides whether a rep pushes or walks away, and a total hides it.
BUCKETS = ((0, 7), (8, 14), (15, 30), (31, None))


def ours(collection) -> bool:
	"""Is this money ours to post? The single branch in the whole phase (ADR-025)."""
	party_type = (
		collection if isinstance(collection, str)
		else collection.get("party_type") if isinstance(collection, dict)
		else collection.party_type
	)
	return party_type == "Distributor"


# --------------------------------------------------------------------------------------
# what is owed
# --------------------------------------------------------------------------------------


def outstanding_for(outlet, field_user: str | None = None) -> dict:
	"""What a shop owes its distributor, with the bills behind it and their ageing.

	Nobody else holds this figure. We are not a party to the sale — the distributor billed the
	shop — so there is no ERPNext receivable to read. It accrues from the orders we booked and
	falls as collections come in, and it is honest about being an estimate: a distributor who
	invoiced the shop something we never saw is a gap this cannot close.
	"""
	field_user = field_user or field_user_service.for_user()
	doc = frappe.db.get_value(
		"FieldMate Outlet", outlet, ["name", "outlet_name", "distributor", "credit_limit"],
		as_dict=True,
	)
	if not doc:
		frappe.throw(frappe._("That shop no longer exists."))

	bills = open_bills_for(doc.name)
	today = getdate(nowdate())

	total = overdue = 0.0
	buckets = {f"bucket_{a}_{b or 'plus'}": 0.0 for a, b in BUCKETS}
	oldest = None

	for bill in bills:
		total += bill["pending"]
		age = frappe.utils.date_diff(today, getdate(bill["due_date"])) if bill["due_date"] else 0
		bill["days_overdue"] = max(0, age)
		if age > 0:
			overdue += bill["pending"]
			if oldest is None or getdate(bill["due_date"]) < oldest:
				oldest = getdate(bill["due_date"])
		for start, end in BUCKETS:
			if age >= start and (end is None or age <= end):
				buckets[f"bucket_{start}_{end or 'plus'}"] += bill["pending"]
				break

	limit = flt(doc.credit_limit)
	return {
		"outlet": doc.name,
		"outlet_name": doc.outlet_name,
		"distributor": doc.distributor,
		"outstanding": round(total, 2),
		"overdue": round(overdue, 2),
		"credit_limit": limit,
		# None rather than zero where no limit is set. A shop nobody has given a limit is not a
		# shop with no room, and the two read identically as 0.
		"headroom": round(limit - total, 2) if limit else None,
		"oldest_due_date": str(oldest) if oldest else None,
		"days_overdue": frappe.utils.date_diff(today, oldest) if oldest else 0,
		"bills": bills,
		"ageing": {k: round(v, 2) for k, v in buckets.items()},
		"source": "Soft Ledger",
		"last_payment": last_payment_for(doc.name),
	}


def open_bills_for(outlet) -> list[dict]:
	"""Orders this shop has not finished paying for, oldest first.

	FIFO, because that is how a shopkeeper and a rep both think about it: the oldest bill is the
	one being argued about. Allocations are read per order rather than netted against a running
	balance, so a payment made against one bill cannot silently settle another.
	"""
	orders = frappe.get_all(
		"FieldMate Order",
		filters={"outlet": outlet, "docstatus": 1,
		         "order_status": ["not in", ["Cancelled", "Rejected"]]},
		fields=["name", "order_date", "net_total", "credit_days", "payment_term"],
		order_by="order_date asc, creation asc",
	)
	if not orders:
		return []

	paid = paid_by_order([o.name for o in orders])
	bills = []
	for order in orders:
		# Settled at the door, so it was never outstanding in the first place.
		if order.payment_term in ("Cash on Delivery", "UPI on Delivery"):
			continue
		pending = flt(order.net_total) - flt(paid.get(order.name))
		if pending <= 0.005:
			continue
		bills.append({
			"reference_type": "FieldMate Order",
			"reference_name": order.name,
			"bill_no": order.name,
			"bill_date": str(order.order_date),
			"due_date": str(add_days(order.order_date, cint(order.credit_days) or 0)),
			"amount": flt(order.net_total),
			"paid": flt(paid.get(order.name)),
			"pending": round(pending, 2),
		})
	return bills


def paid_by_order(orders: list[str]) -> dict:
	"""What has been collected against each order.

	Bounced and cancelled collections are excluded: a cheque that came back never paid anything,
	and leaving it in is how a shop's outstanding quietly understates itself.
	"""
	if not orders:
		return {}
	rows = frappe.get_all(
		"FieldMate Collection Allocation",
		filters={"reference_type": "FieldMate Order", "reference_name": ["in", orders],
		         "parenttype": "FieldMate Collection"},
		fields=["reference_name", "allocated_amount", "parent"],
	)
	if not rows:
		return {}

	live = set(frappe.get_all(
		"FieldMate Collection",
		filters={"name": ["in", list({r.parent for r in rows})], "docstatus": 1,
		         "status": ["not in", ["Bounced", "Cancelled"]]},
		pluck="name",
	))

	paid = {}
	for row in rows:
		if row.parent in live:
			paid[row.reference_name] = paid.get(row.reference_name, 0) + flt(row.allocated_amount)
	return paid


def last_payment_for(outlet) -> dict | None:
	row = frappe.db.get_value(
		"FieldMate Collection",
		{"outlet": outlet, "docstatus": 1, "status": ["not in", ["Cancelled"]]},
		["name", "collection_date", "amount", "mode", "receipt_no", "status"],
		order_by="collection_date desc, creation desc",
		as_dict=True,
	)
	return dict(row) if row else None


def distributor_outstanding(distributor: str) -> dict:
	"""What a distributor owes us. Real, and read from ERPNext rather than held here."""
	customer = frappe.db.get_value("FieldMate Distributor Profile", distributor, "customer")
	company = settings_service.value("default_company")
	if not customer:
		return {"distributor": distributor, "outstanding": 0.0, "source": "ERPNext"}

	return {
		"distributor": distributor,
		"customer": customer,
		"outstanding": flt(compat.get_outstanding(customer, company)),
		"credit_limit": flt(compat.get_credit_limit(customer, company)),
		"source": "ERPNext",
	}


# --------------------------------------------------------------------------------------
# taking the money
# --------------------------------------------------------------------------------------


def create(payload: dict, field_user: str | None = None) -> dict:
	"""Record a collection. Posts nothing, whoever it came from."""
	field_user = field_user or field_user_service.for_user()
	if not field_user:
		frappe.throw(frappe._("You are not set up as a field user yet. Ask your manager."))

	data = dict(payload or {})
	doc = frappe.new_doc("FieldMate Collection")
	doc.collection_date = data.get("collection_date") or nowdate()
	doc.party_type = data.get("party_type") or "Outlet"
	doc.outlet = data.get("outlet")
	doc.distributor = data.get("distributor")
	doc.field_user = field_user
	doc.visit = data.get("visit")
	doc.mode = data.get("mode") or "Cash"
	doc.amount = flt(data.get("amount"))
	doc.instrument_no = data.get("instrument_no")
	doc.instrument_date = data.get("instrument_date")
	doc.instrument_bank = data.get("instrument_bank")
	doc.collected_from_name = data.get("collected_from_name")
	doc.denominations = data.get("denominations")
	doc.latitude = data.get("latitude")
	doc.longitude = data.get("longitude")
	doc.remarks = data.get("remarks")
	doc.client_uuid = data.get("client_uuid")
	doc.created_offline = cint(data.get("created_offline"))
	doc.device_id = data.get("device_id")

	for line in data.get("allocations") or []:
		row = doc.append("allocations", {})
		row.reference_type = line.get("reference_type") or "FieldMate Order"
		row.reference_name = line.get("reference_name")
		row.bill_no = line.get("bill_no")
		row.bill_date = line.get("bill_date")
		row.due_date = line.get("due_date")
		row.outstanding_amount = flt(line.get("outstanding_amount"))
		row.allocated_amount = flt(line.get("allocated_amount"))

	doc.insert()
	# A rep holds create and submit-if-owner and never write (ADR-004). The server submits on
	# their behalf once it has confirmed the record names them.
	doc.flags.ignore_permissions = True
	doc.submit()
	mark_visit_task(doc)
	return summarise(doc)


def mark_visit_task(doc) -> None:
	"""Tick the visit's collection task, so the hub shows the work as done.

	Written straight to the row: the visit is submitted by now and a rep holds no write on it.
	Silent where the visit has no such task - money taken outside a visit is ordinary.
	"""
	if not doc.visit:
		return
	task = frappe.db.get_value(
		"FieldMate Visit Task",
		{"parent": doc.visit, "parenttype": "FieldMate Visit", "task_type": "Collection"},
		"name",
	)
	if not task:
		return
	frappe.db.set_value("FieldMate Visit Task", task, {
		"status": "Done",
		"completed_on": now_datetime(),
		"reference_doctype": "FieldMate Collection",
		"reference_name": doc.name,
	}, update_modified=False)

	# What the visit produced. `collection_amount` was built in Phase 3 and left at zero waiting
	# for this, exactly as order_value was - and every productivity figure a manager reads is
	# computed off the visit, not off the collection.
	total = sum(flt(row.amount) for row in frappe.get_all(
		"FieldMate Collection",
		filters={"visit": doc.visit, "docstatus": 1, "status": ["not in", ["Bounced", "Cancelled"]]},
		fields=["amount"],
	))
	frappe.db.set_value("FieldMate Visit", doc.visit, "collection_amount", total,
	                    update_modified=False)


def summarise(doc) -> dict:
	return {
		"name": doc.name,
		"receipt_no": doc.receipt_no,
		"collection_date": str(doc.collection_date),
		"party_type": doc.party_type,
		"party": doc.party,
		"outlet": doc.outlet,
		"distributor": doc.distributor,
		"mode": doc.mode,
		"amount": flt(doc.amount),
		"allocated_amount": flt(doc.allocated_amount),
		"unallocated_amount": flt(doc.unallocated_amount),
		"status": doc.status,
		"deposit": doc.deposit,
		# Empty in both cases until a deposit is confirmed, and empty forever for a shop.
		"payment_entry": doc.payment_entry,
		"posts_to_ledger": cint(doc.posts_to_ledger),
		"instrument_no": doc.instrument_no,
	}


def mine(field_user: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
	field_user = field_user or field_user_service.for_user()
	filters = {"field_user": field_user, "docstatus": 1}
	if status:
		filters["status"] = status
	return frappe.get_list(
		"FieldMate Collection",
		filters=filters,
		fields=["name", "receipt_no", "collection_date", "party", "party_type", "mode",
		        "amount", "status", "deposit"],
		order_by="collection_date desc, creation desc",
		limit_page_length=limit,
		user=frappe.session.user,
		ignore_permissions=False,
	)


# --------------------------------------------------------------------------------------
# handing it over
# --------------------------------------------------------------------------------------


def undeposited(field_user: str | None = None) -> dict:
	"""What the rep is still carrying, and how long they have had it.

	Cash in a satchel is the risk, not cash in a ledger, so this counts a shop's money and a
	distributor's alike — the rep is equally liable for both and equally likely to be robbed.
	"""
	field_user = field_user or field_user_service.for_user()
	rows = frappe.get_all(
		"FieldMate Collection",
		filters={"field_user": field_user, "docstatus": 1, "status": "Collected"},
		fields=["name", "receipt_no", "collection_date", "party", "party_type", "mode",
		        "amount", "instrument_no", "posts_to_ledger"],
		order_by="collection_date asc",
	)

	today = getdate(nowdate())
	cash = cheque = ours_total = 0.0
	oldest_age = 0
	for row in rows:
		if row.mode in ("Cheque", "DD"):
			cheque += flt(row.amount)
		else:
			cash += flt(row.amount)
		if cint(row.posts_to_ledger):
			ours_total += flt(row.amount)
		oldest_age = max(oldest_age, frappe.utils.date_diff(today, getdate(row.collection_date)))

	threshold = cint(settings_service.value("cash_in_hand_alert_days") or 2)
	return {
		"collections": rows,
		"count": len(rows),
		"cash_amount": round(cash, 2),
		"cheque_amount": round(cheque, 2),
		"total_amount": round(cash + cheque, 2),
		"ours_amount": round(ours_total, 2),
		"oldest_days": oldest_age,
		# Named rather than merely flagged: "you are carrying money from Tuesday" is actionable,
		# "overdue" is not.
		"is_overdue": oldest_age > threshold and bool(rows),
		"threshold_days": threshold,
	}


def declare_deposit(payload: dict, field_user: str | None = None) -> dict:
	"""The rep says where the money went. Still posts nothing."""
	field_user = field_user or field_user_service.for_user()
	data = dict(payload or {})

	collections = data.get("collections") or []
	if not collections:
		frappe.throw(frappe._("Tick which collections are in this deposit."))

	doc = frappe.new_doc("FieldMate Collection Deposit")
	doc.deposit_date = data.get("deposit_date") or nowdate()
	doc.field_user = field_user
	doc.channel = data.get("channel") or "Bank Branch"
	doc.bank_account = data.get("bank_account")
	doc.distributor = data.get("distributor")
	doc.reference_no = data.get("reference_no")
	doc.deposited_at = data.get("deposited_at")
	doc.remarks = data.get("remarks")
	doc.company = frappe.db.get_value("FieldMate Field User", field_user, "company")
	doc.client_uuid = data.get("client_uuid")
	doc.created_offline = cint(data.get("created_offline"))
	doc.device_id = data.get("device_id")

	for name in collections:
		doc.append("lines", {"collection": name})

	doc.insert()
	doc.flags.ignore_permissions = True
	doc.submit()
	return summarise_deposit(frappe.get_doc("FieldMate Collection Deposit", doc.name))


def confirm_deposit(name: str, confirmed_by: str | None = None) -> dict:
	"""Somebody at our end confirms the money arrived. **This is where a Payment Entry appears.**

	Not before, and not for everything. Only the part collected from distributors was ever ours
	(ADR-025); a shop's cash was the distributor's from the moment it left the till and passes
	through without touching our books.

	The confirmer cannot be the rep who declared it. A declaration somebody can confirm themselves
	is a declaration, not a control.
	"""
	doc = frappe.get_doc("FieldMate Collection Deposit", name)
	confirmed_by = confirmed_by or frappe.session.user

	if doc.status == "Confirmed":
		return summarise_deposit(doc)
	if doc.docstatus != 1:
		frappe.throw(frappe._("That deposit has not been declared yet."))
	if field_user_service.for_user(confirmed_by) == doc.field_user:
		frappe.throw(frappe._("A deposit cannot be confirmed by the person who declared it."))

	for row in doc.lines or []:
		if not cint(row.posts_to_ledger):
			# The distributor's own money. Marked cleared and left alone - there is no receivable
			# of ours for it to clear.
			frappe.db.set_value("FieldMate Collection", row.collection, "status", "Cleared",
			                    update_modified=False)
			continue
		post_payment(row.collection, doc)

	doc.db_set("status", "Confirmed", update_modified=False)
	doc.db_set("confirmed_by", confirmed_by, update_modified=False)
	doc.db_set("confirmed_on", now_datetime(), update_modified=False)
	return summarise_deposit(frappe.get_doc("FieldMate Collection Deposit", name))


def post_payment(collection: str, deposit) -> str | None:
	"""One Payment Entry for one distributor collection, with its references.

	Idempotent on the collection: a confirmation retried after a dropped connection must not pay
	the same money twice.
	"""
	doc = frappe.get_doc("FieldMate Collection", collection)
	if doc.payment_entry:
		return doc.payment_entry

	customer = frappe.db.get_value("FieldMate Distributor Profile", doc.distributor, "customer")
	if not customer:
		frappe.throw(
			frappe._("{0} has no billing account, so there is nothing to credit the payment to.")
			.format(doc.distributor)
		)

	name = compat.make_payment_entry({
		"party_type": "Customer",
		"party": customer,
		"company": doc.company or deposit.company,
		"posting_date": deposit.deposit_date,
		"paid_amount": flt(doc.amount),
		"mode_of_payment": doc.mode,
		"reference_no": doc.instrument_no or deposit.reference_no,
		"reference_date": doc.instrument_date or deposit.deposit_date,
		"bank_account": deposit.bank_account,
		"fm_source_key": doc.name,
		"references": [
			{"reference_doctype": row.reference_type, "reference_name": row.reference_name,
			 "allocated_amount": flt(row.allocated_amount)}
			for row in (doc.allocations or [])
			if row.reference_type == "Sales Invoice" and row.reference_name
		],
	})

	frappe.db.set_value("FieldMate Collection", doc.name,
	                    {"payment_entry": name, "status": "Cleared"}, update_modified=False)
	return name


def summarise_deposit(doc) -> dict:
	return {
		"name": doc.name,
		"deposit_date": str(doc.deposit_date),
		"channel": doc.channel,
		"reference_no": doc.reference_no,
		"cash_amount": flt(doc.cash_amount),
		"cheque_amount": flt(doc.cheque_amount),
		"cheque_count": cint(doc.cheque_count),
		"total_amount": flt(doc.total_amount),
		"ours_amount": flt(doc.ours_amount),
		"status": doc.status,
		"confirmed_by": doc.confirmed_by,
		"confirmed_on": str(doc.confirmed_on) if doc.confirmed_on else None,
		"lines": [
			{"collection": r.collection, "party": r.party, "mode": r.mode,
			 "amount": flt(r.amount), "posts_to_ledger": cint(r.posts_to_ledger)}
			for r in (doc.lines or [])
		],
	}


# --------------------------------------------------------------------------------------
# when it comes back
# --------------------------------------------------------------------------------------


def bounce(collection: str, reason: str | None = None) -> dict:
	"""A cheque came back. Restore the outstanding it appeared to settle.

	Whichever side it was on: a shop's bill goes back to unpaid because `paid_by_order` stops
	counting a bounced collection, and a distributor's Payment Entry is cancelled so ERPNext's
	receivable comes back too. Leaving either in place is how a month's collections look better
	than they were.
	"""
	doc = frappe.get_doc("FieldMate Collection", collection)
	if doc.status == "Bounced":
		return summarise(doc)
	if doc.docstatus != 1:
		frappe.throw(frappe._("That collection was never recorded."))

	note = f"Bounced: {reason}" if reason else "Bounced"
	entry = doc.payment_entry

	if entry:
		# The link is released before the entry is cancelled, not after. Frappe checks for
		# back-links first, so a collection still pointing at the payment refuses to let it go -
		# the same lock that stopped a cancelled order releasing its scheme ledger in Phase 4.
		# The reference survives in the remark, where it is still findable.
		frappe.db.set_value("FieldMate Collection", doc.name, "payment_entry", None,
		                    update_modified=False)
		compat.cancel_payment_entry(entry)
		note = f"{note}. Payment Entry {entry} cancelled."

	frappe.db.set_value("FieldMate Collection", doc.name, {
		"status": "Bounced",
		"remarks": (doc.remarks + chr(10) + note).strip() if doc.remarks else note,
	}, update_modified=False)

	return summarise(frappe.get_doc("FieldMate Collection", doc.name))


# --------------------------------------------------------------------------------------
# the nightly snapshot
# --------------------------------------------------------------------------------------


def snapshot_outstanding(on=None) -> dict:
	"""Freeze what every shop owes, so a trend can be read tomorrow.

	Computed rather than accumulated: a snapshot that drifts from the bills behind it is worse
	than no snapshot, because somebody will act on it.
	"""
	on = getdate(on or nowdate())
	written = 0

	for outlet in frappe.get_all("FieldMate Outlet",
	                             filters={"outlet_status": "Active"},
	                             pluck="name"):
		position = outstanding_for(outlet)
		if not position["outstanding"]:
			continue

		existing = frappe.db.get_value(
			"FieldMate Outstanding Snapshot",
			{"party_type": "Outlet", "party": outlet, "as_of": on}, "name",
		)
		values = {
			"outstanding_amount": position["outstanding"],
			"overdue_amount": position["overdue"],
			"credit_limit": position["credit_limit"],
			"oldest_due_date": position["oldest_due_date"],
			"days_overdue": position["days_overdue"],
			"bill_count": len(position["bills"]),
			"bucket_0_7": position["ageing"]["bucket_0_7"],
			"bucket_8_14": position["ageing"]["bucket_8_14"],
			"bucket_15_30": position["ageing"]["bucket_15_30"],
			"bucket_30_plus": position["ageing"]["bucket_31_plus"],
			"source": "Soft Ledger",
		}

		if existing:
			frappe.db.set_value("FieldMate Outstanding Snapshot", existing, values,
			                    update_modified=False)
		else:
			doc = frappe.get_doc({
				"doctype": "FieldMate Outstanding Snapshot",
				"as_of": on, "party_type": "Outlet", "party": outlet,
				"outlet": outlet, "distributor": position["distributor"],
				**values,
			})
			doc.flags.ignore_permissions = True
			doc.insert()
		written += 1

	frappe.db.commit()
	return {"as_of": str(on), "written": written}


def alert_cash_in_hand() -> dict:
	"""Tell a manager which reps are still carrying money, and since when.

	The satchel is the exposure. A rep holding four days of cash is a risk whoever the money
	legally belongs to, so this counts both kinds.
	"""
	threshold = cint(settings_service.value("cash_in_hand_alert_days") or 2)
	flagged = []

	for rep in frappe.get_all("FieldMate Field User",
	                          filters={"status": "Active"},
	                          fields=["name", "full_name", "reports_to"]):
		position = undeposited(rep.name)
		if position["is_overdue"]:
			flagged.append({
				"field_user": rep.name,
				"full_name": rep.full_name,
				"manager": rep.reports_to,
				"amount": position["total_amount"],
				"days": position["oldest_days"],
				"count": position["count"],
			})

	return {"threshold_days": threshold, "flagged": flagged}
