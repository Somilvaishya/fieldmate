"""Does this scoped master apply to this shop?

Checklist templates, must-sell lists, catalogues and schemes are all scoped the same way: by
territory, channel and outlet class, where a blank field means "everywhere". This is the one
place that comparison lives, because getting it subtly wrong in four places is how a rep ends up
answering the wrong survey at the right shop.

Territory is a tree, and that is the part worth being careful about. A template scoped to *North*
must apply to a shop in *North / Delhi / South Delhi*. Comparing the two names for equality would
silently exclude every shop that is not pinned to the exact node a planner happened to pick -
and because Frappe fills an empty `territory` field from the session's own default, the node a
planner "picks" is very often the root they never chose at all.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate


def territory_covers(scope: str | None, territory: str | None) -> bool:
	"""True when `scope` is the shop's territory or any ancestor of it.

	A blank scope means everywhere. So does the root, which is simply the ancestor of everything.
	"""
	if not scope:
		return True
	if not territory:
		# A shop with no territory cannot be shown to be inside a narrower scope.
		return False
	if scope == territory:
		return True

	bounds = frappe.db.get_value("Territory", scope, ["lft", "rgt"], as_dict=True)
	mine = frappe.db.get_value("Territory", territory, "lft")
	if not bounds or mine is None:
		return False
	return bounds.lft <= mine <= bounds.rgt


def narrows_territory(territory: str | None) -> bool:
	"""Whether naming this territory actually restricts a master to anything less than everywhere.

	The root does not. It is the ancestor of every node, so a master "scoped" to it reaches the
	same shops as one scoped to nothing at all - and the root is precisely what Frappe writes
	when nobody picked a territory, because an empty Link is filled from the session defaults of
	whoever happened to save the form. Anything weighing one master against another by how
	narrowly it was scoped has to discount that row rather than believe it, or a national
	catalogue somebody saved from a Delhi login outranks the regional one written on purpose.
	"""
	if not territory:
		return False
	return bool(frappe.db.get_value("Territory", territory, "parent_territory"))


def applies_to_outlet(scoped, outlet) -> bool:
	"""Whether a scoped master covers this shop on territory, channel and class."""
	if not territory_covers(scoped.get("territory"), outlet.territory):
		return False

	channel = scoped.get("channel")
	if channel and channel != outlet.channel:
		return False

	outlet_class = scoped.get("outlet_class")
	if outlet_class and outlet_class != outlet.outlet_class:
		return False

	return True


def is_effective_on(scoped, date) -> bool:
	"""Whether a scoped master is live on a date, for the ones carrying a validity window."""
	on = getdate(date)
	valid_from = scoped.get("valid_from") or scoped.get("effective_from")
	valid_to = scoped.get("valid_to")
	if valid_from and getdate(valid_from) > on:
		return False
	if valid_to and getdate(valid_to) < on:
		return False
	return True
