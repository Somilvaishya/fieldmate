# Manual tests — Phase 9, distributor portal and claims

Written for: whoever is sitting at a laptop on testerp2, not for the person who built it. Every
step says what to click and what you should see. Where something is meant *not* to happen, that
is said too — half of this phase is things that must not occur.

**Site:** `testerp2.web.gargsystems.com`
**You will need:** a Desk login with FieldMate Admin, and a second browser (or a private window)
for the depot login. Keep them separate — logging in and out of one window will cost you an hour.

---

## Before you start: the five-minute setup

Run this once, from a Desk session, to give yourself something to look at.

```
cd ~/frappe/frappe-bench-v15/sites
../env/bin/python ../apps/fieldmate/scripts/setup_phase9.py
```

It prints the two logins it made and the passwords. Write them down; it will not print them
again.

If you would rather do it by hand, this is all it does:

1. **FieldMate Settings → Scheme Claim Settlement.** Set three things:
   - *Settlement Item* — a non-stock item, e.g. `SCHEME-CLAIM`. Create it if it does not exist.
   - *Trade Scheme Expense Account* — where trade spend is booked. Leave blank to use the company
     default income account, but then the claim reads as a sales shortfall, not as spend.
   - *Claim Cost Center* — leave blank to use the company default.
2. **A depot login.** New User (Website User is fine), then **FieldMate Portal User** → pick that
   user and the distributor profile. Save. The `FieldMate Distributor` role appears on the User
   by itself — do not add it by hand.
3. Make sure your test rep's outlet has a **distributor** on it, and that the distributor has a
   **Customer** on its profile. Without the Customer there is nowhere for a credit note to go and
   the claim will say so.

---

## 1. The depot only sees its own work

**This is the criterion that matters most.** Everything else is bookkeeping; this one is whether
one distributor can read another's order book.

1. In the second browser, sign in as the depot login and go to **`/distributor/orders`**.
2. You should land on the order queue with your depot's name in the top-left.
3. Count the orders. Now, in the Desk window, open **FieldMate Order** list and count how many
   exist for *other* distributors. The depot's queue must not show any of them.

Now go after one by name:

4. In Desk, copy the name of an order belonging to a **different** distributor
   (e.g. `FM-ORD-000123`).
5. In the depot browser, open:
   `/api/method/fieldmate.api.portal.order_detail?order=FM-ORD-000123`

**Expected:** a 403 and a message saying the order *was not found*.

> The wording is deliberate. It does not say "that belongs to someone else", because that would
> confirm to whoever is probing that the name they guessed is a real one.

6. Try the same through the generic resource route:
   `/api/resource/FieldMate Order/FM-ORD-000123`

**Expected:** refused as well. If this one succeeds and step 5 did not, the framework-level hook
is not loaded — run `bench --site testerp2.web.gargsystems.com migrate` and try again.

7. Finally, `/api/resource/FieldMate Order?limit_page_length=0`

**Expected:** only this depot's orders. Not one row from anywhere else.

---

## 2. Working the queue

Take an order through its whole life and watch it reach the rep.

1. Have the rep book an order on the phone at a shop belonging to this depot, and sync.
2. In the depot browser, hit **Refresh**. The order appears under **Waiting on you**, tinted
   amber, with the shop name, the rep's name, the line count and the net total.
3. Click the ▶ twisty on the left.

**Expected in the drawer:**
- every line, in the unit the rep sold in — "2 Cases" with "24 Nos" underneath, not bare pieces;
- any free goods on their own rows, in green, at zero, marked *You supply, you claim it back*;
- a totals panel whose note says this is the depot's bill to the shop and posts nothing in our
  books;
- an empty history.

4. Click **Accept**.

**Expected:** the status pill turns to *Accepted*, the tiles across the top re-count, and the
history in the drawer gains one line.

5. Click **Mark invoiced**. It asks for your invoice number and **will not proceed without one**.
   Enter something like `DEP/2026/8842`.
6. Click **Mark delivered**.

7. Now check the log. In Desk, open **FieldMate Order Ingest Log** filtered on that order.

**Expected:** three rows — Accepted, Invoiced, Delivered — each with the from-status, the
to-status, the depot user who did it and the time. The Invoiced row carries your invoice number.

### 2a. The double-tap

8. Click **Accept** on some other new order, and while it is still working, click it again.

**Expected:** the second tap says *Already accepted*. Check the ingest log — there must be
**one** row for that move, not two a second apart.

### 2b. What the depot may not do

9. Find a delivered order. It has no action buttons at all — there is nowhere left for it to go.
10. In Desk, edit the portal user and clear **May Accept Orders**. Reload the depot browser.

**Expected:** the queue still loads and still reads, but every row says *View only* and the
**Accept selected** button is gone. Set the box back before carrying on.

---

## 3. The status reaches the rep

**This is the whole reason the portal exists.** The shopkeeper asks the rep, not the depot.

1. On the rep's phone, open the orders list. The order you just moved still reads
   **Sent To Distributor** — the phone has not synced since.
2. Pull to sync.

**Expected:** the same order now reads **Delivered**, and the depot's invoice number is on it.

> If it does not change, the sync pull is not returning orders. Check that
> `services/registry.py` has `pull=True` on `FieldMate Order`.

3. On the phone, try to change that status. There is no control for it, and there should not be:
   the rep proposes an order, the depot answers it.

---

## 4. Raising a claim

1. In the depot browser, go to **Scheme Claims**.
2. The four tiles read zero if this depot has never claimed.
3. Click **Raise a claim**. The dialog opens on **last calendar month**.
4. Change the dates to cover the period your test orders were booked in.

**Expected:** the preview box fills in with something like
*₹1,240.00 across 6 benefits at 3 shops*, and lists the schemes underneath. The
**Raise and submit** button only becomes usable once there is something to claim.

5. Pick a period where nothing was granted.

**Expected:** *Nothing is left to claim in that period.* Button stays disabled.

6. Put the good dates back and click **Raise and submit**.

**Expected:** a toast naming the claim and its value, and the claim appears in the table with:
- status **Pending Approval**;
- a green **Matches the ledger** pill in the *Reconciles* column;
- an em dash under *Approved* — nobody has decided yet.

7. Open the twisty.

**Expected in the drawer:**
- one row per benefit, each naming the order, the shop, the rep, the benefit kind and the value;
- a *What makes up this claim* panel splitting bill discounts from free-goods value;
- an *Against the ledger* panel showing the period's benefits and this claim's, with a difference
  of **₹0.00** and the line *Everything recorded for this period is on this claim.*

### 4a. The same benefit cannot be claimed twice

8. Click **Raise a claim** again, same dates.

**Expected:** *Nothing is left to claim in that period.* The first claim took them off the table.

### 4b. A partial claim is flagged, not blocked

9. Book another order that grants a benefit, and sync.
10. Raise a claim for a window that covers **only** the new order.

**Expected:** it is allowed, and the *Reconciles* column reads **₹x unclaimed** in amber rather
than the green pill. That is not an error — a depot may claim part of a month. It is flagged so
that at approval a partial claim and a missing accrual do not look identical.

---

## 5. Approving, and the credit note

From the **Desk** window now, as FieldMate Admin or Sales Head.

1. Open the claim. Read the *Reconciliation* section — it should agree with what the depot saw.
2. Approve it. Either from the Desk form, or:

```
/api/method/fieldmate.api.claim.decide?claim=FM-CLM-2026-00001&decision=Approved
```

**Expected:**
- claim status **Settled**;
- a **Credit Note** link on the claim;
- *Settled On* filled in.

3. Open the credit note.

**Check all four:**

| | Expected |
|---|---|
| Is Return | ticked |
| Customer | the distributor's Customer, not the shop |
| Items | **one** line, on the settlement item — not one per SKU |
| Account & Cost Centre | the two you configured in Settings |

4. Check what it did *not* do. Open the **Stock Ledger** and confirm nothing moved. The stock was
   the distributor's from primary billing onward; a claim settles money, not goods.

5. Check the ledger rows. Open **FieldMate Scheme Ledger** filtered on this claim.

**Expected:** every row is **Settled**, with a *Settled On* date.

### 5a. Approving twice credits once

6. Call settle again:

```
/api/method/fieldmate.api.claim.settle?claim=FM-CLM-2026-00001
```

**Expected:** the same credit note name comes back. In Desk, search Sales Invoice for
`fm_source_key = CLAIM:FM-CLM-2026-00001` — there must be exactly **one**.

### 5b. Approving less than was claimed

7. Raise another claim and approve it for half the value.

**Expected:** the credit note is for **the approved figure**, not the claimed one. Approving for
*more* than was claimed is refused.

### 5c. Rejecting

8. Raise another claim and reject it. It **will not let you** without a reason.
9. Give one.

**Expected:** status **Rejected**, the reason visible on the depot's screen, and — the important
part — the scheme ledger rows are back to **Accrued**. The depot fixes whatever was wrong and
claims again; if the rows stayed Claimed their entitlement would have been silently deleted.

---

## 6. Things that must not happen

Run through this list at the end. Each one is a bug if it happens.

- [ ] No **Sales Order** was created by anything in this phase.
- [ ] No **GL Entry** from an order moving through the queue. Only the credit note posts.
- [ ] No **Stock Ledger Entry** from anything here.
- [ ] The depot login cannot reach **/app** (Desk). It has no desk access.
- [ ] The depot login cannot read **FieldMate Portal User**, **FieldMate Scheme**, or any other
      depot's anything.
- [ ] A claim cannot be cancelled while its credit note stands. Try it: it should refuse and
      name the note.
- [ ] An **Incentive** ledger row never appears on a claim. That is the rep's earning; it never
      came off a shop bill.

---

## If something is wrong

| What you see | Where to look |
|---|---|
| Depot login says *not attached to a distributor* | FieldMate Portal User row missing or inactive |
| *is not a billing account we know* | FieldMate Portal User → Distributor names a Customer that has been deleted or renamed |
| Depot header shows no credit terms | Customer → Payment Terms is blank; credit days are derived from the template, never stored |
| *No settlement item is set* | FieldMate Settings → Scheme Claim Settlement |
| Claim reconciles to zero | The orders granted no scheme benefits — check the scheme is active and in date |
| Rep's phone never updates | `registry.py`, `pull=True` on FieldMate Order; then re-sync |
| `/api/resource` returns another depot's rows | hooks not loaded — run `bench migrate` |
