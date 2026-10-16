from frappe.model.document import Document


class FieldMateOrder(Document):
	"""An order a rep took standing in a shop, which is a proposal and not yet a commitment.

	It is captured on whatever prices, schemes and credit figures the phone had cached, possibly
	hours earlier and possibly in a market with no signal at all. That is why it is its own
	document rather than a Sales Order: every offline retry, every credit argument and every
	approval round-trip happens here.

	And it ends here. An order booked at a shop is a secondary sale (ADR-023) - it routes to the
	distributor, who bills that shop out of stock they already own, so nothing about it reaches
	the company order book or the ledger. What the company eventually sells is the distributor's
	own primary order on us, which is a different document raised by a different party. A Sales
	Order appears against this one only where the seller is genuinely us: a van sale, or an
	outlet billed direct.

	Two things about this document are worth holding on to.

	Every total on it is the server's. The phone works the same schemes out at the counter because
	the rep has to say a number out loud, and that number is kept in `proposed_net_total` - but
	the figures the business acts on are recomputed here from the engine and overwrite what
	arrived. The two agreeing is not something to be trusted; it is something to be checked, and
	`totals_match` is the record of the check.

	Nothing about it is refused in the field. A credit breach, an order over the value threshold,
	a discount past the ceiling - each is recorded, flagged and routed to whoever can decide.
	A rep blocked in front of a shopkeeper does not book a smaller order; he stops using the app,
	and then there is no data at all.

	The recomputation, the credit check and the hand-off to the distributor's queue live in the
	order service. This controller only describes what the document is.
	"""

	def validate(self):
		"""Reprice from the server's own figures, whatever the phone proposed.

		This lives on the controller and not only in the service because an order captured with
		no signal arrives through `sync.push`, which inserts the document directly and never
		calls a service at all. Anything that ran only in the service would simply not happen
		for the offline majority - which is exactly how a day once landed with every figure
		at zero for a rep who had worked a whole day in a village.
		"""
		from fieldmate.services import order as order_service

		self.settle_the_party()
		if self.items:
			order_service.price(self)
		# After the repricing, because `price` is what decides this is a booking at all. Refused
		# here rather than in the service for the reason the repricing is: an order amended
		# through the offline sync push never passes through a service.
		#
		# Not guarded on `is_new`. An **amendment** is a brand new document carrying
		# `amended_from`, so that guard excluded the one case this rule is for, while catching
		# the submit of an ordinary new booking - which is how a season with an early change
		# cutoff came to refuse every booking taken in its last few open days.
		order_service.assert_may_amend(self)

	def settle_the_party(self):
		"""Exactly one party, and `party_type` agreeing with it.

		An order is for a shop or for a party we bill ourselves, never both and never neither.
		The check is here rather than in the service for the reason the repricing is: an order
		captured with no signal arrives through `sync.push`, which inserts the document directly
		and calls no service at all.

		`party_type` is inferred where a caller did not send one, because every order written
		before this field existed has an outlet and no idea that it needed to say so, and so does
		every build of the phone that is already in somebody's pocket.
		"""
		import frappe

		if not self.party_type:
			self.party_type = "Customer" if (self.customer and not self.outlet) else "Outlet"

		if self.party_type == "Customer":
			self.outlet = None
			if not self.customer:
				frappe.throw(frappe._("A primary order has to say which party it is for."))
		else:
			self.customer = None
			if not self.outlet:
				frappe.throw(frappe._("An order has to say which shop it is for."))

	def on_submit(self):
		"""Hand the order to whoever actually fulfils it. See ADR-023."""
		from fieldmate.services import order as order_service

		# Before routing, so that whatever the order becomes downstream is built on rates that
		# have stopped moving. A booking taken in November is delivered in February off a season
		# list that will have been corrected twice by then, and the party is owed the November
		# price it was read out.
		order_service.lock_rates(self)
		order_service.route(self)

	def before_update_after_submit(self):
		"""A submitted booking changing after its season's cutoff.

		`save()` on a submitted document does **not** run `validate` - it takes the
		update-after-submit path - so the check in `validate` never saw this case at all. The
		fields a FieldMate Order allows after submit are small (the depot's reference, the
		approval remark), but "the book has stopped moving" has to mean the book has stopped
		moving.
		"""
		from fieldmate.services import order as order_service

		order_service.assert_may_amend(self)

	def on_cancel(self):
		from fieldmate.services import order as order_service

		order_service.withdraw(self)
