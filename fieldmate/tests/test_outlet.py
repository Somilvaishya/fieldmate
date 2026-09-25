import frappe

from fieldmate.services import registry
from fieldmate.services import sync as sync_service
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_field_user import FieldUserFixture


class OutletFixture(FieldUserFixture):
	def leaf_customer_group(self) -> str:
		"""A non-group Customer Group, named rather than inherited.

		Left unset, ERPNext fills it from Selling Settings, and on a site whose default is the
		root node ("All Customer Groups") every Customer insert throws. That made the whole
		suite depend on one piece of site configuration nobody here owns.
		"""
		existing = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		if existing:
			return existing

		doc = frappe.get_doc({
			"doctype": "Customer Group",
			"customer_group_name": self.uid("CG"),
			"parent_customer_group": frappe.db.get_value(
				"Customer Group", {"is_group": 1, "parent_customer_group": ("in", ("", None))},
				"name",
			),
			"is_group": 0,
		}).insert(ignore_permissions=True)
		self.track("Customer Group", doc.name)
		return doc.name

	def make_distributor(self):
		name = self.uid("DIST")
		doc = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": self.leaf_customer_group(),
		}).insert(ignore_permissions=True)
		self.track("Customer", doc.name)
		return doc.name

	def make_outlet(self, **kwargs):
		data = {
			"doctype": "FieldMate Outlet",
			"outlet_name": kwargs.pop("outlet_name", None) or self.uid("SHOP"),
			"mobile_no": "9800000000",
			"distributor": kwargs.pop("distributor", None) or self.make_distributor(),
			"territory": kwargs.pop("territory", None) or self.make_territory(),
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Outlet", doc.name)
		return doc


class TestOutletLifecycle(OutletFixture):
	def test_new_outlet_is_named_by_series(self):
		outlet = self.make_outlet()
		self.assertTrue(outlet.name.startswith("FM-OUT-"))
		self.assertEqual(outlet.onboarding_date, frappe.utils.today())

	def test_outlet_starts_unapproved(self):
		self.assertEqual(self.make_outlet().approval_status, "Pending Approval")

	def test_pending_outlet_can_be_visited_but_not_sold_to(self):
		"""Blocking capture in the field guarantees the data never gets entered at all."""
		outlet = self.make_outlet()
		allowed, reason = outlet.can_take_order()
		self.assertFalse(allowed)
		self.assertIn("waiting for approval", reason)

	def test_approved_outlet_can_take_an_order(self):
		outlet = self.make_outlet()
		outlet.approval_status = "Approved"
		outlet.save(ignore_permissions=True)
		allowed, _ = outlet.can_take_order()
		self.assertTrue(allowed)

	def test_closed_outlet_cannot_take_an_order(self):
		outlet = self.make_outlet(approval_status="Approved")
		outlet.outlet_status = "Closed"
		outlet.save(ignore_permissions=True)
		allowed, reason = outlet.can_take_order()
		self.assertFalse(allowed)
		self.assertIn("Closed", reason)

	def test_approval_records_who_approved(self):
		outlet = self.make_outlet()
		outlet.approval_status = "Approved"
		outlet.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("FieldMate Outlet", outlet.name, "approved_by"),
			frappe.session.user,
		)

	def test_rejecting_clears_the_approver(self):
		outlet = self.make_outlet()
		outlet.approval_status = "Approved"
		outlet.save(ignore_permissions=True)
		outlet.reload()
		outlet.approval_status = "Rejected"
		outlet.save(ignore_permissions=True)
		self.assertFalse(
			frappe.db.get_value("FieldMate Outlet", outlet.name, "approved_by")
		)


class TestOutletValidation(OutletFixture):
	def test_impossible_latitude_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_outlet(latitude=120, longitude=77)
		self.assertIn("Latitude", str(ctx.exception))

	def test_impossible_longitude_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_outlet(latitude=28.6, longitude=400)

	def test_capturing_location_stamps_the_time(self):
		outlet = self.make_outlet(latitude=28.6139, longitude=77.2090)
		self.assertIsNotNone(outlet.geo_captured_on)

	def test_absurd_geo_fence_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_outlet(geo_fence_radius_m=2)

	def test_geo_fence_falls_back_to_settings(self):
		from fieldmate.services import settings as settings_service
		outlet = self.make_outlet()
		self.assertEqual(
			outlet.effective_geo_fence_radius(),
			settings_service.value("default_geo_fence_radius_m"),
		)

	def test_outlet_specific_geo_fence_wins(self):
		self.assertEqual(self.make_outlet(geo_fence_radius_m=250).effective_geo_fence_radius(), 250)

	def test_a_directly_billed_outlet_needs_no_mode_switched_on(self):
		"""ADR-024. A Customer here is ADR-001's escape hatch, not a van-sales setting.

		The old rule refused it unless van sales was enabled, on ADR-016's claim that the shop
		was billed on the spot in that mode. That claim was wrong - a van sale is the
		distributor's sale too - so the mode never had anything to say about this.
		"""
		outlet = self.make_outlet(customer=self.make_distributor())
		self.assertTrue(outlet.customer)

	def test_a_shop_cannot_be_billed_direct_by_its_own_distributor(self):
		"""Both at once would make the seller test answer yes and no to one question."""
		shared = self.make_distributor()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_outlet(distributor=shared, customer=shared)
		self.assertIn("also its distributor", str(ctx.exception))

	def test_only_one_primary_contact(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_outlet(contacts=[
				{"person_name": "A", "is_primary": 1},
				{"person_name": "B", "is_primary": 1},
			])
		self.assertIn("one contact", str(ctx.exception))

	def test_billing_party_is_the_distributor_in_order_booking(self):
		outlet = self.make_outlet()
		self.assertEqual(outlet.billing_party(), outlet.distributor)


class TestOutletTerritoryScoping(OutletFixture):
	"""The proof owed from task 1.2: a rep must not read another district's shops.

	Task 1.2 could only show that the User Permission rows were written correctly. This runs the
	query as the rep and checks what actually comes back.
	"""

	def setUp(self):
		super().setUp()
		self.north = self.make_territory()                      # group
		self.delhi = self.make_territory(parent=self.north)
		self.mumbai = self.make_territory(parent=self.north)

		self.delhi_shop = self.make_outlet(territory=self.delhi)
		self.mumbai_shop = self.make_outlet(territory=self.mumbai)

		self.rep = self.make_field_user(territory=self.delhi)
		self.manager = self.make_field_user(territory=self.north, designation="Area Manager")
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def visible_outlets(self, user):
		# get_list, never get_all: get_all forces ignore_permissions=True, so it would pass
		# whether scoping worked or not.
		frappe.set_user(user)
		try:
			return {r.name for r in frappe.get_list("FieldMate Outlet", fields=["name"],
			                                        limit_page_length=0)}
		finally:
			frappe.set_user("Administrator")

	def pulled_outlets(self, user):
		"""What sync.pull would actually send to this rep's phone."""
		from fieldmate.services import sync as sync_service
		frappe.set_user(user)
		try:
			result = sync_service.pull(user)
			return {r["name"] for r in result["changes"].get("FieldMate Outlet", [])}
		finally:
			frappe.set_user("Administrator")

	def test_rep_sees_only_their_own_district(self):
		visible = self.visible_outlets(self.rep.user)
		self.assertIn(self.delhi_shop.name, visible)
		self.assertNotIn(self.mumbai_shop.name, visible)

	def test_manager_on_a_parent_node_sees_both_districts(self):
		visible = self.visible_outlets(self.manager.user)
		self.assertIn(self.delhi_shop.name, visible)
		self.assertIn(self.mumbai_shop.name, visible)

	def test_sync_pull_sends_only_the_reps_own_district(self):
		"""The one that matters: this is what physically lands on the phone."""
		pulled = self.pulled_outlets(self.rep.user)
		self.assertIn(self.delhi_shop.name, pulled)
		self.assertNotIn(self.mumbai_shop.name, pulled)

	def test_sync_pull_gives_a_manager_both_districts(self):
		pulled = self.pulled_outlets(self.manager.user)
		self.assertIn(self.delhi_shop.name, pulled)
		self.assertIn(self.mumbai_shop.name, pulled)

	def test_moving_a_rep_moves_what_they_can_see(self):
		self.rep.territory = self.mumbai
		self.rep.save(ignore_permissions=True)
		frappe.db.commit()

		visible = self.visible_outlets(self.rep.user)
		self.assertIn(self.mumbai_shop.name, visible)
		self.assertNotIn(self.delhi_shop.name, visible)


class TestOutletSync(OutletFixture):
	"""Outlet is the first real syncable master, so the offline contract gets exercised
	against something a rep actually creates rather than a stand-in."""

	def setUp(self):
		super().setUp()
		self.device = frappe.get_doc({
			"doctype": "FieldMate Device Registry",
			"device_uuid": self.uid("DEV"),
			"user": "Administrator",
			"platform": "Android",
		}).insert(ignore_permissions=True)
		self.track("FieldMate Device Registry", self.device.name)
		self.distributor = self.make_distributor()
		self.territory = self.make_territory()

	def tearDown(self):
		for name in frappe.get_all("FieldMate Outlet",
		                           filters={"client_uuid": ["like", "T-%"]}, pluck="name"):
			frappe.delete_doc("FieldMate Outlet", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("FieldMate Sync Batch",
		                           filters={"batch_uuid": ["like", "T-%"]}, pluck="name"):
			frappe.delete_doc("FieldMate Sync Batch", name, force=True, ignore_permissions=True)
		super().tearDown()

	def record(self, **overrides):
		data = {
			"outlet_name": self.uid("SHOP"),
			"mobile_no": "9800000001",
			"distributor": self.distributor,
			"territory": self.territory,
		}
		data.update(overrides)
		return {"doctype": "FieldMate Outlet", "client_uuid": self.uid("T"), "data": data}

	def test_outlet_is_pushable(self):
		self.assertTrue(registry.is_pushable("FieldMate Outlet"))

	def test_rep_created_outlet_syncs(self):
		records = [self.record() for _ in range(3)]
		result = sync_service.push("Administrator", self.device, self.uid("T"), records)
		self.assertEqual(result["accepted"], 3)
		self.assertEqual(result["status"], "Completed")

	def test_replaying_the_batch_creates_no_second_shop(self):
		records = [self.record() for _ in range(5)]
		batch = self.uid("T")
		sync_service.push("Administrator", self.device, batch, records)
		again = sync_service.push("Administrator", self.device, batch, records)

		self.assertTrue(again["replayed"])
		uuids = [r["client_uuid"] for r in records]
		self.assertEqual(frappe.db.count("FieldMate Outlet", {"client_uuid": ["in", uuids]}), 5)

	def test_device_cannot_approve_its_own_outlet(self):
		"""server_owned strips this. Otherwise manager approval would be decorative."""
		rec = self.record()
		rec["data"]["approval_status"] = "Approved"
		rec["data"]["approved_by"] = "Administrator"
		sync_service.push("Administrator", self.device, self.uid("T"), [rec])

		name = frappe.db.get_value("FieldMate Outlet", {"client_uuid": rec["client_uuid"]}, "name")
		self.assertEqual(
			frappe.db.get_value("FieldMate Outlet", name, "approval_status"), "Pending Approval"
		)

	def test_a_bad_outlet_does_not_sink_the_batch(self):
		good = [self.record(), self.record()]
		bad = self.record(latitude=999)
		result = sync_service.push("Administrator", self.device, self.uid("T"), [*good, bad])
		self.assertEqual(result["accepted"], 2)
		self.assertEqual(result["conflicts"], 1)
		self.assertEqual(result["status"], "Partial")


class TestSmallMasters(FieldMateTestCase):
	def test_visits_per_month_is_bounded(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "FieldMate Outlet Class",
				"class_name": self.uid("CLS"),
				"visits_per_month": 99,
			}).insert(ignore_permissions=True)

	def test_max_potential_cannot_be_below_min(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "FieldMate Outlet Class",
				"class_name": self.uid("CLS"),
				"min_monthly_potential": 5000,
				"max_monthly_potential": 100,
			}).insert(ignore_permissions=True)

	def test_channel_is_created(self):
		doc = frappe.get_doc({
			"doctype": "FieldMate Outlet Channel",
			"channel_name": self.uid("CH"),
		}).insert(ignore_permissions=True)
		self.track("FieldMate Outlet Channel", doc.name)
		self.assertTrue(doc.is_active)
