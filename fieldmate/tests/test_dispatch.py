"""Phase 2, step 6 — getting a season's allocation out of the warehouse.

Real documents throughout: real stock, real reservations, real Delivery Notes and Sales Invoices.
There is nothing here worth testing against a mock, because every question this module answers is
a question about what ERPNext did.

The one thing worth stating up front, because the plan says otherwise: **no Pick List**. ERPNext
refuses one for a Sales Order carrying reserved stock, so the reserved path goes straight to a
Delivery Note built from the reservations. `test_a_pick_list_is_not_the_path_here` pins that, so
nobody re-reads the plan in six months and 'fixes' it.
"""

import frappe
from frappe.utils import flt, now_datetime, today

from fieldmate import compat
from fieldmate.services import allocation as allocation_service
from fieldmate.services import collection as collection_service
from fieldmate.services import dispatch as dispatch_service
from fieldmate.services import order as order_service
from fieldmate.tests.test_season import SeasonFixture


class DispatchFixture(SeasonFixture):
	"""A season with one booking, allocated, with stock behind it."""

	def setUp(self):
		super().setUp()
		if not compat.stock_reservation_enabled():
			self.skipTest("stock reservation is switched off on this site")

		# Close anything still booking for this company before opening ours.
		#
		# Submitting a Sales Invoice commits, so a season from an earlier test in this class
		# outlives FrappeTestCase's rollback - and it cannot be deleted either, because the
		# orders against it are still there. The next `make_season` then hits the overlap guard
		# from step 1 and every remaining test in the file fails on a message about two seasons.
		#
		# So the fixture does what the master's own message tells a person to do: close the
		# other one. Deactivating rather than deleting, for the same reason a real site would.
		self.close_other_seasons()

		self.price_item(self.item, 100)
		self.season = self.make_season(price_list=self.season_price_list(100), advance_pct=0)
		self.warehouse = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not self.warehouse:
			self.skipTest("this company has no leaf warehouse")
		frappe.db.set_value("Customer", self.party, "fm_warehouse", self.warehouse,
		                    update_modified=False)
		frappe.clear_document_cache("Customer", self.party)
		self.give_the_party_an_address()

	def give_the_party_an_address(self):
		"""A Delivery Trip is a route, and a route needs somewhere to go.

		ERPNext reads the customer's address for each stop and fails with `Address None not
		found` without one. That is not a FieldMate rule to work around - a van cannot be sent
		to a party whose address nobody has recorded - so the fixture records one.
		"""
		if frappe.db.exists("Dynamic Link", {"link_doctype": "Customer",
		                                     "link_name": self.party,
		                                     "parenttype": "Address"}):
			return
		address = frappe.get_doc({
			"doctype": "Address",
			"address_title": self.party,
			"address_type": "Shipping",
			"address_line1": "1 Test Road",
			"city": "Delhi",
			# An Indian address has to name its state, and india_compliance says so - the state
			# is what decides CGST/SGST against IGST, so an address without one cannot be
			# taxed. Pincode for the same reason: the e-way bill and the GSTR both want it.
			"state": "Delhi",
			"pincode": "110001",
			# India, named. `get_value("Country", {}, "name")` answers with whichever row
			# MariaDB hands back first, which is **Afghanistan** - so this was giving the party
			# an Afghan address, india_compliance read it as an overseas party, and every
			# invoice and delivery note was refused with "GST Category cannot be set to
			# Overseas since it is disabled in GST Settings". The `or "India"` never fired,
			# because the query always answered something.
			#
			# The same lesson `TestAnOrderOnAPartyWeBill` records about price lists: "whichever
			# row MariaDB returns first" is not a rule, and the moment it matters it is wrong.
			"country": "India" if frappe.db.exists("Country", "India")
			           else frappe.db.get_value("Country", {}, "name"),
			"links": [{"link_doctype": "Customer", "link_name": self.party}],
		}).insert(ignore_permissions=True)
		self.track("Address", address.name)

	def tearDown(self):
		try:
			allocation_service.revert(self.season)
		except Exception:
			pass
		# Closed as well as tracked. Where a commit has outlived the rollback the delete will
		# fail - a season with orders against it cannot go - and a closed season clashes with
		# nothing, so the next test can still open its own.
		try:
			frappe.db.set_value("FieldMate Season", self.season, "is_active", 0,
			                    update_modified=False)
			frappe.db.commit()
		except Exception:
			pass
		super().tearDown()

	def close_other_seasons(self):
		for name in frappe.get_all("FieldMate Season",
		                           filters={"company": self.company, "is_active": 1},
		                           pluck="name"):
			frappe.db.set_value("FieldMate Season", name, "is_active", 0, update_modified=False)
		frappe.db.commit()

	def booking(self, qty=10):
		created = self.as_rep(order_service.create, {
			"party_type": "Customer", "customer": self.party,
			"lines": [{"item": self.item, "qty": qty}],
			"client_uuid": self.uid("BOOK"),
		}, self.rep.name)
		name = self.track("FieldMate Order", created["name"])
		self.as_rep(order_service.submit_order, name)
		so = frappe.db.get_value("FieldMate Order", name, "sales_order")
		self.track("Sales Order", so)
		return name, so

	def stock(self, qty):
		entry = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
			"company": self.company,
			"items": [{"item_code": self.item, "qty": qty, "t_warehouse": self.warehouse,
			           "basic_rate": 50}],
		})
		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()
		self.track("Stock Entry", entry.name)

	def allocated(self, qty=10, stock=100):
		name, so = self.booking(qty)
		self.stock(stock)
		allocation_service.apply(self.season, allocation_service.PRO_RATA)
		return name, so


class TestWhatIsReadyToGo(DispatchFixture):
	def test_a_booking_with_stock_held_against_it_is_ready(self):
		name, _ = self.allocated()
		rows = dispatch_service.ready(self.season)
		self.assertEqual([row["order"] for row in rows], [name])
		self.assertEqual(rows[0]["qty"], 10)

	def test_a_booking_nobody_allocated_is_not(self):
		self.booking()
		self.stock(100)
		self.assertEqual(dispatch_service.ready(self.season), [])

	def test_an_allocation_reverted_overnight_takes_it_off_the_list(self):
		"""What is dispatchable is what the warehouse is holding now, not what it held when
		somebody opened the page."""
		self.allocated()
		allocation_service.revert(self.season)
		self.assertEqual(dispatch_service.ready(self.season), [])


class TestShippingIt(DispatchFixture):
	def test_a_delivery_note_is_posted_and_submitted(self):
		name, _ = self.allocated()
		answer = dispatch_service.deliver(self.season)

		self.assertEqual(len(answer["delivered"]), 1)
		note = answer["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)
		self.assertEqual(frappe.db.get_value("Delivery Note", note, "docstatus"), 1)
		self.assertEqual(answer["delivered"][0]["order"], name)

	def test_it_ships_what_was_allocated_not_what_was_asked_for(self):
		"""A booking served short gets a Delivery Note for what it was given, which is the whole
		point of having allocated."""
		self.booking(60)
		self.stock(25)
		allocation_service.apply(self.season, allocation_service.PRO_RATA)

		answer = dispatch_service.deliver(self.season)
		note = answer["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)
		doc = frappe.get_doc("Delivery Note", note)
		self.assertEqual(sum(row.qty for row in doc.items), 25)

	def test_dispatching_twice_ships_once(self):
		"""A button somebody presses twice while a long run is still going. A second note would
		take the same stock out of the warehouse again."""
		order, _ = self.allocated()
		first = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", first)

		dispatch_service.deliver(self.season)
		# Counted on **this booking's** key, not on a pattern across the site - the first
		# version of this counted every note any test in the file had made and read six.
		self.assertEqual(
			frappe.db.count("Delivery Note",
			                {"fm_source_key": f"{order}:DN", "docstatus": 1}),
			1, "exactly one note for the booking")

	def test_a_booking_with_nothing_held_is_reported_rather_than_thrown_at(self):
		"""A run over forty bookings that stops on the ninth leaves thirty-one undispatched and
		nobody told which."""
		self.booking()
		answer = dispatch_service.deliver(self.season)
		self.assertEqual(answer["delivered"], [])

	def test_a_pick_list_is_not_the_path_here(self):
		"""The plan says Pick List; ERPNext refuses one for a Sales Order carrying reserved
		stock. Reserving and picking are alternatives, not steps. Pinned so nobody re-reads the
		plan in six months and 'fixes' this."""
		from erpnext.selling.doctype.sales_order.sales_order import create_pick_list

		_, so = self.allocated()
		with self.assertRaises(frappe.ValidationError) as caught:
			create_pick_list(so)
		self.assertIn("reserved stock", str(caught.exception))


class TestBillingIt(DispatchFixture):
	def shipped(self):
		self.allocated()
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)
		return note

	def test_what_has_shipped_is_found_after_the_reservation_is_consumed(self):
		"""ERPNext stops reporting a reservation once the goods go out, so `ready` empties.
		`notes_for` is how what has already gone is found - the first version of `invoice` read
		`ready` and would have had nothing to bill the moment the delivery succeeded."""
		note = self.shipped()
		self.assertEqual(dispatch_service.ready(self.season), [])
		self.assertEqual(dispatch_service.notes_for(self.season), [note])

	def test_a_sales_invoice_is_posted_and_submitted(self):
		self.shipped()
		answer = dispatch_service.invoice(self.season)

		self.assertEqual(len(answer["invoiced"]), 1)
		invoice = answer["invoiced"][0]["sales_invoice"]
		self.track("Sales Invoice", invoice)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 1)

	def test_invoicing_twice_bills_once(self):
		note = self.shipped()
		self.assertTrue(note)
		first = dispatch_service.invoice(self.season)["invoiced"][0]["sales_invoice"]
		self.track("Sales Invoice", first)

		again = dispatch_service.invoice(self.season)
		self.assertEqual(again["invoiced"][0]["sales_invoice"], first)
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"fm_source_key": f"{note}:SI", "docstatus": 1}), 1)

	def test_the_invoice_reaches_the_ledger(self):
		"""The whole reason a primary sale is ours is that it ends up in our books."""
		self.shipped()
		invoice = dispatch_service.invoice(self.season)["invoiced"][0]["sales_invoice"]
		self.track("Sales Invoice", invoice)
		self.assertTrue(frappe.db.count("GL Entry", {"voucher_no": invoice}))


class TestTheTrip(DispatchFixture):

	def van(self):
		"""A vehicle to send. ERPNext will not save a Delivery Trip without one."""
		existing = frappe.db.get_value("Vehicle", {}, "name")
		if existing:
			return existing
		doc = frappe.get_doc({
			"doctype": "Vehicle", "license_plate": self.uid("VAN"), "make": "Tata",
			"model": "Ace", "last_odometer": 0, "acquisition_date": today(),
			"location": "Depot", "chassis_no": self.uid("CH"), "vehicle_value": 100000,
			"uom": frappe.db.get_value("UOM", {}, "name") or "Litre",
			"fuel_type": "Diesel", "fuel_uom": frappe.db.get_value("UOM", {}, "name") or "Litre",
		}).insert(ignore_permissions=True)
		return self.track("Vehicle", doc.name)

	def test_it_groups_the_notes_and_stays_a_draft(self):
		"""A trip is a plan for a van that has not left. The driver, the vehicle and the
		departure time are filled in by whoever is standing in the yard."""
		self.allocated()
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)

		answer = dispatch_service.trip(self.season, today(), self.van(), now_datetime())
		self.assertTrue(answer["trip"])
		self.track("Delivery Trip", answer["trip"])
		self.assertEqual(answer["stops"], 1)
		self.assertEqual(frappe.db.get_value("Delivery Trip", answer["trip"], "docstatus"), 0)

	def test_a_second_run_on_the_same_day_joins_the_same_trip(self):
		self.allocated()
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)

		first = dispatch_service.trip(self.season, today(), self.van(), now_datetime())["trip"]
		self.track("Delivery Trip", first)
		self.assertEqual(dispatch_service.trip(self.season, today(), self.van(),
		                                       now_datetime())["trip"], first)

	def test_a_season_that_has_shipped_nothing_gets_no_trip(self):
		self.allocated()
		answer = dispatch_service.trip(self.season, today(), self.van(), now_datetime())
		self.assertIsNone(answer["trip"])
		self.assertIn("Nothing has been delivered", answer["reason"])


class TestWhereTheSeasonHasGotTo(DispatchFixture):
	def test_the_four_numbers_a_planner_asks_for(self):
		self.allocated()
		at_start = dispatch_service.position(self.season)
		self.assertEqual((at_start["booked"], at_start["held"], at_start["shipped"],
		                  at_start["billed"]), (1, 1, 0, 0))

		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)
		after_shipping = dispatch_service.position(self.season)
		self.assertEqual(after_shipping["shipped"], 1)
		self.assertEqual(after_shipping["billed"], 0)

		invoice = dispatch_service.invoice(self.season)["invoiced"][0]["sales_invoice"]
		self.track("Sales Invoice", invoice)
		self.assertEqual(dispatch_service.position(self.season)["billed"], 1)


class TestTheAdvanceOnTheBill(DispatchFixture):
	"""A season is bought months before it is delivered, so by the time the invoice goes out the
	party has already paid part of it.

	**The invoice has to carry that advance.** Without it the party is billed for money they
	handed over in November, their Payment Entry sits unallocated on their account, and the
	receivable is overstated until somebody finds it and journals it by hand in February. It is
	also the plan's own criterion for this phase - "a released dispatch plan produces Delivery
	Notes and invoices with advances allocated" - and the gate script found it missing.

	ERPNext allocates it itself once asked, through `allocate_advances_automatically`. That is
	deliberately its switch and not advance rows of ours: which advance covers which invoice, in
	which currency, to what exchange gain, is accounting ERPNext already does, and a second
	implementation here would be a second answer to reconcile.
	"""

	def manager(self):
		"""Somebody other than the rep: a deposit cannot be confirmed by whoever declared it."""
		user = frappe.get_doc({
			"doctype": "User", "email": f"{self.uid('mgr')}@fieldmate.test".lower(),
			"first_name": "Manager", "send_welcome_email": 0,
			"roles": [{"role": "FieldMate Area Manager"}],
		}).insert(ignore_permissions=True)
		self.track("User", user.name)
		return user.name

	def advance(self, order, amount):
		"""Money in, declared and confirmed, so there is a Payment Entry for ERPNext to find.

		All three steps, because the first two post nothing (ADR-004). An advance that has only
		been collected is money the rep says they took; it becomes something ERPNext can allocate
		when somebody at the office agrees it arrived.
		"""
		result = self.as_rep(collection_service.create, {
			"party_type": "Distributor", "distributor": self.party, "amount": amount,
			"mode": "Cash", "client_uuid": self.uid("COL"),
			"allocations": [{"reference_type": "FieldMate Order", "reference_name": order,
			                 "allocated_amount": amount}],
		}, self.rep.name)
		collection = self.track("FieldMate Collection", result["name"])

		deposit = self.as_rep(collection_service.declare_deposit, {
			"collections": [collection], "channel": "Bank Branch",
			"reference_no": self.uid("SLIP")[:20], "client_uuid": self.uid("DEP"),
		}, self.rep.name)
		self.track("FieldMate Collection Deposit", deposit["name"])
		collection_service.confirm_deposit(deposit["name"], confirmed_by=self.manager())

		entry = frappe.db.get_value("FieldMate Collection", collection, "payment_entry")
		self.assertTrue(entry, "confirming the deposit posted no Payment Entry")
		self.track("Payment Entry", entry)
		return entry

	def bill(self):
		invoice = dispatch_service.invoice(self.season)["invoiced"][0]["sales_invoice"]
		return self.track("Sales Invoice", invoice)

	def allocated_on(self, invoice, entry):
		return sum(flt(row.allocated_amount) for row in frappe.get_all(
			"Sales Invoice Advance",
			filters={"parent": invoice, "reference_name": entry},
			fields=["allocated_amount"]))

	def test_the_advance_is_put_against_the_invoice(self):
		order, _ = self.allocated()
		entry = self.advance(order, 300)
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)

		invoice = self.bill()
		self.assertEqual(self.allocated_on(invoice, entry), 300)

	def test_what_is_still_owed_is_what_is_left(self):
		"""The figure the party is chased for, and the one that was wrong: billed in full against
		an advance already paid."""
		order, _ = self.allocated()
		self.advance(order, 300)
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)

		invoice = self.bill()
		doc = frappe.get_doc("Sales Invoice", invoice)
		self.assertEqual(flt(doc.outstanding_amount, 2),
		                 flt(flt(doc.grand_total) - 300, 2))

	def test_an_invoice_with_no_advance_behind_it_carries_none(self):
		"""Asking ERPNext to allocate is not the same as it inventing something to allocate."""
		self.allocated()
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)

		invoice = self.bill()
		self.assertEqual(
			frappe.db.count("Sales Invoice Advance", {"parent": invoice}), 0)
		doc = frappe.get_doc("Sales Invoice", invoice)
		self.assertEqual(flt(doc.outstanding_amount, 2), flt(doc.grand_total, 2))

	def test_an_advance_bigger_than_the_bill_is_not_over_allocated(self):
		"""A party that paid for the whole season up front, delivered in two lorries. The first
		invoice may take what it is worth and no more - allocating the rest would credit them
		twice when the second one goes out."""
		order, _ = self.allocated()
		entry = self.advance(order, 100_000)
		note = dispatch_service.deliver(self.season)["delivered"][0]["delivery_note"]
		self.track("Delivery Note", note)

		invoice = self.bill()
		doc = frappe.get_doc("Sales Invoice", invoice)
		self.assertLessEqual(self.allocated_on(invoice, entry), flt(doc.grand_total))
		self.assertEqual(flt(doc.outstanding_amount, 2), 0.0)
