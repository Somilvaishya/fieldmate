import frappe
from frappe.utils import add_days, today

from fieldmate.tests.test_outlet import OutletFixture


class MasterFixture(OutletFixture):
	def make_item(self):
		code = self.uid("ITEM")
		doc = frappe.get_doc(self.with_hsn({
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
			"stock_uom": frappe.db.get_value("UOM", {}, "name") or "Nos",
			"is_stock_item": 0,
		})).insert(ignore_permissions=True)
		self.track("Item", doc.name)
		return doc.name

	def make_class(self, **kwargs):
		data = {"doctype": "FieldMate Outlet Class", "class_name": self.uid("CLS")}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Outlet Class", doc.name)
		return doc.name


# TestDistributorProfile stood here. It asserted that a FieldMate Distributor Profile was named
# after its Customer, that there could only be one per Customer, and that its outstanding figure
# came from the ledger rather than being stored. All three have become true by construction: a
# distributor IS the Customer (step 2d), so there is no second record to name, to duplicate or to
# keep a stale number on. `test_party` covers what replaced it.


class TestProductCatalogue(MasterFixture):
	def make_catalogue(self, items=None, **kwargs):
		data = {
			"doctype": "FieldMate Product Catalogue",
			"catalogue_name": self.uid("CAT"),
			"items": [{"item_code": i} for i in (items or [])],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Product Catalogue", doc.name)
		return doc

	def test_item_count_is_computed(self):
		cat = self.make_catalogue(items=[self.make_item(), self.make_item()])
		self.assertEqual(cat.item_count, 2)

	def test_same_item_twice_is_refused(self):
		item = self.make_item()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_catalogue(items=[item, item])
		self.assertIn("listed twice", str(ctx.exception))

	def test_valid_to_before_valid_from_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_catalogue(valid_from=today(), valid_to=add_days(today(), -5))
		self.assertIn("Valid To cannot be before", str(ctx.exception))

	def test_max_qty_below_min_is_refused(self):
		item = self.make_item()
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.get_doc({
				"doctype": "FieldMate Product Catalogue",
				"catalogue_name": self.uid("CAT"),
				"items": [{"item_code": item, "min_order_qty": 10, "max_order_qty": 2}],
			}).insert(ignore_permissions=True)
		self.assertIn("Max Qty cannot be below", str(ctx.exception))

	def test_is_current_respects_the_window(self):
		cat = self.make_catalogue(valid_from=add_days(today(), -1), valid_to=add_days(today(), 1))
		self.assertTrue(cat.is_current())
		self.assertFalse(cat.is_current(add_days(today(), 30)))
		self.assertFalse(cat.is_current(add_days(today(), -30)))

	def test_inactive_catalogue_is_never_current(self):
		cat = self.make_catalogue()
		cat.is_active = 0
		cat.save(ignore_permissions=True)
		self.assertFalse(cat.is_current())


class TestMustSellList(MasterFixture):
	def make_list(self, items=None, **kwargs):
		data = {
			"doctype": "FieldMate Must Sell List",
			"list_name": self.uid("MSL"),
			"items": items if items is not None else [{"item_code": self.make_item()}],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Must Sell List", doc.name)
		return doc

	def test_active_list_needs_items(self):
		"""Scoring against nothing always reads 100%, which is worse than no score."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_list(items=[])
		self.assertIn("at least one item", str(ctx.exception))

	def test_inactive_list_may_be_empty(self):
		doc = self.make_list(items=[], is_active=0)
		self.assertEqual(doc.item_count, 0)

	def test_zero_weight_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_list(items=[{"item_code": self.make_item(), "weightage": 0}])
		self.assertIn("Weight must be above zero", str(ctx.exception))

	def test_total_weight_sums_the_lines(self):
		doc = self.make_list(items=[
			{"item_code": self.make_item(), "weightage": 2},
			{"item_code": self.make_item(), "weightage": 3},
		])
		self.assertEqual(doc.total_weight(), 5)

	def test_same_item_twice_is_refused(self):
		item = self.make_item()
		with self.assertRaises(frappe.ValidationError):
			self.make_list(items=[{"item_code": item}, {"item_code": item}])


class TestGeoFenceException(MasterFixture):
	def make_exception(self, **kwargs):
		outlet = kwargs.pop("outlet", None) or self.make_outlet(geo_fence_radius_m=100).name
		rep = kwargs.pop("field_user", None) or self.make_field_user().name
		data = {
			"doctype": "FieldMate Geo Fence Exception",
			"outlet": outlet,
			"field_user": rep,
			"distance_m": 450,
			"reason": "Shop has moved two lanes over; master pin is stale.",
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Geo Fence Exception", doc.name)
		return doc

	def test_exception_is_created_pending(self):
		doc = self.make_exception()
		self.assertEqual(doc.status, "Pending")
		self.assertTrue(doc.name.startswith("FM-GFE-"))

	def test_check_in_inside_the_fence_needs_no_exception(self):
		"""An approval queue full of non-exceptions is one nobody reads."""
		outlet = self.make_outlet(geo_fence_radius_m=200).name
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_exception(outlet=outlet, distance_m=50)
		self.assertIn("No exception is needed", str(ctx.exception))

	def test_fence_falls_back_to_settings(self):
		from fieldmate.services import settings as settings_service
		radius = settings_service.value("default_geo_fence_radius_m")
		outlet = self.make_outlet().name
		with self.assertRaises(frappe.ValidationError):
			self.make_exception(outlet=outlet, distance_m=radius - 1)

	def test_cannot_submit_while_still_pending(self):
		doc = self.make_exception()
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.submit()
		self.assertIn("Approve or reject", str(ctx.exception))

	def test_approving_records_who_and_when(self):
		doc = self.make_exception()
		doc.status = "Approved"
		doc.save(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.approved_by, frappe.session.user)
		self.assertIsNotNone(doc.decided_on)
		self.assertEqual(doc.docstatus, 1)

	def test_rejection_is_also_a_decision(self):
		doc = self.make_exception()
		doc.status = "Rejected"
		doc.save(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		self.assertIsNotNone(doc.decided_on)
