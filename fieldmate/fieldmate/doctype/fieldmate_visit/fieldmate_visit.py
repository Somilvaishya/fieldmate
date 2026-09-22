import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, time_diff_in_seconds


class FieldMateVisit(Document):
	"""A rep's stop at one shop.

	Every derived field is recomputed here rather than trusted from the payload. The API is not
	the only way a visit arrives - the offline queue pushes rows straight through `frappe.get_doc`,
	and `read_only` in the DocType JSON only greys out a desk field; it stops nothing over REST.
	This controller is the single place a faked distance or a self-declared 'planned' visit dies.
	"""

	def validate(self):
		self.assert_own_visit()
		self.set_visit_date()
		self.recompute_geo()
		self.recompute_plan()
		self.recompute_duration()
		self.resnapshot_checklist()

	def before_submit(self):
		if not self.check_out_time:
			frappe.throw(frappe._("Check out of the shop before submitting the visit."))
		if not self.visit_outcome:
			frappe.throw(frappe._("A submitted visit needs an outcome."))

	# ------------------------------------------------------------------ ownership

	def assert_own_visit(self):
		"""A rep may only record their own visits.

		The `if_owner` rule ties the record to whoever created it, but it says nothing about
		the `field_user` *named* on it. Without this, a rep sharing a territory could push
		visits onto a colleague's name and either pad or sabotage their coverage.
		"""
		if not self.is_new():
			return
		if frappe.session.user in ("Administrator", "Guest"):
			return

		from fieldmate.services import field_user as field_user_service

		mine = field_user_service.for_user()
		if not mine or self.field_user == mine:
			return
		# Managers legitimately record on behalf of their team; write access is what marks them.
		if frappe.has_permission("FieldMate Visit", "write"):
			return
		frappe.throw(
			frappe._("You can only record your own visits."), frappe.PermissionError
		)

	# ------------------------------------------------------------------ derived

	def set_visit_date(self):
		# A visit belongs to the day it started, not the day it was pushed. A rep syncing at
		# midnight must not have this morning's work land on tomorrow.
		if not self.visit_date and self.check_in_time:
			self.visit_date = getdate(self.check_in_time)

	def recompute_geo(self):
		from fieldmate.services.visit import geo_check

		outlet = frappe.get_cached_doc("FieldMate Outlet", self.outlet)
		geo = geo_check(outlet, self.check_in_latitude, self.check_in_longitude)
		self.distance_from_outlet_m = geo["distance_from_outlet_m"]

		# An approved exception clears the flag; a pending one does not. Until somebody has
		# actually looked, the breach stands.
		if geo["is_geo_fence_breach"] and self.geo_fence_exception:
			status = frappe.db.get_value(
				"FieldMate Geo Fence Exception", self.geo_fence_exception, "status"
			)
			self.is_geo_fence_breach = 0 if status == "Approved" else 1
		else:
			self.is_geo_fence_breach = geo["is_geo_fence_breach"]

	def recompute_plan(self):
		from fieldmate.services.visit import is_on_beat

		on_beat = bool(self.beat) and is_on_beat(self.beat, self.outlet)
		self.is_planned = 1 if on_beat else 0
		self.is_deviation = 0 if on_beat else 1

	def recompute_duration(self):
		from fieldmate.services.visit import minimum_minutes

		if not (self.check_in_time and self.check_out_time):
			self.duration_minutes = 0
			self.is_short_visit = 0
			return

		check_in = get_datetime(self.check_in_time)
		check_out = get_datetime(self.check_out_time)
		if check_out < check_in:
			frappe.throw(frappe._("Check-out cannot be before check-in."))

		self.duration_minutes = max(
			0, round(time_diff_in_seconds(check_out, check_in) / 60.0)
		)
		outlet = frappe.get_cached_doc("FieldMate Outlet", self.outlet)
		self.is_short_visit = 1 if self.duration_minutes < minimum_minutes(outlet) else 0

	# ------------------------------------------------------------------ checklist

	def resnapshot_checklist(self):
		"""Take the question wording from the template, never from the device.

		A visit captured offline arrives with answers the phone built from a cached form. The
		answers are the rep's and are kept as sent; the wording, the version and whether an
		answer was required are the template's, and are rewritten here. Otherwise a phone with
		a stale cache - or an edited one - could record a visit as having asked something it
		never asked, which is the one thing a checklist exists to prove.
		"""
		if not self.checklist_answers:
			return

		from fieldmate.services.visit import build_checklist

		outlet = frappe.get_cached_doc("FieldMate Outlet", self.outlet)
		authoritative = {
			row["question_code"]: row
			for row in build_checklist(outlet, self.field_user, self.visit_date)
		}

		for row in self.checklist_answers:
			source = authoritative.get(row.question_code)
			if not source:
				# Answered against a template that no longer applies. The answer is kept -
				# the rep did the work - but nothing about it is claimed as current.
				row.template = None
				row.template_version = 0
				row.is_required = 0
				continue
			row.question = source["question"]
			row.answer_type = source["answer_type"]
			row.is_required = source["is_required"]
			row.sequence = source["sequence"]
			row.template = source["template"]
			row.template_version = source["template_version"]

	# No visit-count rollup onto the day: `day_service.day_counts` already counts submitted
	# visits straight from this table when the rep ends their day. A denormalised tally kept in
	# two places is a tally that will eventually disagree with itself.
