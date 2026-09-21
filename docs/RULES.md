# RULES — FieldMate development standards

The project rulebook. Read before coding; check against before committing.

## General

- Python for backend, JS/Vue 3 for frontend. No TypeScript in the Frappe app itself.
- **Reuse before create.** ERPNext first, then our own services, then a new thing. Check the reuse
  map in `fieldmate` skill → `references/data-model.md`.
- Business logic lives in `fieldmate/services/`. Controllers and DocType hooks stay thin.
- Small, named functions. One concern each. If a function needs "and" to describe it, split it.
- No dead code, no commented-out blocks, no `TODO` without an owner and a TASKS.md entry.

## Before coding

1. Read the relevant skill reference and the existing code in that area.
2. State what you will do and which files you will touch.
3. Confirm nothing already does it.
4. Only then implement.

Never build a whole layer. Build a **vertical slice** — one complete flow end to end.
Never accept "build the entire app" as a task.

## UI

- Follow DESIGN.md. The field constraints there are requirements, not preferences.
- 48 px minimum touch targets, 4.5:1 minimum contrast, 16 px minimum body text.
- Primary actions in the bottom third. Bottom sheets, not modals.
- Every screen handles loading, empty and error states explicitly.
- Permanent offline state strip with accurate queue depth.
- No hard-coded user-facing strings — everything translatable.
- Renders at 360 px width.

## Security

- Territory scoping derived **server-side** from `FieldMate Field User`. Never trusted from a request parameter.
- `allow_guest=True` forbidden except on login.
- Validate all input server-side. Recompute anything that is evidence (`distance_from_outlet_m`,
  `is_geo_fence_breach`) — never trust a client-supplied value.
- **No field role gets create/write on any accounting DocType.** Reps create `FieldMate Collection`;
  Payment Entries are posted by authorised roles on deposit confirmation.
- No secrets in Git. Secrets live in `site_config.json`. `.env.example` lists names only.
- Visit photos and GPS trails are private files and PII. Retention policy in `FieldMate Settings`.
- Never leak a stack trace or SQL error to the client. Stable error codes, rep-readable messages.

## Testing

- Every write endpoint has an **idempotency test**: same `client_uuid` twice, one document.
- Every read endpoint has a **scoping test**: another territory's record returns a permission error.
- `FrappeTestCase` rolls back **per class, not per method** — create fixtures in `setUp`, delete
  them explicitly, make names unique per test.
- Tests run on `dev-15.local`. Gates are verified on `testerp2`.
- A green suite is necessary, not sufficient. `bench migrate` succeeding proves nothing.
- Report failures with output. Never round a failure up to a pass.

## Git

- **Never commit or push without explicit approval.** Show the diff, say what is in it, ask.
- Small commits. Conventional prefixes: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- Feature branches (`feature/fieldmate-visit-checkin`). Never straight to the default branch.
- **Author is somilvaishya only.** No `Co-Authored-By: Claude` trailer, no Claude attribution in
  commits or PR descriptions on this project.

## Compatibility

- Nothing outside `compat.py` imports `erpnext.*`.
- No raw SQL against ERPNext tables. Use `frappe.qb` / `frappe.get_all` / `frappe.db.get_value`.
- No core edits to `frappe` or `erpnext`. Custom fields are `fm_`-prefixed fixtures.
- Branch on capability probes where possible, version numbers only where a probe is impossible.
- Additive schema only.

## Documentation

- Update `MEMORY.md` at the end of every task.
- Tick the `TASKS.md` checkbox when a task is genuinely done, not when the code is written.
- Record architectural choices as ADRs in `DECISIONS.md`.
- A stale doc is worse than no doc.
