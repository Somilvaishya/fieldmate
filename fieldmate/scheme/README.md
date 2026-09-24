# The scheme parity corpus

`cases.json` is the case corpus for Gate 4. It holds 100 cases, each one a complete
`{id, why, cart, specs, expect}` in the shapes defined by `docs/SCHEME_SPEC.md` sections 3, 4 and 6,
**revision 2**. The Python suite runs every case through `services/scheme_engine.evaluate`,
`frontend/scheme/parity.mjs` runs the identical file through the JS engine under Node, and
`scripts/parity.sh` diffs the two. Any difference in any field fails the gate.

## The one rule

**Every expected value in this file was computed by hand from `docs/SCHEME_SPEC.md`. None of it was
read out of, or checked against, either engine.**

This is not a stylistic preference, it is the only thing that makes Gate 4 mean anything. Two engines
that were both fitted to the same corpus, where the corpus was fitted to one of the engines, will
agree perfectly and prove nothing at all. The corpus is the independent third party: when the two
engines disagree, the corpus says which one is wrong, and when the corpus disagrees with both, the
specification says whether the corpus or the engines need to change. Nobody patches an engine to make
a case pass until `SCHEME_SPEC.md` has said which answer is right.

So when a case fails, the order of work is:

1. Read the clause of `SCHEME_SPEC.md` the case is testing. The `why` field names the stake.
2. Decide what the document says the answer is.
3. Fix whichever of the three is wrong - engine, corpus, or document - and say so in the commit.

Adding a case by running it through an engine and pasting the output defeats the whole arrangement.
If a new case is needed, work the arithmetic on paper first.

## What the cases cover

Slab boundaries on both a Qty and a Value basis, including exactly on `from`, one below, one above,
exactly on `to`, one past `to`, an open top, and the two ways a measure can fall out of every slab.
All three `per` multipliers, including `Multiple` on a zero floor. Percent rounding at the half
paise, bracketed from both sides at three different `pct_bp` values, because that is the single most
likely place for Python and JavaScript to part company. Percent taken on the qualifying gross and
never the cart gross. Every benefit kind in the six-key shape, with and without free goods. Several
benefits on one slab and several schemes on one cart. Every stacking mode and every way they
interact, including the `Best Of Group` tie on S3 order and the ranking of a free-goods scheme by its
valuation. Budget uncapped, exactly enough, one paise short both ways, already spent, and pushed over
the cap separately by free goods and by rep incentive. Free goods that must not feed any slab, that
grant an item the cart does not hold, and that arrive with no valuation. Incentive that accrues,
never nets, and still consumes budget. Unknown `kind`, `per` and `stacking` values, which are the
forward-compatibility guarantee. Empty carts, zero and negative quantities, duplicate lines with
conflicting rates, negative net, and determinism pairs for both line order and spec order.

## Revision 2

The corpus was first written against revision 1 of `SCHEME_SPEC.md` and reported fourteen places
where the document was silent and the corpus had to pick. Revision 2 closed all of them, and this
file was recomputed against it. The changes worth knowing when reading an old failure report:

- **Free Goods carry `value_paise`** in the compiled spec, so a free case has a price. It feeds
  `amount_paise` on the benefit, `benefit_paise` on the applied scheme, and the S7 budget cost.
- **`benefits[]` elements carry all six keys**, always. A money benefit pads `item` to null and
  `qty` to 0 rather than omitting them, because `JSON.stringify` drops an undefined key and Python
  writes null.
- **`benefit_paise` is discount plus free-goods value, incentive excluded** - what the shop
  receives. The S7 budget cost is the wider figure and does include incentive.
- **Near misses** report the lowest slab strictly above the measure, emit nothing when no slab sits
  above, never appear for a dropped scheme, and carry `measure`. The two negative-gap cases from
  revision 1 are gone.
- **`per: Unit` on a `Value` basis is skipped**, not evaluated. The case that used to blow the net
  to zero now records a skipped benefit and no error.
- **`Best Of Group` ties break on S3 order**, so the higher-priority scheme wins.
- **`measured_over: Order` measures the whole cart unconditionally**, whatever the item list says.

## Why this folder, and not `fixtures/`

`fieldmate/fixtures/` is reserved by Frappe. On every `bench migrate`, `import_fixtures` reads each
top-level `.json` file there and calls `import_doc`, which reaches for `doc["doctype"]`. A case
corpus is not a document list and has no `doctype`, and the loop catches only `ImportError` and
`DoesNotExistError` — so a corpus sitting in `fixtures/` takes the migration down with
`KeyError: 'doctype'`.

The corpus was written there first, against revision 1 of `SCHEME_SPEC.md`, and moved here before
anyone migrated. If you ever see a migration fail with `KeyError: 'doctype'`, look for a stray data
file under `fixtures/` before you go looking for a broken DocType.
