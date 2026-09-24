# DESIGN — FieldMate Field Force

**DESIGN.md = HOW IT SHOULD LOOK AND FEEL.**

Our design is driven by the field, not by taste. A rep uses this 60–80 times a day, standing,
one-handed, in sunlight, often with no signal, while talking to a shopkeeper. Everything below
follows from that.

## Style

Utilitarian and legible. Dense where it saves taps, spacious where it prevents mis-taps. No
decorative motion, no brand flourish that costs a frame on a four-year-old Android. The app should
feel like a well-made tool, not a consumer product.

## Typography

- System font stack — no web font download on a metered connection.
  `-apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif`
- **16 px minimum** body text. Never smaller, for any reason.
- 18–20 px for primary values (order totals, outlet names).
- `font-variant-numeric: tabular-nums` everywhere digits line up — quantities, amounts, KPI tiles.
- Line height 1.5 minimum for anything read in motion.

## Colors

**Derived from the logo, not chosen.** `frontend/scripts/make-palette.py` reads the brand mark
at `frontend/brand/app-icon.png`, pulls the navy and the green out of it, walks each colour's
lightness down until it measures 4.5:1 *where it is actually used*, and refuses to emit a
palette that fails. Every value below is audited output. Change the logo, re-run it, and the
theme follows.

| Token | Value | Purpose |
|---|---|---|
| `--bg` | `#F4F5F7` | page ground, faintly navy |
| `--surface` | `#FFFFFF` | cards, sheets |
| `--ink` | `#05172E` | primary text |
| `--muted` | `#465972` | secondary text (6.6:1 on the page) |
| `--line` | `#BFC7D2` | borders |
| `--primary` | `#092850` | primary action — the logo navy, 14.7:1 on white |
| `--primary-soft` | `#E6EAEE` | tinted fill that navy text sits on |
| `--on-primary` | `#FFFFFF` | text on the primary fill |
| `--accent` | `#3BBF62` | the logo green — **fills and icons only** |
| `--ok` | `#277D40` | done, synced, in credit |
| `--ok-soft` | `#E4F6E9` | the card an `ok` message sits on |
| `--warn` | `#955F07` | pending, due now, queue backlog |
| `--warn-soft` | `#F9ECD8` | the card a `warn` message sits on |
| `--crit` | `#C62A25` | blocked, overdue, breach |
| `--crit-soft` | `#FAE4E3` | the card a `crit` message sits on |

**Minimum 4.5:1 contrast throughout.** No thin grey-on-grey — it disappears in sunlight. Semantic
colour (ok/warn/crit) is separate from the primary accent and never doubles as decoration.

Two rules the audit exists to enforce, both of which were broken before it existed:

- **The brand green is never text on white.** It measures 2.4:1, which is illegible outdoors.
  It is a fill and an icon colour. `--ok` is the same hue darkened until it is readable, so the
  family still reads as one.
- **Status colours are checked against their own tinted card**, not against white. Amber text on
  an amber card is a strictly harder pairing than amber text on a page, and checking only the
  easy case passed three colours that failed where they are actually rendered.

Dark mode is **not** implemented. The tokens are structured for it, but no dark values are
defined and `color-scheme` is `light`.

## Buttons

| Type | Use |
|---|---|
| **Primary** | Filled `--primary`, white text. One per screen, bottom third. |
| **Secondary** | Outlined `--primary`. Alternative paths ("No order — give reason"). |
| **Destructive** | Outlined `--crit`. Cancel, delete. Always confirms. |

**48 px minimum height and hit area** on every interactive element. 8 px minimum gap between
adjacent targets.

## Cards and sheets

- Border radius 6 px on cards, 16 px on bottom sheets.
- One border, no shadow stack. Border and fill are spent by role — not every block is a card.
- **Bottom sheets, not modals.** A modal centred on screen is out of thumb reach.

## UX requirements

These are requirements, not preferences. A screen that fails any of them is not done.

1. **Primary actions live in the bottom third.** One-handed use while standing.
2. **A permanent state strip** — online / offline with queue count / syncing. Always honest about
   queue depth. Never a spinner that could hang forever.
3. **Every write commits locally first and says so.** "Saved" appears immediately.
4. **Loading, empty and error states are designed**, not afterthoughts. An empty beat list says why.
5. **Errors explain what went wrong and what to do**, in a rep's language. No codes, no apologies,
   no stack traces.
6. **Icons always paired with text.** Mixed literacy is a real constraint in these markets.
7. **Product thumbnails in the catalogue**, numeric keypads for quantity entry.
8. **Repeat-order prefill** — the cart opens on the last order's lines with quantities filled. A
   repeat order is two taps, not forty.
9. **Credit headroom shown before the cart is built**, never as a rejection afterwards.
10. **Scheme results explained in words** — "Qty slab 4+ case → 3% off, free 2 pc soap". "Why did I
    get this discount" is the single most common field support call.
11. **Free goods are listed, never folded into a discount.** A scheme that gives 2 free packs and
    ₹19.68 off reads as *"₹19.68 off, and 2 free packs"* — never as one combined "₹263.68 saved".
    Free stock ships at ₹0.00 in addition to the order; its value is not a deduction. Showing a
    single savings figure that includes it pays the shop twice on paper, and the distributor
    settles a claim for the half nobody authorised. `SCHEME_SPEC.md` S9 has the two figures:
    `discount_paise` is what comes off the bill and is the only thing a total may subtract;
    `benefit_paise` is what the shop received and belongs on the scheme card, labelled as such.
12. **Renders at 360 px.** That is the device that matters.
13. **All strings translatable.** No hard-coded user-facing text, from day one.

## Breakpoints

| Width | Surface |
|---|---|
| 360 px | Field phone — the one that matters |
| 768 px | Tablet, occasional supervisor use |
| 1440 px | Frappe Desk (manager surfaces, not our CSS) |

## Motion

- Respect `prefers-reduced-motion`.
- Transitions under 150 ms, or none. A four-year-old Android drops frames on anything ambitious,
  and a dropped frame during order entry reads as a broken app.
