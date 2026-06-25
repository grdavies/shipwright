---
date: 2026-06-25
topic: deliver-autonomy-hardening
prd: docs/prds/007-deliver-autonomy-hardening/007-prd-deliver-autonomy-hardening.md
frozen: true
frozen_at: 2026-06-25
---

# Tasks — PRD 007 Structured autonomy hardening

Generated from the frozen PRD `007-prd-deliver-autonomy-hardening.md` (effective union R1–R58).
Phases are dependency-ordered; foundational floor/state phases land first.

## Tasks

### 1. Branch-name conformance: floor fix + creation guard (S/M)

- [x] 1.1 Add a branch-name guard single-sourcing allowed types from `release-please-config.json` (R22, R25)
  - **File:** `scripts/branch-name-guard.sh`
  - **Expected:** reads `changelog-sections[].type`; exit 0 on a conforming `<type>/<slug>` name, non-zero with remediation otherwise; no `pf/` accepted
- [x] 1.2 Remove the `pf/<name>` default in `worktree.sh` and call the guard at provision (R23, R27)
  - **File:** `scripts/worktree.sh`
  - **Expected:** no `new_branch="${branch:-pf/$name}"`; provisioning without a conforming `--branch` derives a conforming name or fails closed — never mints `pf/`
- [x] 1.3 Conforming multi-feature derivation with single-sourced types (R24)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** item branches use a type prefix (default `feat/`) instead of `pf/{i}`; `VALID_TYPES` resolves from `release-please-config.json` (shared with the guard)
- [x] 1.4 Migrate existing `pf/` matchers and fixtures to the conforming scheme (R26)
  - **File:** `scripts/reconcile-status.sh`, `scripts/test/run-impl-fixtures.sh`, `core/skills/deliver/SKILL.md`, `core/skills/worktree/SKILL.md`
  - **Expected:** no `pf/` literals remain; impl fixtures pass against conforming names

### 2. Crash-safe durable state core (M)

- [x] 2.1 Atomic, corruption-detecting state read/write (R43)
  - **File:** `scripts/wave_state.py`
  - **Expected:** `write_json` = temp + `rename` + `fsync`; `read_json` distinguishes absent from corrupt and raises on corruption so callers halt (no silent `{}`)
- [x] 2.2 Lock liveness metadata + stale-lock reclaim (R44)
  - **File:** `scripts/wave_state.py`
  - **Expected:** lock records pid/host/`heartbeatAt`; a dead/stale-owner lock is reclaimable; a concurrently live lock is refused
- [x] 2.3 Transactional, idempotent merge journal (R45)
  - **File:** `scripts/wave_state.py`, `scripts/wave_merge.py`
  - **Expected:** an interrupted merge replays on resume without double-merging or skipping a phase

### 3. Durable deliver-loop driver (L)

- [x] 3.1 `deliver-loop` verb with durable cursor + idempotent resume (R1, R2, R3)
  - **File:** `scripts/wave.sh`, `scripts/wave_deliver.py`
  - **Expected:** one entrypoint runs plan→provision→dispatch→collect→merge→forward-merge→teardown→terminal; persists `currentWave`/`nextAction`/per-phase status; auto-detects and resumes an in-progress run from state alone
- [x] 3.2 Remove manual handoff; wire `doc.afterTasks` directly to the driver (R4, R5)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/deliver/SKILL.md`, `core/commands/sw-doc.md`
  - **Expected:** no `cd <worktree>` → `/sw-gaps…` prose emitted while progress is possible; `auto`/`confirm` hand straight to `deliver-loop`
- [x] 3.3 Advance solely from durable per-phase status (R7)
  - **File:** `scripts/wave.sh`, `scripts/ship-phase-status.sh`
  - **Expected:** each phase `/sw-ship` runs phase-mode and writes machine-readable status; the driver never advances from chat output
- [x] 3.4 Bounded remediation, blast-radius siblings, clean terminal + consolidated blocker (R8, R9, R10, R12)
  - **File:** `scripts/wave_deliver.py`, `scripts/wave.sh`
  - **Expected:** blocked phase gets bounded remediation then halts; independent siblings continue; run ends merge-ready or one consolidated blocker report
- [x] 3.5 Configurable remediation budget, default 2 (R11)
  - **File:** `workflow.config.json` (schema + example), `scripts` setup seeding
  - **Expected:** `deliver.remediation.maxAttempts` present; absent key → default 2
- [x] 3.6 Heartbeat + per-phase timeout watchdog (R46)
  - **File:** `scripts/wave.sh`, `scripts/wave_state.py`
  - **Expected:** heartbeat each transition; stale heartbeat or exceeded timeout converts a hung/crashed run into a consolidated blocker

### 4. Orchestrator branch ownership + single spec-seed (M)

- [x] 4.1 Orchestrator owns a non-detached `<type>/<slug>`; primary asserted off; dirty-primary fails closed (R55, R40)
  - **File:** `scripts/wave_lifecycle.py`
  - **Expected:** orchestrator worktree checks out the branch non-detached; primary checkout asserted off it; dirty primary on the branch → fail closed with remediation; phase merges advance the ref directly (no manual ff)
- [x] 4.2 Single idempotent spec-seed owner for both entry paths (R6, R57)
  - **File:** `scripts/wave.sh` (spec-seed helper), `core/commands/sw-doc.md`
  - **Expected:** create/resolve `<type>/<slug>`; commit frozen `docs/prds/<n>-<slug>/` onto it only if absent; never `main`; `/sw-doc` afterTasks calls the same helper

### 5. Local phase-mode merge-queue mechanics (M)

- [x] 5.1 `status collect` resolves the phase-worktree status path directly (R38)
  - **File:** `scripts/wave.sh`, `scripts/wave_merge.py`
  - **Expected:** reads `<phase-worktree>/.cursor/sw-deliver-runs/<phase>/status.json` — no manual copy to the orchestrator root
- [x] 5.2 No-PR local-merge path; branch on PR presence; honor gate/barrier (R39, R54)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** `merge run-next` uses `check-gate.sh` when a PR exists, else a local-evidence path (per-phase merge-ready-green + post-merge incremental verify); never fails on "no open PR"
- [x] 5.3 Bind phase status to head SHA (R47)
  - **File:** `scripts/ship-phase-status.sh`, `scripts/wave_merge.py`
  - **Expected:** `status.json` records the phase head SHA; a SHA-mismatched status cannot authorize a merge

### 6. Step-granular per-phase resume (M)

- [x] 6.1 Persist `/sw-ship` step-level state; resume mid-chain (R58)
  - **File:** `core/commands/sw-ship.md`, `scripts/ship-phase-status.sh`, `scripts/shipwright-state.sh`
  - **Expected:** current/last step + attempt counters persisted per phase; a fresh agent resumes a phase mid-`/sw-ship` from state instead of restarting the chain

### 7. Task-document currency (M)

- [x] 7.1 Checkbox-only progress writer + non-checkbox-edit guard (R13, R14)
  - **File:** `scripts/tasks-progress.sh`
  - **Expected:** toggles `[ ]`↔`[x]` only; rejects any non-checkbox diff (text/R-IDs/structure/frontmatter); exposes a shared `is_checkbox_only_diff` predicate
- [x] 7.2 Frozen-guard checkbox carve-out (R48)
  - **File:** `scripts/check-frozen.sh`, `core/hooks/pre-commit-frozen.sh`
  - **Expected:** both guards permit a checkbox-only diff to a `frozen: true` task file (sharing the 7.1 predicate); all other frozen edits still rejected; no `--no-verify`
- [x] 7.3 Durable per-task completion ledger (R49)
  - **File:** `scripts/wave_state.py`, `scripts/tasks-currency-gate.sh`
  - **Expected:** per-task/per-phase completion recorded durably; gate compares checkboxes to the ledger, distinguishing partial from stale
- [x] 7.4 Currency gate hard-block + in-loop commit (R15, R16)
  - **File:** `scripts/tasks-currency-gate.sh`, `scripts/wave.sh`
  - **Expected:** divergence hard-blocks the terminal merge gate; checkbox updates committed on the feature branch in-loop

### 8. Pre-merge compounding + completion semantics (M)

- [x] 8.1 Pre-merge compound-ship mode; commit file outputs; memory not committed (R17, R18, R19)
  - **File:** `core/commands/sw-compound-ship.md`, `scripts/wave.sh`
  - **Expected:** full chain runs pre-merge; status/COMPLETION-LOG/CHANGELOG/learnings committed on the branch; memory writes run via `memory-preflight`, not committed; provider unreachable fails closed
- [x] 8.2 Rule-class memory promotion stays human-gated (R21)
  - **File:** `core/commands/sw-compound-ship.md`
  - **Expected:** no auto-promotion of rule-class memory inside the loop
- [x] 8.3 `completed-pending-merge` sub-state; completion gated on merge detection; suggest cleanup (R20, R31, R53)
  - **File:** `scripts/reconcile-status.sh`, `scripts/wave_state.py`, `scripts/wave.sh`
  - **Expected:** INDEX `complete` flip + resume terminal verdict gated on actual merge detection; declined merge never reports merged; loop prints a one-line `/sw-cleanup` suggestion when merge detected

### 9. Secret-safety guardrails (M)

- [x] 9.1 Secret scan at every workflow push chokepoint (R41, R50)
  - **File:** `scripts/secret-scan.sh`, `core/commands/sw-pr.md`, `core/commands/sw-stabilize.md`
  - **Expected:** scan runs before every push (incl. `sw-pr`'s first push); a match blocks the push with remediation
- [x] 9.2 Single-sourced patterns + allowlist + fail-closed (R51)
  - **File:** `scripts/secret-scan.sh`, shared pattern module with `scripts/memory_redact.py`
  - **Expected:** deny-set is a superset of `memory_redact.py` coverage; allowlist keeps scanner fixtures/examples pushable; scan error fails closed
- [x] 9.3 Mechanical range-scoped redaction guard + rule (R42, R52)
  - **File:** `scripts/redaction-guard.sh`, `rules/sw-redaction-scope.mdc`
  - **Expected:** a bare-branch `filter-branch` rewriting shared history is mechanically refused; range-scoped redaction required

### 10. `/sw-cleanup` command (M)

- [x] 10.1 `/sw-cleanup` command + script: dry-run + confirm + report (R28, R29, R33)
  - **File:** `core/commands/sw-cleanup.md`, `scripts/cleanup.sh`
  - **Expected:** enumerates merged local/remote branches, stale worktrees, completed run-state; dry-run default; deletes only after confirm; emits removed/protected report
- [x] 10.2 Protections + no `rm -rf` (R30, R32)
  - **File:** `scripts/cleanup.sh`
  - **Expected:** protects current/default/unmerged branches, active/locked worktrees, in-flight deliver runs; uses `git worktree remove`/`prune` only
- [x] 10.3 Squash-aware merge detection + shared-state guards (R56)
  - **File:** `scripts/cleanup.sh`
  - **Expected:** squash-merged branches detected (patch-id / `git cherry` / host status); indeterminate status fails closed; remote deletion guarded
- [x] 10.4 Register in plugin manifest under the `sw-` contract (R34)
  - **File:** `.cursor-plugin/plugin.json`, `core/commands/sw-cleanup.md`
  - **Expected:** command registered; description states scope + explicit non-goals

### 11. Fixtures, docs, dist propagation (M)

- [x] 11.1 Fixture suite for all new behaviors (R36)
  - **File:** `scripts/test/run-deliver-fixtures.sh` (+ new fixture dirs)
  - **Expected:** every fixture named in the PRD Testing Strategy table exists and passes
- [x] 11.2 Documentation updates (R37)
  - **File:** `docs/guides/*`, `rules/sw-naming.mdc`, relevant command/skill docs
  - **Expected:** durable autonomy contract, pre-merge compounding, branch-type policy, `/sw-cleanup`, merge-queue mechanics (R38–R40), secret-safety (R41–R42) documented; presence asserted by a fixture
- [x] 11.3 Emitter propagation + freshness gate (R35)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 1, 2 |
| 4 | 1, 3 |
| 5 | 3, 4 |
| 6 | 3 |
| 7 | 2, 3 |
| 8 | 3, 5 |
| 9 | none |
| 10 | 1 |
| 11 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 3.1 | deliver-loop-resume-from-state |
| R2 | 3.1 | deliver-loop-resume-from-state |
| R3 | 3.1 | deliver-loop-resume-from-state |
| R4 | 3.2 | deliver-loop-no-manual-handoff |
| R5 | 3.2 | deliver-loop-no-manual-handoff |
| R6 | 4.2 | deliver-spec-seed-feature-branch |
| R7 | 3.3 | deliver-advance-from-status-only |
| R8 | 3.4 | deliver-blocker-clean-halt |
| R9 | 3.4 | deliver-blocker-clean-halt |
| R10 | 3.4 | deliver-blocker-clean-halt |
| R11 | 3.5 | deliver-remediation-maxattempts-default |
| R12 | 3.4 | deliver-blocker-clean-halt |
| R13 | 7.1 | tasks-checkbox-currency |
| R14 | 7.1 | tasks-progress-nonckbox-reject |
| R15 | 7.4 | tasks-currency-gate-block |
| R16 | 7.4 | tasks-checkbox-currency |
| R17 | 8.1 | compound-ship-premerge-commit |
| R18 | 8.1 | compound-ship-premerge-commit |
| R19 | 8.1 | compound-ship-premerge-commit |
| R20 | 8.3 | completion-pending-merge-decline |
| R21 | 8.2 | compound-ship-rule-class-gated |
| R22 | 1.1 | branch-name-guard-floor |
| R23 | 1.2 | branch-name-guard-floor |
| R24 | 1.3 | branch-name-guard-multifeature |
| R25 | 1.1 | branch-name-guard-creation |
| R26 | 1.4 | pf-matcher-migration |
| R27 | 1.2 | branch-name-guard-floor |
| R28 | 10.1 | cleanup-dry-run-default |
| R29 | 10.1 | cleanup-dry-run-default |
| R30 | 10.2 | cleanup-protects-inflight |
| R31 | 8.3 | deliver-suggest-cleanup-on-merge |
| R32 | 10.2 | cleanup-protects-inflight |
| R33 | 10.1 | cleanup-dry-run-default |
| R34 | 10.4 | cleanup-registered |
| R35 | 11.3 | emitter-freshness-007 |
| R36 | 11.1 | run-deliver-fixtures.sh (full suite) |
| R37 | 11.2 | docs-autonomy-contract-presence |
| R38 | 5.1 | status-collect-phase-path |
| R39 | 5.2 | merge-run-next-no-pr |
| R40 | 4.1 | primary-ref-autosync |
| R41 | 9.1 | secret-scan-prepush |
| R42 | 9.3 | redaction-range-scoped-guard |
| R43 | 2.1 | state-write-atomic-crash |
| R44 | 2.2 | lock-stale-reclaim |
| R45 | 2.3 | merge-journal-idempotent-replay |
| R46 | 3.6 | driver-heartbeat-timeout-halt |
| R47 | 5.3 | status-sha-freshness |
| R48 | 7.2 | frozen-guard-allows-checkbox |
| R49 | 7.3 | currency-gate-vs-ledger |
| R50 | 9.1 | secret-scan-at-sw-pr-push |
| R51 | 9.2 | secret-patterns-single-source-allowlist |
| R52 | 9.3 | redaction-mechanical-guard |
| R53 | 8.3 | completion-pending-merge-decline |
| R54 | 5.2 | merge-run-next-pr-vs-local |
| R55 | 4.1 | orchestrator-owns-branch |
| R56 | 10.3 | cleanup-squash-merge-aware |
| R57 | 4.2 | spec-seed-single-owner-idempotent |
| R58 | 6.1 | phase-resume-mid-chain |
