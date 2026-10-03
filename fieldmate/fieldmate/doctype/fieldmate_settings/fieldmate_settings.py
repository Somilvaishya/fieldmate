import frappe
from frappe.model.document import Document
from frappe.utils import cint

# Bounds that stop a typo becoming a field-wide outage. Each is a real limit, not a guess:
# a 5 second ping drains a battery before lunch, a 2000-record batch times out on 3G.
BOUNDS = {
	"default_geo_fence_radius_m": (10, 5000),
	"min_visit_duration_minutes": (0, 120),
	"gps_ping_interval_seconds": (30, 900),
	"auto_close_day_after_hours": (1, 24),
	"sync_batch_size": (1, 500),
	"sync_max_retries": (1, 20),
	"photo_max_kb": (20, 2000),
	"photo_max_dimension_px": (320, 4096),
	"gps_trail_retention_days": (1, 3650),
	"selfie_retention_days": (1, 3650),
	"visit_photo_retention_days": (1, 3650),
}


class FieldMateSettings(Document):
	def validate(self):
		self.validate_sales_model()
		self.validate_bounds()

	def validate_sales_model(self):
		# One model today. The check is kept rather than deleted because it is the thing that
		# stops a site being saved with nothing a rep can sell in, and Phase 1 adds the modes
		# back beside this line.
		if not self.enable_order_booking:
			frappe.throw(
				frappe._("Enable at least one sales model. With none, no rep can sell anything.")
			)

	def validate_bounds(self):
		for fieldname, (low, high) in BOUNDS.items():
			value = cint(self.get(fieldname))
			if value < low or value > high:
				label = self.meta.get_label(fieldname)
				frappe.throw(
					frappe._("{0} must be between {1} and {2}. Got {3}.").format(
						label, low, high, value
					)
				)

	def on_update(self):
		# Settings are read on every bootstrap; a stale cache would keep a changed geo fence
		# or photo limit out of the field until the next restart.
		frappe.cache().delete_value("fieldmate_settings")
