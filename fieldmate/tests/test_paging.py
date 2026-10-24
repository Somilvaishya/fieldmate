"""A list says what it is a page of.

Thirteen endpoints took a `limit` and the rest took nothing. A `limit` is a cap, not a page: it
tells the server where to stop and tells the screen nothing. A rep with two hundred orders got
fifty, had no way to ask for the rest, and - the part that matters - **got no sign there was a
rest**. The list simply ended, which is the worst way for a cap to fail, because the screen looks
complete.

These pin the three rules that make a page a page:

  * a window moves (`start`), and the second page is not the first one again;
  * `total` counts everything the user may see, not what fitted on the page;
  * `has_more` is computed from the total, not guessed from a full page - "I received fifty so
    there are probably more" is wrong exactly when there are fifty, and a Load more button that
    returns nothing reads as a broken screen.

And one rule that is a security rule rather than a paging one: a count is **permission-aware**.
`frappe.db.count` is not, so a rep's total would otherwise be the whole site's.
"""

import frappe

from fieldmate.api import outlet as outlet_api
from fieldmate.api import portal as portal_api
from fieldmate.services import paging
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_outlet import OutletFixture
from fieldmate.tests.test_portal import PortalFixture


class TestWindowClamping(FieldMateTestCase):
	"""Everything arrives over HTTP as a string, and some of it arrives as nonsense."""

	def test_nothing_asked_for_is_the_default_page(self):
		self.assertEqual(paging.window(None, None), (0, paging.DEFAULT_LIMIT))

	def test_a_string_is_read_as_a_number(self):
		self.assertEqual(paging.window("50", "25"), (50, 25))

	def test_a_negative_start_is_the_beginning(self):
		"""A negative offset is one the database refuses outright."""
		self.assertEqual(paging.window(-10, 20), (0, 20))

	def test_a_limit_of_zero_is_the_default(self):
		"""A page nobody can read is not what the caller meant."""
		self.assertEqual(paging.window(0, 0), (0, paging.DEFAULT_LIMIT))

	def test_a_huge_limit_is_capped(self):
		"""A page is a round trip over a market uplink. Five thousand rows is a screen that
		never paints, and the ceiling is the server's to keep."""
		self.assertEqual(paging.window(0, 10_000), (0, paging.MAX_LIMIT))

	def test_rubbish_is_the_default_rather_than_an_error(self):
		self.assertEqual(paging.window("soon", "lots"), (0, paging.DEFAULT_LIMIT))


class TestTheEnvelope(FieldMateTestCase):
	def test_more_is_waiting(self):
		got = paging.envelope(rows=[1, 2, 3], total=10, start=0, limit=3)
		self.assertTrue(got["has_more"])
		self.assertEqual(got["total"], 10)

	def test_the_last_page_says_so(self):
		got = paging.envelope(rows=[1, 2, 3], total=6, start=3, limit=3)
		self.assertFalse(got["has_more"])

	def test_a_full_page_that_is_the_whole_list_says_there_is_no_more(self):
		"""The case a guess gets wrong. Fifty rows against a total of fifty is the end of the
		list, and a Load more button here would fetch nothing."""
		got = paging.envelope(rows=list(range(50)), total=50, start=0, limit=50)
		self.assertFalse(got["has_more"])

	def test_an_empty_list_is_not_more(self):
		got = paging.envelope(rows=[], total=0, start=0, limit=50)
		self.assertFalse(got["has_more"])
		self.assertEqual(got["total"], 0)


class TestOutletSearchPages(OutletFixture):
	"""The one list on this app that genuinely runs to thousands - Gate 1 imports five thousand
	shops - so it is the one where a cap with no page was most obviously a dead end."""

	def setUp(self):
		super().setUp()
		self.north = self.make_territory()
		self.delhi = self.make_territory(parent=self.north)
		self.mumbai = self.make_territory(parent=self.north)
		self.rep = self.make_field_user(territory=self.delhi)
		self.mine = [self.make_outlet(territory=self.delhi, outlet_name=f"Paged Shop {i}")
		             for i in range(5)]
		self.theirs = self.make_outlet(territory=self.mumbai, outlet_name="Somebody Else")
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def as_rep(self, fn, *args, **kwargs):
		frappe.set_user(self.rep.user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def page(self, **kwargs):
		return self.as_rep(outlet_api.search, q="Paged Shop", **kwargs)["data"]

	def test_the_first_page_is_a_page(self):
		got = self.page(limit=2)
		self.assertEqual(len(got["outlets"]), 2)
		self.assertEqual(got["total"], 5)
		self.assertTrue(got["has_more"])

	def test_the_second_page_is_different_rows(self):
		"""The whole point. Before this, asking twice got the same fifty rows twice."""
		first = {o["name"] for o in self.page(limit=2, start=0)["outlets"]}
		second = {o["name"] for o in self.page(limit=2, start=2)["outlets"]}
		self.assertEqual(len(first), 2)
		self.assertEqual(len(second), 2)
		self.assertEqual(first & second, set(), "a page repeated is not a page")

	def test_walking_to_the_end_finds_every_shop(self):
		seen = set()
		start = 0
		while True:
			got = self.page(limit=2, start=start)
			seen.update(o["name"] for o in got["outlets"])
			if not got["has_more"]:
				break
			start += 2
		self.assertEqual(seen, {o.name for o in self.mine})

	def test_the_last_page_does_not_offer_another(self):
		got = self.page(limit=2, start=4)
		self.assertEqual(len(got["outlets"]), 1)
		self.assertFalse(got["has_more"])

	def test_the_total_is_what_this_rep_may_see(self):
		"""A security rule wearing a count. `frappe.db.count` ignores permissions, so this
		number would otherwise be the whole site's - both wrong and a disclosure."""
		got = self.as_rep(outlet_api.search)["data"]
		names = {o["name"] for o in got["outlets"]}
		self.assertNotIn(self.theirs.name, names)
		self.assertEqual(got["total"], len(self.mine))

	def test_the_list_keeps_its_name_and_its_type(self):
		"""`api/_base` holds the envelope to additive changes because old builds stay in the
		field for weeks after a deploy. A build that has never heard of `start` has to read the
		first page exactly as it always did."""
		got = self.page()
		self.assertIsInstance(got["outlets"], list)


class TestTheDepotsQueuePages(PortalFixture):
	"""The depot's queue, and the search that only ever searched the first page.

	`portal_service.orders` read a page and then filtered it **in Python**. So a depot searching
	for one of their own orders further down the queue was told it did not exist - the search ran
	over the hundred rows that happened to come back, not over the queue. Moving it into the query
	is what makes a page and a search true at the same time, and it is what these pin.
	"""

	def setUp(self):
		super().setUp()
		self.queued = [self.routed(qty=20 + i) for i in range(4)]
		frappe.db.commit()

	def page(self, **kwargs):
		return self.as_depot(portal_api.distributor_orders, **kwargs)["data"]

	def test_the_queue_says_how_many_there_are(self):
		got = self.page(limit=2)
		self.assertEqual(len(got["orders"]), 2)
		self.assertGreaterEqual(got["total"], 4)
		self.assertTrue(got["has_more"])

	def test_the_second_page_is_different_orders(self):
		first = {o["name"] for o in self.page(limit=2, start=0)["orders"]}
		second = {o["name"] for o in self.page(limit=2, start=2)["orders"]}
		self.assertEqual(first & second, set(), "a page repeated is not a page")

	def test_search_reaches_past_the_first_page(self):
		"""The bug, in one assertion. Looking for the last order in the queue with a page of one
		found nothing, because the filter ran after the page rather than inside the query."""
		wanted = self.queued[-1]
		got = self.page(search=wanted, limit=1)
		self.assertIn(wanted, [o["name"] for o in got["orders"]])

	def test_a_search_counts_what_it_matched(self):
		got = self.page(search=self.queued[0], limit=50)
		self.assertEqual(got["total"], len(got["orders"]))
		self.assertFalse(got["has_more"])

	def test_the_list_keeps_its_name_and_its_type(self):
		got = self.page()
		self.assertIsInstance(got["orders"], list)
		self.assertIn("totals", got, "the queue's tiles must still travel with it")
