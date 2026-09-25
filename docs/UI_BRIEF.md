# FieldMate — UI brief for an AI design tool

**Written for: Google Stitch, Figma Make, v0 or similar.** Paste the *House style* section once,
then **one screen prompt at a time**. Pasting the whole document as a single prompt produces
mush — these tools do markedly better work one screen at a time.

The constraints here are not preferences. They come from `docs/DESIGN.md`, which was written from
how the app is actually used, and a screen that breaks them is wrong however good it looks.

## Contents

| Phase | Screens | Status |
|---|---|---|
| [0–1](#phase-01--getting-in-and-the-shops) | Sign in, Today, shop list, shop detail, add a shop | **built — redesign these first** |
| [2](#phase-2--the-working-day) | Start day, Finish day, route | **built — redesign** |
| [3](#phase-3--the-visit) | Check in, visit hub, checklist, shelf check, check out | **built — redesign** |
| [4](#phase-4--orders-and-schemes) | Catalogue, cart, scheme preview, review & submit | not built — **the densest surface in the app** |
| [5](#phase-5--stock-and-van-sales) | Shop stock audit, van load, van settlement | not built |
| [6](#phase-6--collections) | Outstanding, collection entry, deposit | not built — **money, so design carefully** |
| [7](#phase-7--targets-and-expenses) | My performance, expense claim | not built |
| [8](#phase-8--rep-dashboard) | Today at a glance, this month | not built |
| [9](#phase-9--distributor-portal) | Orders, claims | not built — **desktop, not the field phone** |

**Do not design all of these now.** Phases 5–9 will change before they are built, and design done
too early is thrown away. Start with Today and Visit hub; get the vocabulary right; the rest
follows from it.

---

## The user, in one paragraph

A field sales rep in India visiting 30–40 small shops a day. They are **standing**, holding the
phone in **one hand**, in **direct sunlight**, often with **no signal**, while talking to a
shopkeeper who is also serving customers. They open this app 60–80 times a day. Their phone is a
four-year-old Android at 360 px wide. They are not a consumer browsing — they are a professional
trying to finish a shop in ninety seconds and get to the next one.

Design for that person. Not for a dribbble shot.

---

## House style

> Paste this block into the tool first, as the style or system prompt. Re-paste it if the tool
> starts drifting — they all do, after a few screens.

```
Design a mobile-first field sales app for Android, 360px wide. Utilitarian and legible,
like a well-made tool, not a consumer product. Dense where it saves taps, spacious where
it prevents mis-taps.

COLOURS — use these exact values, no others. They are derived from the logo and
every pairing is measured at 4.5:1 or better:
  Background      #F4F5F7
  Surface/cards   #FFFFFF
  Primary text    #05172E
  Secondary text  #465972
  Borders         #BFC7D2
  Primary action  #092850  (deep navy, from the logo)
  Tinted fill     #E6EAEE  (navy text sits on this)
  On primary      #FFFFFF
  Success/synced  #277D40   on a #E4F6E9 card
  Warning/pending #955F07   on a #F9ECD8 card
  Critical/error  #C62A25   on a #FAE4E3 card
  Brand accent    #3BBF62  (green — FILLS AND ICONS ONLY, NEVER TEXT ON WHITE)

TYPOGRAPHY:
  System font stack only. No Google Fonts, no web fonts.
  Body text 16px minimum. Never smaller, anywhere, for any reason.
  Primary values (shop names, totals, quantities) 18-20px.
  Line height 1.5 minimum.
  Tabular numerals wherever digits line up in a column.

RULES:
  Every tap target is at least 48x48px with 8px between adjacent targets.
  All text is at least 4.5:1 contrast. No grey on grey — it vanishes in sunlight.
  The one primary action on each screen sits in the BOTTOM THIRD, full width,
    because the screen is used one-handed while standing.
  Bottom sheets, never centre modals — a centred modal is out of thumb reach.
  Cards: 6px radius, one 1px border, no drop shadows. Bottom sheets: 16px top radius.
  Not every block is a card. Spend borders and fills by role.
  Every icon is paired with a text label. Mixed literacy is a real constraint here.
  No decorative animation. Nothing over 150ms.
  Design the empty state and the error state, not just the happy path.

MONEY AND NUMBERS:
  Indian numbering — ₹1,24,500 not ₹124,500.
  Amounts always tabular, right-aligned in any column.
  Never show a bare number where a unit is meant: "12 cases", "₹4,200", "86%".

VOICE:
  Plain words a rep would use. "Shop", not "outlet entity". "Take the order",
  not "initiate transaction". Errors say what went wrong and what to do next —
  never a code, never an apology, never a stack trace.
  Buttons say what will happen: "Check in", "Save shop", "Finish visit".
```

---

## A permanent element on every screen

A **state strip** pinned directly under the status bar, full width, 28 px tall:

| State | Look | Text |
|---|---|---|
| Online, nothing queued | green tint, `#2C6E45` text | `Online` |
| Offline | amber tint, `#9A6410` text | `Offline · 4 saved on this phone` |
| Syncing | navy tint | `Sending 4…` |

Never a spinner that could hang forever, and always honest about how much is waiting. A rep who
cannot tell whether their day's work has left the phone will stop trusting the app.

---

# Phase 0–1 — getting in, and the shops

### 1. Sign in
> A sign-in screen for a field sales app. Logo, phone/email field, password field, one full-width
> primary button at the bottom. Nothing else.

- The FieldMate mark on navy at the top, generous whitespace
- Two fields, 48 px tall, 16 px text
- One primary button, bottom third: **Sign in**
- Below it, muted: `Works offline once you have signed in`
- Error state: a red line under the fields — `That phone number or password is wrong.`

### 2. Today — the home screen
> The home screen of a field sales app, showing today's route progress and the primary action for
> the working day.

Seen 80 times a day. It must answer three questions at a glance: *is my day running, how far
through my route am I, is my work synced.*

- **If a visit is open**, that is the first thing on screen — a navy-bordered card:
  `Still in Sharma Kirana` / `Tap to carry on, or finish the visit`
- Day card: `Day running since 9:14` or `Day not started`, with today's route name
- Progress: `4 of 12 shops done` with a thin progress bar
- The shop list in walking order. Each row: sequence number, shop name (18 px), area, and a
  right-hand pill — `Visited` (green outline), `Pending approval` (amber outline), or nothing
- Visited rows dimmed to ~70% but still legible
- Bottom third: **Start day** or **Finish day**; under it an outlined `Sync now (4 queued)`
- Empty state, no route today: `No route planned for today.` + `Add a shop`

### 3. Shop list
> A searchable list of shops for a field rep, with a full-width action to add a new one.

- Sticky search field: `Search shops`
- Rows: shop name 18 px, area and phone muted 14 px beneath, chevron right
- Status pill where relevant
- **Add a shop** full width in the bottom third — not a small floating circle, which is hard to
  hit one-handed
- Empty state: `No shops match "kirana".` + `Clear search`

### 4. Shop detail
> A shop profile screen showing whether an order can be taken, key details, and contacts.

- Shop name 20 px, area and phone beneath
- Status card at top, bordered green or amber: `Ready to take an order` /
  `Cannot take an order yet — waiting for approval`
- Credit line where known: `Credit headroom ₹12,400`
- A plain label/value list — status, class, route, area — not a card per row
- Contacts list
- Bottom third: **Check in here**

### 5. Add a shop
> A short form to add a new shop, with a location pin capture.

- Fields: shop name, mobile, owner name, area — 48 px each, 16 px text
- A tappable tile for the pin: `Pin saved · ±18 m` once captured, green border
- Bottom third: **Save shop**
- Muted: `A manager approves new shops before orders can be booked.`

---

# Phase 2 — the working day

### 6. Start day
> A start-of-day screen with a location capture tile, a selfie capture tile, and an optional
> odometer field.

- Two large tiles, stacked, 72 px tall, green border and check once done:
  `Location captured · ±8 m`, `Photo taken · 84 KB`
- One optional number field: `Odometer (optional)`
- Bottom third: **Start day**
- Muted: `Your location is recorded through the day and stops when you finish.`

### 7. Finish day
> An end-of-day summary screen showing what the day produced.

- A 2-across tile grid, tabular numerals: shops visited, orders taken, value, distance travelled
- Coverage line: `12 of 14 planned shops · 86%`
- Optional odometer field
- Bottom third: **Finish day**

### 8. My route
> A list of the rep's assigned routes and which day each runs.

- Route cards: name, day it runs, shop count, `Next: Tuesday 29 Sep`
- Tapping one shows its shops in walking order
- Empty state: `You have no route yet. Ask your manager.`

---

# Phase 3 — the visit

### 9. Check in
> A check-in confirmation screen showing distance from the shop, with a warning state when the
> rep is far away.

- Shop name and area; a location tile showing the fix
- **The distance line is the point of this screen.** Two states:
  - Inside range: plain surface card — `24 m from the shop.`
  - Outside range: amber-bordered card — `You are 412 m from this shop, outside its 100 m range.
    You can still check in — your manager will see the distance.`
- An optional one-line note field
- Bottom third: **Check in**; below it outlined `Cancel`

**The far-away state must not look like a blocked state.** Nothing here stops the rep. If it
reads as a rejection, reps stop checking in and the coverage data disappears — the exact failure
the whole design is built to avoid.

### 10. Visit hub
> The screen a rep works from while inside a shop, showing elapsed time and the jobs to do.

- Shop name 20 px; beneath it `In the shop 6 min · 24 m away`
- If checked in outside range, an amber strip: `Checked in outside this shop's range.`
- Three large job rows, 72 px each, title plus progress line:
  - `Checklist` → `3 of 7 answered`
  - `Shelf check` → `What is on the shelf, and the competition`
  - `Add a photo` → `2 waiting to send`
- A remarks textarea
- Bottom third: **Finish visit**

### 11. Checklist
> A survey form with mixed question types — yes/no, rating, single choice, multi choice, number
> and free text.

- Each question in its own bordered card; question 16 px semibold, muted help text beneath
- Required questions marked with a red asterisk
- **Yes/No and choice questions are chip rows** — 48 px pills, selected chip filled navy with
  white text. Not radio buttons, not a dropdown
- Rating is 1–5 chips; number questions open the numeric keypad
- Out-of-range answers show an amber line and are **saved anyway**: `Expected between 0 and 50.
  Saved anyway — check it is right.`
- Bottom third: **Back to visit**, with `2 required questions left` above it
- Empty state: `No questions are set for this shop today.`

### 12. Shelf check
> A merchandising audit screen — tick which products are on the shelf, count facings, and add
> competitor products.

- Summary strip, tabular: `Ours 12 · Theirs 10 · Share 55%`
- One optional field: `Facings on the whole shelf`
- Product rows: 24 px checkbox, product name, narrow right-aligned facings field disabled until
  ticked
- A competitor section, each competitor a small bordered group: brand, product, selling price,
  facings
- **Add a competitor** outlined, full width
- Bottom third: **Save shelf check**

### 13. Check out
> A visit completion sheet — pick an outcome, give a reason when there was no order, add a note.

- `Finish at Sharma Kirana`
- Outcome chips, 48 px: `Order taken`, `No order`, `Shop closed`, `Owner away`, `Enough stock`
- When anything but *Order taken* is chosen, a reason chip row appears below
- A note field whose label becomes `Note (required for this reason)` when the reason demands one
- If required questions are unanswered: an amber card — `Answer 2 required questions before you
  leave.` with a link `Open the checklist`
- Bottom third: **Check out**, disabled until complete, plus `Back to visit`

---

# Phase 4 — orders and schemes

**The densest surface in the app, and the one that decides whether reps adopt it.** An order is
taken while standing at a counter with the shopkeeper waiting. Forty taps loses the sale.

### 14. Catalogue
> A product catalogue for a field sales rep taking an order at a shop counter, with thumbnails,
> search, category tabs and quantity entry inline.

- Sticky header: search field, then a horizontally scrolling category tab row
- **A credit line pinned under the header**, before anything is added:
  `Credit headroom ₹12,400 of ₹50,000` — green, amber under 20%, red at zero.
  Credit is shown *before* the cart is built, never as a rejection afterwards
- Product rows, 88 px tall: 56 px thumbnail, name (16 px semibold), pack size and rate muted
  beneath, and on the right a **quantity stepper** — minus, a tappable number, plus. Tapping the
  number opens a numeric keypad sheet
- A scheme tag on qualifying rows: a small green-filled pill, `Scheme`
- A sticky bottom bar once anything is added: `6 lines · ₹8,420` and **Review order**
- Empty search state: `No products match "surf".` + `Clear search`

### 15. Cart
> An order cart that opens prefilled with the shop's last order, with editable lines and a
> running total.

- **Opens prefilled with the last order's lines and quantities.** A repeat order must be two taps,
  not forty. A banner says so: `Prefilled from the last order, 12 Sep. Change what is different.`
- Line rows: product name, pack, rate, stepper, line total right-aligned tabular
- Swipe or a trailing button to remove a line
- A totals block: gross, scheme discount (green, negative), net — tabular, right-aligned
- Bottom third: **See what this earns** (goes to scheme preview) or **Review order**
- Empty state: `Nothing in the order yet.` + `Open the catalogue`

### 16. Scheme preview
> A screen explaining in plain words every discount and free item an order has earned, and what
> one more case would earn.

*"Why did I get this discount?" is the single most common support call from the field. This
screen exists to end it.*

- One card per scheme earned. Each card says, in words, what triggered it:
  `Surf Excel 1kg · 4 cases` → **`Qty slab 4+ cases → 3% off`** → `You saved ₹126`
- Free goods shown as a line with a thumbnail: `Free: 2 pc Lifebuoy soap`
- **A "nearly there" card** where relevant, amber-bordered:
  `Add 1 more case of Surf Excel to reach the 5-case slab — 5% off instead of 3%.`
  with an `Add 1 case` button. This is the screen's commercial job
- A totals line: `Total saved ₹412`
- Bottom third: **Review order**

### 17. Review and submit
> An order review screen showing the totals, the credit position after this order, and any
> approval that will be needed.

- Shop name and delivery date at the top
- A collapsed line summary: `6 lines · 14 cases` expanding to the full list
- Totals block: gross, discount, net — net at 20 px
- **A credit card, always visible**: `After this order: ₹4,000 headroom left` in green, or
  `This order is ₹6,000 over the credit limit` in red with
  `Your manager will be asked to approve it.`
- An optional note field
- Bottom third: **Place order**, or **Send for approval** when over limit — the button says which
- After submit: a full-screen confirmation with the order number and `Saved on this phone. It
  will sync when you are back online.` if offline

---

# Phase 5 — stock and van sales

> **The van holds the distributor's stock, not ours (ADR-024).** The rep collects it from the
> distributor's godown and carries it; a van sale is the distributor's sale. No screen here may
> say "invoice created", "our warehouse" or "deposit to company". The full generation prompt for
> these three is `docs/STITCH_PROMPT_PHASE5.md`.

### 18. Shop stock audit
> A stock-taking screen for recording how much of our product a shop currently holds. He is
> counting boxes on a shelf while the shopkeeper watches, so every extra tap costs him a second
> of the conversation.

- Same row pattern as the catalogue but a single quantity field per product, no stepper — he is
  typing 14, not tapping plus fourteen times. Numeric keypad, with a Cases / Pieces toggle
- A muted line per row showing what they held last time: `Last visit: 4 cases`, and
  `Never counted here` where there is no history
- **A zero is a real answer** and must not look like an empty field. An `Out of stock` chip
- `Same as last time` per row — most shops barely move between visits, and this is the single
  biggest time saver on the screen
- A pinned summary strip: `8 of 24 products counted`, with search beneath it
- Bottom third: **Save stock**. A partial count still saves — it is worth more than no count

### 19. Van load sheet *(van sales only)*
> A morning van-loading screen listing what stock is being taken out for the day, **out of the
> distributor's godown**.

- A date, vehicle and distributor header. `Verified by godown` once the storekeeper confirms
- A summary strip: `42 SKUs · 186 cases · ₹2,84,600` — the value matters because a shortfall at
  settlement needs a number attached to it
- Product rows read-only by default with an edit affordance: the godown loads, the rep checks
- A row he changed shows **both** figures — `Godown said 12, you counted 10` — and any difference
  raises an amber block with a required note
- Bottom third: **Confirm load**
- Muted: `This becomes your opening stock for the day.`

### 20. Van settlement *(van sales only)*
> An end-of-day reconciliation: loaded, sold, returned, and cash to hand over. The most
> scrutinised screen in the app, read by a tired man at 8pm.

- **The stock equation laid out as an equation**, not four unrelated tiles:
  `Loaded 186 − Sold 94 − Returned 89 = Short 3`. Loaded is fixed from the morning, Sold is
  computed from his orders, **Returned is the one number he enters**, Short is derived and moves
  as he types
- **Any shortfall in red, in the largest type on the screen, with a required note field.** This
  is where stock loss is caught, so a difference must never be silently rounded away. Zero turns
  the line green and reads `All accounted for`
- An expandable per-SKU breakdown of where the difference is, so he can find it rather than guess
- A cash block: `Cash collected ₹18,400`, `Already deposited ₹12,000`, `To hand over ₹6,400`,
  and **to the distributor** — never to the company
- Good / Damaged split on returned stock. Damaged returns are a real cost and vanish if the
  screen does not ask
- Bottom third: **Settle day**, disabled until a shortfall has a note

---

# Phase 6 — collections

**This is money.** Every screen here must be unambiguous about what was counted, who it came
from, and where it is going. A collection screen that is merely pretty is a liability.

### 21. Outstanding
> A list of what a shop owes, split into ageing buckets.

- Total at the top, 20 px tabular: `₹42,600 outstanding`
- **Ageing bar** — a single horizontal stacked bar, four segments, with a legend beneath:
  `0–30 ₹18,000` (green) · `31–60 ₹12,000` (amber) · `61–90 ₹8,600` (darker amber) ·
  `90+ ₹4,000` (red)
- Invoice rows: number, date, amount, days overdue. Rows past 90 days carry a red left edge
- Bottom third: **Collect payment**

### 22. Collection entry
> A screen for recording a payment collected from a shopkeeper, with a receipt photo.

- Amount field at the top, **large — 28 px, numeric keypad, tabular**. It is the most important
  number on the screen
- Mode chips: `Cash`, `Cheque`, `UPI`, `Bank transfer`
- Cheque fields appear only when *Cheque* is chosen: number, date, bank
- **Allocation list** — which invoices this payment settles, oldest first by default, each with a
  tick and an editable amount. A running line: `₹4,000 of ₹5,000 allocated`
- A receipt photo tile: `Photo of the receipt`
- Bottom third: **Record payment**
- Confirmation screen shows the receipt number large, and a `Share receipt` action —
  the shopkeeper will ask for proof

### 23. Deposit declaration
> A screen for a rep to declare the cash they are holding and depositing to the bank.

- `Cash in hand ₹34,200` at 24 px, tabular
- **An ageing warning where the cash is old**, amber card: `₹8,000 collected 4 days ago has not
  been deposited.`
- A list of the collections making up the total
- A deposit slip photo tile
- Bottom third: **Declare deposit**

---

# Phase 7 — targets and expenses

### 24. My performance
> A personal performance screen for a field rep showing target versus achievement for the month.

- A month selector at the top
- **One large primary metric**: a circular or horizontal progress meter, `₹6.4L of ₹10L · 64%`,
  with `12 days left` beneath
- Secondary metrics as a 2-across tile grid: shops covered, productive calls, new shops, lines
  per call — each with its own target and a small progress bar
- An incentive card where earned, green-bordered: `On track for ₹4,200 incentive` with
  `Hit 80% to earn ₹6,000` beneath
- No leaderboard unless asked for. Ranking demotivates the bottom half, which is most of the team

### 25. Expense claim
> A claim entry screen where travel distance is pre-filled from the day's GPS trail.

- Date, then claim-type chips: `Travel`, `Food`, `Stay`, `Other`
- **For travel, distance is pre-filled and shown as derived, not typed**:
  `48 km from your GPS trail` with a muted `Edit if this is wrong`
- Amount field, receipt photo tile, note field
- Bottom third: **Submit claim**
- A claim history list beneath, each with a status pill: `Approved`, `Pending`, `Rejected`

---

# Phase 8 — rep dashboard

### 26. Today at a glance
> A compact dashboard for a field rep showing how today is going so far.

- A 2-across tile grid, tabular: shops visited, orders taken, order value, collections
- A coverage bar: `8 of 12 planned`
- A short list: `Still to visit` — the remaining shops, tappable
- Keep it to one screen with no scrolling at 360 px. A dashboard a rep has to scroll is one they
  will not open

### 27. This month
> A monthly summary screen for a field rep with a simple trend.

- Month selector
- A 2-across tile grid with a small delta against last month: `▲ 12%` in green, `▼ 4%` in red
- One simple bar chart — value by week. No pie charts, no dual axes, no legends requiring a key
- A `Best day` and a `Best shop` line

---

# Phase 9 — distributor portal

**A different surface.** Desktop or tablet, used sitting down by a distributor's office staff,
not a rep in the field. The 48 px and one-handed rules do not apply; 16 px minimum text and
4.5:1 contrast still do. Design at 1280 px.

### 28. Portal — orders
> A desktop web page where a distributor sees incoming orders from field reps.

- A filterable table: date, shop, rep, lines, value, status
- Status pills: `New`, `Accepted`, `Dispatched`, `Cancelled`
- Bulk select with an `Accept selected` action
- A row expands to show the order lines

### 29. Portal — claims
> A desktop page where a distributor tracks scheme claims and their approval status.

- Summary cards across the top: `Claimed`, `Approved`, `Paid`, `Rejected` with values
- A claims table: period, scheme, value, status, credit note number
- A row expands to show which orders make up the claim

---

## What to send back

Whatever the tool exports — HTML, screenshots, a Figma link. **Screenshots alone are enough.**
Put them in `design/` at the repo root, one folder per screen, numbered to match this document:

```
design/
  02-today/            screenshot.png, export.html
  10-visit-hub/        screenshot.png, empty-state.png
  16-scheme-preview/   screenshot.png
```

The app is **Vue 3 with plain CSS custom properties**, not React and not Tailwind. Exported
Tailwind markup is a useful reference for layout and spacing, but it is translated rather than
dropped in.

---

## Where the palette comes from

It is **derived from the logo**, not chosen. `frontend/scripts/make-palette.py` reads the brand
mark, pulls the navy and green out of it, walks each colour's lightness down until it measures
4.5:1 *where it is actually used*, and refuses to emit a palette that fails. `docs/DESIGN.md`,
`frontend/src/style.css` and the block above all carry the same audited output.

Two things the audit caught, worth knowing before a design tool undoes them:

- **The brand green cannot be text on white.** It measures 2.38:1 — illegible in sunlight. It is
  a fill and icon colour only. `--ok` (`#277D40`) is the same hue darkened until readable, so the
  family still reads as one.
- **Status colours are checked against their own tinted card.** Amber text on an amber card is a
  harder pairing than amber text on a page, and three colours that passed the easy check failed
  the real one.

If the logo changes, re-run the script and the whole theme follows.
