# MEMORY — current project state

Current state only. Permanent decisions go in DECISIONS.md.
**Update at the end of every task.**

---

## Current status

**Phase 0 and Phase 1 complete. Gate 0 and Gate 1 both passed.**
17 DocTypes, 14 whitelisted methods, **171 tests green**, ruff clean.

Branch `feature/phase-1-masters`, off main after PR #1.

Last updated: 21 Sep 2026

## Completed

- **Phase 0** — app scaffold, roles, version guard, `compat.py`, three sync DocTypes, the
  `fieldmate.api.*` facade and sync contract, offline-first Vue PWA, local CI lane.
  Gate 0 passed on a real Android device.
- **Phase 1** — Settings, Field User, Outlet Channel, Outlet Class, Outlet, Outlet Contact,
  Beat, Beat Outlet, Distributor Profile, Product Catalogue, Catalogue Item, Must Sell List,
  Must Sell Item, Geo Fence Exception. Seven outlet endpoints, a per-row bulk importer, and
  four PWA screens (outlet list, Outlet 360, onboarding, beats).
- Two security fixes found by testing rather than review: `sync.pull` used `frappe.get_all`,
  which forces `ignore_permissions=True` and would have sent every outlet to every rep; and
  `pull_fields` was unset for Outlet, putting a 500-outlet pull at 6.6 MB against a 2.5 MB
  budget. Both fixed and covered.
- `docs/MANUAL_TESTS.md` now covers both phases: 8 Phase 0 checks, 12 Phase 1 checks, plus setup.

## Current task

None. **Phase 2 (journey plan and attendance) is next** — 7 DocTypes, and the first phase that
writes into HRMS, so it exercises the compat layer for real.

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
