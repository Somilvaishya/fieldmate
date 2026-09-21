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
