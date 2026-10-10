# Phase 2, the Holi season — what a person has to check

`scripts/gate_phase2.py` proves the plan's four "done when" lines on a real site and prints a pass
or a fail for each. Run that first:

```
cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate_phase2.py testerp2.web.gargsystems.com
```

This sheet is the rest, and the rest is most of what a person actually touches:

- **the phone** — the booking chip, the delivery dates, the season book, the deposit screen's PDC
  block. The Vitest suite in `frontend/tests/` covers the arithmetic and the words on these
  screens, but nothing has ever drawn them on a handset.
- **the two Desk pages** — allocation and the cockpit. Their services are tested; the pages are
  not, at all.
- **the showcase as a stranger sees it** — the one page in this app with no login behind it.
- **the e-way bill**, which cannot be raised on this bench and is here so that nobody records it
  as done.

---

## Before you start

Nothing below works on an empty site, and **an empty site looks exactly like broken software**:
with no season there are no bookings, the season book is blank, the allocation and cockpit pages
have nothing to list, and the share screen says nothing can be shared. One command fixes that:

```
cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase2_season.py
```

It makes a season whose book is open today and whose lorries leave in two months, a price list of
its own with every catalogue item priced **10% under** the everyday list, a payment terms template
for the balance, the party's warehouse, **20 of each item in stock**, and a copy of the working
catalogue marked as a showcase. `--show` prints what is there; `--undo` takes it back out.

It does **not** book anything. That is section 2 and it is the rep's job.

Two things it may print, and both matter:

| It says | What it means |
|---|---|
| `WARN  n catalogue item(s) have no price at all` | Those lines will read **no price yet** on the phone. That is correct behaviour over a pricing job nobody has done — not a bug, and worth fixing before you demonstrate anything. |
| `WARN  stock reservation is switched off` | Allocation will refuse by name. Stock Settings → Enable Stock Reservation. |

**Running a gate closes this season for the duration of its run**, and puts it back afterwards.
It has to: an open season makes every primary order a booking of it, so neither phase gate can
measure anything with somebody else's book open. A gate interrupted halfway therefore leaves the
season **closed**, and a closed season looks exactly like a working site on which nothing will
book. `--show` prints `active` first for that reason; run the setup script again to re-open it.

**The stock is short on purpose.** Twenty of each against two bookings asking for thirty, because
with a full warehouse all three allocation rules hand everybody everything and section 7 has
nothing to compare.

Sign in on the phone at `https://<site>/fieldmate` as a rep in the party's territory
(`test@rep.com` on testerp2), and in Desk as a manager.

---

## 1. The phone knows it is taking a booking before the cart is built

1. **Orders** tab → **Order on a distributor** → pick the party.
2. Build a cart, then open **Review**.

**What must be true.** Above *What the party pays* there is a card headed
**Booking · \<season name\>** saying four things: the rates are held for this season, the advance
to collect, the delivery window, and — if the cutoff has passed — that the book is shut for
changes.

**The one to watch, and the reason this section is first.** Compare a rate on the catalogue screen
with the same item's rate in Desk on the season's price list. They must be the **season's** rate,
not the party's everyday one.

This was wrong until step 11. The catalogue the rep browses was priced from the party's everyday
list while the server booked the order from the season's, so a rep read out a figure 10% above
what was recorded and `totals_match` was zero on every booking. The seeding script in *Before you
start* is what exposed it, because it is the first thing that ever put a season price list and a
party price list on the same site with different rates on them. **If the catalogue rate and the
booked rate differ by a round percentage, that defect is back.**

## 2. The delivery dates, and the window that refuses them

On the review screen of a booking:

1. **When is this wanted** holds a date, already filled with the season's first delivery day.
2. Each line in *What was ordered* carries its own date box beside the figure.

**What must be true.**

- Changing the order-level date moves every line that has not been set individually.
- A line set outside the window puts a red note above the button naming **every** such line, and
  the send button greys. The server refuses one line at a time; this screen names all of them, so
  a rep is not sent round the loop three times at a counter.
- The date picker will not offer a day outside the window.

Then send it, and in Desk open the Sales Order: each line carries the date the rep chose, not the
order date.

## 3. Booking it, and the hold it sits in

Send the booking.

**What must be true on the confirmation screen.** It says **Booked**, names the season, and —
because the seeded season asks for 25% — tells the rep how much to **collect to release this
booking** and that nothing is reserved or dispatched before then.

It must **not** say "Sent to the distributor" or that somebody else will bill the shop. A booking
is a sale we raise and we invoice; that sentence belongs to a retailer order and used to appear on
every order of every kind.

In Desk: the FieldMate Order is **Awaiting Advance** and has **no Sales Order** against it. That
negative is the commercial point of the whole phase — the company plans against the book, and
nothing is planned for a booking nobody has paid for.

## 4. The advance, and the cheque that does not count

On the phone, **Collections** → **Take from a depot**.

1. **Against a booking** lists the bookings still short, with what each is short of.
2. Pick the one you just took. The depot is set from that booking and the shortfall is suggested
   as the amount.

**What must be true of step 2.** The depot follows the booking and is not left as whatever was
chosen before. A receipt saved against one depot while allocated to another party's booking is
money credited to the wrong account and an advance releasing somebody else's order.

Tapping **Collect …** on the season book arrives here with all three already filled in.

**Do the post-dated cheque first.** Choose mode **Cheque**, give it a date a month out, and record
it for the full advance.

**What must be true.** Before saving, the screen says a cheque dated later **does not release the
booking** — it is held against it and the booking goes forward when the cheque falls due. After
saving, the order in Desk is **still Awaiting Advance** and still has no Sales Order. A rep who
reads a PDC as payment tells the party their stock is coming when nothing has been set aside.

**Then the cash.** Record the advance again as **Cash**.

**What must be true.** The screen says *This releases the booking*. In Desk the order is now
**Approved** with a Sales Order against it, and that Sales Order's **Payment Schedule** has two
rows from the season's terms template — 50% at 30 days, 50% at 60.

## 5. The season book

**Orders** → **Season book**, or `#/bookings`.

**What must be true.** One card per booking, and on each: what the advance is, what has arrived,
what is still to collect, and a bar. At the top, the total still to collect across the list — the
figure a day's plan comes off.

Where a post-dated cheque is held, it is reported **beside** the shortfall and never inside it,
with *does not count until it falls due*. The status reads **Waiting for the advance**, not
"waiting on your manager": nobody is deciding anything, and a rep chasing a manager over it is a
rep wasting a morning.

Tap **Collect …** on a held booking. It opens the depot form of section 4 with that booking
already chosen.

## 6. The deposit screen tells a PDC from money

**Collections** → the satchel → **Hand in the money**.

**What must be true.**

- The post-dated cheque's row is marked **Dated \<date\> — not bankable yet**.
- It appears under its own heading, **Post-dated cheques**, not among *Cheques in the envelope*,
  and the block says the office holds each one until its date and that **no booking is released**
  before then.
- The tiles carry a **Post-dated** column, which is part of the cheque figure beside it and not on
  top of it.
- The bottom line says how much of the declaration will not clear yet.

All of it is still tickable and still handed in. A rep who thinks a PDC is useless keeps it in the
satchel, and then nobody has it at all.

## 7. Allocation, three ways

Desk → **Season Allocation** (`/app/fieldmate-allocation`).

Take a **second** booking on the phone first, smaller than the first, so there is something to
divide. With 20 in stock against 30 asked for:

1. Pick the season and a rule, then **Preview**. Nothing is reserved until **Apply**. Do all
   three rules in turn.

**What must be true.**

| Rule | What the table must show |
|---|---|
| Advance First | the booking with money against it filled first |
| First Booked | the earlier booking filled first |
| Pro Rata | both cut by the same proportion, **in whole units** — 14 and 6 of 20: each share floored to 13 and 6, and the stray unit to the larger ask |

Nothing in any preview exceeds what is in stock, and every row says what it is short of.

2. **Apply** one — it asks first, because this reserves real stock against real Sales Orders.
   Then open a Sales Order in Desk: it carries **Stock Reservation Entries**.
3. **Revert**. The reservations are gone and the stock is free again. Anything already delivered
   stays where it is, which is ERPNext's rule and the right one.

**Preview after Apply shows what is left, not what there was.** ERPNext subtracts live
reservations from what it calls available, so reverting first is what gives a clean slate. A
second preview showing smaller numbers is the system working.

Pro rata giving 14/6 rather than 13.33/6.67 is correct, and it is the one number on this sheet
most likely to be reported as a bug: nobody can reserve a third of a bar of soap, so each share is
floored and the stray unit goes to the largest ask. `allocation.split` says so.

## 8. Dispatch, and the advance on the bill

Desk → **Season Allocation** → the **⋯ menu**, which is where dispatch lives: *Deliver what is
held*, *Invoice what has shipped*, *Build a delivery trip*, and *Where has it got to?*

1. Allocate the season (section 7).
2. **Deliver what is held**. One submitted Delivery Note per booking. It asks first, because the
   goods leave the building.
3. **Invoice what has shipped**. One submitted Sales Invoice per note.

**What must be true.** Open the Sales Invoice. Its **Advance Payments** table carries the Payment
Entry from section 4, and the **outstanding** is the bill *less* the advance. Without it the party
is billed for money they handed over, their payment sits unallocated on their account, and the
receivable is wrong until somebody journals it by hand. The gate found this missing; it is the one
defect this phase's gate caught.

4. **Build a delivery trip**, giving it a vehicle and a departure time. Both are ERPNext's
   requirement and a reasonable one: a trip is a specific van leaving at a specific time, and one
   without either is a list of addresses.

**What must be true.** The Delivery Trip groups the day's notes and stays a **draft**. A submitted
trip says a van is going when nobody has agreed to drive it.

Run deliver and invoice **twice**. The second run must report the documents the first one made and
create nothing — the warehouse must not ship the same booking twice because somebody pressed a
button again while a long run was still going.

## 9. The cockpit

Desk → **Season Cockpit** (`/app/fieldmate-season-cockpit`).

**What must be true.** Booked, allocated, delivered and billed by state, by party and by SKU. The
state columns account for every booking **exactly once**. The value is the sum of the bookings, and
*owing* is that value less what has arrived.

Every state figure is read back from the Delivery Notes and Sales Invoices themselves, so a
booking that shows as Delivered has a Delivery Note you can open. The page keeps no count of its
own, deliberately — a number we kept would be a claim.

Then the **⋯ menu** → *Who is late*. It lists the parties whose balance is overdue, or says
nothing is. Those parties and their managers are told once a day by the scheduled reminder, so
check the scheduler is running before concluding that nobody is being chased.

Then reconcile one figure by hand against Desk: the value of the posted bookings against the sum of
their Sales Orders. The **goods** figure must match to the paisa.

**The tax will not match on this bench, and it is not the cockpit's fault.** See section 11.

## 10. The showcase, as a party sees it

On the phone: **Orders** → **Share the range**, or `#/showcase`.

1. Pick the party. The catalogue list shows only what is **marked as a showcase** — the working
   catalogue must not appear, because it carries focus flags, minimum order quantities and notes
   written for the person selling.
2. Make the link. The address is shown as text as well as copied, so a browser that refuses the
   clipboard does not leave the rep with nothing.

**Now open that link in a private window, signed out of everything.**

**What must be true.**

- It draws the party's **own** prices, names the party, and says who prepared it.
- An item with no price is **left out**, not shown at nothing.
- Put quantities against something and send it. The page says it has gone to the representative —
  never that an order was placed.
- On the phone, that arrives as a **draft FieldMate Order** for the rep, with *shared catalogue* in
  its remarks. It shows in **My orders** as *Not sent*. It is not submitted, and it must not be: a
  party typing into a web page has been through no credit check, no scheme engine and no MRP check.
- **But the rep cannot submit it from the phone either.** There is no endpoint that submits an
  existing draft — `order.submit` takes a cart and does both at once — so the only way to act on a
  self-order today is to open it in Desk. The loop this feature exists to close is not closed on
  the handset. Check it in Desk, and read the last section of this sheet.
- An item code the link does not show, if you can contrive to send one, is dropped.

Then, back on the share screen, **Switch it off** — two taps, and it says it cannot be undone.
Reload the public link: it says **Not available** and nothing else. Not who it was for, not when it
expired, not how often it was opened. Those are facts about a conversation the visitor may not have
been part of.

Check the page's source for `noindex`. A shared price list is not something to find in a search
engine.

## 11. The e-way bill, and the tax that does not match

**Neither of these can be checked on testerp2, and both have the same cause:** company `test` has
no GSTIN and no address, so india_compliance can determine no place of supply.

- **No e-way bill can be raised.** The Sales Invoice it would hang off is posted and correct;
  nothing else in dispatch depends on it.
- **A booking quotes a tax the company does not bill.** FieldMate's tax comes from the **Item Tax
  Template** on the item or its group. ERPNext puts tax on a sales document from a **Sales Taxes
  and Charges Template in its header**, and an Item Tax Template only overrides a rate on an
  account row that header already carries. With no header template there is no tax on the Sales
  Order or the invoice at all — so an order reads ₹3,360 to the rep and the invoice goes out at
  ₹3,000, and nothing in the app notices.

The gate reports this as criterion 5, *not answerable on this bench*, every run. **Nothing has been
changed for it**, because it is a decision about GST rather than a patch: fill in the company's
GSTIN and address, or have the app refuse when its computed tax has no ERPNext tax head behind it,
or take our tax from where ERPNext takes its own. On a pilot site with a GSTIN, that criterion asks
the real question and this section becomes a test rather than a note.

---

## What is still missing after this sheet

Said plainly, because a phase that reports itself finished when it is not is worse than one that
reports a gap:

- **The two Desk pages have no automated cover at all.** Their services are tested thoroughly;
  the pages themselves are checked by a person or not at all.
- **The e-way bill has never been raised**, here or anywhere.
- **The tax head is unresolved** and is a known issue, not a passing test. Section 11.
- **A booking cannot be amended from the phone.** The cutoff rule is enforced and the server
  accepts an amendment, but there is no screen for it — a change goes through Desk.
- **A self-order draft cannot be submitted from the phone.** The showcase puts a draft in the
  rep's orders list and there it stops: `order.submit` creates and submits in one call and there
  is nothing that submits a draft already on the server. A rep who shares a catalogue has to
  finish the order in Desk, which is not what step 8 set out to build.
- **Nothing converts the November orders.** The plan's "convert November orders" row is a patch
  that was never needed on this bench, because no primary orders were taken before the season
  existed. A pilot that took some will need one.
- **The allocation page previews one season at a time.** A company running two overlapping
  seasons is refused at the master, so this is a limit of the design rather than of the page.
