---
date: 2026-07-01
topic: operator-worktree-contract-and-cwd-guard
prd: docs/prds/049-operator-worktree-contract-and-cwd-guard/049-prd-operator-worktree-contract-and-cwd-guard.md
frozen: true
frozen_at: 2026-07-01
visibility: public
---

# Tasks — PRD 049 Operator worktree contract & in-flight cwd guard

Single-pass task list from the frozen PRD 049 spec union (R1–R7). Phases mirror the PRD's Rollout Plan and
its Definition of done anti narrative-closure gate: documentation (R1/R2) and code (R3/R4/R7) land in
parallel-safe phases with disjoint files, the end-to-end contract fixture (R5) and the standalone
`gap_backlog.py` reschedule fix (TR4) follow, and gap closure (R6) is the terminal phase gated on every
prior fixture being registered **and** green — not narrative confidence.

## Tasks

### 1. Operator worktree contract documentation (M)

Publish the R1/R2 contract and reconcile the GAP-078 contradiction in `conductor/SKILL.md`.

- [ ] 1.1 Publish operator worktree contract in `.sw/layout.md` (R1)
  - **File:** `.sw/layout.md`
  - **Expected:** new diagram/table covering primary checkout, orchestrator worktree
    (`.sw-worktrees/<slug>-orchestrator`), phase worktrees (`.sw-worktrees/<slug>-phase-*`), and repo-root
    gitignored `.cursor/`; explicitly states `.cursor/` at repo root is conductor runtime, not feature
    implementation; states `status.json` copy direction is phase worktree → repo root (mirror) only, never a
    general root→worktree sync
  - **R-IDs:** R1
- [ ] 1.2 Echo contract in conductor/deliver skills + reconcile GAP-078 (R2)
  - **File:** `core/skills/conductor/SKILL.md`, `core/skills/deliver/SKILL.md`
  - **Expected:** skills state which checkout ship/execute run in, that repo-root `.cursor/` updates during
    deliver are expected, and tracked `main` must not accumulate implementation commits during a run; the
    existing "run `deliver-loop` from `.sw-worktrees/<slug>-orchestrator` (or repo root with state synced)"
    alternate-cwd language in `conductor/SKILL.md` is removed or reconciled so it no longer contradicts
    mandatory orchestrator provisioning (closes GAP-078); run `python3 scripts/build-chain-sync.py` after
    editing (emitter parity)
  - **R-IDs:** R2
- [ ] 1.3 Doc-currency fixture for R1/R2 sections (TR3)
  - **File:** `scripts/test/run_doc_currency_049_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `doc-currency-049-contract-sections` registered and green — asserts `.sw/layout.md` and the
    conductor/deliver skills carry the R1/R2 contract language and that the GAP-078 contradiction is gone
  - **R-IDs:** R1, R2

### 2. In-flight cwd guard + canonical state read (L)

Implement the fail-closed guard (R3/R7) and the terminal-step canonical state reader (R4), wired into their
minimum call-site surfaces.

- [ ] 2.1 Implement `deliver_cwd_guard.py` (R3, R7)
  - **File:** `scripts/deliver_cwd_guard.py`
  - **Expected:** `.py` module + thin CLI entrypoint (R7; matches `_sw.cli.run_module_main` convention, see
    `scripts/living-status-gap-resolve.py`); detects an in-flight run via `.cursor/sw-deliver-runs/index.json`
    + repo-root canonical state; fail-closed defined precisely — a missing/corrupt/unreadable index or state
    file is treated as "cannot rule out an in-flight run" (refuse), never as "no run detected"; falls back to
    a live scan via the existing `enumerate_scoped_runs` primitive when the cached index is stale or absent;
    `--allow-default-branch` is the only escape hatch (CI/fixture-only), logs its use, and is not reachable
    from an interactive operator command
  - **R-IDs:** R3, R7
- [ ] 2.2 Wire guard into R3's minimum surfaces
  - **File:** `scripts/wave_living_docs.py`, `scripts/reconcile.py`, `core/skills/retro/SKILL.md` (or its
    write-path script), `scripts/wave_deliver_loop.py`
  - **Expected:** `wave_living_docs --commit`, `reconcile.py reconcile`, `/sw-retrospective` write paths, and
    `wave_deliver_loop` manual living-doc reconcile suggestions all call `deliver_cwd_guard.py` and refuse
    (non-zero, remediation text) when run from the primary checkout on `defaultBaseBranch` while a deliver run
    for the repo is `verdict: running`
  - **R-IDs:** R3
- [ ] 2.3 Add `sync_canonical_state_read()` with skew threshold + conflict precedence (R4)
  - **File:** `scripts/wave_state.py`
  - **Expected:** new function hoists to `git_toplevel` itself, then calls the existing
    `resolve_state_path(git_toplevel)` (line ~285) — never a cwd-relative read; on `save_state`, mirrors to
    repo-root when `orchestratorWorktree.path` is set; single-sourced named constant for the dual-copy
    `updatedAt` skew threshold at **300 seconds** (strictly-greater-than refuses, equal-to passes); on a
    `verdict` conflict between repo-root and orchestrator-mirror copies, repo-root wins (mirror is advisory
    only)
  - **R-IDs:** R4
- [ ] 2.4 Wire `sync_canonical_state_read()` into terminal deliver actions (R4)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** `retrospective`, `terminal-ship`, and `all-phases-complete` actions call
    `sync_canonical_state_read()` before their existing logic, replacing any cwd-relative state read
  - **R-IDs:** R4
- [ ] 2.5 Fixtures: guard refusal + terminal state read (TR1, TR2)
  - **File:** `scripts/test/run_deliver_cwd_guard_fixtures.py`,
    `scripts/test/run_terminal_state_read_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** `deliver-cwd-guard-blocks-main-living-doc` (including the fail-closed-on-corrupt-index case)
    and `terminal-reads-repo-root-state-from-orchestrator-cwd` (including a skew-boundary case — >300s
    refuses, =300s passes — and a repo-root-vs-mirror `verdict` conflict case where repo-root wins) both
    registered and green
  - **R-IDs:** R3, R4

### 3. End-to-end operator contract fixture (S)

Prove the full contract, including the negative guard-refusal assertion this PRD's review added.

- [ ] 3.1 `deliver-worktree-contract` fixture incl. negative assertion (R5)
  - **File:** `scripts/test/run_deliver_worktree_contract_fixtures.py`,
    `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** after orchestrator provision + one `deliver-loop` tick, asserts repo-root scoped state is
    updated, the primary checkout remains on `defaultBaseBranch`, and no tracked files on `main` are modified
    — **and** attempts at least one R3-guarded surface from the primary checkout while the simulated run is
    `verdict: running`, asserting non-zero exit with remediation text (not merely absence-of-mutation)
  - **R-IDs:** R5

### 4. `gap_backlog.py` reschedule fix (S)

Independent, standalone script fix — a prerequisite for R6's `GAP-056` reschedule, not new design scope.

- [ ] 4.1 Add `--force` to `flip --schedule` (TR4)
  - **File:** `scripts/gap_backlog.py`
  - **Expected:** new `--force` flag on the `flip --schedule` subcommand rewrites `schedule` (status stays
    `scheduled`) for a matched row regardless of its current label; without `--force`, the existing
    no-op-on-mismatch behavior (only `open` rows get scheduled; a row already scheduled to a different label
    is left untouched) is preserved
  - **R-IDs:** R6
- [ ] 4.2 Fixture `gap-backlog-flip-schedule-force-reschedule` (TR4)
  - **File:** `scripts/test/run_gap_backlog_fixtures.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** proves `--force` reschedules a row already scheduled to a different label, and that
    omitting `--force` still no-ops (no accidental cross-PRD reschedule of an unrelated in-flight schedule)
  - **R-IDs:** R6

### 5. Gap closure + definition-of-done verification (S)

Terminal phase — gated on every fixture from phases 1–4 being registered **and** green, not on narrative
confidence (PRD Definition of done).

- [ ] 5.1 Verify Definition of done checklist before any flip (Goals 5 / Definition of done)
  - **File:** `docs/prds/049-operator-worktree-contract-and-cwd-guard/049-prd-operator-worktree-contract-and-cwd-guard.md`
  - **Expected:** `deliver-cwd-guard-blocks-main-living-doc`, `terminal-reads-repo-root-state-from-orchestrator-cwd`,
    `deliver-worktree-contract` (with negative assertion), `doc-currency-049-contract-sections`, and
    `gap-backlog-flip-schedule-force-reschedule` are all registered in
    `core/sw-reference/pr-test-plan.manifest.json` and green; a repo-wide search for
    `deliver_cwd_guard`/`cwd_guard` and `sync_canonical_state_read` returns positive matches
  - **R-IDs:** R5, R6
- [ ] 5.2 Reschedule + resolve `GAP-056`; close `gap-006` (R6)
  - **File:** `docs/prds/GAP-BACKLOG.md`, `docs/prds/gap/gap-006-prd-033-marked-complete-but-a3-r37-r39-r40-r42-r/`,
    `docs/prds/INDEX.md`
  - **Expected:** `python3 scripts/gap_backlog.py flip --schedule --gaps GAP-056 --prd 049 --force` moves the
    `GAP-056` schedule pointer from `PRD 033 A3` to `PRD 049`; `python3 scripts/gap_backlog.py flip --resolve
    --prd 049` (or the PRD 048 automatic path, if shipped) flips it to `resolved — PRD 049`; only after this
    PRD's INDEX status legitimately reaches `complete`, `python3 scripts/planning-graph.py reconcile --commit`
    flips `gap-006`'s status to `resolved` referencing this PRD — never a hand-edit of the gap unit file;
    `gap_backlog.py check` and `docs-currency-gate.py` both show clean output
  - **R-IDs:** R6

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 2 |
| 4 | none |
| 5 | 1, 3, 4 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R1 | 1.1 | `.sw/layout.md` publishes the operator worktree contract table; `.cursor/` labeled conductor runtime, not implementation |
| R2 | 1.2 | conductor/deliver skills echo the contract; GAP-078's "or repo root with state synced" contradiction is gone |
| R3 | 2.1, 2.2 | guarded surface run from primary checkout on `defaultBaseBranch` during `verdict: running` refuses non-zero with remediation; corrupt/missing index also refuses (fail-closed) |
| R4 | 2.3, 2.4 | terminal deliver steps read canonical repo-root state via `resolve_state_path(git_toplevel)`; >300s skew refuses, =300s passes; repo-root wins on `verdict` conflict |
| R5 | 3.1 | end-to-end contract fixture proves state/branch/main invariants **and** guard refusal from the primary checkout during an in-flight run |
| R6 | 4.1, 4.2, 5.2 | `flip --schedule --force` reschedules `GAP-056` from `PRD 033 A3` to `PRD 049`; `--resolve` flips it to resolved; `gap-006` flips to resolved via reconciler only after INDEX `complete` |
| R7 | 2.1 | `deliver_cwd_guard.py` is a `.py` module (not `.sh`), per `rules/sw-python-first.mdc` |
