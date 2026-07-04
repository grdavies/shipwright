# Call-site map — execute tier (PRD 053)

Extends [PRD 022 call-site map](../../docs/prds/022-kernel-classification-and-plan-validation/call-site-map.md)
with execute-tier proposal sites under `/sw-ship --phase-mode`.

| Entrypoint | Flag read site | Plan tier | Canonical fallback | Live wiring | Parity / gate fixtures |
| --- | --- | --- | --- | --- | --- |
| `/sw-ship` execute fan-out | `execute_plan.py` / `execute_ship.py` at phase entry (before `sw-verify`) | Execute step plan | Linear authored order + contention edges (`execute_fallback_canonical_linear_order`) | PRD 053 default-on (`execute.enabled: true`) | `execute-plan-dag-049-phase-2`, `execute-plan-linear-fallback`, `execute-ship-chain-gated` |
| `/sw-ship` per-ref dispatch | `ship_phase_steps.py` / `intra_phase_dispatch.py` (`execute_fan_out`) | Execute dispatch | Monolithic `/sw-execute` when single sub-task or `execute.enabled: false` | PRD 053 | `execute-single-subtask-skip-tier`, `execute-plan-dag-049-phase-2` |
| `wave.py execute integrate` | `execute_integrate.py` at per-ref terminal | Integrate journal | N/A (phase-executor scoped) | PRD 053 | `execute-integrate-clean-merge`, `execute-integrate-conflict-partial-batch` |

## Mechanical primitives

| Primitive | Role |
| --- | --- |
| `python3 scripts/wave.py plan validate --tier execute …` | Closed-world execute DAG gate |
| `python3 scripts/execute_plan.py propose` | Build execute-step-plan from frozen task list |
| `python3 scripts/wave.py execute integrate …` | Phase-scoped sub-branch merge (not conductor merge queue) |
| `python3 scripts/execute_failure.py blast-radius apply` | Block transitive dependents on ref failure |

## Resume semantics

| Condition | Behavior |
| --- | --- |
| Mid-phase crash after partial integrate | Resume from `execute-step-plan.json` + `integrate-journal.json` + per-ref status |
| Stale sub-branch | `execute_ship.py resume-frontier` reports reprovision path |
| `execute.enabled: false` | Skip execute tier; monolithic `sw-execute` Task |
