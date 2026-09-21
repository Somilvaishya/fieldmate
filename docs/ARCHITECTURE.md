# ARCHITECTURE — FieldMate Field Force

**Architecture = HOW.** What and why is in PRD.md.

## Stack

| Layer | Choice |
|---|---|
| Field client | Vue 3 (Composition API) + Vite, installable PWA |
| Local store | Dexie (IndexedDB) |
| Service worker | Workbox via `vite-plugin-pwa` |
| Manager client | Frappe Desk + Insights (no custom SPA in v1) |
| Distributor client | Frappe portal web pages |
| Backend | Frappe `15.118.0` custom app `fieldmate` |
| Business layer | ERPNext `15.119.1` + HRMS |
| Database | MariaDB (Frappe-managed) |
| Auth | Frappe session + device binding |
| Background | Frappe Scheduler + RQ workers |
| Deployment | `testerp2.web.gargsystems.com` (verify), `dev-15.local` (tests) |

## Data flow

```
Rep device                     Server                          Book of account
──────────                     ──────                          ───────────────
Vue screen
   ↓ reads
Dexie (local truth)
   ↓ outbox (client_uuid)
   └──── HTTPS ────→  fieldmate.api.*  ──→  fieldmate/services/  ──→  fieldmate/compat.py ──→ ERPNext
   ←──── delta pull ──┘                    ↓                                  ↓
                                    FieldMate DocTypes                    Sales Order → DN → SI
                                                                    Payment Entry, Credit Note
                                                                           ↓
                                                                       GL Entry
```

Three crossings into ERPNext, each on a submit or approval event, each idempotent, each recording
the created document's name back on the FieldMate record:

1. `FieldMate Order` submit → Sales Order
2. `FieldMate Collection` deposit confirmation → Payment Entry
3. `FieldMate Claim` approval → Credit Note

**Secondary sales never cross.** They are market intelligence, not accounting.

## Folder structure

```
apps/fieldmate/
  fieldmate/
    api/              thin whitelisted controllers (fieldmate.api.*)
      _base.py        auth helpers, ok()/fail() envelopes
      sync.py  visit.py  order.py  collection.py  ...
    services/         ALL business logic, plain testable functions
      visit.py  order.py  scheme.py  collection.py  ...
    fieldmate/doctype/      the 68 FieldMate DocTypes
    compat.py         THE ONLY module importing erpnext.*
    fixtures/         Custom Field / Property Setter exports (fm_ prefixed)
    public/fieldmate/       built PWA assets
    hooks.py
  frontend/           Vue 3 + Vite source
    src/
      screens/  components/  stores/  db/ (Dexie)  sync/ (outbox)  api/
  fieldmate-docs/           these planning documents
```

## Architectural rules

1. **UI components contain no business logic.** Neither do API controllers — logic lives in
   `fieldmate/services/*.py`, callable from a test, a scheduler job and a controller without change.
2. **Nothing outside `compat.py` imports from `erpnext.*`.** No raw SQL against ERPNext tables.
3. **Nothing in the PWA calls a Frappe endpoint that is not `fieldmate.api.*`.** No `frappe.client.*`.
4. **The PWA reads from Dexie, never the network.** The network layer only fills Dexie and drains
   the outbox.
5. **The client assigns identity.** Every field-created record carries `client_uuid`; the server
   upserts on it. Retries are always safe.
6. **No FieldMate DocType writes a GL Entry.** Ledger effects happen only by creating a proper ERPNext
   document through compat.
7. **No core edits.** Custom fields on ERPNext DocTypes ship as `fm_`-prefixed fixtures.
8. **Reports read `FieldMate KPI Snapshot`, never raw `FieldMate Visit`.** 2.1 M visits/year makes live
   aggregation non-viable.
9. **Additive schema only.** New capability is a new optional field with a safe default, so a v15
   site and a v17 site run the same app version.

## The version boundary

`fieldmate/compat.py` is the only place in the codebase that knows an ERPNext version. The facade keeps
payload shapes stable for the client; compat keeps ERPNext changes contained server-side. Full
rules in `fieldmate` skill → `references/compat.md`.

CI runs the suite against `version-15`, `version-16` and `develop` on every push.

## Scale design

250 reps × 28 outlets × 25 days ≈ 175 k visits/month, 2.1 M/year.

- Composite indexes on `(field_user, visit_date)` and `(outlet, visit_date)` from Phase 0
- `track_changes: 0` on `FieldMate Visit` and `FieldMate Location Trail`
- `FieldMate Location Trail`: one row per rep per day with the GPS path as compressed JSON —
  65 k rows/year, not 30 M
- `FieldMate KPI Snapshot` materialised nightly and hourly
