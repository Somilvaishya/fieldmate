# TASKS — FieldMate Field Force

Loop: **TASK → Implement → Test → Review → Mark complete → Next TASK.**
Never build a whole layer. Never take on more than one task at a time.

Phases and gate criteria: `fieldmate` skill → `references/build-plan.md`. Do not invent a different
phase numbering.

A task is complete when: implemented, working on `testerp2`, tests green on `dev-15`,
`MEMORY.md` updated, reviewed against `RULES.md` and `SECURITY.md`.

---

## Phase 0 — Foundation and sync spine · 1 week

- [x] 0.1 `bench new-app fieldmate` (--no-git), module layout, `hooks.py`, `required_apps`
- [ ] 0.1b `git init` + first feature branch (needs approval)
- [x] 0.2 Roles: Field Rep, Area Manager, Regional Manager, Sales Head, Admin, Distributor
- [x] 0.3 `required_apps` + `after_install` version guard (Frappe/ERPNext/HRMS minimums)
- [x] 0.4 `fieldmate/compat.py` skeleton + first four adapters + capability probe
- [x] 0.5 DocType `FieldMate Device Registry` (16 fields)
- [x] 0.6 DocType `FieldMate Sync Batch` (21 fields)
- [x] 0.7 DocType `FieldMate Sync Conflict` (20 fields)
- [x] 0.8 `fieldmate/api/_base.py` — auth helper, `ok()` / `fail()` envelopes, `v` param handling
- [x] 0.9 APIs: `auth.login`, `auth.bootstrap`, `sync.register_device`
- [x] 0.10 APIs: `sync.pull`, `sync.push`, `sync.status`, `sync.resolve_conflict`
- [x] 0.11 PWA scaffold: Vite + Vue 3, routing, `website_route_rules` mount
- [x] 0.12 Dexie schema + outbox with dependency ordering and backoff
- [x] 0.13 Workbox service worker, install prompt, offline state strip
- [x] 0.14 Three-lane CI matrix written (`.github/workflows/ci.yml`) — NOT yet run
- [x] **Gate 0 — PASSED** (21 Sep 2026, v15 scope per ADR-015)
  - [x] 1. Installs clean on v15, and refuses an unsupported host with a readable message
        *(installed on testerp2; 6 guard tests in `test_install.py`)*
  - [x] 2. PWA installs to an Android home screen and opens offline
        *(confirmed on a real device: standalone, no address bar, offline shell + cached profile)*
  - [x] 3. Same batch of 20 pushed 3x creates exactly 20 documents *(`test_sync.py`)*
  - [x] 4. A bad record becomes one Sync Conflict; the rest of the batch still commits
  - [x] 5. Lint and tests green on v15 *(`scripts/ci-local.sh` — ruff clean, 42 tests)*

## Phase 1 — Masters and hierarchy · 2 weeks

- [x] 1.1 `FieldMate Settings` (single, 24 fields) + feature flags, incl.
      `enable_order_booking`, `enable_van_sales`, `default_sales_mode` (ADR-016)
- [x] 1.2 `FieldMate Field User` (22 fields, + `sales_mode`) + territory User Permission
      generation
- [x] 1.3 `FieldMate Outlet Channel` (6), `FieldMate Outlet Class` (8)
- [x] 1.4 `FieldMate Outlet` (46 data fields) + `FieldMate Outlet Contact` — `customer` and
      outlet credit present but refused unless van sales is on (ADR-013, ADR-016)
- [x] 1.5 `FieldMate Beat` (18 data fields) + `FieldMate Beat Outlet` (8), plus the
      `primary_beat` back-reference on Outlet
- [x] 1.6 `FieldMate Distributor Profile` (20 data fields)
- [x] 1.7 `FieldMate Product Catalogue` (12) + `FieldMate Catalogue Item` (8)
- [x] 1.8 `FieldMate Must Sell List` (12) + `FieldMate Must Sell Item` (5)
- [x] 1.9 `FieldMate Geo Fence Exception` (submittable, 17 data fields)
- [x] 1.10 APIs: `outlet.search`, `outlet.detail`, `outlet.create`, `outlet.update`,
      `outlet.approve`, plus `outlet.import_template` and `outlet.bulk_import`
- [x] 1.11 Bulk import with per-row geo validation and dry run
- [x] 1.12 PWA: outlet list, Outlet 360, new-outlet onboarding, beat browse
- [x] **Gate 1 — PASSED** (21 Sep 2026)
  - [x] 1. 5,000 outlets and 200 beats imported clean; mixed files report per row
  - [x] 2. A rep sees only their territory — proven in tests three ways
  - [x] 3. Field-created outlet lands Pending, visitable, not sellable
  - [x] 4. 500-outlet pull: **8 KB gzipped**, 224 KB raw, budget 2,560 KB
        (first measured 6,614 KB — `pull_fields` was unset, sending all 46 columns)

## Phase 2 — Journey plan and attendance · 1.5 weeks

- [ ] 2.1 `FieldMate Deviation Reason`
- [ ] 2.2 `FieldMate Journey Plan` + `FieldMate Journey Plan Day`
- [ ] 2.3 Plan generator (frequency, week pattern, holidays, approved leave)
- [ ] 2.4 `FieldMate Day Start`, `FieldMate Day End`
- [ ] 2.5 `FieldMate Location Trail` (one row per rep per day)
- [ ] 2.6 `FieldMate Attendance Summary`
- [ ] 2.7 `Employee Checkin` write-through via compat
- [ ] 2.8 Mock-location detection + trail plausibility
- [ ] 2.9 APIs: `day.start`, `day.current`, `day.end`, `day.trail_upload`, `beat.today`, `beat.outlets`
- [ ] 2.10 PWA: Day Start (selfie + GPS), Today board, Day End, background ping batching
- [ ] **Gate 2** — verify all 5 criteria on testerp2

## Phase 3 — Visit execution · 3 weeks

- [ ] 3.1 `FieldMate No Order Reason`
- [ ] 3.2 `FieldMate Visit` (42 fields) + `FieldMate Visit Task` + `FieldMate Visit Photo`
- [ ] 3.3 Geo-fence evaluation + exception workflow + short-visit detection
- [ ] 3.4 `FieldMate Checklist Template` / `Question` / `Answer` with versioning
- [ ] 3.5 `FieldMate Merchandising Audit` + `Line` + `FieldMate Competitor Capture`
- [ ] 3.6 APIs: `visit.check_in`, `visit.save_tasks`, `visit.upload_photo`, `visit.check_out`
- [ ] 3.7 Client-side image compression + out-of-band photo queue
- [ ] 3.8 PWA: check-in sheet, visit hub, merchandising capture, survey renderer, no-order sheet, check-out
- [ ] **Gate 3** — verify all 5 criteria on testerp2

## Phase 4 — Orders and scheme engine · 3 weeks

- [ ] 4.1 Scheme rule specification format (the single source both engines compile from)
- [ ] 4.2 `FieldMate Scheme` + `Slab` + `Item` + `Scope`
- [ ] 4.3 Python scheme engine in `fieldmate/services/scheme.py`
- [ ] 4.4 JS scheme engine compiled from the same spec
- [ ] 4.5 60-case parity suite — **zero tolerance for divergence**
- [ ] 4.6 `FieldMate Scheme Ledger` + budget accrual
- [ ] 4.7 `FieldMate Order` + `Order Item` + `Scheme Applied` + `Free Goods`
- [ ] 4.8 `FieldMate Order Approval Rule` + credit check via compat + override workflow
- [ ] 4.9 Sales Order creation in `on_submit` (idempotent) + cancel cascade
- [ ] 4.10 APIs: `catalogue.items`, `catalogue.prices`, `scheme.applicable`, `scheme.evaluate`
- [ ] 4.11 APIs: `order.estimate`, `order.submit`, `order.list`, `order.cancel`, `order.approve`
- [ ] 4.12 PWA: catalogue, cart with repeat-order prefill, scheme preview, review and submit
- [ ] **Gate 4** — verify all 6 criteria on testerp2

## Phase 5 — Secondary sales and van · 2 weeks *(van sales IN scope, ADR-016)*

- [ ] 5.1 `FieldMate Retailer Stock` + `Item`, implied offtake calculation
- [ ] 5.2 `FieldMate Secondary Sales` + `Item` + distributor upload pipeline
- [ ] 5.3 `FieldMate Distributor Stock`
- [ ] 5.4 `FieldMate Van Load`, `FieldMate Van Settlement`, vehicle-as-Warehouse Stock Entries
- [ ] 5.5 APIs: `stock.retailer_stock_save`, `stock.secondary_sales_upload`
- [ ] 5.6 PWA: stock & sales audit, van load sheet, settlement
- [ ] **Gate 5** — verify all 4 criteria on testerp2

## Phase 6 — Collections · 1.5 weeks

- [ ] 6.1 `FieldMate Collection` + `FieldMate Collection Allocation`
- [ ] 6.2 `FieldMate Collection Deposit` + Payment Entry posting via compat
- [ ] 6.3 Bounce reversal path
- [ ] 6.4 `FieldMate Outstanding Snapshot` + cash-in-hand ageing alert
- [ ] 6.5 APIs: `collection.outstanding`, `collection.create`, `collection.list`, `collection.deposit`
- [ ] 6.6 PWA: outstanding with ageing, collection entry with receipt photo, deposit declaration
- [ ] **Gate 6** — verify all 5 criteria on testerp2

## Phase 7 — Targets, incentives, expenses · 2 weeks

- [ ] 7.1 `FieldMate Target Plan` + `FieldMate Target Line` + cascade down the Sales Person tree
- [ ] 7.2 `FieldMate Achievement` + nightly computation (6 target types)
- [ ] 7.3 `FieldMate Incentive Scheme` + `Slab` + `FieldMate Incentive Payout`
- [ ] 7.4 Expense Claim extension with GPS-derived distance
- [ ] 7.5 APIs: `target.my_targets`, `target.achievement`, `expense.create_claim`, `expense.my_claims`
- [ ] 7.6 PWA: My performance, claim entry
- [ ] **Gate 7** — verify all 5 criteria on testerp2

## Phase 8 — Analytics and alerts · 1.5 weeks

- [ ] 8.1 `FieldMate KPI Snapshot` (30 fields) + nightly/hourly rollups
- [ ] 8.2 The nine core metrics
- [ ] 8.3 `FieldMate Dashboard Preset` + Desk workspaces
- [ ] 8.4 Insights datasets pointed at the snapshot
- [ ] 8.5 `FieldMate Alert Rule` + the five exception alerts
- [ ] 8.6 Dashboard charts / number cards in `<slug>/<slug>.json` subfolders
- [ ] 8.7 APIs: `dashboard.rep_today`, `dashboard.rep_month`, `dashboard.manager_summary`
- [ ] **Gate 8** — verify all 5 criteria on testerp2

## Phase 9 — Distributor portal and claims · 1.5 weeks

- [ ] 9.1 `FieldMate Claim` + `FieldMate Claim Item` from the Scheme Ledger
- [ ] 9.2 Claim approval + Credit Note via compat
- [ ] 9.3 `FieldMate Portal User`, `FieldMate Order Ingest Log`
- [ ] 9.4 Portal web pages + APIs: `portal.distributor_orders`, `portal.claim_status`
- [ ] **Gate 9** — verify all 4 criteria on testerp2

## Phase 10 — Hardening and pilot · 2 weeks

- [ ] 10.1 Load test: 250 concurrent syncs in a 30-minute window
- [ ] 10.2 Security pass: RBAC per DocType, API authorisation, private files, GPS PII
- [ ] 10.3 Battery profiling: 9-hour day with GPS
- [ ] 10.4 Field pilot: 10–15 reps, two weeks, daily triage
- [ ] 10.5 Docs: admin setup, rep quick-start (local language), upgrade runbook
- [ ] **Gate 10** — go / no-go, all 5 criteria
