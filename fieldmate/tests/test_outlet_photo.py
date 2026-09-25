import frappe

from fieldmate.tests.test_outlet import OutletFixture

# A 1x1 PNG. What is being proved is the plumbing, not the picture.
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class TestOutletPhoto(OutletFixture):
	"""shop_photo is an Attach Image - varchar(140) holding a path, not bytes.

	A phone sends a base64 data URL of roughly 120 KB. Storing it raw fails with "Data too
	long for column", which is exactly how the start-of-day selfie broke in Phase 2. The
	conversion lives in the controller so the offline queue, which pushes outlets straight
	through frappe.get_doc, is covered by the same code.
	"""

	def test_a_camera_capture_is_stored_as_a_file(self):
		outlet = self.make_outlet(shop_photo=PIXEL)
		self.assertTrue(
			outlet.shop_photo.startswith(("/files/", "/private/files/")),
			f"expected a file path, got {outlet.shop_photo[:40]!r}",
		)
		self.assertLessEqual(len(outlet.shop_photo), 140)

	def test_an_already_uploaded_path_is_left_alone(self):
		"""An older app build that uploads separately must keep working."""
		outlet = self.make_outlet(shop_photo="/files/already-there.jpg")
		self.assertEqual(outlet.shop_photo, "/files/already-there.jpg")

	def test_no_photo_is_not_an_error(self):
		self.assertIsNone(self.make_outlet().shop_photo)

	def test_the_board_photo_is_converted_too(self):
		outlet = self.make_outlet(shop_board_photo=PIXEL)
		self.assertTrue(outlet.shop_board_photo.startswith(("/files/", "/private/files/")))

	def test_a_pushed_outlet_carries_a_photo_without_failing(self):
		"""The offline path: the queue inserts the document directly, bypassing the API."""
		doc = frappe.get_doc({
			"doctype": "FieldMate Outlet",
			"outlet_name": self.uid("SHOP"),
			"mobile_no": "9800000001",
			"distributor": self.make_distributor(),
			"territory": self.make_territory(),
			"shop_photo": PIXEL,
			"created_offline": 1,
		}).insert(ignore_permissions=True)
		self.track("FieldMate Outlet", doc.name)
		self.assertTrue(doc.shop_photo.startswith(("/files/", "/private/files/")))
