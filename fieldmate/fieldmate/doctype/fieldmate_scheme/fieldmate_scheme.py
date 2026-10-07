import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from fieldmate.services import scope
from fieldmate.services import settings as settings_service
from fieldmate.services.visit import is_on_beat

# Each kind of benefit is granted through exactly one column, and the engine reads only that one.
# A row naming one kind while carrying a number in another's column is perfectly readable to the
# manager who typed it and meaningless to everything downstream, so the two are tied together here.
BENEFIT_COLUMNS = {
	"Free Goods": "free_qty",
	"Percent Discount": "discount_pct",
	"Value Discount": "discount_amount",
	"Rate Off": "rate_off",
	"Incentive": "incentive_amount",
}

COLUMN_LABELS = {
	"free_qty": "Free Qty",
	"discount_pct": "Discount %",
	"discount_amount": "Value Discount",
	"rate_off": "Rate Off",
	"incentive_amount": "Incentive",
}

KIND_OF_COLUMN = {column: kind for kind, column in BENEFIT_COLUMNS.items()}

SCOPE_DIMENSIONS = ("territory", "channel", "outlet_class", "beat", "outlet", "distributor")


class FieldMateScheme(Document):
	"""A trade offer as a manager writes it: rupees, cases, item groups and territories.

	Nothing in here is what the engine actually runs. The compiler resolves the scope, expands the
	groups to item codes, turns cases into base units and rupees into paise, and emits a flat spec
	the phone caches. This document is the human side of that, and everything the compiler is
	entitled to assume about it has to be true before it is saved - a spec compiled from slabs that
	overlap or a benefit whose amount sits in the wrong column produces a discount on the phone and
	a different one on the invoice, which is exactly the divergence a rep never recovers from once
	a shopkeeper has caught it.
	"""

	def validate(self):
		self.set_defaults()
		self.validate_period()
		self.validate_stacking()
		self.validate_scope()
		self.validate_items()
		self.fill_case_sizes()
		self.validate_slabs()
		self.validate_benefits()
		self.bump_spec_version()

	def set_defaults(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {}, "name")
		if not self.currency and self.company:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")
		if not cint(self.spec_version):
			self.spec_version = 1
		self.slab_count = len({cint(row.slab_idx) for row in self.slabs or []})

	def validate_period(self):
		if self.valid_from and self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(
				frappe._("This scheme ends on {0}, before it starts on {1}. It would never be "
				         "live for a single day.").format(self.valid_to, self.valid_from)
			)

	def validate_stacking(self):
		self.stack_group = (self.stack_group or "").strip()
		if self.stacking == "Best Of Group" and not self.stack_group:
			frappe.throw(
				frappe._("Best Of Group keeps only the richest scheme inside a group, so this one "
				         "needs a group to compete in. Give it the same Stack Group as the schemes "
				         "it is meant to be weighed against.")
			)

	def validate_scope(self):
		narrowed = False
		for row in self.scopes or []:
			narrows = row_narrows_anything(row)
			if cint(row.is_excluded) and not narrows:
				frappe.throw(
					frappe._("Scope row {0} excludes everywhere, which switches the scheme off "
					         "without saying so. Name what it excludes, or delete the row.")
					.format(row.idx)
				)
			if narrows and not cint(row.is_excluded):
				narrowed = True

		self.applies_everywhere = 0 if narrowed else 1

	def validate_items(self):
		if self.measured_over == "Item Set" and not self.items:
			frappe.throw(
				frappe._("This scheme measures its slabs over a set of items but lists none, so "
				         "no cart would ever qualify. Add the items, or measure it over the whole "
				         "order instead.")
			)

		seen = set()
		for row in self.items or []:
			named = [field for field in ("item_code", "item_group", "brand") if row.get(field)]
			if not named:
				frappe.throw(
					frappe._("Row {0} names no item, item group or brand, so there is nothing for "
					         "a cart to qualify on.").format(row.idx)
				)
			if len(named) > 1:
				frappe.throw(
					frappe._("Row {0} names both {1} and {2}. A row has to say exactly one of item, "
					         "item group or brand - with two, nobody reading this months later can "
					         "tell which one the offer was written for.")
					.format(row.idx, frappe.bold(row.get(named[0])), frappe.bold(row.get(named[1])))
				)

			key = (named[0], row.get(named[0]))
			if key in seen:
				frappe.throw(
					frappe._("Row {0}: {1} is already in the qualifying list. Listed twice, its "
					         "quantity would count twice towards the slab.")
					.format(row.idx, frappe.bold(row.get(named[0])))
				)
			seen.add(key)

	def fill_case_sizes(self):
		"""Look the case size up from the Item, so a manager only ever picks the UOM.

		The compiler turns "2 cases" into a count of base units before the spec ever leaves the
		server, because the engine is handed numbers that already agree and never divides by a
		conversion factor (ADR-021). It reads that factor from here. Asking a manager to type 12
		next to a UOM the Item master already knows is how the two drift apart, and a scheme that
		disagrees with its own item about what a case holds under-rewards every shop that buys it.

		A factor typed by hand is left alone: somebody overrode it on purpose.
		"""
		for row in self.items or []:
			if not row.case_uom or flt(row.conversion_factor) > 0:
				continue
			if not row.item_code:
				# A group or brand row has no single Item to ask, and picking one member's pack
				# size to speak for the rest is exactly the ambiguity `case_factor` refuses.
				continue
			factor = frappe.db.get_value(
				"UOM Conversion Detail",
				{"parent": row.item_code, "parenttype": "Item", "uom": row.case_uom},
				"conversion_factor",
			)
			if not factor:
				frappe.throw(
					frappe._("Row {0}: {1} has no {2} conversion on its Item master, so nobody "
					         "knows how many pieces one holds. Add the UOM to the item first.")
					.format(row.idx, frappe.bold(row.item_code), frappe.bold(row.case_uom))
				)
			row.conversion_factor = flt(factor)

	def validate_slabs(self):
		"""Slabs ascend and never overlap, so exactly one of them can match any cart.

		The engine takes the highest slab that matches, and that is a safety net rather than a
		policy - by the time a spec is compiled, overlap has to be impossible. Two slabs that both
		match leave the rep quoting one tier and the invoice printing another, and the shopkeeper
		is the one who finds out.
		"""
		if cint(self.is_active) and not self.slabs:
			frappe.throw(
				frappe._("An active scheme with no slabs grants nothing. Add a slab, or leave the "
				         "scheme inactive until the offer is decided.")
			)

		bands = {}
		for row in self.slabs or []:
			number = cint(row.slab_idx)
			if number < 1:
				frappe.throw(
					frappe._("Row {0}: every benefit belongs to a slab. Number the slabs from 1 "
					         "upwards, and give rows that make up one combo the same number.")
					.format(row.idx)
				)

			if cint(row.is_open_ended):
				# A Float is never null in Frappe, so a leftover ceiling on an open-topped slab
				# would compile to a real number and quietly cap the top tier.
				row.to_value = 0

			band = bands.get(number)
			if band is None:
				bands[number] = {
					"from": flt(row.from_value),
					"to": flt(row.to_value),
					"open": cint(row.is_open_ended),
					"row": row.idx,
				}
				continue

			same_band = (
				flt(row.from_value) == band["from"]
				and flt(row.to_value) == band["to"]
				and cint(row.is_open_ended) == band["open"]
			)
			if not same_band:
				frappe.throw(
					frappe._("Rows {0} and {1} are both slab {2} but cover different ranges. Rows "
					         "sharing a slab number are one slab granting a combo, so they have to "
					         "open and close together.").format(band["row"], row.idx, number)
				)

		self.validate_band_order(bands)

	def validate_band_order(self, bands: dict):
		previous_number = None
		previous = None
		for number in sorted(bands):
			band = bands[number]
			if not band["open"] and band["to"] <= band["from"]:
				frappe.throw(
					frappe._("Slab {0} runs from {1} to {2} and so matches nothing. Give it a "
					         "ceiling above its floor, or tick Open Top if it is the last tier.")
					.format(number, band["from"], band["to"])
				)

			if previous is not None:
				if previous["open"]:
					frappe.throw(
						frappe._("Slab {0} has no ceiling, so slab {1} can never be reached. The "
						         "open-topped slab has to be the highest one.")
						.format(previous_number, number)
					)
				if band["from"] <= previous["to"]:
					frappe.throw(
						frappe._("Slab {0} starts at {1}, inside slab {2} which runs to {3}. A cart "
						         "that lands in two slabs at once is an offer nobody can explain "
						         "across a counter.")
						.format(number, band["from"], previous_number, previous["to"])
					)

			previous_number = number
			previous = band

	def validate_benefits(self):
		for row in self.slabs or []:
			owned = BENEFIT_COLUMNS.get(row.benefit_kind)
			if not owned:
				continue

			filled = [column for column in BENEFIT_COLUMNS.values() if flt(row.get(column)) > 0]
			strays = [column for column in filled if column != owned]

			if flt(row.get(owned)) <= 0:
				self.throw_empty_benefit(row, owned, strays)
			if strays:
				frappe.throw(
					frappe._("Row {0} grants {1}, so only {2} may carry a number - clear {3}. One "
					         "row is one benefit; add another row with the same slab number to "
					         "grant both.")
					.format(row.idx, row.benefit_kind, COLUMN_LABELS[owned],
					        ", ".join(COLUMN_LABELS[column] for column in strays))
				)

			if row.benefit_kind == "Free Goods" and not row.free_item:
				frappe.throw(
					frappe._("Row {0} gives goods away but names no item. A rep cannot hand a "
					         "shopkeeper a quantity of nothing.").format(row.idx)
				)
			if row.benefit_kind == "Percent Discount" and flt(row.discount_pct) > 100:
				frappe.throw(
					frappe._("Row {0} gives away {1}%, which is more than the line is worth.")
					.format(row.idx, flt(row.discount_pct))
				)
			if row.per == "Multiple" and flt(row.from_value) <= 0:
				frappe.throw(
					frappe._("Row {0} grants its benefit per multiple of the slab, which counts how "
					         "many times the floor was crossed. A slab starting at zero has no "
					         "floor to count.").format(row.idx)
				)

	def throw_empty_benefit(self, row, owned: str, strays: list):
		if len(strays) == 1:
			frappe.throw(
				frappe._("Row {0} grants {1}, but {2} is empty and {3} carries {4}. Fill {2}, or "
				         "change the benefit to {5}.")
				.format(row.idx, row.benefit_kind, COLUMN_LABELS[owned], COLUMN_LABELS[strays[0]],
				        flt(row.get(strays[0])), KIND_OF_COLUMN[strays[0]])
			)
		frappe.throw(
			frappe._("Row {0} grants {1}, but {2} is empty. A benefit worth nothing is a tier the "
			         "rep quotes and the invoice ignores.")
			.format(row.idx, row.benefit_kind, COLUMN_LABELS[owned])
		)

	def bump_spec_version(self):
		"""Raise the version only when the rules a phone prices against actually changed.

		Rewording the pitch or correcting a remark must not tell every device in the field that its
		cached spec is stale. A pull costs a rep minutes on a market uplink, and a version that
		moves for cosmetic edits is one nobody trusts when it moves for a real one.
		"""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if not before:
			return
		if self.fingerprint() != self.fingerprint(before):
			self.spec_version = cint(before.spec_version) + 1

	def fingerprint(self, doc=None) -> tuple:
		doc = doc or self
		return (
			doc.basis, doc.basis_uom, doc.measured_over, doc.stacking, doc.stack_group,
			cint(doc.priority), cint(doc.is_active), doc.valid_from, doc.valid_to,
			flt(doc.budget_amount), doc.on_exhaust,
			tuple((row.item_code, row.item_group, row.brand, row.case_uom, flt(row.conversion_factor))
			      for row in doc.items or []),
			tuple((row.territory, row.channel, row.outlet_class, row.beat, row.outlet,
			       row.distributor, cint(row.is_excluded)) for row in doc.scopes or []),
			tuple((cint(row.slab_idx), flt(row.from_value), flt(row.to_value),
			       cint(row.is_open_ended), row.benefit_kind, row.per, row.free_item,
			       flt(row.free_qty), row.free_uom, flt(row.discount_pct),
			       flt(row.discount_amount), flt(row.rate_off), flt(row.incentive_amount))
			      for row in doc.slabs or []),
		)

	def is_live_on(self, date) -> bool:
		return bool(cint(self.is_active)) and scope.is_effective_on(self, date)

	def books_in(self, date) -> bool:
		"""Was the order taken inside this scheme's early-booking window?

		A different question from `is_live_on`, which asks whether the offer exists at all. A
		season scheme is live from November to March because that is when it is billed, and
		rewards only the orders booked in November.

		Read with `.get`, like `applies_to` - on a site where the code has landed and the
		migration has not run, the columns do not exist and reading them as attributes fails
		every order on that site from inside the pricing path.
		"""
		opens, closes = self.get("booking_from"), self.get("booking_to")
		if not opens and not closes:
			return True
		on = getdate(date)
		if opens and on < getdate(opens):
			return False
		return not (closes and on > getdate(closes))

	def advance_met(self, season_advance_pct) -> bool:
		"""Does the deal behind this order carry the advance this offer asks for?

		Measured against the **season's** advance, not against what has been collected. The order
		is priced the moment it is taken, when nothing has been paid - so reading what is in hand
		would mean no early-booking offer ever fired at the counter, which is the one place it
		has to. A booking cannot be released without its season's advance either, so by the time
		anything is billed the two come to the same thing.

		A scheme asking for an advance therefore cannot reach an order that is not a booking.
		"""
		asked = flt(self.get("requires_advance_pct"))
		if not asked:
			return True
		return flt(season_advance_pct) >= asked

	def covers_sale(self, kind: str | None) -> bool:
		"""Whether this scheme is for this kind of sale at all.

		Asked before the scope rows, because it is a different question from *where*: a scheme
		can be scoped to the whole of North and still be the wrong scheme for a distributor's own
		purchase. A retailer offer firing on a primary order is trade spend nobody budgeted, and
		it would do so silently - the engine would simply find a scheme that matched everywhere.

		`None` means the caller did not say, which is every caller that predates primary orders,
		so it reads as a retailer order.

		Read with `.get`, not as an attribute. On a site where the code has landed and the
		migration has not yet run, the field does not exist and `self.applies_to` raises
		`AttributeError` - from inside the pricing path, so *every* order on that site fails
		until somebody runs `bench migrate`. Found by the Phase 1 gate on a site one migration
		behind, which is precisely the window a deploy opens.
		"""
		mine = self.get("applies_to") or "Secondary"
		# A booking is a primary sale, so a scheme written for Primary covers it. `applies_to`
		# deliberately does NOT grow a Booking option: a scheme that should run only during a
		# season says so with its own validity dates, which it already has, rather than with a
		# third scope nobody can tell apart from the second.
		asked = "Primary" if kind == settings_service.BOOKING else (kind or "Secondary")
		return mine == "Both" or mine == asked

	def covers_outlet(self, outlet) -> bool:
		"""Whether this scheme's scope reaches a particular shop.

		Scope is a table rather than one set of fields so a manager can name two districts without
		writing two schemes. With no include row it reaches everywhere, and an exclude row carves
		back out of that - the only way to write "all of North except modern trade" without listing
		every beat in North.
		"""
		includes = [row for row in self.scopes or [] if not cint(row.is_excluded)]
		excludes = [row for row in self.scopes or [] if cint(row.is_excluded)]

		if includes and not any(scope_row_matches(row, outlet) for row in includes):
			return False
		return not any(scope_row_matches(row, outlet) for row in excludes)


def row_narrows_anything(row) -> bool:
	"""Whether a scope row restricts the scheme to anything less than everywhere.

	A row holding nothing but the root territory does not, and that is precisely the row Frappe
	writes when nobody picked one: an empty Territory link is filled from the session defaults of
	whoever opened the form, so a scheme nobody scoped arrives looking scoped. Checklist templates
	presented that as "the survey never appears", with no error anywhere to explain it.
	"""
	if any(row.get(field) for field in SCOPE_DIMENSIONS if field != "territory"):
		return True
	if not row.territory:
		return False
	return bool(frappe.db.get_value("Territory", row.territory, "parent_territory"))


def scope_row_matches(row, outlet) -> bool:
	"""Whether one scope row covers this shop, on every dimension it names."""
	if not scope.territory_covers(row.territory, outlet.territory):
		return False
	if row.channel and row.channel != outlet.channel:
		return False
	if row.outlet_class and row.outlet_class != outlet.outlet_class:
		return False
	if row.outlet and row.outlet != outlet.name:
		return False
	if row.distributor and row.distributor != outlet.distributor:
		# A distributor profile is named after its customer, so the scope row and the shop's
		# billing party are the same string rather than two that have to be joined.
		return False
	if row.beat and not (row.beat == outlet.primary_beat or is_on_beat(row.beat, outlet.name)):
		# A shop is served on its primary beat and often walked on a second one as well. Matching
		# only the primary would drop the scheme on exactly the days a relief rep covers the route.
		return False
	return True
