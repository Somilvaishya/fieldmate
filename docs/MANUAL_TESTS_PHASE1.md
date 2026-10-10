# Phase 1 — what a person has to check

`scripts/gate_phase1.py` proves eight things on a real site and prints a pass or a fail for each.
Run that first:

```
cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate_phase1.py testerp2.web.gargsystems.com
```

This sheet is the rest — **the phone**. Step 9 built a party picker and taught the four order
screens to carry a party, and none of it has automated cover: this repo has no frontend test
harness, and adding one was not part of the step. So the PWA half of Phase 1 is **untested code
that has been built and bundled and never run by anybody**. That is what this sheet is for.

Everything below is done on a handset or in a phone-sized browser window, signed in as a rep.

---

## Before you start

Four things have to be set up on the site, and three of them were being set up by hand during
Phase 1 because nothing creates them:

| What | Where | Without it |
|---|---|---|
| A distributor with **Channel Tier** set | Customer → FieldMate Channel | Shops cannot be onboarded and no party appears in the picker |
| A **PTR Price List** on that distributor | Customer → PTR Price List | Shops fall through to the company's default list |
| A **Payment Terms Template** on that distributor | Customer → Payment Terms | The counter shows no credit terms |
| An **Item Tax Template** on the Item Group | Item Group → Item Tax | No GST row appears anywhere |

Set the tax template's **rate**, not just its name. A template called "GST 12%" with a rate of
zero reads as zero everywhere, which is correct and looks like a bug — it happened twice during
this phase.

---

## 1. A shop order shows the GST the distributor will bill

1. Open a shop from Today and build a cart.
2. On the cart screen, below **Net payable**, there is a **GST** row and a **Bill total**.

**What must be true.** The bill total is the net plus the GST. The bottom bar shows the bill
total, not the net — the number a rep reads out has to be the number on the invoice that arrives
that evening.

**If the GST row is missing**, no tax template covers those items. That is deliberate: a zero GST
row is a claim about the company's tax position rather than a fact about the order.

## 2. An item priced above its MRP cannot be ordered

1. Set an Item's **MRP** below its price on the shop's list.
2. Open the catalogue on the phone and pull to refresh.

**What must be true.** The item shows *Priced above its MRP of …* instead of a price, and the
quantity buttons are replaced by a line telling the rep to ask their manager. Tapping it anywhere
else must not add it.

## 3. A primary order, end to end

This is the step with no automated cover at all. Take it slowly.

1. **Orders** tab → **Order on a distributor**.
2. The list shows the parties this rep sells through, each with its terms underneath.
3. Pick one. The catalogue opens.

**What must be true at each hop:**

- The catalogue is priced off the **party's own** price list, not a shop's.
- The URL carries `?party=Customer`. Every link onward — cart, schemes, review — keeps it.
- The review screen's party is the distributor, not a shop.
- Sending it creates a **Sales Order** in Desk, billed to that party. A shop order creates none.

**The one to watch.** Go back and forth between the catalogue, the cart and the review screen a
few times. If any hop loses `?party=Customer`, the next screen re-prices the same cart as a shop
order — a different price list and a different credit limit, with nothing on the screen to say it
changed. The cart remembers the party type for exactly this reason, so a lost query should
recover, but a hop that drops it is still a bug worth reporting.

## 4. A primary order survives no signal

1. Build a primary cart with signal.
2. Turn the phone's data off.
3. Change quantities. Re-open the screen. Send it.

**What must be true.** Quantities re-price with no spinner and no network. The order queues and
goes when signal returns. When it lands, it is still a primary order on that party — not a shop
order.

## 5. Both sides of the credit are shown

On the review screen of a **shop** order, the credit card shows the distributor's position with
us. Below it, where somebody has given the shop a credit limit, there is a line reading
*This shop owes its distributor …* marked **our own count**.

**What must be true.** The two figures are different numbers and are labelled differently. The
first comes from ERPNext's receivable; the second is this app's own arithmetic over the orders it
booked and the money collected. A rep arguing either one across a counter has to know which it is.

## 6. A depot sends its own sales file

Signed in as a distributor login, not a rep.

1. **/distributor/sales**.
2. The page lists the column names the reader understands.
3. Pick a CSV, give the dates it covers, send it.

**What must be true.** The result says both numbers — how many lines were read *and* how many
could not be, with row numbers and reasons. A file of 347 lines with 3 bad ones imports 344 and
names the 3.

Then, on the phone, open a shop that appears in that file and look at its outstanding. For the
dates the file covers, the bills are now **the distributor's invoices**, not the orders this app
booked. They must not be both.

## 7. A scheme does not cross over

1. Create a scheme with **Applies To = Secondary** and one with **Applies To = Primary**, both
   scoped to everywhere.
2. Open a shop order and a primary order.

**What must be true.** The shop sees only the Secondary one. The party sees only the Primary one.
A retailer offer landing on a distributor's own purchase is trade spend nobody budgeted.

---

## What is still missing after this sheet

Said plainly, because a phase that reports itself finished when it is not is worse than one that
reports a gap:

- **No automated test touches the PWA.** Everything in sections 1–5 is checked by a person or not
  at all.
- **A primary order cannot be created from Desk.** It is reachable from the service layer, the
  API and now the phone, but a manager cannot type one in.
- **A primary order gets no repeat-order prefill**, by design — a party orders to a plan, not to
  last month's pattern.
