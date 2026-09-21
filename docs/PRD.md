# PRD — FieldMate Field Force

**PRD = WHAT + WHY.** How is in ARCHITECTURE.md.

## Product

`fieldmate` — a Sales Force Automation app for FMCG/consumer-goods distribution, built as a Frappe
custom app with an offline-first PWA for field reps.

## Problem

A distribution company sells to distributors and employs a field team to cover retail outlets and
book orders the distributors fulfil. Today that work is invisible: orders travel by WhatsApp and
paper, nobody can prove a rep visited an outlet, trade schemes are computed by hand and settled by
email, and secondary sales — what the distributor actually sells onward — are unknown. ERPNext
records the billing but nothing about the selling.

Commercial FieldMate products (Bizom, FieldAssist, BeatRoute) solve this but sit outside ERPNext, so the
company pays twice and reconciles two systems by spreadsheet.

## Target users

Four roles with genuinely conflicting needs. Do not collapse them into "users".

| Role | Uses | Cares about |
|---|---|---|
| **Field rep** | PWA, 60–80 times a day, standing, often offline | Speed. Two-tap repeat orders. Knowing their incentive. |
| **Area manager** | Desk + reports | Who worked today, beat adherence, approving outlets and blocked orders |
| **Sales head** | Desk + Insights | Coverage, distribution, scheme ROI, target achievement |
| **Distributor** | Frappe portal | Order queue, fulfilment, scheme claim settlement |

## Goal

One system where a field visit, the order it produced, the money collected and the resulting
invoice are the same connected record — with ERPNext remaining the single book of account.

## Core features

1. Outlet, beat and journey-plan masters with territory-scoped access
2. Geo-verified attendance and visit capture, fully offline
3. In-visit tasks: stock & sales audit, merchandising, surveys, competitor capture
4. Offline order capture with a scheme and pricing engine, feeding ERPNext Sales Orders
5. Door collections feeding Payment Entries on deposit confirmation
6. Secondary sales capture (never billed, never posted to the GL)
7. Targets, achievement and incentive computation
8. Coverage and productivity analytics from a materialised KPI table
9. Distributor portal for orders and scheme claims

## MVP

Phases 0–4 and 6, verified on `testerp2` with a 10–15 rep pilot:

- Masters (outlets, beats, field users) importable at scale
- Day Start → beat → geo check-in → in-visit tasks → check-out → Day End
- Offline order capture with schemes, credit check, Sales Order creation
- Door collections with deposit-confirmed Payment Entries
- A rep can work a full offline day and lose nothing

## Out of scope for v1

- Van sales / DSD (Phase 5) unless confirmed in scope — see open decision 2
- Full distributor management (billing, warehousing, routing) — distributor stock is read-only visibility
- Pharma model (doctors, RCPA, POB) — different vertical, different data model
- Custom manager SPA — managers use Frappe Desk
- Route optimisation / turn-by-turn navigation
- Modern-trade-specific planogram compliance scoring

## Success criteria

1. A rep completes a full 9-hour day entirely offline and every record reaches the server.
2. Zero duplicate documents across the pilot, proven by `client_uuid` uniqueness.
3. Scheme results match between the device engine and the server engine on all 60 parity cases.
4. Pilot reps work unaided after a 30-minute briefing.
5. Coverage, strike rate and productive-call numbers reconcile to hand calculation for one rep-week.
6. No field role can post to the ledger, verified by attempted direct access.
7. The app installs and passes its suite on both v15 and v16.

## Open decisions blocking Phase 1

See `fieldmate` skill → `references/build-plan.md`. Questions 1 (direct-billed outlets), 2 (van sales)
and 3 (worst real schemes) must be answered before masters are built.
