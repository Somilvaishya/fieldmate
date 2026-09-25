# Stitch prompt — Phase 5 screens

Three screens: shop stock audit, van load sheet, van settlement.

**How to use this.** Paste **Part 1** first, as the style or system prompt. Then paste **one**
screen block from Part 2 per generation — not all three at once, they drift. If the tool starts
ignoring the palette after a few screens, re-paste Part 1.

---

## Part 1 — paste this first

```
Design a mobile-first field sales app for Android, 360px wide. Utilitarian and legible,
like a well-made tool, not a consumer product. Dense where it saves taps, spacious where
it prevents mis-taps.

CONTEXT: the user is a distribution salesman in India. He uses this 60-80 times a day,
standing, one-handed, in sunlight, often with no signal, while talking to a shopkeeper.
Every decision below follows from that.

COLOURS — use these exact values, no others. They are derived from the logo and every
pairing is measured at 4.5:1 or better:
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
  Indian numbering — Rs 1,24,500 not Rs 124,500.
  Amounts always tabular, right-aligned in any column.
  Never show a bare number where a unit is meant: "12 cases", "Rs 4,200", "86%".
  Quantities are entered in CASES and shown with the piece count underneath:
    "2 Cases" with "= 24 pieces" in secondary text. Both must always agree.

PERMANENT STRIP: every screen has a thin status bar at the very top showing
online/offline and, when offline, how many records are waiting to sync. It is always
honest about the queue depth. Never a spinner that could hang forever.

VOICE:
  Plain words a rep would use. "Shop", not "outlet entity". "Stock left", not
  "closing inventory position". Errors say what went wrong and what to do next —
  never a code, never an apology, never a stack trace.
  Buttons say what will happen: "Save stock", "Confirm load", "Settle day".
```

---

## Part 2 — the three screens

### Screen 18 — Shop stock audit

```
Screen: "Stock check" — recording how much of our product this shop is still holding.

The rep is standing at the counter counting boxes on a shelf while the shopkeeper
watches. Speed matters more than polish: every extra tap is a second he is not talking
to the shopkeeper.

HEADER
  Shop name, beat number, and when stock was last counted here: "Last counted 12 days
  ago". If it has never been counted, say "First stock check here" rather than showing
  a blank.

PROGRESS STRIP
  "8 of 24 products counted" with a thin progress bar. This is the only thing that
  tells him how much is left, so it stays visible while he scrolls — pin it under the
  header.

PRODUCT ROWS — the body of the screen
  One row per SKU, grouped under category headings (Soaps & Detergents, Tea &
  Beverages). Each row carries:
    - Small product thumbnail, SKU code, product name, case size ("12 per case")
    - ONE quantity field. A numeric keypad, not a stepper — he is typing 14, not
      tapping + fourteen times
    - A unit toggle beside it: Cases / Pieces
    - A muted line underneath: "Last visit: 4 cases" — and where there is no history,
      "Never counted here"
    - A counted row gets a green left edge and its number in #05172E; an uncounted row
      stays plain. He has to see at a glance what he has missed
  A "0" is a real answer and must look different from an empty field. Show a small
  "Out of stock" chip on a row counted as zero.

FAST ENTRY
  A "Same as last time" button on each row that fills the previous count in one tap.
  Most shops do not change much between visits and this is the single biggest time
  saver on the screen.

SEARCH
  A search field pinned under the progress strip, so he can jump to a SKU the
  shopkeeper mentions instead of scrolling.

BOTTOM THIRD
  Primary: "Save stock" — full width, navy.
  Above it, muted: "Saved on this phone. Syncs when you have signal."
  If any product is uncounted, a secondary line in amber: "16 products not counted —
  save anyway?" It must NOT block him. A partial count is worth more than no count.

EMPTY STATE
  No catalogue for this shop: "No products listed for this shop yet. Ask your manager
  to set up the catalogue." Not a blank list.
```

### Screen 19 — Van load sheet

```
Screen: "Van load" — what stock is going out on the vehicle this morning.

Read this before designing it: the stock in the van belongs to the DISTRIBUTOR, not to
the company. The rep collects it from the distributor's godown and carries it. The copy
must never imply the company owns it or that this is a purchase.

HEADER
  Date, vehicle number ("MH-12-AQ 4471"), and the distributor's name whose godown this
  came from. A green "Verified by godown" chip once the storekeeper has confirmed it.

SUMMARY STRIP — three figures, tabular
  "42 SKUs · 186 cases · Rs 2,84,600"
  The value is what the stock is worth, so a shortfall at settlement has a number
  attached to it.

PRODUCT ROWS
  One row per SKU: thumbnail, code, name, case size, and the loaded quantity in cases
  with the piece count under it. Rows are read-only by default with a small edit
  affordance — the storekeeper loads the van, the rep confirms it, so this is mostly a
  checking screen rather than a data entry one.
  A row the rep has changed from what the godown said gets an amber left edge and shows
  both numbers: "Godown said 12, you counted 10".

DISCREPANCY BLOCK — only appears when something was changed
  Amber card: "You counted 3 products differently from the load sheet." Lists them with
  both figures and a required note field. This is where stock loss gets caught, so a
  difference must never be quietly accepted.

BOTTOM THIRD
  Primary: "Confirm load".
  Muted above it: "This becomes your opening stock for the day."

EMPTY STATE
  Nothing loaded yet: "No load sheet for today. Ask the godown to prepare one." with
  a secondary action "Load it myself" for a rep who loads his own van.
```

### Screen 20 — Van settlement

```
Screen: "Settle day" — the end-of-day reconciliation for a van rep.

This screen is where the day's money and stock are proved. It is the single most
scrutinised screen in the app, so it must be readable by a tired man at 8pm and must
never hide a difference.

THE STOCK EQUATION — the top block, and the whole point of the screen
  Show it as an equation he can follow, not as four unrelated tiles:

      Loaded          186 cases
    - Sold             94 cases
    - Returned         89 cases
    ------------------------------
      Short            3 cases      <- in #C62A25 on a #FAE4E3 card

  Loaded is fixed from this morning. Sold is computed from his orders — read-only, with
  a link "from 14 sales". Returned is the ONE number he enters. Short is derived and
  updates as he types.
  When Short is zero, that line turns green and reads "All accounted for". When it is
  not zero it is red, in the largest type on the screen, and a note field appears
  underneath marked required: "What happened to the 3 cases?"
  Never round a difference away. Never let him past it without a word of explanation.

SHORTFALL DETAIL — expandable, only when short
  Per-SKU breakdown of where the difference is, so he can find it rather than guess:
  "Surf Excel 1kg: loaded 24, sold 14, returned 8, short 2".

CASH BLOCK — second card
  "Cash collected today    Rs 18,400"   (computed from his sales, read-only)
  "Cash already deposited  Rs 12,000"
  "To hand over            Rs 6,400"    <- large, navy
  A muted line: "Hand over to <distributor name>." It goes to the distributor, not to
  the company — the copy must say so.
  If he is holding cash from previous days, an amber card above: "Rs 4,200 from
  Tuesday is still undeposited."

RETURNS CONDITION — third card, compact
  Two chips per returned SKU where relevant: "Good" / "Damaged", with a quantity split.
  Damaged stock returned is a real cost and disappears if the screen does not ask.

BOTTOM THIRD
  Primary: "Settle day" — disabled until a shortfall has a note.
  Secondary: "Save and finish later".
  Muted: "Once settled, today's stock and cash are locked."

CONFIRMATION STATE
  After settling: a green card with the day's figures — sold, returned, short, cash
  handed over — and a single "Done" button. He may be asked about these numbers
  tomorrow, so they stay on screen rather than flashing a toast.
```

---

## What these screens must never say

Three phrases that would be wrong, because of how the business actually works:

| Do not write | Why |
|---|---|
| "Invoice created" / "Posted to accounts" | A van sale is the **distributor's** sale. Nothing reaches the company's books (ADR-024) |
| "Company stock" / "Our warehouse" | The van holds the distributor's stock. We sold it to them at primary billing; it is already theirs |
| "Deposit to company" | Cash from a van sale is handed to the **distributor** |

Anything that implies the company is the seller is wrong on all three screens.
