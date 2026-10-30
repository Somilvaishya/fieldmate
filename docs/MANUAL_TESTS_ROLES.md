# Manual tests — har designation, scenario ke hisaab se

Written for: jo testerp2 pe baithkar haath se test kar raha hai, banane wale ke liye nahi. Har
step batata hai kya karna hai aur kya dikhna chahiye. Jahan kuch **nahi** hona chahiye, woh bhi
likha hai — is dastavez ka aadha hissa wahi hai.

**Site:** `testerp2.web.gargsystems.com`
**Lagega:** ek Desk login jisme `FieldMate Admin` ho, aur **har designation ke liye ek alag
browser profile ya private window**. Ek hi window me log in / log out karte rahe to ek ghanta
barbaad hoga aur aadha test galat nikalega (purani session cache).

---

## Pehle yeh samajh lijiye — Designation aur Role alag hain

`FieldMate Field User` pe jo **Designation** dropdown hai (Field Rep / Area Manager / Regional
Manager / Sales Head), woh **access nahi deta**. Woh ek label hai. Asli permission `User`
document pe lagi **Role** se aati hai.

Code me ise dekha ja sakta hai: `fieldmate/setup/install.py` saat role banata hai, lekin poore
app me kahin bhi designation se role assign nahi hota (sirf `FieldMate Portal User` apne aap
`FieldMate Distributor` lagata hai).

Designation sirf teen jagah kuch karta hai:

| Jagah | Kya karta hai |
|---|---|
| `outlet.approve` | Designation `Field Rep` hua to naya shop approve karne se **mana** kar deta hai |
| Incentive Scheme | Scheme pe designation bhara ho to sirf usi designation ke reps ko lagta hai |
| Alert Rule | Alert kis designation ko jaaye |

Baaki sab — kaun si list dikhegi, kiska data dikhega — **Role + Territory User Permission** se
chalta hai.

Isliye har user banate waqt **dono** set karne padte hain. Agar sirf Designation set ki aur Role
nahi, to woh banda Field Rep hi rahega aur aapko lagega "manager ko kuch dikh hi nahi raha".

---

## Setup — paanch user, ek baar

Desk → **User** list se paanch user banaiye (ya jo pehle se hain unhe theek kijiye). Har ek ke
liye **teen** cheezein:

1. **User** doc → *Roles* me FieldMate role tick kijiye (neeche table)
2. **FieldMate Field User** doc → `user`, `territory`, `designation`, `reports_to`
3. Save karte hi Territory User Permission apne aap ban jaati hai — **check kijiye**:
   Desk → *User Permission* list → us user ki row dikhni chahiye, `Allow = Territory`,
   `Hide Descendants = 0`

| # | Kaun | User pe Role | Field User pe Designation | Territory | reports_to |
|---|---|---|---|---|---|
| 1 | `rep1@test` | FieldMate Field Rep | Field Rep | ek **leaf** territory | `am1` |
| 2 | `rep2@test` | FieldMate Field Rep | Field Rep | **doosri** leaf territory | `am1` |
| 3 | `am1@test` | FieldMate Area Manager | Area Manager | dono ka **parent** | `rm1` |
| 4 | `rm1@test` | FieldMate Regional Manager | Regional Manager | usse upar ka parent | `sh1` |
| 5 | `sh1@test` | FieldMate Sales Head | Sales Head | root ya uske paas | — |

`rep2` isliye zaroori hai: aadhe test "doosre ka data nahi dikhna chahiye" ko prove karte hain,
aur uske liye ek doosra rep hona chahiye.

**Desk access:** Field Rep aur Distributor ko Desk **nahi** milta (role pe `desk_access = 0`).
Woh log in karenge to seedha PWA / portal khulega. Baaki teen ko Desk milta hai. Agar Field Rep
ko Desk khul gaya — **yeh bug hai**, likh lijiye.

---

## Scenario 0 — Designation badalne se kuch nahi badalta (yeh pass hona chahiye)

Yeh test isliye hai ki aapko pata chale behaviour kahan se aa raha hai.

1. Desk Admin se `rep1` ka **Field User** kholiye, Designation badal kar **Sales Head** kar
   dijiye. Save.
2. `rep1` ki window me PWA refresh kijiye.

**Dikhna chahiye:** *Me* screen pe ab "Sales Head" likha hai — bas. Koi nayi screen nahi,
koi naya data nahi. Jo pehle nahi dikhta tha woh ab bhi nahi dikhta.

3. **Ek cheez badlegi:** ab `rep1` naya shop approve kar sakta hai (`outlet.approve` ka
   designation check hat gaya) — jabki uske paas manager role nahi hai.

   Isi ko note kijiye. Yeh design ka sawal hai: approval designation se rukta hai, role se nahi.

4. **Designation wapas `Field Rep` kar dijiye.** Aage ke saare test iss par tike hain.

---

## Scenario 1 — Field Rep (`rep1`)

Yeh sabse zyada baar chalne wala banda hai. PWA me log in kijiye.

### 1.1 Jo dikhna chahiye
- [ ] Login hote hi PWA khulta hai, Desk **nahi**
- [ ] *Today* board pe aaj ka beat aur uske outlets
- [ ] Day Start (selfie + GPS) maangta hai; bina Day Start ke visit shuru nahi hota
- [ ] Outlet list me **sirf apni territory** ke shop — `rep2` wali territory ka ek shop
      naam se search kijiye, **nahi milna chahiye**
- [ ] Visit → order → scheme preview → submit chalta hai
- [ ] Stock check, van load, collection entry, deposit declare khulte hain
- [ ] *My performance* me **apne** targets aur achievement
- [ ] *Claim expenses* me apna claim ban jata hai

### 1.2 Jo **nahi** dikhna chahiye — yahi asli test hai
- [ ] *My performance* me kisi aur rep ka number **nahi** (`rep2` ka target wahan na ho)
- [ ] Doosri territory ka outlet search me **nahi**
- [ ] Desk URL seedha kholiye — `/app/fieldmate-order` → **"Not Permitted"** ya Desk hi na khule
- [ ] Desk se `/app/fieldmate-location-trail` → `rep2` ki trail **nahi** dikhni chahiye
      (yeh sabse personal row hai; iske liye alag se query hook likha gaya hai)
- [ ] Naya shop onboard kijiye → woh **Pending** me jaata hai, visit ho sakta hai, par
      **uspe order nahi** ban sakta
- [ ] Usi Pending shop ko `rep1` khud approve karne ki koshish kare →
      **"Only a manager can approve a new shop."**
- [ ] Settings, Portal User, Alert Rule, Claim, Order Ingest Log — in paanch pe
      Field Rep ko **kuch bhi nahi** milta. Desk se khole to kuch nahi

### 1.3 Offline
- [ ] Phone ko airplane mode pe daal kar: visit, order, collection — sab ban jaane chahiye
- [ ] Upar offline strip dikhni chahiye, outbox count badhna chahiye
- [ ] Net wapas aane pe sab apne aap chala jaaye, **duplicate banaye bina**
- [ ] Offline me *Sign out* dabaiye → warning aani chahiye ki itni cheezein abhi gayi nahi

---

## Scenario 2 — Area Manager (`am1`)

Isko Desk milta hai. Desk me log in kijiye.

### 2.1 Jo kar sakta hai
- [ ] **Beat** bana aur badal sakta hai (`RWC`)
- [ ] **Outlet** bana aur badal sakta hai; `rep1` ka Pending shop **approve** kar sakta hai
- [ ] **Journey Plan** bana aur submit kar sakta hai — par **cancel nahi**
- [ ] **Order** — padh aur badal sakta hai, aur **cancel** kar sakta hai (`RWX`), par
      naya order Desk se nahi bana sakta
- [ ] **Sync Conflict** — padh aur solve kar sakta hai
- [ ] **Location Trail** — apni team ki trail dikhni chahiye
- [ ] **Geo Fence Exception** — approve/submit kar sakta hai
- [ ] `rep1` aur `rep2` **dono** ke target, achievement, payout, KPI dikhne chahiye
      (manager ke liye rep-only filter nahi lagta)

### 2.2 Jo **nahi** kar sakta
- [ ] **Claim** — sirf padh sakta hai, approve **nahi** (`R` only)
- [ ] **Incentive Scheme / Payout** — sirf padh sakta hai, bana/approve **nahi**
- [ ] **Target Plan** — sirf padh sakta hai, bana **nahi**
- [ ] **Scheme** — sirf padh sakta hai, badal **nahi**
- [ ] **Settings** — sirf padh sakta hai, badal **nahi**
- [ ] **Alert Rule** — sirf padh sakta hai
- [ ] **Portal User** — sirf padh sakta hai, bana **nahi**
- [ ] Apni territory se bahar ka outlet / order / visit — **kuch nahi dikhna chahiye**.
      Ek upar wali ya bagal wali territory ka outlet naam se search kijiye

### 2.3 Territory ka asli test
`am1` dono reps ke parent pe baitha hai, aur `hide_descendants = 0` hai.
- [ ] `rep1` ka outlet dikhe ✓
- [ ] `rep2` ka outlet dikhe ✓
- [ ] `rm1` ki territory ka woh outlet jo in dono ke neeche nahi hai — **na dikhe** ✗

---

## Scenario 3 — Regional Manager (`rm1`)

Area Manager jaisa, par upar ki territory aur kuch alag permissions. Yeh scenario mainly yeh
check karta hai ki **Area Manager se farq kahan hai** — kyunki kaafi jagah RM ko *kam* mila hai.

### 3.1 RM ko jo **extra** milta hai
- [ ] **Field User** badal sakta hai (AM sirf padh sakta hai) — rep ka territory, reports_to
- [ ] **Journey Plan cancel** kar sakta hai (AM nahi kar sakta)
- [ ] **Checklist Template**, **Must Sell List**, **No Order Reason**, **Product Catalogue**,
      **Scheme**, **Order Approval Rule** — badal sakta hai (AM sirf padh sakta hai)

### 3.2 RM ko jo **kam** mila hai — yeh chaukane wala hai, dhyan se dekhiye
- [ ] **Order** — sirf `R`. AM order **cancel** kar sakta hai, RM **nahi**
- [ ] **Visit**, **Collection**, **Retailer Stock**, **Secondary Sales**, **Distributor Stock**,
      **Outstanding Snapshot** — RM ko sirf `R`, jabki AM ke paas `RW` hai
- [ ] **Sync Batch / Sync Conflict / Device Registry** — RM ko **kuch nahi**. AM ko dikhta hai
- [ ] **Share Link** — RM sirf padh sakta hai

Agar yeh "ulta" lage — ki region wala apne area wale se kam kar pa raha hai — to woh aapka
product decision hai, bug nahi. Par **note kar lijiye**, kyunki pilot me manager yeh zaroor
poochega.

### 3.3 Territory
- [ ] `am1` ke neeche ka sab kuch dikhe
- [ ] `sh1` ki baaki region — **na dikhe**

---

## Scenario 4 — Sales Head (`sh1`)

Yeh woh banda hai jo paisa approve karta hai. Sabse zyada dhyan isi pe.

### 4.1 Sirf Sales Head kar sakta hai (Admin ke alawa)
- [ ] **Target Plan** bana sakta hai, aur **submit** → cascade chalta hai, har rep ka leaf plan
      ban jata hai
- [ ] **Incentive Scheme** bana aur submit kar sakta hai
- [ ] **Incentive Payout** bana aur submit kar sakta hai → `Draft → Pending Approval →
      Approved → Paid`
- [ ] **Claim** approve kar sakta hai → **Credit Note** banta hai
      (Sales Invoice, `is_return`, ek settlement line, `update_stock` off)
- [ ] **Expense Claim** submit aur cancel kar sakta hai
- [ ] **Scheme Ledger** submit/cancel kar sakta hai
- [ ] **Alert Rule**, **Portal User**, **Outlet Channel**, **Outlet Class**, **Season**
      bana sakta hai
- [ ] **Scheme** amend kar sakta hai (`RWCSXA`)

### 4.2 Sales Head bhi jo nahi kar sakta
- [ ] **Settings** — sirf padh sakta hai. Sirf Admin badal sakta hai
- [ ] **Geo Fence Exception** — **kuch nahi** milta (AM aur RM ko milta hai).
      Yeh jaan-boojh kar hai ya chhoot gaya — poochh lijiye
- [ ] **Device Registry**, **Sync Batch**, **Sync Conflict** — kuch nahi
- [ ] Kisi bhi FieldMate doc ko **delete** nahi kar sakta

### 4.3 Paise wala poora flow — ek saath
Yeh ek hi chain me chalaiye, yahi Phase 7 + 9 ka asli test hai:

1. `sh1` Target Plan banaye, submit kare → cascade
2. Nightly job (ya haath se `measure_targets`) → Achievement bane
3. Incentive Scheme banaye slabs ke saath
4. `compute_payouts` → Payout bane
5. `rep1` apne PWA pe *My performance* kholo → **wahi number dikhna chahiye**
6. `rep1` ko `rep2` ka payout **nahi** dikhna chahiye

---

## Scenario 5 — Distributor (portal user)

Isko bhi Desk nahi milta. Alag window me portal pe log in kijiye.

- [ ] `FieldMate Portal User` save karte hi `FieldMate Distributor` role **apne aap** lag jaaye
      — haath se mat lagaiye
- [ ] Portal pe sirf **apne** orders dikhein (`portal.order_query`)
- [ ] Doosre distributor ka order URL me naam daal kar kholne ki koshish → **nahi khulna chahiye**
- [ ] Apne claims ka status dikhe, par claim **approve na kar sake** (`R` only)
- [ ] Secondary sales upload chale
- [ ] Desk URL `/app` → **na khule**
- [ ] Outlet, Visit, Collection, Target — in me se **kuch bhi na dikhe**

---

## Scenario 6 — Admin

- [ ] Sab kuch dikhe aur sab kuch ho — yahi iska matlab hai
- [ ] **Settings** sirf yahi badal sakta hai
- [ ] Delete sirf yahi kar sakta hai

Admin ka test chhota isliye hai ki uspe koi rok hai hi nahi. Jo bhi upar kisi ne "nahi kar paya",
woh Admin se kar ke dekh lijiye — agar Admin se bhi nahi hua, to woh permission ka nahi, **code
ka** bug hai.

---

## Scenario 7 — Cross-check: ek hi document, paanch aankhon se

Sabse tez tarika jisme galti pakdi jaati hai. Ek hi order lijiye — `rep1` ka submit kiya hua —
aur paanchon window me ek saath kholiye.

| Kaun | Dikhna chahiye | Badal sakta hai | Cancel |
|---|---|---|---|
| `rep1` (jisne banaya) | haan, PWA me | nahi | nahi |
| `rep2` | **nahi** | — | — |
| `am1` | haan | haan | **haan** |
| `rm1` | haan | **nahi** | **nahi** |
| `sh1` | haan | nahi | nahi |
| Distributor | haan (apna hai to) | nahi | nahi |

Yahi table Visit, Collection aur Retailer Stock ke liye dohra dijiye — teenon me RM ko `R` aur
AM ko `RW` mila hai, aur yahi sabse zyada ulta lagne wala hissa hai.

---

## Kya note karna hai

Har fail hone wali line ke liye teen cheezein likhiye:

1. **Kaun** — kaunsa user, kaunsa role, kaunsi territory
2. **Kya kiya** — URL ya screen, aur kaunsa button
3. **Kya dikha** vs **kya dikhna chahiye tha**

"Manager ko kuch nahi dikh raha" se kuch pata nahi chalta. "am1@test, FieldMate Area Manager,
territory NORTH, /app/fieldmate-claim pe Approve button nahi hai" — isse seedha permission row
tak pahunch jaate hain.

---

## Pehle se pata hui do kamiyaan

Test karte waqt yeh milengi — ye nayi nahi hain, likhi hui hain:

1. **Target Plan, Claim aur Payout pe Desk buttons nahi hain.** Sales Head ko cascade /
   recompute / compute_payouts ke liye browser console kholna padta hai. Yeh kaam karta hai,
   par koi manager aisa nahi karega.
2. **`before_uninstall` hook nahi hai.** App uninstall karne pe Custom Fields reh jaate hain aur
   us site ka Customer form tut jaata hai.
