# Call-site map — orchestration plan policy (PRD 022 phase 7, TR9)

Enumerates every orchestrator proposal entrypoint that reads `orchestration.planPolicy`, its canonical
fallback when the flag is `canonical` (default), and its parity-fixture scope. **`proposed` is
fixture-only** for most rows until PRD-023/024 wire live consumption — this map ensures no flag read is
silently missed.

| Entrypoint | Flag read site | Plan tier | Canonical fallback | Live wiring | Parity / gate fixtures |
| --- | --- | --- | --- | --- | --- |
| `/sw-deliver` wave dispatch | `wave_deliver_loop.py` / conductor at wave entry | Wave batching | `.cursor/sw-deliver-plan.json` waves via `wave.sh plan` | PRD-023 pilot | `wave-fallback-canonical-waves`, `wave-fallback-schedule-overceiling`, `killswitch-canonical-parity` |
| `/sw-deliver` phase dispatch | Phase executor via `ship_phase_steps.py` at phase entry | Phase step plan | `canonicalPhaseChains.sw-ship` → `SHIP_CHAIN` | PRD-023 pilot | `phase-fallback-canonical-chain`, `exec-fidelity-out-of-order-halt`, `killswitch-canonical-parity` |
| `/sw-ship --phase-mode` | `wave_plan_validate.py` / `ship_phase_steps.authoritative_chain` | Phase step plan | Hardcoded canonical chain from `kernel-classification.json` | PRD-023 (via deliver) | `phase-fallback-canonical-chain`, `exec-fidelity-out-of-order-halt` |
| `/sw-ship` interactive | *(deferred)* | Phase step plan | Prose chain in `sw-ship.md` / `SHIP_CHAIN` | **Not in PRD-024** — tracked here | — |
| `/sw-doc` orchestrator chain | *(PRD-024)* `sw-doc` procedure at entry | Single-tier orchestrator plan | Existing `/sw-doc` delegate chain | PRD-024 | `killswitch-canonical-parity` (per-orchestrator, 024) |
| `/sw-debug` orchestrator chain | *(PRD-024)* `sw-debug` procedure at entry | Single-tier orchestrator plan | Existing triage → RCA → route chain | PRD-024 | TR7 subset + route-halt fixtures (024) |
| `/sw-feedback` orchestrator chain | *(PRD-024)* `sw-feedback` procedure at entry | Single-tier orchestrator plan | Existing normalize → route chain | PRD-024 | TR7 subset + handoff-halt fixtures (024) |

## Mechanical primitives (all entrypoints)

| Primitive | Role |
| --- | --- |
| `bash scripts/wave.sh plan validate --tier phase …` | Closed-world phase step plan gate (kernel + guidelines + floor) |
| `bash scripts/wave.sh plan validate --tier wave …` | Wave batching gate (contention + `parallelCeiling`) |
| `scripts/plan_persist.py` | Atomic persist to durable owners; single-writer guard |
| `scripts/ship_phase_steps.py` | Deterministic driver — stored plan is sole authority; ordering re-check at `advance` |

## Resume semantics

| Condition | Behavior |
| --- | --- |
| Run persisted under `proposed` | Completes under **recorded** `planPolicy` + stamped `kernelVersion` / `guidelineVersion` |
| Mid-run config flip after wave persist | Recorded wave mode stays authoritative until phase entry |
| Corrupt / stale-version plan on resume | Fail-closed halt or canonical replacement — never partial execution |

Fixtures: `killswitch-flip-midrun-recorded-mode`, `resume-corrupt-plan-fail-closed`, `resume-two-tier-deterministic`.

## Kernel chokepoints (unchanged under `proposed`)

Named parity fixtures assert each chokepoint is unchanged when `planPolicy: proposed`:

- `plan-proposed-memory-preflight-required`
- `plan-proposed-memory-redact-fail-closed`
- `plan-proposed-secret-scan-before-push`
- `plan-proposed-no-main-auto-merge`
- `plan-proposed-merge-single-flight`
- `plan-proposed-redaction-guard-range-scope`
- `plan-proposed-guardrails-hook-non-selectable`

Suite: `bash scripts/test/run-plan-proposed-parity-fixtures.sh`.

## Cutover policy

1. PRD-022 gate + driver + persist fixtures green in `verify.test` (this slice — dark default).
2. PRD-023 enables live `proposed` on `/sw-deliver` only after R31 benefit metric (program gate).
3. PRD-024 fans out to `/sw-debug`, `/sw-doc`, `/sw-feedback` when 023 metric is positive.
4. Interactive `/sw-ship` remains deferred until explicitly scheduled — flag read tracked in this map.
