---
prd: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
date: 2026-07-01
topic: deliver-concurrency-cwd-terminal-robustness
frozen: true
frozen_at: 2026-07-01
amendment_union: A1-hook-state-worktree-alignment, A2-unregistered-parent-model-tier-and-gap-004-closure, A3-wave-terminal-docs-currency-gate-argv-contract, A4-resume-reconcile-unpushed-local-merge-ground-tip, A5-deliver-verify-fixture-tree-immutability
visibility: public
---
# Tasks — PRD 050 Deliver-loop concurrency, worktree/cwd safety & terminal-finalize robustness

Single-pass task list from the frozen PRD 050 spec union (R1–R54; parent R1–R19 + amendment A1 R20–R33 + amendment A2 R34–R42 + amendment A3 R43–R46 + amendment A4 R47–R50 + amendment A5 R51–R54;
decisions D6–D8, D-A1-1–D-A1-4). Phases mirror the PRD Rollout Plan (Thread A → B/C parallel-eligible → D →
CI/gap verification). Amendment A1 tasks (1.6–1.9) roll into Thread A per A1 rollout note. No implementation
starts until the `doc.afterTasks` boundary.

## Tasks

### 1. Thread A — Primary-checkout & cwd safety (L)

Shared primary-checkout guard, cwd-correct freeze-commit/spec-seed, conductor contract parity, scoped run.log,
and concurrency regression fixtures.

- [ ] 1.1 `primary_checkout_guard` module + call-site wiring (R1, R2, D6)
  - **File:** `scripts/primary_checkout_guard.py`, `scripts/wave_lifecycle.py`, `scripts/check-frozen.py`, `scripts/wave_spec_seed.py`, `.sw/layout.md`
  - **Expected:** shared `(resolved_root, artifact_branch)` guard fails closed when root equals primary checkout and a dedicated worktree exists for the artifact branch; `freeze-commit` and `cmd_spec_seed` resolve root from `Path.cwd()` (not `SCRIPT_DIR.parent`); documented convention for future call sites in layout
  - **R-IDs:** R1, R2
- [ ] 1.2 Cross-run primary-checkout advisory lock (R6, D7)
  - **File:** `scripts/wave_lifecycle.py`, `scripts/primary_checkout_guard.py`
  - **Expected:** lock acquired before any `git checkout` against primary checkout in `assert_primary_off_target`; concurrent acquire fails closed with remediation message; implementer selects lock primitive per D7
  - **R-IDs:** R6
- [ ] 1.3 Conductor cwd contract + emitter parity (R3)
  - **File:** `core/skills/conductor/SKILL.md`, `scripts/build-chain-sync.py`
  - **Expected:** remove "or repo root with state synced" escape hatch; mandatory-provisioning contract matches `core/commands/sw-deliver.md` R53; `build-chain-sync.py` run before phase ship
  - **R-IDs:** R3
- [ ] 1.4 Slug-scoped deliver run.log (R4, D8)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/wave.py`, `.sw/layout.md`
  - **Expected:** migrate shared `.cursor/sw-deliver-runs/run.log` to `.cursor/sw-deliver-runs/run.<slug>.log`; layout durable-artifacts table updated
  - **R-IDs:** R4
- [ ] 1.5 Thread A regression fixtures (R5, R6)
  - **File:** `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `freeze-commit-cwd-forced-primary-fails-closed` and `deliver-provision-does-not-mutate-concurrent-primary-checkout` pass offline
  - **R-IDs:** R5, R6
- [ ] 1.6 Hook-state worktree root alignment (R20, R21, R22, TR14)
  - **File:** `scripts/worktree_root.py`, `core/hooks/sw_hook_util.py`, `core/hooks/before_task_dispatch.py`, `core/hooks/before-submit-guardrails.py`, `platforms/cursor/hook_adapter.py`, `scripts/build-chain-sync.py`
  - **Expected:** `is_shipwright_worktree()` recognizes `.sw-worktrees/*` and non-primary `git worktree list` entries; `workspace_root(payload)` prefers cwd git toplevel when valid cwd + recognized worktree + differs from `workspace_roots[0]`; all hook-state consumers use `workspace_root()` only; `build-chain-sync.py` run before ship
  - **R-IDs:** R20, R21, R22, R32
- [ ] 1.7 Script-side hook root mismatch guard (R25, R26, TR15)
  - **File:** `scripts/wave_memory_prework.py`, `scripts/wave_preflight.py`
  - **Expected:** fail closed with `move_agent_to_root` remediation when cwd toplevel ≠ primary and R21 false; silent when R20 alignment applies
  - **R-IDs:** R25, R26
- [ ] 1.8 Operator contract + layout docs (R23, R24, R31, TR16)
  - **File:** `core/commands/sw-doc.md`, `core/commands/sw-worktree.md`, `core/skills/git-workflow/SKILL.md`, `scripts/docs_worktree.py`, `.sw/layout.md`
  - **Expected:** docs document `move_agent_to_root` escape hatch vs R20 mechanical path; `docs_worktree.py` provision/resume JSON includes `nextSteps` (`cd`, `move_agent_to_root`, prework example); layout distinguishes deliver durable state (repo-root) vs hook ephemeral state (R20-resolved root)
  - **R-IDs:** R23, R24, R31
- [ ] 1.9 Hook-state alignment regression fixtures (R27–R30, TR17)
  - **File:** `scripts/test/run_hook_worktree_alignment_fixtures.py` (or extend `run_memory_prework_fixtures.py`), `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `hook-state-worktree-cwd-alignment`, `hook-state-dispatch-preflight-worktree-alignment`, `hook-state-primary-no-false-positive`, `hook-state-ambiguous-worktree-fail-closed` pass offline
  - **R-IDs:** R27, R28, R29, R30

### 1.10 gap-004 Defect A/C fixture registration (S)

Register existing regression fixtures; code already on `main`.

- [ ] 1.10 Register bash-py and git-push chokepoint fixtures (R34, R35, R36)
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml`, `scripts/zero-shell-guard.py`
  - **Expected:** `bash-py-invocation-guard.test` and `git-push-secret-scan-chokepoint.test` registered `required`; workflow regenerated; `find_bash_py_invocations` remains in zero-shell issue list
  - **R-IDs:** R34, R35, R36

### 1.11 gap-004 Defect B — unregistered parent model tier (M)

Dispatch binding advisory pass + optional config fallback (A2 Thread F).

- [ ] 1.11 Refactor dispatch-check tier resolution (R37–R39, TR18)
  - **File:** `scripts/dispatch-check.py`, `core/sw-reference/config.schema.json`, `.cursor/workflow.config.example.json`
  - **Expected:** non-reviewer/non-panel dispatches pass with advisory when parent not in `models.tiers`; reviewer/panel paths fail-closed unless `dispatch.unregisteredParentModelTier` set; invalid fallback → `binding:invalid-fallback-tier`
  - **R-IDs:** R37, R38, R39
- [ ] 1.12 Dispatch-binding doc + fixtures (R40–R42, TR20–TR21)
  - **File:** `core/rules/sw-subagent-dispatch.mdc`, `core/commands/sw-doc.md`, `scripts/test/run_dispatch_binding_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** docs updated + build-chain-sync; `dispatch-unregistered-parent-delegated-atomic-passes` and `dispatch-unregistered-parent-reviewer-fails-closed` registered and green
  - **R-IDs:** R40, R41, R42
- [ ] 1.13 gap-004 closure at ship (A2 Rollout step 4)
  - **File:** `docs/prds/gap/gap-004-dispatch-binding-preflight-broken-bash-invokes-p/`, `docs/prds/INDEX.md`
  - **Expected:** gap-004 unit `status: resolved` referencing PRD 050 A2 only after R34–R42 fixtures green — not narrative closure
  - **R-IDs:** R34–R42


### 2. Thread B — Deliver-loop provisioning & stall classification (L)

Orphan worktree adopt/teardown, dispatch-ship precondition, differentiated no-progress stalls, stale
IN_PROGRESS check handling, and phase-mode ship polling.

- [ ] 2.1 Orphan phase worktree adopt-or-teardown (R7, R8)
  - **File:** `scripts/wave_lifecycle.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** `provision-phase` adopts matching orphan into `phaseWorktrees` or teardown+retry; `dispatch-ship` refuses until phase path recorded in state; no identical-`nextAction` repeat
  - **R-IDs:** R7, R8
- [ ] 2.2 Differentiated stall causes + auto-recovery (R9, R10)
  - **File:** `scripts/status_integrity.py` (or sibling), `scripts/wave_deliver_loop.py`
  - **Expected:** no-progress classifier distinguishes orphan-worktree-adopt-pending, merge-queue-wait, external-CI-wait before `budgetHalt`; `noProgressStreak` resets when blocking predicate changes
  - **R-IDs:** R9, R10
- [ ] 2.3 Stale IN_PROGRESS + phase-mode poll path (R11, R12)
  - **File:** `scripts/check-gate.py`, `scripts/wave_deliver_loop.py` (phase-mode ship)
  - **Expected:** bounded-TTL stale `IN_PROGRESS` with workflow-run `conclusion: success` settles green or explicit environmental exit 10; blocking `gh pr checks --watch` removed/replaced with `check-gate.py` backoff poll
  - **R-IDs:** R11, R12
- [ ] 2.4 Thread B regression fixtures (R7–R12)
  - **File:** `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `orphan-phase-worktree-adopt-or-teardown`, `no-progress-differentiated-stall-causes`, `stale-in-progress-success-check-gate-green` pass offline
  - **R-IDs:** R7, R9, R11

### 3. Thread C — Terminal-finalize robustness (M)

Host-API-first finalize, post-merge resume without live feature branch, PRD 046 A2 hook, and terminal PR
body template validation.

- [ ] 3.1 Host-API-first finalize-completion (R13, R14)
  - **File:** `scripts/wave_terminal.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** `finalize-completion` / `completion check-merge` succeed when host confirms merge via `terminalPr.number` even if branch-scoped durable state cleared; resume from `main` post-merge without live feature-branch target
  - **R-IDs:** R13, R14
- [ ] 3.2 PRD 046 A2 living-docs hook (R15)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** call `living-docs reconcile --commit` at end of `finalize-completion` when entrypoint exists; feature-detection guarded fallback with logged cross-link when PRD 046 A2 not yet shipped
  - **R-IDs:** R15
- [ ] 3.3 Terminal PR body template pipeline (R16)
  - **File:** `scripts/wave_terminal.py`, `scripts/git_template_lib.py`
  - **Expected:** `terminal_pr_body()` routed through `render pr-body` / `validate pr-body` mirroring `docs_pr.py`; fail closed before `host_pr_create` on validation failure
  - **R-IDs:** R16
- [ ] 3.5 Terminal docs-currency-gate argv alignment (R43, TR22)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** `run_docs_currency_gate` invokes `docs-currency-gate.py` with four positional args (repo root, state root, state JSON, plan JSON); no `--state-root`-only invocation; fail-closed JSON error surfacing preserved
  - **R-IDs:** R43
- [ ] 3.6 gap-017 closure fixtures (R44–R46, TR23–TR24)
  - **File:** `scripts/test/fixtures/deliver-concurrency/`, `scripts/docs-currency-gate.py` (optional argparse shim), `core/sw-reference/pr-test-plan.manifest.json`, `docs/prds/gap/gap-017-wave-terminal-docs-currency-gate-invocation-uses/`
  - **Expected:** `terminal-docs-currency-gate-invocation-valid` registered and green; optional `--state-root` shim delegates to canonical path with deprecation advisory; gap-017 `status: resolved` only after fixtures green
  - **R-IDs:** R44, R45, R46

- [ ] 3.7 Resume-reconcile local-merge ground tip (R47–R48, TR25)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** `resume reconcile` promotes pending phases merged into `local_tip` when `remote_tip` is stale; demotion of `green-merged` rows still uses remote ground truth; `cause: resume:unpushed-local-merge` advisory on unpushed-local promotion path
  - **R-IDs:** R47, R48
- [ ] 3.8 gap-018 closure fixtures (R49–R50, TR26–TR27)
  - **File:** `scripts/test/run_deliver_fixtures.py`, `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`, `docs/prds/gap/gap-018-resume-reconcile-ignores-unpushed-local-phase-me/`
  - **Expected:** `resume-reconcile-unpushed-local-merge-promotes` registered and green; gap-018 `status: resolved` only after fixtures green
  - **R-IDs:** R49, R50

- [ ] 3.9 Subprocess JSON fail-payload forwarding (R55–R56, TR31–TR32)
  - **File:** `scripts/wave_lifecycle.py`, `scripts/wave_terminal.py`, `scripts/wave_failure.py` or new `scripts/wave_errors.py`
  - **Expected:** shared `fail_from_payload` (or `extra.pop("error", None)` contract) replaces unsafe `fail(..., **err)` at forward-merge, phase-teardown, materialize-provision, and `host_pr_create` call sites; grep sweep on deliver-surface wave modules
  - **R-IDs:** R55, R56
- [ ] 3.10 gap-021 closure fixtures (R57–R58, TR33)
  - **File:** `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`, `docs/prds/gap/gap-021-fail-spreads-json-error-dict-causing-duplica/`
  - **Expected:** `deliver-fail-payload-forwards-subprocess-error` registered and green; gap-021 `status: resolved` only after fixtures green
  - **R-IDs:** R57, R58

- [ ] 3.4 Thread C regression fixtures (R13–R16)
  - **File:** `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `finalize-resume-after-state-cleared-post-merge`, `terminal-pr-body-template-valid` pass offline
  - **R-IDs:** R13, R16

### 4. Thread D — Adjacent hygiene guards (S)

Capability fixture shell regression CI guard and all-private visibility freeze-time enforcement.

- [x] 4.1 Capability gateRef no-shell CI guard (R17)
  - **File:** `scripts/capability_trust.py` (or new CI script), `scripts/test/fixtures/capability-select/**`, `scripts/test/fixtures/capability-lint/**`
  - **Expected:** CI fails when `gateRef` points at `.sh` where canonical `.py` exists; restore six gap-014 fixtures to `.py` gateRef values
  - **R-IDs:** R17
- [x] 4.2 All-private visibility at freeze + spec-seed remediation (R18, R19)
  - **File:** `scripts/check-frozen.py`, `scripts/wave_spec_seed.py`, `core/commands/sw-freeze.md`, `core/commands/sw-tasks.md`
  - **Expected:** `/sw-tasks` freeze and `/sw-freeze` require `visibility: public` on git-tracked artifacts when `planning.visibilityProfile: all-private`; `assert_no_tracked_private_bodies` error points at feature branch not bare `main`
  - **R-IDs:** R18, R19
- [x] 4.3 Thread D regression fixtures (R17–R19)
  - **File:** `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `capability-gateref-no-shell`, `all-private-spec-seed-tracked-private-body` pass offline
  - **R-IDs:** R17, R18

- [x] 4.4 Deliver verify fixture-tree immutability (R51, TR28)
  - **File:** `scripts/test/_runner.py`, `scripts/test/run_*_fixtures.py` (deliver-verify call sites), `scripts/test/run_verify_bundle.py`
  - **Expected:** parallel-wave deliver verify uses ephemeral roots; tracked `scripts/test/fixtures/` unchanged in orchestrator worktree after verify
  - **R-IDs:** R51
- [x] 4.5 gap-019 closure doctor + fixtures (R52–R54, TR29–TR30)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/test/fixtures/deliver-concurrency/`, `core/sw-reference/pr-test-plan.manifest.json`, `docs/prds/gap/gap-019-parallel-deliver-verify-mutates-tracked-scripts-/`
  - **Expected:** pre-`merge-run-next` fixture-tree doctor fails closed with remediation; `deliver-verify-fixture-tree-immutable` registered and green; gap-019 `status: resolved` only after fixtures green
  - **R-IDs:** R52, R53, R54

### 5. Manifest registration + gap verification (S)

Register all nine PRD fixtures and verify gap schedule/resolve at ship.

- [ ] 5.1 Register all seventeen fixtures in pr-test-plan manifest
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml`
  - **Expected:** all eighteen named scenarios from PRD + A1 + A3 + A4 + A5 Testing Strategy registered `required` (nine parent + four A1 hook-state alignment + one A3 terminal docs-currency gate + one A4 resume-reconcile local merge + one A5 deliver-verify fixture-tree immutability + one A6 fail-payload forwarding); workflow regenerated if needed
  - **R-IDs:** R5, R6, R7, R9, R11, R13, R16, R17, R18, R27, R28, R29, R30, R44, R49, R53, R57
- [ ] 5.2 Gap flip verification at ship
  - **File:** `scripts/gap_backlog.py`, `scripts/docs-currency-gate.py`
  - **Expected:** `gap_backlog.py check` / `docs-currency-gate.py` confirm GAP-077, GAP-078, GAP-079, gap-005, gap-009–gap-015 show `resolved` after implementation ships (not narratively closed)
  - **R-IDs:** R1–R19
- [ ] 5.3 A1 feedback-signal gap flip (R33)
  - **File:** `docs/planning/gap/` (or `scripts/planning_gap_capture.py materialize), `scripts/gap_backlog.py`
  - **Expected:** gap unit for `feedback-hook-worktree-root-mismatch-2026-07-01` (`plugin-self`) flips to `resolved` referencing PRD 050 A1 only after R27–R30 fixtures green — not narrative closure
  - **R-IDs:** R33

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1 |
| 5 | 2, 3, 4 |

## Traceability

| R-ID | Task ref | Named test scenario | ZOMBIES checklist |
|------|----------|---------------------|-------------------|
| R1 | 1.1 | freeze-commit-cwd-forced-primary-fails-closed | Z, O, I, E |
| R2 | 1.1 | freeze-commit-cwd-forced-primary-fails-closed | Z, O, B, I |
| R3 | 1.3 | conductor-mandatory-provisioning-contract | O, I, E |
| R4 | 1.4 | slug-scoped-run-log-writes | O, M, I, S |
| R5 | 1.5 | freeze-commit-cwd-forced-primary-fails-closed | Z, O, E |
| R6 | 1.2, 1.5 | deliver-provision-does-not-mutate-concurrent-primary-checkout | O, M, I, E |
| R7 | 2.1, 2.4 | orphan-phase-worktree-adopt-or-teardown | O, B, I, S |
| R8 | 2.1 | orphan-phase-worktree-adopt-or-teardown | O, I, E |
| R9 | 2.2, 2.4 | no-progress-differentiated-stall-causes | O, M, I, S |
| R10 | 2.2 | no-progress-differentiated-stall-causes | O, S, I |
| R11 | 2.3, 2.4 | stale-in-progress-success-check-gate-green | O, B, I, E |
| R12 | 2.3 | stale-in-progress-success-check-gate-green | O, I, E |
| R13 | 3.1, 3.4 | finalize-resume-after-state-cleared-post-merge | Z, O, I, S |
| R14 | 3.1 | finalize-resume-after-state-cleared-post-merge | O, I, S |
| R15 | 3.2 | finalize-living-docs-reconcile-hook | O, I, E |
| R16 | 3.3, 3.4 | terminal-pr-body-template-valid | O, I, E |
| R17 | 4.1, 4.3 | capability-gateref-no-shell | O, M, I, E |
| R18 | 4.2, 4.3 | all-private-spec-seed-tracked-private-body | O, I, E |
| R19 | 4.2 | all-private-spec-seed-tracked-private-body | O, E, I |
| R20 | 1.6 | hook-state-worktree-cwd-alignment | O, B, I, E |
| R21 | 1.6 | hook-state-worktree-cwd-alignment | O, I, E |
| R22 | 1.6 | hook-state-worktree-cwd-alignment | O, I, E |
| R23 | 1.8 | hook-state-worktree-cwd-alignment | O, I, E |
| R24 | 1.8 | hook-state-worktree-cwd-alignment | O, I, E |
| R25 | 1.7 | hook-state-ambiguous-worktree-fail-closed | O, B, I, E |
| R26 | 1.7 | hook-state-worktree-cwd-alignment | O, I, E |
| R27 | 1.9 | hook-state-worktree-cwd-alignment | Z, O, I, E |
| R28 | 1.9 | hook-state-dispatch-preflight-worktree-alignment | Z, O, I, E |
| R29 | 1.9 | hook-state-primary-no-false-positive | Z, O, I, E |
| R30 | 1.9 | hook-state-ambiguous-worktree-fail-closed | O, B, I, E |
| R31 | 1.8 | hook-state-worktree-cwd-alignment | O, I, E |
| R32 | 1.6 | hook-state-worktree-cwd-alignment | O, I, E |
| R33 | 5.3 | hook-state-worktree-cwd-alignment | O, I, E |
| R34 | 1.10 | bash-py-invocation-guard | O, M, I, E |
| R35 | 1.10 | git-push-secret-scan-chokepoint | O, M, I, E |
| R36 | 1.10 | bash-py-invocation-guard | O, I, E |
| R37 | 1.11 | dispatch-unregistered-parent-delegated-atomic-passes | O, B, I, E |
| R38 | 1.11 | dispatch-unregistered-parent-reviewer-fails-closed | O, B, I, E |
| R39 | 1.11 | dispatch-unregistered-parent-reviewer-fails-closed | O, I, E |
| R40 | 1.12 | dispatch-unregistered-parent-delegated-atomic-passes | O, I, E |
| R41 | 1.12 | dispatch-unregistered-parent-delegated-atomic-passes | Z, O, I, E |
| R42 | 1.13 | dispatch-unregistered-parent-delegated-atomic-passes | O, I, E |
| R43 | 3.5 | terminal-docs-currency-gate-invocation-valid | O, B, I, E |
| R44 | 3.6 | terminal-docs-currency-gate-invocation-valid | Z, O, I, E |
| R45 | 3.6 | terminal-docs-currency-gate-invocation-valid | O, I, E |
| R46 | 3.6 | terminal-docs-currency-gate-invocation-valid | O, I, E |
| R47 | 3.7 | resume-reconcile-unpushed-local-merge-promotes | O, B, I, E |
| R48 | 3.7 | resume-reconcile-unpushed-local-merge-promotes | O, I, E |
| R49 | 3.8 | resume-reconcile-unpushed-local-merge-promotes | Z, O, I, E |
| R50 | 3.8 | resume-reconcile-unpushed-local-merge-promotes | O, I, E |
| R51 | 4.4 | deliver-verify-fixture-tree-immutable | O, M, I, E |
| R52 | 4.5 | deliver-verify-fixture-tree-immutable | O, B, I, E |
| R53 | 4.5 | deliver-verify-fixture-tree-immutable | Z, O, I, E |
| R54 | 4.5 | deliver-verify-fixture-tree-immutable | O, I, E |
| R55 | 3.9 | `deliver-fail-payload-forwards-subprocess-error` surfaces subprocess error, not TypeError |
| R56 | 3.9 | five lifecycle/terminal call sites use safe fail-payload forwarding |
| R57 | 3.10 | `deliver-fail-payload-forwards-subprocess-error` passes |
| R58 | 3.10 | gap-021 resolved after R55–R57 green |

## Relevant Files

- `scripts/primary_checkout_guard.py` — shared primary-checkout guard (Thread A).
- `scripts/wave_lifecycle.py`, `scripts/wave_deliver_loop.py` — provisioning, locks, stall classification.
- `scripts/check-frozen.py`, `scripts/wave_spec_seed.py` — cwd-correct freeze-commit/spec-seed.
- `scripts/check-gate.py`, `scripts/wave_terminal.py` — stale CI + terminal finalize/template.
- `scripts/status_integrity.py` — no-progress stall taxonomy.
- `core/skills/conductor/SKILL.md`, `.sw/layout.md` — operator contracts + durable-artifact docs.
- `core/sw-reference/pr-test-plan.manifest.json` — CI fixture registration.
- `scripts/worktree_root.py`, `core/hooks/sw_hook_util.py` — hook-state worktree alignment (A1 TR14).
- `scripts/wave_memory_prework.py`, `scripts/wave_preflight.py` — script-side root mismatch guard (A1 TR15).
- `scripts/docs_worktree.py` — provision/resume `nextSteps` (A1 R24).
- `scripts/dispatch-check.py` — unregistered parent model tier (A2 TR18).

## Notes

- TR10 (PRD 046 A2 hook) uses feature-detection — implementation must not block on PRD 046 landing.
- Thread B and C are parallel-eligible after Thread A per PRD Rollout Plan step 3–4.
- Phase 5 gap verification runs at ship; schedule flips occur at PRD freeze via `absorbs:` frontmatter.
- A1 tasks 1.6–1.9 ship alongside Thread A (1.1–1.5) per amendment A1 rollout; R20 relies on Cursor
  `preToolUse` `cwd` (DL-1 resolved — absent/empty cwd → R30 fail-closed + `move_agent_to_root`).
- Do not merge A1 hook-state alignment with PRD 049 `deliver_cwd_guard` (orthogonal primitives).
- A2 tasks 1.10–1.13 may ship before parent Thread A when unblocking `/sw-doc` Task delegation (A2 D-A2-4).
