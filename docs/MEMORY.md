# MEMORY — current project state

Current state only. Permanent decisions go in DECISIONS.md.
**Update at the end of every task.**

Last updated: 10 Oct 2026. The previous version of this file was three weeks stale — it still read
"171 tests, Phase 1 complete" while Phase 9 had shipped and the suite was at 955. A stale MEMORY
is worse than none, because somebody acts on it.

---

## Current status

**Build plan phases 0–9 complete, gates 0–9 passed on testerp2.**
**Channel redesign Phase 1 complete (10/10 steps), gate 8/8 on testerp2.**

**Three-Phase Plan Phase 2 — steps 1 to 10 of 11 done.**

- 1,175 Python tests green (skipped=12), ruff clean
- 155 PWA tests green — see below
- Gates 4-9, Phase 1 and Phase 2 pass on testerp2 (Phase 2 with one criterion not answerable)
- Branch `fix/phase-3-field-findings`

The plan now being worked from is the **FieldMate Three-Phase Plan** of 3 Oct 2026 (Sagar), not
the original ten-phase build plan in TASKS.md. The two use the word "phase" for different things;
TASKS.md numbering is the old one and is kept because the per-task history is still useful.

| Plan | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Three-Phase Plan | All primary + secondary sales — **done** | Holi season — booking, advances, allocation, dispatch | After the sale — claims, returns, Tally/Busy, replenishment |

## Phase 2, step 10 — the gate, and what it found

`scripts/gate_phase2.py`, the plan's four "done when" lines against a real site, plus the Phase 2
documents added to `clean_gate_fixtures`.

    1. PASS  a booking with an advance and two PDCs posts one Sales Order with the season's schedule
    2. PASS  short stock splits by each of the three rules, and reverts
    3. PASS  a dispatch produces Delivery Notes and invoices with the advance allocated
    4. PASS  the cockpit's totals reconcile against the Sales Orders behind them
    5. SKIP  the booking's tax is the Sales Order's tax - not answerable on this bench

Three of the four only mean anything on **short stock** and an **unpaid booking**, so the fixture
builds exactly that: two bookings, one paid, 20 in the warehouse against 30 asked for.

**Criterion 3 failed, and the defect was real.** A season is bought months before delivery, so by
the time the invoice is raised the party has already paid — and the invoice went out without the
advance on it. The party is billed for money they handed over in November, their Payment Entry sits
unallocated, the receivable is overstated, and somebody journals it by hand in February.
`compat.make_sales_invoice` now takes `allocate_advances`, which sets **ERPNext's own switch**
(`allocate_advances_automatically`); off by default, and a season dispatch asks. Four tests in
`test_dispatch`, including that an advance larger than the bill is not over-allocated.

**Criterion 5 is the open one, and it is a decision rather than a patch.** FieldMate's tax comes
from **Item Tax Templates** (item, then item group) — `services/tax.py`, mirrored in `lib/tax.js`
so a rep can quote offline. ERPNext puts tax on a sales document from a **Sales Taxes and Charges
Template in its header**; an Item Tax Template only overrides a rate on an account row that header
already carries. This site has the first and not the second: company `test` has no GSTIN and no
address, so india_compliance determines no place of supply and selects no template. Marking one
`is_default` does not help — `get_party_details` still returns none — so it is not a field nobody
set.

So today **a primary order here quotes 3,360 and the invoice goes out at 3,000**, and nothing in
the app notices. That is a Phase 1 shortfall (its plan row asked for a `taxes` table and
`place_of_supply` on the order; what shipped is a computed `tax_total`). Three ways out, and the
choice is the business's:

1. fill in the company's GSTIN and address — smallest, and a pilot needs it anyway;
2. have the app refuse or warn when its computed tax has no ERPNext tax head behind it;
3. take our tax from where ERPNext takes its own, so the two cannot diverge.

Three expectations of mine were wrong and the code was right each time, which is worth recording
because two of them look like product bugs at first glance:

- **pro rata gives 14/6, not 13.33/6.67.** Nobody can reserve a third of a bar of soap:
  `allocation.split` floors each share and hands the stray unit to the largest ask, and documents
  it. The gate restates that arithmetic rather than copying the figure.
- `held_by` reports `reserved`, not `reserved_qty`.
- the gate never **banked** the advance, so no Payment Entry existed for criterion 3 to find —
  ADR-004 working exactly as intended.

`clean_gate_fixtures` grew the documents this phase posts, in strict dependency order: a Payment
Entry references an invoice, an invoice is made against a Delivery Note, a note ships a Sales
Order, and ERPNext refuses to cancel a Sales Order while a reservation holds stock for it. A Stock
Entry has no name of its own to match, so the gate stamps its remarks. Three gate runs now leave
**nothing** behind on testerp2, verified doctype by doctype.

## Phase 2, step 9 — the season on the phone

`services/season.describe`, a season block on the catalogue payload, booking fields and the
advance position on `order.summarise`, `order.my_bookings`, `collection.pdc_total_by_order`,
`is_pdc` on the satchel rows, `api/showcase.py`, `frontend/src/lib/season.js`, and two new screens
— `/bookings` (the season book) and `/showcase`.

**The first step of this phase the handset can see.** Everything before it happened on the server,
and none of it reached the rep: the catalogue payload said nothing about a season, the order
summary said nothing about a booking, the orders list could not tell one from a shop order, and
the deposit screen could not tell a post-dated cheque from money.

**Arrived and promised are two different figures, and both travel.** A PDC is allocated to a
booking and shown against it, and it is not money until its date. The season book reports the PDC
total *beside* the shortfall and never inside it; the deposit screen gives post-dated cheques
their own block with the date on every line.

Three live defects found while building it:

- **The review screen told every order that "the distributor delivers it and bills the shop."**
  ADR-023 is about a *retailer* order. A primary order and a booking are sales we raise and we
  invoice, and the screen said otherwise in three places including the button.
- **The depot collection form had no field for the date on the cheque**, so every cheque was
  recorded as money in hand in all but name — a booking would release on a promise.
- **The per-line delivery date listened on `change` only.** Which of `input` and `change` arrives
  depends on the Android WebView, so on some handsets the date was lost silently.

And one thing the plan did not name: **a depot collection can now be allocated to a booking.**
`FieldMate Collection.on_submit` tries the advance gate again for each order a receipt names, and
nothing else does — without it there was no path from the field to the gate at all.

Two fixture lessons, both now written into the code:

- a helper called `book` shadowed `OrderFixture.book`, so the test that wanted a plain shop order
  got a second season and the master refused it as an overlap.
- **a released booking's Sales Order has to be tracked.** Submitting one commits, so it outlives
  FrappeTestCase's per-class rollback while the naming series counter is rolled back — and the
  next run to reach that order name fails on a duplicate `fm_source_key`.

Two test-environment quirks, worked around in the tests and not in the product: vitest reports a
rejection from a mock reset in `beforeEach` as **unhandled** even where the component catches it,
and happy-dom **refuses** a value outside a date input's `min`/`max` where a real browser only
marks it invalid.

**Not verified end to end on testerp2.** That site has no season, no booking and no showcase
catalogue, so the new screens have nothing to draw there. Those fixtures belong to step 10's gate
script and step 11's manual sheet. What was verified there: every new endpoint imports and the
no-season path answers correctly.

## Phase 2, step 8 — the showcase, behind a public link

`FieldMate Share Link` (the phase's second and last new doctype), showcase fields on Product
Catalogue, `services/showcase.py`, and a guest page at `/showcase?t=<token>`.

**The only thing in the app that answers to somebody with no login.** Token generated not chosen,
one party's prices fixed at creation, expires by itself, can be switched off, can be capped by
opens, and a refusal says "not available" and nothing more — who it was for and when it expired
are facts about a conversation the visitor may not have been in. `noindex`.

Only a catalogue marked **Showcase** can be shared; an ordinary one carries notes written for the
person selling. An unpriced item is left out rather than shown at nothing.

**A self-order is not an order** — it is a draft for the rep who sent the link. Quantities are the
only thing taken from the visitor, they are re-priced server-side, and an item the link does not
show is dropped.

Two Frappe facts learned the hard way, both in tests:

- **`frappe.set_user` clears `local.form_dict` and `session.data`.** Setting a form value and then
  switching user wipes it.
- **`frappe.as_json` is not in the website's restricted Jinja environment**; Jinja's `tojson` is.

## Phase 2, step 7 — the cockpit, the reminder, and a top-up

`services/cockpit.py` and a Desk page at **fieldmate-season-cockpit**: booked, allocated,
delivered and paid, by state, by party (largest owing first — it is a list you telephone from) and
by SKU. Nothing is stored; every figure is read from the document that holds it, because a cockpit
with its own numbers is a fifth opinion and the one nobody trusts the morning it disagrees.

A **daily reminder** (`tasks.remind_booking_payments`) tells the rep who collects and the manager
who asks, once per booking per day. Read off the Sales Order's own payment schedule — the one
ERPNext built from the season's Payment Terms Template — not a copy of ours. Not the party: this
app has never sent anything to a customer.

A **top-up** is a second booking naming the first through `tops_up`: same party, same season,
original submitted. The cutoff does not stop one, because adding to a booking is not amending it.

**That found a bug from step 2.** `assert_may_amend` fired on any save of a non-new document, and
`submit` is one — so once a change cutoff had passed, a booking taken legitimately inside the
booking window could not be submitted at all. Three things came out of fixing it, all worth
remembering about Frappe:

- An **amendment is a brand new document** with `amended_from`, so a `not is_new()` guard excludes
  the very case an amend rule is for.
- `save()` on a submitted document **does not run `validate`** — that is the
  `before_update_after_submit` path.
- **`docstatus` is set before validate runs on a submit**, so it cannot be used to tell a submit
  from an amendment. `_action` can.

## The last two carry-overs: a rate limit, and a CSRF token nobody was checking

**CSRF had been off the whole time and looked on.** `frappe.auth.validate_csrf_token` returns
early for a session with no token saved, and an API login leaves one unset — so every write this
app accepted was unprotected by it. `auth.login` answers a token now; the phone keeps it (in
memory and `localStorage`, so it survives a service-worker reload) and sends
`X-Frappe-CSRF-Token` on writes only. Cleared on sign-out. A server that answers without one is
tolerated — the two sides being a release apart is an ordinary afternoon.

A bug of mine in that, caught by its own test: `if not session.data` is False for a **fresh**
session, whose data is an empty dict — so it answered None for exactly the sessions it was for.
It asks `data is None` now.

**Rate limits:** `auth.login` 20/hour, `sync.push` 60/hour, both **per address, not per
username** — limiting by username lets anybody lock a named rep out of their own phone. The
limiter short-circuits when there is no HTTP request, so test runs are never limited; that is
pinned.

**The scheduler was never a FieldMate problem.** Everything site-side was right; the bench's
`Procfile` had the scheduler commented out with a note claiming `bench schedule` exits
immediately. It does not — that was tested properly and it ran the full twenty seconds. The line
is re-enabled with the worker's restart wrapper, and all six jobs ran clean by hand against
testerp2.

**The Procfile is a bench file, not in this repo**, so that half does not travel: a pilot site
needs the same in its supervisor config. Also seen and left alone: the scheduler log is full of
`Access denied` for `bench-15.local`, whose DB credentials do not work. Frappe catches per-site
failures and carries on, so it is noise rather than a cause, and that site is not ours.

## The teardown carry-over, finished

The plan's literal complaint — "five files delete every row on the site" — was already fixed;
`wipe_since_setup` deletes only what a test created. What remained cost this phase three days of
chasing failures nowhere near the code that broke, and is now done:

- **Teardown no longer gives up on the first refusal.** It caught `DoesNotExistError` and nothing
  else, so the first document ERPNext would not cancel ended the loop and everything after it
  leaked. It cancels **newest first** (a Delivery Note before its Sales Order — ERPNext's own
  rule, and only about taking fixtures down; nothing in the selling path runs backwards),
  **retries** while anything still moves, and **switches off** whatever is genuinely stuck so a
  leftover season cannot refuse the next test's `make_season`.
- **`OrderFixture` no longer cleans up early.** It deleted this rep's orders before the base had
  taken down what they led to, and a FieldMate Order's `on_cancel` cancels its Sales Order — so
  the base then met a Delivery Note whose Sales Order was gone. `cleanup_targets()` hands them to
  the base instead.
- **gate4 to gate9 and two setup scripts were broken** by installing india_compliance. They took
  "any GST HSN Code" (four-digit chapter headings are rejected, and most of the eighteen thousand
  seeded rows are four digits) and "any selling Price List" (the season fixture creates extras).
  Both answers are in `_guard` now, shared by every script in the folder.

All eight gates pass on testerp2: 4 (5/5), 5 (3/3), 6 (6/6), 7 (5/5), 8 (5/5), 9 (4/4),
Phase 1 (8/8).

**Still true and worth watching:** fourteen test files commit mid-test, so what they post survives
FrappeTestCase's rollback while the rows that keyed it do not. That is what makes the ordered,
retrying teardown necessary rather than merely tidy.

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

Covered today: `lib/tax.js` (the money rule the server copies), `lib/credit.js`, `lib/season.js`
(the booking arithmetic, written twice and required to agree to the paisa), the orders list, the
check-in guard in `stores/visit.js`, `liveSpecs`, the CSRF token, and — as of step 9 — the season
book, the deposit screen's PDC block, the share screen, and the review screen on its booking path.
**Not yet covered:** the cart and catalogue screens, the review screen's ordinary shop path, the
scheme engine's JS half against the Python parity corpus, the sync outbox, and the Dexie
migrations.

## The 18-point review batch (from the user and Sagar)

Worked in the order the user set: bug fixes first, then the easy and risk-free items, then the
risky ones; the doctype-merge questions are held for a decision.

**Done:** #14 (one primary order creating several FieldMate Orders - the cart had no identity
until submit, so a retried submit made a second order), #15 (the phone still showed shops as
visited after the office cancelled the day - `todaysVisits` asked the server nothing),
#2 (Sales Person described rather than renamed), #3 (the daily call target comes off the beat the
journey plan names for that day, so a short Thursday asks for less than a long Monday; the typed
figure is the fallback and its default of 25 is gone), #4 (Activity), #11
(`expected_duration_min` described against the quality floor it was being confused with),
#5 (visit selfie behind a settings toggle), #7 (WebP where the device can encode it - the trap being that a canvas asked for a type it cannot encode returns a
**PNG** silently, which would have made photos *larger* on old WebViews), #8 (below),
#1 (autofill from the master doctypes, below), #12 (dynamic UOM, below),
#10 (`geo_accuracy_m`, below), #16 (the day merged into one document, below).

**Answered, no work needed:** #6 (Flag Mock Location - it already does what it says).

**In progress:** #13 Hindi/English - 9 of 30 screens and the switch itself; the server needs no
code change, only a `translations/hi.csv`, because the 295 translatable calls are already there ·
#18 optimise and remove redundant code - the code half is done (order pricing 16 lookups down to
6 on an eight-line order; the season cockpit four passes per page load down to one), and the
"unnecessary doctypes" half went with #16.

**Outstanding:** #9 approval-rule simplification (high risk - it governs money and permissions) ·
#17 scheme simplification (high risk - the JS and Python evaluators have to agree statement for
statement).

## #10 — the GPS accuracy nobody read

The field was written on every new shop and read by nothing: no rule, report, geo-fence or
approval looked at it, checked across the whole app. Seven outlets on testerp2, every row 0.

**The number still matters, just not stored.** Standing outside a shop, "±8 m" against "±120 m" is
the difference between a pin worth keeping and one worth re-taking, and the rep is the only person
who can act on it - they can walk a few steps and tap again. So the reading stays on the capture
screen, off the handset's own live fix, and the column is gone.

The split had to be deliberate, because `coords` is spread wholesale into the create payload -
anything parked in it is sent. The accuracy now lives in its own ref that never leaves the screen.

## #16 — the day, merged into one document

`FieldMate Day Start` + `FieldMate Day End`, joined by a unique Link, became `FieldMate Day`.
`FieldMate Visit` had held check-in and check-out in one record from the start; the day was the odd
one out, and the pair bought nothing - a join on every read, a second naming series, and
`field_user`, `day_date`, `client_uuid` and `remarks` duplicated across both.

Submitted when the day opens, with `status` carrying the lifecycle, which is what Day Start already
did. The closing fields are therefore `allow_on_submit` - the honest declaration, and it replaces
a `db_set` that bypassed validation. `finish()` is the single place a day ends, reached through
`on_update_after_submit`, so it runs whichever of the three ways the end arrived: the rep tapping
Finish Day, that same tap replayed out of the sync queue, or the scheduler shutting a day nobody
ended. Closing used to be written out once per path, and the offline path was the one that forgot
the attendance row.

**The sync path needed a new capability, not a rename.** A day is pushed twice - once when it opens
and once when it closes - and `_apply` could only insert. It saw a record it already had, reported
`duplicate`, and the close was accepted and silently dropped; the day stayed Open until the
scheduler marked it a day the rep forgot to finish. So `Syncable` grew `closes_field`,
`update_uuid_field` and `update_fields`: the close names what it closes, carries its own id so a
retry is idempotent on its own, and may write only the listed fields. **That allow-list, not the
permission, is what makes writing to an already-submitted record safe** - a device that also sends
`distance_km`, or a colleague's `field_user`, is ignored rather than trusted.

Names are symmetric on purpose - `start_latitude`/`end_latitude`, `start_checkin`/`end_checkin`.
Both documents used a bare `latitude` for their own end of the day, and merging them with one side
keeping the bare name is how somebody later reads the morning's position as the evening's. The one
`employee_checkin` was a real defect waiting: it held whichever HRMS log was written last, so a
day's IN was overwritten by its OUT.

The 147 days on the test site were **carried over, not deleted**, although nobody asked for them -
deleting is the one thing that cannot be undone if that turns out to be wrong about a single row,
and carrying them cost one INSERT. Each keeps the name its Day Start had, which is what makes it
cheap: every record that belonged to a day already holds that name, so repointing `day_start` at
`day` is a column copy rather than a mapping that can lose a row. Days from before the merge
therefore read `FM-DS-00001` and later ones `FM-DAY-00001`, which is accurate.

## #12 — a choice of unit, and where the choice comes from

**The request could not be built as asked, and the reason is worth keeping.** It asked for a
multiselect of UOMs on each Product Catalogue **item**. Those items are rows in
`FieldMate Catalogue Item`, which is `istable: 1`, and a Table MultiSelect inside a child table is
**accepted by Frappe's DocType validator and then stores nothing at all** - checked against a real
save, twice, including saving in two steps so every row had a real name, and the grandchild table
comes back empty with no error anywhere. An admin would have ticked units, saved, and lost them
silently. So the multiselect is on the catalogue **header**: `FieldMate Product Catalogue.uoms`,
rows of the new `FieldMate Catalogue UOM`.

The shape that came out of that:

- **The choices are the item master's**: its stock UOM plus whatever is on its UOM Conversion
  table, which `compat.get_item_details` already carried as `uom_conversions`. A unit the item
  cannot convert is a unit nothing can price - `cart_for` refuses one - so offering it would be
  offering a mistake.
- **The catalogue's Units narrow that**, for a catalogue that should only take cases. Empty means
  no narrowing. Narrowing to units a particular item cannot convert leaves that item its base
  unit, because being unable to order at all is worse than ordering in pieces.
- **The per-row `uom` is now the default**, relabelled "Default Unit": what the phone pre-selects.
- **A primary order's unit already came from the item master** (`sales_uom`, then `stock_uom`,
  through `order_unit`). Verified with a test rather than rebuilt.
- `catalogue.order_units()` is the one place the set is decided; `order_unit()` picks the default
  out of it, so the two cannot disagree.

**The bug a test caught**: with a catalogue narrowed to cases and a default the narrowing excluded,
`order_unit` fell back to the **stock UOM** - which that catalogue does not offer. `order_uom`
then named a unit absent from `order_uoms`, so the phone would pre-select something missing from
its own dropdown and count the rep's typed quantity against a conversion nobody showed them. It
now falls back to the smallest unit on offer, and
`test_whatever_is_pre_selected_is_always_on_offer` asserts the invariant across five shapes.

**On the phone**, `order.setUnit()`: the number the rep typed is kept and the unit is reinterpreted
- somebody who typed 5 and then reaches for the dropdown meant five cases, not their five pieces
restated as four tenths of a case. That multiplies the order, visibly, and the cart says so.
`rate_paise` is per base unit and never touched: a case costs twelve times a piece because it
holds twelve of them. The choices travel on the cart line so the dropdown works with no signal.

**Deliberately not enforced server-side.** The rate is per base unit and the factor comes from the
item master, so whatever unit the rep picks the money is right - the narrowing is a selling policy,
not a safety rail. And `cart_for` reprices submitted bookings on every save, so enforcing it would
make old orders start throwing the day an admin narrowed a catalogue. The narrowing decides what
the phone offers.

## #1 — what an admin should not have to type twice

Narrower than it first looked, and the useful half of the work was deciding what must **not**
autofill.

**Filled now.** The rep's mobile number, from the login and then the Employee's `cell_number`
(two sources, hence the controller rather than `fetch_from`), and only ever into a blank. Joining
Date from `employee.date_of_joining` with `fetch_if_empty`. Company from the Employee **on every
save** - asked for explicitly: HR owns which company somebody is employed by, so a rep whose
Employee record moves follows it. The cost is on the field's own description, because it is real:
while an Employee is linked, a company chosen by hand does not survive the next save, and an
admin who needs a different one clears the Employee link. `company_from_the_employee` corrects
the reps who already existed; a rep with no Employee is left alone.

**Deliberately left alone, with the reason written on the field.** Scheme Item's `item_group` and
`brand` are not copies of the item's own - they are a pick-one selector (`if item_code / elif
item_group` in `scheme_compile`), so filling the group from the item would read as covering every
item in that group, and clearing the item later would silently make it do exactly that. The
Merchandising Line `mrp` is what is printed on the pack on the shelf; the only reason to record it
is to find packs that disagree with the master, and a copy of the master can never disagree.
Item `uom` is blank on every child table and belongs to #12, not here.

**Two things the tests caught, both of the same kind - a pass that meant nothing.** `company` was
first built as `fetch_from=employee.company, fetch_if_empty=1`, and a test showed company arriving
set with **no employee at all**: Frappe fills a Link from the session default during `insert`, so
the field is never empty by the time a fetch runs and the configuration would have looked right
and done nothing. And `test_company_and_joining_date_come_off_the_employee` passed while that
config was dead, because the employee's company was `get_value("Company", {})` - the same string
as the session default on a single-company site, so the assertion could not tell them apart. Both
sites on this bench have exactly one company, which is why the real test now builds a second one
(five seconds, commits, and cleans up after itself).

Also worth keeping: `fetch_from` **does** apply server-side - checked against a real insert, not
assumed, because Accounting Dimension defaults in this same app turned out to be client-only.
Without `fetch_if_empty` it overwrites on every save.

## #8 — the GPS toggle, and the day nobody recorded

Two halves. The toggle is the asked-for part; the second half is the bug it exposed.

- `FieldMate Settings.track_gps_trail` (Check, default 1), in `client_settings()` so it reaches the
  handset. `gps_ping_interval_seconds` now `depends_on` it. Off means the phone takes **no** fixes
  - `pinger.start()` returns early - rather than taking them and discarding them, which costs the
  same battery.
- **The figure was zero for any day the app stayed closed.** A PWA only reports its position while
  it is open, and a rep works a day with the phone in a pocket. `trail.distance_for` returned the
  trail and nothing else, so that day showed no travel on the Day End and an expense claim worth
  nothing for a day somebody drove. `trail.route_distance_for` now measures day start, then each
  shop in the order it was **actually visited** (not the beat that was planned - a rep who skipped
  two shops did not travel the planned route). Straight-line, so it under-reports road travel,
  which is the right direction for a figure a claim is paid against.
- Each stop is the check-in fix, falling back to the shop's own pin. A shop with neither is
  skipped, not counted as (0, 0), which is in the Atlantic.
- **The basis travels with the number.** `trail.measure()` returns `{km, basis}` where basis is
  `trail`, `route`, or nothing. Three places printed "GPS trail" unconditionally - the Day End
  tile and its odometer hint, the claim screen's badge and its over-tolerance sentence, and the
  Day End DocType's own field description. A route figure under that caption is a claim about
  data that is not there, read by the rep claiming and the manager approving.

Two traps worth keeping: a **missing** `track_gps_trail` is not an opt-out (an older bootstrap or
a cached profile has no such key, and reading it as off would silently stop recording for everyone
on an app that had simply not refreshed), and `resumeIfDayOpen()` runs **before** bootstrap
answers, so it reads the cached settings itself and `configure()` stops a run already under way.

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

- **A primary order quotes a tax the company does not bill.** On testerp2 today an order reads
  3,360 to the rep and its Sales Order and invoice total 3,000. FieldMate's tax comes from Item
  Tax Templates; ERPNext puts tax on a document from a Sales Taxes and Charges Template in its
  header, and this site has no GSTIN on the company so india_compliance selects none. Found by
  the Phase 2 gate, which reports it as criterion 5 every run. Three ways out are listed under
  step 10; the choice is the business's and nothing has been changed for it yet.

- **The suite failed once in a way nobody has explained.** One run reported 521 tests and 102
  errors, every one of them `setUpClass` in `test_visit`, with `skipped=2` where every other run
  reports `skipped=12`. That is not a truncated run of the usual set — it is a **smaller set being
  discovered**. The same code then passed four times (1092, 1096, 1096, 1096) and the failure has
  not reproduced, including running `test_cockpit` immediately before `test_visit`, which was the
  obvious suspect. No scheduler process was running and no second bench process was found.
  **Nothing was fixed for this**, because nothing was understood. If it comes back, the thing to
  capture is the unfiltered output and the module list — the test count and the skip count are
  what give it away.

- **The scheduler now runs on this bench** — the Procfile line was commented out, not a FieldMate
  setting. A pilot site needs the same in its supervisor config, because the Procfile is not in
  this repo.
- **Insights is not installed on testerp2**, so `setup/insights.py` has only ever been observed to
  no-op (Phase 8.4). The two datasets that need no Insights work today.
- **GitHub Actions runs again** (15 Oct 2026). The billing lock is cleared, and the first run
  that ever started a job found five things no local run could - see ADR-015's update. The
  version-15 lane is green and required; version-16 reports only; the develop lane is gone with
  v17 (ADR-034).
- `developer_mode` is off on testerp2. Not needed while DocTypes are authored as JSON on disk.
- v17 is **out of the plan** (ADR-034). v16 is deferred and unverified - do not claim either.
- Test accounts on testerp2: `rep1@fieldmate.test`, `mgr1@fieldmate.test`, `test@rep.com`, and the
  portal login `depot.one@fieldmate.test` (Mahalaxmi Distributors, all three rights).
  Test-site credentials, not for production.

## Carry-over items from the Three-Phase Plan, still open

The plan's "do first" list, as it stands today:

| Item | State |
|---|---|
| Direct-billed party bills the distributor | Done — it is the primary path now (ADR-024, ADR-033) |
| `sales_mode` leftovers | Done — van sales removed entirely (ADR-032) |
| Test teardowns delete rows they did not create | **Done.** The literal complaint was already fixed; the ordering, the retrying and the gate scripts are done too — see above |
| Rate limit on login and push; CSRF header from the PWA | **Done** — see above |
| Scheduler on for the pilot site | **Done on this bench** — the Procfile is not in this repo, so a pilot still needs it in supervisor |

## Open decisions

1. **Before Phase 2:** tier and parent of every primary customer — who buys from us and who buys
   from a super stockist. One site with two companies, or two sites.
2. **Before Phase 2:** whether November bookings taken as plain primary orders is acceptable. If
   not, the first three Phase 2 items come into Phase 1 and it runs about two weeks longer.
3. **The booking terms are built as configuration, not settled as a decision.** Advance %, the
   balance's payment terms template, the price lock, the delivery window and the change cutoff are
   fields on `FieldMate Season`; the allocation rule is one of three on the same master (advance
   first / first booked / pro rata). PDCs are accepted and recorded, and deliberately do not
   release a booking until they fall due. What is still open is the **data** — nobody has set those
   values for the real Holi season, and testerp2 has no season record at all.
4. Per-outlet credit limits are built and unset. `FieldMate Outlet.credit_limit` is 0 on every
   outlet on testerp2, which reads as "no limit set" and not as a limit of zero.

## Next step

Phase 2 steps 9, 10 and 11 are done, including the manual sheet
`docs/MANUAL_TESTS_PHASE2_SEASON.md`. Work is now in the **18-point review batch** above.

Next in the user's stated risk order: **#13 Hindi/English**, then the items waiting on a decision
(#10, #16/#18), then the two high-risk ones (#9 approval rules, #17 schemes).

`business_needed_solutions` was read for #12, since the user pointed at its
`enable_uom_restriction`. Its source of truth is the right one - `Item.stock_uom` plus `item.uoms`
- and nothing was taken from it: the implementation is a Desk-only `frm.set_query` holding a
**synchronous** `frappe.call` per dropdown open, which solves nothing for a rep offline in a
market.

The season sheet still has to say **what testerp2 does not have**: no season, no booking and no
showcase catalogue exist there, so the step 9 screens have nothing to draw until somebody creates
them. The sheet's first section is that setup.

**Open, and waiting on a decision rather than on work:** the tax head (step 10 above). A primary
order on this site quotes a figure with GST and the invoice goes out with none.

**Still open from step 6:** the e-way bill, which has the same root cause — india_compliance is
installed, company `test` has no GSTIN, so it reads as Unregistered and none can be raised here.
Nothing else in dispatch depends on it, and the Sales Invoice it would hang off is already posted.

After step 11, the plan's own next move: testing Phase 1 and Phase 2 together, one flow at a time.

What is left of the PWA harness is where it is thinnest: the cart and catalogue screens, and the
scheme engine's JS half against the Python parity corpus. The review screen is covered as of step
9, but only on the booking path.
