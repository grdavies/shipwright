## Legitimate-halt set (R10)

Halt for human input **only** when one of these applies:

| # | Condition | Detection |
| --- | --- | --- |
| 1 | Final merge to `main` | Terminal gate (`report terminal`); never auto-merged |
| 2 | Remediation budget exhausted | `remediationAttempts[phaseId] >= deliver.remediation.maxAttempts` |
| 3 | Ambiguous merge / destructive action | Merge conflict, explicit revert, or irreversible git op |
| 4 | Configured checkpoint | `doc.afterTasks: confirm`, `deliver.phaseAckCadence: K>0`, `deliver.autonomy.mode: supervised` |
| 5 | Phase liveness timeout (R37) | `phase-timeout:<id>` — in-flight phase exceeds `deliver.watchdog.phaseTimeoutMinutes` without terminal `status.json` |
| 6 | External wait exhausted (R40) | CI/self-wake hits `checks.watch.maxWaitMinutes` without signal |
| 7 | Run-level autonomy budget (R42) | `deliver.autonomy.maxRunMinutes` or `maxIterations` exceeded |
| 8 | No-progress circuit breaker (R38) | 3× identical `nextAction` + unchanged state signature |
| 9 | Driver-enforced budget trip (PRD 023 TR3) | `runStartedAt` / `driverIterationCount` / `noProgressStreak` exceeded; `planRejectionLog` feeds no-progress |

Anything not in this table is **not** a legitimate halt.

### Driver-enforced budgets (PRD 023 TR3)

`wave_deliver_loop.py` maintains durable `runStartedAt`, `driverIterationCount`, and `noProgressStreak` on
shared run-state. Proposal and `plan validate` overhead count separately from execution iterations; persistent
`planRejectionLog` rejections increment no-progress. Budget trip emits `halt-blocked` with merge-queue journal
replayability and scoped lock release (R22). Terminal runs roll up `benefitMetric` and surface chosen plans /
rejections / capability sets via `deliver_plan_surfacing` (R21).
