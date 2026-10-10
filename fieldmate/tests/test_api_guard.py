"""Two guards the API facade had been missing: a rate limit, and a CSRF token.

Both are carry-over items from the Three-Phase Plan, and both were worth their place on that list.

**CSRF.** Frappe skips validation entirely for a session that has no token saved - look at
`auth.validate_csrf_token` and its `not saved_token` arm - and an API login leaves one unset. So
every write this app accepted was unprotected by it. The session cookie is `SameSite=Lax`, which
stops the simplest cross-site POST, but a cookie arriving is not a decision to perform an action
and should not be read as one.

**Rate limit.** `auth.login` is the only guest-accessible method in the app and `sync.push` is the
only one that writes a day's work in a single call. Those are the two worth limiting.
"""

import os

import frappe

from fieldmate.api import auth as auth_api
from fieldmate.tests.base import FieldMateTestCase


def source_of(module) -> str:
	with open(module.__file__, encoding="utf-8") as fh:
		return fh.read()


class TestTheSessionCarriesACsrfToken(FieldMateTestCase):
	def test_a_token_is_made_for_a_session_that_has_none(self):
		"""Which is every session this app creates - and 'no token' is exactly what Frappe reads
		as 'do not check'."""
		token = auth_api._csrf_token()
		self.assertTrue(token)
		self.assertGreater(len(token), 16, "long enough to be worth checking")

	def test_the_same_session_keeps_the_same_token(self):
		"""Or the phone sends back one the server has already replaced, and every write after
		the first is refused."""
		self.assertEqual(auth_api._csrf_token(), auth_api._csrf_token())

	def test_it_reaches_the_session_frappe_validates_against(self):
		"""The whole point. A token answered to the phone and not stored is a token the check
		will not recognise."""
		token = auth_api._csrf_token()
		self.assertEqual(frappe.local.session.data.get("csrf_token"), token)

	def test_it_says_nothing_rather_than_failing_without_a_session(self):
		"""Called from a context with no session - a patch, a scheduled job - this must answer
		None rather than raise. Nothing about GST or orders should break because of a guard."""
		session = frappe.local.session
		try:
			frappe.local.session = None
			self.assertIsNone(auth_api._csrf_token())
		finally:
			frappe.local.session = session


class TestTheTwoWaysInAreRateLimited(FieldMateTestCase):
	"""Asserted against the source, deliberately.

	`frappe.rate_limiter` short-circuits when there is no HTTP request, which is every test - so
	calling the endpoint a hundred times here proves nothing at all. What can be proved is that
	the decorator is on the endpoint, which is the thing somebody would remove by accident.
	"""

	def test_login_is_limited(self):
		source = source_of(auth_api)
		self.assertIn("@rate_limit(", source)
		i = source.index("def login(")
		self.assertIn("@rate_limit(", source[max(0, i - 400):i],
		              "the limit is on login, not on some other method in the file")

	def test_push_is_limited(self):
		from fieldmate.api import sync as sync_api

		source = source_of(sync_api)
		i = source.index("def push(")
		self.assertIn("@rate_limit(", source[max(0, i - 400):i])

	def test_the_limit_counts_addresses_rather_than_usernames(self):
		"""Limiting by username lets anybody lock a named rep out of their own phone by failing
		their login twenty times, and a rep standing in a market cannot wait an hour for that."""
		source = source_of(auth_api)
		i = source.index("def login(")
		decorator = source[max(0, i - 400):i]
		self.assertNotIn('key="usr"', decorator)
		self.assertNotIn("key='usr'", decorator)

	def test_a_test_run_is_not_rate_limited(self):
		"""`frappe.rate_limiter` returns early when there is no request, so a thousand calls in a
		suite cost nothing. Pinned because the opposite would be very confusing: a test file
		failing on its twenty-first assertion for reasons nothing in it mentions."""
		# `frappe.request` is a LocalProxy, so it is never None - it is *unbound*, and reading
		# it raises. Truthiness is the question the rate limiter itself asks.
		self.assertFalse(bool(getattr(frappe.local, "request", None)))
		for _ in range(25):
			auth_api._csrf_token()


class TestThePhoneSendsItBack(FieldMateTestCase):
	"""The other half of the rule, and it lives in JavaScript.

	The PWA has its own suite now, and `frontend/tests` covers what the client does with the
	token. This checks the one thing that suite cannot: that the server and the phone agree on
	the header's name. A mismatch there fails nothing and protects nothing.
	"""

	def test_the_header_name_matches_what_frappe_reads(self):
		app = frappe.get_app_path("fieldmate")
		client = os.path.join(app, "..", "frontend", "src", "api", "client.js")
		with open(client, encoding="utf-8") as fh:
			source = fh.read()

		self.assertIn("X-Frappe-CSRF-Token", source,
		              "the name Frappe reads in auth.validate_csrf_token")
		self.assertIn("csrf_token", source, "and the key login answers with")
