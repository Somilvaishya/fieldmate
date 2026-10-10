"""A selling season — Holi, Diwali — and the dates that make an order a booking of it.

The one new master of Phase 2, and deliberately the only one. Everything else a season needs
already exists: the booking is a FieldMate Order, the advance and the post-dated cheque are
FieldMate Collections, the payment schedule is ERPNext's own, and the stock set aside is an
ERPNext Stock Reservation Entry.

**A season is dates, a price list and a percentage.** It decides nothing by itself. A primary
order dated inside the booking window of its company's active season is a booking of that season;
that is the whole rule, and it lives in `services/season.py` next to the resolver that decides
every other kind of sale.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class FieldMateSeason(Document):
	def validate(self):
		self.check_windows()
		self.check_overlap()
		self.default_the_cutoff()

	def check_windows(self):
		"""Dates that cannot be met are caught here rather than by an order that will not book."""
		if getdate(self.booking_to) < getdate(self.booking_from):
			frappe.throw(frappe._("Booking closes before it opens."))
		if getdate(self.delivery_to) < getdate(self.delivery_from):
			frappe.throw(frappe._("Delivery ends before it starts."))

		# Not a hard rule but a real mistake: a season whose deliveries start before its book
		# opens is a season nobody is booking in advance, which is what a season is for.
		if getdate(self.delivery_from) < getdate(self.booking_from):
			frappe.throw(frappe._(
				"Delivery starts before booking opens. A season is booked in advance of its "
				"deliveries - check the dates."))

		if self.change_cutoff and getdate(self.change_cutoff) < getdate(self.booking_from):
			frappe.throw(frappe._("Changes would close before booking opens."))

	def default_the_cutoff(self):
		"""Blank means the book shutting is also the last change.

		Stored rather than worked out on every read: a cutoff is quoted to a distributor, and a
		figure nobody can point at on the document is a figure that gets argued about.
		"""
		if not self.change_cutoff:
			self.change_cutoff = self.booking_to

	def check_overlap(self):
		"""Two active seasons booking at the same time for one company is ambiguous.

		`services/season.open_for` would have to pick one, and any rule for picking is the
		configuration language this design is trying not to have. So it is refused at the master
		instead, where somebody can see both documents.
		"""
		if not self.is_active:
			return

		clash = frappe.db.sql("""
			select name from `tabFieldMate Season`
			where company = %(company)s and is_active = 1 and name != %(name)s
			  and booking_from <= %(to)s and booking_to >= %(from)s
			limit 1
		""", {"company": self.company, "name": self.name or "",
		      "from": self.booking_from, "to": self.booking_to})

		if clash:
			frappe.throw(frappe._(
				"{0} is already booking for {1} over these dates. Two seasons open at once would "
				"leave it undecided which one an order belongs to - close that one, or move "
				"these dates."
			).format(clash[0][0], self.company))

	def books_on(self, on) -> bool:
		"""Is an order dated `on` a booking of this season?"""
		return bool(self.is_active) and getdate(self.booking_from) <= getdate(on) <= getdate(self.booking_to)

	def may_change_on(self, on) -> bool:
		return getdate(on) <= getdate(self.change_cutoff or self.booking_to)

	def delivers_on(self, on) -> bool:
		return getdate(self.delivery_from) <= getdate(on) <= getdate(self.delivery_to)
