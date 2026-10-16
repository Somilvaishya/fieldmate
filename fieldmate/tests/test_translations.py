"""`translations/hi.csv` against what the server can actually say.

The cost of keying a translation on the English sentence is that editing the sentence orphans its
translation silently: the code keeps working, in English, and nobody finds out. The handset half
of #13 is kept honest by a test that reads the screens; this is the same test for the server.

Extraction uses `ast`, not a regex, for one reason that matters in this codebase. Long messages
are written as Python's implicit concatenation -

    frappe._("A sentence that runs on "
             "across two lines.")

- and the key at runtime is the joined string. A regex sees the first fragment and would pass a
CSV that never matches anything, which is exactly the fault the handset's guard forbids.

Nothing here needs a site. It reads files.
"""

from __future__ import annotations

import ast
import csv
import os
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", "tests", "public", "node_modules"}

# Strings handed to `_()` as a module constant rather than a literal. The parser cannot see
# through the name, so they are named here. Frappe resolves them at call time, which is the
# correct pattern server-side - unlike the handset, where a module-level const freezes.
VIA_CONSTANT = (
	"This link is not available.",
)


def _translatable_calls(tree):
	"""Every `_()` / `frappe._()` call in one parsed module."""
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call) or not node.args:
			continue
		func = node.func
		if (isinstance(func, ast.Name) and func.id == "_") or (
			isinstance(func, ast.Attribute) and func.attr == "_"
		):
			yield node


def what_the_server_can_say() -> tuple[set[str], list[str]]:
	"""Every literal the app passes to `_()`, and the call sites it could not resolve."""
	strings: set[str] = set(VIA_CONSTANT)
	unresolved: list[str] = []

	for root, dirs, files in os.walk(APP):
		dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
		for name in sorted(files):
			if not name.endswith(".py"):
				continue
			path = os.path.join(root, name)
			rel = os.path.relpath(path, APP)
			tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
			for node in _translatable_calls(tree):
				arg = node.args[0]
				if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
					strings.add(arg.value)
				else:
					unresolved.append(f"{rel}:{node.lineno}")

	return strings, unresolved


def catalogue(lang: str = "hi") -> dict[str, str]:
	path = os.path.join(APP, "translations", f"{lang}.csv")
	rows = list(csv.reader(open(path, encoding="utf-8", newline="")))
	return {r[0]: r[1] for r in rows if len(r) >= 2}


class TestTheHindiCatalogue(unittest.TestCase):
	def setUp(self):
		self.said, self.unresolved = what_the_server_can_say()
		self.have = catalogue()

	def test_every_message_has_hindi(self):
		"""Named, not counted, so a failure says which sentence to go and translate."""
		missing = sorted(s for s in self.said if not self.have.get(s, "").strip())
		self.assertEqual(missing, [], f"{len(missing)} message(s) with no Hindi")

	def test_the_catalogue_carries_nothing_stale(self):
		"""A row matching no message is one somebody keeps maintaining for a sentence that is
		gone. Not fatal in production, but it is how a catalogue stops being trusted."""
		stale = sorted(set(self.have) - self.said)
		self.assertEqual(stale, [], f"{len(stale)} row(s) match no message in the app")

	def test_the_placeholders_survive_translation(self):
		"""`{0}` in the English and not in the Hindi is a message that throws `IndexError`
		the moment it is formatted - and only for the Hindi rep, which is the worst way to
		find out."""
		wrong = []
		for english, hindi in self.have.items():
			for n in range(6):
				token = f"{{{n}}}"
				if (token in english) != (token in hindi):
					wrong.append(f"{token} in {english[:60]!r}")
		self.assertEqual(wrong, [])

	def test_nothing_is_translated_to_itself(self):
		"""An entry whose Hindi is the English is either a placeholder somebody forgot or a
		word that genuinely does not translate. The second kind is listed, so the first kind
		cannot hide among them."""
		keeps_english = {
			"UPI", "DD", "GST", "MRP", "POSM", "Km", "Date", "Name", "Value",
		}
		same = sorted(
			e for e, h in self.have.items() if e == h and e not in keeps_english
		)
		self.assertEqual(same, [])

	def test_every_call_site_passes_something_resolvable(self):
		"""A call with no constant key can never be translated. Three are deliberate - a
		DocType name and two module constants - and anything beyond that is worth seeing."""
		self.assertLessEqual(
			len(self.unresolved), 3,
			f"unresolvable `_()` calls: {self.unresolved}",
		)
