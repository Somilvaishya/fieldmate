"""A manager's phone: who is in the team, what they see of it, and what they may decide.

Area and Regional Managers lost the Desk and work from the app, so the line that used to be
drawn for them by Desk list filters is now drawn here, by the reporting line. Most of this file
is that line: the board shows your team and nobody else's, and a decision about somebody outside
it is refused - including the expense approval, which was open to every manager in the company.
"""

import frappe
from frappe.utils import today

from fieldmate.services import expense as expense_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import team as team_service
from fieldmate.tests.test_expense import ExpenseFixture
from fieldmate.tests.test_visit import FAR, VisitFixture


class TeamLine:
	"""Two area managers under one regional manager, the fixture rep under the first of them."""

	def build_line(self):
		self.rm = self.manager_named("FieldMate Regional Manager", "Regional Manager")
		self.am = self.manager_named("FieldMate Area Manager", "Area Manager", reports_to=self.rm)
		self.other_am = self.manager_named("FieldMate Area Manager", "Area Manager")
		self.rep.db_set("reports_to", self.am.name)

	def manager_named(self, role, designation, reports_to=None):
		return self.make_field_user(
			user=self.make_user(role=role), designation=designation,
			territory=self.rep.territory, reports_to=reports_to.name if reports_to else None)

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")


# ------------------------------------------------------------------------------- the line


class TestWhoIsInTheTeam(TeamLine, VisitFixture):
	def setUp(self):
		super().setUp()
		self.build_line()

	def test_an_area_manager_has_their_rep(self):
		self.assertEqual(field_user_service.team_of(self.am.name), [self.rep.name])

	def test_a_regional_manager_has_everybody_below_at_any_depth(self):
		team = field_user_service.team_of(self.rm.name)
		self.assertIn(self.am.name, team)
		self.assertIn(self.rep.name, team)

	def test_a_manager_nobody_reports_to_has_nobody_not_everybody(self):
		"""An empty team must read as empty. Read as 'no filter' it is the whole company."""
		self.assertEqual(field_user_service.team_scope(self.other_am.user), [])

	def test_a_sales_head_answers_for_the_whole_company(self):
		head = self.make_user(role="FieldMate Sales Head")
		self.assertIsNone(field_user_service.team_scope(head))

	def test_a_decision_outside_the_line_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			field_user_service.assert_in_team(self.rep.name, self.other_am.user)
		field_user_service.assert_in_team(self.rep.name, self.am.user)


# ------------------------------------------------------------------------------ the board


class TestTheBoard(TeamLine, VisitFixture):
	def setUp(self):
		super().setUp()
		self.build_line()

	def board(self, user):
		return self.as_user(user, team_service.today)

	def row(self, board):
		return next(m for m in board["members"] if m["field_user"] == self.rep.name)

	def test_the_rep_is_on_their_managers_board(self):
		self.assertIn(self.rep.name, [m["field_user"] for m in self.board(self.am.user)["members"]])

	def test_the_rep_is_not_on_another_managers_board(self):
		self.assertEqual(self.board(self.other_am.user)["members"], [])

	def test_a_rep_who_has_not_started_says_so(self):
		row = self.row(self.board(self.am.user))
		self.assertEqual(row["day_status"], "Not Started")
		self.assertEqual(row["visits"], 0)

	def test_a_started_day_and_a_visit_show_up_live(self):
		"""Live, not last night's snapshot - the board is for ten o'clock this morning."""
		self.check_in()
		board = self.board(self.am.user)
		row = self.row(board)
		self.assertEqual(row["day_status"], "Working")
		self.assertEqual(row["visits"], 1)
		self.assertIsNotNone(row["started_at"])
		self.assertEqual(board["totals"]["started"], 1)

	def test_nobody_out_yet_is_listed_first(self):
		self.check_in()
		idle = self.make_field_user(territory=self.rep.territory, reports_to=self.am.name)
		members = self.board(self.am.user)["members"]
		self.assertEqual(members[0]["field_user"], idle.name)


class TestTheManagersOwnDay(TeamLine, VisitFixture):
	"""An Area Manager in the market starts and ends a day like a rep: attendance, an HR
	check-in and the trail their travel is paid on. Signed in as the manager, with only the
	manager's own role - the Day permission row gives them no create, so this is the proof the
	service does not lean on it."""

	def setUp(self):
		super().setUp()
		self.build_line()

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("FieldMate Day", filters={"field_user": self.am.name},
		                           pluck="name"):
			self._drop("FieldMate Day", name)
		frappe.db.commit()
		super().tearDown()

	def test_a_manager_starts_and_ends_their_own_day(self):
		from fieldmate.services import day as day_service
		from fieldmate.tests.test_day import DELHI

		where = {"latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 8,
		         "selfie": "/files/test.jpg"}
		started = self.as_user(self.am.user, day_service.start, self.am.name, where)
		self.assertTrue(started["created"])
		self.assertEqual(frappe.db.get_value("FieldMate Day", started["day"], "field_user"),
		                 self.am.name)

		ended = self.as_user(self.am.user, day_service.end, self.am.name, where)
		self.assertEqual(frappe.db.get_value("FieldMate Day", started["day"], "status"), "Closed")
		self.assertTrue(ended)

	def test_the_manager_is_not_counted_among_their_own_team(self):
		"""Their day is theirs; the board is the people below them."""
		names = [m["field_user"] for m in self.as_user(self.am.user, team_service.today)["members"]]
		self.assertNotIn(self.am.name, names)


# ------------------------------------------------------------------------------ the inbox


class TestTheInbox(TeamLine, VisitFixture):
	def setUp(self):
		super().setUp()
		self.build_line()

	def inbox(self, user):
		return self.as_user(user, team_service.inbox)

	def fence_exception(self):
		doc = frappe.get_doc({
			"doctype": "FieldMate Geo Fence Exception",
			"outlet": self.outlet.name, "field_user": self.rep.name,
			"exception_date": today(), "status": "Pending", "distance_m": 450,
			"reason": "Shop moved across the road", "latitude": FAR[0], "longitude": FAR[1],
		}).insert(ignore_permissions=True)
		self.track("FieldMate Geo Fence Exception", doc.name)
		return doc.name

	def test_a_shop_the_rep_onboarded_waits_for_their_manager(self):
		shop = self.make_outlet(territory=self.rep.territory, created_by_rep=self.rep.name)
		self.assertIn(shop.name, [r["name"] for r in self.inbox(self.am.user)["outlets"]])

	def test_and_not_for_somebody_elses(self):
		self.make_outlet(territory=self.rep.territory, created_by_rep=self.rep.name)
		self.assertEqual(self.inbox(self.other_am.user)["total"], 0)

	def test_a_geo_fence_exception_is_in_the_inbox_with_names(self):
		name = self.fence_exception()
		box = self.inbox(self.am.user)
		row = next(r for r in box["geo_fence"] if r["name"] == name)
		self.assertEqual(row["outlet_name"], self.outlet.outlet_name)
		self.assertEqual(box["counts"]["geo_fence"], 1)

	def test_the_manager_can_excuse_it_from_the_phone(self):
		name = self.fence_exception()
		result = self.as_user(self.am.user, team_service.decide_geo_fence, name, "Approved")
		self.assertEqual(result["status"], "Approved")
		self.assertEqual(frappe.db.get_value("FieldMate Geo Fence Exception", name, "docstatus"), 1)

	def test_another_manager_cannot(self):
		name = self.fence_exception()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other_am.user, team_service.decide_geo_fence, name, "Approved")

	def test_the_rep_cannot_excuse_their_own(self):
		name = self.fence_exception()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rep.user, team_service.decide_geo_fence, name, "Approved")

	def test_a_refusal_needs_a_reason(self):
		name = self.fence_exception()
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.am.user, team_service.decide_geo_fence, name, "Rejected")


# --------------------------------------------------------------------------- the expenses


class TestAnExpenseIsDecidedInsideTheLine(TeamLine, ExpenseFixture):
	"""The hole this file was written around. Any manager could pay any rep's mileage."""

	def setUp(self):
		super().setUp()
		self.build_line()
		self.lay_a_trail(km=100)
		self.claim = self.file_with_bill(claimed_distance_km=300)["name"]
		self.as_rep(expense_service.submit_claim, self.claim, self.rep.name)

	def test_their_own_manager_may_approve(self):
		result = self.as_user(self.am.user, expense_service.approve, self.claim, "Approved",
		                      approved_amount=100, settle=False)
		self.assertEqual(result["claim_status"], "Approved")

	def test_a_manager_two_steps_up_may_too(self):
		result = self.as_user(self.rm.user, expense_service.approve, self.claim, "Approved",
		                      approved_amount=100, settle=False)
		self.assertEqual(result["claim_status"], "Approved")

	def test_another_teams_manager_may_not(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other_am.user, expense_service.approve, self.claim, "Approved",
			             approved_amount=100, settle=False)

	def test_the_pending_list_is_the_teams(self):
		mine, _ = self.as_user(self.am.user, expense_service.pending_for_manager_page)
		theirs, _ = self.as_user(self.other_am.user, expense_service.pending_for_manager_page)
		self.assertIn(self.claim, [r["name"] for r in mine])
		self.assertNotIn(self.claim, [r["name"] for r in theirs])
