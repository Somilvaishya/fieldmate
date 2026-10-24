"""One shape for every list this app hands to a screen.

Until this existed, thirteen endpoints took a `limit` and the rest took nothing. A `limit` is a
cap, not a page: it tells the server how much to stop at and tells the screen nothing at all. A
rep with two hundred orders got fifty, no way to ask for the rest, and **no sign that there was a
rest** - the list simply ended. That is the worst way for a limit to fail, because the screen looks
complete.

So a list answers three questions now: here is a page, here is how many there are altogether, and
here is whether asking again would get you more.

**Additive, never a reshape.** `api/_base` says the envelope is a contract and that old builds stay
in the field for weeks after a deploy, so the list keeps its own key and its own type - `orders` is
still a list of orders - and the counts arrive beside it. A build that has never heard of paging
reads exactly what it always read.

**Counts are permission-aware.** Every list here goes through `frappe.get_list` with a `user`, so a
rep sees their own territory and nothing else. A count that skipped that would quietly tell a rep
how many shops exist on the whole site, which is both wrong and a disclosure.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

# What a screen gets when it asks for nothing in particular.
DEFAULT_LIMIT = 50

# What it gets however much it asks for. A page is a round trip over a market uplink; a rep asking
# for five thousand outlets is a screen that never paints, so the ceiling is the server's to keep.
MAX_LIMIT = 200


def window(start=None, limit=None, default: int = DEFAULT_LIMIT,
           maximum: int = MAX_LIMIT) -> tuple[int, int]:
	"""What the caller asked for, clamped into something worth asking the database.

	Everything arrives over HTTP as a string, and some of it arrives as nonsense. A negative start
	is an offset the database refuses; a limit of zero is a page nobody can read; a limit of ten
	thousand is a screen that never paints. None of those is worth an error to the rep - the
	sensible neighbouring value is.
	"""
	try:
		start = cint(start)
	except (TypeError, ValueError):
		start = 0
	try:
		limit = cint(limit)
	except (TypeError, ValueError):
		limit = 0

	return max(0, start), max(1, min(limit or default, maximum))


def count(doctype: str, filters=None, or_filters=None, user: str | None = None) -> int:
	"""How many rows this user may see, with the same filters the page was read with.

	`frappe.get_list` with an aggregate rather than `frappe.db.count`, because `db.count` does not
	apply permissions: on a territory-scoped doctype it would answer with the whole site.
	"""
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		or_filters=or_filters,
		fields=["count(name) as total"],
		user=user or frappe.session.user,
		ignore_permissions=False,
	)
	return cint(rows[0].get("total")) if rows else 0


def envelope(rows: list, total: int, start: int, limit: int) -> dict:
	"""The counts that travel beside a page.

	`has_more` is computed rather than inferred from a full page. "I received fifty, so there are
	probably more" is wrong exactly when the total is fifty, and a screen that offers a Load more
	button that returns nothing is a screen that looks broken.
	"""
	total = cint(total)
	return {
		"total": total,
		"start": cint(start),
		"limit": cint(limit),
		"has_more": cint(start) + len(rows or []) < total,
	}
