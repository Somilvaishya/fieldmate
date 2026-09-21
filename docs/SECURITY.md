# SECURITY — FieldMate Field Force

## Authentication

- Frappe session auth, plus **device binding** via `FieldMate Device Registry`. A session is tied to a
  registered device; an unrecognised device must re-register.
- `allow_guest=True` is forbidden on every method except `fieldmate.api.auth.login`.
- The PWA stores its token in session storage, never in IndexedDB alongside mirrored data.
- Device deregistration must invalidate the session — a lost phone is a real scenario with a real
  territory's outlet data and customer contacts on it.

## Authorization

- **Territory scoping is derived server-side** from `FieldMate Field User`. Never read from a request
  parameter, never trusted from the client.
- Row-level access uses Territory-based `User Permission`, generated from the field user record —
  no custom permission code.
- Role matrix is in `fieldmate` skill → `references/data-model.md`. The hard rule: **no field role gets
  create or write on any accounting DocType.**
- Distributors see only their own orders and claims. Verified by attempting to fetch another
  distributor's document — that is a Phase 9 gate criterion, not an assumption.
- Every new whitelisted method is reviewed for authorisation before merge.

## Secrets

- No secrets in Git. Ever.
- Real values live in `site_config.json` per site.
- `.env.example` lists variable names with `=` and no values.
- API keys for maps, SMS or push are server-side only. The PWA never holds a third-party key.
- If a secret is ever committed, rotate it — removing the commit is not sufficient.

## Database

- Use `frappe.qb`, `frappe.get_all`, `frappe.db.get_value`. **No raw SQL against ERPNext tables.**
- Any unavoidable raw SQL is parameterised, never string-interpolated.
- No FieldMate DocType writes a GL Entry. Ledger effects only via proper ERPNext documents through
  `compat.py`.

## Input validation

- Validate everything server-side. Client validation is a convenience, not a control.
- **Recompute all evidence.** `distance_from_outlet_m`, `is_geo_fence_breach`,
  `duration_minutes` and scheme benefits are recalculated on the server. Evidence the device can
  edit is not evidence.
- Quantities, amounts and rates are bounded and type-checked. Reject negatives where they are
  meaningless.
- `client_uuid` is validated as a UUID and uniquely indexed.

## APIs

- Flat JSON in and out. No Frappe `Document` objects across the wire.
- Stable machine error codes plus rep-readable messages.
- **Never leak a stack trace, SQL error or internal path to the client.**
- Every read endpoint is bounded — paginated or capped. `sync.pull` is always a territory-scoped
  delta, never a full table.
- Rate-limit `auth.login` and `sync.push`.

## File uploads

- Validate type, size and filename. Images only for visit photos and receipts.
- Cap at 120 KB after client-side compression; reject oversized uploads server-side too — client
  compression is a budget, not a control.
- Strip EXIF except the GPS we deliberately record.
- **All visit photos and receipt images are private files.** Never public, never guessable URLs.

## PII and retention

- **GPS trails are PII.** They track a named employee's movements. Retention period is configured
  in `FieldMate Settings` and enforced by a scheduled purge.
- Outlet owner names, mobile numbers and GSTINs are personal/commercial data — same private-file
  and access rules.
- Selfies captured at Day Start are biometric-adjacent. Store private, retain briefly, and be able
  to explain to an employee exactly what is kept and for how long.
- Mirrored data on a device is a disclosure surface. The PWA must be able to wipe its Dexie store
  on logout or deregistration.

## Pre-deployment checklist

- [ ] No secrets in Git
- [ ] Authentication verified
- [ ] Authorization verified, including cross-territory and cross-distributor negative tests
- [ ] No field role can reach an accounting DocType
- [ ] Input validation and server-side evidence recomputation in place
- [ ] API responses leak no internals
- [ ] Visit photos and receipts are private files
- [ ] GPS retention policy configured and purge job scheduled
- [ ] Device deregistration invalidates session and wipes local store
