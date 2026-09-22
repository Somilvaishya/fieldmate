# Manual tests — Phase 0 and Phase 1

Automation covers what it can: **171 tests**, green on v15 (`scripts/ci-local.sh`). This file is
what a machine cannot check — a real phone, real airplane mode, and a person deciding whether the
thing makes sense.

**App:** https://testerp2.web.gargsystems.com/assets/fieldmate/pwa/index.html
(`/fieldmate` redirects there. `index.html` is required — `/assets/` has no directory index.)
**Desk:** https://testerp2.web.gargsystems.com/app

| Login | Password | Role |
|---|---|---|
| `rep1@fieldmate.test` | `FieldMate@2026` | FieldMate Field Rep |
| `mgr1@fieldmate.test` | `FieldMate@2026` | FieldMate Area Manager |

> **Run `scripts/reset-test-users.sh` first.** The suite creates and deletes Users on this site
> and can clear these fixtures' auth rows, leaving login failing with "Wrong username or
> password" even though the accounts look fine.

`rep1` is a **Website User**, not a System User. That is correct: `FieldMate Field Rep` has
`desk_access = 0`, which is what keeps reps out of `/app`.

---

# Part A — Setup, once, about 10 minutes

Sign in to **`/app` as Administrator**.

### A1 — Settings
`/app/fieldmate-settings`. Confirm **Enable Order Booking** on, **Enable Van Sales** off, Default
Sales Mode *Order Booking*. Note Geo Fence Radius (100 m) — later tests use it.

Set **GPS Ping Interval** to `5`, save → **expect** *"GPS Ping Interval (s) must be between 30
and 900. Got 5."* Put it back to 90.

Turn **both** sales models off, save → **expect** *"Enable at least one sales model. With
neither, no rep can sell anything."*

### A2 — Channels and classes
`/app/fieldmate-outlet-channel/new` → **Kirana**, then **Modern Trade**.
`/app/fieldmate-outlet-class/new` → **A** (8 visits/month), **C** (2/month).
On a class try Visits Per Month `99` → **expect** refused, must be 1–31.

### A3 — Territory tree
`/app/territory`. You should have **FM North** with **FM Delhi** and **FM Mumbai** beneath it.

### A4 — Field users
`/app/fieldmate-field-user`. `rep1` on **FM Delhi**, `mgr1` on **FM North**.

### A5 — Distributor
`/app/customer/new` → **Delhi Distributors**, type Company. Then
`/app/fieldmate-distributor-profile/new` → that customer, Territory *FM Delhi*.
Try a **second** profile for the same customer → **expect** refused, one per customer.

---

# Part B — Phase 0, the offline foundation

### B1 — Installs and runs standalone
Android Chrome → app URL → ⋮ → **Add to Home screen** → close Chrome fully → **airplane mode**
→ tap the icon.
**Expect:** full screen, no address bar, strip reads *"Offline · all work saved"*.
- [ ] Pass / [ ] Fail

### B2 — Login refuses an account with no FieldMate role
Incognito → app URL → sign in as any other user on the site.
**Expect:** *"This account is not set up for the field app. Ask your manager."*
- [ ] Pass / [ ] Fail

### B3 — Wrong password says so plainly
**Expect:** *"Wrong username or password."* No stack trace, no Frappe error dialog.
- [ ] Pass / [ ] Fail

### B4 — A rep signs in
As `rep1` → Today shows *Test Rep*, *FieldMate Field Rep*, a server time and *API v1*.
- [ ] Pass / [ ] Fail

### B5 — The offline strip tells the truth
DevTools → Network → **Offline**. **Expect:** strip flips within ~5 s and Today shows *"Showing
your last saved details. Reconnect to refresh."* — **not** a red error. Back online → *"Online"*.
- [ ] Pass / [ ] Fail

### B6 — The service worker really precaches
DevTools → Application → Service Workers: activated and running, ~6 precache entries. Reload
while Offline — the shell still renders.
- [ ] Pass / [ ] Fail

### B7 — API calls are never served stale
Network tab, filter `api/method`, press **Sync now**. **Expect:** real network requests, never
*(from ServiceWorker)* or *(disk cache)*. A stale order is worse than no order.
- [ ] Pass / [ ] Fail

### B8 — Sync bookkeeping exists
`/app/fieldmate-device-registry` lists your devices with Last Sync On.
`/app/fieldmate-sync-batch` shows batches as you sync.
- [ ] Pass / [ ] Fail

---

# Part C — Phase 1, masters and scoping

## C1 — Bulk import reports rather than refuses *(Gate 1 criterion 1)*

Open `/api/method/fieldmate.api.outlet.import_template` in a browser tab.
**Expect:** column list, required columns, one filled example row.

Then POST to `fieldmate.api.outlet.bulk_import` with `dry_run=1` and four rows — one good, one
with `mobile_no: "oops"`, one with a non-existent territory, one with `latitude: 0, longitude: 0`.

**Expect:** the good row valid, three errors each naming **row, column and the fix** —
*row 4 [territory] 'Nowhere' does not exist. Create it first.* and
*row 5 [latitude] 0,0 is in the Atlantic. Leave both blank instead.*

A file is never rejected wholesale, and nobody guesses which line broke it.
- [ ] Pass / [ ] Fail

## C2 — Create outlets by hand
`/app/fieldmate-outlet/new` — three in **FM Delhi**, distributor *Delhi Distributors*, class *A*,
channel *Kirana*, each with a mobile. Give one latitude `120` → **expect** *"Latitude must be
between -90 and 90."*
Create **one** in **FM Mumbai** — C4 needs it.
- [ ] Pass / [ ] Fail

## C3 — The van-sales guard
On any outlet set **Customer** to *Delhi Distributors*, save.
**Expect:** *"This outlet has a Customer set, which only applies to van sales…"*
That is ADR-013 enforced in code, not just written down. Clear the field.
- [ ] Pass / [ ] Fail

## C4 — Territory scoping *(the security boundary — Gate 1 criterion 2)*
In the app as `rep1`, open **Outlets**.
**Expect:** the three Delhi shops. **The Mumbai shop must not appear.** Search its name — still
absent. *The filter narrows what you may see; it never widens it.*
Sign in as `mgr1` → **expect** all four, because a manager sits on the parent node.
- [ ] Pass / [ ] Fail

## C5 — A rep onboards a shop *(Gate 1 criterion 3)*
As `rep1`: **Outlets → Add a shop**. Name, mobile, owner. Tap **Capture GPS pin**, allow location
→ **expect** *"Pin saved · ±N m"*. Save.
**Expect:** appears marked **Pending**. Open it → *"Cannot take an order yet — This shop is
waiting for approval. You can visit it, but not book an order yet."*
Capture is never blocked in the field; blocking it just means the data is never entered.
- [ ] Pass / [ ] Fail

## C6 — Onboarding while offline
Go Offline (or airplane mode). Add another shop, save.
**Expect:** *"Saved on this phone. It will sync by itself once you have signal."*
Back online → **Sync now** → reopen Outlets → the shop is there.
Nothing captured in front of a shopkeeper is ever lost.
- [ ] Pass / [ ] Fail

## C7 — Approval is a manager's job
As `rep1`, try `/app` → **expect** you cannot reach Desk at all; reps are Website Users.
As `mgr1` in `/app`, open the pending outlet, set Approval *Approved*, save → **expect**
**Approved By** fills in automatically.
Back in the app as `rep1` → that shop now reads *"Ready to take an order."*
- [ ] Pass / [ ] Fail

## C8 — A rep may fix doorstep facts, nothing else
Call `fieldmate.api.outlet.update` for an approved shop with
`{"approval_status": "Pending Approval", "credit_limit": 99999}`.
**Expect:** the call succeeds but **nothing changes**. Fields outside the editable set are ignored
rather than rejected, so an older server never breaks on a newer app build. Confirm in Desk.
- [ ] Pass / [ ] Fail

## C9 — Beats and their integrity rules
`/app/fieldmate-beat/new` — *Delhi Monday*, Territory *FM Delhi*, Assigned To `rep1`, Weekly,
Monday, with your three Delhi outlets. **Expect:** Seq renumbers 1, 2, 3 and Outlets shows 3.

Now try each; every one should be refused with a readable reason:

| Attempt | Expected refusal |
|---|---|
| Same outlet twice | *"is already on this beat"* |
| Add the Mumbai outlet | *"outside this beat's territory"* |
| Second beat reusing an outlet | *"already on active beat FM-BEAT-…"* |
| Weekly **and** Week Pattern W2 | *"A weekly beat runs every week…"* |
| Assign to a rep scoped elsewhere | *"does not include this beat's territory"* |

Open one of those outlets in Desk → **Beat** shows *Delhi Monday*. Deactivate the beat → the
Beat field empties.
- [ ] Pass / [ ] Fail

## C10 — Beats reach the phone
In the app as `rep1`, **Sync now**, then the **Beats** tab.
**Expect:** *Delhi Monday*, Monday, 3 shops. Tap it → the outlet list filters to that beat.
- [ ] Pass / [ ] Fail

## C11 — Must-sell scoring cannot lie
`/app/fieldmate-must-sell-list/new` — Active, **no items**, save → **expect** *"An active
must-sell list needs at least one item, or compliance scores against nothing and always reads
100%."*
Add an item with **Weight 0** → **expect** *"Weight must be above zero…"*
- [ ] Pass / [ ] Fail

## C12 — Geo-fence exceptions stay meaningful
`/app/fieldmate-geo-fence-exception/new` — an outlet, `rep1`, **Distance 50**, any reason →
**expect** *"This check-in was 50.0 m from the shop, inside its 100 m fence. No exception is
needed."*
Change to **450**, save (Pending). Submit while Pending → **expect** *"Approve or reject this
exception before submitting it."* Set Approved, save, submit → Decided By and Decided On fill in.
- [ ] Pass / [ ] Fail

---

# Gate status for the record

### Gate 0 — **PASSED**, 21 Sep 2026 (v15 scope, ADR-015)

### Gate 1 — measured 21 Sep 2026

| Criterion | Result |
|---|---|
| 1. 5,000 outlets and 200 beats import with zero manual correction | **PASS** — imported clean; mixed files report per row |
| 2. A rep sees only their territory | **PASS** — proven three ways in tests, plus C4 |
| 3. Field-created outlet Pending, visitable, not sellable | **PASS** — C5 |
| 4. 500-outlet master pull under 2.5 MB gzipped | **PASS** — 8 KB gzipped, 224 KB raw |

> Criterion 4 failed first at **6,614 KB**: `sync.pull` was sending all 46 columns of every
> outlet because `pull_fields` was never set for it. Trimmed to the 19 that a list row, a map pin
> and a check-in decision actually need. The budget is what caught it.

---

# After testing

Record failures in `docs/MEMORY.md` under Known Issues. Tick a criterion only when it passed on a
real device or a real file — **a gate is not partially passed.**
