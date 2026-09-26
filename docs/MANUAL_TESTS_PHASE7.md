# Manual tests — Phase 7, targets, incentives and expenses

Written for: whoever is sitting at a laptop and a phone on testerp2, not for the person who
built it. Every step says what to do and what you should see.

**Site:** `testerp2.web.gargsystems.com`
**You will need:** a Desk login with FieldMate Admin, and the PWA on a phone signed in as a rep.

---

## Setup

```
cd ~/frappe/frappe-bench-v15/sites
../env/bin/python ../apps/fieldmate/scripts/setup_phase7.py
```

It prints what it built. By hand, it is four things:

1. **FieldMate Settings → Field Expenses.** Travel rate per km (e.g. 3.50), daily food
   allowance, receipt threshold, distance tolerance.
2. **A Sales Person** for your test rep, on the `FieldMate Field User` record. Without it the rep
   is not on the tree and no target can reach them.
3. **A target plan** for that Sales Person, covering this month.
4. **An incentive scheme** with a few slabs.

---

## 1. A target cascades, and the pieces add back up

This is the one worth being careful with.

1. In Desk, open **FieldMate Target Plan** and create one at the *top* of your Sales Person tree.
   Give it a period covering this month and these lines:

   | Target | Value |
   |---|---|
   | Value | 10,00,000 |
   | Volume | 5,001 |
   | Outlet Coverage | 617 |
   | Lines Per Call | 4.5 |

   None of those divide evenly on purpose.

2. Submit it, then cascade:

```
/api/method/fieldmate.api.target.cascade?plan=FM-TGT-2026-00001
```

3. Open the child plans that appeared (filter Target Plan on **Cascaded From**).

**Expected:**
- one child per Sales Person directly below the root;
- each child's **Value** is a share, not the whole thing;
- each child's **Lines Per Call** is **4.5** — the same as the root, not divided.

4. Now check the arithmetic:

```
/api/method/fieldmate.api.target.reconcile?plan=FM-TGT-2026-00001
```

**Expected:** `matches: true`, and per type:

| Type | What it should say |
|---|---|
| Value, Volume, Outlet Coverage | `additive: true`, `difference: 0` — leaves sum to root exactly |
| Lines Per Call | `additive: false`, `leaves: [4.5]` — copied to every leaf |

> If Value comes back with a difference of 0.01, the split is running in rupees instead of
> paise. That is the bug this whole design exists to prevent.

5. Add another level — put reps under the regions and cascade again from the top. Reconcile
   still has to say `matches: true`, now with more leaves.

---

## 2. Achievement against a month you can count

1. On the phone, as the rep: start the day, check in at **two different shops**, and book an
   order at each.
2. In Desk, run the measurement:

```
/api/method/fieldmate.api.target.recompute?plan=<the rep's leaf plan>
```

3. Open **FieldMate Achievement** for that plan.

**Expected, checkable by hand:**

| Type | Should equal |
|---|---|
| Value | the two orders' net totals added up |
| Volume | the two orders' total quantities |
| Outlet Coverage | **2** — two different shops |
| Productive Calls | the number of visits that produced an order |
| New Outlets | shops the rep added this month and that were approved |
| Lines Per Call | distinct SKUs ÷ productive calls |

4. Cancel one of the orders and recompute.

**Expected:** Value and Volume drop. A cancelled order must stop counting, or a rep can book,
take the credit, and cancel on the first of next month.

5. Check the shortfall column. **Lines Per Call must show a shortfall of zero** even when the rep
   is below target. A rep at 4.2 against 4.5 is not "0.3 lines behind"; they are selling narrower
   carts, and a number there would get summed into a total somewhere.

---

## 3. Incentive, against a table you wrote first

Write the answer down before you look at the screen. That is the whole test.

1. In Desk, create a **FieldMate Incentive Scheme**:
   - Measured on: **Value**, qualifies at **80%**
   - Slabs: 80–100 → ₹4,200 (Tier 1) · 100–120 → ₹6,000 (Tier 2) · 120+ open ended → ₹9,000 (Tier 3)

2. Try saving it with a **gap** — change Tier 2 to start at 110.

**Expected:** refused, naming the gap. A rep landing at 105% would otherwise earn nothing and
nobody would find out until it happened to somebody.

3. Try saving with the **top slab closed** (120–150 instead of 120+).

**Expected:** refused. A rep at 160% must not earn zero.

4. Put it back, submit, and compute:

```
/api/method/fieldmate.api.target.compute_payouts?from_date=...&to_date=...&dry_run=1
```

5. Check three reps against what you wrote down. Open a **FieldMate Incentive Payout** and read
   the **Working** field — it says in one sentence what the machine thought it was doing.

### 3a. Percentage schemes

6. Make a second scheme paying **0.5% of value**, open ended from 0%.

**Expected:** a rep at 81% and one at 119% get *different* amounts. It pays on what was actually
sold, never on the target — of the target, both would be paid the same.

7. Put a **cap** on it, below what a good rep earns.

**Expected:** the payout is the cap, and **Cut By Cap** shows what was taken off. A rep who did
their own arithmetic and got less needs to see which rule did it.

---

## 4. Expense claims and the GPS trail

**This is the criterion about trust.**

1. On the phone, with the day running, move around and let the trail record — or in Desk, look at
   **FieldMate Location Trail** for the rep and today, and note **Total Distance Km**.
2. On the phone: **Today → Claim expenses**.

**Expected:** the screen opens on **Travel** with the trail distance already filled in, the ping
count and check-in count underneath, and the rate × distance worked out.

3. File it without changing anything.

**Expected:** filed and **Approved** straight away. Nothing is in question.

### 4a. Claiming more

4. File for another day. Tap **Edit** and put in **50% more** than the trail shows.

**Expected before you tap:** a line saying *"X km more than your trail recorded — your manager
will see this before it is paid."*

5. File it. In Desk, open the claim.

**Expected:** status **Pending Approval**, and **Why** naming the excess in km and percent.

6. Add only **5%** on a third day.

**Expected:** approved straight away. The trail drops pings in basements and markets with no
signal, so a little more is ordinary.

### 4b. The rep cannot sign their own

7. Still signed in as the rep, try to approve the inflated claim:

```
/api/method/fieldmate.api.expense.decide?claim=FM-EXP-...&decision=Approved
```

**Expected:** refused. Filing over the trail and approving it is the same as stating your own
mileage.

8. As a manager, approve it for **less** than was claimed.

**Expected:** allowed. Approving for **more** than was claimed is refused.

### 4c. The rate does not move under a filed claim

9. File a travel claim. Then change **Travel Rate Per Km** in Settings. Reopen the claim and save
   it.

**Expected:** the claim keeps the **old** rate. A rate changed between filing and approval must
not restate the figure the rep was shown.

10. Clear the rate entirely and try to file a travel claim.

**Expected:** refused, naming the setting. Not priced at zero.

---

## 5. The nightly job

1. Run it by hand:

```
bench --site testerp2.web.gargsystems.com execute fieldmate.tasks.measure_targets
```

2. Look in **Error Log** and the bench log.

**Expected:** a line saying how many plans were measured and **how long it took**. That number is
what Gate 7 criterion 5 is about, and the honest way to know it is to have been watching it on a
real site rather than once under a stopwatch.

---

## 6. Things that must not happen

- [ ] A rep cannot read **another rep's** targets, achievement, payouts or expense claims. Try
      `/api/resource/FieldMate Incentive Payout` signed in as a rep — you should see only your
      own rows.
- [ ] No **GL Entry** from filing or approving an expense claim. The HRMS document is created as
      a **draft**; HR submits it.
- [ ] A **cascaded** target plan cannot be cancelled while its children stand.
- [ ] A **submitted** incentive payout is never silently restated by a recompute. Somebody has
      been told what they earned.
- [ ] A **paid** payout cannot be cancelled without reversing the payment first.

---

## If something is wrong

| What you see | Where to look |
|---|---|
| Cascade does nothing | The Sales Person has no children, or they are disabled |
| Reconcile is off by a paisa | The split is not running in paise — check `target.units_for` |
| Lines Per Call divided | `is_additive` on the target line; it is stamped from the type |
| Rep's screen says no target | No leaf plan names that Field User — check `sales_person` on it |
| Achievement is all zero | The job has not run for that plan; `target.recompute` |
| Travel claim refused | `travel_rate_per_km` is unset in Settings |
| Trail distance is zero | No Location Trail for that rep and day |
