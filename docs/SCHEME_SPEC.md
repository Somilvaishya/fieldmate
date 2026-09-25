# The scheme engine — normative specification

A trade scheme must resolve to **the same rupee** on a phone with no signal and on the server an
hour later. If it does not, the rep promises the shopkeeper one number and the invoice carries
another, and the shopkeeper stops believing the app. Gate 4 allows zero divergence across the case
corpus, so this document is the contract, not a description: both engines are written from it, and
where they disagree with each other, the one that disagrees with *this* is the one that is wrong.

> **Revision 2.** The first revision was written before anything was built. Two independent
> readers — the engine author and the corpus author, who was forbidden to read the engines —
> resolved fourteen silent spots *differently*. That is a spec defect, not an implementation one,
> and every one of them is closed below. The amendment log at the end says what changed and why.

## 1. Why the engine is a pure function

The plan says "written once as a pure rule spec, compiled to both Python and JS. Never two
implementations." Two runtimes mean two bodies of code however it is arranged; what can be made
singular is **everything that decides an outcome**. So the split is:

| | Lives where | Written how many times |
|---|---|---|
| Scheme masters (rupees, cases, item groups, scope) | server DB | once |
| **Spec compiler** — resolves scope, converts cases to units, rupees to paise | server, `services/scheme_compile.py` | **once** |
| **Compiled spec** — flat JSON, no lookups left in it | pulled to the phone, cached | **one artifact, byte-identical both sides** |
| **Evaluator** — pure `(cart, specs) -> result` | `services/scheme_engine.py` and `frontend/src/scheme/engine.js` | twice, mirrored step for step |
| Case corpus | `fieldmate/scheme/cases.json` | **once, run by both** |

The evaluator is the only duplicated thing, and it is deliberately small and dumb. It **never**
reads the database, looks up a price, converts a UOM, or reads a clock. Everything ambiguous has
already been decided by the compiler, which exists once. That is what makes parity provable rather
than hoped for.

Each numbered step below (S1…S10) appears as a same-named function with the same step comment in
both engines. A reviewer diffs them side by side.

## 2. The money contract

**Rule: there is no floating-point arithmetic anywhere in the money path.**

All money is **integer paise**. All percentages are **integer basis points** (`pct_bp`), where
5% = `500` and 12.5% = `1250`. Quantities are **integer base-UOM units**.

One rounding primitive, integer-only, identical in both languages:

```
round_half_up_div(n, d)   # n >= 0, d > 0, both integers
    = floor((2 * n + d) / (2 * d))
```

`2*n + d` stays below 2^53 for every value this app can hold (the largest realistic product is
`base_paise * pct_bp` ≤ 10^9 × 10^6 = 10^15), so `Math.floor` in JS and `//` in Python are exactly
equal. No banker's rounding, no `toFixed`, no `flt()`, no `Math.round` — `Math.round(-0.5)` is `-0`
in JS and `0` in Python, and that class of difference is exactly what Gate 4 is looking for.

A percentage benefit is therefore:

```
discount_paise = round_half_up_div(base_paise * pct_bp, 10000)
```

Floats appear at exactly one place, the boundary where a rupee figure becomes paise:

```
to_paise(rupees) = floor(rupees * 100 + 0.5)
```

Both languages perform the identical IEEE-754 double multiply, so this is deterministic too — but
it happens in the **compiler**, on the server, before the spec is ever sent. The evaluator is handed
paise and never calls it.

### 2.1 Type discipline across the two runtimes

JSON cannot tell `24` from `24.0`, and the two languages disagree about what is missing. Three
rules, applied by both engines at every boundary:

- **Every number read from a spec or a cart is coerced to an integer** before use. Python would
  otherwise print `24.0` where JS prints `24`, and the parity diff would fail on a value that is
  arithmetically identical. Garbage coerces to `0` rather than raising on one side only.
- **Every absent label is emitted as `null`, never left undefined.** `JSON.stringify` drops an
  `undefined` key entirely while Python writes `null`, so an omitted key is a divergence.
- **Item codes are compared and sorted as text, never as numbers.** A catalogue holding `"999"`
  and `"1000"` sorts the wrong way round otherwise, and a JS object used as a map would reorder
  them silently. Use an explicit ordered map.

## 3. The compiled spec

One JSON object per scheme. Everything in it is already resolved: no links to follow, no dates to
compare, no UOM to convert. The phone caches these from `sync.pull` and hands them to the evaluator
unchanged.

```jsonc
{
  "scheme": "FM-SCH-00012",          // naming series id, ASCII, the tie-breaker for sort order
  "scheme_name": "Surf Excel Volume Slab",
  "priority": 10,                     // lower runs first
  "stacking": "Stackable",            // Exclusive | Stackable | Best Of Group
  "stack_group": "SURF-VOL",          // required when stacking = Best Of Group, else null

  "basis": "Qty",                     // Qty | Value  — what the slab measures
  "measured_over": "Item Set",        // Item Set | Order  — what is totalled to get that measure
  "qualifying_items": ["SE-1000"],    // base item codes, compiler-expanded from groups/brands

  "slabs": [                          // ordered, non-overlapping, ascending. `to` null = open top
    {"idx": 1, "from": 120, "to": 239, "benefits": [...]},
    {"idx": 2, "from": 240, "to": null, "benefits": [...]}
  ],

  "budget_paise": 5000000,            // null = uncapped
  "consumed_paise": 1234560,
  "on_exhaust": "Block"               // Block | Warn
}
```

`from` and `to` are **base units** when `basis` is `Qty` and **paise** when `basis` is `Value`. A
scheme a manager typed as "2 cases" is stored as `240` by the compiler using that item's conversion
factor, so the engine never divides by one.

**`measured_over` and `qualifying_items` are not independent.** When `measured_over` is `Order` the
compiler **must** emit `qualifying_items` as `[]`, and the evaluator measures the whole cart. When
it is `Item Set`, an empty `qualifying_items` makes the scheme not applicable — a scheme scoped to
no items measures nothing. There is no third case.

### Benefits

```jsonc
{"kind": "Free Goods",       "item": "SE-1000", "qty": 1, "value_paise": 12200, "per": "Multiple"}
{"kind": "Percent Discount", "pct_bp": 500,                                      "per": "Slab"}
{"kind": "Value Discount",   "amount_paise": 5000,                               "per": "Slab"}
{"kind": "Rate Off",         "amount_paise": 50,                                 "per": "Unit"}
{"kind": "Incentive",        "amount_paise": 5000,                               "per": "Unit"}
```

`value_paise` on a Free Goods benefit is **what one free unit costs us**, stamped by the compiler
from the item's valuation. Without it the budget in S7 and the ranking in S8 are uncomputable, and
the rep cannot be shown what the scheme is worth. A Free Goods benefit that arrives without it is
valued at `0` — it still ships the stock, it simply does not consume budget.

| `per` | multiplier | reads as |
|---|---|---|
| `Slab` | 1 | "5% off once you cross 2 cases" |
| `Unit` | `measure` | "₹50 per case" (the compiler already restated per-case as per-unit) |
| `Multiple` | `floor(measure / slab.from)` | "buy 10 get 1 free", and again at 20 |

**`per: Unit` is forbidden on a `Value` basis.** On a value basis `measure` *is* paise, so "50 paise
per unit" on a ₹250 cart would multiply out to ₹12,500 off. The compiler rejects the combination;
an evaluator that meets one anyway skips that benefit entirely (see §5.1).

**`per: Multiple` divides by the matched slab's `from`, which is a trap worth knowing.** On a
tiered ladder — slab 1 from 10, slab 2 from 20 — a 25-unit order matches slab 2 and yields
`floor(25/20) = 1`, where a single open-top slab at 10 would have yielded 2. Free goods can go
*down* as the order grows. This is the only coherent reading of "per multiple of this slab", so it
stands; a manager who wants a repeating ladder uses **one open-topped slab**, not a tier per rung.

`Incentive` is money for the **rep**, not off the shop's bill. It never touches `net_paise`. It does
consume the scheme's budget, because a budget a manager set is a cap on what the scheme pays out,
and rep incentive is real money leaving the same decision.

`Free Goods` bill at zero. They are output as their own lines and never re-enter any basis — a free
case must not help the cart cross the next slab, or a scheme funds its own escalation.

## 4. Cart input

```jsonc
{
  "outlet": "FM-OUT-00042",
  "lines": [
    {"idx": 1, "item": "SE-1000", "qty": 24, "rate_paise": 12200}
  ]
}
```

`qty` is base units, `rate_paise` the per-base-unit rate the compiler resolved from the price list.
Line gross is `qty * rate_paise`, an exact integer product.

## 5. The algorithm

**S1 — normalise.** Merge duplicate item lines by summing `qty`, **then** drop lines whose summed
`qty <= 0` — so a `+5` and a `−5` on the same SKU cancel the line out entirely. Where two merged
rows carry **different rates**, the surviving rate is the one on the **lowest `idx`**: a rep who
re-added a SKU did not intend to renegotiate it, and picking by array position rather than by the
rep's own numbering would make the answer depend on transport order. Sort the result by `item`
ascending (as text — §2.1), then re-index from 1. Sorting here is what makes everything downstream
order-independent: two phones that built the same cart by different routes must produce the same
bytes.

**S2 — line gross.** `line.gross_paise = qty * rate_paise`, and
`cart_gross_paise = sum(line.gross_paise)`.

**S3 — order the schemes.** Sort by `(priority asc, scheme asc)`. `scheme` is an ASCII naming-series
id, so JS UTF-16 ordering and Python code-point ordering agree. Never sort by name — names are
user-typed and may hold non-ASCII. **S3 order is the total order for the whole result**: `applied`,
`dropped` and `near_misses` are all emitted in it, whatever order the work actually happened in.

**S4 — measure each scheme.**
- `measured_over = Order` → `qualifying` is every line.
- `measured_over = Item Set` → `qualifying` is the lines whose item is in `qualifying_items`.
- `basis = Qty` → `measure = sum(qualifying.qty)`
- `basis = Value` → `measure = sum(qualifying.gross_paise)`
- No qualifying lines → `measure = 0` and the scheme is **not applicable**.

**S5 — pick the slab.** The highest slab where `from <= measure` and (`to` is null or
`measure <= to`). None matched → not applicable. Slabs are validated non-overlapping at save time,
so at most one can match and "highest" is a safety net, not a policy.

**A not-applicable scheme is not a dropped scheme.** It appears in `near_misses` (S10) and never in
`dropped`, which is reserved for schemes that *would* have applied and were taken away.

**S6 — compute benefits.** For each benefit of the matched slab, in the order written:

```
multiplier = 1                                   if per == "Slab"
           = measure                             if per == "Unit"
           = floor(measure / slab.from)          if per == "Multiple" and slab.from > 0
           = 1                                   if per == "Multiple" and slab.from <= 0
```

Each benefit yields one entry with **all six keys always present**:

```jsonc
{"kind": "Percent Discount", "per": "Slab", "multiplier": 1,
 "amount_paise": 1968, "item": null, "qty": 0}
{"kind": "Free Goods", "per": "Multiple", "multiplier": 2,
 "amount_paise": 24400, "item": "SE-1000", "qty": 2}
```

| kind | `amount_paise` | `item` / `qty` |
|---|---|---|
| `Percent Discount` | `round_half_up_div(qualifying_gross_paise * pct_bp, 10000) * multiplier` | `null` / `0` |
| `Value Discount` | `amount_paise * multiplier` | `null` / `0` |
| `Rate Off` | `amount_paise * multiplier` | `null` / `0` |
| `Incentive` | `amount_paise * multiplier` | `null` / `0` |
| `Free Goods` | `qty * value_paise` (of the granted total) | the item / `benefit.qty * multiplier` |

**The percentage is rounded before the multiplier**, exactly as written above. The percentage base
is the **qualifying** gross, never the cart gross — a 5% soap scheme must not discount the tea.

**S7 — budget.** `remaining = budget_paise - consumed_paise`; uncapped when `budget_paise` is null.

```
cost = sum of every benefit's amount_paise for this scheme, including Incentive
```

If `cost > remaining`: `on_exhaust = Block` drops the scheme entirely with reason
`BUDGET_EXHAUSTED` — never part of it, because a half-funded scheme is a number nobody can
reconcile. `Warn` keeps it and sets `budget_warning: true`.

Each scheme carries its own budget; there is no shared pot in this revision, so no two schemes can
compete for one. Shared budgets are out of scope for Phase 4.

**S8 — stacking.** Walk the surviving schemes in S3 order, holding a set of claimed items.

- `Exclusive` — claims every item it qualified on. Any **later** scheme, of any stacking mode,
  that overlaps those items is dropped with reason `EXCLUSIVE_OVERLAP`. An earlier `Exclusive`
  beats a later one; priority is how a manager expresses intent.
- `Stackable` — **claims nothing and excludes nothing.** It applies alongside anything. It can
  still be dropped by an *earlier* `Exclusive`, because that one did the claiming.
- `Best Of Group` — within one `stack_group`, keep the single highest `benefit_paise`; the rest are
  dropped with reason `BEST_OF_GROUP`. **Ties break on S3 order**, so the higher-priority scheme
  wins and a tie resolves identically on every device. A `Best Of Group` scheme claims nothing.

`dropped[].reason` is exactly one of `BUDGET_EXHAUSTED`, `EXCLUSIVE_OVERLAP`, `BEST_OF_GROUP`.

**S9 — total.**

```
discount_paise  = sum of amount_paise where kind in (Percent Discount, Value Discount, Rate Off)
incentive_paise = sum of amount_paise where kind == Incentive
benefit_paise   = per applied scheme: sum of amount_paise where kind != Incentive
net_paise       = max(0, cart_gross_paise - discount_paise)
```

`benefit_paise` is **what the shop receives** — the bill reduction plus the value of the free stock.
It is the figure shown as "Benefit Value" and the figure `Best Of Group` ranks on. Rep incentive is
excluded because the shopkeeper never sees it. Budget cost (S7) is the wider figure and *does*
include it.

`net_paise` is floored at 0; `discount_paise` is **not** clamped. A discount larger than the cart is
a scheme misconfiguration, and reporting the real figure alongside `errors: ["NEGATIVE_NET"]` is
what makes it findable. Clamping both would hide it.

#### The two numbers, and the mistake that keeps getting made

`discount_paise` and `benefit_paise` are different figures and must never be substituted for one
another. This is a product rule, not an implementation detail:

| | What it is | Where it may appear |
|---|---|---|
| `discount_paise` | what actually comes **off the bill** | the bill summary, the net payable, the invoice |
| `benefit_paise` | what the shop **receives in total** — bill reduction *plus* the value of the free stock | "Benefit Value" on a scheme card, and `Best Of Group` ranking |

**Free goods are given in addition. Their value never reduces the bill.** Subtracting it would pay
the shop twice for one scheme — once in stock, once in cash — and the distributor would settle a
claim for the second half that nobody authorised.

The supplied Stitch mock-up makes exactly this error: it shows a benefit of ₹313.68 (2 free units at
₹122 = ₹244, plus a ₹50 bill cut, plus ₹19.68 of case discount) and then subtracts the whole
₹313.68 from the total. The correct presentation of that same cart is:

```
bill reduction   ₹19.68 + ₹50.00        <- discount_paise, comes off the net
free stock        2 × Surf Excel 1kg      <- shipped at ₹0.00, listed separately
benefit value    ₹313.68                  <- benefit_paise, what the shop got, NOT a deduction
```

A screen that shows a single "savings" figure must show `discount_paise`, and must list the free
units beside it rather than folding them in. Read the scheme out the way the rep will say it across
the counter: "sixty-nine rupees off, and two free packs" — never "three hundred and thirteen off".

**S10 — near misses.** For each scheme that is **in scope and not dropped**, report the lowest slab
whose `from` is strictly greater than `measure`:

```jsonc
{"scheme": "...", "scheme_name": "...", "slab_idx": 3, "basis": "Value",
 "measure": 330000, "gap": 70000}
```

`gap = slab.from - measure`, and is therefore always ≥ 1. Where no slab sits above the measure —
the top slab is already matched, or the measure is past a closed top with nothing above it — **no
near miss is emitted at all**. A nudge that says "order 380 fewer units" is worse than silence.

A scheme dropped for budget or stacking gets no near miss either: pushing the rep toward a benefit
they cannot collect is a lie the app would be telling on our behalf.

Near misses are advisory and never alter any total.

### 5.1 Forward compatibility

An **unknown `kind`, `per` or `stacking` value is skipped and contributes nothing** — no discount,
no free goods, no budget cost. A phone running last month's build must **under-promise** against a
scheme written this month, never over-promise. A rep who quotes a discount the server then refuses
has to take it back across a counter; a rep who quotes less than the server grants hands over a
pleasant surprise.

## 6. Result shape

```jsonc
{
  "cart_gross_paise": 840360,
  "discount_paise": 24500,
  "net_paise": 815860,
  "incentive_paise": 5000,
  "applied": [{"scheme": "FM-SCH-00012", "scheme_name": "…", "slab_idx": 2,
               "measure": 240, "benefits": [ /* §5 S6 entries */ ],
               "benefit_paise": 29400, "budget_warning": false}],
  "free_goods": [{"item": "SE-1000", "qty": 2, "scheme": "FM-SCH-00012", "value_paise": 24400}],
  "near_misses": [{"scheme": "…", "scheme_name": "…", "slab_idx": 3,
                   "basis": "Value", "measure": 330000, "gap": 70000}],
  "dropped": [{"scheme": "…", "scheme_name": "…", "reason": "BUDGET_EXHAUSTED"}],
  "errors": []
}
```

`applied`, `dropped` and `near_misses` are each in S3 order. `free_goods` follows the order of the
`applied` entries that produced them. Key order within an object does not matter; **values must be
equal**. The parity runner compares parsed objects, not serialised text.

## 7. Parity suite

`fieldmate/scheme/cases.json` holds the corpus, each case `{id, why, cart, specs, expect}`. The
Python suite runs them through `scheme_engine.evaluate`; `frontend/scheme/parity.mjs` runs the
identical file through the JS engine under Node. `scripts/parity.sh` runs both and diffs. **Any
difference in any field fails the gate.**

> The corpus lives in `fieldmate/scheme/`, **not** in `fieldmate/fixtures/`. That directory is
> reserved: Frappe's `import_fixtures` walks every top-level `.json` in it and calls `import_doc`,
> which reads `doc["doctype"]`. Our cases have no `doctype`, and the loop catches only `ImportError`
> and `DoesNotExistError` — so a corpus in `fixtures/` takes `bench migrate` down with a `KeyError`.

Coverage is mandated at: slab boundaries (exactly `from`, one below, one above, exactly `to`, one
above `to`, the open top, and a hole between slabs), every `per` multiplier, percent rounding at the
half-paise from both sides, combos, stacking precedence in every mode, budget exhaustion both ways,
empty carts, duplicate lines with conflicting rates, free goods not feeding a slab, incentive not
netting, and determinism pairs for both line order and spec order.

**Expectations are computed from this document and never from the code.** The corpus author does not
read the engines. Deriving an expectation from an implementation makes Gate 4 a tautology.

When the two engines disagree, neither is patched until this document says which is right.

## Amendment log

Revision 2 closed fourteen gaps found when the engine author and the corpus author read revision 1
independently and resolved them differently. The three that would have failed the whole corpus at
once:

| Gap | Resolution |
|---|---|
| S7 required a free-goods valuation the compiled spec had no field for — it was uncomputable | `value_paise` added to the Free Goods benefit (§3) |
| `benefit_paise` undefined; one reader included incentive and free goods, the other neither | Defined in S9 as what the **shop** receives: discount + free-goods value, incentive excluded. Budget cost is the wider figure and includes it |
| `applied[].benefits[]` element shape never given | Pinned in S6: six keys, always all present |

The rest: drop-reason enum named; `applied`/`dropped`/`near_misses` ordering pinned to S3; the S8
`Stackable` self-contradiction resolved; `Best Of Group` ties moved from scheme id to S3 order so
priority is honoured; S1 duplicate-line rate conflict decided; `measure` added to the near-miss
shape; `per: Unit` forbidden on a `Value` basis; `per: Multiple` on a zero floor pinned to 1;
unknown enum values pinned to skip; `discount_paise` explicitly not clamped; the vestigial
shared-budget sentence removed; type discipline across runtimes written down (§2.1); and the corpus
moved out of Frappe's reserved `fixtures/` directory.

Two commercial traps were found and are documented rather than "fixed", because the behaviour is
correct and the surprise is in the configuration: `per: Multiple` on a tiered ladder can reduce free
goods as an order grows (§3), and a `Value` basis makes `measure` a paise figure (§3).
