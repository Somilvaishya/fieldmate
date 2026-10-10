"""Tax on an order: what the bill will come to, computed once and the same way twice.

**Why a secondary order carries tax at all.** The distributor bills the shop and our books never
see that sale (ADR-023), so FieldMate posts nothing here and charges nobody. But the cart's whole
reason for existing is in `stores/order.js`: *the number the rep says out loud has to be the
number on the invoice the distributor raises that evening*. That invoice carries GST. A rep who
quotes the net and a shopkeeper who receives a bill eighteen per cent higher are having an
argument that nobody can settle, over a figure the app had and did not show.

So the tax here is the distributor's, applied with the distributor's own templates, stated as
**expected** and posted nowhere. `FieldMate Order.tax_total` used to be pinned at zero with a
comment saying a number we have no authority over should not be pretended to - which was right
about authority and wrong about silence. We have no authority to *charge* it; we have every
reason to *say* it.

**One rate, not a split.** `compat.item_tax_rates` answers one effective rate per item in basis
points, because what a shopkeeper is told is one percentage and one amount. Splitting it into
CGST and SGST or IGST depends on the supplier's state and the buyer's, the supplier on a
secondary sale is the distributor rather than us, and the document that has to carry the split is
the distributor's own invoice. On a primary sale it is ERPNext that splits it, on the Sales Order
this app asks it to make.

**Integer paise throughout** (ADR-022). The phone computes this offline and the two figures are
compared to the paise, so there is one rounding rule and it is stated below.
"""

from __future__ import annotations

import frappe

from fieldmate import compat
from fieldmate.services import scheme_engine

# Tax rates arrive as basis points: 18% is 1800. This is the scheme engine's own percentage
# denominator, imported rather than restated - a second copy of 10,000 is a second thing to get
# wrong when somebody decides rates need another decimal place.
BPS = scheme_engine.PERCENT_DENOMINATOR


def on_paise(taxable_paise: int, bps: int) -> int:
	"""Tax on one line, in whole paise.

	**Per line, once.** Per line rather than on the order total because that is what an invoice
	does - every line carries its own tax amount and the total is their sum - and a total taxed
	in one go differs from the sum of its lines by a paisa or two, which is exactly the kind of
	difference that turns into "the app said something else" at a counter.

	The rounding is `scheme_engine.round_half_up_div`, which is the app's only division in the
	money path and is already mirrored in `frontend/src/scheme/engine.js`. Using it rather than
	writing the same formula again means the phone's tax and the server's tax are the same
	operation on the same integers, not two roundings that usually match. Its docstring even
	names this case - "a paise amount times basis points" - as the largest term it expects.
	"""
	if not taxable_paise or not bps:
		return 0
	return scheme_engine.round_half_up_div(int(taxable_paise) * int(bps), BPS)


def for_lines(lines, rates: dict[str, int], discount_paise: int = 0) -> dict:
	"""Tax for a priced cart, per line and in total.

	`lines` are the scheme engine's priced lines - whole base units and integer paise, each with
	its own `gross_paise` - and `rates` is what `compat.item_tax_rates` answered. An item with no
	rate is not taxed and that is not an error: most ERPNext sites have no tax templates at all,
	and refusing a cart over it would make the app unusable in order to say something it does not
	know.

	**The cart's discount is apportioned across the lines before tax.** The scheme engine keeps
	one cart-level `discount_paise` rather than marking down each line, so taxing each line's
	gross would charge tax on money the shop is not paying. Apportioning matters most exactly
	where it is easiest to get wrong: with one line at 5% and another at 18%, *which* line the
	discount lands on changes the total.

	The rule, stated because the phone has to reach the same paise: each line takes
	`gross x discount // cart_gross`, floored, and whatever paise are left over by flooring go to
	the largest line - ties broken by item code, so two identical carts cannot disagree. The
	shares then sum to the discount exactly, and the taxable amounts to the net exactly.

	Free goods are not here and are not taxed. They are a separate list by the time an order is
	written, and the engine's own lines are the paid ones.
	"""
	rows = list(lines or [])
	gross_total = sum(_gross_paise(line) for line in rows)
	shares = _apportion(rows, min(int(discount_paise or 0), gross_total), gross_total)

	per_line = []
	total = 0
	for index, line in enumerate(rows):
		item = line.get("item")
		bps = int(rates.get(item) or 0)
		taxable = _gross_paise(line) - shares.get(index, 0)
		amount = on_paise(taxable, bps)
		total += amount
		per_line.append({
			"item": item,
			"taxable_paise": taxable,
			"tax_bps": bps,
			"tax_paise": amount,
		})
	return {"lines": per_line, "tax_paise": total}


def _gross_paise(line) -> int:
	"""What this line comes to before the cart's discount.

	`gross_paise` is what the engine puts on a line and what it sums into `cart_gross_paise`. The
	fallback recomputes it for a caller that assembled lines by hand - a test, or `cart_for`'s
	output before the engine has run over it.
	"""
	if line.get("gross_paise") is not None:
		return int(line["gross_paise"])
	return int(line.get("rate_paise") or 0) * int(line.get("qty") or 0)


def _apportion(rows, discount: int, gross_total: int) -> dict:
	"""The cart discount split across lines by gross, to the paise, keyed by line index."""
	if discount <= 0 or gross_total <= 0:
		return {}

	shares = {i: _gross_paise(line) * discount // gross_total for i, line in enumerate(rows)}
	left = discount - sum(shares.values())
	if left:
		# Flooring always leaves a few paise over. They go to the largest line, which is where a
		# paisa is least visible, and the item code breaks ties so that two carts holding the
		# same lines in a different order still answer the same.
		biggest = max(range(len(rows)),
		              key=lambda i: (_gross_paise(rows[i]), str(rows[i].get("item") or "")))
		shares[biggest] = shares[biggest] + left
	return shares


def rates_for(item_codes, company, party=None, posting_date=None, net_rates=None,
              item_groups=None) -> dict[str, int]:
	"""The effective tax rate for each item, in basis points.

	`party` is the Customer being billed, and only its `tax_category` is read - that is ERPNext's
	own hook for "this buyer is taxed differently", and it is the one the templates are selected
	against.
	"""
	return compat.item_tax_rates(
		item_codes,
		company=company,
		tax_category=_tax_category_of(party),
		posting_date=posting_date,
		net_rates=net_rates,
		item_groups=item_groups,
	)


def _tax_category_of(party: str | None) -> str | None:
	if not party:
		return None
	return frappe.db.get_value("Customer", party, "tax_category")
