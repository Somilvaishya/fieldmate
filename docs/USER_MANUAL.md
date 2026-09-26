# FieldMate — setup and testing manual

For whoever is testing FieldMate end to end on a real site, from an empty app to a settled
distributor claim. Read it in order. Each step says what to do, what you should see, and — just
as important — **what must not happen.**

Half the rules in this app are about documents that must *not* be created. A test that only
checks the happy path will pass on a build that is quietly booking revenue on sales the company
never made.

**Site used throughout:** `testerp2.web.gargsystems.com`
**Desk:** `/app` · **Rep app:** `/fieldmate` · **Depot portal:** `/distributor/orders`

---

# Part 0 — Starting from zero

## 0.1 See what is there

```
cd ~/frappe/frappe-bench-v15/sites
../env/bin/python ../apps/fieldmate/scripts/reset_fieldmate.py
```

This **counts only**. It prints every FieldMate document on the site and every ERPNext document
FieldMate itself posted, and deletes nothing.

Read the list before going further. It tells you what state you are actually starting from.

## 0.2 Wipe it

```
../env/bin/python ../apps/fieldmate/scripts/reset_fieldmate.py --yes
```

**There is no undo.**

| | |
|---|---|
| Removed | every FieldMate document, and the Sales Invoices / Payment Entries / Sales Orders / Expense Claims **FieldMate posted** — found by the `fm_source_key` stamp this app writes on everything it creates |
| Kept | Company, Accounts, Cost Centers, Warehouses, Users, and any Customer or Item FieldMate did not create |
| Kept | every other app on the bench — excom, crm, trako and the rest |

A Sales Invoice somebody raised by hand has no `fm_source_key` and is never touched, however
similar it looks.

> **Later, to re-run a day without rebuilding the shop list:**
> `reset_fieldmate.py --yes --keep-masters` — wipes visits, orders, collections, snapshots and
> alerts; keeps outlets, beats, the rep, catalogues, schemes and settings.

## 0.3 Two things the wipe leaves behind on purpose

**Customers.** `DIST-*` customers stay, because deleting a Customer can break links in other
apps. If you want a truly blank slate, delete them by hand in Desk first — or just ignore them
and make a new one in step 2.

**Users.** A login may be shared with another app. Delete test users by hand if you want them
gone.

## 0.4 Confirm it is empty

```
../env/bin/python ../apps/fieldmate/scripts/reset_fieldmate.py
```

**Expected:** *nothing to remove — FieldMate is already empty.*

---

# Part 1 — Settings, and what each one actually does

**Desk → FieldMate Settings** (search it, it is a single page).

Nothing else in this manual works until section 1.1 and 1.2 are filled in. The rest can wait.

## 1.1 Sales Model — *this decides the shape of everything*

| Setting | Default | What it decides |
|---|---|---|
| **Enable Order Booking** | on | The rep books an order; the **distributor** delivers and bills the shop |
| **Enable Van Sales** | off | The rep carries stock and sells at the counter |
| **Default Sales Mode** | Order Booking | Which one a rep gets when their own profile says nothing |

**Set for this manual: Order Booking on, Van Sales off.** Part 9 turns van sales on separately.

> **The one idea the whole app is built on.** In order booking, the shop is **not our customer**.
> It buys from its distributor. We never invoice it, so a rep's order creates **no** Sales Order,
> **no** invoice, **no** GL Entry and **no** stock movement. It goes into the distributor's queue
> and stops there. The company's own sale happens later, when the distributor orders from us —
> and that is a different document entirely.
>
> Van sales is the same: the stock in the van is the distributor's, not ours. It posts nothing
> either.
>
> If you see a Sales Order appear when a rep books an order at a kirana shop, **that is a bug**,
> and it is the most important bug this manual can find.

## 1.2 General

| Setting | What it decides |
|---|---|
| **Default Company** | Whose books credit limits and outstanding are read from. **Leave it blank and credit checks silently read nothing.** |
| **Default Price List** | Where item rates come from when a rep's own profile and the distributor do not name one |
| **Support Contact** | Shown on the rep's phone when something fails |

**Set both links now.**

## 1.3 Visit and Location

| Setting | Default | What it decides |
|---|---|---|
| **Enforce Geo Fence** | on | Whether a check-in away from the shop is flagged |
| **Default Geo Fence Radius** | 100 m | How far counts as "at the shop" when the outlet has no radius of its own |
| **Allow Geo Fence Exception** | on | Whether the rep may check in anyway with a reason |
| **Min Visit Duration** | 3 min | Below this, the visit is marked *short* |
| **Flag Mock Location** | on | Whether a faked GPS is recorded |

> **Nothing here blocks a rep.** A blocked rep stops using the app, and then there is no data at
> all. Everything unusual is recorded and surfaced in the **Visit Exceptions** report instead.
> That is the bargain — and if nobody reads that report, the bargain is broken.

## 1.4 Working Day

| Setting | Default | What it decides |
|---|---|---|
| **Require Day Start Selfie** | on | Whether a photo is needed to start the day |
| **Day Start Alert Time** | 11:00 | The hour the *Day Not Started* alert measures lateness from |
| **Auto Close Day After** | 14 h | A forgotten day is closed overnight, marked **Auto Closed** — not *Closed* |
| **GPS Ping Interval** | 90 s | How often the phone records a location |

## 1.5 Credit

| Setting | Default | What it decides |
|---|---|---|
| **Block Order On Credit Breach** | on | A breaching order is **held for a manager**, not sent to the depot |
| **Allow Manager Override** | on | Whether a manager may release it |

> **Which limit is checked depends on the mode**, and this catches people out:
>
> | Mode | Limit read from | Because |
> |---|---|---|
> | Order booking | the **distributor's** Customer credit limit | the shop is not a party to that sale |
> | Van sales | the **outlet's** own `credit_limit`, then the Customer's | the rep is selling to the shop at the counter |
>
> Setting a credit limit on the outlet and testing in order booking will show you **nothing** —
> the order sails through. Set it on the Customer.

## 1.6 Scheme Claim Settlement — *needed for Part 10*

| Setting | What it decides |
|---|---|
| **Settlement Item** | The non-stock item an approved distributor claim is credited against |
| **Trade Scheme Expense Account** | Debited by the credit note. Blank books the claim as negative sales instead of trade spend |
| **Claim Cost Center** | Blank falls back to the company default |

> A claim is **trade spend, not a return of goods.** The stock reached the distributor at full
> price and that sale stands; what is being settled is the cost of a promise a rep made at a
> counter. So the credit note is **one line** on the settlement item, and it moves **no stock**.

## 1.7 Field Expenses — *needed for Part 8*

| Setting | Default | What it decides |
|---|---|---|
| **Travel Rate Per Km** | *(none)* | Multiplied by the distance the GPS trail recorded |
| **Daily Food Allowance** | *(none)* | Cap for a food claim |
| **Daily Stay Allowance** | *(none)* | Cap for an outstation night. Zero means not claimable |
| **Receipt Required Above** | 500 | A claim over this needs a photo before it can be submitted |
| **Distance Tolerance** | 10% | How far above the trail a rep may claim without a manager |

> **Travel rate has no default on purpose.** Leave it blank and a travel claim is *refused* with
> a message naming this field — rather than priced at zero. Inventing a rate would quietly pay
> every rep a number nobody at the company chose.

## 1.8 Sync, Retention

| Setting | Default | What it decides |
|---|---|---|
| Sync Batch Size | 50 | Records per push |
| Sync Max Retries | 6 | Before the outbox gives up and asks |
| Photo Max KB / Dimension | 120 / 1280 | Compression on the phone before upload |
| GPS Trail Retention | 180 d | GPS tracks a named employee — kept only this long |
| Selfie Retention | 30 d | |
| Visit Photo Retention | 365 d | |

**Leave these alone unless you are testing them.**

---

# Part 2 — The masters

Build these in order. Each one depends on the one before.

## 2.1 Territory

**Desk → Territory → New.** Name it something you will recognise, e.g. `Pune South`.
Parent: `All Territories`. **Is Group: off.**

> Territory is the app's security boundary. A rep sees only their own territory's shops — not by
> a filter somebody remembered to write, but by a Frappe User Permission generated when the Field
> User is saved. That is why it applies to the API, the Desk, reports and exports alike.

## 2.2 Customer (the distributor)

**Desk → Customer → New.**
- Customer Name: `Mahalaxmi Distributors`
- Customer Type: Company · Customer Group: any non-group · Territory: the one above
- **Credit Limits table:** company = your company, credit limit = **50,000**

> That limit is what Part 6 will breach. Put it here, not on the outlet.

## 2.3 FieldMate Distributor Profile

**Desk → FieldMate Distributor Profile → New.**
- Customer: the one above · Territory: yours
- Credit Days: 15 · Delivery Days: 2 · Min Order Value: 500

## 2.4 Items and prices

**Desk → Item → New**, at least three. For each: non-group Item Group, stock UOM `Nos`,
**Is Stock Item on**. If india_compliance is installed you must give an HSN code.

Then **Item Price** for each: your selling price list, e.g. 122.00, 8.20, 275.00.

> An item with no price **stops the whole cart** rather than booking itself free. Leave one item
> deliberately unpriced later to see that message.

## 2.5 FieldMate Product Catalogue

**New.** Active on. Territory: yours. Add all your items.

> A blank territory means **everywhere**, which is usually what you want while testing. A
> catalogue scoped to the wrong node is the commonest reason a rep opens an empty catalogue.

## 2.6 The rep

**Desk → User → New:** e.g. `rep1@yourco.test`, first name Manoj, **no welcome email**.
Roles: **FieldMate Field Rep** only.

**Desk → FieldMate Field User → New:**
- User: that login · Full Name: Manoj Kumar · Designation: Field Rep
- **Territory: yours** · Company: yours · Status: Active
- Can Create Outlet: on · Can Collect Payment: on
- Daily Target Calls: 20

> Save it, then open the User and confirm a **User Permission** for your territory now exists.
> If it does not, the rep will see every shop on the site.

## 2.7 Outlets

**Desk → FieldMate Outlet → New**, at least five.
- Outlet Name, Mobile No
- **Distributor: the Customer from 2.2** — mandatory; an order cannot route without it
- Territory: yours · **Approval Status: Approved**
- Latitude / Longitude: roughly where you will be standing, if you want geo-fence to behave

## 2.8 Beat

**Desk → FieldMate Beat → New.**
- Beat Name, Territory, **Assigned To: your Field User**
- Frequency: Weekly · Visit Day: today's weekday
- Add your outlets in the child table

## 2.9 A scheme

**Desk → FieldMate Scheme → New.**
- Scheme Name: `10% on 20 pieces` · Type: Volume Slab · Priority: 10 · Active
- Basis: Qty · Basis UOM: Unit · Measured Over: Item Set · Stacking: Stackable
- Valid From: last week · On Exhaust: Block
- **Budget Amount: 5,000** — Part 7 will exhaust it
- Items: one of your SKUs
- Slabs: `#1 · from 20 · open ended · Percent Discount · per Slab · 10%`

**Submit it.**

## 2.10 Checklist and reasons (optional)

**FieldMate No Order Reason**, **FieldMate Deviation Reason**, **FieldMate Checklist Template** —
create a couple of each if you want to see those screens do something.

---

# Part 3 — The rep signs in

1. On an Android phone, open `https://testerp2.web.gargsystems.com/fieldmate`
2. Sign in as `rep1@yourco.test`
3. **Add to home screen** when offered

**Expected:** it opens standalone — no browser address bar.

**Check:** turn on aeroplane mode and reopen it. The shell and your profile should still load.
A white screen here means the service worker did not install.

---

# Part 4 — The day starts

On the phone: **Start day**.

1. Selfie (if required) · 2. GPS fix · 3. Pick today's beat

**Expected:** Today shows the beat and its shops in order.

**Check in Desk:**

| Document | Should show |
|---|---|
| **FieldMate Day Start** | one, today, docstatus 1, your rep |
| **FieldMate Location Trail** | appears once a few GPS pings are in |
| **Employee Checkin** (HRMS) | an IN punch, **if** the Field User has an Employee linked |

> The Employee Checkin is a bonus, not a gate. A rep with no Employee record still gets their day.

---

# Part 5 — A visit

Walk to a shop (or pretend). On the phone: **Start next visit**.

## 5.1 Check in

**Expected:** if you are within the radius, it checks in quietly. Outside it, you are asked for a
reason — and **it still lets you in**.

**Check in Desk → FieldMate Visit:**
- `distance_from_outlet_m` is a real number
- `is_geo_fence_breach` is set if you were outside
- a **FieldMate Geo Fence Exception** exists if you gave a reason

## 5.2 The visit hub

From here the rep can reach: stock check, merchandising photo, checklist, **order**, collection,
check out.

## 5.3 Stock check

Count a few SKUs. **Expected:** last month's count is offered beside each line, so "same as last
time" is one tap.

**Check:** `FieldMate Retailer Stock`, one row per SKU counted.

> **Nothing here moves stock in ERPNext.** It is a count at somebody else's shelf.

---

# Part 6 — An order, and the scheme

**This is the heart of the app. Take your time here.**

## 6.1 Build the cart

Catalogue → pick your scheme SKU → **quantity 20**.

**Expected before you leave the cart:**
- the 10% discount appears **as you type the twentieth piece**, not after submitting
- the scheme is named, not just a figure
- the net total is the figure the rep would say out loud

**Check the arithmetic by hand.** 20 × 122.00 = 2,440.00 · less 10% = 2,196.00.

> The phone works this out **offline**, with its own copy of the scheme rules. The server works
> it out again on submit. If they ever disagree, the order records **both** — `proposed_net_total`
> is what the rep said to the shopkeeper, kept exactly as sent, and `totals_match` says whether
> the server agreed. That field is the whole early-warning system for scheme bugs.

## 6.2 An unpriced item

Add the item you left without a price.

**Expected:** it is named and excluded, and the order **refuses to commit** until you remove it.
Not booked free.

## 6.3 Submit

**Expected on the phone:** confirmed, with the net total.

**Check in Desk → FieldMate Order:**

| Field | Should be |
|---|---|
| Status | **Sent To Distributor** |
| Distributor | your Distributor Profile |
| Sent To Distributor On | a timestamp |
| **Sales Order** | **empty** |
| Totals Match | ticked |

## 6.4 The checks that matter most

Before the order and after it, note the counts of these. **None may change.**

- [ ] **Sales Order**
- [ ] **Sales Invoice**
- [ ] **Delivery Note**
- [ ] **Stock Ledger Entry**
- [ ] **GL Entry**

> If any moved, stop and tell me. That is ADR-023 broken, and it means the company's books are
> recording a sale it did not make.

## 6.5 The scheme ledger

**Desk → FieldMate Scheme Ledger.** One row per benefit granted, submitted, naming the order, the
shop and the rep.

**Check:** the scheme's **Consumed Amount** has gone up by exactly that benefit.

## 6.6 Submit the same order twice

On the phone, with signal off, submit — then turn signal on and let it sync. Or in Desk:

```
/api/method/fieldmate.api.order.submit?payload={"outlet":"<outlet>","client_uuid":"<the same uuid>","lines":[...]}
```

**Expected:** **one** order, and the second call returns the same one.

> This was a live bug until Gate 4 found it: the online path raised a duplicate-key error and the
> rep, told only that it had failed, retyped the whole cart.

## 6.7 Credit breach

Book an order worth more than the distributor's 50,000 limit.

**Expected:**
- the rep is told, at the door, before the cart is built
- on submit the order goes to **Pending Approval** — **not** to the distributor
- `credit_status` = **Breach**
- **still no accounting document of any kind**

Now try to approve it **as the rep**:

```
/api/method/fieldmate.api.order.approve?order=FM-ORD-000123&decision=Approved
```

**Expected:** refused. A rep cannot sign their own.

Sign in as a manager (a user with **FieldMate Area Manager**) and approve it.

**Expected:** *now* the order reaches **Sent To Distributor**, the scheme accrues, and the visit
is rolled up. Still no accounting document.

> This was the second bug Gate 4 found. The approval was being *recorded* and enforcing nothing —
> every breaching order reached the depot anyway, and Desk made it look like a control.

## 6.8 Cancel

Cancel the order.

**Expected:** the scheme ledger rows are **cancelled**, not relabelled, and the scheme's consumed
budget goes back down. No orphan anywhere.

---

# Part 7 — Budget exhaustion

Book enough orders to use up the scheme's 5,000 budget.

**Expected:** with **On Exhaust = Block**, the scheme stops applying once the budget is gone.
Consumed never exceeds the budget.

**Check:** the scheme ledger's total equals the consumed amount, to the paisa.

---

# Part 8 — Money, and expenses

## 8.1 A collection at a shop

On the phone, from the visit: **Collect**. Take 1,000 in cash.

**Expected on the receipt:** the money belongs to the **distributor**.

**Check in Desk → FieldMate Collection:** `party_type` = Outlet, `posts_to_ledger` = **off**,
`payment_entry` = **empty**.

> A shop owes its distributor, not us. The rep is carrying somebody else's cash. **No Payment
> Entry is created — ever.**

## 8.2 A collection from the distributor

Take 5,000 from the distributor.

**Check:** `party_type` = Distributor, `posts_to_ledger` = **on**, `payment_entry` still
**empty**.

> Ours, yes — but nothing posts until somebody at our end confirms the deposit.

## 8.3 Deposit

On the phone: **Hand in**. Declare both collections.

**Expected:** the deposit is **Declared**. Payment Entry count **unchanged**.

Now, as a *different* user in Desk, confirm the deposit.

**Expected:** **one** Payment Entry, for the **distributor's 5,000 only**. Not for the shop's
1,000.

## 8.4 A travel claim

Set **Travel Rate Per Km** to 3.50 first, or the claim is refused.

Phone → **Today → Claim expenses**.

**Expected:** the distance the GPS trail recorded is already filled in, with the ping count and
the check-in count, and rate × distance worked out.

1. File it unchanged → **Approved** straight away
2. File another day at **+50%** → held at **Pending Approval**, with the excess named in km and percent
3. File a third at **+5%** → approved; a trail drops pings in basements
4. Try to approve your own inflated claim → **refused**

---

# Part 9 — Van sales *(optional — only if you sell off a vehicle)*

Turn **Enable Van Sales** on and set the rep's Sales Mode to Van Sales.

1. **Today → Load the van** — record what is on board
2. Sell at a counter — the shop is billed **by the distributor**, and cash is taken at the door
3. **Today → Settle the van** — what went out, what sold, what came back

**Expected:** loaded − sold − returned = **0**. A shortfall cannot be settled without an
explanation.

**The checks:** **no Stock Ledger Entry, no GL Entry.** The van holds the distributor's stock.
A shortfall is a conversation, not a journal entry.

---

# Part 10 — The depot, and claims

## 10.1 A depot login

```
cd ~/frappe/frappe-bench-v15/sites
../env/bin/python ../apps/fieldmate/scripts/setup_phase9.py
```

It prints two logins and the password, and sets the claim settlement config.

Or by hand: a **Website User**, then **FieldMate Portal User** linking it to your distributor
profile. The `FieldMate Distributor` role appears by itself — do not add it manually.

## 10.2 The queue

Sign in **in a second browser** as the depot and open `/distributor/orders`.

**Expected:** your rep's orders, with shop names, rep names, line counts and values. Expand one —
lines in the unit the rep sold in (2 Cases, with 24 Nos underneath), free goods in green at zero,
and a note saying this is the depot's bill to the shop and posts nothing in our books.

## 10.3 Work it

**Accept** → **Mark invoiced** (it demands an invoice number) → **Mark delivered**.

**Check:** **FieldMate Order Ingest Log** — three rows, each with from-status, to-status, who and
when.

## 10.4 It reaches the rep

On the phone, sync.

**Expected:** the same order now reads **Delivered**, with the depot's invoice number.

> Without this the rep is the last person in the chain to know, and the shopkeeper asks *them*.

## 10.5 Only their own

Copy an order name belonging to a **different** distributor and, as the depot, open:

```
/api/method/fieldmate.api.portal.order_detail?order=FM-ORD-000123
/api/resource/FieldMate Order/FM-ORD-000123
```

**Expected:** both refused, and the message says *not found* rather than *belongs to someone
else* — the second phrasing confirms the name is real to whoever is probing.

## 10.6 A claim

Depot → **Scheme Claims → Raise a claim**. Pick the period your orders were in.

**Expected:** a preview — *₹x across n benefits at m shops* — before anything is created.
Raise it.

**Expected on the claim:** status **Pending Approval**, and a green **Matches the ledger** pill.
Open it: every line names its order, shop, rep and benefit, and the *Against the ledger* panel
shows a difference of **₹0.00**.

Try to raise the same claim again → *nothing left to claim*.

## 10.7 Approve it

In Desk, approve the claim.

**Expected:**

| | |
|---|---|
| Claim | **Settled**, with a Credit Note link |
| Credit Note | a **Sales Invoice with Is Return ticked** |
| Customer | the **distributor's**, not the shop's |
| Items | **one line**, on the settlement item — not one per SKU |
| Account / Cost Centre | the ones you configured |
| **Stock Ledger** | **unchanged** |

Call settle again → the **same** credit note comes back, not a second one.

**Reject** a different claim → refused without a reason; give one, and the scheme ledger rows go
back to **Accrued** so the depot can fix and re-claim.

---

# Part 11 — End of day

Phone → **Finish day**.

**Check → FieldMate Day End:** duration, distance, planned vs actual visits, productive visits,
orders count and value, collection amount — **all filled in, none zero** if you did the work.

> Those figures are computed on the server, not sent by the phone. A phone that has been offline
> all day cannot know what finally synced.

---

# Part 12 — Targets and incentive

```
../env/bin/python ../apps/fieldmate/scripts/setup_phase7.py
```

Or by hand: give the Field User a **Sales Person**, create a **FieldMate Target Plan** at the top
of that tree, submit it, then:

```
/api/method/fieldmate.api.target.cascade?plan=FM-TGT-2026-00001
/api/method/fieldmate.api.target.reconcile?plan=FM-TGT-2026-00001
```

**Expected from reconcile:** `matches: true`, and per type:

| Type | |
|---|---|
| Value, Volume, Coverage, Calls, New Shops | leaves **sum** to the root, difference **0** |
| **Lines Per Call** | **copied** to every leaf — `leaves: [4.5]` |

> A rate has no total. A root asking 4.5 lines a call asks *each* rep for 4.5; dividing it
> between twenty reps would set each of them 0.225 lines.

Then measure and look at the phone:

```
/api/method/fieldmate.api.target.recompute?plan=<the rep's leaf plan>
```

Phone → **Today → My performance.**

---

# Part 13 — Analytics and alerts

```
../env/bin/python ../apps/fieldmate/scripts/setup_phase8.py
```

It rolls up the last 90 days from what you have actually done, installs the five alert rules and
evaluates them. **It invents nothing** — every number is one you can go and check.

## 13.1 Check a number by hand

Open one **FieldMate KPI Snapshot** row. Note orders, value, shops billed, calls, productive.
Now count them yourself in the Order and Visit lists for that rep and date.

**Expected:** identical, to the paisa.

## 13.2 The one that is not a sum

In **Rep Scorecard**, look at a rep's strike rate for the month. Now average their daily strike
rates by hand.

**Expected: they differ, and the scorecard is right.** It divides total productive calls by total
calls. One call converted, then twelve with three converted, is 4 in 13 — not the average of
100% and 25%.

## 13.3 Alerts fire once

```
/api/method/fieldmate.api.dashboard.run_alerts?days_back=30
```

Run it three times. **Expected:** `fired` is 0 after the first, `already_logged` climbs. An
occurrence is rule + rep + day, and it is logged once.

## 13.4 The rep's own screens

**Today → How today is going** — three tiles, a three-segment bar, a 14-day sparkline. Book an
order and refresh: the tiles move **immediately**, because today is counted live.

---

# Part 14 — The list of things that must never happen

Run through this at the end. **Each one is a bug if it happens.**

- [ ] A **Sales Order** created by a retailer order
- [ ] A **GL Entry** from an order, a van sale, a collection, or a deposit *declaration*
- [ ] A **Stock Ledger Entry** from anything in FieldMate
- [ ] A **Payment Entry** for money collected at a **shop**
- [ ] A **Payment Entry** before a deposit is **confirmed**
- [ ] A credit-breaching order reaching the depot **without** approval
- [ ] A rep approving **their own** order, expense claim, or deposit
- [ ] A rep seeing another rep's targets, payouts, expense claims or KPI rows
- [ ] A depot seeing another depot's orders or claims
- [ ] The same **client_uuid** producing two documents
- [ ] An alert firing twice for the same rep on the same day
- [ ] A cancelled order still counting in targets or KPIs
- [ ] A settled claim or paid payout being cancelled without reversing the payment first

---

# How to report what you find

For each problem, tell me:

1. **Where** — the screen or the API call
2. **What you did** — the steps, in order
3. **What you expected**, and **what happened**
4. **The document name** if there is one (`FM-ORD-000123`)
5. A screenshot if it is a screen

The document name matters most. With it I can read exactly what the server did and why.
