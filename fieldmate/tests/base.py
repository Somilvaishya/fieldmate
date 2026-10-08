import frappe
from frappe.tests.utils import FrappeTestCase


class FieldMateTestCase(FrappeTestCase):
	"""Shared fixture hygiene.

	FrappeTestCase rolls back per CLASS, not per method, so records leak between tests in the
	same class. Everything here is therefore named uniquely per test and deleted explicitly -
	never relying on rollback between methods.
	"""

	def fresh_settings(self):
		"""FieldMate Settings is a Single: frappe hands back one shared instance, and a stale
		copy saved twice raises TimestampMismatchError. Every read here loads its own."""
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")
		doc = frappe.get_single("FieldMate Settings")
		doc.flags.ignore_permissions = True
		return doc

	def apply_settings(self, **values):
		"""Change settings and drop the cache, which is the half everybody forgets.

		`services/settings.get()` reads through `frappe.cache()`, so a test that writes with
		`frappe.db.set_single_value` changes the row and nothing else - the service keeps
		answering with the old value and the test fails somewhere unrelated. Lives here rather
		than on one fixture because three test files have now needed it.
		"""
		doc = self.fresh_settings()
		for key, value in values.items():
			doc.set(key, value)
		doc.save()
		frappe.cache().delete_value("fieldmate_settings")
		return doc

	def hsn_code(self) -> str | None:
		"""An HSN code these fixtures' items will be accepted with, or None where none is needed.

		india_compliance refuses a sales Item with no HSN/SAC, and refuses one of the wrong
		length: `GST Settings` says which lengths are valid and on a default install that is six
		or eight digits, so the four-digit chapter headings - which are most of the 18,000 seeded
		rows - are **not** usable. A fixture that picked any row at all passed on a site without
		the app and failed on the site the gates run against.

		340111 is toilet soap, which is what these fixtures spend their time pretending to sell,
		and it carries no taxes of its own - an HSN that did would be copied onto every item by
		`set_taxes_from_hsn_code` and would quietly override what a tax test is asserting.

		None on a site without india_compliance: FieldMate has no opinion about GST and does not
		write this field itself.
		"""
		meta = frappe.get_meta("Item")
		if not meta.has_field("gst_hsn_code"):
			return None

		for code in ("340111", "340119", "340290"):
			if frappe.db.exists("GST HSN Code", code):
				return code

		# Any seeded row of a length this site accepts, rather than giving up. A site whose HSN
		# table was loaded differently is still a site these tests should run on.
		from india_compliance.gst_india.doctype.gst_hsn_code.gst_hsn_code import get_hsn_settings

		_, lengths = get_hsn_settings()
		for length in sorted(lengths):
			row = frappe.db.sql(
				"select name from `tabGST HSN Code` where length(name) = %s limit 1", length)
			if row:
				return row[0][0]
		return None

	def with_hsn(self, data: dict) -> dict:
		"""Put an HSN on an Item payload where this site wants one. Harmless where it does not."""
		if not data.get("gst_hsn_code"):
			code = self.hsn_code()
			if code:
				data["gst_hsn_code"] = code
		return data

	def uid(self, prefix: str = "T") -> str:
		return f"{prefix}-{frappe.generate_hash(length=10)}"

	def track(self, doctype: str, name: str) -> str:
		self._created.append((doctype, name))
		return name

	def setUp(self):
		super().setUp()
		self._created = []
		# A watermark for `wipe_since_setup`. Documents a test makes through a service - an
		# order, a collection, a snapshot - never pass through `track`, so there is no list of
		# their names to delete.
		self._began = frappe.utils.now_datetime()

	def wipe_since_setup(self, *doctypes):
		"""Delete rows of these doctypes that this test created, and nothing older.

		The five files that clean up after service-made documents used to do this instead:

		    for name in frappe.get_all(dt, pluck="name"):

		which is every row of that doctype on the site, not the test's own. On a disposable
		site that is merely wrong; run once against a site somebody is working on - which is
		what happened - and it destroys their records. `creation` is the one thing every
		document has and no service forgets to set.

		No commit. Committing inside a test defeats FrappeTestCase's per-class rollback, which
		is how a committed Payment Entry ended up pointing at a Customer that had been rolled
		back out from under it.
		"""
		for doctype in doctypes:
			if not frappe.db.exists("DocType", doctype):
				continue
			for name in frappe.get_all(doctype, filters={"creation": [">=", self._began]},
			                           pluck="name"):
				try:
					if frappe.get_meta(doctype).is_submittable:
						if frappe.db.get_value(doctype, name, "docstatus") == 1:
							doc = frappe.get_doc(doctype, name)
							doc.flags.ignore_permissions = True
							doc.cancel()
					frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
				except Exception:
					# A row another test still holds a link to comes round again on its own
					# teardown. Refusing here would strand the rest of this list.
					pass

	# Where a master that will not delete can be switched off instead, so it cannot clash with
	# the next test. A season still booking, or a price list still enabled, is worse left behind
	# than left behind and closed.
	QUIET_FIELDS = ("is_active", "enabled", "disabled")

	def cleanup_targets(self):
		"""Rows this fixture made that `track` never saw, oldest first.

		A fixture that creates documents through a *service* has no list of their names, so it
		finds them by filter. Those rows belong in the same ordered pass as everything else -
		**a subclass that deletes them in its own `tearDown` does so before the base has
		cleaned up, and that is how a Delivery Note came to be stranded on a Sales Order its
		FieldMate Order had already cancelled.** Return them here instead.

		Oldest first, like `track`'s own list, because the pass walks it backwards.
		"""
		return []

	def tearDown(self):
		# Oldest first: what a fixture found by filter is the root of what it built, and the
		# pass below walks this list backwards so the leaves come down before the trunk.
		targets = list(self.cleanup_targets()) + list(self._created)
		self.release(targets)
		frappe.db.commit()
		super().tearDown()

	def release(self, targets):
		"""Cancel and delete these rows, newest first, retrying while anything still moves.

		**Newest first** because a document depends on the ones made before it: a Delivery Note
		has to be cancelled before its Sales Order, and ERPNext refuses the other way round. That
		is ERPNext's own rule rather than ours - it refuses the same thing in Desk - and it is
		only about taking a test's fixtures down. Nothing in the selling path runs backwards.

		**Retrying** because one pass cannot always be enough: a row can refuse to go while
		something later in the list still links to it, and that something is deleted on this very
		pass. So the list is walked again until a pass clears nothing new, at which point
		whatever is left is genuinely stuck.

		**Never stranding the rest.** This used to catch only `DoesNotExistError`, so the first
		document ERPNext refused ended the loop and everything after it leaked - which is how a
		failing dispatch test left eleven price lists on the site and a later run started failing
		with "these have no price yet", eighty-nine tests away from the cause.
		"""
		pending = list(targets)
		while pending:
			stuck = []
			for doctype, name in reversed(pending):
				if not self._drop(doctype, name):
					stuck.append((doctype, name))
			if len(stuck) == len(pending):
				break
			# Back into oldest-first order for the next walk.
			pending = list(reversed(stuck))

		for doctype, name in pending:
			self._quieten(doctype, name)

	def _drop(self, doctype: str, name: str) -> bool:
		"""Cancel if submitted, then delete. True when the row is gone or was never there."""
		try:
			if not frappe.db.exists(doctype, name):
				return True
			if frappe.get_meta(doctype).is_submittable:
				if frappe.db.get_value(doctype, name, "docstatus") == 1:
					doc = frappe.get_doc(doctype, name)
					doc.flags.ignore_permissions = True
					doc.cancel()
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			return True
		except Exception:
			# Said nowhere and raised nowhere: a row that will not go is the ordinary end of a
			# test whose documents another test still links to, and `release` comes back to it.
			return False

	def _quieten(self, doctype: str, name: str) -> None:
		"""Switch off what would not delete, so the next test does not collide with it.

		A FieldMate Season left behind is still booking, and the next `make_season` is refused
		for overlapping with it - a failure in a test that has nothing to do with seasons. A
		Price List left enabled changes which list a fixture prices into. Closing them costs
		nothing and removes both.
		"""
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			return

		for field in self.QUIET_FIELDS:
			if not meta.has_field(field):
				continue
			off = 1 if field == "disabled" else 0
			try:
				frappe.db.set_value(doctype, name, field, off, update_modified=False)
			except Exception:
				pass
