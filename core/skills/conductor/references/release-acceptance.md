# PRD 062 release acceptance

## PRD 062 release acceptance metrics (R18)

PRD 062 is **not complete** until all R1–R19 harnesses pass **and** these four operator acceptance checks
are green on the integration branch (record in verify notes / `benefitMetric` soak where applicable):

| # | Metric | Pass criterion | R-IDs |
| --- | --- | --- | --- |
| 1 | Issue-store deliver entry | Provision materializes frozen task list before discover; `--issue` normalize stable | R1, R2 |
| 2 | Terminal ship on separate-project | Docs-currency slug fallback + readonly gap-backlog skip unblock phase ship | R4, R5 |
| 3 | Loop drain without spin | `deliver.loop.drainMechanical: true` drains mechanical steps; no spurious `conductor:no-progress` on happy path | R7, R9 |
| 4 | Scoped cleanup hygiene | Unrelated in-flight scoped run does not block terminal orch cleanup; `cleanup.autonomy: auto` respects terminal allowlist | R10, R11 |

Meta gate: `scripts/unit_tests/deliver/test_prd062_release_completeness.py` (R20).
