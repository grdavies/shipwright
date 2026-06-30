---
prd: docs/prds/036-delivery-conductor-concurrency-and-remediation-robustness/036-prd-delivery-conductor-concurrency-and-remediation-robustness.md
date: 2026-06-28
topic: delivery-conductor-concurrency-and-remediation-robustness
frozen: true
frozen_at: 2026-06-28
---
# Tasks — PRD 036 Delivery-Conductor Concurrency & Remediation Robustness

Generated from the frozen PRD 036 spec union (R1–R22, no amendments). Phases map to the four PRD workstreams
plus a cross-cutting CI/invariant/dogfood phase. All fixtures run offline/deterministically (host stubs); no
live GitHub. New `core/` scripts/keys propagate to both dist trees (R20).

## Tasks

### 1. Ship single-flight (R1–R5) — L

Make a concurrent parent + sub-agent ship on one phase head incapable of producing more than one PR, always
based on the integration branch.

- [ ] 1.1 Per-phase-head single-shipper lease (R2)
  - **File:** `scripts/wave_lock.py`, `scripts/wave.sh` (lock verbs)
  - **Expected:** new keyed lease file `.cursor/sw-deliver-locks/<phaseBranchHash>.lock` reusing the `O_EXCL`/`reclaim_stale_lock` internals; key `(integrationBranch, phaseBranch)`; heartbeat-based liveness (steal only on stale `heartbeatAt`, illegal while `shipSteps` in-progress); short ship-lease TTL distinct from `SW_LOCK_STALE_SECONDS`; `realpath` resolution, reject symlinked parents, sanitized slug
  - **R-IDs:** R2
- [ ] 1.2 In-turn single-ship dispatch discipline (R1)
  - **File:** `scripts/wave_deliver_loop.py`, `core/skills/conductor/SKILL.md`, `core/rules/sw-conductor.mdc`, `core/rules/sw-dispatch-background-phase.mdc`
  - **Expected:** `dispatch-ship` for a single phase runs in-turn (`background=False`); only `dispatch-batch` backgrounds sub-agents on distinct heads
  - **R-IDs:** R1
- [ ] 1.3 PR-creation idempotency window + durable PR record (R3)
  - **File:** `scripts/wave_phase_pr.py`, `scripts/wave_terminal.py`
  - **Expected:** `pr-list --head <branch>` filtered by integration base, executed under the per-head lease across the list→create window; persist `openPrNumber` to durable wave state on first create; second create for a recorded-open head is fatal → supersede flow
  - **R-IDs:** R3
- [ ] 1.4 Integration-base pinning from durable state (R4)
  - **File:** `scripts/wave_phase_pr.py`
  - **Expected:** base sourced from durable deliver state as sole authority; `SW_INTEGRATION_BRANCH` harness-only with fail-closed on disagreement; re-validate integration stamp immediately before `pr-create`; fail closed when `SW_PHASE_MODE` and base ≠ current integration; close PRs whose base ≠ current integration before enqueue
  - **R-IDs:** R4
- [ ] 1.5 Takeover hygiene + canonical PR selection (R5)
  - **File:** `scripts/wave_phase_pr.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** on parent takeover the orphaned sub-agent is cancelled/prevented from reaching `sw-pr`; duplicates resolved by integration-base identity (not finish order); superseded duplicates closed by branch identity (PRD 026 R21 consistent)
  - **R-IDs:** R5
- [ ] 1.6 Dual-ship regression fixture (R18)
  - **File:** `scripts/test/run-dual-ship-fixtures.sh`
  - **Expected:** deterministic simulation — two concurrent `lock acquire` / `host_pr_create` callers on one head with host stubs → exactly one PR on the integration base, no orphan-`main` PR, lease-holder wins; asserts PRD 026 R20/R21 did not cover the racing path
  - **R-IDs:** R18
- [ ] 1.7 Propagate + docs (R20, R21)
  - **File:** `core/` mirror via `scripts/copy-to-core.sh`, dist via `python3 -m sw generate --all`, `core/commands/sw-ship.md`
  - **Expected:** `copy-to-core` parity + emitter-freshness green; `sw-ship.md` phase-mode PR/base/lease contract documented
  - **R-IDs:** R20

### 2. Regression remediation routing (R6–R8) — M

Make a genuine post-merge regression reach bounded `/sw-stabilize` without tripping the no-progress breaker.

- [ ] 2.1 Route `verify:failed` to bounded remediation (R6)
  - **File:** `scripts/wave_deliver_loop.py` (`merge-run-next`), `scripts/wave_failure.py`
  - **Expected:** exit-20 regression routes to `remediate`/`/sw-stabilize` within `deliver.remediation.maxAttempts`; classification from structured exit codes + `check-gate` JSON first (substring markers tie-breaker only); separate environmental vs regression budgets
  - **R-IDs:** R6
- [ ] 2.2 No-progress signature includes remediation state (R7)
  - **File:** `scripts/wave_deliver_loop.py` (`build_state_signature`)
  - **Expected:** signature incorporates per-phase `remediationAttempts`, `lastRemediationAt`, stabilize pass id (commit SHA + gate verdict) so a freshly-`blocked`-with-budget phase changes signature before the breaker can trip
  - **R-IDs:** R7
- [ ] 2.3 Consolidated halt + non-convergence escalation (R8)
  - **File:** `scripts/wave_failure.py`
  - **Expected:** budget exhaustion emits one consolidated legitimate halt with `resumeCommand`; early human-halt when the same verify-failure cause repeats across attempts; one environmental re-verify does not count against the regression budget
  - **R-IDs:** R8
- [ ] 2.4 Regression-remediation fixture (R18)
  - **File:** `scripts/test/run-regression-remediation-fixtures.sh`
  - **Expected:** `merge-run-next` on exit-20 reaches `remediate` on the next tick within budget without manual reset; freshly-`blocked` phase changes signature; exhaustion emits one halt
  - **R-IDs:** R18
- [ ] 2.5 Propagate + docs (R20, R21)
  - **File:** `core/` mirror, dist, `core/commands/sw-stabilize.md`, `core/skills/stabilize-loop/SKILL.md`
  - **Expected:** parity/emitter green; deliver-loop-initiated remediation documented
  - **R-IDs:** R21

### 3. Parallel-merge batch safety (R9–R12) — L

Prevent avoidable collisions, enforce whole-batch completion before any merge, auto-resolve deterministic
conflicts only.

- [ ] 3.1 Generator-output contention edges (R9)
  - **File:** `scripts/wave_deliver.py`, `scripts/planning_paths.py`
  - **Expected:** golden-manifest / `dist/**` / generated-mirror touches are contention edges; any phase invoking `generate` is treated as touching the full declared generator-output set
  - **R-IDs:** R9
- [ ] 3.2 Strict whole-batch completion + atomic merge (R10)
  - **File:** `scripts/wave_deliver_loop.py` (`compute_next_action`), `scripts/wave_merge.py`
  - **Expected:** no member merges until all batch members publish a *validated* terminal `status.json` (R13–R14); never enqueue a lone ready member early; batch merge atomic w.r.t. integration tip (freeze HEAD at `collect-all-ready` or rebase-before-exec; halt if integration moves mid-batch)
  - **R-IDs:** R10
- [ ] 3.3 Deterministic merge ordering / contention serialization (R11)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** ready members enqueued in deterministic phase-id order; if co-waving of contended phases remains possible, pre-enqueue contended-artifact check serializes them
  - **R-IDs:** R11
- [ ] 3.4 Deterministic-conflict auto-regen (R12)
  - **File:** `scripts/wave_merge.py`, `core/sw-reference/deterministic-regen-paths.json`
  - **Expected:** conflicts confined to the allowlist (golden manifest, `dist/**`, generated mirrors) auto-resolve by regenerate-and-restage within `deliver.deterministicConflict.maxAttempts` (default 1, max 2); only when paths trace to a single source preimage; determinism gate (identical re-run hash + golden parity) before restage; scoped to orchestrator worktree; semantic/multi-preimage conflicts halt
  - **R-IDs:** R12
- [ ] 3.5 Parallel-merge fixture (R18)
  - **File:** `scripts/test/run-parallel-merge-safety-fixtures.sh`
  - **Expected:** a batch sharing a golden-manifest touch never merges a member early, merges in deterministic order, avoids the collision via contention, auto-resolves a deterministic conflict, and halts on a seeded semantic conflict
  - **R-IDs:** R18
- [ ] 3.6 Propagate + docs (R20, R21)
  - **File:** `core/` mirror, dist, `core/commands/sw-deliver.md`, `docs/guides/workflows.md`
  - **Expected:** parity/emitter green; whole-batch + auto-resolve behavior documented
  - **R-IDs:** R20

### 4. Terminal-status integrity + recovery (R13–R17) — L

Make terminal `status.json` provenance-stamped, validity-checked, and recoverable; never trust hand-authored
status; re-verify live host evidence at merge.

- [ ] 4.1 Provenance marker emission (R13)
  - **File:** `scripts/ship-phase-status.py`
  - **Expected:** deterministic content-hash marker over canonical fields (`verdict`, `phase`, `head`, gate-subset, `shipSteps`-checksum; excluding `writtenAt`); driver rejects status lacking a valid marker
  - **R-IDs:** R13
- [ ] 4.2 Validity check + live-host-evidence re-verification (R14)
  - **File:** `scripts/wave_merge.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** validate terminal `verdict`, full 40-char head SHA == tip, parseable gate JSON; terminal acceptance + merge enqueue re-verify live host evidence (open PR + `check-gate`/`checks-status` green on current head); embedded gate JSON diagnostic-only; resolve multiple status copies by head-SHA/`writtenAt`, not path precedence; forged `merge-ready-green` rejected
  - **R-IDs:** R14
- [ ] 4.3 `stuck-stale` classification (R15)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** classify `stuck-stale` only on head-SHA equality across branch tip / PR head / gate-checked SHA / status.json, plus tip quiescence — never on "open PR + green CI on older tip"
  - **R-IDs:** R15
- [ ] 4.4 Budget-bounded canonical re-emit (R16)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/ship-phase-status.py`
  - **Expected:** re-emit re-derives verdict via canonical ship terminal steps; acquires the per-head lease and confirms no in-flight ship before atomic temp-write+rename; changes the state signature (re-emit counter); exhaustion is a legitimate halt
  - **R-IDs:** R16
- [ ] 4.5 Blessed recovery command (R17)
  - **File:** `core/commands/sw-ship.md`, `core/rules/sw-conductor.mdc`
  - **Expected:** recovery reuses `/sw-ship --phase-mode --from <terminal-step>`; rule points to it; invocations log actor metadata to `run.log`
  - **R-IDs:** R17
- [ ] 4.6 Status-integrity fixtures (R18)
  - **File:** `scripts/test/run-status-integrity-fixtures.sh`
  - **Expected:** non-terminal hand-authored status with green CI → `stuck-stale` → canonical re-emit (no `conductor:no-progress`/heartbeat-stale stall); forged `merge-ready-green` without valid marker / disagreeing with live evidence rejected; abbreviated/stale head SHA rejected
  - **R-IDs:** R18
- [ ] 4.7 Propagate + docs (R20, R21)
  - **File:** `core/` mirror, dist, `.sw/layout.md`, `core/sw-reference/layout.md`
  - **Expected:** parity/emitter green; provenance fields, lease files, recovery command documented in layout
  - **R-IDs:** R21

### 5. Cross-cutting invariants, CI enforcement & dogfood (R18–R22) — M

Wire all guards into CI, verify no invariant regressions, and confirm the four classes no longer recur.

- [ ] 5.1 Register fixtures as CI-required (R18, R20)
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml`
  - **Expected:** all four class fixtures registered `required`; workflow regenerated (PRD 016); `copy-to-core` parity + emitter-freshness + golden parity cover new `core/` keys
  - **R-IDs:** R20
- [ ] 5.2 Mechanical-sourcing audit (R19)
  - **File:** `scripts/test/run-mechanical-sourcing-fixtures.sh`
  - **Expected:** asserts no new parallel state store; all transitions flow through `wave_*.py` + durable `status.json`/state; no conductor prose re-implements state transitions
  - **R-IDs:** R19
- [ ] 5.3 Invariant-regression guard (R22)
  - **File:** `scripts/test/run-deliver-invariant-fixtures.sh`
  - **Expected:** human merge-to-`main` gate, secret-scan push chokepoint, scoped-lock / single-flight merge invariants, and frozen-doc/CI gates all unchanged
  - **R-IDs:** R22
- [ ] 5.4 Operator-doc sweep (R21)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/conductor/SKILL.md`, `core/skills/deliver/SKILL.md`, `docs/guides/workflows.md`, `docs/guides/configuration.md`
  - **Expected:** single-flight ship, regression routing, whole-batch + deterministic-conflict auto-resolve, status provenance + recovery documented as acceptance
  - **R-IDs:** R21
- [ ] 5.5 Dogfood validation (SC1–SC6)
  - **File:** (validation step — no new file)
  - **Expected:** one `/sw-deliver` run under `orchestration.planPolicy: proposed` reaches terminal gate with zero manual `status.json` edits and zero duplicate phase PRs; SC1–SC6 confirmed (go/no-go for widening `proposed`)
  - **R-IDs:** R22

## Relevant Files

- `scripts/wave_deliver_loop.py` — conductor driver: dispatch discipline, signature, routing, stuck-stale, re-emit.
- `scripts/wave_merge.py` — merge queue: whole-batch gating, deterministic order, auto-regen, live-evidence.
- `scripts/wave_phase_pr.py` — phase-mode PR idempotency + base pinning + supersede.
- `scripts/wave_lock.py` / `scripts/wave.sh` — per-head ship lease.
- `scripts/wave_failure.py` — remediation routing + consolidated halt.
- `scripts/wave_deliver.py` / `scripts/planning_paths.py` — plan-time contention edges.
- `scripts/ship-phase-status.py` — provenance marker emission + canonical re-emit.
- `core/sw-reference/pr-test-plan.manifest.json` + `.github/workflows/pr-test-plan-ci.yml` — CI registration.
- `core/commands/`, `core/skills/`, `core/rules/`, `docs/guides/`, `.sw/layout.md` — operator-facing docs (R21).

## Notes

- All fixtures are offline/deterministic with host-fixture stubs; live Task/PR concurrency is dogfood-validated, not CI-blocking.
- New `core/` scripts/config keys propagate to `dist/cursor` and `dist/claude-code` via `copy-to-core` + `generate --all` (R20).
- Phase 3 depends on Phase 4 because R10 batch completeness is the R13–R14 validated-status check; Phase 4 depends on Phase 1 because R16 re-emit acquires the R2 per-head lease.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 4 |
| 4 | 1 |
| 5 | 2, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.2 | conductor-single-ship-in-turn |
| R2 | 1.1 | per-head-lease-heartbeat-steal |
| R3 | 1.3 | pr-idempotency-toctou-one-pr |
| R4 | 1.4 | phase-pr-base-pin-from-state |
| R5 | 1.5 | takeover-superseded-close-by-branch |
| R6 | 2.1 | verify-failed-routes-bounded-stabilize |
| R7 | 2.2 | blocked-budget-signature-distinct |
| R8 | 2.3 | remediation-exhaustion-consolidated-halt |
| R9 | 3.1 | contention-generator-output-separation |
| R10 | 3.2 | whole-batch-no-early-merge-atomic |
| R11 | 3.3 | deterministic-merge-order-serialized |
| R12 | 3.4 | deterministic-conflict-autoregen-single-preimage |
| R13 | 4.1 | provenance-marker-emit-canonical-fields |
| R14 | 4.2 | forged-status-rejected-live-evidence |
| R15 | 4.3 | stuck-stale-sha-equality-quiescence |
| R16 | 4.4 | canonical-reemit-under-lease-atomic |
| R17 | 4.5 | recovery-command-reuses-ship-phase-mode |
| R18 | 1.6 | dual-ship-exactly-one-pr |
| R19 | 5.2 | no-new-parallel-state-store |
| R20 | 5.1 | fixtures-ci-required-parity-green |
| R21 | 5.4 | operator-docs-updated-as-acceptance |
| R22 | 5.3 | invariant-gates-unchanged |
