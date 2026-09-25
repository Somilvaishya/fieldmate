# Manual test — Phase 4, orders and schemes

Everything here runs on **testerp2**. Seed the data first, once:

```
cd ~/frappe/frappe-bench-v15/sites
../env/bin/python ../apps/fieldmate/scripts/setup_phase4.py
```

That creates five SKUs, a catalogue and four schemes. `--show` reports the state without
changing anything; `--undo` removes the catalogue and the schemes and leaves the items alone.

The SKUs are chosen so every figure on screen can be checked on a calculator:

| SKU | Item | Per case | Rate |
|---|---|---|---|
| `SE-1000` | Surf Excel Easy Wash 1kg | 12 | ₹122.00 |
| `LB-100` | Lifebuoy Total Soap 100g | 48 | ₹8.20 |
| `RIN-250` | Rin Detergent Bar 250g | 36 | ₹16.50 |
| `TM-500` | Taj Mahal Tea 500g | 24 | ₹275.00 |
| `WH-500` | Wheel 2-in-1 Powder 500g | 30 | **no price, on purpose** |

And four schemes:

| Priority | Scheme | Fires when |
|---|---|---|
| 10 | Surf Excel — buy 10 get 1 free | 10 units, and again at 20 |
| 20 | Lifebuoy — 5% off on 2 cases | 96 units (2 × 48) |
| 30 | Bill over ₹10,000 — ₹400 back | the whole order crosses ₹10,000 |
| 40 | Tea festival — ₹4,000 of tea | ₹4,000 of `TM-500` |

---

## The reference cart

Build exactly this, because every number below is hand-computed from it:

```
SE-1000    2 cases   =  24 units
LB-100     2 cases   =  96 units
TM-500     1 case    =  24 units
```

| | Expected | Where it comes from |
|---|---|---|
| Gross | **₹10,315.20** | 2,928.00 + 787.20 + 6,600.00 |
| Lifebuoy 5% | **−₹39.36** | 787.20 × 5% |
| Bill over 10,000 | **−₹400.00** | gross is over ₹10,000 |
| Discount total | **−₹439.36** | |
| **Net** | **₹9,875.84** | |
| Free goods | **2 × SE-1000**, **1 × TM-500** | floor(24 ÷ 10) = 2, and tea over ₹4,000 |

**The free stock is worth ₹519.00 and must NOT come off the bill.** If the net reads ₹9,356.84
the app is paying the shop twice for one scheme — once in stock and once in cash — and the
distributor will later claim for the half nobody authorised. See `SCHEME_SPEC.md` S9.

---

## A — the screens

| # | Do this | Expect |
|---|---|---|
| A1 | Open a shop, tap through to order | Catalogue lists 5 SKUs with case sizes and rates |
| A2 | Look at `WH-500` | Marked as having no price. **Not** shown at ₹0.00, and it cannot be added to the cart |
| A3 | Add `SE-1000`, tap +1 Case twice | Shows **2 Cases = 24 units**, subtotal **₹2,928.00** |
| A4 | Watch the totals as you tap | They move **immediately**, with no spinner and no pause |
| A5 | Add `LB-100` 2 cases and `TM-500` 1 case | Totals match the reference cart above |
| A6 | Go to the schemes screen | All four benefits listed **in words**, e.g. "2 free Surf Excel", "₹39.36 off" |
| A7 | Read the free-goods section | 2 × SE-1000 and 1 × TM-500, at ₹0.00, **listed separately from the discount** |
| A8 | Check the headline saving | **₹439.36 off**, not ₹958.36. Free stock is listed, never folded in |
| A9 | Go to review, then punch the order | Confirmation names the order and says it went to the **distributor** |
| A10 | Read every word on the review screen | It must never say "invoice", "posted" or "Sales Order" |

## B — the thing this phase exists to prove

| # | Do this | Expect |
|---|---|---|
| B1 | In Desk, before booking: count `Sales Order` | note the number |
| B2 | Book the reference cart from the phone | order appears in `FieldMate Order` |
| B3 | Count `Sales Order` again | **exactly the same number** |
| B4 | Open `GL Entry`, filter on today | **nothing new** from this order |
| B5 | Open the `FieldMate Order` | `Status` = **Sent To Distributor**, `Sent To Distributor On` stamped, `Sales Order` **empty** |
| B6 | Check `Distributor` on it | the shop's distributor, and the order shows in a list filtered on them |

If a Sales Order appears, stop and report it. That is ADR-023 broken, and it means the company's
books are recording a sale it did not make.

## C — offline, which is the majority path

| # | Do this | Expect |
|---|---|---|
| C1 | Turn flight mode on **before** opening the cart | catalogue and schemes still load, from the phone |
| C2 | Build the reference cart offline | every total is identical to A5 — **to the paisa** |
| C3 | Punch the order offline | says it is saved on the phone and will sync |
| C4 | Close the app, reopen it | the order is still queued, nothing lost |
| C5 | Turn the network back on | it syncs by itself |
| C6 | Open the order in Desk | one order, not two. `Engines Agreed` is **ticked** |
| C7 | Count `Sales Order` | still unchanged |

C6 is the parity check on real hardware. If `Engines Agreed` is unticked, compare
`Phone Said` against `Net Total` on the same record and send me both figures — that is a real
divergence and I need the exact numbers.

## D — the edges

| # | Do this | Expect |
|---|---|---|
| D1 | Put only 1 case of Lifebuoy in the cart | the 5% does **not** fire; a nudge says how much more is needed |
| D2 | Add the second case | the discount appears, and the nudge goes |
| D3 | Build a cart of exactly ₹9,999 | the ₹400 does not fire |
| D4 | Add one more unit | it fires |
| D5 | Add `SE-1000` twice on separate taps | it merges into **one** line with the quantities summed |
| D6 | Set a line to 0 | the line stays on screen rather than vanishing |
| D7 | Cancel a booked order | its scheme benefits are given back — check `Consumed Amount` on the scheme drops |

## E — permissions

| # | Do this | Expect |
|---|---|---|
| E1 | Sign in as a rep, open Desk directly | cannot create or edit a `FieldMate Order` by hand |
| E2 | Try to open another rep's order | refused |
| E3 | As a rep, try to approve your own order | refused |

---

## What to send back

For anything that fails: the screen, what you did, what you expected, what you got. For a
totals mismatch, send `Phone Said` and `Net Total` off the order record — those two numbers are
enough to find it.

**Not covered here, and still open:**

- Gate 4 criterion 5 asks a 40-line cart to re-price in under 150 ms on a mid-range Android.
  It measures 0.179 ms on a laptop; it has never been timed on a real phone. If step A4 ever
  feels slow, say so.
- Budget exhaustion is tested in the engine corpus but no seeded scheme has a budget on it, so
  Gate 4 criterion 4 is not exercised by this plan.
