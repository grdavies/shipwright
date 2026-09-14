## Two-tier plan lifecycle (PRD 022)

Proposals route through `python3 scripts/wave.py plan validate` — **never** hand-author plan JSON in prose.
Kernel invariants live in `core/sw-reference/kernel-classification.md` (single home — do not duplicate the
enumeration here).

| Tier | Proposer | Validated plan | Durable owner | Driver |
| --- | --- | --- | --- | --- |
| Wave | Conductor at wave entry | Wave-batching plan | `waveBatchingPlan` on shared run-state | `wave_deliver_loop` |
| Phase | Phase executor at phase entry | Phase step plan | `.cursor/sw-deliver-runs/<phase-slug>/phase-step-plan.json` | `ship_phase_steps.py` |

**Lifecycle** (`twoTierLifecycle` on shared run-state): `wave-validated` → `phase-plan-pending` →
`phase-plan-validated`. Crash with a validated wave but missing/pending phase plan re-runs phase
proposal+validate only — never partial execution.

**Reject fallbacks:** phase reject → canonical chain from `kernel-classification.json`; wave contention or
dependency violation → canonical waves re-derived from the frozen plan; over-ceiling → `wave.py schedule`.

**Proposed pilot wiring (PRD 023 phase 1):** `/sw-deliver` reads `orchestration.planPolicy` at wave entry and
phase entry. Under `proposed` (after TR0 gate), the conductor proposes → `wave.py plan validate`
(`--record-rejection` on shared state) → persist; `wave_deliver_loop` sets `wave-validated` after wave persist
and routes phase entry through validate-before-persist. Default `canonical` is unchanged.

**`orchestration.planPolicy`:** read at proposal time (default `canonical` — byte-identical to today);
recorded `planPolicy` + `kernelVersion` + `guidelineVersion` stamped on each persisted plan and honored on
resume over live config. Live `proposed` runs on `/sw-deliver` when TR0 passes and pilot opt-in guards are
met; default stays `canonical`. PRD-024 fans the pattern to other orchestrators — see
`docs/prds/022-kernel-classification-and-plan-validation/call-site-map.md`.
