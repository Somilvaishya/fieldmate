# Manual tests — Phase 8, analytics and alerts

Written for: whoever is sitting at a Desk login and a phone on testerp2.

**Site:** `testerp2.web.gargsystems.com`
**You will need:** a Desk login with FieldMate Admin, and the PWA signed in as a rep.

---

## Setup

```
cd ~/frappe/frappe-bench-v15/sites
../env/bin/python ../apps/fieldmate/scripts/setup_phase8.py
```

It rolls up the last 90 days from whatever is already on the site, installs the five alert rules
if they are missing, and evaluates them. It **invents nothing** — every number you see comes
from documents you can go and open.

> Without this, every chart is zero. That is correct behaviour on an empty snapshot and looks
> exactly like a bug, which is why the script exists.

---

## 1. The Desk workspace

1. Open **/app/fieldmate**.

**Expected:** four number cards across the top (value, productive calls, new shops, exceptions
this week), three charts under them, and four groups of links.

2. Click through **Today → KPI Snapshot**.

**Expected:** one row per rep per day. Open one.

**Check the shape:** every percentage has its base beside it — coverage has *Shops In Territory*,
collection efficiency has *Collectable Base*, strike rate has *Made* and *Productive*.

> A percentage without its base cannot be argued with or acted on. 0% over no calls and 0% over
> twelve calls are not the same fact.

---

## 2. Every number is checkable

**This is the criterion that matters.** Pick one rep and one day where something happened.

1. Open that day's **KPI Snapshot** row. Write down: orders, value, shops billed, calls,
   productive calls.
2. Now open **FieldMate Order**, filter on that rep and that date, and count them yourself.
3. Do the same with **FieldMate Visit**.

**Expected:** they match exactly. Value to the paisa.

4. Check a ratio by hand: strike rate should be *productive ÷ calls × 100*.
5. Check `distinct_skus` is **not** the same as `order_lines`. A rep selling the same SKU at ten
   shops has ten lines and one SKU.

### 2a. A cancelled order stops counting

6. Cancel one of that rep's orders for that day.
7. Re-run the rollup:

```
/api/method/fieldmate.api.dashboard.rebuild?from_date=<that day>&to_date=<that day>&field_user=<rep>
```

**Expected:** value and order count drop. A cancelled order that still counted would let a rep
book, take the credit, and cancel on the first of next month.

---

## 3. A month is the days added up — except the ratios

1. Open **Rep Scorecard** (Desk → reports) for this month.
2. Pick a rep. Add up their daily `order_value` from **KPI Daily Trend** for the same window.

**Expected:** the two agree.

3. Now the one that is *not* a sum. Take that rep's daily strike rates and average them by hand.
   Compare with the scorecard's figure.

**Expected: they do NOT match**, and the scorecard is the right one. The scorecard divides total
productive calls by total calls; the average of the daily percentages answers a different
question. A rep with one call converted, then twelve with three converted, is 4 in 13 — not the
average of 100% and 25%.

4. Check coverage. The scorecard's **Shops Covered** counts a shop **once** for the month, even
   if it was billed on Monday and again on Friday.

---

## 4. A backdated correction restates the day

1. Note a rep's snapshot for some day last week.
2. In Desk, create and submit an order for that rep dated **that day**.
3. Re-run the rollup for the window.

**Expected:** that day's row changes; the days around it do not. Still **one** row for that
rep-day.

4. Run the rollup again with nothing changed.

**Expected:** it reports rows as *unchanged*. Each row carries a fingerprint of what it was
counted from, which is what lets an hourly job look at a month cheaply.

---

## 5. Alerts fire once, and only when worth reading

1. Open **FieldMate Alert Rule**. Five should exist.

| Rule | Fires when |
|---|---|
| Day not started by mid-morning | no day start, two hours past the usual time |
| A day out with nothing sold | four or more calls, no order |
| Coverage below 60% | three days running, at least 20 shops in territory |
| Cash carried and not handed over | over ₹10,000 still in the satchel |
| Checked in away from the shop | more than two geo-fence breaches in a day |

2. Open **FieldMate Alert Log**. Each row names the observed value, the threshold **and the
   base**.

3. Run the evaluator again:

```
/api/method/fieldmate.api.dashboard.run_alerts?days_back=30
```

**Expected:** `fired: 0`, `already_logged: <n>`. Run it a third time — same. An occurrence is
rule + rep + day, and it is logged once.

4. Try to break it. In Desk, create an **Alert Log** by hand with an `occurrence_key` copied
   from an existing row.

**Expected:** refused by the database, not by a check somebody remembered to write.

### 5a. Noise control

5. Edit a rule and set **Ignore Below A Base Of** to 20. Re-run.

**Expected:** reps with thin days stop appearing. A ratio over almost nothing is noise, and
noise teaches people to filter the whole channel.

6. Set **For This Many Days Running** to 3 on the coverage rule.

**Expected:** it only fires where the condition held three days in a row. One bad day is weather.

---

## 6. The rep's phone

1. On the phone: **Today → How today is going**.

**Expected:** three tiles (booked / calls / collected), a three-segment bar (sold, no order, to
go), and a 14-day sparkline.

2. Book an order right now and pull to refresh.

**Expected:** the tiles move **immediately**. Today is the one screen counted live — the rep is
looking at the last hour, and last night's row is the one figure they would know to be wrong.

3. Go to **My performance**.

**Expected:** targets at the top (Phase 7), and under them **How the month is going** — coverage,
strike rate, plan compliance, collection efficiency, lines per call, average order — each with
its base. Those are measured, not targets.

4. Check the run-rate line: what is needed per day, and what the rep has actually been doing.

---

## 7. Nothing else counts for itself

- [ ] Every chart and number card on the workspace is over **FieldMate KPI Snapshot** or
      **FieldMate Alert Log**. None is over Visit, Order or Collection.
- [ ] **Rep Scorecard** and **KPI Daily Trend** are over the snapshot.
- [ ] **Visit Exceptions** is over Visit — and that is deliberate and declared. It lists *which*
      visit and *how far outside the fence*, which the snapshot does not carry. It aggregates
      nothing. See ADR-030.
- [ ] A rep signed in to `/api/resource/FieldMate KPI Snapshot` sees **only their own rows**.

---

## 8. Insights

```
bench --site testerp2.web.gargsystems.com execute fieldmate.setup.insights.report
```

**Expected on testerp2 today:** `installed_on_site: False`.

> Insights is on the bench at 3.11.2 but is not installed on this site, so
> `setup/insights.py` has only ever been observed to **no-op**. It is written the way `compat`
> guards HRMS, but nobody has watched it register a table. Install Insights on a site and run
> this again before relying on it. The two reports above need no Insights and work today.

---

## If something is wrong

| What you see | Where to look |
|---|---|
| Everything is zero | The rollup has not run — `setup_phase8.py`, or `dashboard.rebuild` |
| A chart is empty but the table has rows | The chart's timespan; the shipped ones are "last month" |
| A number disagrees with the documents | Check the day's row first; the month is the days added up |
| A monthly percentage looks wrong | It is the ratio of totals, not the average of the dailies — that is correct |
| Alerts never fire | No snapshot for those days, or `minimum_base` is filtering them |
| Alerts fire every run | Should be impossible — check `occurrence_key` is unique on the table |
| Charts missing after migrate | Each needs its own `<slug>/<slug>.json` subfolder |
