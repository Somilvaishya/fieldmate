import frappe
from frappe.utils import add_to_date, now_datetime, today

from fieldmate.services import settings as settings_service
from fieldmate.services import sync as sync_service
from fieldmate.services import visit as visit_service
from fieldmate.tests.test_day import DELHI, DayFixture

# ~450 m east of the Delhi fixture point, comfortably outside any sane shop fence.
FAR = (28.6139, 77.2136)
# ~20 m away: the sort of drift an ordinary phone produces standing at the counter.
NEAR = (28.61408, 77.20900)


class VisitFixture(DayFixture):
	def setUp(self):
		super().setUp()
		self.outlet = self.make_outlet(
			territory=self.territory,
			latitude=DELHI[0], longitude=DELHI[1],
			enable_geo_fence=1, geo_fence_radius_m=100,
			approval_status="Approved",
		)
		self.beat = self.make_beat(
			territory=self.territory, assigned_to=self.rep.name, outlets=[self.outlet.name]
		)
		settings_service.get()  # materialise the Single before tests poke at it

	def tearDown(self):
		for name in frappe.get_all("FieldMate Visit",
		                           filters={"field_user": self.rep.name}, pluck="name"):
			self._drop("FieldMate Visit", name)
		for dt in ("FieldMate Merchandising Audit", "FieldMate Geo Fence Exception"):
			for name in frappe.get_all(dt, filters={"field_user": self.rep.name}, pluck="name"):
				self._drop(dt, name)
		frappe.db.commit()
		super().tearDown()

	def _drop(self, doctype, name):
		try:
			doc = frappe.get_doc(doctype, name)
			if doc.meta.is_submittable and doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		except Exception:
			pass

	def set_setting(self, **kwargs):
		doc = frappe.get_single("FieldMate Settings")
		for key, value in kwargs.items():
			setattr(doc, key, value)
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")

	def check_in(self, **kwargs):
		self.start_day()
		payload = {
			"outlet": self.outlet.name,
			"latitude": NEAR[0], "longitude": NEAR[1], "accuracy_m": 9,
			"client_uuid": self.uid("VIS"),
			"device_id": self.device.name,
		}
		payload.update(kwargs)
		return visit_service.check_in(self.rep.name, payload)

	def check_out(self, visit, answer_required=True, **kwargs):
		"""Finish a visit the way a rep would: required questions answered.

		The site this runs on has its own live checklist templates - a real one always does -
		and they apply to the test's shops just as they would to any other. So unless a test is
		specifically about the blocking rule, it answers whatever is required first. Leaning on
		the site happening to be empty is what broke these tests the first time.
		"""
		if answer_required:
			self.answer_required(visit)
		payload = {"visit_outcome": "Order Taken", "latitude": NEAR[0], "longitude": NEAR[1]}
		payload.update(kwargs)
		return visit_service.check_out(visit, payload)

	def answer_required(self, visit):
		doc = frappe.get_doc("FieldMate Visit", visit)
		answers = [
			{"question_code": row.question_code,
			 "answer_number": 1 if row.answer_type in ("Number", "Rating") else None,
			 "answer": None if row.answer_type in ("Number", "Rating") else "Yes"}
			for row in doc.checklist_answers
			if row.is_required and not row.is_answered
		]
		if answers:
			visit_service.save_tasks(visit, {"answers": answers})

	def make_reason(self, **kwargs):
		data = {
			"doctype": "FieldMate No Order Reason",
			"reason": self.uid("WHY"),
			"category": "Stock",
			"is_active": 1,
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate No Order Reason", doc.name)
		return doc.name


# ----------------------------------------------------------------------------- check-in


class TestCheckIn(VisitFixture):
	def test_check_in_opens_a_visit(self):
		result = self.check_in()
		self.assertTrue(result["created"])
		self.assertTrue(result["visit"].startswith("FM-VIS-"))
		self.assertEqual(result["outlet"], self.outlet.name)
		self.assertEqual(result["visit_date"], today())

	def test_replaying_the_same_uuid_returns_the_same_visit(self):
		"""A retried push after a dropped connection must not double-count a shop."""
		uuid = self.uid("VIS")
		first = self.check_in(client_uuid=uuid)
		second = self.check_in(client_uuid=uuid)
		self.assertFalse(second["created"])
		self.assertEqual(first["visit"], second["visit"])

	def test_visiting_without_starting_the_day_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			visit_service.check_in(self.rep.name, {
				"outlet": self.outlet.name, "latitude": NEAR[0], "longitude": NEAR[1],
			})
		self.assertIn("Start your day", str(ctx.exception))

	def test_visits_are_numbered_in_order(self):
		self.check_in()
		second = self.check_in(client_uuid=self.uid("VIS"))
		self.assertEqual(second["visit_sequence"], 2)

	def test_walking_into_the_next_shop_no_longer_closes_the_previous_visit(self):
		"""This used to be the rule, written here as one: a check-in anywhere closed whatever
		visit was open. The reasoning was that a rep who forgot to check out must never be
		locked out of the next shop, and that part still holds - it is now a deliberate
		override rather than what happens by default. See TestAVisitEndsByCheckingOut.
		"""
		first = self.check_in()
		other = self.make_outlet(territory=self.territory, approval_status="Approved")
		with self.assertRaises(visit_service.OpenVisitError):
			self.check_in(outlet=other.name, client_uuid=self.uid("VIS"))

		still_open = frappe.get_doc("FieldMate Visit", first["visit"])
		self.assertFalse(still_open.check_out_time)

	def test_the_override_still_closes_it_and_says_why(self):
		first = self.check_in()
		other = self.make_outlet(territory=self.territory, approval_status="Approved")
		self.check_in(outlet=other.name, client_uuid=self.uid("VIS"), close_open_visit=1)

		closed = frappe.get_doc("FieldMate Visit", first["visit"])
		self.assertTrue(closed.check_out_time)
		self.assertEqual(closed.docstatus, 1)
		self.assertIn("Closed automatically", closed.remarks)

	def test_open_visit_is_resumable_after_an_app_restart(self):
		opened = self.check_in()
		self.assertEqual(visit_service.open_visit(self.rep.name)["visit"], opened["visit"])

	def test_no_open_visit_reads_as_none(self):
		self.assertIsNone(visit_service.open_visit(self.rep.name))


# ----------------------------------------------------------------------------- geo-fence


class TestGeoFence(VisitFixture):
	def test_distance_is_measured_from_the_shops_own_pin(self):
		result = self.check_in()
		self.assertLess(result["distance_from_outlet_m"], 40)

	def test_a_device_cannot_declare_its_own_distance(self):
		"""The whole point of the number is that the phone did not choose it."""
		result = self.check_in(latitude=FAR[0], longitude=FAR[1],
		                       distance_from_outlet_m=1, is_geo_fence_breach=0)
		self.assertGreater(result["distance_from_outlet_m"], 300)
		self.assertTrue(result["is_geo_fence_breach"])

	def test_a_far_check_in_is_recorded_not_refused(self):
		result = self.check_in(latitude=FAR[0], longitude=FAR[1])
		self.assertTrue(result["created"])
		self.assertTrue(result["is_geo_fence_breach"])

	def test_a_shop_with_no_pin_is_a_gap_not_a_breach(self):
		blind = self.make_outlet(territory=self.territory, approval_status="Approved",
		                         enable_geo_fence=1)
		result = self.check_in(outlet=blind.name)
		self.assertIsNone(result["distance_from_outlet_m"])
		self.assertFalse(result["is_geo_fence_breach"])
		self.assertEqual(result["geo"]["unmeasurable"], "shop has no pin")

	def test_no_gps_fix_is_a_gap_not_a_breach(self):
		result = self.check_in(latitude=None, longitude=None)
		self.assertFalse(result["is_geo_fence_breach"])
		self.assertEqual(result["geo"]["unmeasurable"], "no gps fix")

	def test_fence_off_on_the_shop_means_no_breach(self):
		open_shop = self.make_outlet(territory=self.territory, approval_status="Approved",
		                             latitude=DELHI[0], longitude=DELHI[1], enable_geo_fence=0)
		result = self.check_in(outlet=open_shop.name, latitude=FAR[0], longitude=FAR[1])
		self.assertGreater(result["distance_from_outlet_m"], 300)
		self.assertFalse(result["is_geo_fence_breach"])

	def test_enforcement_off_globally_still_measures_the_distance(self):
		"""Turning enforcement off should stop the flag, not stop the evidence."""
		self.set_setting(enforce_geo_fence=0)
		try:
			result = self.check_in(latitude=FAR[0], longitude=FAR[1])
			self.assertGreater(result["distance_from_outlet_m"], 300)
			self.assertFalse(result["is_geo_fence_breach"])
		finally:
			self.set_setting(enforce_geo_fence=1)

	def test_a_breach_raises_a_pending_exception(self):
		result = self.check_in(latitude=FAR[0], longitude=FAR[1])
		self.assertTrue(result["geo_fence_exception"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Geo Fence Exception",
			                    result["geo_fence_exception"], "status"),
			"Pending",
		)

	def test_a_pending_exception_does_not_clear_the_flag(self):
		"""Until a human has actually looked, the breach stands."""
		result = self.check_in(latitude=FAR[0], longitude=FAR[1])
		doc = frappe.get_doc("FieldMate Visit", result["visit"])
		doc.save(ignore_permissions=True)
		self.assertTrue(doc.is_geo_fence_breach)

	def test_an_approved_exception_clears_the_flag(self):
		result = self.check_in(latitude=FAR[0], longitude=FAR[1])
		exception = frappe.get_doc("FieldMate Geo Fence Exception",
		                           result["geo_fence_exception"])
		exception.status = "Approved"
		exception.decision_notes = "Shop moved; pin not updated yet."
		exception.flags.ignore_permissions = True
		exception.save()

		doc = frappe.get_doc("FieldMate Visit", result["visit"])
		doc.save(ignore_permissions=True)
		self.assertFalse(doc.is_geo_fence_breach)

	def test_outlet_class_radius_beats_the_global_default(self):
		self.outlet.geo_fence_radius_m = 500
		self.outlet.save(ignore_permissions=True)
		result = self.check_in(latitude=FAR[0], longitude=FAR[1])
		self.assertFalse(result["is_geo_fence_breach"])


# ----------------------------------------------------------------------------- planning


class TestPlannedAndDeviation(VisitFixture):
	def plan_today(self, beat=None):
		plan = frappe.get_doc({
			"doctype": "FieldMate Journey Plan",
			"field_user": self.rep.name,
			"from_date": today(),
			"to_date": today(),
			"days": [{"plan_date": today(), "beat": (beat or self.beat).name,
			          "status": "Planned", "is_working_day": 1,
			          "day_of_week": frappe.utils.getdate(today()).strftime("%A")}],
		}).insert(ignore_permissions=True)
		self.track("FieldMate Journey Plan", plan.name)
		plan.submit()
		return plan

	def test_a_shop_on_todays_beat_is_a_planned_visit(self):
		self.plan_today()
		result = self.check_in()
		self.assertTrue(result["is_planned"])
		self.assertFalse(result["is_deviation"])

	def test_a_shop_off_the_beat_is_a_deviation(self):
		self.plan_today()
		stray = self.make_outlet(territory=self.territory, approval_status="Approved")
		result = self.check_in(outlet=stray.name)
		self.assertFalse(result["is_planned"])
		self.assertTrue(result["is_deviation"])

	def test_a_deviation_is_recorded_not_blocked(self):
		self.plan_today()
		stray = self.make_outlet(territory=self.territory, approval_status="Approved")
		result = self.check_in(outlet=stray.name, deviation_reason=None,
		                       deviation_note="Owner called us in.")
		self.assertTrue(result["created"])

	def test_a_device_cannot_claim_a_visit_was_planned(self):
		stray = self.make_outlet(territory=self.territory, approval_status="Approved")
		result = self.check_in(outlet=stray.name, is_planned=1, is_deviation=0)
		self.assertFalse(result["is_planned"])
		self.assertTrue(result["is_deviation"])

	def test_with_no_plan_at_all_every_visit_is_a_deviation(self):
		result = self.check_in()
		self.assertFalse(result["is_planned"])


# ----------------------------------------------------------------------------- check-out


class TestCheckOut(VisitFixture):
	def test_check_out_submits_the_visit(self):
		opened = self.check_in()
		closed = self.check_out(opened["visit"])
		self.assertTrue(closed["checked_out_at"])
		self.assertEqual(frappe.db.get_value("FieldMate Visit", opened["visit"], "docstatus"), 1)

	def test_duration_is_measured_not_reported(self):
		opened = self.check_in(check_in_time=add_to_date(now_datetime(), minutes=-25))
		closed = self.check_out(opened["visit"], duration_minutes=1)
		self.assertGreaterEqual(closed["duration_minutes"], 24)

	def test_a_rushed_visit_is_flagged_short(self):
		opened = self.check_in()
		closed = self.check_out(opened["visit"])
		self.assertTrue(closed["is_short_visit"])

	def test_a_full_length_visit_is_not_short(self):
		opened = self.check_in(check_in_time=add_to_date(now_datetime(), minutes=-30))
		closed = self.check_out(opened["visit"])
		self.assertFalse(closed["is_short_visit"])

	def test_outlet_class_sets_its_own_minimum(self):
		klass = frappe.get_doc({
			"doctype": "FieldMate Outlet Class",
			"class_name": self.uid("CLS"),
			"is_active": 1,
			"min_visit_duration_minutes": 45,
		}).insert(ignore_permissions=True)
		self.track("FieldMate Outlet Class", klass.name)
		self.outlet.outlet_class = klass.name
		self.outlet.save(ignore_permissions=True)

		opened = self.check_in(check_in_time=add_to_date(now_datetime(), minutes=-30))
		self.assertTrue(self.check_out(opened["visit"])["is_short_visit"])

	def test_no_outcome_is_refused(self):
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError) as ctx:
			visit_service.check_out(opened["visit"], {})
		self.assertIn("What happened", str(ctx.exception))

	def test_no_order_without_a_reason_is_refused(self):
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.check_out(opened["visit"], visit_outcome="No Order")
		self.assertIn("reason", str(ctx.exception))

	def test_a_reason_that_needs_a_note_is_refused_without_one(self):
		reason = self.make_reason(requires_note=1)
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.check_out(opened["visit"], visit_outcome="No Order", no_order_reason=reason)
		self.assertIn("note", str(ctx.exception))

	def test_a_reason_with_a_note_is_accepted(self):
		reason = self.make_reason(requires_note=1)
		opened = self.check_in()
		closed = self.check_out(opened["visit"], visit_outcome="No Order",
		                        no_order_reason=reason, remarks="Shutter down all afternoon.")
		self.assertEqual(closed["visit_outcome"], "No Order")

	def test_checking_out_twice_is_harmless(self):
		opened = self.check_in()
		self.check_out(opened["visit"])
		again = self.check_out(opened["visit"])
		self.assertFalse(again["created"])

	def test_check_out_before_check_in_is_refused(self):
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.check_out(opened["visit"],
			               check_out_time=add_to_date(now_datetime(), minutes=-60))
		self.assertIn("before check-in", str(ctx.exception))

	def test_a_visit_cannot_be_submitted_unfinished(self):
		opened = self.check_in()
		doc = frappe.get_doc("FieldMate Visit", opened["visit"])
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.submit()
		self.assertIn("Check out", str(ctx.exception))


# ----------------------------------------------------------------------------- checklists


class ChecklistFixture(VisitFixture):
	def setUp(self):
		super().setUp()
		self.my_templates = set()

	def mine(self, result):
		"""Only the questions that came from templates this test created.

		A live site carries its own active templates and they apply here too. Asserting on the
		whole checklist would make every one of these tests a test of the site's data.
		"""
		checklist = result["checklist"] if isinstance(result, dict) else result
		return [q for q in checklist if q.get("template") in self.my_templates]

	def make_template(self, questions=None, **kwargs):
		data = {
			"doctype": "FieldMate Checklist Template",
			"template_name": self.uid("TPL"),
			"is_active": 1,
			"applies_to": "Every Visit",
			"effective_from": today(),
			"questions": questions or [
				{"question_code": "SHELF", "question": "Is our shelf clean?",
				 "answer_type": "Yes/No", "is_required": 1, "sequence": 1},
				{"question_code": "PRICE", "question": "What is the shelf price?",
				 "answer_type": "Number", "is_required": 0, "sequence": 2},
			],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Checklist Template", doc.name)
		self.my_templates.add(doc.name)
		return doc


class TestChecklistTemplate(ChecklistFixture):
	def test_questions_are_counted(self):
		self.assertEqual(self.make_template().question_count, 2)

	def test_duplicate_codes_are_refused(self):
		"""Answers are matched to questions by code, so two rows sharing one is unanswerable."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_template(questions=[
				{"question_code": "A", "question": "First", "answer_type": "Text", "sequence": 1},
				{"question_code": "A", "question": "Second", "answer_type": "Text", "sequence": 2},
			])
		self.assertIn("both use the code", str(ctx.exception))

	def test_a_choice_question_needs_options(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_template(questions=[
				{"question_code": "C", "question": "Which?", "answer_type": "Single Choice",
				 "sequence": 1},
			])
		self.assertIn("no options", str(ctx.exception))

	def test_a_backwards_dependency_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_template(questions=[
				{"question_code": "CHILD", "question": "Why not?", "answer_type": "Text",
				 "sequence": 1, "depends_on_code": "PARENT", "depends_on_value": "No"},
				{"question_code": "PARENT", "question": "In stock?", "answer_type": "Yes/No",
				 "sequence": 2},
			])
		self.assertIn("comes later", str(ctx.exception))

	def test_a_dependency_on_a_missing_question_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_template(questions=[
				{"question_code": "A", "question": "Why?", "answer_type": "Text",
				 "sequence": 1, "depends_on_code": "GHOST"},
			])
		self.assertIn("not a question in this template", str(ctx.exception))

	def test_rewording_a_question_bumps_the_version(self):
		template = self.make_template()
		self.assertEqual(template.version, 1)
		template.questions[0].question = "Is the shelf clean and faced?"
		template.save(ignore_permissions=True)
		self.assertEqual(template.version, 2)

	def test_renaming_the_template_does_not_bump_the_version(self):
		"""Answers are pinned to a version. Bumping it for a cosmetic edit orphans them."""
		template = self.make_template()
		template.template_name = self.uid("TPL")
		template.save(ignore_permissions=True)
		self.assertEqual(template.version, 1)

	def test_narrowing_the_scope_does_not_bump_the_version(self):
		template = self.make_template()
		template.territory = self.territory
		template.save(ignore_permissions=True)
		self.assertEqual(template.version, 1)


class TestChecklistOnVisit(ChecklistFixture):
	def test_questions_are_snapshotted_onto_the_visit(self):
		self.make_template()
		codes = [q["question_code"] for q in self.mine(self.check_in())]
		self.assertEqual(codes, ["SHELF", "PRICE"])

	def test_the_answer_carries_the_version_it_was_asked_under(self):
		template = self.make_template()
		asked = self.mine(self.check_in())
		self.assertEqual(asked[0]["template_version"], template.version)

	def test_rewording_later_does_not_change_what_an_old_visit_asked(self):
		template = self.make_template()
		result = self.check_in()

		template.questions[0].question = "Completely different question"
		template.save(ignore_permissions=True)

		row = next(r for r in frappe.get_doc("FieldMate Visit", result["visit"]).checklist_answers
		           if r.template == template.name)
		self.assertEqual(row.question, "Is our shelf clean?")
		self.assertEqual(row.template_version, 1)

	def test_a_template_for_another_territory_does_not_apply(self):
		self.make_template(territory=self.make_territory())
		self.assertEqual(self.mine(self.check_in()), [])

	def test_a_template_scoped_to_a_parent_territory_reaches_the_shop(self):
		"""A survey for 'North' must reach a shop in 'North / Delhi', not just one pinned to
		the exact node a planner happened to click."""
		child = self.make_territory(parent=self.territory)
		shop = self.make_outlet(territory=child, approval_status="Approved")
		self.make_template(territory=self.territory)
		self.assertEqual(len(self.mine(self.check_in(outlet=shop.name))), 2)

	def test_the_root_territory_means_everywhere(self):
		"""Frappe fills an empty Territory field from the session default, so a template a
		planner never scoped arrives pinned to the root. It must still apply everywhere."""
		self.make_template(territory="All Territories")
		self.assertEqual(len(self.mine(self.check_in())), 2)

	def test_an_inactive_template_does_not_apply(self):
		self.make_template(is_active=0)
		self.assertEqual(self.mine(self.check_in()), [])

	def test_a_future_template_does_not_apply_yet(self):
		self.make_template(effective_from=add_to_date(today(), days=7))
		self.assertEqual(self.mine(self.check_in()), [])

	def test_a_new_outlet_template_skips_approved_shops(self):
		self.make_template(applies_to="New Outlet Only")
		self.assertEqual(self.mine(self.check_in()), [])

	def test_answers_are_saved_and_replayable(self):
		self.make_template()
		opened = self.check_in()
		visit_service.save_tasks(opened["visit"], {
			"answers": [{"question_code": "SHELF", "answer": "Yes"},
			            {"question_code": "PRICE", "answer_number": 42}],
		})
		again = visit_service.save_tasks(opened["visit"], {
			"answers": [{"question_code": "SHELF", "answer": "No"}],
		})
		by_code = {q["question_code"]: q for q in self.mine(again)}
		self.assertEqual(by_code["SHELF"]["answer"], "No")
		# The untouched row keeps what it had rather than being wiped by a partial save.
		self.assertEqual(by_code["PRICE"]["answer_number"], 42)

	def test_the_renderer_gets_the_options_without_storing_them_on_every_row(self):
		self.make_template(questions=[
			{"question_code": "STOCK", "question": "Stock level?", "answer_type": "Single Choice",
			 "options": "Full\nLow\nOut", "sequence": 1},
		])
		question = self.mine(self.check_in())[0]
		self.assertEqual(question["options"], ["Full", "Low", "Out"])

	def test_a_required_answer_blocks_check_out_at_an_open_shop(self):
		self.make_template()
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.check_out(opened["visit"], answer_required=False)
		self.assertIn("Answer these before you leave", str(ctx.exception))

	def test_a_required_answer_does_not_trap_a_rep_at_a_closed_shop(self):
		"""A rep cannot describe a shelf behind a shutter, and must not be stuck there."""
		self.make_template()
		reason = self.make_reason()
		opened = self.check_in()
		closed = self.check_out(opened["visit"], visit_outcome="Outlet Closed",
		                        no_order_reason=reason)
		self.assertEqual(closed["visit_outcome"], "Outlet Closed")

	def test_zero_is_a_real_answer_not_an_unanswered_question(self):
		"""'Zero facings on the shelf' is the most actionable answer there is. A Float column
		stores an unset value as 0, so answeredness has to be recorded, not inferred."""
		self.make_template(questions=[
			{"question_code": "FACE", "question": "How many facings?",
			 "answer_type": "Number", "is_required": 1, "sequence": 1},
		])
		opened = self.check_in()
		visit_service.save_tasks(opened["visit"],
		                         {"answers": [{"question_code": "FACE", "answer_number": 0}]})
		closed = self.check_out(opened["visit"])
		self.assertTrue(closed["checked_out_at"])
		face = next(q for q in self.mine(closed) if q["question_code"] == "FACE")
		self.assertTrue(face["is_answered"])
		self.assertEqual(face["answer_number"], 0)

	def test_an_untouched_numeric_question_still_blocks_check_out(self):
		self.make_template(questions=[
			{"question_code": "FACE", "question": "How many facings?",
			 "answer_type": "Number", "is_required": 1, "sequence": 1},
		])
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError):
			self.check_out(opened["visit"], answer_required=False)

	def test_answering_lets_the_rep_leave(self):
		self.make_template()
		opened = self.check_in()
		closed = self.check_out(opened["visit"],
		                        answers=[{"question_code": "SHELF", "answer": "Yes"}])
		self.assertTrue(closed["checked_out_at"])

	def test_saving_after_check_out_is_refused(self):
		opened = self.check_in()
		self.check_out(opened["visit"])
		with self.assertRaises(frappe.ValidationError) as ctx:
			visit_service.save_tasks(opened["visit"], {"remarks": "afterthought"})
		self.assertIn("already finished", str(ctx.exception))


# ----------------------------------------------------------------------------- photos


class TestVisitPhotos(VisitFixture):
	PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
	         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

	def test_a_photo_is_stored_as_a_file_not_a_blob_in_the_row(self):
		"""The column holds 140 characters. A base64 image does not fit, and must not try."""
		opened = self.check_in()
		visit_service.add_photo(opened["visit"], {"photo": self.PIXEL, "purpose": "Shelf"})
		row = frappe.get_doc("FieldMate Visit", opened["visit"]).photos[0]
		self.assertTrue(row.photo.startswith("/private/files/") or
		                row.photo.startswith("/files/"))

	def test_a_replayed_photo_is_not_stored_twice(self):
		opened = self.check_in()
		uuid = self.uid("PIC")
		visit_service.add_photo(opened["visit"], {"photo": self.PIXEL, "client_uuid": uuid})
		again = visit_service.add_photo(opened["visit"], {"photo": self.PIXEL,
		                                                 "client_uuid": uuid})
		self.assertTrue(again["duplicate"])
		self.assertEqual(again["photos"], 1)

	def test_a_photoless_call_is_refused(self):
		opened = self.check_in()
		with self.assertRaises(frappe.ValidationError):
			visit_service.add_photo(opened["visit"], {"purpose": "Shelf"})


# ----------------------------------------------------------------------------- ownership


class TestVisitOwnership(VisitFixture):
	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_a_rep_cannot_record_a_visit_in_a_colleagues_name(self):
		"""`if_owner` ties the row to its creator but says nothing about the name on it."""
		colleague = self.make_field_user(territory=self.territory)
		opened = self.check_in()
		frappe.set_user(self.rep.user)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc({
					"doctype": "FieldMate Visit",
					"visit_date": today(),
					"outlet": self.outlet.name,
					"field_user": colleague.name,
					"check_in_time": now_datetime(),
					"client_uuid": self.uid("VIS"),
				}).insert()
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(opened["created"])

	def test_a_rep_may_record_their_own(self):
		frappe.set_user(self.rep.user)
		try:
			doc = frappe.get_doc({
				"doctype": "FieldMate Visit",
				"visit_date": today(),
				"outlet": self.outlet.name,
				"field_user": self.rep.name,
				"check_in_time": now_datetime(),
				"client_uuid": self.uid("VIS"),
			}).insert()
			self.track("FieldMate Visit", doc.name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(doc.name)


# ----------------------------------------------------------------------------- offline push


class TestOfflineVisit(ChecklistFixture):
	"""A whole day captured with no signal, pushed when the rep gets back to town."""

	def push(self, data, client_uuid=None):
		records = [{
			"doctype": "FieldMate Visit",
			"client_uuid": client_uuid or self.uid("VIS"),
			"data": data,
		}]
		return sync_service.push("Administrator", self.device, self.uid("BATCH"), records)

	def offline_visit(self, **overrides):
		self.start_day()
		data = {
			"outlet": self.outlet.name,
			"field_user": self.rep.name,
			"visit_date": today(),
			"check_in_time": add_to_date(now_datetime(), minutes=-30),
			"check_in_latitude": NEAR[0],
			"check_in_longitude": NEAR[1],
			"check_out_time": now_datetime(),
			"visit_outcome": "Order Taken",
			"created_offline": 1,
		}
		data.update(overrides)
		return data

	def result_of(self, pushed):
		return pushed["results"][0]

	def test_a_day_captured_offline_lands_submitted(self):
		"""Every count that matters reads submitted rows. A pushed day that stays in draft is
		a day of work recorded and not counted."""
		row = self.result_of(self.push({**self.offline_visit(), "docstatus": 1}))
		self.assertEqual(row["status"], "created")
		self.track("FieldMate Visit", row["name"])
		self.assertEqual(frappe.db.get_value("FieldMate Visit", row["name"], "docstatus"), 1)

	def test_an_unfinished_visit_pushed_mid_shop_stays_a_draft(self):
		data = self.offline_visit()
		data.pop("check_out_time")
		data.pop("visit_outcome")
		row = self.result_of(self.push(data))
		self.track("FieldMate Visit", row["name"])
		self.assertEqual(frappe.db.get_value("FieldMate Visit", row["name"], "docstatus"), 0)

	def test_a_replayed_push_does_not_create_a_second_visit(self):
		uuid = self.uid("VIS")
		first = self.result_of(self.push({**self.offline_visit(), "docstatus": 1}, uuid))
		self.track("FieldMate Visit", first["name"])
		second = self.result_of(self.push({**self.offline_visit(), "docstatus": 1}, uuid))
		self.assertEqual(second["status"], "duplicate")
		self.assertEqual(second["name"], first["name"])

	def test_a_replayed_batch_still_reports_the_server_names(self):
		"""The normal end of a bad connection: the server finished and the reply never landed.

		If the replay answered with only a summary, the phone would never learn the visit's
		name, and every photo queued against it would be orphaned for good.
		"""
		batch_uuid = self.uid("BATCH")
		records = [{
			"doctype": "FieldMate Visit",
			"client_uuid": self.uid("VIS"),
			"data": {**self.offline_visit(), "docstatus": 1},
		}]
		first = sync_service.push("Administrator", self.device, batch_uuid, records)
		self.track("FieldMate Visit", first["results"][0]["name"])

		replay = sync_service.push("Administrator", self.device, batch_uuid, records)
		self.assertTrue(replay["replayed"])
		self.assertEqual(replay["results"][0]["status"], "duplicate")
		self.assertEqual(replay["results"][0]["name"], first["results"][0]["name"])

	def test_a_photo_attaches_after_the_visit_is_already_submitted(self):
		"""Records sync first and pictures follow, so this is the normal order, not the odd one."""
		row = self.result_of(self.push({**self.offline_visit(), "docstatus": 1}))
		self.track("FieldMate Visit", row["name"])

		visit_service.add_photo(row["name"], {
			"photo": TestVisitPhotos.PIXEL, "purpose": "Shelf", "client_uuid": self.uid("PIC"),
		})
		self.assertEqual(len(frappe.get_doc("FieldMate Visit", row["name"]).photos), 1)

	def test_the_device_cannot_push_its_own_evidence(self):
		"""Coverage is what managers act on, so none of it may be device-authored."""
		row = self.result_of(self.push({
			**self.offline_visit(),
			"docstatus": 1,
			"distance_from_outlet_m": 0,
			"is_geo_fence_breach": 0,
			"is_planned": 1,
			"duration_minutes": 90,
			"is_short_visit": 0,
		}))
		self.track("FieldMate Visit", row["name"])

		doc = frappe.get_doc("FieldMate Visit", row["name"])
		self.assertGreater(doc.distance_from_outlet_m, 0)   # measured from the shop's pin
		self.assertFalse(doc.is_planned)                    # no beat planned today
		self.assertEqual(doc.duration_minutes, 30)          # from the two timestamps

	def test_question_wording_is_taken_from_the_template_not_the_phone(self):
		"""A stale or edited cache must not be able to record a question that was never asked."""
		self.make_template()
		row = self.result_of(self.push({
			**self.offline_visit(),
			"docstatus": 1,
			"checklist_answers": [{
				"question_code": "SHELF",
				"question": "Did you hand over the bribe?",
				"answer": "Yes",
				"is_answered": 1,
				"is_required": 0,
				"template_version": 99,
			}],
		}))
		self.track("FieldMate Visit", row["name"])

		answer = frappe.get_doc("FieldMate Visit", row["name"]).checklist_answers[0]
		self.assertEqual(answer.question, "Is our shelf clean?")
		self.assertEqual(answer.template_version, 1)
		self.assertTrue(answer.is_required)
		self.assertEqual(answer.answer, "Yes")          # the rep's answer is kept as given

	def test_an_answer_to_a_retired_question_is_kept_but_not_claimed(self):
		row = self.result_of(self.push({
			**self.offline_visit(),
			"docstatus": 1,
			"checklist_answers": [{
				"question_code": "GONE", "question": "An older survey",
				"answer": "Yes", "is_answered": 1, "is_required": 1,
			}],
		}))
		self.track("FieldMate Visit", row["name"])

		answer = frappe.get_doc("FieldMate Visit", row["name"]).checklist_answers[0]
		self.assertEqual(answer.answer, "Yes")
		self.assertIsNone(answer.template)
		self.assertFalse(answer.is_required)


class TestChecklistForms(ChecklistFixture):
	def test_forms_carry_their_questions(self):
		"""A template pulled as a flat row is an empty form, and an empty form is unusable
		in a market with no signal."""
		from fieldmate.api import visit as visit_api

		self.make_template()
		payload = visit_api.forms()["data"]
		mine = [t for t in payload["templates"] if t["questions"]]
		self.assertTrue(mine)
		question = mine[0]["questions"][0]
		self.assertIn("answer_type", question)
		self.assertIn("options", question)

	def test_choice_options_arrive_as_a_list(self):
		from fieldmate.api import visit as visit_api

		template = self.make_template(questions=[
			{"question_code": "STOCK", "question": "Stock level?",
			 "answer_type": "Single Choice", "options": "Full\nLow\nOut", "sequence": 1},
		])
		payload = visit_api.forms()["data"]
		found = next(t for t in payload["templates"] if t["name"] == template.name)
		self.assertEqual(found["questions"][0]["options"], ["Full", "Low", "Out"])


# ----------------------------------------------------------------------------- merchandising


class TestMerchandisingAudit(VisitFixture):
	def make_item(self, **kwargs):
		data = {
			"doctype": "Item",
			"item_code": self.uid("ITEM"),
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Nos",
			"is_stock_item": 0,
		}
		data.update(kwargs)
		doc = frappe.get_doc(self.with_hsn(data)).insert(ignore_permissions=True)
		self.track("Item", doc.name)
		return doc.name

	def make_audit(self, lines=None, competitors=None, **kwargs):
		data = {
			"doctype": "FieldMate Merchandising Audit",
			"outlet": self.outlet.name,
			"field_user": self.rep.name,
			"audit_date": today(),
			"lines": lines or [],
			"competitors": competitors or [],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Merchandising Audit", doc.name)
		return doc

	def test_numeric_distribution_is_counted_from_the_rows(self):
		a, b = self.make_item(), self.make_item()
		audit = self.make_audit(lines=[
			{"item_code": a, "is_available": 1, "facings": 4},
			{"item_code": b, "is_available": 0, "facings": 0},
		])
		self.assertEqual(audit.line_count, 2)
		self.assertEqual(audit.available_count, 1)

	def test_shelf_share_is_ours_over_the_whole_shelf(self):
		item = self.make_item()
		audit = self.make_audit(
			lines=[{"item_code": item, "is_available": 1, "facings": 3}],
			competitors=[{"competitor": "Rival", "product": "Their pack", "facings": 7}],
		)
		self.assertEqual(audit.our_facings, 3)
		self.assertEqual(audit.total_facings, 10)
		self.assertEqual(audit.shelf_share_pct, 30.0)

	def test_a_reported_shelf_total_below_what_was_counted_is_corrected(self):
		"""Our own facings cannot exceed the shelf they sit on."""
		item = self.make_item()
		audit = self.make_audit(
			lines=[{"item_code": item, "is_available": 1, "facings": 12}],
			total_facings=5,
		)
		self.assertEqual(audit.total_facings, 12)
		self.assertEqual(audit.shelf_share_pct, 100.0)

	def test_a_larger_reported_total_is_respected(self):
		"""Counting a crowded shelf whole is often faster than listing every rival."""
		item = self.make_item()
		audit = self.make_audit(
			lines=[{"item_code": item, "is_available": 1, "facings": 5}],
			total_facings=50,
		)
		self.assertEqual(audit.total_facings, 50)
		self.assertEqual(audit.shelf_share_pct, 10.0)

	def test_an_empty_shelf_does_not_divide_by_zero(self):
		self.assertEqual(self.make_audit().shelf_share_pct, 0.0)

	def test_a_must_sell_item_never_checked_counts_as_missing(self):
		"""Otherwise a rep raises compliance simply by not looking."""
		stocked, ignored = self.make_item(), self.make_item()
		must_sell = frappe.get_doc({
			"doctype": "FieldMate Must Sell List",
			"list_name": self.uid("MSL"),
			"is_active": 1,
			"territory": self.territory,
			"items": [{"item_code": stocked, "weightage": 1},
			          {"item_code": ignored, "weightage": 1}],
		}).insert(ignore_permissions=True)
		self.track("FieldMate Must Sell List", must_sell.name)

		audit = self.make_audit(lines=[{"item_code": stocked, "is_available": 1, "facings": 2}])
		self.assertEqual(audit.must_sell_total, 2)
		self.assertEqual(audit.must_sell_available, 1)
		self.assertEqual(audit.must_sell_compliance_pct, 50.0)

	def test_submitting_links_the_audit_back_to_its_visit(self):
		opened = self.check_in()
		audit = self.make_audit(visit=opened["visit"])
		audit.submit()
		self.assertEqual(
			frappe.db.get_value("FieldMate Visit", opened["visit"], "merchandising_audit"),
			audit.name,
		)


class TestAVisitEndsByCheckingOut(VisitFixture):
	"""A second check-in used to close the first visit, always and silently.

	One tap from the shop list ended the visit the rep was standing in, stamped it "No Order" and
	short, and told nobody - so a rep could walk a row of shops leaving behind empty visits that
	still counted towards coverage. Checking out is how a visit ends.

	The refusal is for a check-in happening now. A visit created offline already happened - the
	rep was in that shop - and rejecting it when the queue lands would delete real work.
	"""

	def second_shop(self):
		return self.make_outlet(
			territory=self.territory,
			latitude=DELHI[0], longitude=DELHI[1],
			approval_status="Approved",
		)

	def test_it_is_refused_and_names_the_shop_they_are_in(self):
		self.check_in()
		other = self.second_shop()
		with self.assertRaises(visit_service.OpenVisitError) as caught:
			self.check_in(outlet=other.name, client_uuid=self.uid("VIS2"))
		self.assertIn(self.outlet.outlet_name, str(caught.exception),
		              "the shop they have to go back to, by name")

	def test_the_refusal_leaves_the_open_visit_alone(self):
		"""The whole point. A refusal that had already closed the visit would be the bug with a
		message attached."""
		first = self.check_in()
		other = self.second_shop()
		with self.assertRaises(visit_service.OpenVisitError):
			self.check_in(outlet=other.name, client_uuid=self.uid("VIS2"))

		doc = frappe.get_doc("FieldMate Visit", first["visit"])
		self.assertFalse(doc.check_out_time, "still open, still theirs to finish properly")
		self.assertEqual(visit_service.open_visit(self.rep.name)["visit"], first["visit"])

	def test_checking_out_first_lets_the_next_one_through(self):
		first = self.check_in()
		self.check_out(first["visit"])
		other = self.second_shop()
		second = self.check_in(outlet=other.name, client_uuid=self.uid("VIS2"))
		self.assertEqual(second["outlet"], other.name)

	def test_a_rep_who_has_walked_away_can_say_so(self):
		"""The deliberate override, sent only after the screen has said what it closes. Without
		it a rep whose shop is behind them is stuck outside the next one."""
		first = self.check_in()
		other = self.second_shop()
		second = self.check_in(outlet=other.name, client_uuid=self.uid("VIS2"),
		                       close_open_visit=1)
		self.assertEqual(second["outlet"], other.name)

		closed = frappe.get_doc("FieldMate Visit", first["visit"])
		self.assertTrue(closed.check_out_time)
		self.assertTrue(closed.is_short_visit)

	def test_a_visit_taken_offline_is_recorded_not_rejected(self):
		"""It already happened. The rep stood in that shop, the phone had no signal, and the
		queue is landing now - refusing it would throw away the visit."""
		first = self.check_in()
		other = self.second_shop()
		second = self.check_in(outlet=other.name, client_uuid=self.uid("VIS2"),
		                       created_offline=1)
		self.assertEqual(second["outlet"], other.name)
		self.assertTrue(
			frappe.db.get_value("FieldMate Visit", first["visit"], "check_out_time"))

	def test_checking_in_again_at_the_same_shop_is_not_refused(self):
		"""The guard is about walking off mid-visit. A rep re-opening the app, or a push being
		retried, is at the shop they are already in - refusing that would lock a rep out of the
		shop they are standing in, which is worse than what this fixes."""
		self.check_in()
		again = self.check_in(client_uuid=self.uid("VIS"))
		self.assertEqual(again["outlet"], self.outlet.name)

	def test_a_visit_closed_this_way_is_not_counted_as_a_sale(self):
		"""`visit_outcome` is a Select with options and no default, so it holds its first option
		- "Order Taken" - from the moment the visit is inserted. The old `or "No Order"` could
		therefore never fire, and `day_counts` counts that exact string as a productive visit:
		a rep walking a row of shops inflated their own productivity figure.

		Found by this test, not in the field."""
		reason = self.make_reason()
		first = self.check_in()
		other = self.second_shop()
		self.check_in(outlet=other.name, client_uuid=self.uid("VIS2"), close_open_visit=1)

		closed = frappe.get_doc("FieldMate Visit", first["visit"])
		self.assertEqual(closed.visit_outcome, "No Order", "no order was taken in it")
		self.assertEqual(closed.no_order_reason, reason,
		                 "and a reason, so the figure can be explained")


class TestAForgottenDayClosesItsVisit(VisitFixture):
	"""A day auto-closed used to leave the visit on it open forever - and an open visit from
	yesterday blocks today's first check-in, which is the bug the rep actually meets."""

	def test_the_open_visit_goes_with_the_day(self):
		from fieldmate.services import day as day_service

		first = self.check_in()
		day = day_service.current(self.rep.name)
		frappe.db.set_value("FieldMate Day Start", day["day_start"], {
			"day_date": add_to_date(today(), days=-1),
			"start_time": add_to_date(now_datetime(), days=-1),
		}, update_modified=False)
		# Back-dated properly: this is a visit the rep really walked away from yesterday, so
		# the check-in time moves with the date. A visit checked in *today* is a live one and
		# is deliberately left alone - see TestALiveVisitSurvivesTheDayClosing.
		frappe.db.set_value("FieldMate Visit", first["visit"], {
			"visit_date": add_to_date(today(), days=-1),
			"check_in_time": add_to_date(now_datetime(), days=-1),
		}, update_modified=False)
		frappe.clear_document_cache("FieldMate Day Start", day["day_start"])
		frappe.clear_document_cache("FieldMate Visit", first["visit"])

		self.assertIsNone(day_service.current(self.rep.name))
		self.assertTrue(
			frappe.db.get_value("FieldMate Visit", first["visit"], "check_out_time"),
			"closed with the day, so today's first check-in is not blocked by it")
		self.assertIsNone(visit_service.open_visit(self.rep.name))


class TestALiveVisitSurvivesTheDayClosing(VisitFixture):
	"""Found in the field, by the person it happened to.

	A rep was standing in a shop with a visit open. The day they were working under was dated
	yesterday - which is the bug `day.current` now fixes - so the first call the app made closed
	that day, and the day closing took the visit with it. The rep could not check out of the shop
	they were in, and the app went on showing a visit the server had already closed.

	So the tidy-up stops at the visit the rep is in. `check_in_time` decides that, not
	`visit_date`: `visit_date` is the field the original bug corrupted.
	"""

	def stale_day(self):
		from fieldmate.services import day as day_service
		day = day_service.current(self.rep.name)
		frappe.db.set_value("FieldMate Day Start", day["day_start"], {
			"day_date": add_to_date(today(), days=-1),
			"start_time": add_to_date(now_datetime(), days=-1),
		}, update_modified=False)
		frappe.clear_document_cache("FieldMate Day Start", day["day_start"])
		return day["day_start"]

	def test_a_visit_checked_in_today_is_not_closed_with_yesterdays_day(self):
		from fieldmate.services import day as day_service

		first = self.check_in()
		self.stale_day()
		# The corruption as it actually appeared: checked in today, filed under yesterday.
		frappe.db.set_value("FieldMate Visit", first["visit"], "visit_date",
		                    add_to_date(today(), days=-1), update_modified=False)
		frappe.clear_document_cache("FieldMate Visit", first["visit"])

		self.assertIsNone(day_service.current(self.rep.name), "the day is over")
		self.assertFalse(
			frappe.db.get_value("FieldMate Visit", first["visit"], "check_out_time"),
			"but the rep is still in the shop")
		self.assertEqual(visit_service.open_visit(self.rep.name)["visit"], first["visit"])

	def test_the_day_that_opens_next_adopts_it(self):
		"""Otherwise it dangles off a closed day carrying the wrong date, and every count that
		reads `visit_date` misses it."""
		from fieldmate.services import day as day_service

		first = self.check_in()
		stale = self.stale_day()
		frappe.db.set_value("FieldMate Visit", first["visit"], "visit_date",
		                    add_to_date(today(), days=-1), update_modified=False)
		frappe.clear_document_cache("FieldMate Visit", first["visit"])
		day_service.current(self.rep.name)

		fresh = self.start_day()
		self.assertNotEqual(fresh["day_start"], stale)
		row = frappe.db.get_value("FieldMate Visit", first["visit"],
		                          ["day_start", "visit_date"], as_dict=True)
		self.assertEqual(row.day_start, fresh["day_start"])
		self.assertEqual(str(row.visit_date), str(today()))

	def test_the_rep_can_then_check_out_of_the_shop_they_are_in(self):
		"""The whole point of the two tests above, said as the rep would say it."""
		from fieldmate.services import day as day_service

		first = self.check_in()
		self.stale_day()
		day_service.current(self.rep.name)
		self.start_day()

		closed = self.check_out(first["visit"])
		self.assertTrue(closed["created"])
		self.assertTrue(
			frappe.db.get_value("FieldMate Visit", first["visit"], "check_out_time"))


class TestTheDaysHistory(VisitFixture):
	"""What `visit.history` answers, which is now read twice over.

	It draws the rep's home screen, and since the phone began reconciling against it, it also
	decides which rows survive on the handset. Both readings want the same thing: **a cancelled
	visit did not happen.** Somebody in the office took it back, and a rep's day showing it as a
	shop they covered is simply false.

	Before this, nothing filtered `docstatus`. A day cancelled in Desk left every visit sitting on
	the phone - the route read as done, the progress bar was full, and "next shop" pointed past
	shops nobody had been to. It was reported from the field in exactly those words.
	"""

	def closed_visit(self):
		opened = self.check_in()
		self.check_out(opened["visit"])
		return opened["visit"]

	def names_in_history(self):
		return [row["visit"] for row in visit_service.history(self.rep.name, today())]

	def test_a_visit_that_happened_is_in_it(self):
		self.assertIn(self.closed_visit(), self.names_in_history())

	def test_a_cancelled_visit_is_not(self):
		name = self.closed_visit()
		doc = frappe.get_doc("FieldMate Visit", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
		self.assertNotIn(name, self.names_in_history())

	def test_cancelling_one_leaves_the_others_alone(self):
		"""The phone deletes its local row for anything missing from this answer, so an answer
		that lost a visit it should have kept would wipe a rep's day."""
		kept = self.closed_visit()
		gone = self.closed_visit()
		doc = frappe.get_doc("FieldMate Visit", gone)
		doc.flags.ignore_permissions = True
		doc.cancel()

		names = self.names_in_history()
		self.assertIn(kept, names)
		self.assertNotIn(gone, names)

	def test_it_answers_under_the_key_the_phone_reads(self):
		"""`name as visit`. The phone matches on that key; reading `name` instead would match
		nothing, every synced row would look cancelled, and the reconcile would delete the lot."""
		self.closed_visit()
		rows = visit_service.history(self.rep.name, today())
		self.assertTrue(rows)
		self.assertIn("visit", rows[0])
