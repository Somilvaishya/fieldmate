# TEST_PLAN — FieldMate Field Force

**Define what "working" actually means.**

Two separate activities, constantly confused:

| | Where | Proves |
|---|---|---|
| Tests | `dev-15.local` | The code does what the developer thought |
| Gate verification | `testerp2.web.gargsystems.com` | The feature actually works |

Never verify a gate on dev-15. A green suite is necessary, not sufficient. `bench migrate`
succeeding proves nothing.

## Commands

```bash
cd ~/frappe/frappe-bench-v15
bench --site dev-15.local run-tests --app fieldmate
bench --site dev-15.local run-tests --app fieldmate --module fieldmate.fieldmate.doctype.fm_visit.test_fm_visit
```

## Fixture hygiene — read before writing any test

`FrappeTestCase` rolls back **per class, not per method.** Records leak between test methods in the
same class. Therefore:

- Create fixtures in `setUp`, delete them explicitly. Do not rely on rollback between methods.
- Unique names per test: `f"TEST-OUT-{frappe.generate_hash(length=6)}"`.
- Never assert on a bare `frappe.db.count(...)` — scope counts to the test's own fixtures.
- `setUpClass` only for genuinely immutable shared masters.

## Cross-cutting test requirements

Applied to every relevant endpoint, in every phase:

- **Idempotency** — every write endpoint, called twice with the same `client_uuid`, produces
  exactly one document and returns the same name both times.
- **Territory scoping** — every read endpoint, called as a rep for another territory's record,
  returns a permission error. Testing the happy path proves nothing about the boundary.
- **Ledger boundary** — negative tests: secondary sales produce no GL Entry; a rep role cannot
  create a Payment Entry.
- **Compat** — every adapter in `compat.py` has a test that runs on all three CI lanes.

---

## Per-feature test cases

### Sync (Phase 0)
- Same batch of 20 pushed three times → exactly 20 documents
- Forced 409 → one `FieldMate Sync Conflict`, rest of batch still commits
- Ordered outbox: order pushed before its visit → held, not orphaned
- Backoff: 6 failed attempts → surfaces in Sync Centre, does not silently drop
- Delta pull with a watermark returns only changed rows

### Masters (Phase 1)
- 5,000 outlets + 200 beats import with zero manual correction
- Rep API call for another territory's outlet → permission error
- Field-created outlet → Pending Approval, visitable, ordering rejected until approved
- Full master pull for 500 outlets → <2.5 MB gz, <30 s on throttled 3G

### Journey plan and attendance (Phase 2)
- Month plan for 20 reps skips Sundays, holiday list, one approved leave day
- Day Start creates `Employee Checkin` with correct lat/long — **on v15 and v16**
- Full day of pings → one `FieldMate Location Trail` row; distance within 10% of odometer
- Mock location flagged, not silently accepted
- App killed mid-day and reopened → resumes the same open day

### Visit execution (Phase 3)
- Offline visit + 4 photos + 12-question checklist + merchandising audit syncs fully, no duplicate
- Check-in 400 m away → recorded, flagged, appears on manager exception report
- Photos ≤120 KB, attach to the right visit even when uploaded after it
- Checklist template changed without deploy; in-flight old-version answers still render
- 30 offline visits sync in under 3 minutes on 3G

### Orders and schemes (Phase 4) — the critical suite
- **60-case parity suite**: slab boundaries (exactly at edge, one below, one above), combos, QPS,
  stacking, budget exhaustion. Device engine and server engine identical **to the rupee**.
  **Zero tolerance for divergence.**
- Offline order → exactly one `FieldMate Order` and one `Sales Order`, totals match including tax
- Credit-breaching order → blocked, routed to correct approver, Sales Order only after approval
- Budget exhaustion → blocks or warns per config; ledger reconciles to applied benefits
- 40-line cart re-prices offline in under 150 ms on a mid-range Android
- Cancelling `FieldMate Order` cancels its `Sales Order`, no orphan

### Secondary sales and van (Phase 5)
- File with 3 bad rows → good rows import, 3 reported with row numbers and reasons
- Implied offtake matches hand calculation across a month
- Van load → 3 cash sales → settle-in → vehicle stock zero, Stock Ledger balanced
- **No secondary sales document produces a GL Entry**

### Collections (Phase 6)
- Collection across 3 invoices → one Payment Entry, 3 references, correct outstanding reduction
- **No Payment Entry before deposit confirmation**; rep role cannot create one directly
- Bounced cheque reverses cleanly, restores original outstanding
- Undeposited cash past threshold → manager alert
- Offline collection reflects correct outstanding after sync even if another landed first

### Targets and incentives (Phase 7)
- National target cascades to 20 reps; leaves sum to root for every target type
- All six achievement types correct against a seeded month
- Incentive payout for 3 reps matches a hand-built spreadsheet to the rupee
- Claim distance matches Location Trail; rep cannot edit upward without approval
- Nightly job for 250 reps finishes under 10 minutes

**Criterion 1 needs one word read carefully.** Five of the six types are quantities and are
split, so their leaves sum to the root. The sixth, Lines Per Call, is a **rate**, and a rate has
no total — a root asking 4.5 lines a call asks each rep for 4.5, and a cascade that divided it
would give twenty reps a target of 0.225 lines each. So `scripts/gate7.py` asserts *sum* for the
five and *equality at every leaf* for the sixth (ADR-028). One verdict could not carry both.

The split runs in whole units — paise for money, ones for counts — because ten lakh divided three
ways in floating point sums to ₹9,99,999.99, and that is found at month end rather than here.
`tests/test_target.py::TestTheSplit` exercises the function on its own, with no database.

Criterion 5 builds 250 leaf plans for real. It is slow to set up and that is the point: a job
timed against three reps has been timed against nothing. `--fast` skips it and the gate then
reports it as **not run** rather than as passed.

### Analytics (Phase 8)
- Every metric reproduced by hand for one rep-week and matches
- 40-rep dashboard renders under 2 s against 6 months of seeded data
- **No report or chart queries `FieldMate Visit` directly**
- Backdated visit correction picked up by next rollup, restates the snapshot
- Each alert rule fires exactly once per occurrence

### Portal and claims (Phase 9)
- Distributor sees only own orders/claims — verified by attempting another's document
- Month's claim reconciles exactly to applied benefits on those orders
- Claim approval → Credit Note with right account and cost centre
- Distributor-set fulfilment status appears in rep's PWA order list after sync

Three of the four are asserted as refusals or negatives, and that is deliberate:

- **Criterion 1 is a refusal, not an absence.** An empty list proves nothing on a site where the
  fixture created nothing. Both `scripts/gate9.py` and `tests/test_portal.py` build a *second*
  distributor with a real order and then go after it by name — through the service layer and
  through a plain `frappe.get_list`, because the second is what catches the route nobody thought
  of (ADR-027).
- **Criterion 2 counts twice and compares.** The claim's own lines and the window's accruals are
  totalled independently; asserting the `reconciles` flag alone would pass on a flag that was
  always true.
- **Criterion 3 checks what did not happen too.** One line rather than one per SKU, the
  configured account and cost centre, and **no Stock Ledger Entry** — a claim settles money, not
  goods (ADR-026).

Manual walkthrough: `docs/MANUAL_TESTS_PHASE9.md`. Seed it with `scripts/setup_phase9.py`, which
builds **two** depot logins at two distributors, because criterion 1 cannot be tested by hand
with one.

---

## End-to-end flow (run before every gate from Phase 4 on)

```
Install PWA → Day Start (GPS + selfie) → load beat → check in at outlet
→ stock audit → merchandising photo → build order → scheme applies
→ submit offline → record collection → check out → next outlet
→ Day End → go online → outbox drains
→ verify in Desk: Visit, FieldMate Order, Sales Order, FieldMate Collection all present and linked
→ confirm deposit → verify Payment Entry posted
```

## Responsive breakpoints

- **360 px** — field phone, the one that matters
- 768 px — tablet
- 1440 px — Desk

## Pre-deployment checklist

**Functionality** — [ ] Login [ ] Day Start/End [ ] Beat load [ ] Check-in/out [ ] Order capture
[ ] Scheme application [ ] Collection [ ] Sync drain [ ] Error handling [ ] Loading states
[ ] Empty states

**UI** — [ ] 360 px [ ] 768 px [ ] Desk [ ] 48 px targets [ ] 4.5:1 contrast [ ] Offline strip
accurate [ ] Keyboard/accessibility

**Security** — [ ] No secrets in Git [ ] Auth verified [ ] Cross-territory denied
[ ] Cross-distributor denied [ ] No field role reaches accounting [ ] Input validated server-side
[ ] Photos private [ ] GPS retention configured

**Code** — [ ] Lint passes [ ] Tests pass on dev-15 [ ] CI green on version-15 and version-16
[ ] develop lane recorded and triaged [ ] `bench migrate` clean on testerp2

## Reporting

State outcomes plainly. Failing tests are reported with output. Skipped steps are named as
skipped. A criterion that could not be checked is reported as unchecked, never implied as passed.
**A gate is not partially passed.**
