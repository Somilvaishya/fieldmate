# DECISIONS — Architecture Decision Records

Permanent decisions and their reasoning. Prevents architecture drifting between sessions.
Current state belongs in MEMORY.md, not here.

Format: `ADR-00X` · Decision · Reason.

---

## ADR-001 — A retail outlet is not an ERPNext Customer

**Decision.** Retailers are modelled as `FieldMate Outlet`, a new DocType. The billing party is the
distributor, an ERPNext `Customer`. `FieldMate Outlet.customer` exists but stays empty unless an outlet
is genuinely billed direct.

**Reason.** Modelling 60,000 kirana shops as Customers corrupts AR ageing, credit exposure and GST
reporting, for no benefit — we never invoice them. The Customer table is for parties we bill.

---

## ADR-002 — `FieldMate Order` is a separate DocType from `Sales Order`

**Decision.** Field orders are captured as `FieldMate Order`. On submit, and only after scheme resolution
and a credit check, it creates an ERPNext `Sales Order`.

**Reason.** A field order is a *proposal* captured offline on possibly stale prices and stock. A
Sales Order is a company commitment. Writing field captures straight into Sales Order means every
offline sync artefact, credit rejection and approval round-trip happens inside the company's order
book. This is the most common design mistake in ERPNext FieldMate projects.

---

## ADR-003 — Primary, secondary and tertiary sales stay separate; secondary never posts

**Decision.** Primary (company→distributor) is a real Sales Invoice. Secondary
(distributor→retailer) is captured in `FieldMate Retailer Stock` / `FieldMate Secondary Sales` and **never
produces a GL Entry**. Tertiary is inferred from stock audits only.

**Reason.** Secondary sales are transactions we do not own and cannot substantiate. Posting them
would put unauditable numbers in the books. They are market intelligence; they belong in analytics,
not accounting.

---

## ADR-004 — No field role posts to the ledger

**Decision.** Reps create `FieldMate Collection` with a receipt photo. A `Payment Entry` is posted only
on deposit confirmation by an authorised role. No field role has create/write on any accounting
DocType.

**Reason.** Finance will not sign off on a system where a phone in a market can write to the
general ledger. Separating capture from posting also gives a natural cash-in-hand control point.

---

## ADR-005 — The `fieldmate.api.*` facade is the version-compatibility boundary

**Decision.** The PWA calls only `fieldmate.api.*`. All ERPNext-specific calls go through `fieldmate/compat.py`.
No core edits; custom fields ship as `fm_`-prefixed fixtures. CI runs against version-15,
version-16 and develop.

**Reason.** Supporting v15, v16 and v17 from one branch is only possible if the surface that moves
(ERPNext internals) is isolated from the surface that must stay stable (what the field client
depends on). This confines a breaking upstream change to one module — days of work, not a
re-platform.

---

## ADR-006 — `FieldMate Location Trail` is one row per rep per day

**Decision.** The GPS path is stored as compressed JSON on a single daily row, with summary columns
(total distance, ping count, first/last fix). Not one row per ping.

**Reason.** At 250 reps pinging every 90 seconds, per-ping rows add ~30 M rows/year and make every
location-based report slow. The daily-row design adds ~65 k. No query we need requires an
individually addressable ping.

---

## ADR-007 — Reports read `FieldMate KPI Snapshot`, never raw `FieldMate Visit`

**Decision.** All dashboards, Query Reports and Insights datasets read a materialised
`FieldMate KPI Snapshot`, refreshed nightly and hourly. Nothing aggregates `FieldMate Visit` live.

**Reason.** 2.1 M visits/year makes live aggregation non-viable, and it will not become viable.
Building reports against the raw table works in month one and fails in month nine.

---

## ADR-008 — One scheme rule specification, compiled to two engines

**Decision.** The scheme engine is written once as a rule specification, compiled to both a Python
implementation (server, authoritative) and a JS implementation (device, advisory). Never two
hand-written implementations.

**Reason.** The cart must re-price offline, so the logic must exist on the device. Two
hand-maintained implementations drift, and a scheme that computes a different discount on the
phone than on the server destroys rep trust immediately. Gate 4 enforces a 60-case parity suite
with zero tolerance.

---

## ADR-009 — Managers use Frappe Desk; no custom manager SPA in v1

**Decision.** Manager surfaces are Desk workspaces, list views, Query Reports and Insights.
Distributors use Frappe portal pages. Only the field rep gets a custom PWA.

**Reason.** Managers work at a desk with connectivity and need flexible slicing — exactly what Desk
and Insights already do well. A custom manager SPA would add ~4 weeks for a worse result.

---

## ADR-010 — The app is named `fieldmate`

**Decision.** App `fieldmate`, module `FieldMate`, DocType prefix `FieldMate `, custom-field
prefix `fm_`, naming series `FM-<THING>-.#####`.

**Reason.** "Salesforce" is a registered trademark of Salesforce, Inc. and was never usable as a
shipped name. `FieldMate` is distinct from the `trako` app already on this bench and from the
`crm` app, so nothing collides. The short `FM-` series keeps document names readable while the
full `FieldMate ` DocType prefix keeps the namespace unambiguous.

---

## ADR-011 — FieldMate does not touch `trako`

**Decision.** `trako` is a separate, pre-existing SFA app on this bench (14 DocTypes, 34 API
methods, installed on `trako.dev`). FieldMate never edits it, imports from it, reuses its
DocTypes, or migrates its data. The two must install side by side without interference.

**Reason.** Explicit instruction from the owner. Beyond that, coupling a new app to another app's
schema would make both harder to upgrade and would undermine the v15/v16/v17 compatibility
strategy, which depends on FieldMate's only external surface being ERPNext through `compat.py`.

**Consequence.** Where `trako` has already solved something, FieldMate re-solves it
independently. If a `trako` approach looks worth adopting, raise it and ask — do not copy it.

---

## ADR-012 — Design system: Material 3 tokens + Tailwind, from the Stitch exports

**Decision.** Adopt the Material 3 token set and Inter type scale from the Stitch exports as
FieldMate's design system, expressed as Tailwind theme config. Supersedes the ad-hoc palette in
the first draft of DESIGN.md.

**Reason.** The exports are internally consistent, already cover light and dark roles, and give
designers a tool (Stitch) that speaks the same token vocabulary. Rebuilding an equivalent system
by hand would cost time and produce something no design tool can round-trip.

**Consequences, and they are not optional.**
- Tailwind must be a **build step**, never the CDN `<script>` the exports use.
- Material Symbols and Inter must be **self-hosted**, not loaded from Google Fonts — the app runs
  offline.
- The exports violate three field constraints and must be corrected on intake every time:
  40 px touch targets (need 48), 10–12 px label text (need 16 minimum for body),
  and `user-scalable=no` (blocks pinch-zoom).
- The exports have **no offline state strip**. Every screen needs one added.
- Placeholder imagery from `lh3.googleusercontent.com` must be stripped; it will fail offline and
  under our CSP.

---

## ADR-013 — Outlets are never billed directly

**Decision.** `FieldMate Outlet.customer` stays dormant. Every outlet is served through a
distributor. The only billable party is the distributor, as an ERPNext `Customer`.

**Reason.** Owner decision, 21 Sep 2026: the business runs on the primary/secondary model.
Primary (company -> distributor) is the billable transaction and produces a real Sales Invoice.
Secondary (distributor -> retailer) is captured as field intelligence and never billed, never
posted to the GL. See ADR-001 and ADR-003, which this confirms rather than changes.

**Consequences.**
- No outlet-to-Customer promotion flow is built. Phase 1 masters get simpler.
- `FieldMate Outlet.customer` is still created as an optional field, unset, so the schema stays
  additive if a direct-billing channel ever appears. It must not be populated by any code path.
- Credit checks resolve against the outlet's **distributor**, never the outlet itself.
- `FieldMate Collection` settles distributor invoices. A rep collecting at a shop door is
  collecting on the distributor's behalf.

---

## ADR-014 — CI evidence may come from a local lane, not only GitHub Actions

**Decision.** `scripts/ci-local.sh` runs the same lint, test and frontend-build steps as
`.github/workflows/ci.yml`, against any bench and site. A phase gate accepts its output as
evidence. GitHub Actions stays in the repo and becomes the default once it can run.

**Reason.** The GitHub account is locked over an unrelated metered Copilot balance, which blocks
Actions entirely. The repo is public, so Actions minutes themselves are free — the lock is
collateral. Blocking a phase gate on someone else's billing state would be the wrong dependency:
what the gate needs is proof that lint and tests pass on a given host version, and where that
proof is produced does not change its value.

**Consequences.**
- Each lane must be recorded with the host versions it ran against, not just "passed".
- The v16 lane still needs a v16 bench. Until one exists, criterion 1 and 5 stay open for v16.
- When Actions is unblocked, it becomes authoritative again because it builds each lane from
  scratch, which a reused local bench cannot prove.

---

## ADR-015 — v15 only for now; v16/v17 support is unverified, not abandoned

**Decision.** FieldMate targets **Frappe/ERPNext v15 only**. Gate criteria reference v15 alone.
`compat.py`, the capability probes and the CI matrix file all stay exactly as they are.

**Reason.** Owner decision, 21 Sep 2026: the work is on v15. There is no v16 site or bench here,
GitHub Actions is blocked by an account billing lock, and building a second bench to satisfy a
gate nobody is deploying against is effort spent on the wrong thing.

**This amends ADR-005.** That ADR described the facade as the v15/v16/v17 boundary and the plan
still claims three-major support. **That claim is now unverified and must not be repeated as
fact.** What is true: the architecture that would make it cheap is in place and costs nothing to
keep — one module holds every ERPNext-specific call, capabilities are probed rather than assumed,
custom fields ship as fixtures, and no core file is edited.

**Consequences.**
- Say "built so v16 support is cheap to add", never "supports v16".
- The `version-16` and `develop` CI lanes stay in the workflow but gate nothing.
- The rules that keep the option open are still binding: nothing outside `compat.py` imports
  `erpnext`, no raw SQL against ERPNext tables, no core edits, additive schema only. Dropping
  those would make later v16 work expensive rather than cheap, which is the whole point.
- When a v16 bench appears, the work is: run `scripts/ci-local.sh` against it, fix `compat.py`,
  refresh fixtures.

---

## ADR-016 — Both sales models ship, switched by FieldMate Settings

**Decision.** FieldMate supports **order booking** and **van sales**, chosen by configuration
rather than by a fork in the codebase.

`FieldMate Settings` gains:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enable_order_booking` | Check | 1 | The rep books an order; the distributor delivers later |
| `enable_van_sales` | Check | 0 | The rep sells and delivers from a vehicle, billing on the spot |
| `default_sales_mode` | Select | Order Booking | Used when a rep has no explicit mode |

`FieldMate Field User` gains `sales_mode` (Select: *Company Default* / *Order Booking* /
*Van Sales*), because in practice the two models coexist in one company: a van route in a town
and order-booking reps in the district around it.

**Reason.** Owner decision, 21 Sep 2026. Both models are needed. Making it configuration keeps a
single codebase and a single test suite.

**This amends ADR-013.** That ADR said outlets are never billed directly. That remains true in
**order booking**, which is the default. In **van sales the shop is billed on the spot**, so
`FieldMate Outlet.customer` becomes live in that mode, along with an outlet-level credit limit.
The field was already planned as optional and dormant, so the schema does not change — only when
it is populated.

**This does NOT weaken ADR-004.** A rep still never holds write permission on an accounting
DocType. A van sale calls a whitelisted method; the **server** validates it and posts the
resulting documents with elevated permission, exactly as `FieldMate Order` already creates a
Sales Order. What a rep can do is still bounded by what the server will do on their behalf, not
by what their role can touch.

**Consequences.**
- Credit resolves against the **distributor** in order booking and against the **outlet** in van
  sales. One branch point, in `fieldmate/services/credit.py`, never scattered.
- Van sales posts a Sales Invoice plus a stock movement out of the vehicle warehouse at the time
  of sale. Order booking posts a Sales Order and nothing else.
- The vehicle is an ERPNext `Warehouse`. Load-out and settle-in are `Stock Entry` documents.
- Phase 1 must build the settings and the mode field even though van sales itself lands in
  Phase 5, so no outlet data has to be migrated later.
- Every scheme, credit and collection test gets a van-sales variant. Two modes means two paths
  through the same money, and an untested second path is where the money goes missing.

## ADR-017 — Nothing is blocked in the field except an answerable question

**Decision.** A visit is never refused for being in the wrong place, off the planned route, too
short, or reported from a mocked location. Each is recorded, flagged, and surfaced on the
**Visit Exceptions** report. The single exception: a required checklist question must be
answered before check-out **when the shop was actually open** — outcomes of *Outlet Closed* and
*Owner Absent* skip the requirement.

**Reason.** A rep who is blocked stops using the app, and an app nobody uses produces no data at
all. Blocking a 400 m check-in does not make the rep walk closer; it makes them stop checking in.
The bargain is that everything unusual is captured rather than prevented — which only holds if
somebody reads it, hence the report shipping in the same phase as the flags.

A required question is different in kind: the rep is standing in the shop and can answer it. But
they cannot describe a shelf behind a shutter, so the requirement lifts when the shop was never
open.

**Consequences.**
- `is_geo_fence_breach`, `is_short_visit`, `is_deviation` and `is_mock_location` are evidence,
  not gates.
- The **Visit Exceptions** report is the other half of the bargain and is not optional.
- Off-beat alone is excluded from that report by default. A rep covering for a colleague is
  ordinary, and listing every one of them would bury the visits that need a look.
- `auto_close` does not demand required answers: the rep has already walked into the next shop,
  and refusing would strand them outside it.

## ADR-018 — Evidence is recomputed on every save, not validated on one path

**Decision.** Distance from the shop, fence breach, planned-vs-deviation, duration and
short-visit are derived in `FieldMateVisit.validate()` — the DocType controller — not in the
API service. Checklist question wording, version and requiredness are re-snapshotted from the
template in the same place. The sync registry additionally lists them as `server_owned` so a
push cannot even propose a value.

**Reason.** `visit.check_in` is not the only way a visit arrives. The offline queue pushes rows
straight through `frappe.get_doc`, and `read_only` in a DocType JSON only greys out a desk
field — it stops nothing over REST. Validating in the service would have left the offline path,
which is the majority path, entirely unguarded.

The same argument applies to the checklist: a phone with a stale or edited cache could otherwise
record a visit as having asked a question it never asked, which is the one thing a checklist
exists to prove. The rep's *answer* is kept exactly as sent; everything describing the question
is rewritten from the template.

**Consequences.**
- Belt and braces on purpose: `server_owned` strips the fields, and the controller recomputes
  them anyway. Either alone would be a single point of failure.
- An answer to a question since retired is kept but disclaims itself — `template` cleared,
  `is_required` 0. The rep did the work; nothing about it is claimed as current.
- An approved Geo Fence Exception clears the breach flag; a pending one does not. Until a human
  has looked, the breach stands.

## ADR-019 — Photos travel on their own queue, and land after the record

**Decision.** Visit photos are not outbox rows. They live in a separate IndexedDB queue, upload
one request at a time through `visit.upload_photo`, and are keyed to the visit's `client_uuid`
rather than its server name. `FieldMate Visit.photos` is `allow_on_submit`.

**Reason.** A compressed shelf photo is ~120 KB against a visit record's ~2 KB. Sharing one FIFO
means a whole day of records waits behind a single photo crawling up a 2G uplink, and a manager
sees no coverage until the pictures finish. Records must go first.

The consequence is that a photo routinely arrives **after** its visit has synced and been
submitted. Without `allow_on_submit` the picture has nowhere to go — which is exactly what Gate 3
criterion 3 caught.

**Consequences.**
- The client-to-server name mapping has to outlive the outbox row that produced it, so
  successful pushes write into a `names` table.
- A replayed batch must therefore still return per-record results. It does, rebuilt from the
  `client_uuid` unique index rather than stored on the batch — see the note in `sync._replay_results`.
  Answering a replay with only a summary would orphan every queued photo.
- Images are deleted from the device the moment the server confirms them. They are the heaviest
  thing the phone holds.
- A cancelled visit is the one case where a late photo is refused.

## ADR-020 — Scope is matched against the territory tree, never by name equality

**Decision.** Checklist templates, must-sell lists and every future scoped master are matched
through `fieldmate/services/scope.py`. A scope territory covers itself **and all its
descendants**. Blank means everywhere.

**Reason.** A survey scoped to *North* must reach a shop in *North / Delhi / South Delhi*.
Comparing names for equality silently excluded every shop not pinned to the exact node a planner
happened to pick. Worse, Frappe fills an empty Territory link from the session's own defaults, so
templates nobody ever scoped arrived pinned to the root and matched nothing at all — the bug
presented as "checklists never appear", with no error anywhere.

**Consequences.**
- One module, because getting this subtly wrong in four places is how a rep ends up answering the
  wrong survey at the right shop.
- The phone cannot evaluate a tree it holds only leaves of, so its client-side match ignores
  territory. That decides what the rep is *shown*; the server re-snapshots what is *recorded*.
- The same session-default injection breaks `Customer` inserts when Selling Settings names a
  group node, which is why test fixtures now name a non-group Customer Group explicitly rather
  than inheriting one.

## ADR-021 — The scheme engine is a pure function over a pre-compiled spec

**Decision.** Scheme evaluation is split in two. A **compiler** on the server resolves scope,
expands item groups, converts cases to base units and rupees to paise, and emits a flat JSON
**compiled spec** with no lookups left in it. An **evaluator** — `services/scheme_engine.py` and
`frontend/src/scheme/engine.js` — is a pure function of `(cart, specs)`. It never reads the
database, resolves a price, converts a UOM or reads a clock. `docs/SCHEME_SPEC.md` is normative:
where the two engines disagree, the one that disagrees with the document is the one that is wrong.

**Reason.** The plan asks for the engine "written once, compiled to both Python and JS, never two
implementations". Two runtimes mean two bodies of code however it is arranged; what can genuinely
be made singular is *everything that decides an outcome*. Pushing every ambiguous decision into
the compiler leaves an evaluator small and dumb enough that its duplication is auditable — the
two files are step-for-step mirrors with the same function names and the same `S4 —` comments, so
a reviewer diffs them side by side.

The alternative, transpiling Python to JS at build time, buys a weaker guarantee at a much higher
cost: the generated file still has to be reviewed, and a transpiler bug is harder to see than a
divergent line.

**Consequences.**
- Parity is provable rather than hoped for: both sides are handed byte-identical input, so any
  difference is in the ~200 lines of evaluator and nowhere else.
- A pricing or scope bug can never present as a parity failure, because neither is in the engine.
- The phone must cache compiled specs from `sync.pull`, not scheme masters. A scheme edited in
  Desk does not reach a rep until the next pull — which is correct, and must be visible in the UI
  rather than silent.
- The case corpus is authored from the specification by someone who has not read the engines.
  Deriving expectations from the implementation would make Gate 4 a tautology.

## ADR-022 — Money in the scheme path is integer paise, and never a float

**Decision.** Inside the engine every amount is an integer count of paise and every percentage an
integer count of basis points. One rounding primitive exists,
`round_half_up_div(n, d) = floor((2n + d) / (2d))`, implemented with integer arithmetic in both
languages. `round()`, `Math.round()`, `flt()` and `toFixed()` are banned from the money path.

**Reason.** The two runtimes agree on IEEE-754 arithmetic but not on rounding: Python's `round()`
is banker's rounding, `Math.round(-0.5)` is `-0` in JS and `0` in Python, and Frappe's `flt()` is a
third behaviour again. A scheme is exactly the code where a half-paise lands on a boundary often
enough to matter, and Gate 4 allows zero divergence. Integer arithmetic removes the question
instead of testing it.

**Consequences.**
- Floats survive at exactly one boundary, `to_paise(rupees) = floor(rupees * 100 + 0.5)`, and that
  runs in the compiler on the server — the evaluator is handed paise and never calls it.
- Every product stays under 2^53, so `Math.floor` and `//` are exactly equal. The largest realistic
  term is `base_paise * pct_bp` at roughly 10^15.
- DocType fields stay `Currency` in rupees, because Desk and the people reading it work in rupees.
  Conversion happens at the service boundary, in one place, in both directions.

## ADR-023 — A retailer order is a secondary sale and never becomes a Sales Order

**Decision.** A `FieldMate Order` booked by a rep at a retail outlet is a **secondary sales order**.
It is terminal in our books: no Sales Order, no Sales Invoice, no GL Entry, no stock movement. It
routes to the distributor's order queue, and the distributor bills the shop from their own stock.

The company's revenue event happens one step later and is a different document: the **distributor's
primary order on us**. That is where an ERPNext Sales Order belongs.

```
Rep → FieldMate Order (secondary) → distributor's queue
                                     ↓
                        distributor bills the shop
                                     ↓
                    distributor raises a PRIMARY order on the company
                                     ↓
                            ERPNext Sales Order
```

**Reason.** Primary and secondary are different sales in different books. We never invoice a kirana
shop, so booking a Sales Order when a rep punches one would:

- book revenue on a sale the company did not make;
- consume the distributor's credit limit for stock they have not asked us for;
- double-count against stock the distributor may already be holding.

This is not a new principle, it is the one the app already states and was about to contradict.
ADR-001 says a retail outlet is not a Customer because "we never invoice them". Gate 5 criterion 4
says in as many words: **no secondary sales document produces a GL Entry.** Build-plan task 4.9
("Sales Order creation in `on_submit`") and Gate 4 criterion 2 ("one FieldMate Order and one Sales
Order") were written against the wrong half of that model. **This ADR supersedes both.**

**The two exceptions, and they are the same exception.** An ERPNext document is created only where
*we* are genuinely the seller:

- **Van sales** (ADR-016) — we bill the shop at the counter, so a Sales Invoice plus a stock issue
  out of the vehicle warehouse is correct.
- **A directly-billed outlet** — ADR-001's escape hatch, `FieldMate Outlet.customer` populated.

Both are the same test — "is the billing party us?" — and both are answered in one place,
`services/credit.py`, never with an `if van_sales:` scattered through the order code.

**Consequences.**
- `FieldMate Order.order_status` carries the secondary lifecycle: Draft → Sent To Distributor →
  Accepted → Invoiced → Delivered, plus Cancelled and Rejected. `sales_order` stays empty in the
  default mode and is populated only under the exceptions above.
- **Credit changes meaning.** In order booking the limit that matters is the *shop's* limit with
  *its distributor*, which is what a rep is shown at the counter. We do not do that accounting, so
  we hold it as a **soft ledger** — it warns and can block per settings, but posts nothing. The
  distributor's own hard credit limit is only consulted where a real ERPNext document is created.
- Gate 4 criterion 2 is rewritten: *an offline order creates exactly one `FieldMate Order`, routed
  to exactly one distributor queue, and **no** accounting document.* Cancelling it withdraws it from
  the queue; the cancel cascade only reaches ERPNext under the exceptions.
- Phase 9's distributor portal is no longer optional polish — it is the other end of this pipe. Until
  it ships, the queue is a Desk list view filtered by distributor, which is enough to pilot.

## ADR-024 — Van sales is the distributor's sale too, so it posts nothing either

**Decision.** Van sales is **not** a case where the company sells. The stock in the vehicle belongs
to the **distributor**; the rep carries it and hands it over at the counter. So a van sale is a
**secondary** sale exactly like a booked order, and it creates no Sales Order, no Sales Invoice, no
GL Entry and no Stock Entry in our books.

`credit.we_are_the_seller()` is therefore left with exactly **one** case: an outlet the company
genuinely invoices direct, which is ADR-001's escape hatch. Everything else routes to the
distributor.

**This supersedes the second half of ADR-016.** That ADR said "in van sales the shop is billed on
the spot" and made `FieldMate Outlet.customer` live in that mode. The first half still stands — both
models ship, chosen by configuration — but the billing claim was wrong.

**Reason.** Owner correction, 25 Sep 2026: *"van sale bhi billing distributor ko hota hai, na ki
company ko — van sale = distributor, bas sales person carry karta hai apne paas."*

Van sales is not a different **seller**, it is a different **delivery timing**:

| | Order booking | Van sales |
|---|---|---|
| Who sells to the shop | the distributor | the distributor |
| Whose stock | the distributor's | the distributor's |
| When the goods move | delivered later | handed over at the counter |
| What reaches our books | nothing | nothing |

Modelling it as a company sale would have done precisely what ADR-023 was written to prevent, one
mode later: revenue recorded on a sale we did not make, and a Stock Ledger holding goods we had
already sold to the distributor at primary billing.

**Consequences.**
- Build-plan task 5.4, "vehicle-as-Warehouse Stock Entries", is wrong and is rewritten. A vehicle
  is **not** an ERPNext `Warehouse`, because the stock in it is not ours to hold. `FieldMate Van
  Load` and `FieldMate Van Settlement` record the movement at FieldMate level for operational
  control — what went out, what was sold, what came back — and post nothing.
- `FieldMate Field User.vehicle_warehouse` loses its meaning. It stays as a field (schema is
  append-only, compat rule 5) but nothing reads it; the van is identified by the Field User.
- Gate 5 criterion 3 said "van load → 3 cash sales → settle-in leaves vehicle stock at zero and
  the **Stock Ledger** balanced". Rewritten: the vehicle's FieldMate stock returns to zero and
  reconciles to what was loaded, and **the Stock Ledger is not touched at all**.
- Gate 5 criterion 4 — *no secondary sales document produces a GL Entry* — now covers van sales
  as well, which is the whole point.
- What still differs between the two modes is *when* stock moves and *when* money is collected,
  not who sells. That difference lives in Phase 5 and Phase 6, not in `credit.py`.

## ADR-025 — Who the cash belongs to is decided by who it was collected from

**Decision.** A collection carries a **party type**, and that one field decides everything
downstream:

| Collected from | Whose money | What it reduces | What it posts |
|---|---|---|---|
| **A retail shop** | the **distributor's** | the shop's soft ledger with that distributor | **nothing** |
| **A distributor** | **ours** | the distributor's real outstanding with us | a `Payment Entry`, **on deposit confirmation only** |

The test lives in `services/collection.py` and is asked once, exactly as
`credit.we_are_the_seller()` is asked once for orders. There is no `if outlet:` scattered through
the deposit, bounce or snapshot code.

**Reason.** Owner decision, 25 Sep 2026, and it follows from where the sale happened. A shop buys
from its distributor (ADR-023, ADR-024), so what it owes is owed to the distributor and the rep
collecting it is carrying the distributor's money — recording a Payment Entry would credit us for
cash we never earned and reduce an ERPNext receivable that was never raised. A distributor buys
from us, so what they owe is ours and a Payment Entry is exactly right.

The rep's own hands look identical in both cases, which is the trap: the same person, the same
receipt book, the same satchel. Only the counterparty differs, so only the counterparty may decide.

**Consequences.**
- **No Payment Entry is created when a collection is recorded**, in either case. Gate 6
  criterion 2 asks for that in as many words, and adds that a rep role may not create one
  directly — which they cannot, because they hold no permission on the DocType at all (ADR-004).
  The posting happens on `FieldMate Collection Deposit` confirmation, through `compat`, and only
  for money that was ours to begin with.
- A shop collection still needs a deposit: the rep is holding the distributor's cash and it has
  to be accounted for and handed over. That deposit posts nothing, exactly like a van settlement
  (ADR-024). Cash-in-hand ageing applies to both, because the risk is the satchel, not the ledger.
- Outstanding has two sources. A distributor's comes from ERPNext through `compat.get_outstanding`.
  A shop's is ours to hold, because nobody else does — it accrues from `FieldMate Order` and is
  reduced by collections, and it is a **soft** ledger that posts nothing.
- A bounced cheque reverses whichever of the two it was, and a bounce on a distributor cheque
  additionally cancels its Payment Entry.

## ADR-026 — A claim is settled as trade spend, not as a return of goods

**Decision.** An approved `FieldMate Claim` produces exactly one accounting document: an ERPNext
**Sales Invoice with `is_return = 1`** against the distributor's Customer, carrying **one line**
on a configured settlement item, debiting a configured **trade scheme expense account** at a
configured **cost centre**, with `update_stock` off.

It is raised on **approval**, never on submission, and never per SKU.

**Reason.** The goods reached the distributor at primary billing, at full price, and that sale
stands. What is being settled is the cost of a promise a rep made at a shop counter out of the
distributor's stock — trade spend, not a return.

Crediting the SKUs instead would do two wrong things at once. It would restate product revenue
for a return that never happened, and — with `update_stock` off, which it must be — it would do
so while putting no goods back. A brand manager reading item-wise credit notes sees a sales
shortfall where the truth is a scheme that worked.

`update_stock` is off for the same reason every other secondary document in this app posts no
stock (ADR-023, ADR-024): from primary billing onward the stock is the distributor's.

**Consequences.**
- Three settings carry the configuration: `claim_settlement_item`, `claim_expense_account`,
  `claim_cost_center`. The expense account and cost centre fall back to the item and company
  defaults; the settlement item does not fall back, and `compat.make_credit_note` **refuses to
  post without one** rather than inventing an item.
- Approval and settlement are separate states on the claim, because at most companies they are
  separate decisions weeks apart. `approve(..., settle=True)` does both where they are one person.
- The credit note is keyed on `CLAIM:<name>` in `fm_source_key`, so an approval clicked twice on
  a slow connection returns the note that already exists. `Sales Invoice` joins `Sales Order` and
  `Payment Entry` in `IDEMPOTENCY_FIELDS`.
- An **Incentive** ledger row is never claimable. It is what the rep earned; it never came off a
  shop bill and the distributor was never out of pocket for it. Claiming it would pay the same
  money twice.
- Reversal cancels the note **before** releasing the claim, because Frappe checks back-links
  first. That is the third time this trap has been hit — Scheme Ledger on order cancel, Payment
  Entry on a bounced collection, and now this — so it is a test rather than a comment.

## ADR-027 — The portal is scoped in two places, and neither is the template

**Decision.** Every distributor portal session resolves through one function, `portal.me()`,
which reads a `FieldMate Portal User` row. Scoping is then applied **twice**: in the service
layer, where `assert_scope` refuses a document belonging to another depot, and at the framework
layer, through `permission_query_conditions` and `has_permission` hooks on `FieldMate Order` and
`FieldMate Claim`.

A portal user holds `read` and nothing else on any DocType. Every move is server-elevated after
the scope check — the same posture as a Field Rep (ADR-004).

**Reason.** The service layer covers the two screens the portal ships. The framework layer covers
everything else: a report, a Desk list, an `api.resource` call, a query added next year by
somebody who has never read this file. Either one on its own is a rule with a hole in it.

A depot login is an ordinary Frappe login, so a `FieldMate Portal User` attached to a System
Manager or a FieldMate Admin is refused at validation. Such an account would read as scoped while
carrying permissions no narrowing here could take away.

**Consequences.**
- Gate 9 criterion 1 is asserted as a **refusal**, not an absence. Absence from a list proves
  nothing on a site where the fixture created nothing, so the gate builds a second distributor
  with a real order and goes after it by name, through both layers.
- `FieldMate Order` gains `pull=True` in the sync registry. The depot now moves an order through
  its own states, and the rep is the person the shopkeeper asks the next morning; without a pull
  the phone would still read "Sent To Distributor" on an order delivered on Tuesday. Push is
  unchanged: `order_status`, `sent_to_distributor_on` and `distributor_reference` stay
  server-owned, or the queue would be decorative.
- Every move the depot makes appends a `FieldMate Order Ingest Log` row in the same call, keyed
  on order-plus-target-state, so a second tap on a bad connection is the same answer rather than
  a second event a minute later.

## ADR-028 — Five target types are split; the sixth is copied

**Decision.** Of the six target types, **five are quantities and are divided** among a node's
children when a plan cascades: Value, Volume, Outlet Coverage, Productive Calls, New Outlets.
The sixth, **Lines Per Call, is a rate and is copied to every child unchanged.**

The division happens in **whole units** — paise for money, ones for counts — by largest
remainder, and the leftover units go to the largest share, recorded on the parent.

**Reason.** Gate 7 criterion 1 says "the leaves sum to the root for every target type", and read
literally that is wrong for one of the six. A root asking for 4.5 lines per productive call is
asking *each* rep for 4.5. Dividing it between twenty reps would set each of them a target of
0.225 lines, which is not a smaller version of the same goal — it is a different, meaningless
one. A rate has no total.

The integer split is the other half. Ten lakh divided three ways in floating point and stored to
two places gives three numbers that add up to ₹9,99,999.99. Nobody finds that here; they find it
at month end, in a regional report that is a rupee short, with no way to say which rep is
carrying the difference. Largest remainder in paise makes the sum exact by construction, and
ties break on position so a re-run produces the same answer — a cascade that moved the spare
rupee between reps on every run would be uncheckable.

**Consequences.**
- `target.reconcile()` reports **per type**, not one verdict: an additive type reports root
  against the sum of the leaves, a ratio type reports root against the *set* of leaf values and
  passes only when that set is exactly `{root}`. One boolean could not carry both.
- `FieldMate Target Line.is_additive` is stamped from the type at save and stored, so a plan
  cascaded a year ago can still be read against the rule that was in force when it ran.
- **Shortfall is zero on a ratio line.** A rep at 4.2 against 4.5 is not "0.3 lines behind";
  they are selling narrower carts. A shortfall figure there would be summed into a total
  somewhere and mean nothing.
- The headline percentage on the rep's screen is the **Value** line, not an average of the six.
  Averaging a rupee target with a lines-per-call target does not produce a quantity.
- Default cascade weight is **outlet count**, because a rep with 280 shops cannot carry the same
  number as one with 90 and it is the one weight every site already has without maintaining it.

## ADR-029 — The distance is the server's, the claim is the rep's, the gap is the manager's

**Decision.** A `FieldMate Expense Claim` for travel takes its distance from `FieldMate Location
Trail`, computed server-side. The rep may claim **more**, and the claim is accepted — but any
excess beyond a configured tolerance marks the claim `needs_approval`, and **a rep cannot
approve their own claim** at all.

An approved claim settles as a **draft HRMS Expense Claim** — the fourth and last crossing out
of FieldMate, and the only one that pays a person rather than a party.

**Reason.** Both halves of the rule are load-bearing and pull in opposite directions.

A device that could state its own mileage could invent it, and this is the one figure in the app
that turns directly into money. So the trail is read, never accepted.

But a trail is *evidence, not truth*. It drops pings in a basement car park and in a market with
no signal, and a rep who walked a beat for six hours has a real claim against a thin recording.
Refusing anything above the trail would make the honest case unfileable, so the excess is
measured and routed to somebody who can weigh it, along with the ping count so they can tell
four readings from four hundred.

**Consequences.**
- `travel_rate_per_km` has **no default**. A claim is refused with a message naming the setting
  rather than priced at zero — inventing a rate would quietly pay every rep a number nobody at
  the company chose.
- The rate is **frozen onto the claim** when it is filed, not read at approval. A rate changed
  in between must not restate the figure the rep saw on the screen.
- The HRMS document is left as a **draft**. Submitting it books a liability and, on many sites,
  starts an approval workflow of its own that this app has no business short-circuiting.
  FieldMate says what is owed; HR decides when it is payable.
- Where HRMS is absent, `compat.make_expense_claim` returns None and the claim settles with
  nothing behind it, saying so. A site running FieldMate before HRMS still has reps owed money,
  and refusing to record that they were paid would be the worse answer.
- A rep's own targets, achievement, payouts and claims are scoped by
  `permission_query_conditions` and `has_permission` (as ADR-027 does for the portal). Territory
  scoping cannot do this: a target belongs to a person, not a place, and two reps routinely
  share a territory.
