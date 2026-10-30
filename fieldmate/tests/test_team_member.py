"""One rep, from their manager's phone: the profile, their orders, and their phone's sync trouble.

The last three things Area and Regional Managers did in Desk. Each keeps exactly the right Desk
gave - read off the DocType permission, not restated - so most of this file is who may and who
may not:

  edit the profile   Regional Manager yes, Area Manager no
  cancel an order    Area Manager yes, Regional Manager no
  close a sync jam   Area Manager yes, Regional Manager no
"""

import frappe

from fieldmate.services import sync as sync_service
from fieldmate.services import team as team_service
from fieldmate.tests.test_order import OrderFixture
from fieldmate.tests.test_team import TeamLine


class MemberFixture(TeamLine, OrderFixture):
	def setUp(self):
		super().setUp()
		self.build_line()

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("FieldMate Sync Conflict", filters={"user": self.rep.user},
		                           pluck="name"):
			frappe.delete_doc("FieldMate Sync Conflict", name, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def page(self, user):
		return self.as_user(user, team_service.member, self.rep.name)

	def jam(self):
		return sync_service.record_conflict(
			None, None, self.rep.user, "FieldMate Order", self.uid("UUID"), "Validation Failed",
			{"outlet": self.outlet.name}, "Item ABC is not on the price list")


class TestWhatTheManagerSees(MemberFixture):
	def test_an_area_manager_sees_orders_they_may_cancel_and_a_profile_they_may_not_edit(self):
		order = self.book()["name"]
		page = self.page(self.am.user)
		self.assertFalse(page["can_edit"])
		self.assertIsNone(page["options"])
		self.assertTrue(next(o for o in page["orders"] if o["name"] == order)["can_cancel"])

	def test_a_regional_manager_the_other_way_round(self):
		order = self.book()["name"]
		page = self.page(self.rm.user)
		self.assertTrue(page["can_edit"])
		self.assertFalse(next(o for o in page["orders"] if o["name"] == order)["can_cancel"])

	def test_sync_trouble_is_shown_to_the_area_manager_only(self):
		name = self.jam()
		self.assertIn(name, [c["name"] for c in self.page(self.am.user)["conflicts"]])
		self.assertEqual(self.page(self.rm.user)["conflicts"], [])

	def test_another_teams_manager_sees_nothing(self):
		with self.assertRaises(frappe.PermissionError):
			self.page(self.other_am.user)


class TestCancellingFromThePhone(MemberFixture):
	def test_the_area_manager_cancels_and_the_scheme_budget_comes_back(self):
		"""The same withdrawal a rep's own cancel runs - not a second, thinner one."""
		order = self.book(qty=20)["name"]
		self.as_user(self.am.user, team_service.cancel_order, order, "Shop shut for a month")
		self.assertEqual(frappe.db.get_value("FieldMate Order", order, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("FieldMate Order", order, "order_status"), "Cancelled")
		ledger = frappe.get_all("FieldMate Scheme Ledger", filters={"order": order}, pluck="status")
		self.assertTrue(all(s == "Reversed" for s in ledger), ledger)
		self.assertIn("Shop shut for a month",
		              frappe.db.get_value("FieldMate Order", order, "remarks"))

	def test_not_without_a_reason(self):
		order = self.book()["name"]
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.am.user, team_service.cancel_order, order, "  ")

	def test_not_by_the_regional_manager(self):
		order = self.book()["name"]
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rm.user, team_service.cancel_order, order, "Not mine to cancel")

	def test_not_by_another_team(self):
		order = self.book()["name"]
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other_am.user, team_service.cancel_order, order, "Wrong team")


class TestEditingTheProfile(MemberFixture):
	def test_the_regional_manager_changes_who_the_rep_reports_to(self):
		page = self.as_user(self.rm.user, team_service.update_member, self.rep.name,
		                    {"reports_to": self.rm.name, "daily_target_calls": 30})
		self.assertEqual(page["profile"]["reports_to"], self.rm.name)
		self.assertEqual(page["profile"]["daily_target_calls"], 30)

	def test_the_area_manager_may_not(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.am.user, team_service.update_member, self.rep.name,
			             {"daily_target_calls": 30})

	def test_a_rep_is_never_offered_as_their_own_manager_or_below(self):
		options = self.as_user(self.rm.user, team_service.member, self.am.name)["options"]
		offered = [m["name"] for m in options["reports_to"]]
		self.assertIn(self.rm.name, offered)
		self.assertNotIn(self.am.name, offered)
		self.assertNotIn(self.rep.name, offered)

	def test_and_a_loop_is_refused_if_sent_anyway(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rm.user, team_service.update_member, self.am.name,
			             {"reports_to": self.rep.name})

	def test_a_territory_outside_the_managers_permission_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rm.user, team_service.update_member, self.rep.name,
			             {"territory": self.make_territory()})


class TestClosingASyncJam(MemberFixture):
	def test_left_as_it_is_and_the_original_reason_is_kept(self):
		name = self.jam()
		result = self.as_user(self.am.user, team_service.resolve_conflict, name, "Keep Server",
		                      "Rep re-booked it by hand")
		self.assertEqual(result["status"], "Resolved")
		notes = frappe.db.get_value("FieldMate Sync Conflict", name, "resolution_notes")
		self.assertIn("not on the price list", notes)
		self.assertIn("re-booked it by hand", notes)

	def test_discarded(self):
		name = self.jam()
		result = self.as_user(self.am.user, team_service.resolve_conflict, name, "Discarded")
		self.assertEqual(result["status"], "Discarded")

	def test_keep_client_is_not_offered_because_nothing_would_be_applied(self):
		name = self.jam()
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.am.user, team_service.resolve_conflict, name, "Keep Client")

	def test_not_by_the_regional_manager(self):
		name = self.jam()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.rm.user, team_service.resolve_conflict, name, "Discarded")

	def test_not_by_another_team(self):
		name = self.jam()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other_am.user, team_service.resolve_conflict, name, "Discarded")
