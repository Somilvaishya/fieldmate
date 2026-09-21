# Manual tests — Phase 0

Everything automation can cover is already covered: 32 tests, green on v15
(`scripts/ci-local.sh`). This file is only what a machine cannot check — a real browser, a real
phone, real airplane mode.

**Site:** https://testerp2.web.gargsystems.com
**App:** https://testerp2.web.gargsystems.com/assets/fieldmate/pwa/index.html
(`/fieldmate` redirects there. Note `index.html` is required — `/assets/` has no directory
index, so the bare folder URL 404s. The app lives under `/assets/` because that is the only path
Frappe serves as true static, and a service worker can only control pages inside its own path.)

| Login | Password | Role |
|---|---|---|
| `rep1@fieldmate.test` | `FieldMate@2026` | FieldMate Field Rep |
| `mgr1@fieldmate.test` | `FieldMate@2026` | FieldMate Area Manager |

Test accounts on a test site. Not for production.

---

## The one that closes Gate 0

### M1 — PWA installs to an Android home screen and opens offline ← **blocks Gate 0 criterion 2**

1. On an **Android phone**, open Chrome → `https://testerp2.web.gargsystems.com/fieldmate`
   (it redirects to `/assets/fieldmate/pwa/index.html` — install from there)
2. Menu (⋮) → **Add to Home screen** / **Install app**
3. Confirm the icon appears on the home screen, named **FieldMate**
4. Close Chrome completely (swipe away from recents)
5. Turn on **airplane mode**
6. Tap the FieldMate icon from the home screen

**Expect:** the app opens full-screen with no browser address bar, and the top strip reads
**"Offline · all work saved"**. It must not show a dinosaur/"no internet" page.

> If it shows the browser's offline page, the service worker did not precache the shell. Send me
> what `chrome://inspect` → Service Workers reports for the origin.

- [x] **PASS** — 21 Sep 2026. Installed as a home-screen icon, launches standalone with no
  address bar, renders the shell offline and shows the cached profile.

---

## Browser checks (desktop Chrome is fine)

### M2 — Login rejects an account with no FieldMate role
1. Open `/assets/fieldmate/pwa/index.html` in an incognito window
2. Sign in as any existing non-FieldMate user on the site

**Expect:** *"This account is not set up for the field app. Ask your manager."*
Not a stack trace, not a blank screen.

- [ ] Pass / [ ] Fail

### M3 — Login works for a rep
1. Same screen, sign in as `rep1@fieldmate.test`

**Expect:** lands on **Today**, showing "Test Rep", role `FieldMate Field Rep`, a server time and
`API v1`.

- [ ] Pass / [ ] Fail

### M4 — Wrong password says so plainly
Sign in with a deliberately wrong password.

**Expect:** *"Wrong username or password."* — no stack trace, no SQL, no Frappe error dialog.

- [ ] Pass / [ ] Fail

### M5 — Offline strip tells the truth
1. Signed in on Today, open DevTools → Network → **Offline**
2. Watch the strip at the top of the screen

**Expect:** it changes to **"Offline · all work saved"** within ~5 seconds. Switch back to Online
and it returns to **"Online"**.

- [ ] Pass / [ ] Fail

### M6 — Service worker is registered and precaching
DevTools → Application → Service Workers.

**Expect:** a worker for this origin, status **activated and running**. Under Cache Storage there
is a precache with ~5 entries (the shell, JS, CSS, manifest).

- [ ] Pass / [ ] Fail

### M7 — Reload while offline still works
With the Network tab still set to Offline, press **reload**.

**Expect:** the app shell renders again from cache. Data areas may be empty — the shell must not
be.

- [ ] Pass / [ ] Fail

### M8 — API calls are never served stale
DevTools → Network, filter `api/method`. Click **Sync now**.

**Expect:** requests to `fieldmate.api.*` show as network requests, **never** "(from ServiceWorker)"
or "(disk cache)". A stale order is worse than no order.

- [ ] Pass / [ ] Fail

---

## Desk checks (manager side)

### M9 — The three DocTypes exist and are usable
1. Sign in to `/app` as Administrator
2. Visit each list:
   - `/app/fieldmate-device-registry`
   - `/app/fieldmate-sync-batch`
   - `/app/fieldmate-sync-conflict`

**Expect:** each list opens without error. Device Registry shows the device created by your M1/M3
login. Forms open, sections are laid out sensibly, no "field not found" errors.

- [ ] Pass / [ ] Fail

### M10 — A conflict cannot be closed without a resolution
1. In `/app/fieldmate-sync-conflict`, create a new record
2. Conflict Type `Duplicate`, Client UUID anything, Status **Resolved**
3. Save

**Expect:** *"Choose how this conflict was resolved before closing it."* Set Resolution to
`Keep Client`, save again — now it saves, and **Resolved By / Resolved On fill in automatically**.

- [ ] Pass / [ ] Fail

### M11 — A rep cannot reach accounting
1. Sign in to `/app` as `rep1@fieldmate.test`
2. Try `/app/payment-entry` and `/app/sales-invoice`

**Expect:** permission denied / not permitted. **No field role may ever post to the ledger** — this
is the check finance will ask about.

- [ ] Pass / [ ] Fail

---

## Not manual — status for the record

| Gate 0 criterion | How it is covered |
|---|---|
| 3. Batch replay creates no duplicates | Automated — `test_sync.py` |
| 4. Bad record → one conflict, rest commits | Automated — `test_sync.py` |
| 5. CI green on v15 | Automated — `scripts/ci-local.sh`, ruff + 32/32 |
| 1. Installs clean on v15 | Verified on testerp2 |
| v16 | **Out of scope** — see ADR-015 |
| 2. PWA on Android, offline | **PASSED on a real device** |

---

## After testing

Record results in `docs/MEMORY.md` under Known Issues, and tick Gate 0 criterion 2 in
`docs/TASKS.md` only if **M1 passes on a real phone**. A gate is not partially passed.
