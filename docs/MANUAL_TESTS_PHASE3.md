# Manual tests — Phase 3 (visit execution)

Written for: whoever is holding the phone. No Frappe knowledge assumed.

These are the things automated tests cannot reach: a real GPS chip, a real camera, a real walk
between two shops, and a real tunnel with no signal. Every bug found in Phases 0–2 that mattered
was found this way.

**Before you start**

- Site: `https://testerp2.web.gargsystems.com`
- App: `https://testerp2.web.gargsystems.com/assets/fieldmate/pwa/`
- Install it to the home screen so it opens without an address bar.
- Sign in as a rep who has a beat with at least three shops on it, at least one of which has a
  saved location (latitude/longitude) and a geo-fence radius.
- Tap **Sync now** once while you have signal. This downloads the checklist questions and the
  no-order reasons. Without it, Part D will look broken when it is not.

Record each result as **pass**, **fail**, or **not reached**. A "fail" needs what you saw, not
what you expected.

---

## Part A — Setting up the survey (desk, 10 minutes)

Do this on a laptop before going out.

| # | Step | Expect |
|---|---|---|
| A1 | Go to **FieldMate Checklist Template** → New. Name it, set *Applies To* = Every Visit, *Effective From* = today, tick *Is Active*. | Saves. |
| A2 | Add questions covering each type: one Yes/No (required), one Number with min 0 / max 50, one Single Choice with three options, one Text, one Rating. Give each a short code (SHELF, FACINGS, STOCK, NOTE, RATE). | Saves. *Version* reads 1, *Question Count* matches. |
| A3 | Add a question whose *Depends On Code* is `SHELF` and *Depends On Value* is `No`, with a **lower** sequence number than SHELF. | **Refused**, saying it comes later in the list. Fix the sequence and save. |
| A4 | Add a second question reusing the code `SHELF`. | **Refused**, naming both rows. Remove it. |
| A5 | Add a Single Choice question with no options. | **Refused**. Remove it. |
| A6 | Save. Note the version number. | Still 1 — you only added questions during the first save. |
| A7 | Now reword any question and save again. | Version becomes **2**. |
| A8 | Rename the template itself and save. | Version stays **2**. Renaming is not a change to what was asked. |
| A9 | Create **FieldMate No Order Reason** rows: "Stock still with him" (no note needed) and "Shop refused" with *Requires Note* ticked. | Both save. |

---

## Part B — Checking in (in the field)

Stand **inside** the first shop on your beat.

| # | Step | Expect |
|---|---|---|
| B1 | Open the app. Start your day if it is not already running. | Today screen shows the day running and lists your beat. |
| B2 | Tap a shop → **Check in here**. | The check-in screen finds your location and shows the distance to the shop. |
| B3 | Read the distance. | A number in metres, not blank. Under the shop's radius, shown plainly. |
| B4 | Tap **Check in**. | You land on the visit screen. It names the shop and starts counting minutes. |
| B5 | Close the app completely (swipe it away) and reopen it. | Today screen shows **"Still in \<shop name\>"** at the top. Tap it — you are back in the same visit, minutes still counting. |

**Now walk 400–500 m away from a shop** (a different one, ideally down the road) and check in
there if it has a saved location.

| # | Step | Expect |
|---|---|---|
| B6 | On the check-in screen, read the warning. | It says you are N metres away, outside the shop's range, and that you **can still check in**. |
| B7 | Check in anyway. | It works. The visit screen shows an orange line: checked in outside the shop's range. |
| B8 | Later, on the desk: open **Visit Exceptions** report for today. | That visit is listed, reason "Outside the shop's range". |
| B9 | Open **FieldMate Geo Fence Exception** list. | A row for that visit, status **Pending**. |

---

## Part C — The survey

Back inside a shop, in an open visit.

| # | Step | Expect |
|---|---|---|
| C1 | Tap **Checklist**. | Your questions from Part A, in sequence order. Required ones marked with a red `*`. |
| C2 | Look for the question that depends on SHELF = No. | It is **not shown** yet. |
| C3 | Answer SHELF = **No**. | The dependent question **appears**. |
| C4 | Change SHELF to **Yes**. | The dependent question **disappears** again. |
| C5 | On the Number question, type `0`. | It is accepted as an answer — the counter on the visit screen goes up. This matters: zero facings is a real finding, not a blank. |
| C6 | On the Number question, type `999` (outside the min/max). | Saved anyway, with an orange line saying it is outside the expected range. Not refused. |
| C7 | Tap a Single Choice option, then tap a different one. | The selection moves. Only one stays highlighted. |
| C8 | Go back to the visit, then into the checklist again. | Every answer is still there. |
| C9 | Turn **airplane mode on**. Answer two more questions. Go back and in again. | Answers still there. No red error. |
| C10 | Turn airplane mode off. Wait ten seconds, then tap **Sync now** on Today. | No error. On the desk, the visit's Checklist table shows your answers. |

---

## Part D — Photos and the shelf

| # | Step | Expect |
|---|---|---|
| D1 | In an open visit, tap **Add a photo** and take one. | Returns to the visit screen. "1 waiting to send" appears, then clears once it uploads. |
| D2 | Turn **airplane mode on**. Take three more photos. | Each is accepted. The count rises to 3 and stays — nothing errors. |
| D3 | Tap **Shelf check**. | The item list loads from what the phone already holds. |
| D4 | Tick three items, set facings 4 / 2 / 6. Set the whole-shelf total to 30. Add one competitor with 10 facings. | The line at the top updates: Ours 12, Theirs 10, Share 40%. |
| D5 | Tap **Save shelf check** while still in airplane mode. | Saves without error, returns to the visit. |
| D6 | Turn airplane mode off, tap **Sync now**. | Queue count falls to 0. On the desk, a **FieldMate Merchandising Audit** exists, submitted, with your three lines and the competitor. |
| D7 | Open that audit. | *Shelf Share* reads **40%**. *Our Facings* reads 12. You did not type either number. |
| D8 | Open the visit on the desk. | All four photos are attached, each a real image. The three taken offline arrived **after** the visit did. |
| D9 | Check each photo's size (**File** list, sort by size). | All at or under 120 KB. |

---

## Part E — Checking out

| # | Step | Expect |
|---|---|---|
| E1 | In a visit with a required question still unanswered, tap **Finish visit**, pick **Order taken**. | The **Check out** button stays disabled, with a line saying how many required questions are left and a link to the checklist. |
| E2 | Answer them, come back. | Check out is now enabled. |
| E3 | Pick **No order**. | A list of reasons appears. |
| E4 | Pick "Shop refused" (the one requiring a note) and leave the note empty. | Check out stays **disabled**. The label says the note is required for this reason. |
| E5 | Type a note. | Check out enables. |
| E6 | Pick **Shop closed** instead, with required questions unanswered. | Check out is **allowed**. You cannot describe a shelf behind a shutter. |
| E7 | Check out. | Back on Today. The shop is marked **Visited** and the count at the top goes up. |
| E8 | On the desk, open the visit. | Submitted. *Minutes* matches roughly how long you were in the shop. If that was under the minimum, *Short Visit* is ticked. |

---

## Part F — The forgotten check-out

This is the one reps actually do.

| # | Step | Expect |
|---|---|---|
| F1 | Check into shop A. Do not check out. Walk to shop B and check in there. | Check-in at B works. No error, no block. |
| F2 | On the desk, open the visit at shop A. | Submitted, with a remark saying it was **closed automatically when the next visit began**. Marked as a short visit. |

---

## Part G — A whole offline round (the real test)

Do this on a route where you lose signal, or turn airplane mode on before you leave and keep it
on for the whole run.

| # | Step | Expect |
|---|---|---|
| G1 | With airplane mode **on** the entire time, visit **three** shops end to end: check in, answer the checklist, take a photo, check out with an outcome. | Every step works. No red errors. No spinner that never stops. |
| G2 | Watch the Today screen between shops. | Each finished shop is marked **Visited**. The sync count rises. |
| G3 | Close the app fully between shop two and three, then reopen. | Nothing is lost. |
| G4 | Turn airplane mode off. Tap **Sync now** once. | The queue drains to 0. Records go first, photos follow. |
| G5 | On the desk, open **FieldMate Visit** list for today. | Exactly three new visits, all **submitted** — not drafts. |
| G6 | Count them again after tapping **Sync now** a second time. | Still three. No duplicates. |
| G7 | Open one and check the Checklist table. | The question wording matches the **template**, even if you edited the template between G1 and G4. |
| G8 | Finish your day. Open the **FieldMate Day End** record. | *Actual Visits* counts all of today's visits including the offline three. |

---

## What counts as a failure worth reporting

- Any red error message a rep would not understand.
- Any screen that blocks you with no way forward.
- A number that changed on its own between two screens.
- Work you did that is not on the desk after syncing.
- A duplicate visit, order or photo after a second sync.
- A photo attached to the **wrong** visit.

Take a screenshot of anything on this list. The screenshot is usually the whole bug report.
