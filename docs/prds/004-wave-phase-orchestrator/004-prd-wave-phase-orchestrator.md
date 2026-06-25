---
date: 2026-06-24
topic: wave-phase-orchestrator
source_brainstorm: docs/brainstorms/2026-06-24-wave-phase-orchestrator-requirements.md
---

# PRD 004: `/sw-deliver` task-list phase orchestrator

## Overview

`/sw-deliver` becomes the "play button" for a frozen task list. Given `tasks-<n>-<slug>.md`, it drives every
remaining implementation phase of a single feature to one human merge gate: dependency-ordered, parallel
where safe, stacked where not, sub-agent-dispatched where policy allows. Each phase runs the full `/sw-ship`
chain inside its own worktree and **auto-merges into a single feature branch `<type>/<slug>` when `check-gate.sh`
is green** — the bot/CI gate replaces the per-phase human gate. The only human stop is the final
`<type>/<slug> → main` pull request.

This is unified with (not a replacement for) the existing multi-feature wave. `/sw-deliver` keeps one
DAG-of-`/sw-ship`-runs engine; an auto-detected **mode** selects only the terminal merge unit:

- **phase-mode** (new): items are phases of one PRD; all greens stack onto one `<type>/<slug>`; **one** merge to
  `main` at the end.
- **multi-feature mode** (existing, unchanged): items are independent features; each promotes to `main`
  individually via `integration/<stamp>`.

> **Naming (this PRD).** The command was previously `/sw-wave`. Because phase-mode makes it the default
> implementation entry point (the "play button"), it is renamed to **`/sw-deliver`** (skill `skills/deliver/`),
> slotting above `/sw-ship`: *ship one phase → deliver the feature*. "Wave" is retained **only** as the internal
> term for a dependency-ordered batch of concurrently-runnable units (and the planning engine `scripts/wave.sh`);
> a "wave run" means one `/sw-deliver` invocation. It is no longer a command name. See R64 / DL-33.

**Input:** [docs/brainstorms/2026-06-24-wave-phase-orchestrator-requirements.md](../../brainstorms/2026-06-24-wave-phase-orchestrator-requirements.md) (Full tier).

**Dependency (blocking):** Sequences after [PRD 002](../002-first-run-onboarding-ux/002-prd-first-run-onboarding-ux.md)
(worktree guard `sw-assert-worktree.sh`, single-pass `/sw-tasks`, `doc.afterTasks` boundary). The
`sw-assert-worktree.sh` guard does **not exist in the repo yet** — PRD 004's no-bare-main guarantee (R16)
depends on it, so PRD 004 implementation MUST either land after PRD 002 ships that guard, or define its own
minimal bare-main assertion so R16 is enforced regardless of 002's timing. PRD 004 does not change PRD 002
defaults; it adds the orchestrator that the `doc.afterTasks: auto` path can eventually dispatch.

## Goals

1. **One-command feature delivery** — `/sw-deliver run <frozen-task-list>` drives all phases to a single
   `<type>/<slug> → main` PR with no human interaction in between.
2. **Parallel where safe** — independent phases (per authoritative task-list edges, after the shared-file
   safety net) execute concurrently in isolated worktrees, bounded by `worktree.parallelCeiling`.
3. **Full gating preserved** — every phase runs the complete `/sw-ship` chain; auto-merge happens only on a
   live green `check-gate.sh` verdict; no `/sw-ship` step or guardrail is bypassed.
4. **Single human gate** — the only stop is `<type>/<slug> → main`; `/sw-deliver` never merges or force-pushes to
   `main`.
5. **Honest blast radius** — a single unrecoverable phase failure continues independent siblings, blocks only
   transitive dependents, and halts once with a consolidated report.
6. **Resumable** — re-invocation skips already-merged-green phases and resumes blocked/unstarted ones,
   reconciled against git as ground truth; safe to interrupt without duplicate branches/PRs/merges.
7. **Zero regression** — existing multi-feature mode (items + edges → `integration/<stamp>` → per-leaf
   promotion) is unchanged and its fixtures stay green.
8. **Release-coherent throughout** — the base branch is typed per `release-please-config.json` (default
   `feat/<slug>`), and `CHANGELOG.md` + `version.txt` are maintained as each phase lands, so the in-development
   state stays release-ready while release-please remains the release authority.

## Non-Goals

- Bypassing, reimplementing, or skipping any `/sw-ship` step or guardrail.
- Auto-merging or force-pushing to `main` (the terminal human merge gate is inviolate).
- Re-authoring, re-freezing, or amending PRDs / task lists from within `/sw-deliver`.
- Changing the multi-feature promotion model or its `integration/<stamp>` machinery.
- Sub-task-level (`1.1` / `1.2`) parallelism — within-phase work stays governed by `/sw-execute`
  execute-discipline; `/sw-deliver` orchestrates at **phase** granularity.
- Hand-rolling any CI/merge verdict outside `check-gate.sh`.
- Cross-feature waves that mix phase-mode and multi-feature units in one plan (deferred).
- Automatic file-set edge inference as a fallback (deferred; sequential fallback only in v1).
- A rich live dashboard / `living-status` integration for per-phase progress (deferred) — note the *minimal*
  append-only run-log + terminal notification (R54) IS in scope for v1; only the rich dashboard is deferred.
- Auto-dispatch wiring from `/sw-doc` `doc.afterTasks: auto` (integration point noted; wiring out of scope).
- Creating, merging, or tagging a release, or pushing to the default branch — release-please remains the
  release authority; the wave only maintains the in-development `## [Unreleased]` changelog + `version.txt`
  (R57–R60).

## Requirements

Requirements `R1`–`R34` carry forward from the brainstorm (verbatim intent). PRD additions are `R35`–`R44`.
Each is testable.

### Command surface and mode resolution

- **R1** `/sw-deliver` MUST remain a single command exposing both phase-mode and multi-feature mode over a shared
  dependency-DAG engine; the existing multi-feature behavior (per-leaf promotion to `main` via
  `integration/<stamp>`) MUST be preserved unchanged.
- **R2** `/sw-deliver run` MUST auto-detect mode from input: a task-list path (`tasks-<n>-<slug>.md`) selects
  phase-mode; an explicit item set, `--edges`, or an existing wave-plan artifact selects multi-feature mode.
- **R3** `/sw-deliver` MUST echo the resolved mode, the target feature branch (`<type>/<slug>` in phase-mode), and the
  planned waves before provisioning any worktree.
- **R4** Ambiguous input (e.g. both a task-list path and an explicit item set) MUST halt with a disambiguation
  prompt rather than guessing.

### Phase dependency model

- **R5** `/sw-tasks` MUST emit explicit phase-dependency metadata in the generated task list, declaring for
  each phase the phases it depends on (a phase with no declared dependency is a wave-1 leaf).
- **R6** The phase-dependency metadata MUST be machine-parseable by `/sw-deliver`, human-reviewable, and live
  inside the task-list artifact (not a sidecar file). The concrete format is fixed by R37.
- **R7** Phase-mode MUST build the phase DAG from the task list's explicit edges and MUST refuse to run on a
  dependency cycle (reusing `wave.sh` cycle detection).
- **R8** When a task list carries **no** phase-dependency metadata, `/sw-deliver` MUST fall back to strict
  sequential ordering (phase `N` depends on phase `N-1`), run with no parallelism, and emit a missing-edges
  notice.
- **R9** `/sw-deliver` MUST map each task-list phase (`### N.`) to exactly one orchestrated unit and MUST carry
  the phase's sub-task scope and R-IDs into the `/sw-ship` run for that phase.

### Wave planning and contention

- **R10** Phase-mode planning MUST produce dependency-ordered waves (batches with no intra-wave dependency)
  and persist a wave plan artifact distinguishable from a multi-feature plan (phase identifiers, target
  `<type>/<slug>`, mode marker).
- **R11** Before parallelizing any wave batch, `/sw-deliver` MUST run the `skills/parallelism/` pre-flight and
  serialize declared-parallel phases whose `**File:**` paths overlap on migrations, shared config, living
  `INDEX`/numbering counters, or the release-bookkeeping files (`CHANGELOG.md`, `version.txt` — though those
  are written only by the orchestrator merge step per R59, not phase worktrees), emitting a contention notice
  for each forced serialization.
- **R12** The shared-file safety net (R11) MUST override declared parallelism but MUST NOT override declared
  ordering — it can only make two phases more serial, never reorder or drop a declared dependency. The forced
  serialization direction MUST be deterministic and declared-order-respecting (order the earlier-wave /
  lower-numbered phase first; never inject an edge opposing a transitive declared path). Cycle detection (R7)
  MUST re-run on the **combined** graph (declared edges + injected contention edges) and refuse with a
  contention-cycle notice if injection would close a cycle.

### Execution, concurrency, and dispatch

- **R13** Each phase MUST be implemented and gated by the full `/sw-ship` chain inside its own worktree;
  `/sw-deliver` MUST NOT reimplement or bypass any `/sw-ship` step or guardrail.
- **R14** Independent phases within a wave batch MUST be dispatchable as concurrent background sub-agents,
  one `/sw-ship` per worktree, bounded by `worktree.parallelCeiling` with greedy fill and a queued remainder;
  the scheduler MUST never exceed the ceiling and MUST never unwind a running phase to admit a queued one.
- **R15** Sub-agent dispatch MUST obey `rules/sw-subagent-dispatch.mdc` (delegation heuristics, the dispatch
  rule's loop hard stops, circuit breaker) and the `ceiling-check` recombination handoff in
  `skills/parallelism/`. (Note: "the dispatch rule's hard stops" is distinct from this PRD's own requirement
  R29 on resumption — the two are unrelated despite the shared digits.)
- **R16** Implementation MUST never occur on bare `main`; every phase runs on a phase branch within a
  provisioned worktree (R35), and dependent phases MUST provision with `--base <type>/<slug>` after their
  dependencies have merged.

### Phase integration onto `<type>/<slug>`

- **R17** A phase MUST auto-merge into `<type>/<slug>` only when `check-gate.sh` returns a live `green` verdict for
  that phase's PR head; a non-green verdict MUST NOT merge.
- **R18** Phase `/sw-ship` runs MUST execute under a non-interactive phase-mode contract (R48): the terminal
  "ready to merge — your call" pause is suppressed and replaced by emitting a machine-readable terminal status,
  and `/sw-ship` exits **without merging** (the orchestrator owns the phase → `<type>/<slug>` merge per R19). The
  human merge gate is preserved exclusively for `<type>/<slug> → main`. (R18 governs only the pause/exit behavior;
  R48 specifies the full contract including non-pause human-halt conditions.)
- **R19** Merges into `<type>/<slug>` MUST be serialized by the orchestrator (a single merge in flight at a time)
  even when phases execute concurrently.
- **R20** After merging a phase, `/sw-deliver` MUST advance dependents to the new `<type>/<slug>` tip before
  provisioning or running them (R40 strategy).
- **R21** Phase worktrees MUST be torn down via safe `git worktree remove` + `prune` only (never raw `rm`)
  after their phase merges green or the wave halts.

### Terminal merge gate

- **R22** In phase-mode, `/sw-deliver` MUST open or update the single `<type>/<slug> → main` pull request **only when
  every phase in the DAG is `green-merged`** ("reachable" = the full phase set, with zero `blocked` phases). If
  any phase is `blocked`, the wave halts per R26 and MUST NOT open or advance the terminal PR. `/sw-deliver` MUST
  NOT create an `integration/<stamp>` branch in phase-mode.
- **R23** `/sw-deliver` MUST run `check-gate.sh` on the `<type>/<slug> → main` PR head as the authoritative
  whole-feature verdict and MUST halt at the human merge gate (it MUST NOT merge or force-push to `main`).
- **R24** The terminal report MUST state the gate verdict and merge-readiness of `<type>/<slug>` in the same
  "ready to merge — your call" form used by `/sw-ship` / `/sw-ready`.

### Failure handling and blast radius

- **R25** When a phase cannot reach green, `/sw-deliver` MUST continue independent sibling phases, auto-merge
  their greens, and block only the failed phase's **transitive dependents**.
- **R26** `/sw-deliver` MUST halt the wave exactly once with a consolidated blocker report enumerating: the failed
  phase(s) and cause, the blocked dependents, the phases merged green this run, and the recommended next
  command per blocker.
- **R27** A blocked or red phase MUST route to `/sw-stabilize` (its own `/sw-ship` stabilize surface) for
  remediation; `/sw-deliver` MUST NOT silently retry beyond the per-phase stabilize budget (the dispatch rule's
  loop hard stops). Whole-feature (`<type>/<slug>`-level) stabilization triggered by R39 MUST use a **distinct**
  budget with its own hard stop, separate from any single phase's per-phase budget, so a `<type>/<slug>`-level flap cannot
  loop unbounded or prematurely block. Intermittent/flaky failures MUST be distinguished from deterministic
  failures (re-run/quorum) before a phase blocks its dependents.

### State, idempotency, and resumption

- **R28** `/sw-deliver` MUST persist per-phase run-state with at least the statuses `pending`, `in-flight`,
  `green-merged`, and `blocked`, keyed by phase identifier and feature slug (R36 schema).
- **R29** On re-invocation for the same task list, `/sw-deliver` MUST skip phases already merged green and resume
  blocked/unstarted ones, reconciling run-state against the **pushed remote `<type>/<slug>` tip** as ground truth
  (an unpushed local merge commit MUST NOT be trusted as "merged"). The reconciliation predicate is fixed by
  R50 (merge method + ancestry/PR-state check); run-state loses to remote git on conflict.
- **R30** `/sw-deliver` MUST be safe to interrupt and resume without producing duplicate phase branches, duplicate
  PRs, or double-merges.

### Documentation, naming, and distribution

- **R31** `core/commands/sw-deliver.md` and `core/skills/deliver/SKILL.md` MUST document both modes, the
  auto-detection rule, auto-merge-on-green, the single terminal human gate, and the failure blast-radius
  policy, consistent with the `/sw-deliver` command-boundary description in `rules/sw-naming.mdc`.
- **R32** The `/sw-deliver` description MUST state scope and non-goals (does not bypass `/sw-ship`, does not
  auto-merge to `main`, does not re-author/re-freeze specs) per the description contract in `rules/sw-naming.mdc`.
- **R33** Source changes MUST land in `core/` and propagate to `dist/cursor/` and `dist/claude-code/` via the
  existing build/sync pipeline (no hand-edited `dist/` only).
- **R34** Phase-mode behavior MUST be covered by fixtures under `scripts/test/` (at minimum: explicit-edge DAG
  planning, sequential fallback, contention serialization, auto-merge-on-green, blocked-dependent blast
  radius, idempotent resume), wired into `verify.test`.
- **R64** Implementation MUST rename the command `/sw-wave → /sw-deliver` and skill `skills/wave/ →
  skills/deliver/` (`core/commands/sw-deliver.md`, `core/skills/deliver/SKILL.md`), the persisted artifacts
  (`.cursor/sw-deliver-plan.json`, `.cursor/sw-deliver-state.json`, `.cursor/sw-deliver.lock`,
  `.cursor/sw-deliver-runs/`), the config keys (`deliver.baseBranchType`, `deliver.phaseAckCadence`), and the
  fixtures (`deliver-phase-*`, `run-deliver-fixtures.sh`); and MUST update every `/sw-wave` reference in
  `rules/sw-naming.mdc`, `README.md`, and other docs. The internal "wave" vocabulary (dependency-ordered
  batches) and `scripts/wave.sh` are retained. No back-compat `/sw-wave` alias ships (pre-release plugin;
  DL-33).

### PRD additions

- **R35** Phase-mode MUST use the branch convention: base/integration branch `<type>/<slug>`; per-phase branch
  `<type>/<slug>-phase-<phase-slug>`. `<slug>` derives from the PRD/task-list slug; `<phase-slug>` derives from
  the phase heading. `<type>` MUST be a Conventional-Commits / `release-please-config.json` type
  (`feat`, `fix`, `perf`, `revert`, `docs`, `chore`, `refactor`, `test`), defaulting to `feat`. (The prior
  `pf/` prefix was a plan-forge leftover and MUST NOT be used.)
- **R35a** `<type>` MUST be resolved deterministically: a `--type <t>` flag wins; otherwise read a `type:`
  field from the task-list/PRD front-matter; otherwise default to `feat`. The resolved `<type>` MUST be one of
  the `release-please-config.json` types or `/sw-deliver` halts with a notice; the resolved value is echoed with
  the mode/branch pre-flight (R3) and recorded in the wave plan (R36) so resume binds to the same base branch.
- **R36** Wave plan and wave run-state MUST be separate artifacts: the **plan** (`.cursor/sw-deliver-plan.json`,
  DAG + waves + contention, mode marker) and the **run-state** (`.cursor/sw-deliver-state.json`, per-phase status
  + merged-commit refs + PR numbers). Run-state MUST be reconcilable from git and MUST NOT be committed (gated
  out of `/sw-commit` like other per-worktree state).
- **R37** `/sw-tasks` MUST emit a `## Phase Dependencies` table in the task list mapping each phase number to
  its dependencies (`Depends on:` cell with phase refs or `none`). `/sw-deliver` parses this table as the
  authoritative edge source (R5/R6); absence triggers the R8 sequential fallback.
- **R38** The orchestrator MUST collect concurrent `/sw-ship` sub-agent outcomes via a **durable,
  orchestrator-owned per-phase status path** (R47) — NOT the sub-agent's private `scripts/sw-tmp.sh` run dir,
  which is per-invocation, 0700, and deleted at `/sw-ship` chain end and is therefore unreadable by the
  orchestrator. Each phase `/sw-ship` MUST write a machine-readable terminal status
  (`merge-ready-green` | `blocked` + cause) to that path **before** `sw-tmp clean`. Green outcomes feed the
  serialized `<type>/<slug>` merge queue (R19); a sub-agent crash/timeout MUST be treated as a `blocked` phase
  (R25), never a silent skip.
- **R39** `/sw-deliver` MUST run the configured `verify.*` whole-feature check on the `<type>/<slug>` head **after
  each phase merge** (incrementally), not only once before the terminal PR. This attributes a cross-phase
  emergent failure to the specific merge that introduced it (declared-independent phases can be semantically
  coupled in ways the file-overlap net (R11) cannot see). On failure: route to `/sw-stabilize` on `<type>/<slug>`,
  mark the offending phase `blocked`, and apply the revert protocol (R45) before continuing; MUST NOT
  open/advance the terminal PR. (Resolves OQ2 — the verify re-runs on every `<type>/<slug>` advance, including late
  sibling merges.)
- **R40** When `<type>/<slug>` advances after a dependent phase branch was provisioned (a sibling merged first),
  `/sw-deliver` MUST integrate `<type>/<slug>` forward into the dependent branch by **merge** (not history-rewriting
  rebase of a published branch) in the dependent's own worktree before that phase's PR; an integration
  conflict MUST surface as a `blocked` phase (R25/R26), never an auto-resolved merge.
- **R41** Phase-mode MUST support `--dry-run` (print resolved mode, DAG, waves, and contention serializations
  with no mutations) and `--from <phase>` (resume at a specific phase), in addition to inheriting `/sw-ship`
  pass-through flags (`--fast`, `--skip-simplify`) applied per-phase. If `--from <phase>` names a phase whose
  upstream dependencies are not yet `green-merged`, `/sw-deliver` MUST **refuse** with a notice listing the unmet
  prerequisites (it does not auto-include them — the user names a valid resume point) (DL-28).
- **R42** `/sw-deliver` MUST validate that the input task list is **frozen** (`frozen: true`) before running
  phase-mode; an unfrozen task list MUST halt with a notice to `/sw-freeze` first.
- **R43** Both the wave plan **and** the run-state MUST record the `source_task_list` path and PRD number so a
  resumed run binds to the same feature/`INDEX.md` entry (firm requirement, tied to R29). `/sw-deliver` updates the
  `docs/prds/INDEX.md` status using **only the existing vocabulary** (`not-started`/`complete`) — it introduces
  **no** new `in-progress` value (DL-27): the entry stays `not-started` while the wave runs and transitions to
  `complete` only through the normal post-merge completion path, never frozen by the wave.
- **R44** The `worktree.parallelCeiling` accounting unit MUST be defined precisely: only wave-level `/sw-ship`
  phase worktrees count against the ceiling; sub-agent dispatch *within* a phase's `/sw-ship`
  (`rules/sw-subagent-dispatch.mdc`) MUST NOT consume wave ceiling slots. The orchestrator's own merge/
  integration work MUST be able to make progress without holding a phase slot, so a queued dependent can never
  be starved by a slot held while waiting on a merge (no hold-and-wait). (Scheduler caps merged into R14.)

### PRD additions — review hardening (P1 from `/sw-doc-review`)

- **R45** `/sw-deliver` MUST define a **revert/unstack protocol** for an already-merged green phase that later
  proves bad (cross-phase emergent failure R39, flaky-green, or per-phase terminal rejection R46): `git revert`
  the phase's merge commit on `<type>/<slug>` (preserving history), re-route the phase to `blocked`, re-block its
  transitive dependents, and record the revert in run-state. `/sw-deliver` MUST NOT rewrite `<type>/<slug>` history.
- **R46** The terminal `<type>/<slug> → main` gate MUST define **deny semantics**: a human rejection records a
  `rejected` terminal state in run-state with scope. Whole-feature rejection routes `<type>/<slug>` to
  `/sw-stabilize` or `/sw-amend` and MUST NOT re-present the same PR on resume; per-phase rejection applies the
  R45 revert to the named phase. Resume (R29) MUST NOT silently re-open a rejected terminal PR.
- **R47** `/sw-deliver` MUST define a durable, orchestrator-owned per-phase status location (e.g.
  `.cursor/sw-deliver-runs/<phase>/status.json`, or an explicit `SW_RUN_DIR` exported into each dispatched
  `/sw-ship`) independent of `sw-tmp`'s private/ephemeral run dirs, so phase outcomes survive `sw-tmp clean`
  and are readable by the orchestrator (consumed by R38).
- **R48** `/sw-ship` MUST gain an explicit non-interactive phase-mode contract (flag, e.g. `--phase-mode` /
  `--no-pause`, or `SW_PHASE_MODE` env) that: (a) replaces the terminal pause with a written machine-readable
  `merge-ready-green` status and exits **without merging**; (b) converts every other human-triage halt
  (local-review validated P0/P1, verification-gate halt, branch/scope/config ambiguity) into a written
  `blocked` status with cause rather than an interactive prompt. Phase-mode `/sw-deliver` invokes `/sw-ship` only
  under this contract.
- **R49** Before running phases, `/sw-deliver` MUST preflight that the repo's CI workflows **and** the configured
  review provider actually trigger on PRs whose **base is `<type>/**`** (non-default base). If they do not (phase
  PRs would get `checkCount == 0` → `blocked`, or never-landed review → `yellow` → timeout), `/sw-deliver` MUST
  surface an actionable preflight error and MUST NOT silently degrade every phase into a timeout-blocked state.
- **R50** The phase → `<type>/<slug>` merge method MUST be pinned to a **true merge commit** (no squash/rebase) so
  ancestry-based reconciliation is valid, and the resume reconciliation predicate MUST be specified
  (`git merge-base --is-ancestor <type>/<slug>-phase-<phase-slug> <pushed remote tip of `<type>/<slug>`>` and/or recorded PR
  state/merge-commit). This preserves per-phase review granularity (R55) and idempotent resume (R29/R30).
- **R51** `/sw-deliver` MUST guarantee single-writer integrity: (a) an orchestrator lock (e.g. `flock` on
  `.cursor/sw-deliver.lock` keyed by `<type>/<slug>`) acquired at start and released on exit/halt — a second
  concurrent invocation on the same slug MUST refuse (or attach read-only); (b) a per-phase **merge journal**
  entry written before the merge and cleared after push + state-commit, so an interrupted merge is detected and
  completed/rolled-back deterministically on resume (no double-merge, no divergence). Provisioning
  (`ceiling-check` + `worktree add` + port allocation) MUST also be serialized to avoid ceiling/port races.
- **R52** Phase → `<type>/<slug>` auto-merge MUST wait for the async review barrier (CodeRabbit / configured
  provider) to **settle** on the phase PR head before treating `check-gate.sh` green as merge-authorizing — a
  pending/not-yet-landed review is **non-green** for auto-merge purposes. (Closes the window where actionable
  P1 findings post after an auto-merge.)
- **R53** `/sw-deliver` MUST materialize `<type>/<slug>` in a **dedicated orchestrator worktree** that hosts the
  serialized merge queue (R19) and R40 forward-merges so conflicts surface locally as `blocked`. This
  orchestrator worktree does **not** count against `worktree.parallelCeiling` (it is infrastructure, not a
  phase slot) (DL-29).

### PRD additions — autonomy mitigations (product panel)

- **R54** `/sw-deliver` MUST emit a minimal, user-tailable **progress surface**: an append-only run log written on
  each phase state transition (`in-flight` / `green-merged` / `blocked`) plus a completion/blocked notification
  at terminal halt. (Distinct from the deferred rich living-status dashboard — this is the bare "what is
  happening now" affordance for an unattended run.)
- **R55** Phase → `<type>/<slug>` merges MUST preserve per-phase review granularity: no squash (R50 merge commits),
  and the terminal report (R24) MUST link each auto-merged phase PR so the human at the `<type>/<slug> → main` gate can
  review phase-by-phase rather than only as one whole-feature diff.
- **R56** `/sw-deliver` MUST support an optional ack-cadence config (`deliver.phaseAckCadence`, default `0` = off)
  that, when set to `K`, pauses for a single human ack after every `K` phase merges. Default preserves the
  hands-off play button; the knob gives risk-averse users a graduated on-ramp without abandoning auto-merge.

### PRD additions — release bookkeeping (CHANGELOG + version)

- **R57** Every phase commit and every phase → `<type>/<slug>` PR title MUST follow Conventional Commits using
  a type from `release-please-config.json` (so release-please can derive changelog sections). A phase MAY use a
  more specific type than the feature `<type>` (e.g. a `fix:` phase inside a `feat` feature); a breaking change
  MUST use the `!`/`BREAKING CHANGE:` footer convention.
- **R58** As each phase green-merges into `<type>/<slug>`, `/sw-deliver` MUST maintain `CHANGELOG.md` and
  `version.txt` throughout development: append the phase's entry to the `## [Unreleased]` section under the
  heading mapped from its commit type via the `changelog-sections` map in `release-please-config.json`
  (`feat`→Features, `fix`→Bug Fixes, `perf`→Performance, `revert`→Reverts, `docs`→Documentation; hidden types
  omitted), and update `version.txt` to the **projected** next semver computed from the aggregate of merged
  phase types (breaking→major, `feat`→minor, `fix`/`perf`→patch), never exceeding what release-please would
  compute. These bookkeeping edits are committed as `chore:` so they do not themselves appear in the changelog.
- **R59** `CHANGELOG.md` and `version.txt` are shared-state files: they MUST be treated as contention-serialized
  (R11) and updated **only** by the orchestrator's single locked merge step (R51) on `<type>/<slug>`, never
  concurrently inside parallel phase worktrees. A revert/unstack (R45) MUST also revert the corresponding
  `## [Unreleased]` entry and recompute `version.txt`.
- **R60** release-please remains authoritative at release time on the default branch; the wave's in-development
  edits MUST be release-please-compatible (Keep-a-Changelog `## [Unreleased]` heading; `version.txt` = a bare
  semver line with trailing newline) so release-please's release PR cleanly supersedes/reconciles them.
  `/sw-deliver` MUST NOT create, merge, or tag a release, and MUST NOT push to the default branch (R23 — the
  terminal gate still halts for a human; auto-release stays release-please's job).

### PRD additions — spec availability in worktrees

- **R61** The frozen task list **and** its PRD MUST be readable inside every provisioned phase worktree. Because
  `git worktree add` checks out only tracked files, `docs/prds/` MUST be git-tracked (un-ignored) — this makes
  the frozen task list/PRD present in each phase worktree and visible in the `<type>/<slug> → main` review diff
  (reinforcing R55). `docs/brainstorms/`, `docs/plans/`, and `docs/decisions/` remain gitignored (local-only),
  so PRD front-matter cross-references to those paths (e.g. `source_brainstorm:`) are intentionally dangling in
  the public repo. The orchestrator MUST NOT depend on reading the spec from the main checkout via absolute
  path (which breaks for worktree-local `/sw-execute`/`/sw-ship`).

### PRD additions — resolved scope (memory, nested dispatch)

- **R62** v1 `/sw-deliver` MUST write distilled learnings from a wave run (recurring contention patterns,
  dependent-conflict patterns) to durable memory via `memory-preflight`, routed through
  `scripts/memory-redact.sh` per `rules/memory-guardrails.mdc`; it MUST store only distilled patterns, never raw
  sub-agent logs, transcripts, or secrets (DL-30).
- **R63** The phase `/sw-ship` chain's internal two-stage review MUST run **inline inside the phase worktree**
  when the platform restricts a background sub-agent from spawning child sub-agents. A pre-implementation spike
  MUST confirm whether nested background dispatch is available before the concurrency rollout phase (2b);
  inline review is the default/fallback so phase fidelity never depends on unconfirmed nesting (DL-31).

## Technical Requirements

### Mode resolution and entry

```
/sw-deliver run <arg>
  ├─ arg matches tasks-<n>-<slug>.md (frozen)        → phase-mode (target <type>/<slug>)
  ├─ --edges / item set / existing wave-plan          → multi-feature mode (unchanged)
  └─ ambiguous (both)                                 → halt, disambiguation prompt (R4)
```

`/sw-deliver` echoes resolved mode + target branch + planned waves before any provision (R3).

### Phase dependency table (R37)

`/sw-tasks` appends to the task list:

```markdown
## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 1, 2 |
| 4 | 3 |
```

- A phase with `none` is a wave-1 leaf.
- `/sw-deliver` feeds these edges to `scripts/wave.sh plan` (item = phase number, edge `to:from`), reusing cycle
  detection. Absent table → strict sequential edges `2:1, 3:2, …` (R8) with a missing-edges notice.

### Branch and worktree topology (R16, R35, R35a, R40)

`<type>` is a `release-please-config.json` type (default `feat`; resolved per R35a) — e.g. `feat/<slug>`.

```
main
 └─ <type>/<slug>                                   (base/integration branch; the only thing merged to main)
     ├─ <type>/<slug>-phase-<slug-1>   (worktree) ─ PR → <type>/<slug>, auto-merge on green
     ├─ <type>/<slug>-phase-<slug-2>   (worktree) ─ PR → <type>/<slug>, auto-merge on green   [parallel with phase 1]
     └─ <type>/<slug>-phase-<slug-3>   (worktree, base <type>/<slug> after 1+2 merged)
        (phase branch suffix is the heading-derived <phase-slug> per R35, not the phase number)
```

- `<type>/<slug>` is created from `defaultBaseBranch` at wave start if absent.
- Leaf phases provision with `--base <type>/<slug>` at the current tip; dependents provision once their deps have
  merged (so they start current). If `<type>/<slug>` advances mid-flight, dependents merge `<type>/<slug>` forward
  before their PR (R40).
- Each phase PR targets `<type>/<slug>` (not `main`); `check-gate.sh` runs on the phase PR head.

### Concurrency, result collection, and merge queue (R14, R19, R38, R44)

- Scheduler: greedy-fill to `worktree.parallelCeiling`; queued remainder admitted as slots free. Never exceeds
  ceiling; never unwinds a running phase.
- Each phase runs `/sw-ship` as a background sub-agent in its worktree under the non-interactive contract
  (R48), dispatched per `rules/sw-subagent-dispatch.mdc`. Wave-level slot accounting excludes the phase's own
  internal sub-agent dispatch (R44).
- Outcome collection: each `/sw-ship` writes a machine-readable terminal status to a **durable
  orchestrator-owned path** (R47, e.g. `.cursor/sw-deliver-runs/<phase>/status.json`) before `sw-tmp clean` — the
  orchestrator never reads the sub-agent's private `sw-tmp` run dir. Green → enqueue for merge;
  non-green / crash / timeout → `blocked`.
- Merge queue: single locked orchestrator (R51) performs one in-flight merge into `<type>/<slug>` at a time
  (true merge commits, R50), guarded by a per-phase merge journal. After each merge: incremental whole-feature
  verify (R39), update `CHANGELOG.md` `## [Unreleased]` + `version.txt` as a `chore:` commit (R58/R59), then
  recompute/forward-merge ready dependents (R20/R40).

### State artifacts (R28, R36, R43)

| Artifact | Path | Role | Committed |
|----------|------|------|-----------|
| Wave plan | `.cursor/sw-deliver-plan.json` | DAG, waves, contention, mode marker, `source_task_list`, PRD `<n>`, target `<type>/<slug>` | living (existing) |
| Wave run-state | `.cursor/sw-deliver-state.json` | `source_task_list`, PRD `<n>`, per-phase `status` (`pending`/`in-flight`/`green-merged`/`blocked`/`rejected`), merged commit ref, PR number, worktree path, revert refs | **no** (excluded from `/sw-commit`) |
| Per-phase status | `.cursor/sw-deliver-runs/<phase>/status.json` (R47) | machine-readable `/sw-ship` terminal outcome (`merge-ready-green`/`blocked`+cause) | **no** |
| Orchestrator lock | `.cursor/sw-deliver.lock` (R51) | single-writer `flock` keyed by `<type>/<slug>` + per-phase merge journal | **no** |

Resumption (R29/R50): reconcile run-state against the **pushed remote `<type>/<slug>` tip** (ancestry of phase
merge commits / recorded PR state) as ground truth; skip `green-merged`, resume `blocked`/`pending`, never
re-present a `rejected` terminal PR (R46). An interrupted merge is completed/rolled-back from the journal.

### Failure routing (R25–R27, R38)

| Event | Action |
|-------|--------|
| Phase verify/CI red, stabilize budget exhausted | mark phase `blocked`; route to `/sw-stabilize` |
| Halting local-review P0/P1 (per `/sw-ship` gate) | mark phase `blocked`; surface for human triage |
| Async review (CodeRabbit) not settled on head | hold merge — pending review is non-green (R52) |
| Sub-agent crash/timeout | treat as `blocked` (never silent skip) |
| Incremental whole-feature verify red after a merge | revert offending phase merge (R45); phase→`blocked`; re-block dependents |
| Flaky (intermittent) failure | re-run/quorum before blocking dependents (R27) |
| Transitive dependents of a blocked phase | `blocked` (not started) |
| Independent siblings | continue; auto-merge greens |
| Human rejects terminal `<type>/<slug> → main` PR | record `rejected`; whole-feature → `/sw-stabilize`/`/sw-amend`, per-phase → revert (R45/R46); resume never re-presents |
| Terminal | halt once; consolidated report (R26) |

### Terminal gate (R22, R23, R39, R46)

1. **Every** DAG phase is `green-merged` (zero `blocked`); otherwise halt per R26 (no terminal PR).
2. Incremental whole-feature `verify.*` (R39) has already validated `<type>/<slug>` after each merge.
3. Open/update single `<type>/<slug> → main` PR (linking each phase PR, R55).
4. `check-gate.sh` on the PR head → authoritative whole-feature verdict.
5. Halt at human merge gate (no merge/force-push by `/sw-deliver`). On a human **NO**, apply deny semantics (R46).

### Files touched (implementation checklist)

| Area | Paths |
|------|-------|
| Command | `core/commands/sw-deliver.md` |
| Skill | `core/skills/deliver/SKILL.md` |
| Wave script | `scripts/wave.sh` (mode-aware `plan`: `--mode phase --slug`, phase-branch derivation, file-overlap contention, combined-graph cycle recheck, plan/run-state helpers) + new lock/journal/status helpers. Repo-root `scripts/` is the source; `core/scripts/` is **generated** by `scripts/copy-to-core.sh` and MUST NOT be hand-edited |
| `/sw-ship` contract | `core/commands/sw-ship.md` (non-interactive phase-mode flag/env, R48: suppress pause, emit machine status, exit without merging, halts→`blocked`) |
| Tasks emit | `core/commands/sw-tasks.md`, `core/skills/tasks/SKILL.md` (Phase Dependencies table) |
| Naming rule | `rules/sw-naming.mdc` (`/sw-deliver` two-mode boundary) |
| State exclude | `core/commands/sw-commit.md` (exclude `sw-deliver-state.json`, `.cursor/sw-deliver-runs/`, `.cursor/sw-deliver.lock`) |
| Config schema | `.sw/config.schema.json` + `core/sw-reference/config.schema.json` (`deliver.phaseAckCadence`, `deliver.baseBranchType` default, optional INDEX-status enum) |
| Release bookkeeping | `CHANGELOG.md`, `version.txt` (maintained per phase merge, R58/R59); reads `release-please-config.json` `changelog-sections` (not edited) |
| Tests | `scripts/test/fixtures/deliver-phase-*`, new `scripts/test/run-deliver-fixtures.sh` (wired into `verify.test`) |
| Docs | `README.md`, `documentation/commands.md` (phase-mode play button) |
| Dist | sync to `dist/cursor/`, `dist/claude-code/` |

## Security & Compliance

- **No bare-main writes:** every phase runs in a worktree; `sw-assert-worktree.sh` (PRD 002) guards
  implementation entry **once it exists** — until then R16 enforcement rests on convention or PRD 004's own
  minimal guard (see blocking Dependency). `<type>/<slug>` is mutated only by the single locked orchestrator merge
  queue (R51).
- **Merge-gate integrity:** `check-gate.sh` remains the sole CI/merge oracle for both per-phase and terminal
  gates; `/sw-deliver` never hand-rolls a green verdict and never merges/force-pushes to `main`.
- **No auto-merge to main:** the terminal `<type>/<slug> → main` step halts for a human; auto-merge applies only
  to phase → `<type>/<slug>` and only on live green.
- **No auto-release:** `/sw-deliver` maintains `CHANGELOG.md`/`version.txt` in development only (R57–R60); it never
  creates/merges/tags a release or pushes to the default branch — release-please stays the release authority.
- **State hygiene:** `sw-deliver-state.json` is per-run/per-worktree state — excluded from commits (R36) like
  `shipwright.json`; it records refs/PR numbers, never secrets or transcripts.
- **Memory redaction:** v1 `/sw-deliver` writes distilled learnings (R62) through `memory-preflight`, routed via
  `scripts/memory-redact.sh` per `rules/memory-guardrails.mdc` (the standing redaction chokepoint); it stores
  only distilled patterns (recurring contention, dependent-conflict patterns), never raw sub-agent logs,
  transcripts, or secrets.
- **Sub-agent boundary:** dispatched `/sw-ship` sub-agents inherit `rules/sw-subagent-dispatch.mdc` limits;
  a crashed/timed-out sub-agent fails closed to `blocked`.

## Testing Strategy

### Fixtures (`scripts/test/run-deliver-fixtures.sh`, new; wired into `verify.test`)

| Fixture | Asserts |
|---------|---------|
| `deliver-phase-plan-explicit` | Phase Dependencies table → correct DAG + waves; cycle → refuse |
| `deliver-phase-sequential-fallback` | Metadata-less list → strict sequential edges + missing-edges notice |
| `deliver-phase-contention` | Declared-parallel phases sharing a migration path → serialized + notice |
| `deliver-phase-auto-merge` | Phase merges into `<type>/<slug>` only on live green; non-green never merges |
| `deliver-phase-blast-radius` | Blocked phase blocks transitive dependents; independent siblings still merge |
| `deliver-phase-resume` | Re-run skips `green-merged`; reconciles run-state against merged branches |
| `deliver-phase-frozen-guard` | Unfrozen task list halts with `/sw-freeze` notice (R42) |
| `deliver-mode-detect` | Task-list path → phase-mode; item set/`--edges` → multi-feature; both → disambiguation |
| `deliver-phase-deny` | Human rejects terminal PR → `rejected` state recorded; resume does NOT re-present it (R46) |
| `deliver-phase-revert` | Bad merged green (incremental-verify fail) → `git revert` on `<type>/<slug>`, phase→blocked, dependents re-blocked (R45/R39) |
| `deliver-phase-interrupt-lock` | Process killed mid-merge → resume completes/rolls-back via journal, no double-merge; second concurrent invocation refused (R51) |
| `deliver-phase-async-review` | Phase with pending/late CodeRabbit P1 does NOT auto-merge until barrier settles (R52) |
| `deliver-phase-base-preflight` | Repo whose CI/review only triggers on `main`-base PRs → actionable preflight error, not silent timeout-blocked (R49) |
| `deliver-phase-noninteractive` | `/sw-ship` phase-mode contract: no pause, emits machine status, exits without merging; other halts → `blocked` (R48/R18) |
| `deliver-phase-merge-method` | Phase→`<type>/<slug>` uses merge commits; resume ancestry reconciliation against pushed remote tip is correct under interruption (R50/R29) |
| `deliver-phase-contention-cycle` | Contention edge that would close a cycle on the combined graph → refused with notice (R12) |
| `deliver-phase-branch-type` | Base branch is `<type>/<slug>` with `<type>` from `release-please-config.json` (default `feat`); `--type fix` honored; invalid type → halt (R35/R35a) |
| `deliver-phase-changelog` | Each green merge appends to `## [Unreleased]` under the release-please-mapped section; bookkeeping commit is `chore:`; revert removes the entry (R58/R59) |
| `deliver-phase-version` | `version.txt` reflects the projected next semver from aggregate phase types (feat→minor, fix→patch); never exceeds release-please's computation (R58) |

### Regression

- **No wave fixtures exist today and `verify.test` runs no wave runner** — R34 MUST therefore (a) add
  baseline multi-feature `wave.sh plan` / `integration` fixtures to establish the regression baseline the
  zero-regression goal relies on, and (b) append `bash scripts/test/run-deliver-fixtures.sh` to the `verify.test`
  command chain in `workflow.config.json`.
- Multi-feature `wave.sh plan` / `integration` behavior (branch derivation, hardcoded contention set, cycle
  detection) MUST stay green once baseline fixtures exist (R1, R7).
- `worktree.sh` provision/teardown and `ceiling-check` unchanged.

### Manual smoke (post-implementation)

1. Freeze a small 3-phase task list (phases 1,2 independent; 3 depends on 1,2).
2. `/sw-deliver run <tasks>` → phases 1,2 run in parallel worktrees, auto-merge to `<type>/<slug>` on green; phase 3
   runs after, auto-merges; terminal `<type>/<slug> → main` PR opens and halts.
3. Inject a phase-2 failure → wave continues phase 1, blocks phase 3 (dependent), halts with consolidated
   report.
4. Re-run `/sw-deliver` → resumes from blocked phase 2 only; phase 1 not re-run.
5. `--dry-run` prints DAG/waves/contention with no mutations.
6. After each green merge, `CHANGELOG.md` `## [Unreleased]` gains an entry under the right section and
   `version.txt` reflects the projected bump; `--type fix` produces a `fix/<slug>` base branch.

## Rollout Plan

### Phase 1 — Planning + tasks edges (no execution)

- `/sw-tasks` emits the `## Phase Dependencies` table (R37); `wave.sh plan` accepts phase input; sequential
  fallback + frozen guard. Planning fixtures green.

### Phase 2a — Sequential execution engine

- Mode auto-detect, branch/worktree topology with typed base branch (R35/R35a), `/sw-ship` non-interactive
  contract (R48), durable per-phase status path (R47), `<type>/<slug>` materialization (R53), single-phase
  auto-merge-on-green (sequential), CI/review base-branch preflight (R49), async-review wait (R52),
  `CHANGELOG.md`/`version.txt` maintenance per merge (R57–R60). Auto-merge + non-interactive + changelog
  fixtures green **before** true concurrency lands.

### Phase 2b — Concurrency + integrity

- Concurrent sub-agent dispatch, serialized merge queue + orchestrator lock + merge journal (R51), contention
  safety net + combined-graph cycle recheck (R11/R12), incremental whole-feature verify (R39), revert/unstack
  protocol (R45), blast-radius. Concurrency + interrupt/lock + revert fixtures green.

### Phase 3 — Terminal gate + resume

- Single `<type>/<slug> → main` PR + gate + human halt + **deny semantics** (R46); run-state persistence,
  source-binding (R43), and idempotent resume (R29/R50). Resume + terminal + deny fixtures green. (INDEX
  status write deferred per OQ1.)

### Phase 4 — Docs + dist

- `sw-deliver.md`, wave skill, naming rule, README/commands docs; build/sync to `dist/`; dogfood on a Shipwright
  feature task list.

**Rollout safety:** Additive command behavior; multi-feature mode untouched. No migration required. Legacy
frozen task lists run via sequential fallback.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Unify into one `/sw-deliver`; mode auto-detected; multi-feature preserved | Shared topological-sort + worktree-stacking engine; only the terminal merge unit differs. Brainstorm Key Decision 1–2. |
| DL-2 | Auto-merge phases into `<type>/<slug>` on live green `check-gate.sh`; single human gate at `<type>/<slug> → main` | The "play button" — minimal interaction with full per-phase gating. **Supersedes** prior design (memory #2111) "human gate between phases": that gate's original purpose was early spec-drift detection and merge approval; merge approval is now covered by `check-gate.sh` + async review (R52), and drift detection is mitigated by incremental whole-feature verify (R39) + per-phase review preservation (R55) + optional ack cadence (R56), so the per-phase **human** gate is no longer required by default. Users who want the old behavior set `deliver.phaseAckCadence: 1` (migration path). The single explicit "go" is granted at wave start. |
| DL-3 | Explicit phase edges authoritative in the task list via `## Phase Dependencies` table (R37) | Authoring-time, reviewable, frozen dependency truth beats runtime inference. Brainstorm Key Decision 3. |
| DL-4 | Strict sequential fallback for metadata-less (legacy) lists | Keeps every frozen list runnable with zero edits; cost is only lost parallelism (R8). |
| DL-5 | `<type>/<slug>` is the integration surface; one terminal PR; no `integration/<stamp>` in phase-mode | `<type>/<slug>` already holds every green phase; the terminal PR's CI is the whole-feature check (R22). |
| DL-6 | Continue siblings, block transitive dependents, halt once | Maximize honest progress; one red phase should not strand mergeable independent work (R25). |
| DL-7 | True concurrency via bounded background sub-agents; orchestrator-serialized `<type>/<slug>` merges | Wall-clock parallelism with no write contention on the feature branch (R14/R19/R44). |
| DL-8 | Shared-file safety net serializes declared-parallel overlaps; never reorders | A declaration of independence cannot make a shared migration concurrent-safe (R11/R12). |
| DL-9 | Base branch `<type>/<slug>` (`<type>` ∈ `release-please-config.json` types, default `feat`) + per-phase `<type>/<slug>-phase-<phase-slug>` | The old `pf/` prefix was a plan-forge leftover; aligning the base-branch prefix with Conventional-Commit / release-please types keeps branch semantics consistent with the release tooling and `/sw-start` shape (R35/R35a). |
| DL-10 | Separate plan vs run-state artifacts; run-state uncommitted | Plan is reviewable/living; run-state is per-run, git-reconcilable, excluded from commits (R36). |
| DL-11 | Merge `<type>/<slug>` forward into dependents (no rebase of published branches); conflict → blocked | Safe for pushed branches; conflicts are human decisions, not auto-resolves (R40). |
| DL-12 | Whole-feature `verify.*` runs **incrementally after each `<type>/<slug>` advance**, not only pre-terminal-PR | Attributes cross-phase emergent failures to the introducing merge; declared-independent phases can be semantically coupled beyond file overlap (R39; resolves OQ2). |
| DL-13 | Require frozen task list (R42); `--dry-run` / `--from` supported (R41) | Phase-mode operates on frozen specs only; dry-run + resume are core to a re-run-heavy orchestrator. |
| DL-14 | Contention serialization emits a runtime notice only (no task-list feedback in v1) | Keeps v1 scope bounded; durable feedback to `/sw-tasks` deferred (brainstorm OQ5). |
| DL-15 | Define a `git revert`-based revert/unstack protocol for bad merged greens (R45) | Auto-merge needs a backout primitive; underlies cross-phase conflict, flaky-green, and per-phase rejection recovery without rewriting `<type>/<slug>` history. |
| DL-16 | Define terminal-PR **deny** semantics; resume never re-presents a rejected PR (R46) | The single human gate's "no" path determines whether high-autonomy auto-merge is actually safe. |
| DL-17 | Durable orchestrator-owned per-phase status path; not `sw-tmp` (R47/R38) | `sw-tmp` run dirs are private + cleaned at chain end → unreadable by the orchestrator; the merge queue needs a durable contract. |
| DL-18 | Explicit non-interactive phase-mode contract on `/sw-ship` (R48/R18) | `/sw-ship` has no pause-suppression flag today and has other human-halt conditions; a background sub-agent needs a deterministic non-interactive mode that emits machine status and never merges. |
| DL-19 | Preflight CI/review trigger on `<type>/**`-base PRs (R49) | If CI/review only fire on `main`-base PRs, every phase PR is `checkCount==0`→blocked or never-reviewed→timeout, silently defeating phase-mode. |
| DL-20 | Pin phase→<type>/<slug> to true **merge commits**; ground truth = pushed remote `<type>/<slug>` tip (R50/R29) | Squash/rebase break ancestry-based resume reconciliation → phantom re-runs / double-merge; merge commits also preserve per-phase review granularity. |
| DL-21 | Single-writer orchestrator lock + per-phase merge journal + serialized provisioning (R51) | Non-atomic merge sequence, concurrent invocations, and provisioning races can corrupt/diverge `<type>/<slug>`; lock + journal make interrupt/resume deterministic. |
| DL-22 | Auto-merge waits for async review barrier to settle; pending review is non-green (R52) | Closes the window where CodeRabbit P1 findings post after an auto-merge already landed. |
| DL-23 | Hold the play-button; add observability + granularity mitigations (R54/R55/R56) | Product panel challenge accepted as mitigations, not reversal: run-log progress surface, no-squash + linked phase PRs, optional ack cadence (default off). |
| DL-24 | Base-branch prefix is a `release-please-config.json` type (default `feat`), replacing `pf/` (R35/R35a) | `pf/` was a plan-forge leftover; Conventional-Commit-typed branches keep branch semantics aligned with the release tooling and make the work kind explicit. |
| DL-25 | Wave maintains `CHANGELOG.md` (`## [Unreleased]`) + `version.txt` per phase merge; release-please stays authoritative at release (R57–R60) | "Maintained throughout development" — the in-dev state stays coherent as phases land, using Conventional-Commit types so release-please's release PR reconciles cleanly; `/sw-deliver` never auto-releases/tags. |
| DL-26 | Track `docs/prds/` (un-ignore); keep brainstorms/plans/decisions local-only (R61) | `git worktree` only checks out tracked files, so the frozen task list/PRD must be tracked to be present in each phase worktree; tracking also surfaces the spec in the review diff. Upstream thinking stays private on the public repo. |
| DL-27 | INDEX status write reuses existing `not-started`/`complete` vocabulary; no new `in-progress` value (R43) | Avoids introducing an enum value the rest of the workflow doesn't yet understand; resolves OQ1. |
| DL-28 | `--from <phase>` refuses when upstream deps aren't `green-merged` (R41) | Explicit, predictable resume; avoids silently auto-running prerequisites the user didn't ask for. Resolves OQ3. |
| DL-29 | `<type>/<slug>` lives in a dedicated orchestrator worktree, not counted against `parallelCeiling` (R53) | Clean local surface for the serialized merge queue + R40 forward-merges; infrastructure shouldn't steal a phase slot. Resolves OQ4. |
| DL-30 | v1 writes distilled learnings to durable memory via `memory-redact.sh` (R62) | Compounding value from wave runs (contention/conflict patterns) with the standing redaction chokepoint. Resolves OQ6. |
| DL-31 | Inline-review fallback inside the phase worktree; spike confirms nested dispatch before phase 2b (R63) | Phase `/sw-ship` fidelity must not depend on unconfirmed platform nesting limits. Resolves OQ5. |
| DL-32 | Projected `version.txt` bump written by default each merge (R58) | "Maintained throughout development" means version coherence by default, not opt-in; release-please reconciles at release. Resolves OQ7. |
| DL-33 | Rename `/sw-wave → /sw-deliver` (skill `deliver`, config `deliver.*`); retain "wave" only as the internal dependency-ordered-batch concept + `scripts/wave.sh`; no `/sw-wave` alias | "Wave" named the multi-feature batching mechanism, not the command's new default purpose — driving a frozen task list's phases to one merge gate. `/sw-deliver` names the outcome and slots cleanly above `/sw-ship` (ship one phase → deliver the feature) as the default implementation entry point. Pre-release plugin, so no alias is needed (R64). |

## Open Questions

None — all prior open questions are resolved and recorded in the Decision Log: OQ1→DL-27, OQ2→DL-12,
OQ3→DL-28, OQ4→DL-29, OQ5→DL-31, OQ6→DL-30, OQ7→DL-32.
