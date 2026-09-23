import frappe

from fieldmate.api import _base
from fieldmate.tests.base import FieldMateTestCase


class TestEnvelope(FieldMateTestCase):
	def test_ok_shape(self):
		payload = _base.ok({"x": 1})
		self.assertTrue(payload["ok"])
		self.assertEqual(payload["v"], _base.API_VERSION)
		self.assertEqual(payload["data"]["x"], 1)

	def test_fail_shape(self):
		payload = _base.fail(_base.Err.BAD_REQUEST, "nope")
		self.assertFalse(payload["ok"])
		self.assertEqual(payload["code"], "BAD_REQUEST")
		self.assertEqual(payload["message"], "nope")

	def test_endpoint_converts_known_errors(self):
		@_base.endpoint(require_auth=False)
		def boom():
			raise _base.FieldMateError(_base.Err.CONFLICT, "clash")

		result = boom()
		self.assertFalse(result["ok"])
		self.assertEqual(result["code"], "CONFLICT")

	def test_endpoint_hides_unexpected_errors(self):
		"""Never leak a stack trace or SQL error to a phone."""
		@_base.endpoint(require_auth=False)
		def boom():
			raise RuntimeError("SELECT * FROM tabSecret failed at line 42")

		result = boom()
		self.assertEqual(result["code"], "INTERNAL")
		self.assertNotIn("tabSecret", result["message"])
		self.assertIn("saved on this device", result["message"])

	def test_parse_json_accepts_both_forms(self):
		self.assertEqual(_base.parse_json('[{"a":1}]', "x"), [{"a": 1}])
		self.assertEqual(_base.parse_json([{"a": 1}], "x"), [{"a": 1}])

	def test_parse_json_rejects_garbage(self):
		with self.assertRaises(_base.FieldMateError):
			_base.parse_json("{not json", "x")


class TestReadableErrors(FieldMateTestCase):
	"""Every message from the API is read on a phone, in a market, with no support line.

	A raw MandatoryError reached a real screen during Phase 3 testing - the rep saw
	`[FieldMate Outlet, FM-OUT-05153]: distributor` and could do nothing with it. This guards
	every endpoint at once, because the translation lives in the decorator.
	"""

	def test_a_mandatory_error_becomes_a_sentence(self):
		message = _base.readable(
			frappe.MandatoryError("[FieldMate Outlet, FM-OUT-05153]: distributor")
		)
		self.assertNotIn("[", message)
		self.assertNotIn("FM-OUT-05153", message)
		self.assertTrue(message.endswith("is required."), message)

	def test_the_field_label_is_used_not_the_column_name(self):
		message = _base.readable(
			frappe.MandatoryError("[FieldMate Outlet, FM-OUT-00001]: mobile_no")
		)
		self.assertIn("Mobile", message)
		self.assertNotIn("mobile_no", message)

	def test_several_missing_fields_are_listed(self):
		message = _base.readable(
			frappe.MandatoryError("[FieldMate Outlet, new]: outlet_name, mobile_no")
		)
		self.assertIn("These are required:", message)
		self.assertIn("Mobile", message)

	def test_an_unknown_doctype_still_degrades_to_words(self):
		"""A message we cannot decode is still better than one we invent."""
		message = _base.readable(frappe.MandatoryError("[No Such DocType, x]: some_field"))
		self.assertIn("some field", message)

	def test_our_own_messages_pass_through_untouched(self):
		ours = "Start your day before visiting a shop."
		self.assertEqual(_base.readable(frappe.ValidationError(ours)), ours)

	def test_html_is_stripped(self):
		message = _base.readable(frappe.ValidationError("Row <b>3</b>: fix this"))
		self.assertEqual(message, "Row 3: fix this")

	def test_an_empty_error_still_says_something(self):
		self.assertTrue(_base.readable(frappe.ValidationError("")))


class TestDeviceResolution(FieldMateTestCase):
	def test_unknown_device_is_rejected(self):
		with self.assertRaises(_base.FieldMateError) as ctx:
			_base.resolve_device(self.uid("NOPE"))
		self.assertEqual(ctx.exception.code, _base.Err.DEVICE_UNKNOWN)

	def test_missing_device_id_is_rejected(self):
		with self.assertRaises(_base.FieldMateError) as ctx:
			_base.resolve_device(None)
		self.assertEqual(ctx.exception.code, _base.Err.BAD_REQUEST)

	def test_inactive_device_is_refused(self):
		device = frappe.get_doc({
			"doctype": "FieldMate Device Registry",
			"device_uuid": self.uid("DEV"),
			"user": "Administrator",
			"status": "Suspended",
		}).insert(ignore_permissions=True)
		self.track("FieldMate Device Registry", device.name)
		with self.assertRaises(frappe.PermissionError):
			device.assert_active()
