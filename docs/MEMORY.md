# MEMORY — current project state

Current state only. Permanent decisions go in DECISIONS.md.
**Update at the end of every task.**

---

## Current status

**App scaffolded.** `fieldmate` exists at `apps/fieldmate`, imports cleanly, `required_apps` set.
No DocTypes, no APIs, no frontend yet. Not installed on any site.

Last updated: 21 Sep 2026

## Completed

- Market and category research (Bizom, FieldAssist, BeatRoute, Ivy, SalesDiary, pharma SFA)
- ERPNext / HRMS reuse audit against the live bench (Frappe 15.118.0, ERPNext 15.119.1)
- Full build plan: 68 DocTypes, 1,078 fields, 46 APIs, 11 phases, 4 process diagrams
  - `C:\Users\Abhishek Kumar\Desktop\SFA-Build-Plan.html` (written before the rename; content valid)
  - https://claude.ai/artifact/JDPUCtn6yMAZZ5WrGKRWRe
- Claude skills in `.claude/skills/`: `fieldmate` (+4 references), `fieldmate-doctype`,
  `fieldmate-api`, `fieldmate-pwa`, `fieldmate-testing`
- Planning documents in `fieldmate-docs/`: PRD, ARCHITECTURE, DESIGN, RULES, TASKS, DECISIONS,
  MEMORY, TEST_PLAN, SECURITY, .env.example
- ADR-001 through ADR-012 recorded
- **Task 0.1 (partial)** — `bench new-app fieldmate --no-git` run 21 Sep 2026.
  `app_title` FieldMate, publisher somilvaishya, MIT, module `FieldMate`.
  `required_apps = ["erpnext", "hrms"]` set. Skeleton dirs created: `api/`, `services/`,
  `fieldmate/doctype/`.

## Current task

**Task 0.1 remainder** — git init + first feature branch. Deliberately not done: the app was
scaffolded with `--no-git` to respect the no-git-writes-without-approval rule. Needs a go-ahead.

## Known issues

- **`bench build` fails bench-wide, pre-existing, not FieldMate's fault.** `sites/apps.txt`
  contains `ai-interface`; the hyphen is not a valid Python module name, so
  `frappe.build.generate_assets_map` raises `ModuleNotFoundError: No module named 'ai-interface'`
  for *any* app. Blocks asset builds — will matter from Phase 0.11 (PWA scaffold) onward.
  Fix is either renaming that app to `ai_interface` or removing it from apps.txt. **Owner's call —
  do not change it unilaterally.**
- `node`/`yarn` are not on the non-interactive PATH (they live under nvm: v18.20.8, v20.20.2).
  The PWA build will need nvm sourced explicitly.
- Nothing installed on a site yet — install target not decided.

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
