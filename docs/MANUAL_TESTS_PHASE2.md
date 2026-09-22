# Manual tests — Phase 2 (journey plan, the working day, GPS)

Phase 0 and Phase 1 checks live in `MANUAL_TESTS.md`. This file is only Phase 2, and unlike the
earlier phases **most of it needs a real phone that actually moves.** A desk browser can fake a
lot, but not a GPS trail.

**App:** https://testerp2.web.gargsystems.com/assets/fieldmate/pwa/index.html
**Desk:** https://testerp2.web.gargsystems.com/app
**Logins:** `rep1@fieldmate.test` / `mgr1@fieldmate.test`, both `FieldMate@2026`

> Run `scripts/reset-test-users.sh` first.

---

# Part A — Setup in Desk (Administrator, ~10 min)

### A1 — Deviation reasons
`/app/fieldmate-deviation-reason/new` — create three: **Shop closed**, **Owner unavailable**,
**Urgent customer call** (set the last one to *Unplanned Visit*, tick **Requires A Note**).

### A2 — A beat for today
`/app/fieldmate-beat/new` — Territory *FM Delhi*, Assigned To `rep1`, Weekly, and set **Visit Day
to today's weekday**. Add three approved Delhi outlets. Save.

> If your outlets are still *Pending Approval*, approve them as `mgr1` first — Phase 1, test C7.

### A3 — A journey plan
There is no Desk button for this yet, so generate it from the API. In a browser tab signed in as
Administrator:

```
/api/method/fieldmate.api.day.today
```

That only reads. To generate, use the bench console or ask for a plan-generation button — for now,
create the plan in Desk:

`/app/fieldmate-journey-plan/new` — Field User `rep1`, From = today, To = today. In **Days**, add
one row: Date = today, Beat = the beat from A2, Status *Planned*, Working ✓. **Submit it.**

**Expect:** Planned Visits shows 3, Working Days shows 1.

### A4 — Try to break it
Create a second journey plan for `rep1` covering today and submit it.
**Expect:** *"FM-JP-… already covers part of this period for rep1. Cancel it first."*
Two plans covering one date would make "today's beat" ambiguous. Delete the second.

Also try From = today, To = today + 200 days.
**Expect:** *"A plan cannot span more than 120 days. Generate one month at a time."*

- [ ] Pass / [ ] Fail

---

# Part B — On the phone, standing still (~10 min)

Open the app as `rep1` and **install it to the home screen** if you have not already.

### B1 — Today knows the day has not started
**Expect:** a card reading **"Day not started"**, and below it *"Planned: FM-BEAT-… (3 shops)"*.
The primary button at the bottom reads **Start day**.

- [ ] Pass / [ ] Fail

### B2 — Start day asks for what it needs
Tap **Start day**.

**Expect:** two tiles — *Capture location* and *Take start-of-day photo* — plus an optional
odometer field. Tap **Start day** at the bottom without doing either.

**Expect:** *"Take the start-of-day photo first."* It should not silently do nothing.

- [ ] Pass / [ ] Fail

### B3 — Location capture
Tap **Capture location**, allow the permission.

**Expect:** the tile turns green and reads **"Location captured"** with an accuracy like
*±8 m · gps*.

Now deny the permission instead (Chrome → site settings → Location → Block, then retry).
**Expect:** *"Location permission is off. Turn it on for this app and try again."* — a sentence
telling you what to do, not an error code.

- [ ] Pass / [ ] Fail

### B4 — Photo capture and compression
Tap **Take start-of-day photo**. Your camera should open **front-facing**.

**Expect:** after taking it, the tile reads **"Photo taken"** with a size like *84 KB*. A modern
phone camera produces 3–5 MB files; anything near that here means compression did not run.

- [ ] Pass / [ ] Fail

### B5 — Start the day
Enter an odometer reading (note it down), tap **Start day**.

**Expect:** you land back on Today, now showing **"Day running"** with *since HH:MM* and the beat
name, followed by **"3 shops on this beat"** listing them in sequence order with a number beside
each. The bottom button now reads **Finish day**.

- [ ] Pass / [ ] Fail

### B6 — Starting twice does nothing bad
Force-close the app and reopen it from the home screen.

**Expect:** it comes straight back to **"Day running"** with the same start time. Not a fresh
start, not a second day.

- [ ] Pass / [ ] Fail

---

# Part C — On the road (the part that needs movement)

This is the half a desk cannot fake. **Take the phone on a real trip** — a few kilometres by any
means, ideally your normal beat.

### C1 — Points accumulate
After 10–15 minutes of moving, open Today.

**Expect:** a line reading **"N location points waiting to upload"**, with N growing roughly once
every 90 seconds.

- [ ] Pass / [ ] Fail

### C2 — They survive a kill
Force-close the app mid-journey, wait a few minutes, reopen.

**Expect:** the count carried over — pings live in the phone's database, not in memory. A killed
app must not lose the morning's trail.

- [ ] Pass / [ ] Fail

### C3 — They survive no signal
Put the phone in airplane mode for a stretch of the journey, then restore signal and open Today.

**Expect:** the waiting count rises while offline and then drops to zero shortly after signal
returns. An offline morning uploads in one go.

- [ ] Pass / [ ] Fail

### C4 — Battery
Note the battery percentage at Start day and again after a few hours.

**Expect:** well under 20% attributable to the app over a nine-hour day. If you see rapid drain,
say so — the ping interval is a setting and can be relaxed.

- [ ] Pass / [ ] Fail

---

# Part D — Finishing (~5 min)

### D1 — Finish day
Tap **Finish day**.

**Expect:** a warning that this closes the day and cannot be undone, the count of location points
still to upload, and fields for odometer and remarks. Enter the closing odometer.

- [ ] Pass / [ ] Fail

### D2 — The summary, and where distance comes from

**Expect:** hours worked, **distance in km**, visits, orders, new shops — and a line reading
*"Distance comes from your location trail, not the odometer."*

**Now the check that matters.** Compare the reported distance with `odometer_end − odometer_start`.

**Expect:** within about 10%. Road distance is always a little longer than the straight-line
segments we sum, so the app reading slightly **lower** is correct behaviour. A wildly different
number is a real failure — write down both readings.

> This figure is what expense claims will be paid against, which is exactly why it is computed
> from the trail rather than typed.

- [ ] Pass / [ ] Fail — odometer delta: ______ km · app: ______ km

### D3 — A finished day cannot be restarted
Back on Today, try to start again.

**Expect:** *"You have already finished today. Ask your manager if you need it reopened."*
Restarting would split one day's work across two records and double-count coverage.

- [ ] Pass / [ ] Fail

---

# Part E — Back in Desk (~10 min)

### E1 — The day records
`/app/fieldmate-day-start` and `/app/fieldmate-day-end`.

**Expect:** one of each. Day Start carries your coordinates, accuracy, the selfie and the
odometer. Day End carries hours, distance and the counts.

- [ ] Pass / [ ] Fail

### E2 — One trail row, not thousands
`/app/fieldmate-location-trail`.

**Expect:** **exactly one row** for you today — not one per ping — with Pings, Distance, Max Speed
and Implausible Jumps filled in. Open it: the whole path is JSON in one field.

> A row per ping would add roughly 30 million rows a year at 250 reps.

- [ ] Pass / [ ] Fail

### E3 — Plausibility
On that trail, check **Implausible Jumps**.

**Expect:** usually 0. A small number is not an accusation — GPS drifts badly indoors and a bad
fix can jump a kilometre — but those segments are excluded from the distance, which is why the
total stays sane.

- [ ] Pass / [ ] Fail

### E4 — Attendance summary
`/app/fieldmate-attendance-summary`.

**Expect:** one row, status **Present**, with your hours, distance and coverage. **Late Start** is
ticked only if you began after the alert time in FieldMate Settings.

- [ ] Pass / [ ] Fail

### E5 — The HRMS mirror *(Gate 2 criterion 2)*
This needs `rep1`'s Field User to have an **Employee** linked. Set one in
`/app/fieldmate-field-user/rep1@fieldmate.test` if it is blank, then repeat a short day.

`/app/employee-checkin`

**Expect:** two rows — **IN** at your start location, **OUT** at your finish location. If both
show the same coordinates, that is the bug fixed on 22 Sep returning; say so.

- [ ] Pass / [ ] Fail

---

# Gate 2

| Criterion | How it is covered |
|---|---|
| 1. A month's plan skips Sundays, holidays and approved leave | Automated — `test_journey.py` |
| 2. Day Start creates an Employee Checkin with correct lat/long | Automated — `test_hrms_mirror.py`, plus **E5** |
| 3. A full day of pings stores as one row, distance within 10% of odometer | **C1–C4 and D2 — needs a real trip** |
| 4. A mock location is flagged, not silently accepted | Automated; visible on Day Start in Desk |
| 5. Killing the app mid-day resumes the same day | **B6** |

Criterion 3 is the one that cannot be faked, and the one most worth doing properly.

---

# After testing

Record failures in `docs/MEMORY.md` under Known Issues. Tick a criterion only when it passed on a
real device — **a gate is not partially passed.**
