"""The FieldMate workspaces draw every widget they name, and the app sits where a Frappe app sits.

For as long as the page existed, none of its charts or number cards rendered. Frappe's workspace
finds a block's widget by the child row's *label* (frappe/public/js/frappe/views/workspace/blocks/
block.js, `make`), and every chart and card block named the chart instead - so each lookup came
back empty and the block was dropped without a word. The page showed a gap where seven widgets
should have been, while the server was sending all seven with data in them.

Nothing on the server fails when this goes wrong, which is why it is pinned here - for the parent
workspace and for each area below it in the sidebar.
"""

import json
import os

import frappe

from fieldmate.permissions import check_app_permission
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_field_user import FieldUserFixture

AREAS = ("Field Operations", "Orders and Stock", "Money", "Targets and Incentives", "Seasons",
         "FieldMate Setup")


def workspaces():
	return [frappe.get_doc("Workspace", name) for name in ("FieldMate", *AREAS)]


def blocks(ws, kind, key):
	return [b["data"][key] for b in json.loads(ws.content) if b["type"] == kind]


class TestTheSidebar(FieldMateTestCase):
	def test_every_area_sits_under_fieldmate(self):
		for name in AREAS:
			ws = frappe.get_doc("Workspace", name)
			self.assertEqual((ws.parent_page, ws.module, ws.public), ("FieldMate", "FieldMate", 1), name)
		self.assertEqual(frappe.db.get_value("Workspace", "FieldMate", "parent_page") or "", "")

	def test_every_doctype_in_the_module_is_reachable_from_some_area(self):
		"""A DocType with no link is one a manager only finds by typing its name in the search bar.

		This is how Attendance Summary, Location Trail, Share Link and Order Ingest Log were found:
		on no page at all.
		"""
		linked = {r.link_to for ws in workspaces() for r in ws.links if r.link_type == "DocType"}
		everything = set(frappe.get_all("DocType", {"module": "FieldMate", "istable": 0},
		                                pluck="name"))
		self.assertEqual(everything - linked, set())


class TestEveryBlockFindsItsWidget(FieldMateTestCase):
	def test_every_chart_block_names_a_chart_label(self):
		for ws in workspaces():
			labels = {r.label for r in ws.charts}
			self.assertEqual(set(blocks(ws, "chart", "chart_name")) - labels, set(), ws.name)

	def test_every_number_card_block_names_a_card_label(self):
		for ws in workspaces():
			labels = {r.label for r in ws.number_cards}
			self.assertEqual(set(blocks(ws, "number_card", "number_card_name")) - labels, set(),
			                 ws.name)

	def test_every_shortcut_block_names_a_shortcut_label(self):
		for ws in workspaces():
			labels = {r.label for r in ws.shortcuts}
			self.assertEqual(set(blocks(ws, "shortcut", "shortcut_name")) - labels, set(), ws.name)

	def test_every_link_card_block_names_a_card(self):
		for ws in workspaces():
			breaks = {r.label for r in ws.links if r.type == "Card Break"}
			self.assertTrue(breaks, ws.name)
			self.assertEqual(set(blocks(ws, "card", "card_name")) - breaks, set(), ws.name)

	def test_nothing_is_listed_that_the_page_never_draws(self):
		"""A chart in the table but not in the layout is a widget somebody thinks is there."""
		for ws in workspaces():
			self.assertEqual({r.label for r in ws.charts} - set(blocks(ws, "chart", "chart_name")),
			                 set(), ws.name)
			self.assertEqual({r.label for r in ws.number_cards}
			                 - set(blocks(ws, "number_card", "number_card_name")), set(), ws.name)
			self.assertEqual({r.label for r in ws.shortcuts}
			                 - set(blocks(ws, "shortcut", "shortcut_name")), set(), ws.name)

	def test_the_parent_still_carries_every_decision_number_and_chart(self):
		parent = frappe.get_doc("Workspace", "FieldMate")
		self.assertEqual(len(parent.shortcuts), 6)
		self.assertEqual(len(parent.number_cards), 8)
		self.assertEqual(len(parent.charts), 7)


class TestEveryWidgetWorks(FieldMateTestCase):
	def test_every_chart_exists_and_computes(self):
		from frappe.desk.doctype.dashboard_chart.dashboard_chart import get

		for ws in workspaces():
			for row in ws.charts:
				self.assertTrue(frappe.db.exists("Dashboard Chart", row.chart_name), row.chart_name)
				get(chart_name=row.chart_name, refresh=1)

	def test_every_number_card_exists_and_computes(self):
		from frappe.desk.doctype.number_card.number_card import get_result

		for ws in workspaces():
			for row in ws.number_cards:
				self.assertTrue(frappe.db.exists("Number Card", row.number_card_name),
				                row.number_card_name)
				card = frappe.get_doc("Number Card", row.number_card_name)
				get_result(card.as_dict(), [])

	def test_no_widget_puts_a_plain_value_where_desk_expects_javascript(self):
		"""Desk evals each dynamic filter value as JavaScript (dashboard_utils.js, get_all_filters).

		The cards once carried `Timespan "this month"` there: fine on the server, so every test
		above passed, and in the browser every card stopped on "Invalid expression set in filter".
		None of ours needs a dynamic filter; a period is a plain Timespan filter.
		"""
		for ws in workspaces():
			for row in ws.number_cards:
				card = frappe.db.get_value("Number Card", row.number_card_name, "dynamic_filters_json")
				self.assertEqual(json.loads(card or "[]"), [], row.number_card_name)
			for row in ws.charts:
				chart = frappe.db.get_value("Dashboard Chart", row.chart_name, "dynamic_filters_json")
				self.assertEqual(json.loads(chart or "[]"), [], row.chart_name)

	def test_every_shortcut_counts(self):
		for ws in workspaces():
			for row in ws.shortcuts:
				frappe.get_list(row.link_to, filters=json.loads(row.stats_filter),
				                limit_page_length=1)

	def test_every_link_points_at_something_real(self):
		kinds = {"DocType": "DocType", "Report": "Report", "Page": "Page"}
		for ws in workspaces():
			for row in ws.links:
				if row.type != "Link":
					continue
				self.assertTrue(frappe.db.exists(kinds[row.link_type], row.link_to),
				                f"{ws.name}: {row.label} -> {row.link_type} {row.link_to}")


class TestTheAppsScreen(FieldUserFixture):
	def entry(self):
		return frappe.get_hooks("add_to_apps_screen", app_name="fieldmate")[0]

	def test_the_logo_is_a_file_the_app_ships(self):
		logo = self.entry()["logo"]
		self.assertTrue(logo.startswith("/assets/fieldmate/"))
		path = frappe.get_app_path("fieldmate", "public", logo.removeprefix("/assets/fieldmate/"))
		self.assertTrue(os.path.isfile(path), path)

	def test_the_tile_opens_the_workspace(self):
		self.assertEqual(self.entry()["route"], "/app/fieldmate")

	def test_a_desk_user_with_fieldmate_sees_the_tile(self):
		frappe.set_user(self.make_user(role="FieldMate Sales Head"))
		try:
			self.assertTrue(check_app_permission())
		finally:
			frappe.set_user("Administrator")

	def test_a_rep_who_cannot_open_desk_does_not(self):
		user = self.make_user(role="FieldMate Field Rep")
		frappe.db.set_value("User", user, "user_type", "Website User")
		frappe.set_user(user)
		try:
			self.assertFalse(check_app_permission())
		finally:
			frappe.set_user("Administrator")
