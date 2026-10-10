"""Phase 2, step 8 — the range shown to a party at their own prices, behind a public link.

**This is the only thing in the app that answers to somebody with no login**, so most of what is
below is about what it refuses rather than what it shows. A share link is a URL in a WhatsApp
message: whoever holds it is whoever it was forwarded to.

The page is drawn too, not just its context built. `/distributor/sales` had a test that called
`get_context` and stopped, and it passed for weeks over a page that answered 500 on every load.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate.services import showcase as showcase_service
from fieldmate.tests.test_season import SeasonFixture


class ShowcaseFixture(SeasonFixture):
	def setUp(self):
		super().setUp()
		self.price_item(self.item, 100)
		self.catalogue = self.make_showcase()

	def make_showcase(self, **kwargs):
		data = {
			"doctype": "FieldMate Product Catalogue",
			"catalogue_name": self.uid("SHOW"),
			"is_active": 1,
			"is_showcase": 1,
			"blurb": "Everything for the season.",
			"items": [{"item_code": self.item, "sort_order": 1}],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		return self.track("FieldMate Product Catalogue", doc.name)

	def share(self, **kwargs):
		name = showcase_service.make_link(
			self.catalogue, self.party, self.rep.name, "Customer", **kwargs)
		self.track("FieldMate Share Link", name)
		return frappe.get_doc("FieldMate Share Link", name)


class TestMakingALink(ShowcaseFixture):
	def test_the_token_is_generated_not_chosen(self):
		"""It is the only thing standing between a public URL and one party's prices."""
		link = self.share()
		self.assertTrue(link.token)
		self.assertGreaterEqual(len(link.token), 32)

	def test_two_links_never_share_a_token(self):
		self.assertNotEqual(self.share().token, self.share().token)

	def test_the_price_list_is_fixed_when_the_link_is_made(self):
		"""A party reading a price on Tuesday and being quoted another on Wednesday is the
		argument this field exists to prevent."""
		link = self.share()
		self.assertTrue(link.price_list)

	def test_it_expires_by_itself(self):
		"""A quotation that never expires is a price somebody holds you to next year."""
		link = self.share()
		self.assertTrue(link.valid_to)
		self.assertGreater(str(link.valid_to), str(today()))

	def test_an_ordinary_catalogue_cannot_be_shared(self):
		"""It carries focus flags, minimum order quantities and notes written for a rep. Putting
		one in front of a buyer is not a feature."""
		plain = self.make_showcase(is_showcase=0)
		with self.assertRaises(frappe.ValidationError) as caught:
			showcase_service.make_link(plain, self.party, self.rep.name, "Customer")
		self.assertIn("not a showcase", str(caught.exception))

	def test_a_link_is_for_exactly_one_party(self):
		with self.assertRaises(frappe.ValidationError):
			doc = frappe.get_doc({
				"doctype": "FieldMate Share Link", "catalogue": self.catalogue,
				"party_type": "Customer", "field_user": self.rep.name,
			})
			doc.flags.ignore_permissions = True
			doc.insert()


class TestOpeningIt(ShowcaseFixture):
	def test_a_good_token_shows_the_range(self):
		link = self.share()
		answer = showcase_service.page(link.token)
		self.assertTrue(answer["ok"])
		self.assertEqual([row["item_code"] for row in answer["items"]], [self.item])
		self.assertEqual(answer["items"][0]["rate"], 100)

	def test_it_names_the_party_and_the_rep(self):
		"""A buyer wants to know whose prices these are; a rep wants them to see it was
		personal."""
		answer = showcase_service.page(self.share().token)
		self.assertTrue(answer["party_name"])
		self.assertTrue(answer["shared_by"])

	def test_an_unpriced_item_is_left_out_rather_than_shown_at_nothing(self):
		"""On a rep's screen an unpriced line is named so somebody fixes it. On a customer's
		screen it is either free or broken, and neither goes in front of a buyer."""
		spare = self.make_item()
		doc = frappe.get_doc("FieldMate Product Catalogue", self.catalogue)
		doc.append("items", {"item_code": spare, "sort_order": 2})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)

		answer = showcase_service.page(self.share().token)
		self.assertNotIn(spare, [row["item_code"] for row in answer["items"]])

	def test_opening_it_is_counted(self):
		link = self.share()
		showcase_service.page(link.token)
		link.reload()
		self.assertEqual(link.view_count, 1)
		self.assertTrue(link.first_opened)

	def test_the_address_is_kept_so_a_forwarded_link_can_be_recognised(self):
		link = self.share()
		showcase_service.page(link.token, ip="203.0.113.9")
		link.reload()
		self.assertEqual(link.last_seen_ip, "203.0.113.9")


class TestWhatItRefuses(ShowcaseFixture):
	def refused(self, token):
		answer = showcase_service.page(token)
		self.assertFalse(answer["ok"])
		return answer["message"]

	def test_an_unknown_token(self):
		self.assertEqual(self.refused("not-a-token"), showcase_service.CLOSED)

	def test_an_empty_token(self):
		self.assertEqual(self.refused(""), showcase_service.CLOSED)

	def test_a_withdrawn_link(self):
		"""Switching it off is the only way a URL is ever taken back."""
		link = self.share()
		showcase_service.withdraw(link.name)
		self.assertEqual(self.refused(link.token), showcase_service.CLOSED)

	def test_an_expired_link(self):
		link = self.share(valid_from=add_days(today(), -30), valid_to=add_days(today(), -1))
		self.assertFalse(showcase_service.page(link.token)["ok"])

	def test_a_link_that_is_not_open_yet(self):
		link = self.share(valid_from=add_days(today(), 3), valid_to=add_days(today(), 30))
		self.assertFalse(showcase_service.page(link.token)["ok"])

	def test_a_link_opened_more_times_than_allowed(self):
		"""A link forwarded round a market is still one link, and this is the only thing that
		notices."""
		link = self.share(max_views=1)
		self.assertTrue(showcase_service.page(link.token)["ok"])
		self.assertFalse(showcase_service.page(link.token)["ok"])

	def test_a_refusal_says_nothing_about_whose_link_it_was(self):
		"""Who it was for, when it expired and how often it was opened are all facts about a
		conversation the visitor may not have been part of."""
		link = self.share()
		showcase_service.withdraw(link.name)
		message = self.refused(link.token)
		self.assertNotIn(self.party, message)
		self.assertNotIn(str(link.name), message)


class TestAskingForSomething(ShowcaseFixture):
	def test_it_becomes_the_reps_draft_and_not_an_order(self):
		"""A party typing quantities into a web page has been through no credit check, no scheme
		engine and no MRP check, and must not be able to commit the company by filling in a
		form."""
		link = self.share()
		answer = showcase_service.self_order(link.token, [{"item": self.item, "qty": 5}])
		self.assertTrue(answer["ok"])

		order = frappe.get_doc("FieldMate Order", self.track("FieldMate Order", answer["order"]))
		self.assertEqual(order.docstatus, 0, "a draft, for the rep to look at")
		self.assertEqual(order.field_user, self.rep.name)
		self.assertEqual(order.customer, self.party)

	def test_the_draft_says_where_it_came_from(self):
		"""A draft nobody can explain is a draft nobody acts on."""
		link = self.share()
		answer = showcase_service.self_order(link.token, [{"item": self.item, "qty": 5}])
		order = frappe.get_doc("FieldMate Order", self.track("FieldMate Order", answer["order"]))
		self.assertIn("shared catalogue", order.remarks)

	def test_an_item_the_link_does_not_show_is_ignored(self):
		"""An item code the visitor supplied that is not on the page is somebody trying it on."""
		spare = self.make_item()
		self.price_item(spare, 50)
		link = self.share()

		answer = showcase_service.self_order(link.token, [
			{"item": self.item, "qty": 2}, {"item": spare, "qty": 99}])
		order = frappe.get_doc("FieldMate Order", self.track("FieldMate Order", answer["order"]))
		self.assertEqual([row.item_code for row in order.items], [self.item])

	def test_nothing_asked_for_is_refused_kindly(self):
		link = self.share()
		answer = showcase_service.self_order(link.token, [{"item": self.item, "qty": 0}])
		self.assertFalse(answer["ok"])
		self.assertIn("how much", answer["message"])

	def test_a_closed_link_cannot_be_ordered_from(self):
		link = self.share()
		showcase_service.withdraw(link.name)
		answer = showcase_service.self_order(link.token, [{"item": self.item, "qty": 5}])
		self.assertFalse(answer["ok"])

	def test_the_server_prices_it_not_the_visitor(self):
		"""Quantities are the only thing taken from them, and even those are re-priced."""
		link = self.share()
		answer = showcase_service.self_order(
			link.token, [{"item": self.item, "qty": 3, "rate": 1}])
		order = frappe.get_doc("FieldMate Order", self.track("FieldMate Order", answer["order"]))
		self.assertEqual(order.items[0].rate, 100)


class TestThePageActuallyRenders(ShowcaseFixture):
	"""Drawn, not just built.

	`/distributor/sales` had a test that called `get_context` and stopped, and it passed for weeks
	over a page that answered 500 on every load because it had written to a context key Frappe
	owns. This draws the page.
	"""

	def render(self, token: str) -> str:
		from frappe.website.page_renderers.template_page import TemplatePage

		# The user FIRST, then the form. `frappe.set_user` clears `local.form_dict` (and
		# `session.data`) on its way through, so setting the token before switching to Guest
		# wipes it - and the page then renders its "not available" branch for a link that is
		# perfectly good.
		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict({"t": token})
		try:
			page = TemplatePage(path="showcase")
			self.assertTrue(page.can_render(), "showcase is not a page at all")
			answer = page.render()
			return (answer.get_data(as_text=True)
			        if hasattr(answer, "get_data") else str(answer))
		finally:
			frappe.set_user("Administrator")
			frappe.local.form_dict = frappe._dict()

	def test_a_guest_can_draw_it(self):
		link = self.share()
		html = self.render(link.token)
		self.assertIn(self.item, html)
		self.assertGreater(len(html), 500)

	def test_a_closed_link_draws_the_refusal_rather_than_failing(self):
		link = self.share()
		showcase_service.withdraw(link.name)
		html = self.render(link.token)
		self.assertIn("Not available", html)
		self.assertNotIn(self.item, html, "a closed link shows nothing of the range")

	def test_the_page_leaves_frappes_own_context_keys_alone(self):
		"""`template`, `doc`, `route` and their like belong to the renderer."""
		from fieldmate.www import showcase as page_module

		frappe.local.form_dict = frappe._dict({"t": self.share().token})
		try:
			context = page_module.get_context(frappe._dict())
		finally:
			frappe.local.form_dict = frappe._dict()

		for reserved in ("template", "doc", "route", "path"):
			self.assertNotIn(reserved, context,
			                 f"{reserved} belongs to Frappe, not to this page")

	def test_it_asks_not_to_be_indexed(self):
		"""A shared price list is not something to find in a search engine."""
		html = self.render(self.share().token)
		self.assertIn("noindex", html)
