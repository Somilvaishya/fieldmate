"""Phase 10 security pass: each test here is a hole that was found open, and is now shut.

Read as a rep, because every one of these was reachable by a Field Rep with a phone and a guessed
name. What a rep is *meant* to do keeps its own tests elsewhere; these only prove the refusals.
"""

from types import SimpleNamespace

import frappe
from frappe.utils import add_days, today

from fieldmate.api import outlet as outlet_api
from fieldmate.services import catalogue as catalogue_service
from fieldmate.services import collection as collection_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import order as order_service
from fieldmate.tests.test_order import OrderFixture


class SecurityFixture(OrderFixture):
	def tearDown(self):
		frappe.set_user("Administrator")
		self.wipe_since_setup("FieldMate Collection")
		super().tearDown()

	def somebody_elses_party(self):
		"""A party we bill, in a territory the rep has nothing to do with."""
		doc = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": self.uid("Far Distributor"),
				"customer_group": self.distributor.customer_group,
				"territory": self.make_territory(),
				"fm_tier": "Distributor",
				"fm_buys_from": "Company",
			}
		).insert(ignore_permissions=True)
		self.track("Customer", doc.name)
		return doc.name

	def my_area_manager(self):
		"""An Area Manager the rep reports to. Returns their login."""
		manager = self.make_field_user(
			user=self.make_user(role="FieldMate Area Manager"),
			designation="Area Manager",
			territory=self.rep.territory,
		)
		self.rep.db_set("reports_to", manager.name)
		return manager.user

	def another_area_manager(self):
		"""An Area Manager nobody in this fixture reports to."""
		return self.make_field_user(
			user=self.make_user(role="FieldMate Area Manager"),
			designation="Area Manager",
			territory=self.rep.territory,
		).user

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")


class TestARepWithoutARecord(SecurityFixture):
	"""A Field Rep with no Field User was treated like a manager: limited to nobody."""

	def test_is_limited_to_nothing_rather_than_to_everybody(self):
		orphan = self.make_user(role="FieldMate Field Rep")
		self.assertEqual(field_user_service.rep_only(orphan), field_user_service.NO_RECORD)
		self.assertIn(
			field_user_service.NO_RECORD,
			field_user_service.own_rows_query("FieldMate Location Trail", orphan),
		)

	def test_a_manager_is_still_not_limited(self):
		manager = self.make_user(role="FieldMate Area Manager")
		self.assertIsNone(field_user_service.rep_only(manager))


class TestSigningIn(SecurityFixture):
	"""`on_login`, which every login path runs before it makes a session."""

	def sign_in(self, user):
		field_user_service.refuse_a_rep_without_an_active_record(SimpleNamespace(user=user))

	def test_the_hook_is_wired(self):
		self.assertIn(
			"fieldmate.services.field_user.refuse_a_rep_without_an_active_record",
			frappe.get_hooks("on_login"),
		)

	def test_an_active_rep_signs_in(self):
		self.sign_in(self.rep.user)

	def test_an_inactive_rep_is_refused(self):
		frappe.db.set_value("FieldMate Field User", self.rep.name, "status", "Inactive")
		with self.assertRaises(field_user_service.NotAnActiveFieldUser):
			self.sign_in(self.rep.user)

	def test_going_inactive_signs_the_rep_out_everywhere(self):
		frappe.db.sql(
			"insert into `tabSessions` (user, sid, sessiondata, ipaddress, lastupdate, status)"
			" values (%s, %s, '{}', '127.0.0.1', now(), 'Active')",
			(self.rep.user, self.uid("sid")))
		self.rep.reload()
		self.rep.status = "Inactive"
		self.rep.save(ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Sessions", {"user": self.rep.user}))

	def test_a_rep_with_no_record_is_refused(self):
		with self.assertRaises(frappe.AuthenticationError):
			self.sign_in(self.make_user(role="FieldMate Field Rep"))

	def test_people_who_are_not_reps_are_left_alone(self):
		self.sign_in(self.make_user(role="FieldMate Area Manager"))
		self.sign_in(self.make_user(role=None))
		self.sign_in("Administrator")


class TestImportingShops(SecurityFixture):
	def test_a_rep_cannot_import_approved_shops(self):
		frappe.set_user(self.rep.user)
		try:
			result = outlet_api.bulk_import(rows="[]", dry_run=1)
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(result["ok"])
		self.assertEqual(result["code"], "PERMISSION_DENIED")


class TestSomebodyElsesParty(SecurityFixture):
	def test_its_price_book_is_refused(self):
		far = self.somebody_elses_party()
		with self.assertRaises(frappe.PermissionError):
			self.as_rep(catalogue_service.readable_party, far, "Customer")

	def test_my_own_distributor_is_still_readable(self):
		party = self.as_rep(catalogue_service.readable_party, self.distributor.name, "Customer")
		self.assertEqual(party.name, self.distributor.name)

	def test_its_credit_is_refused(self):
		from fieldmate.api import credit as credit_api

		far = self.somebody_elses_party()
		frappe.set_user(self.rep.user)
		try:
			result = credit_api.position(party=far, party_type="Customer")
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(result["ok"])

	def test_a_primary_order_on_it_is_refused(self):
		far = self.somebody_elses_party()
		with self.assertRaises(frappe.PermissionError):
			self.as_rep(
				order_service.create,
				{
					"party_type": "Customer",
					"customer": far,
					"lines": self.cart(),
					"client_uuid": self.uid("ORD"),
				},
				self.rep.name,
			)
		self.assertFalse(frappe.db.exists("FieldMate Order", {"customer": far}))


class TestCollectingAgainstSomebodyElsesOrder(SecurityFixture):
	"""An allocation to a booking releases it on submit, before any money is confirmed."""

	def test_an_order_of_another_party_is_refused(self):
		other_shop = self.make_outlet(territory=self.rep.territory, approval_status="Approved")
		order = self.as_rep(
			order_service.create,
			{
				"outlet": other_shop.name,
				"lines": self.cart(),
				"client_uuid": self.uid("ORD"),
			},
			self.rep.name,
		)

		with self.assertRaises(frappe.PermissionError):
			self.as_rep(
				collection_service.create,
				{
					"party_type": "Outlet",
					"outlet": self.outlet.name,
					"amount": 100,
					"mode": "Cash",
					"client_uuid": self.uid("COL"),
					"collection_date": today(),
					"allocations": [
						{
							"reference_type": "FieldMate Order",
							"reference_name": order["name"],
							"allocated_amount": 100,
						}
					],
				},
				self.rep.name,
			)


class TestRunningTheMachinery(SecurityFixture):
	"""M2. `rebuild` and `run_alerts` are the nightly jobs. Any Area Manager could run them over
	any window for the whole company, inside one web request."""

	def rebuild(self, user, **kwargs):
		from fieldmate.api import dashboard as dashboard_api

		return self.as_user(user, dashboard_api.rebuild, **kwargs)

	def run_alerts(self, user, **kwargs):
		from fieldmate.api import dashboard as dashboard_api

		return self.as_user(user, dashboard_api.run_alerts, **kwargs)

	def test_a_manager_may_restate_their_own_reps_week(self):
		answer = self.rebuild(
			self.my_area_manager(), from_date=add_days(today(), -6), to_date=today(),
			field_user=self.rep.name)
		self.assertTrue(answer["ok"], answer)

	def test_a_manager_may_not_restate_somebody_elses_rep(self):
		answer = self.rebuild(
			self.another_area_manager(), from_date=today(), to_date=today(),
			field_user=self.rep.name)
		self.assertEqual(answer["code"], "PERMISSION_DENIED")

	def test_a_manager_may_not_rebuild_the_whole_company(self):
		answer = self.rebuild(self.my_area_manager(), from_date=today(), to_date=today())
		self.assertEqual(answer["code"], "PERMISSION_DENIED")

	def test_ten_years_is_refused_whoever_asks(self):
		answer = self.rebuild("Administrator", from_date="2016-01-01", to_date=today(),
		                      field_user=self.rep.name)
		self.assertEqual(answer["code"], "BAD_REQUEST")

	def test_a_window_that_ends_before_it_starts_is_refused(self):
		answer = self.rebuild("Administrator", from_date=today(), to_date=add_days(today(), -3),
		                      field_user=self.rep.name)
		self.assertEqual(answer["code"], "BAD_REQUEST")

	def test_alerts_for_everybody_are_not_an_area_managers_to_run(self):
		self.assertEqual(self.run_alerts(self.my_area_manager())["code"], "PERMISSION_DENIED")

	def test_alerts_over_a_year_are_refused(self):
		answer = self.run_alerts("Administrator", days_back=365)
		self.assertEqual(answer["code"], "BAD_REQUEST")


class TestTheManagersDashboards(SecurityFixture):
	"""M5. A manager's summary and alert log are their team's, not the company's."""

	def sales_person(self, parent=None):
		root = parent or self.root()
		doc = frappe.get_doc({
			"doctype": "Sales Person", "sales_person_name": self.uid("SP"),
			"parent_sales_person": root, "is_group": 1,
		}).insert(ignore_permissions=True)
		return self.track("Sales Person", doc.name)

	def root(self):
		"""The top of the tree, found by position: a NULL parent never matches `in ("", None)`."""
		return frappe.get_all("Sales Person", order_by="lft asc", limit=1, pluck="name")[0]

	def alert_for(self, field_user):
		doc = frappe.new_doc("FieldMate Alert Log")
		doc.update({"rule": self.uid("RULE"), "field_user": field_user, "occurred_on": today()})
		doc.name = self.uid("ALR")
		doc.db_insert()
		return self.track("FieldMate Alert Log", doc.name)

	def call(self, user, method, **kwargs):
		from fieldmate.api import dashboard as dashboard_api

		return self.as_user(user, getattr(dashboard_api, method), **kwargs)

	def test_a_manager_summarises_their_own_branch(self):
		manager = self.my_area_manager()
		node = self.sales_person()
		frappe.db.set_value("FieldMate Field User", {"user": manager}, "sales_person", node)
		self.assertTrue(self.call(manager, "manager_summary", sales_person=node)["ok"])

	def test_a_manager_cannot_summarise_the_root(self):
		manager = self.my_area_manager()
		frappe.db.set_value("FieldMate Field User", {"user": manager}, "sales_person",
		                    self.sales_person())
		root = self.root()
		self.assertTrue(root)
		answer = self.call(manager, "manager_summary", sales_person=root)
		self.assertEqual(answer["code"], "PERMISSION_DENIED")

	def test_the_alert_log_is_the_teams(self):
		manager = self.my_area_manager()
		mine = self.alert_for(self.rep.name)
		stranger = self.make_field_user(territory=self.make_territory())
		theirs = self.alert_for(stranger.name)

		names = {a["name"] for a in self.call(manager, "exceptions", limit=200)["data"]["alerts"]}
		self.assertIn(mine, names)
		self.assertNotIn(theirs, names)

	def test_somebody_elses_rep_cannot_be_asked_for_by_name(self):
		manager = self.my_area_manager()
		stranger = self.make_field_user(territory=self.make_territory())
		answer = self.call(manager, "exceptions", field_user=stranger.name)
		self.assertEqual(answer["code"], "PERMISSION_DENIED")


class TestEvidenceIsNotEditable(SecurityFixture):
	"""M6. A trail is where a person was all day, and a day carries their selfie and odometer.
	Nobody above a rep edits either; the services that write them do so on the rep's behalf."""

	def test_no_manager_may_write_or_make_a_trail(self):
		for role in ("FieldMate Area Manager", "FieldMate Regional Manager", "FieldMate Sales Head"):
			user = self.make_user(role=role)
			for ptype in ("write", "create"):
				self.assertFalse(
					frappe.has_permission("FieldMate Location Trail", ptype, user=user),
					f"{role} may {ptype} a Location Trail")
			self.assertTrue(frappe.has_permission("FieldMate Location Trail", "read", user=user))

	def test_an_area_manager_may_not_edit_a_day(self):
		user = self.make_user(role="FieldMate Area Manager")
		self.assertFalse(frappe.has_permission("FieldMate Day", "write", user=user))
		self.assertTrue(frappe.has_permission("FieldMate Day", "read", user=user))

	def bare_visit(self):
		doc = frappe.new_doc("FieldMate Visit")
		doc.name = self.uid("VIS")
		doc.field_user = self.rep.name
		doc.outlet = self.outlet.name
		doc.visit_date = today()
		doc.db_insert()
		self.track("FieldMate Visit", doc.name)
		return frappe.get_doc("FieldMate Visit", doc.name)

	def test_a_manager_acts_on_their_own_teams_visit(self):
		from fieldmate.services import visit as visit_service

		visit = self.bare_visit()
		self.as_user(self.my_area_manager(), visit_service.assert_owner, visit)

	def test_a_manager_may_not_act_on_somebody_elses_visit(self):
		from fieldmate.services import visit as visit_service

		visit = self.bare_visit()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.another_area_manager(), visit_service.assert_owner, visit)


class TestWhoSeesWhatIsPersonal(SecurityFixture):
	"""M8. Trails, days, visits and devices: a manager their team, the Sales Head everybody."""

	def bare(self, doctype, **fields):
		doc = frappe.new_doc(doctype)
		doc.update(fields)
		doc.name = self.uid("ROW")
		doc.db_insert()
		return self.track(doctype, doc.name)

	def rows_for_two(self, doctype):
		"""One row for the manager's own rep, one for a stranger's."""
		stranger = self.make_field_user(territory=self.make_territory())
		if doctype == "FieldMate Device Registry":
			mine = self.bare(doctype, user=self.rep.user, device_uuid=self.uid("dev"))
			theirs = self.bare(doctype, user=stranger.user, device_uuid=self.uid("dev"))
		else:
			mine = self.bare(doctype, field_user=self.rep.name)
			theirs = self.bare(doctype, field_user=stranger.name)
		return mine, theirs

	def visible(self, user, doctype, names):
		def read():
			return set(frappe.get_list(doctype, filters={"name": ["in", names]}, pluck="name"))

		return self.as_user(user, read)

	def check(self, doctype):
		mine, theirs = self.rows_for_two(doctype)
		manager = self.my_area_manager()
		self.assertEqual(self.visible(manager, doctype, [mine, theirs]), {mine})
		self.assertFalse(frappe.has_permission(doctype, "read", doc=theirs, user=manager))
		self.assertTrue(frappe.has_permission(doctype, "read", doc=mine, user=manager))

		head = self.make_user(role="FieldMate Sales Head")
		if frappe.has_permission(doctype, "read", user=head):
			self.assertEqual(self.visible(head, doctype, [mine, theirs]), {mine, theirs})

	def test_trails(self):
		self.check("FieldMate Location Trail")

	def test_days(self):
		self.check("FieldMate Day")

	def test_visits(self):
		self.check("FieldMate Visit")

	def test_devices(self):
		self.check("FieldMate Device Registry")

	def test_a_rep_still_sees_only_their_own_trail(self):
		mine, theirs = self.rows_for_two("FieldMate Location Trail")
		self.assertEqual(self.visible(self.rep.user, "FieldMate Location Trail", [mine, theirs]),
		                 {mine})


class TestWhosePlanItIs(SecurityFixture):
	"""M10. A journey plan is which shops a rep walks on which day."""

	def plan(self, field_user):
		return frappe.get_doc({
			"doctype": "FieldMate Journey Plan", "field_user": field_user,
			"from_date": today(), "to_date": add_days(today(), 6),
		})

	def build_days(self, user):
		from fieldmate.fieldmate.doctype.fieldmate_journey_plan import fieldmate_journey_plan

		return self.as_user(user, fieldmate_journey_plan.build_days, self.rep.name, today(),
		                    add_days(today(), 6))

	def test_my_area_manager_builds_my_days(self):
		self.assertIn("days", self.build_days(self.my_area_manager()))

	def test_another_area_manager_does_not(self):
		with self.assertRaises(frappe.PermissionError):
			self.build_days(self.another_area_manager())

	def test_another_area_manager_cannot_save_a_plan_for_me(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.another_area_manager(), self.plan(self.rep.name).insert)
		self.assertFalse(frappe.db.exists("FieldMate Journey Plan", {"field_user": self.rep.name}))

	def test_my_area_manager_can(self):
		doc = self.as_user(self.my_area_manager(), self.plan(self.rep.name).insert)
		self.track("FieldMate Journey Plan", doc.name)

	def test_a_rep_reads_only_their_own_plan(self):
		colleague = self.make_field_user(territory=self.rep.territory)
		names = []
		for fu in (self.rep.name, colleague.name):
			doc = frappe.new_doc("FieldMate Journey Plan")
			# Territory named: `new_doc` fills an empty Link from the session's defaults, and
			# the rep's Territory permission would then hide their own row for that reason.
			doc.update({"field_user": fu, "from_date": today(), "to_date": today(),
			            "territory": self.rep.territory})
			doc.name = self.uid("JP")
			doc.db_insert()
			names.append(self.track("FieldMate Journey Plan", doc.name))

		seen = self.as_user(self.rep.user, frappe.get_list, "FieldMate Journey Plan",
		                    filters={"name": ["in", names]}, pluck="name")
		self.assertEqual(seen, [names[0]])
