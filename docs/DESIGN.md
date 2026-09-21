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

Defined as tokens; both light and dark are designed, since reps work indoors and outdoors.

| Token | Light | Purpose |
|---|---|---|
| `--bg` | `#F4F6F5` | page ground |
| `--surface` | `#FFFFFF` | cards, sheets |
| `--ink` | `#141E1C` | primary text |
| `--muted` | `#5F706B` | secondary text (still ≥4.5:1) |
| `--line` | `#D3DCD9` | borders |
| `--primary` | `#B81E5A` | primary action |
| `--ok` | `#2C6E45` | done, synced, in credit |
| `--warn` | `#9A6410` | pending, due now, queue backlog |
| `--crit` | `#A32A26` | blocked, overdue, breach |

**Minimum 4.5:1 contrast throughout.** No thin grey-on-grey — it disappears in sunlight. Semantic
colour (ok/warn/crit) is separate from the primary accent and never doubles as decoration.

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
11. **Renders at 360 px.** That is the device that matters.
12. **All strings translatable.** No hard-coded user-facing text, from day one.

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
