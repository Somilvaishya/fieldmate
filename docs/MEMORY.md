# MEMORY — current project state

Current state only. Permanent decisions go in DECISIONS.md.
**Update at the end of every task.**

Last updated: 7 Oct 2026. The previous version of this file was three weeks stale — it still read
"171 tests, Phase 1 complete" while Phase 9 had shipped and the suite was at 955. A stale MEMORY
is worse than none, because somebody acts on it.

---

## Current status

**Build plan phases 0–9 complete, gates 0–9 passed on testerp2.**
**Channel redesign Phase 1 complete (10/10 steps), gate 8/8 on testerp2.**

**Three-Phase Plan Phase 2 started — step 1 of 11 done.**

- 974 Python tests green, ruff clean
- 31 PWA tests green — **new, see below**
- Branch `fix/phase-3-field-findings`

The plan now being worked from is the **FieldMate Three-Phase Plan** of 3 Oct 2026 (Sagar), not
the original ten-phase build plan in TASKS.md. The two use the word "phase" for different things;
TASKS.md numbering is the old one and is kept because the per-task history is still useful.

| Plan | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Three-Phase Plan | All primary + secondary sales — **done** | Holi season — booking, advances, allocation, dispatch | After the sale — claims, returns, Tally/Busy, replenishment |

## Phase 2, step 1 — a season, and what makes an order a booking

`FieldMate Season` (the phase's one new master), `order_kind` on FieldMate Order
(Secondary / Primary / Booking, read-only and server-owned), `services/season.py`, and a patch
stamping the kind onto every existing order. One rule, no flag and no rule table:

> a primary order dated inside the booking window of its company's active season is a booking

Two seasons active and booking at once for one company are refused at the master, because
`open_for` would otherwise have to pick one and any rule for picking is the configuration
language this design keeps avoiding.

This also closes a Phase 1 naming gap: the plan asked for `order_kind` and Phase 1 shipped
`party_type` plus `channel.resolve` instead.

**Two things it cost, both worth remembering:**

1. **A Select default defeats its own backfill patch.** `order_kind` carried
   `"default": "Secondary"`, and Frappe fills every existing row with a Select's default when the
   column is added — so the patch guarded on `order_kind is null or = ''` found nothing and two
   primary orders on testerp2 were stamped Secondary. The default is gone; the patch derives for
   every row. `stamp_scheme_applies_to` has the same shape and is right only because the value it
   writes equals the default. Do not copy that shape.
2. **One value had two names.** `credit.billing_party` reshapes `channel.resolve`'s answer and
   renamed `kind` to `mode` on the way through. `season.kind_for` read `kind`, got nothing, and
   quietly made every primary order secondary. `kind` is the name now; `mode` stays as an alias
   because that dict is part of the catalogue payload and an un-updated phone reads it.

### Still open before step 2

- **Business decisions:** advance %, when the balance is due relative to Holi, whether PDCs are
  accepted, when the price locks. And the allocation rule when stock is short — advance first,
  first booked, or pro rata.
- **`india_compliance` is not installed on testerp2**, so the e-way bill half of the dispatch item
  cannot be built or verified there.
- **Stock reservation is switched off** (`Stock Settings.enable_stock_reservation = 0`). The whole
  allocation item rests on it.

## The PWA test harness

Vitest, `@vue/test-utils`, happy-dom and fake-indexeddb in `frontend/`. `npm test`, and
`scripts/ci-local.sh` now runs it as its own lane **before** the build.

This was done ahead of Three-Phase Plan Phase 2 because of what the week showed. Three bugs
reached a rep in three days. Every one of them was a figure the server answered correctly and the
phone drew wrong, and not one was catchable in Python:

1. **GST never reached the phone.** `order.mine` and `order.summarise` named their columns
   explicitly and both predated the tax, so the orders list could only quote `net_total` — short
   by the whole of the GST. The same list drew a blank name on every primary order, which has a
   customer and no outlet.
2. **A kirana's screen showed its distributor's credit limit** under a heading saying it was the
   shop's. Five screens, root cause in `lib/credit.js`, which carried neither the party's name nor
   the shop's own position.
3. **A check-in into the next shop silently closed the open visit**, stamped it short, and told
   nobody — so a row of shops could be walked leaving empty visits that counted towards coverage.

The first four tests written were reverted against the old code to prove they fail on it. They do.

Covered today: `lib/tax.js` (the money rule the server copies), `lib/credit.js`, the orders list
screen, and the check-in guard in `stores/visit.js`. **Not yet covered:** the cart and review
screens, the scheme engine's JS half against the Python parity corpus, the sync outbox, and the
Dexie migrations.

## Field findings fixed this week

All on testerp2, all found by the user rather than by a test:

- A day started yesterday was still handed back as today's day, so today's visits, orders and
  collections landed on yesterday's record and yesterday's date. `day.current` guards on the date
  now rather than trusting a scheduled job.
- The old auto-close flipped a status and stopped: no Day End, so no counts, no distance, no
  attendance, no HRMS OUT.
- `auto_close` recorded every visit it closed as "Order Taken" — a Select with options and no
  default holds its first option, so `or "No Order"` could never fire, and `day_counts` counts
  that exact string as a productive visit.
- `api.currentVisit` existed and was called from nowhere, so a visit the server had closed stayed
  open on the phone for good.
- `/distributor/sales` had **never once rendered**: `sales.py` set `context.template`, a key
  Frappe reads as the Jinja path. Its test called `get_context` and stopped, and the key it
  asserted was the bug. Once it rendered it looked broken too — three classes with no rule in
  portal.css.

## Known issues

- **The scheduler is not running on testerp2.** `enable_scheduler` is 1 and `Scheduled Job Log`
  holds no rows at all, so `close_stale_days`, `purge_old_trails`, `measure_targets` and the KPI
  and alert jobs have never fired on that site. The Three-Phase Plan lists this as a carry-over to
  do first. It is half of why the stale-day bug was found by a person.
- **Insights is not installed on testerp2**, so `setup/insights.py` has only ever been observed to
  no-op (Phase 8.4). The two datasets that need no Insights work today.
- **GitHub Actions blocked** by an account billing lock unrelated to this repo.
  `scripts/ci-local.sh` covers the gates meanwhile.
- `developer_mode` is off on testerp2. Not needed while DocTypes are authored as JSON on disk.
- v16/v17 compatibility is **unverified** (ADR-015). Do not claim it.
- Test accounts on testerp2: `rep1@fieldmate.test`, `mgr1@fieldmate.test`, `test@rep.com`, and the
  portal login `depot.one@fieldmate.test` (Mahalaxmi Distributors, all three rights).
  Test-site credentials, not for production.

## Carry-over items from the Three-Phase Plan, still open

The plan's "do first" list, as it stands today:

| Item | State |
|---|---|
| Direct-billed party bills the distributor | Done — it is the primary path now (ADR-024, ADR-033) |
| `sales_mode` leftovers | Done — van sales removed entirely (ADR-032) |
| Test teardowns delete rows they did not create | **Open.** Five test files still wipe by filter rather than by what they made |
| Rate limit on login and push; CSRF header from the PWA | **Open** |
| Scheduler on for the pilot site | **Open** — see Known issues |

## Open decisions

1. **Before Phase 2:** tier and parent of every primary customer — who buys from us and who buys
   from a super stockist. One site with two companies, or two sites.
2. **Before Phase 2:** whether November bookings taken as plain primary orders is acceptable. If
   not, the first three Phase 2 items come into Phase 1 and it runs about two weeks longer.
3. **Before Phase 2:** booking terms — advance %, balance due relative to Holi, PDCs accepted,
   price lock. Allocation rule when stock is short.
4. Per-outlet credit limits are built and unset. `FieldMate Outlet.credit_limit` is 0 on every
   outlet on testerp2, which reads as "no limit set" and not as a limit of zero.

## Next step

Phase 2, step 2: a booking priced from the season's list with the rate locked at submit, a
delivery date per line, and one Sales Order carrying both and the payment schedule from the
season's Payment Terms Template. Blocked on the business decisions above for its defaults, not
for its shape.

Then, in no fixed order: the rest of the PWA harness where it is thinnest (the cart and review
screens, and the scheme engine's JS half against the Python parity corpus), and the three
carry-over items still open — test teardowns, rate limit and CSRF, and the scheduler.
