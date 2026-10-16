import base64

import frappe

from fieldmate.services import files as file_service
from fieldmate.tests.test_day import DayFixture

# A genuine 1x1 PNG.
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def big_png(kilobytes: int) -> str:
	"""A payload of a given size. Not a valid image, but base64 that decodes."""
	return "data:image/png;base64," + base64.b64encode(b"x" * kilobytes * 1024).decode()


class TestDataUrlFiles(DayFixture):
	def track_files(self):
		for name in frappe.get_all(
			"File", filters={"attached_to_doctype": "FieldMate Day"}, pluck="name"
		):
			self.track("File", name)

	def test_recognises_a_data_url(self):
		self.assertTrue(file_service.is_data_url(PIXEL))
		self.assertFalse(file_service.is_data_url("/private/files/photo.jpg"))
		self.assertFalse(file_service.is_data_url(None))

	def test_a_data_url_becomes_a_private_file(self):
		url = file_service.save_data_url(PIXEL, filename=self.uid("shot"))
		self.assertTrue(url.startswith("/private/files/"),
		                f"photos must be private, got {url}")

	def test_an_existing_path_passes_through_untouched(self):
		"""An older app build that uploads separately keeps working against a newer server."""
		path = "/private/files/already-there.jpg"
		self.assertEqual(
			file_service.attach_photo(path, "x", "FieldMate Day", "y", "selfie"), path
		)

	def test_nothing_in_nothing_out(self):
		self.assertIsNone(
			file_service.attach_photo(None, "x", "FieldMate Day", "y", "selfie")
		)

	def test_garbage_is_refused_in_words_a_rep_understands(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			file_service.save_data_url("data:image/png;base64,!!!not-base64!!!", "x")
		self.assertIn("Take it again", str(ctx.exception))

	def test_a_non_image_data_url_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			file_service.save_data_url("data:application/pdf;base64,AAAA", "x")

	def test_the_size_limit_is_enforced_on_the_server_too(self):
		"""The device limit is a budget. This is the control — a payload from a phone is never
		the only thing that could send one."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			file_service.save_data_url(big_png(300), filename="huge", max_kb=120)
		self.assertIn("over the 120 KB limit", str(ctx.exception))

	def test_a_photo_inside_the_limit_is_accepted(self):
		url = file_service.save_data_url(big_png(50), filename=self.uid("ok"), max_kb=120)
		self.assertTrue(url.startswith("/private/files/"))


class TestDayStartSelfie(DayFixture):
	def tearDown(self):
		for name in frappe.get_all(
			"File", filters={"attached_to_doctype": "FieldMate Day"}, pluck="name"
		):
			try:
				frappe.delete_doc("File", name, force=True, ignore_permissions=True)
			except Exception:
				pass
		super().tearDown()

	def test_a_photo_from_the_phone_is_stored_as_a_path_not_as_bytes(self):
		"""The regression this file exists for.

		`selfie` is an Attach Image, which is a varchar(140) holding a path. Writing the image
		into it failed at the database with 'Data too long for column selfie', and the rep saw
		only a generic error at the moment they were trying to begin work.
		"""
		result = self.start_day(selfie=PIXEL)
		stored = frappe.db.get_value("FieldMate Day", result["day"], "selfie")

		self.assertTrue(stored, "no selfie recorded")
		self.assertFalse(stored.startswith("data:"), "raw image bytes stored in a path column")
		self.assertLess(len(stored), 140, "value would not fit the column")
		self.assertTrue(stored.startswith("/private/"), "photos must be private")

	def test_starting_a_day_with_an_oversized_photo_says_why(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.start_day(selfie=big_png(400))
		self.assertIn("KB limit", str(ctx.exception))
