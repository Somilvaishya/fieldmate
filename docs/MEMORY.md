# MEMORY — current project state

Current state only. Permanent decisions go in DECISIONS.md.
**Update at the end of every task.**

---

## Current status

**Phase 0 complete. Gate 0 passed on 21 Sep 2026** (v15 scope, ADR-015).

`fieldmate` is installed on `testerp2`, serving an installable offline-first PWA at
`/assets/fieldmate/pwa/index.html`. 3 DocTypes, 7 whitelisted methods, 42 tests green, ruff clean.

Last updated: 21 Sep 2026

## Completed

- Market research, ERPNext/HRMS reuse audit, full build plan (68 DocTypes, 46 APIs, 11 phases)
  - Canonical plan: https://kgopldummy.m.frappe.cloud/sfa_plan (predates the FieldMate rename)
- Claude skills in `.claude/skills/`: `fieldmate` (+4 references) and four sibling skills
- Planning docs in `apps/fieldmate/docs/`, ADR-001 to ADR-015
- **Phase 0, all 14 tasks**, on `feature/phase-0-foundation`:
  - 0.1 app scaffold, 0.1b git init and push
  - 0.2 six roles, 0.3 install-time version guard, 0.4 `compat.py`
  - 0.5-0.7 Device Registry, Sync Batch, Sync Conflict
  - 0.8-0.10 `api/_base.py` envelope plus the auth and sync contract
  - 0.11-0.13 Vue 3 + Vite + Dexie + Workbox PWA, offline-first
  - 0.14 CI matrix written; `scripts/ci-local.sh` is the lane that actually runs
- Bugs found by manual testing and fixed: service worker scope, Jinja-rendered www assets,
  unregistered device on a returning session, Frappe errors rendered as data, a `start_url`
  pointing at a 404, `DataCloneError` from caching a Vue proxy, and "Failed to fetch" shown
  to a rep as a red error

## Current task

**Phase 1 in progress** on `feature/phase-1-masters`. **17 DocTypes, 142 tests green.**

Done: 1.1 Settings · 1.2 Field User · 1.3 Channel + Class · 1.4 Outlet + Contact ·
1.5 Beat + Beat Outlet · 1.6 Distributor Profile · 1.7 Product Catalogue + Item ·
1.8 Must Sell List + Item · 1.9 Geo Fence Exception.

All nine master DocTypes for Phase 1 exist. What remains is behaviour rather than schema:

**Next: 1.10** the five outlet APIs (search, detail, create, update, approve), then
**1.11** bulk import templates with geo validation, **1.12** PWA screens, then **Gate 1**.

## Known issues

- **GitHub Actions blocked** by an account billing lock over a metered Copilot balance,
  unrelated to this repo. The repo is public, so Actions minutes are free. Support ticket
  drafted. `scripts/ci-local.sh` covers gates meanwhile.
- `developer_mode` is off on testerp2. Not needed while DocTypes are authored as JSON on disk,
  but required to edit them through the Desk UI.
- v16/v17 compatibility is **unverified** (ADR-015). Do not claim it.
- Test accounts on testerp2: `rep1@fieldmate.test` and `mgr1@fieldmate.test`, both
  `FieldMate@2026`. Test-site credentials, not for production.

## Open decisions

Blocking Phase 1 (masters):

1. **Vertical: FMCG or automotive?** The Stitch screens show Lubricants, Spare Parts, Tires,
   Safety Vests, Wrench Sets — that is automotive aftermarket, not FMCG kirana. The whole plan
   assumed FMCG. This changes outlet types, beat frequency, scheme shapes and the must-sell model.
   **Highest priority.**
2. Does any outlet get billed directly? → affects `FieldMate Outlet.customer`
3. Van sales in scope, or order-booking only? → most of Phase 5 (2 weeks)
4. The three most complicated live schemes → the engine is designed around the real worst case

Wanted soon:

5. Secondary sales: rep audits, distributor uploads, or both? Which wins on disagreement?
6. Launch languages — cheap in Phase 0, expensive as a Phase 8 retrofit
7. Pilot geography and the 10–15 named reps

## Next step

Confirm the vertical (decision 1), then either continue Phase 0 (Task 0.2 roles → 0.14 CI) or
pause to rework the masters model if this is automotive rather than FMCG.
