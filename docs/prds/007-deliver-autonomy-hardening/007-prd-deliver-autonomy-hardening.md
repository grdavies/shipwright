---
date: 2026-06-25
topic: deliver-autonomy-hardening
frozen: true
frozen_at: 2026-06-25
---

# PRD 007 — Structured autonomy hardening for `/sw-deliver`

## Overview

The `/sw-doc → /sw-deliver → /sw-ship` pipeline promises that, once planning starts under
`doc.afterTasks: auto`, the workflow runs unattended until the feature branch is **merge-ready** (or
halts in a cleanly-described, blocked state). In practice it does not: `/sw-deliver` and `/sw-ship` are
markdown-orchestrated procedures an agent must execute faithfully across a long, often-compacting
session. When context drops or a fresh agent resumes, the agent loses the thread and reverts to printing
a manual handoff (`cd <worktree>` → `/sw-gaps → /sw-verify → /sw-ship`), leaving the operator with an
in-flux repository.

This PRD replaces prose-dependent autonomy with a **durable, resumable, enforced contract**: a
state-machine driver that owns phase sequencing and advancement, bounded auto-remediation with a clean
terminal state, in-loop task-document currency, pre-merge compounding committed with the feature,
conformant branch naming, self-driving local merge-queue mechanics, secret-safety gates, and a safe
post-merge `/sw-cleanup`. It derives from the frozen brainstorm
`docs/brainstorms/2026-06-25-deliver-autonomy-hardening-requirements.md` (R1–R42) and the corroborating
PRD 005 deliver-run items in `docs/prds/GAP-BACKLOG.md`.

## Goals

1. A `doc.afterTasks: auto` run reaches a merge-ready terminal PR — or a single consolidated blocker
   report — without manual intervention unless genuinely necessary.
2. A fresh agent can resume an interrupted run from durable state to the same terminal outcome —
   including a run killed mid-flight (process crash) and a phase resumed mid-`/sw-ship` — or surface a
   consolidated blocker; corrupt state never silently becomes a divergent run, and an orphaned lock never
   deadlocks resume.
3. Task documentation stays accurate in the terminal PR (checkboxes reflect real completion).
4. Compounding artifacts are committed alongside the delivered feature, pre-merge.
5. Every workflow-created branch conforms to `release-please-config.json` types; `pf/` never recurs.
6. Local phase-mode merge-queue mechanics are self-driving (no manual `status collect`, `merge exec`, or
   primary-ref fast-forward).
7. Secrets fail a local gate before `git push`; history redaction never disturbs shared `main`.
8. A safe, standalone `/sw-cleanup` prunes merged branches/worktrees without breaking in-flight work.

## Non-Goals

- Changing the terminal **human merge gate** — the loop halts at merge-ready and never merges to `main`
  or force-pushes.
- Redesigning multi-feature `integration/<stamp>` promotion beyond the `pf/` → conforming-type rename.
- New memory-provider behavior beyond fail-closed reuse of existing guardrails.
- Auto-promotion of rule-class memories (remains human-gated).
- Cleanup of arbitrary untracked files or non-workflow branches.

## Requirements

R-IDs are carried forward from the frozen brainstorm (stable namespace; do not renumber); requirement
text receives only clarifying edits. The sections are presented in numeric R-ID order, so the
Cross-cutting group (R35–R37) appears before Phase merge-queue (R38–R40) and Secret-safety (R41–R42),
which it forward-references.

### Durable autonomy driver

- **R1** A deterministic, resumable deliver driver MUST own phase sequencing and advancement via a single
  script entrypoint — a `deliver-loop` verb on `scripts/wave.sh` (reusing the existing state, merge-queue,
  and journal machinery; no divergent parallel script) — so progression does not depend on an agent
  executing long prose faithfully.
- **R2** The driver MUST persist sufficient durable state (current wave/phase, per-phase status, next
  action, lock, merge journal) such that a fresh agent with no prior conversational context can resume
  the run to completion from state alone.
- **R3** On invocation the driver MUST auto-detect an in-progress run and resume it idempotently, rather
  than starting a new or divergent run.
- **R4** While a run can still progress autonomously, the orchestrator MUST NOT emit a manual
  "Next steps" handoff (e.g. `cd <worktree>` → `/sw-gaps → /sw-verify → /sw-ship`); the binding contract
  is "do not stop until merge-ready or a defined blocker."
- **R5** `doc.afterTasks: auto` (and `confirm` after human ack) MUST hand directly to the durable driver,
  which carries the run through every per-phase `/sw-ship` step to the terminal merge gate without
  intermediate human prompts.
- **R6** The spec-seed step MUST create/resolve the `<type>/<slug>` base branch and commit the frozen
  `docs/prds/<n>-<slug>/` set onto it (never `main`) **before** phase worktrees are provisioned, closing
  the observed main-seed and missing-base-branch failure.
- **R7** Each per-phase `/sw-ship` MUST run in phase-mode and write durable machine-readable status; the
  driver MUST advance solely from that status, never from chat output.

### Bounded remediation & clean terminal state

- **R8** On a phase blocker (CI red, merge/forward-merge conflict, validated P0/P1 review, verification
  `not-verified`), the driver MUST attempt bounded auto-remediation (stabilize loop, single flaky
  re-run) up to a configured budget before halting that branch.
- **R9** Independent sibling phases MUST continue via blast-radius while a blocked phase halts; only
  transitive dependents of the blocked phase are blocked.
- **R10** Every run MUST terminate in a clean, fully-described state: either merge-ready (terminal PR
  green, "ready to merge — your call") or a consolidated blocker report — never an in-flux/ambiguous
  state.
- **R11** The remediation budget MUST be configurable via `deliver.remediation.maxAttempts` with a
  documented default of **2** attempts per blocked phase before halting clean.
- **R12** On a halt, the driver MUST write a single consolidated blocker report to a durable path
  capturing per-phase cause, remediation attempted, and the specific human decision required.

### Task-document currency

- **R13** The driver MUST keep the task list's completion checkboxes current as task refs and phases
  complete; checkbox toggles (`[ ]` ↔ `[x]`) are a permitted progress-only mutation of an otherwise
  frozen task file.
- **R14** A guard MUST reject any non-checkbox edit (task text, R-IDs, structure, frontmatter) made via
  the progress path, preserving spec immutability.
- **R15** A gate MUST verify the task file's checkbox state matches actual phase/task completion before
  the terminal merge gate; on divergence (e.g. an all-unchecked task file for completed work) it MUST
  hard-block the terminal merge gate until reconciled — not warn-and-continue.
- **R16** Task-file progress updates MUST be committed onto the feature branch in-loop so the terminal PR
  reflects accurate task status.

### Compounding in-loop (pre-merge)

- **R17** The driver MUST run the full `/sw-compound-ship` chain (retro → compound → memory-sync →
  status reconcile → COMPLETION-LOG append) pre-merge, as the loop's final step once the feature branch
  is merge-ready, before presenting the human merge gate.
- **R18** All file-based compounding outputs (status reconcile, COMPLETION-LOG entry, CHANGELOG/version
  bookkeeping, learnings notes) MUST be committed onto the feature branch so they ride in the terminal
  PR.
- **R19** External memory writes (via `memory-preflight` + `scripts/memory-redact.sh`) MUST still run but
  are not committed; provider unreachability MUST fail-closed per existing memory guardrails without
  leaving the run in-flux.
- **R20** The COMPLETION-LOG entry MUST record completion pre-merge on the feature branch (completion is
  recorded before the human merge), per the chosen sequencing.
- **R21** Rule-class memory promotion MUST remain human-gated within the autonomous loop — no
  auto-promotion (preserves the memory guardrails rule-class promotion gate).

### Branch-prefix conformance

- **R22** Every workflow-created branch (feature base, phase, multi-feature item, ad-hoc worktree) MUST
  use a type prefix drawn from `release-please-config.json` `changelog-sections[].type`
  (feat/fix/perf/revert/docs/chore/refactor/test); `pf/` MUST NOT be produced anywhere.
- **R23** `scripts/worktree.sh` MUST NOT default to `pf/<name>`; provisioning without an explicit
  conforming `--branch` MUST derive a conforming name or fail closed with remediation — never silently
  mint `pf/`.
- **R24** Multi-feature derivation in `scripts/wave_deliver.py` MUST replace `pf/<id>` with a conforming
  type-prefixed name (type from item metadata; default `feat/` when unknown).
- **R25** A branch-name guard MUST validate any branch the workflow creates against the allowed type set
  (single-sourced from `release-please-config.json`) and reject non-conforming names at creation, so the
  regression cannot recur off-script.
- **R26** Existing logic and fixtures that match `pf/` (`scripts/reconcile-status.sh`,
  `scripts/test/run-impl-fixtures.sh`, deliver/worktree skills) MUST be updated to the conforming scheme.
- **R27** The fix MUST be applied at the `worktree.sh` floor plus the guard — not caller-only — since the
  prior caller-only fix is what allowed the regression to recur.

### Cleanup command

- **R28** A new standalone `/sw-cleanup` command MUST remove merged local branches, their merged remote
  counterparts, stale worktrees (branch merged or gone), and completed deliver run-state artifacts.
- **R29** `/sw-cleanup` MUST default to dry-run + explicit confirmation; deletions occur only after the
  operator confirms.
- **R30** `/sw-cleanup` MUST always protect the current branch, the default branch, any unmerged branch,
  active/locked worktrees, and any in-flight deliver run (lock/journal present).
- **R31** The deliver loop MUST detect when the feature branch has been merged and print a one-line
  suggestion to run `/sw-cleanup` (suggestion only; the human runs and confirms).
- **R32** `/sw-cleanup` MUST never `rm -rf` worktree directories — only `git worktree remove` + `prune`
  (consistent with deliver teardown safety).
- **R33** `/sw-cleanup` MUST emit a report of what was/would be removed and what was protected and why.
- **R34** `/sw-cleanup` MUST be registered in `.cursor-plugin/plugin.json` and follow the `sw-` naming
  contract (scope + explicit non-goals in its description).

### Cross-cutting

- **R35** All behavior authored in `core/` (commands, skills, scripts) MUST be propagated to `dist/`
  via the emitter, with the freshness gate (`scripts/test/run-emitter-fixtures.sh`) passing.
- **R36** New behaviors MUST be covered by fixtures: driver resume-from-state, blocker clean-halt +
  consolidated report, task-checkbox currency + non-checkbox-edit rejection, branch-prefix guard
  (floor + creation-time), `/sw-cleanup` safety/protection (dry-run, in-flight protection),
  `status collect` phase-worktree path resolution (R38), no-PR local merge path (R39), primary-ref
  auto-sync (R40), pre-push secret scan deny patterns (R41), and range-scoped redaction guardrail (R42).
- **R37** Documentation (`docs/guides/*`, `rules/sw-naming.mdc`, relevant command/skill docs) MUST be
  updated to describe the durable autonomy contract, pre-merge compounding, branch-type policy,
  `/sw-cleanup`, the local phase-mode merge-queue mechanics (R38–R40), and the secret-safety guardrails
  (R41–R42).

### Phase merge-queue & status mechanics (local phase-mode)

- **R38** `scripts/wave.sh status collect` MUST resolve the durable phase status file at the
  phase-worktree path (`<phase-worktree>/.cursor/sw-deliver-runs/<phase>/status.json`) directly — no
  manual copy from the phase worktree to the orchestrator root.
- **R39** `scripts/wave.sh merge run-next` MUST provide a no-PR local-merge path for phase-mode, where
  phases have no per-phase PR; it MUST NOT fail `gate-check` with "no open PR" and force a manual
  `merge exec` fallback. The local path still honors the live gate and review barrier where applicable.
- **R40** After each phase merge, the driver MUST automatically advance/sync the primary checkout's
  `<type>/<slug>` ref (the orchestrator merges into its own worktree checkout); a manual
  `git merge --ff-only` on the primary checkout MUST NOT be required.

### Secret-safety guardrails

- **R41** A pre-push deny-pattern secret scan MUST run locally before `git push` (in `/sw-stabilize` or
  terminal-PR prep) covering at least `sk_(live|test)_`, `ghp_`, and PEM private-key blocks, so secrets
  fail locally as the first line of defense rather than only at GitHub push protection. A detected
  pattern MUST block the push with remediation guidance.
- **R42** A `rules/` guardrail plus a documentation note MUST require history redaction to be
  range-scoped (`git filter-branch <base>..<branch>` or interactive rebase); a bare-branch
  `filter-branch` that rewrites shared `main` commits under new SHAs MUST be prohibited.

### Crash-safety & resumability hardening (doc-review panel)

*(Added after the PRD 007 persona panel found the durability claims were asserted but not backed by the
existing `core/scripts/wave_state.py` machinery. New stable R-IDs; do not renumber R1–R42.)*

- **R43** Durable state writes MUST be crash-safe: atomic write (temp file + `rename`) with `fsync`, and a
  read path that **detects** corruption/truncation. A corrupt or unreadable state file MUST halt with a
  consolidated blocker (R12) — it MUST NOT be silently treated as "no run" and restarted as a new/divergent
  run (closes ADV-01: today `read_json` swallows errors → `{}`).
- **R44** The orchestrator lock MUST record owner liveness (pid/host/heartbeat) and support stale-lock
  reclaim: a fresh agent MUST reclaim a lock whose owner is provably dead or whose heartbeat is stale past
  a threshold, so resume is never deadlocked by a crashed run; a concurrently **live** invocation MUST still
  be refused (closes ADV-02).
- **R45** The merge journal MUST make crash recovery idempotent: an interrupted merge MUST be replayable
  without double-merging or skipping a phase (transactional record + idempotent replay) (closes ADV-03).
- **R46** The driver MUST emit a heartbeat and enforce a per-phase timeout; a hung or crashed run MUST be
  detected and converted into a clean consolidated blocker report, so R10's "never in-flux" holds for the
  ungraceful crash path — the exact observed failure — not only graceful halts (closes prod-1).
- **R47** Per-phase `status.json` MUST bind to the phase head SHA; a status whose SHA does not match the
  branch's current head is stale and MUST NOT authorize a merge, preventing a flapped-then-red phase from
  merging on stale-green status (closes ADV-04).

### Task-currency mechanics hardening (doc-review panel)

- **R48** `scripts/check-frozen.sh` and the `pre-commit-frozen.sh` hook MUST permit a **checkbox-only**
  diff (`[ ]` ↔ `[x]` on existing task lines, no other line changes) to a `frozen: true` task file as a
  sanctioned progress mutation; the permitted-diff predicate MUST be single-sourced with the TR5 progress
  writer/guard, and checkbox commits MUST NOT use `--no-verify` (closes FEAS-01 — without this the
  currency commits turn the terminal PR red and self-block the merge gate).
- **R49** A durable per-task/per-phase completion ledger MUST be the source the R15 currency gate compares
  against (not chat output), and MUST distinguish a legitimately partial phase from a stale all-unchecked
  file, so the gate does not force the R7-forbidden chat re-derivation (closes ADV-07/ADV-08).

### Secret-safety hardening (doc-review panel)

- **R50** The secret scan MUST run mechanically before **every** workflow `git push` (including `sw-pr`'s
  initial branch push and any `/sw-stabilize` / terminal re-push), at the push chokepoint — not phase-keyed
  to `/sw-stabilize` (which runs after the first push and only on non-green CI) (closes SEC-002/FEAS-03).
- **R51** Secret deny-patterns MUST be single-sourced with the coverage already in
  `scripts/memory_redact.py` (AWS `AKIA`, full GitHub token family, JWT, Bearer, `rk_`, `whsec_`, DB URLs,
  generic high-entropy — superset of `sk_`/`ghp_`/PEM); the scan MUST support an **allowlist** so the
  scanner's own fixtures/patterns and documented examples remain pushable, and MUST **fail closed** on scan
  error (closes SEC-001/ADV-05/SEC-004).
- **R52** R42's range-scoped-redaction requirement MUST be backed by a **mechanical** guard (not docs/rules
  only) that refuses a bare-branch `filter-branch` rewriting shared history (closes SEC-007).

### Completion & merge-queue semantics hardening (doc-review panel)

- **R53** Pre-merge completion MUST be recorded as a distinct `completed-pending-merge` durable sub-state;
  the COMPLETION-LOG / INDEX `complete` flip and a resuming agent's terminal verdict MUST be gated on
  **actual merge detection** (tied to R31), so a declined or deferred human merge never leaves the branch
  or a resumed run asserting the feature is merged/complete (closes FEAS-06/prod-4; supersedes the
  unconditional pre-merge flip implied by R20).
- **R54** The local no-PR merge gate (R39) MUST explicitly evaluate per-phase merge-ready-green local
  evidence (local verification-gate + local review barrier) plus a mandatory post-merge incremental verify
  on `<type>/<slug>`; `merge run-next` MUST branch on PR presence (PR → `check-gate.sh`; no PR → local
  evidence path) rather than failing on "no open PR". Remote `check-gate.sh` CI authority applies at the
  terminal PR (closes FEAS-04).
- **R55** The orchestrator worktree MUST own a **real (non-detached)** checkout of `<type>/<slug>`; at
  provision the primary checkout MUST be asserted off that branch, and when the primary is **dirty** on it
  the step MUST **fail closed** with remediation (commit/stash and move off). Phase merges then advance the
  branch ref directly with no cross-worktree `update-ref` and no manual fast-forward (resolves R40 via the
  chosen ownership model; closes FEAS-02).
- **R56** `/sw-cleanup` merged-detection MUST be squash-merge-aware (e.g. patch-id / `git cherry` / host
  merge status), MUST fail closed when merge status is indeterminate, and remote-branch deletion MUST be
  guarded against shared state (closes SEC-005/SEC-006).
- **R57** A single idempotent spec-seed step MUST own committing the frozen `docs/prds/<n>-<slug>/` set
  onto `<type>/<slug>`; `/sw-doc` afterTasks MUST call into that same step rather than seeding
  independently, covering both the auto-handoff path and a bare `deliver-loop` entry where the docs still
  sit on `main` (closes FEAS-05; reinforces R6).

### Per-phase resumability (scope expansion)

*(Operator decision: expand scope so the durable-state guarantee reaches inside each phase, not just the
outer wave sequencing — closing the root cause at the phase level, per prod-2.)*

- **R58** Each per-phase `/sw-ship` chain MUST persist durable step-level state (current step, last
  completed step, attempt counters) so a fresh agent resumes a phase **mid-chain** from state alone, and
  the phase advances from durable step status rather than re-entering the long prose procedure from the
  top (closes prod-2; extends R7 from phase-granular to step-granular resumability).

## Technical Requirements

- **TR1 — Driver (`scripts/wave.sh deliver-loop`).** Add a `deliver-loop` verb that, given a frozen
  task-list path or existing plan, runs the full phase-mode cycle: plan → orchestrator provision → per
  wave (provision → dispatch `/sw-ship --phase-mode` → `status collect` → `merge enqueue`/`run-next` →
  `bookkeeping` → incremental verify → `forward-merge` dependents → `phase-teardown`) → `resume
  reconcile` → terminal PR prepare/gate → compounding → terminal report. It composes existing `wave.sh`
  subcommands and MUST never bypass any `/sw-ship` step. Each transition appends to
  `.cursor/sw-deliver-runs/run.log`.
- **TR2 — Resumable state.** Extend `.cursor/sw-deliver-state.json` with a driver cursor
  (`currentWave`, `nextAction`) and per-phase `remediationAttempts`. `deliver-loop` reads state on entry
  (R3) and recomputes `nextAction` deterministically; the lock + merge journal prevent double-merge on
  resume.
- **TR3 — Branch-name guard.** Add `scripts/branch-name-guard.sh` that reads allowed types from
  `release-please-config.json` (`changelog-sections[].type`) and validates a candidate branch name;
  exit non-zero with remediation on non-conforming input. Call it from `scripts/worktree.sh` provision
  and `scripts/wave.sh` phase/orchestrator provision. Change `worktree.sh` so the default is a conforming
  derivation or a fail-closed error — remove the `pf/$name` fallback (R23/R27).
- **TR4 — Multi-feature derivation.** Update `scripts/wave_deliver.py` to emit conforming
  type-prefixed branches (type from item metadata; default `feat/`), replacing `pf/{i}` (R24). The
  allowed type set MUST be single-sourced (both `wave_deliver.py` type validation and
  `branch-name-guard.sh` read `release-please-config.json`, or a shared helper) so the two cannot drift.
- **TR5 — Task-progress writer + currency gate.** Add `scripts/tasks-progress.sh` to toggle task
  checkboxes (`[ ]`↔`[x]`) with a guard that rejects any non-checkbox diff to a frozen task file (R13/R14),
  and `scripts/tasks-currency-gate.sh` to compare checkbox state against phase/task completion and exit
  non-zero (hard block) on divergence before the terminal gate (R15). The driver commits checkbox updates
  on the feature branch in-loop (R16).
- **TR6 — Pre-merge compounding.** `/sw-compound-ship` gains a pre-merge invocation used by the driver:
  it runs the full chain before the human merge gate and commits file-based outputs (status reconcile,
  COMPLETION-LOG, CHANGELOG/version, learnings notes) onto the feature branch (R17/R18/R20). External
  memory writes run via `memory-preflight` and are not committed (R19). The command's "post-merge only"
  precondition is relaxed to "pre-merge in-loop OR post-merge standalone."
- **TR7 — `/sw-cleanup`.** Add `core/commands/sw-cleanup.md` and `scripts/cleanup.sh` (a `skills/cleanup`
  skill is added only if the dry-run/protection procedure exceeds what fits in the command file, and it
  introduces no cleanup behavior beyond R28–R34): enumerate merged local branches, their merged remotes, stale
  worktrees, and completed run-state; dry-run by default; protect current/default/unmerged branches,
  active/locked worktrees, and in-flight deliver runs; `git worktree remove`/`prune` only (no `rm -rf`);
  emit a removed/protected report; register in `.cursor-plugin/plugin.json` (R28–R34).
- **TR8 — Local merge-queue mechanics.** `wave.sh status collect` resolves the phase-worktree status path
  directly (R38); `merge run-next` adds a no-PR local-merge path honoring the live gate/review barrier
  (R39); after each merge the driver fast-forwards the primary checkout's `<type>/<slug>` ref
  automatically (R40).
- **TR9 — Secret scan + redaction guard.** Add `scripts/secret-scan.sh` (deny patterns
  `sk_(live|test)_`, `ghp_`, PEM blocks, extensible) invoked before `git push` in `/sw-stabilize` /
  terminal-PR prep; block with remediation on match (R41). Add a `rules/` guardrail (and doc note)
  prohibiting bare-branch `filter-branch`, requiring range-scoped redaction (R42).
- **TR10 — Config.** Add `deliver.remediation.maxAttempts` (default 2) to the config schema, example
  config, and `setup` seeding (R11).
- **TR11 — Emitter propagation.** Regenerate `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all`; freshness gate must pass (R35).
- **TR12 — Crash-safe state core.** Harden `scripts/wave_state.py`: atomic `write_json` (temp + `rename`
  + `fsync`); `read_json` distinguishes "absent" from "present-but-corrupt" and raises on corruption so
  callers halt (R43). Add lock metadata (pid/host/`heartbeatAt`) and a `reclaim` path keyed on liveness +
  staleness threshold (R44). Make the merge journal transactional with idempotent replay (R45).
- **TR13 — Liveness watchdog.** The `deliver-loop` writes a heartbeat each transition and enforces a
  per-phase timeout (configurable); a stale heartbeat or exceeded timeout converts the run to a
  consolidated blocker (R46). Bind each phase `status.json` to `git rev-parse HEAD`; `status collect` /
  merge enqueue reject SHA-mismatched status (R47).
- **TR14 — Frozen checkbox carve-out.** Extract a shared `is_checkbox_only_diff` predicate used by both
  `scripts/tasks-progress.sh` (TR5) and the freeze guards (`scripts/check-frozen.sh`,
  `core/hooks/pre-commit-frozen.sh`); the guards allow a checkbox-only diff to a frozen task file and
  reject anything else (R48). The driver commits checkbox updates through normal (non-`--no-verify`)
  commits.
- **TR15 — Per-task completion ledger.** Persist a durable per-task/per-phase completion ledger under the
  run state; `scripts/tasks-currency-gate.sh` compares the frozen task file's checkboxes against the
  ledger (not chat), tolerating declared-partial phases and hard-blocking only on true divergence
  (R49, R15).
- **TR16 — Secret-scan chokepoint.** `scripts/secret-scan.sh` is invoked at every workflow push point
  (`sw-pr` push step, `sw-stabilize` re-push, terminal-PR push) via a single push wrapper; patterns are
  single-sourced with `scripts/memory_redact.py` (shared pattern module), support a committed allowlist,
  and fail closed on error (R50, R51). Add a mechanical range-scoped-redaction guard refusing bare-branch
  `filter-branch` (R52).
- **TR17 — Completion semantics.** Run state gains a `completed-pending-merge` sub-state; COMPLETION-LOG /
  INDEX `complete` flip and resume's terminal verdict are gated on merge detection (R31/R53). Pre-merge
  compounding (TR6) writes its file outputs but does not assert `complete` until merge is detected.
- **TR18 — Local merge gate.** `scripts/wave_merge.py` `merge run-next` branches on PR presence: PR →
  `check-gate.sh`; no PR → local-evidence path (per-phase merge-ready-green + post-merge incremental
  verify on base) (R54). Document the CI-authority boundary in the deliver skill.
- **TR19 — Orchestrator branch ownership.** `scripts/wave_lifecycle.py` orchestrator-provision checks out
  `<type>/<slug>` **non-detached** in the orchestrator worktree; it asserts the primary checkout is off
  that branch and **fails closed** when the primary is dirty on it. Phase merges advance the ref directly;
  R40's manual-ff path is removed (R55).
- **TR20 — Squash-aware cleanup.** `scripts/cleanup.sh` merged-detection uses a squash-aware predicate
  (patch-id / `git cherry` / host merge status) and fails closed when indeterminate; remote deletion is
  shared-state-guarded (R56).
- **TR21 — Single spec-seed owner.** Factor spec-seed into one idempotent helper invoked by both the
  driver and `/sw-doc` afterTasks; it creates `<type>/<slug>` if missing and commits the frozen docs only
  if not already present, never on `main` (R57, R6).
- **TR22 — Step-granular phase resume.** Per-phase `/sw-ship` persists step-level state (current/last
  step, attempts) in the per-phase run record; the chain resumes mid-phase from that state instead of
  restarting the prose chain (R58). This extends the phase-mode status contract already written by
  `scripts/ship-phase-status.sh`.

## Security & Compliance

- **Secret hygiene (R41).** The pre-push scan is the local first line of defense; GitHub push protection
  remains the backstop, not the only line. Patterns are conservative (deny-list) and extensible; matches
  block the push and must not be auto-bypassed.
- **History integrity (R42).** Range-scoped redaction only; bare-branch `filter-branch` on shared `main`
  is prohibited to prevent SHA rewrites and spurious conflicts.
- **Memory guardrails (R19/R21).** Redaction chokepoint (`scripts/memory-redact.sh`) runs before any
  persist; provider unreachability fails closed; rule-class promotion stays human-gated.
- **No destructive git (constraints, R32).** The driver never merges to `main` or force-pushes;
  `/sw-cleanup` never `rm -rf`s and protects in-flight work; deletions are confirm-gated.
- **Least privilege.** Memory provider credentials via environment only (existing trust boundary).

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (notably
`scripts/test/run-deliver-fixtures.sh`, `run-impl-fixtures.sh`, `run-emitter-fixtures.sh`).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `deliver-loop-resume-from-state` | a fresh `deliver-loop` invocation resumes from `sw-deliver-state.json` without restarting | R1, R2, R3 |
| `deliver-loop-no-manual-handoff` | driver never emits a manual `Next steps` handoff while progress is possible | R4, R5 |
| `deliver-spec-seed-feature-branch` | spec committed onto `<type>/<slug>` (never `main`) before phase provisioning | R6 |
| `deliver-advance-from-status-only` | advancement keyed on durable status, not chat | R7 |
| `deliver-blocker-clean-halt` | bounded remediation then a consolidated blocker report; siblings continue | R8, R9, R10, R12 |
| `deliver-remediation-maxattempts-default` | default budget = 2 from config | R11 |
| `tasks-checkbox-currency` | checkboxes toggled in-loop; committed on feature branch | R13, R16 |
| `tasks-progress-nonckbox-reject` | non-checkbox edit to frozen task file rejected | R14 |
| `tasks-currency-gate-block` | divergence hard-blocks the terminal gate | R15 |
| `compound-ship-premerge-commit` | pre-merge chain commits file outputs on feature branch; memory not committed | R17, R18, R19, R20 |
| `compound-ship-rule-class-gated` | no auto-promotion of rule-class memory in loop | R21 |
| `branch-name-guard-floor` | `worktree.sh` no longer defaults to `pf/`; fail-closed/derive | R22, R23, R27 |
| `branch-name-guard-multifeature` | `wave_deliver.py` emits conforming type prefix | R24 |
| `branch-name-guard-creation` | guard rejects non-conforming branch at creation | R25 |
| `pf-matcher-migration` | reconcile/impl fixtures updated off `pf/` | R26 |
| `cleanup-dry-run-default` | `/sw-cleanup` dry-run + confirm gate | R28, R29, R33 |
| `cleanup-protects-inflight` | protects current/default/unmerged/active-locked/in-flight | R30, R32 |
| `deliver-suggest-cleanup-on-merge` | loop suggests `/sw-cleanup` after detected merge | R31 |
| `cleanup-registered` | `/sw-cleanup` in plugin manifest + `sw-` contract | R34 |
| `emitter-freshness-007` | `dist/` regenerated and fresh | R35 |
| `status-collect-phase-path` | `status collect` resolves phase-worktree path directly | R38 |
| `merge-run-next-no-pr` | no-PR local-merge path works in phase-mode | R39 |
| `primary-ref-autosync` | primary checkout ref advanced automatically post-merge | R40 |
| `secret-scan-prepush` | deny patterns block push locally | R41 |
| `redaction-range-scoped-guard` | bare-branch `filter-branch` prohibited | R42 |
| `state-write-atomic-crash` | corrupt/truncated state halts, not silent new run | R43 |
| `lock-stale-reclaim` | dead-owner lock reclaimed; live lock refused | R44 |
| `merge-journal-idempotent-replay` | interrupted merge replays without double/skip | R45 |
| `driver-heartbeat-timeout-halt` | hung/crashed run → consolidated blocker | R46 |
| `status-sha-freshness` | SHA-mismatched status cannot authorize a merge | R47 |
| `frozen-guard-allows-checkbox` | checkbox-only diff to frozen task file permitted; other edits rejected | R48 |
| `currency-gate-vs-ledger` | gate compares to durable ledger; tolerates declared-partial | R49 |
| `secret-scan-at-sw-pr-push` | scan fires on the first (`sw-pr`) push | R50 |
| `secret-patterns-single-source-allowlist` | patterns shared with `memory_redact.py`; allowlist; fail-closed | R51 |
| `redaction-mechanical-guard` | bare-branch `filter-branch` mechanically refused | R52 |
| `completion-pending-merge-decline` | declined merge → resume does not report merged/complete | R53 |
| `merge-run-next-pr-vs-local` | PR → check-gate; no PR → local-evidence path | R54 |
| `orchestrator-owns-branch` | non-detached orchestrator checkout; primary asserted off; dirty-primary fails closed | R55 |
| `cleanup-squash-merge-aware` | squash-merged branch detected; indeterminate fails closed | R56 |
| `spec-seed-single-owner-idempotent` | both entry paths seed via one idempotent helper; never `main` | R57 |
| `phase-resume-mid-chain` | fresh agent resumes a phase mid-`/sw-ship` from step state | R58 |

R36 is satisfied by this fixture set itself; R37 (documentation) is verified by review, not a fixture.
Per-R traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/deliver-autonomy-hardening`, delivered in dependency-ordered phases:
  (1) branch-guard + `worktree.sh` floor (R22–R27) and crash-safe state core (`wave_state.py`: R43–R45) —
  these underpin everything that provisions worktrees or persists state; (2) durable `deliver-loop` +
  resume + heartbeat/timeout + orchestrator branch ownership (R1–R7, R46, R55, R58); (3) local merge-queue
  mechanics + status SHA-freshness (R38–R40, R47, R54); (4) task-currency + frozen carve-out + ledger
  (R13–R16, R48, R49); (5) pre-merge compounding + completion semantics (R17–R21, R53); (6) secret-safety
  (R41–R42, R50–R52); (7) `/sw-cleanup` incl. squash-aware detection (R28–R34, R56); (8) spec-seed single
  owner (R6, R57); (9) docs + dist (R35, R37).
- **Backward compatible.** New config key `deliver.remediation.maxAttempts` defaults to 2; absent key →
  default. Existing `pf/` branches are migrated/cleaned via the new `/sw-cleanup` (not auto-deleted).
- **Bootstrap caution.** Because this PRD repairs the very `/sw-deliver` machinery, the first delivery
  SHOULD be supervised (`doc.afterTasks: confirm` or `--after-tasks stop`) rather than `auto`, until the
  durable driver lands and its fixtures are green. See Decision Log (DL-9).
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Durable resumable state-machine driver replaces prose orchestration | Prose autonomy fails across long/compacting sessions; a fresh agent must resume from state alone (R1–R5). |
| DL-2 | `/sw-compound-ship` runs fully pre-merge with all file outputs (incl. COMPLETION-LOG) committed on the feature branch | Operator wants compounding "committed along with the delivered feature"; single complete terminal PR (R17–R20). |
| DL-3 | Bounded auto-remediation; default `maxAttempts = 2`; always end clean | "No manual intervention unless absolutely necessary" + "never in-flux" (R8–R12). |
| DL-4 | Branch types single-sourced from `release-please-config.json`; fix at the `worktree.sh` floor + creation-time guard | Prior caller-only fix let `pf/` recur off-script (R22–R27). |
| DL-5 | `/sw-cleanup` standalone, dry-run + confirm, protects in-flight work | Safe pruning that cannot break in-progress implementations (R28–R34). |
| DL-6 | Task-checkbox divergence hard-blocks the terminal merge gate | Accurate task docs in the terminal PR; warn-and-continue would let staleness ship (R15). |
| DL-7 | Driver entrypoint = `deliver-loop` verb on `scripts/wave.sh` (no separate script) | Reuse existing state/merge-queue/journal machinery; single source (R1). |
| DL-8 | Secret-safety is a first-class local gate; redaction range-scoped | Catch secrets before push; never rewrite shared `main` (R41, R42). |
| DL-9 | First delivery of this PRD is supervised, not `auto` | Bootstrap hazard: using the broken deliver loop to fix itself; supervise until the driver + fixtures are green. |
| DL-10 | Durable state is made crash-safe (atomic+fsync, corruption-halt, stale-lock reclaim, idempotent journal, heartbeat/timeout) | Panel showed `wave_state.py` had no atomicity/corruption/liveness; the crash path is the failure that motivated the PRD (R43–R47). |
| DL-11 | Freeze guards permit a checkbox-only diff to frozen task files | Otherwise the in-loop currency commits redden the terminal PR and self-block the merge gate (R48). |
| DL-12 | Secret scan is a mechanical chokepoint at every push; patterns single-sourced with `memory_redact.py` + allowlist + fail-closed | An agent-executed prose scan is the exact fragility being fixed; `sw-pr` pushes first; the narrow deny-set regressed vs existing redaction (R50–R52). |
| DL-13 | Completion recorded as `completed-pending-merge`; INDEX `complete` gated on actual merge detection | A declined/deferred human merge must not leave the branch or a resume asserting merged (R53). |
| DL-14 | Orchestrator owns a real `<type>/<slug>` checkout; primary asserted off, dirty-primary fails closed | Removes the cross-worktree ref hazard and the residual manual fast-forward (R55). Operator-chosen over detached+safe-ff. |
| DL-15 | Scope expanded to step-granular per-phase resumability | Phase-granular resume still re-entered the prose chain mid-phase; close the root cause at the phase level (R58). Operator-chosen over phase-granular-only. |

## Open Questions

None — all brainstorm open questions were resolved (driver entrypoint → `wave.sh deliver-loop`;
checkbox gate → hard-block; `maxAttempts` default → 2) and are recorded in the Decision Log.
