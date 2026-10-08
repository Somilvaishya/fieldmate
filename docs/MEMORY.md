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

**Three-Phase Plan Phase 2 — steps 1 to 6 of 11 done.**

- 1,020 Python tests green, ruff clean
- 42 PWA tests green — see below
- Branch `fix/phase-3-field-findings`

The plan now being worked from is the **FieldMate Three-Phase Plan** of 3 Oct 2026 (Sagar), not
the original ten-phase build plan in TASKS.md. The two use the word "phase" for different things;
TASKS.md numbering is the old one and is kept because the per-task history is still useful.

| Plan | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Three-Phase Plan | All primary + secondary sales — **done** | Holi season — booking, advances, allocation, dispatch | After the sale — claims, returns, Tally/Busy, replenishment |

## Phase 2, step 6 — getting it out of the warehouse

`services/dispatch.py`, the dispatch half of the allocation page, a **FieldMate Dispatch Planner**
role, and an idempotency key on Delivery Note and Delivery Trip. No dispatch document of our own:
the Delivery Note is the record of what left and the Sales Invoice of what was billed.

**It does not build a Pick List, and the plan says it should.** ERPNext refuses outright —
*"Cannot create a pick list for Sales Order X because it has reserved stock"* — because reserving
and picking are two alternative ways of promising stock, not two steps of one. The reserved path
goes straight to a Delivery Note built `for_reserved_stock`, whose line quantities come from what
allocation actually held, so a booking served short ships what it was given. Picking instead would
mean giving the allocation back first, which is the one thing a dispatch must not do.
`test_a_pick_list_is_not_the_path_here` pins it so nobody re-reads the plan in six months and
"fixes" this.

A Delivery Trip is left a **draft** — the route is still being planned — but it needs a vehicle and
a departure time, because ERPNext will not save one without them. That is the right rule rather
than one to work around: a trip without either is a list of addresses.

**Three things the tests caught:**

1. `ready()` empties the moment a booking ships — ERPNext consumes the reservation when the goods
   go out. The first `invoice()` read `ready()` and would have had nothing to bill the instant the
   delivery succeeded. `notes_for()` looks them up by key instead.
2. A Delivery Trip would not save: `vehicle` and `departure_time` are mandatory even in draft.
3. **Test teardown order.** `OrderFixture.tearDown` cancels this rep's FieldMate Orders by filter,
   and a FieldMate Order's `on_cancel` cancels its Sales Order — so by the time the base teardown
   reached the Delivery Note, ERPNext refused with "Sales Order is cancelled or closed" and the
   whole cleanup loop stopped there, leaking everything after it. Dispatch documents come down
   first now. This is the "test teardowns" carry-over the plan lists, met for the second time.

## Phase 2, step 5 — who gets the stock when a season is short

`services/allocation.py`, a Desk page at **fieldmate-allocation**, and a reservation seam in
`compat`. **No allocation doctype**, which was the plan's own call and is the right one: the
decision is FieldMate's, the record is ERPNext's Stock Reservation Entry. A second table of
who-gets-what would be a second answer to a question the warehouse already answers, and the two
would disagree the first time somebody delivered something.

Three rules, named as the people arguing about them name them — **Advance First** (by the share
of their own booking a party has paid, so a small distributor who paid in full outranks a large
one who paid a tenth), **First Booked**, **Pro Rata** (floored, remainder to the largest ask, ties
by order name — the same rule and the same reason as apportioning a cart discount in
`services/tax`). Every ordering is total, so two previews of the same figures cannot differ.

Preview, then apply, is the whole shape. A short season is somebody's commercial decision about
which distributor is told they are served short, and nobody should make it by pressing a button
and seeing what happened. The preview is the same arithmetic as the apply.

Only **released** bookings are allocated. One still waiting for its advance has no Sales Order, so
there is no line to reserve against — and reserving stock for an order nobody has paid for is what
the advance hold exists to prevent.

**It needed `set_warehouse` on the booking's Sales Order.** `Customer.fm_warehouse` has existed
since Phase 1 and nothing read it; reserving stock means reserving it *somewhere*, and that
somewhere is the depot that will ship. The allocation tests found this by stocking one warehouse
while the Sales Order named another and reserving nothing at all — passing, silently, until the
skips were removed.

Stock reservation is now on for **fieldmate-test.local** as well. It was only on testerp2, so nine
of these tests skipped on the first run — nine tests proving nothing, which is worse than none.

## Phase 2, step 4 — an offer that rewards booking early

`booking_from`, `booking_to` and `requires_advance_pct` on FieldMate Scheme, filtered in
`for_outlet` beside `covers_sale` because both are questions about the *order* rather than about
where it was booked.

**The booking window is not the validity window.** `valid_from`/`valid_to` say when the offer
exists; the new pair says when the order has to have been **taken** to earn it. A season scheme is
live from November to March, because that is when it is billed, and rewards only the orders booked
in November. Read against the order date, not today, so a rep syncing in December does not have
November's orders judged against December.

**`requires_advance_pct` is measured against the season's advance, not against what has been
collected.** The order is priced the moment it is taken, when nothing has been paid — reading what
is in hand would mean no early-booking offer ever fired at the counter, which is the one place it
has to. A booking cannot be released without its season's advance either, so by the time anything
is billed the two come to the same thing. A scheme asking for an advance therefore cannot reach an
order that is not a booking at all. This is written down in the field's own description because it
is a judgement, not an obvious consequence.

The window travels in the compiled spec and the phone filters on it too — `liveSpecs` is exported
now and has a test of its own, because it is one half of a rule the server also enforces and the
two drifting apart is the exact class of bug this app keeps finding in the field. That test also
pins what happens to a spec from a server that predates these keys: `undefined` reads as "no
window", not as a wall, or a phone would quote nothing at all after a server downgrade.

## Phase 2, step 3 — the advance that releases a booking, and the cheque that does not

A booking is held at `Awaiting Advance` until the season's `advance_pct` has actually been
received against it, and goes the moment it is — `release_if_paid` runs from the collection's own
`on_submit`, so a rep who collects in a village and syncs that evening does not find it still held
in the morning.

**It is deliberately not an approval.** Nobody decides it: the money has arrived or it has not. So
it has its own status rather than Pending Approval, no approval rule is picked, and it never
appears in a queue of things a manager could act on but cannot.

**A post-dated cheque is not money until its date.** `collection.in_hand_by_order` is the stricter
sibling of `paid_by_order`: both exclude Bounced and Cancelled, and this one also excludes a
cheque dated ahead. Releasing a booking against a PDC means reserving stock and planning a
dispatch on a promise. The cheque is still recorded, still allocated, and `pdcs_for` lists it —
and the hold message names it, because a rep who has handed in a cheque would otherwise read the
hold as the office losing their paperwork.

**Nothing new was needed to hold a PDC.** `FieldMate Collection` already carries mode Cheque, the
instrument number, its date, the bank and a Bounced status — the whole of what a PDC register
holds — and `FieldMate Collection Allocation.reference_type` already offers `FieldMate Order`, so
"linked to the order" was already expressible. No field was added anywhere in this step.

One thing worth knowing: a party we bill is collected from with `party_type = "Distributor"`, not
"Customer". There is no Customer option and there should not be one — the field distinguishes who
owes the money, not what doctype they are, and `distributor` is already a Link to Customer whose
own description says "the one paying us".

## Phase 2, step 2 — a booking priced from its season, and the rate stops moving

`delivery_date` per order line, validated against the season's delivery window and defaulting to
its first delivery day. `rates_locked_on` on the order. A booking is priced from the season's
price list, posts one Sales Order carrying each line's own delivery date, and names the season's
Payment Terms Template so ERPNext builds the payment schedule from it. Amending after the change
cutoff is refused.

The order date now reaches the pricing chain — `channel.resolve`, `credit.billing_party`,
`catalogue.cart_for`, `scheme_compile.evaluate_for` all take `on` — because which season an order
books into, and therefore which list it is priced from, is a question about the order's date and
not about today.

**What it cost, and the two that were already there:**

1. **Pinning the price list is not pinning the rate.** The first version passed the locked list
   back into the pricing pass. The list is corrected between November and February, so the party
   was handed February's rate for an order read out in November. A submitted booking is not
   repriced at all now.
2. **`we_are_the_seller` compared `kind == PRIMARY`** and a booking's kind is "Booking", so no
   booking posted a Sales Order. The kinds live together in `settings` now and the question is
   asked with `settings.is_primary`, never a string equality. Same shape as the `kind`/`mode`
   trap in step 1.
3. **`channel._from_outlet` never passed `field_user` to `pricing.price_list_for`** — so this
   module answered a different price list from the catalogue for any rep who had one of their
   own. Latent until `cart_for` started trusting the channel's answer, and contradicted the
   comment on `resolve_price_list` saying the two cannot drift.
4. **A submitted Sales Order survives a test rollback.** Submitting commits, so the Sales Order
   outlives the FieldMate Order that keyed it, the naming counter hands the next run the same
   order name, and it collides on the unique `fm_source_key`. One orphan was cleaned off the test
   site by hand. This is the "test teardowns" carry-over the plan lists, meeting us in person.

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

### Both environment blockers are now cleared

`india_compliance` 15.31.3 is installed on **testerp2 and fieldmate-test.local**, and
`Stock Settings.enable_stock_reservation` is on (with `allow_partial_reservation`). A database
backup was taken before each install. GST Settings: e-way bill on, API on, e-invoice off.

Installing it broke things, which is the point of having done it before building on top:

- **HSN/SAC is mandatory on a sales Item, and the length is checked** — six or eight digits by
  default, so most of the 18,000 seeded rows (four-digit chapter headings) are not usable. Four
  fixtures and the gate script created Items without one. `tests/base.hsn_code` / `with_hsn` now
  answer `340111` (toilet soap, which is what these fixtures sell, and carries no taxes of its own
  — an HSN that did would be copied onto every item by `set_taxes_from_hsn_code` and would
  override what a tax test asserts).
- **An Item Tax Template needs `gst_treatment` and `gst_rate`**, and a Taxable template with a
  zero rate is refused. The rate is not inferred from the rows unless they use recognised
  CGST/SGST/IGST accounts, and these fixtures build a plain tax account on purpose. Zero is now a
  Nil-Rated template, which is how a real site records it.

Suite 974 green on a site that **has** india_compliance, which it never was before — and that is
exactly why the HSN problem stayed hidden until the gate ran on testerp2.

### Still open before step 2

- **Business decisions**, though not blocking the shape of the work: the Season doctype holds
  advance %, price list and Payment Terms Template as fields, and the allocation page will preview
  all three rules, so these are values to fill in rather than code to write.
- **Company `test` has no GSTIN** and reads as Unregistered. An e-way bill needs a registered
  GSTIN, so the dispatch item cannot be verified end to end until that is set.
- Two items on testerp2 were given a fallback HSN that is certainly wrong for them —
  `FM-SCHEME-CLAIM` and `test`, both stamped 340111. Correct them in the item master.

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
screen, the check-in guard in `stores/visit.js`, and `liveSpecs` (which offers a phone still
honours). **Not yet covered:** the cart and review screens, the scheme engine's JS half against
the Python parity corpus, the sync outbox, and the Dexie migrations.

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

Phase 2, step 7: the cockpit and the reminders — booked, allocated, delivered and paid by state,
party and SKU; daily payment reminders; the cutoff lock; and top-up orders against a booking.

**Still open from step 6:** the e-way bill. india_compliance is installed, but company `test` has
no GSTIN and reads as Unregistered, so none can be raised on testerp2. Nothing else in dispatch
depends on it, and the Sales Invoice that an e-way bill would hang off is already posted.

Then, in no fixed order: the rest of the PWA harness where it is thinnest (the cart and review
screens, and the scheme engine's JS half against the Python parity corpus), and the three
carry-over items still open — test teardowns, rate limit and CSRF, and the scheduler.
