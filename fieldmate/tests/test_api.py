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
