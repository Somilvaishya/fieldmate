import frappe

from fieldmate.services import importer as importer_service
from fieldmate.services import outlet as outlet_service
from fieldmate.tests.test_outlet import OutletFixture


class TestOutletService(OutletFixture):
	def setUp(self):
		super().setUp()
		self.north = self.make_territory()
		self.delhi = self.make_territory(parent=self.north)
		self.mumbai = self.make_territory(parent=self.north)
		self.rep = self.make_field_user(territory=self.delhi)
		self.manager = self.make_field_user(territory=self.north, designation="Area Manager")
		self.mine = self.make_outlet(territory=self.delhi, outlet_name="Sharma Kirana")
		self.theirs = self.make_outlet(territory=self.mumbai, outlet_name="Patel Stores")
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	# ---------------------------------------------------------------- search

	def test_search_is_territory_scoped(self):
		names = {o["name"] for o in self.as_user(self.rep.user, outlet_service.search)}
		self.assertIn(self.mine.name, names)
		self.assertNotIn(self.theirs.name, names)

	def test_manager_search_spans_the_subtree(self):
		names = {o["name"] for o in self.as_user(self.manager.user, outlet_service.search)}
		self.assertIn(self.mine.name, names)
		self.assertIn(self.theirs.name, names)

	def test_search_matches_on_name(self):
		found = self.as_user(self.rep.user, outlet_service.search, query="Sharma")
		self.assertEqual({o["name"] for o in found}, {self.mine.name})

	def test_search_cannot_reach_across_territory_even_by_name(self):
		"""The filter narrows what you may see; it never widens it."""
		found = self.as_user(self.rep.user, outlet_service.search, query="Patel")
		self.assertEqual(found, [])

	# ---------------------------------------------------------------- detail

	def test_detail_returns_the_360_payload(self):
		payload = self.as_user(self.rep.user, outlet_service.detail, self.mine.name)
		self.assertEqual(payload["outlet"]["name"], self.mine.name)
		self.assertIn("can_take_order", payload)
		self.assertIn("geo_fence_radius_m", payload)
		self.assertEqual(payload["billing_party"], self.mine.distributor)

	def test_rep_cannot_edit_another_territory(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rep.user, outlet_service.update,
			             self.theirs.name, {"mobile_no": "9800000000"})

	def test_rep_holds_no_write_permission_on_the_doctype(self):
		"""Editing goes through our service, which is why generic write endpoints stay shut."""
		self.assertFalse(
			frappe.has_permission("FieldMate Outlet", "write", user=self.rep.user)
		)

	def test_detail_refuses_another_territory(self):
		"""get_doc applies no user permission of its own, so this is gated explicitly."""
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rep.user, outlet_service.detail, self.theirs.name)

	def test_detail_says_why_an_order_is_blocked(self):
		payload = self.as_user(self.rep.user, outlet_service.detail, self.mine.name)
		self.assertFalse(payload["can_take_order"])
		self.assertIn("approval", payload["blocked_reason"])

	# ---------------------------------------------------------------- create

	def test_field_created_outlet_is_unapproved(self):
		result = self.as_user(self.rep.user, outlet_service.create, {
			"outlet_name": self.uid("NEW"),
			"mobile_no": "9800000123",
			"distributor": self.mine.distributor,
			"territory": self.delhi,
			"approval_status": "Approved",       # the device asking nicely
		})
		self.track("FieldMate Outlet", result["name"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Outlet", result["name"], "approval_status"),
			"Pending Approval",
		)

	def test_create_is_idempotent_on_client_uuid(self):
		payload = {
			"outlet_name": self.uid("NEW"),
			"mobile_no": "9800000124",
			"distributor": self.mine.distributor,
			"territory": self.delhi,
			"client_uuid": self.uid("U"),
		}
		first = self.as_user(self.rep.user, outlet_service.create, payload)
		second = self.as_user(self.rep.user, outlet_service.create, payload)
		self.track("FieldMate Outlet", first["name"])

		self.assertTrue(first["created"])
		self.assertFalse(second["created"])
		self.assertEqual(first["name"], second["name"])

	# ---------------------------------------------------------------- distributor
	#
	# The app never sends a distributor - a rep at a doorstep is not asked to pick one, and a
	# dropdown of every customer in the company is the wrong thing to hand somebody on a phone.
	# Every test above passes one explicitly, which is precisely why the real payload was never
	# exercised and a raw `[FieldMate Outlet, FM-OUT-05153]: distributor` reached a phone screen.

	def bare_payload(self, **kwargs):
		data = {"outlet_name": self.uid("NEW"), "mobile_no": "9800000199"}
		data.update(kwargs)
		return data

	def test_a_rep_with_no_distributor_is_told_what_to_do(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.as_user(self.rep.user, outlet_service.create, self.bare_payload())
		message = frappe.utils.strip_html(str(ctx.exception))
		self.assertIn("not linked to a distributor", message)
		# The thing that must never happen again: a framework error on a rep's screen.
		self.assertNotIn("FieldMate Outlet,", message)

	def test_the_reps_own_distributor_is_used_when_the_app_sends_none(self):
		self.rep.distributor = self.mine.distributor
		self.rep.save(ignore_permissions=True)
		frappe.db.commit()

		result = self.as_user(self.rep.user, outlet_service.create, self.bare_payload())
		self.track("FieldMate Outlet", result["name"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Outlet", result["name"], "distributor"),
			self.mine.distributor,
		)

	def serves(self, customer: str, territory: str) -> str:
		"""Make this Customer the distributor for a territory.

		What `outlet.create` looks for since step 2d: a Customer with tier Distributor covering
		the territory, in place of an Active FieldMate Distributor Profile. No undo needed -
		`make_distributor` builds a fresh Customer per call and setUp a fresh territory per test,
		so nothing here outlives the case that set it.
		"""
		frappe.db.set_value("Customer", customer,
		                    {"fm_tier": "Distributor", "territory": territory, "disabled": 0},
		                    update_modified=False)
		frappe.clear_document_cache("Customer", customer)
		return customer

	def test_a_single_distributor_serving_the_territory_is_inferred(self):
		self.serves(self.mine.distributor, self.delhi)
		frappe.db.commit()

		result = self.as_user(self.rep.user, outlet_service.create, self.bare_payload())
		self.track("FieldMate Outlet", result["name"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Outlet", result["name"], "distributor"),
			self.mine.distributor,
		)

	def test_two_distributors_on_one_territory_is_not_guessed_at(self):
		"""Picking one at random would put the shop's orders on the wrong ledger."""
		for _ in range(2):
			self.serves(self.make_distributor(), self.delhi)
		frappe.db.commit()

		with self.assertRaises(frappe.ValidationError) as ctx:
			self.as_user(self.rep.user, outlet_service.create, self.bare_payload())
		self.assertIn("More than one distributor", str(ctx.exception))

	def test_rep_without_permission_cannot_onboard(self):
		self.rep.can_create_outlet = 0
		self.rep.save(ignore_permissions=True)
		frappe.db.commit()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rep.user, outlet_service.create, {
				"outlet_name": self.uid("NEW"), "mobile_no": "9800000125",
				"distributor": self.mine.distributor, "territory": self.delhi,
			})

	# ---------------------------------------------------------------- update

	def test_rep_may_fix_a_phone_number(self):
		result = self.as_user(self.rep.user, outlet_service.update,
		                      self.mine.name, {"mobile_no": "9899999999"})
		self.assertEqual(result["changed"], ["mobile_no"])

	def test_rep_cannot_change_its_own_approval(self):
		"""Fields outside the editable set are ignored, not rejected, so a newer app build
		sending an extra field never breaks an older server."""
		self.as_user(self.rep.user, outlet_service.update,
		             self.mine.name, {"approval_status": "Approved", "credit_limit": 999999})
		self.mine.reload()
		self.assertEqual(self.mine.approval_status, "Pending Approval")
		self.assertFalse(self.mine.credit_limit)

	def test_moving_the_pin_stamps_the_time(self):
		self.as_user(self.rep.user, outlet_service.update,
		             self.mine.name, {"latitude": 28.61, "longitude": 77.20})
		self.mine.reload()
		self.assertIsNotNone(self.mine.geo_captured_on)

	# ---------------------------------------------------------------- approve

	def test_manager_approves(self):
		result = self.as_user(self.manager.user, outlet_service.approve,
		                      self.mine.name, "Approved")
		self.assertEqual(result["approval_status"], "Approved")
		self.assertEqual(result["approved_by"], self.manager.user)

	def test_rep_cannot_approve(self):
		"""Otherwise the approval queue is decorative."""
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rep.user, outlet_service.approve, self.mine.name, "Approved")

	def test_decision_must_be_a_real_decision(self):
		with self.assertRaises(ValueError):
			self.as_user(self.manager.user, outlet_service.approve, self.mine.name, "Maybe")

	def test_approved_outlet_can_take_an_order(self):
		self.as_user(self.manager.user, outlet_service.approve, self.mine.name, "Approved")
		payload = self.as_user(self.rep.user, outlet_service.detail, self.mine.name)
		self.assertTrue(payload["can_take_order"])


class TestOutletImport(OutletFixture):
	def setUp(self):
		super().setUp()
		self.territory = self.make_territory()
		self.distributor = self.make_distributor()

	def row(self, **overrides):
		data = {
			"outlet_name": self.uid("SHOP"),
			"mobile_no": "9812345678",
			"distributor": self.distributor,
			"territory": self.territory,
			"latitude": "28.7041",
			"longitude": "77.1025",
			"pincode": "110009",
		}
		data.update(overrides)
		return data

	def test_clean_file_imports_with_no_errors(self):
		rows = [self.row() for _ in range(5)]
		result = importer_service.import_outlets(rows)
		for created in result["created"]:
			self.track("FieldMate Outlet", created["name"])
		self.assertEqual(result["failed"], 0)
		self.assertEqual(len(result["created"]), 5)

	def test_dry_run_writes_nothing(self):
		before = frappe.db.count("FieldMate Outlet")
		result = importer_service.import_outlets([self.row()], dry_run=True)
		self.assertTrue(result["dry_run"])
		self.assertEqual(result["created"], [])
		self.assertEqual(frappe.db.count("FieldMate Outlet"), before)

	def test_bad_rows_are_reported_and_the_good_ones_still_land(self):
		"""The Gate 1 behaviour: a file is never rejected wholesale."""
		rows = [
			self.row(),
			self.row(mobile_no="not-a-number"),
			self.row(),
			self.row(territory="No Such Territory"),
			self.row(latitude="500", longitude="77.1"),
		]
		result = importer_service.import_outlets(rows)
		for created in result["created"]:
			self.track("FieldMate Outlet", created["name"])

		self.assertEqual(len(result["created"]), 2)
		self.assertEqual(result["failed"], 3)
		self.assertEqual({e["row"] for e in result["errors"]}, {3, 5, 6})

	def test_errors_name_the_row_the_column_and_the_fix(self):
		result = importer_service.import_outlets(
			[self.row(territory="Nowhere")], dry_run=True
		)
		error = result["errors"][0]
		self.assertEqual(error["row"], 2)          # 1-based, counting the header
		self.assertEqual(error["column"], "territory")
		self.assertIn("does not exist", error["message"])

	def test_half_a_coordinate_is_refused(self):
		result = importer_service.import_outlets(
			[self.row(longitude="")], dry_run=True
		)
		self.assertIn("together", result["errors"][0]["message"])

	def test_null_island_is_refused(self):
		"""0,0 is in the Atlantic and is what an empty GPS field becomes when coerced."""
		result = importer_service.import_outlets(
			[self.row(latitude="0", longitude="0")], dry_run=True
		)
		self.assertIn("Atlantic", result["errors"][0]["message"])

	def test_duplicate_rows_inside_one_file_are_caught(self):
		same = self.row()
		result = importer_service.import_outlets([same, dict(same)], dry_run=True)
		self.assertIn("same shop and mobile as row 2", result["errors"][0]["message"])

	def test_reimporting_the_same_client_uuid_skips_rather_than_duplicates(self):
		row = self.row(client_uuid=self.uid("U"))
		first = importer_service.import_outlets([row])
		self.track("FieldMate Outlet", first["created"][0]["name"])
		second = importer_service.import_outlets([row])
		self.assertEqual(second["created"], [])
		self.assertEqual(len(second["skipped_existing"]), 1)

	def test_template_lists_required_columns_and_an_example(self):
		template = importer_service.outlet_template()
		self.assertIn("outlet_name", template["required"])
		self.assertIn("territory", template["required"])
		self.assertEqual(set(template["example"]), set(template["columns"]))

	def test_imported_outlets_are_approved(self):
		"""An import is an administrative act, not a field onboarding."""
		result = importer_service.import_outlets([self.row()])
		name = result["created"][0]["name"]
		self.track("FieldMate Outlet", name)
		self.assertEqual(
			frappe.db.get_value("FieldMate Outlet", name, "approval_status"), "Approved"
		)
