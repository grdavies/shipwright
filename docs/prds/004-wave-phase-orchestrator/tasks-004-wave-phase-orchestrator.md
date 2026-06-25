---
date: 2026-06-24
topic: wave-phase-orchestrator
prd: docs/prds/004-wave-phase-orchestrator/004-prd-wave-phase-orchestrator.md
frozen: true
frozen_at: 2026-06-24
---

# Task list — PRD 004 `/sw-deliver` phase orchestrator

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Command | `core/commands/sw-deliver.md` (rename from `sw-wave.md`) |
| Skill | `core/skills/deliver/SKILL.md` (rename from `skills/wave/`) |
| Wave engine | `scripts/wave.sh` (+ generated `core/scripts/wave.sh`) |
| `/sw-ship` contract | `core/commands/sw-ship.md` |
| Tasks emit | `core/commands/sw-tasks.md`, `core/skills/tasks/SKILL.md` |
| Naming | `rules/sw-naming.mdc` |
| State exclude | `core/commands/sw-commit.md` |
| Config | `.sw/config.schema.json`, `.sw/workflow.config.example.json` |
| Layout | `.sw/layout.md`, `core/sw-reference/layout.md` |
| Release bookkeeping | `CHANGELOG.md`, `version.txt`, `release-please-config.json` (read-only) |
| Worktree guard | `scripts/sw-assert-worktree.sh` (PRD 002 dependency) |
| Parallelism | `skills/parallelism/`, `rules/sw-subagent-dispatch.mdc` |
| Memory | `scripts/memory-redact.sh`, `rules/memory-guardrails.mdc` |
| Fixtures | `scripts/test/fixtures/deliver-phase-*`, `scripts/test/run-deliver-fixtures.sh` |
| Build chain | `scripts/copy-to-core.sh`, `python3 -m sw generate --all` |
| User docs | `README.md`, `documentation/commands.md` |
| Gitignore | `.gitignore` (`docs/prds/` tracked per R61) |

## Notes

- PRD 002's `sw-assert-worktree.sh` may not exist yet; phase 7 must enforce R16 via that guard or a minimal
  bare-main assertion until 002 lands.
- Multi-feature mode (`integration/<stamp>`) must remain unchanged; baseline `wave.sh` fixtures are part of
  phase 13 (R34 regression).
- Artifact paths use `.cursor/sw-deliver-*.json` and `.cursor/sw-deliver-runs/` per R64; no `/sw-wave` alias.
- `docs/brainstorms/` stays gitignored; only `docs/prds/` is un-ignored for R61.

## Tasks

### 1. Rename `/sw-wave` → `/sw-deliver` and naming boundary (S)

- [x] 1.1 Rename command and skill paths; update artifact names (R64)
  - **File:** `core/commands/sw-wave.md` → `core/commands/sw-deliver.md`, `core/skills/wave/` → `core/skills/deliver/`
  - **Expected:** no `sw-wave` command file remains; skill frontmatter `name: sw-deliver`; plan/state/lock paths use `sw-deliver-*`
  - **R-IDs:** R64

- [x] 1.2 Update naming rule and grep-sweep references (R31, R32, R64)
  - **File:** `rules/sw-naming.mdc`, `README.md`, `documentation/commands.md`, `.sw/layout.md`
  - **Expected:** `/sw-deliver` two-mode boundary documented; scope + non-goals in command description; no stale `/sw-wave` in rules/docs
  - **R-IDs:** R31, R32, R64

- [x] 1.3 Add config keys `deliver.phaseAckCadence` and `deliver.baseBranchType` (R56, R35)
  - **File:** `.sw/config.schema.json`, `.sw/workflow.config.example.json`
  - **Expected:** `deliver.phaseAckCadence` integer default `0`; `deliver.baseBranchType` optional override; schema validates
  - **R-IDs:** R56, R35

### 2. Phase-mode planning in `wave.sh` (M)

- [x] 2.1 Mode auto-detect, disambiguation halt, and pre-flight echo (R1–R4, R3)
  - **File:** `scripts/wave.sh`, `core/commands/sw-deliver.md`
  - **Expected:** task-list path → phase-mode; item set/`--edges`/plan → multi-feature; both → disambiguation halt; echoes mode + `<type>/<slug>` + waves before provision
  - **R-IDs:** R1, R2, R3, R4

- [x] 2.2 Phase DAG from `## Phase Dependencies` + cycle refuse (R7, R9, R10)
  - **File:** `scripts/wave.sh`
  - **Expected:** parses phase table; feeds `wave.sh plan`; cycle → refuse; each `### N.` maps to one orchestrated unit with sub-task scope + R-IDs carried forward
  - **R-IDs:** R7, R9, R10

- [x] 2.3 Sequential fallback when metadata absent (R8)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** no `## Phase Dependencies` → edges `2:1, 3:2, …`; no parallelism; emits missing-edges notice
  - **R-IDs:** R8

- [x] 2.4 Branch type resolution and plan artifact schema (R35, R36, R43)
  - **File:** `scripts/wave.sh`, `.cursor/sw-deliver-plan.json` schema in skill
  - **Expected:** `--type` > frontmatter `type:` > default `feat`; invalid type halts; plan records mode marker, DAG, waves, contention, `source_task_list`, PRD `<n>`, target `<type>/<slug>`
  - **R-IDs:** R35, R36, R43

- [x] 2.5 Frozen guard, dry-run, and `--from` resume guard (R41, R42)
  - **File:** `core/commands/sw-deliver.md`, `scripts/wave.sh`
  - **Expected:** unfrozen task list halts with `/sw-freeze` notice; `--dry-run` prints DAG/waves/contention with no mutations; `--from` refuses when upstream deps not `green-merged`
  - **R-IDs:** R41, R42

### 3. `/sw-tasks` Phase Dependencies emission (S)

- [x] 3.1 Emit `## Phase Dependencies` table from task generation (R5, R6, R37)
  - **File:** `core/commands/sw-tasks.md`, `core/skills/tasks/SKILL.md`
  - **Expected:** every generated task list includes machine-parseable `| Phase | Depends on |` table inside the artifact; human-reviewable; no sidecar
  - **R-IDs:** R5, R6, R37

- [x] 3.2 Document sequential-fallback contract for authors (R8)
  - **File:** `core/skills/tasks/SKILL.md`
  - **Expected:** skill states that omitting the table triggers R8 sequential fallback in `/sw-deliver`
  - **R-IDs:** R8

### 4. `/sw-ship` non-interactive phase-mode contract (M)

- [x] 4.1 Add `--phase-mode` / `SW_PHASE_MODE` contract (R48, R18)
  - **File:** `core/commands/sw-ship.md`
  - **Expected:** suppresses terminal "ready to merge" pause; writes `merge-ready-green` or `blocked`+cause to durable path; exits without merging; other human halts → `blocked` not prompt
  - **R-IDs:** R48, R18

- [x] 4.2 Nested sub-agent dispatch spike and inline-review fallback doc (R63)
  - **File:** `core/skills/deliver/SKILL.md`, spike note in deliver skill or `docs/plans/` (local)
  - **Expected:** spike records whether nested background dispatch is available; inline two-stage review documented as default/fallback when nesting unavailable
  - **R-IDs:** R63

### 5. State artifacts, lock, and progress surface (M)

- [x] 5.1 Run-state schema and per-phase status paths (R28, R36, R47, R38)
  - **File:** `core/skills/deliver/SKILL.md`, `scripts/wave.sh` helpers
  - **Expected:** `.cursor/sw-deliver-state.json` with `pending`/`in-flight`/`green-merged`/`blocked`/`rejected`; `.cursor/sw-deliver-runs/<phase>/status.json` for `/sw-ship` terminal outcomes; not committed
  - **R-IDs:** R28, R36, R47, R38

- [x] 5.2 Orchestrator lock and merge journal (R51)
  - **File:** `scripts/wave.sh` (lock/journal helpers), `core/commands/sw-commit.md`
  - **Expected:** `flock` on `.cursor/sw-deliver.lock` keyed by `<type>/<slug>`; second invocation refuses; per-phase merge journal detects interrupted merge; state paths excluded from `/sw-commit`
  - **R-IDs:** R51

- [x] 5.3 Append-only progress run log (R54)
  - **File:** `core/skills/deliver/SKILL.md`, `scripts/wave.sh`
  - **Expected:** log append on each phase transition (`in-flight`/`green-merged`/`blocked`); terminal completion/blocked notification
  - **R-IDs:** R54

### 6. Contention preflight and parallel scheduling (M)

- [x] 6.1 Shared-file safety net + combined-graph cycle recheck (R11, R12)
  - **File:** `scripts/wave.sh`, `skills/parallelism/`
  - **Expected:** pre-flight serializes overlapping `**File:**` paths (migrations, shared config, INDEX counters, CHANGELOG/version contention); emits contention notice; injected edges respect declared order; combined graph cycle → refuse
  - **R-IDs:** R11, R12

- [x] 6.2 Greedy parallel scheduler with ceiling accounting (R14, R15, R44)
  - **File:** `core/skills/deliver/SKILL.md`, `scripts/wave.sh`
  - **Expected:** wave-level `/sw-ship` worktrees count against `worktree.parallelCeiling`; internal sub-agent dispatch within a phase does not; never exceeds ceiling or unwinds running phase; obeys `sw-subagent-dispatch.mdc`
  - **R-IDs:** R14, R15, R44

### 7. Orchestrator worktree, branches, and lifecycle (M)

- [x] 7.1 Branch topology and orchestrator worktree (R16, R35, R53)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** `<type>/<slug>` base; per-phase `<type>/<slug>-phase-<phase-slug>`; dedicated orchestrator worktree for merge queue; orchestrator worktree does not consume ceiling slot
  - **R-IDs:** R16, R35, R53

- [x] 7.2 Dependent forward-merge and worktree teardown (R20, R21, R40)
  - **File:** `scripts/wave.sh`
  - **Expected:** after merge, dependents advance to new `<type>/<slug>` tip; mid-flight forward-merge via merge (not rebase) in dependent worktree; conflicts → `blocked`; teardown via `git worktree remove` + prune only
  - **R-IDs:** R20, R21, R40

- [x] 7.3 Bare-main guard at implementation entry (R16)
  - **File:** `core/commands/sw-deliver.md`, integration with `scripts/sw-assert-worktree.sh` or minimal guard
  - **Expected:** no phase implementation on bare `main`; guard invoked before phase `/sw-ship` writes
  - **R-IDs:** R16

### 8. Phase execution, merge queue, and review barrier (L)

- [x] 8.1 Full `/sw-ship` per phase in isolated worktree (R13)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/deliver/SKILL.md`
  - **Expected:** each phase runs complete `/sw-ship` chain under R48 contract; orchestrator does not bypass any step
  - **R-IDs:** R13

- [x] 8.2 Serialized merge queue with true merge commits (R17, R19, R50)
  - **File:** `scripts/wave.sh`
  - **Expected:** one merge in flight; auto-merge only on live `check-gate.sh` green; uses merge commits (no squash/rebase); ancestry predicate for resume documented
  - **R-IDs:** R17, R19, R50

- [x] 8.3 Async review barrier before auto-merge (R52)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** pending/not-settled review on phase PR head is non-green; merge waits until barrier settles
  - **R-IDs:** R52

- [x] 8.4 Per-phase PR granularity in terminal report (R55, R57)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** terminal report links each auto-merged phase PR; phase commits/PR titles use Conventional Commits types from `release-please-config.json`
  - **R-IDs:** R55, R57

- [x] 8.5 Collect sub-agent outcomes from durable status path (R38)
  - **File:** `scripts/wave.sh`
  - **Expected:** orchestrator reads `.cursor/sw-deliver-runs/<phase>/status.json` before merge enqueue; crash/timeout → `blocked`, never silent skip
  - **R-IDs:** R38

### 9. Release bookkeeping on `<type>/<slug>` (M)

- [x] 9.1 CHANGELOG and version.txt maintenance per merge (R58, R59, R60)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** each green merge appends to `## [Unreleased]` under release-please-mapped section; `version.txt` projected semver; `chore:` bookkeeping commit; orchestrator-only writes (contention-serialized); release-please-compatible format
  - **R-IDs:** R58, R59, R60

- [x] 9.2 Revert bookkeeping on unstack (R45, R59)
  - **File:** `scripts/wave.sh`
  - **Expected:** `git revert` of phase merge also removes matching `## [Unreleased]` entry and recomputes `version.txt`
  - **R-IDs:** R45, R59

### 10. Verify, failure blast radius, and stabilize routing (M)

- [x] 10.1 Incremental whole-feature verify after each merge (R39)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** configured `verify.*` runs on `<type>/<slug>` head after every phase merge; failure routes to `/sw-stabilize` on `<type>/<slug>`, marks phase `blocked`, triggers revert protocol; does not open/advance terminal PR
  - **R-IDs:** R39

- [x] 10.2 Blast-radius policy and consolidated halt report (R25, R26)
  - **File:** `core/skills/deliver/SKILL.md`, `scripts/wave.sh`
  - **Expected:** failed phase blocks transitive dependents only; independent siblings continue and auto-merge greens; single consolidated blocker report with recommended next command per blocker
  - **R-IDs:** R25, R26

- [x] 10.3 Stabilize routing and flaky-vs-deterministic distinction (R27)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** blocked/red phase routes to `/sw-stabilize`; per-phase stabilize budget obeys dispatch hard stops; whole-feature stabilize has distinct budget; flaky failures get re-run/quorum before blocking dependents
  - **R-IDs:** R27

- [x] 10.4 Revert/unstack protocol and terminal deny semantics (R45, R46)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** bad merged green → `git revert` on `<type>/<slug>`, phase→`blocked`, dependents re-blocked; human terminal rejection records `rejected`; resume never re-presents rejected terminal PR
  - **R-IDs:** R45, R46

### 11. Terminal PR gate, resumption, and ack cadence (M)

- [x] 11.1 Terminal `<type>/<slug> → main` PR and gate halt (R22, R23, R24)
  - **File:** `core/commands/sw-deliver.md`, `scripts/wave.sh`
  - **Expected:** opens/updates single terminal PR only when all phases `green-merged`; no `integration/<stamp>` in phase-mode; `check-gate.sh` on PR head; halts at human merge gate; report matches `/sw-ready` form
  - **R-IDs:** R22, R23, R24

- [x] 11.2 Idempotent resume against pushed remote tip (R29, R30, R50)
  - **File:** `scripts/wave.sh`
  - **Expected:** re-invocation skips `green-merged`; resumes `blocked`/`pending`; reconciles against pushed remote `<type>/<slug>` tip; no duplicate branches/PRs/double-merges; safe interrupt/resume
  - **R-IDs:** R29, R30, R50

- [x] 11.3 Optional phase ack cadence (R56)
  - **File:** `core/commands/sw-deliver.md`, `scripts/wave.sh`
  - **Expected:** `deliver.phaseAckCadence: K` pauses for human ack after every K merges; default `0` = off
  - **R-IDs:** R56

- [x] 11.4 INDEX status vocabulary unchanged (R43)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** run-state binds `source_task_list` + PRD number; INDEX uses only `not-started`/`complete` — no `in-progress`
  - **R-IDs:** R43

### 12. Preflight, spec availability, and memory learnings (S)

- [x] 12.1 CI/review base-branch preflight (R49)
  - **File:** `scripts/wave.sh`, `core/skills/deliver/SKILL.md`
  - **Expected:** before phases, verify CI workflows and review provider trigger on PRs with base `<type>/**`; actionable error if not — no silent timeout-blocked degradation
  - **R-IDs:** R49

- [x] 12.2 Un-ignore `docs/prds/` for worktree spec visibility (R61)
  - **File:** `.gitignore`
  - **Expected:** `docs/prds/` tracked; frozen task list + PRD readable in every phase worktree; orchestrator does not read spec via absolute main-checkout path
  - **R-IDs:** R61

- [x] 12.3 Distilled wave learnings to memory (R62)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** post-run writes contention/conflict patterns via `memory-preflight` + `memory-redact.sh`; no raw logs/transcripts/secrets
  - **R-IDs:** R62

### 13. Fixtures, build chain, and user documentation (M)

- [ ] 13.1 Deliver phase-mode fixture suite (R34)
  - **File:** `scripts/test/fixtures/deliver-phase-*`, `scripts/test/run-deliver-fixtures.sh`
  - **Expected:** fixtures per Testing Strategy table (plan, sequential fallback, contention, auto-merge, blast-radius, resume, frozen guard, mode-detect, deny, revert, interrupt-lock, async-review, base-preflight, noninteractive, merge-method, contention-cycle, branch-type, changelog, version); wired into `verify.test`
  - **R-IDs:** R34

- [ ] 13.2 Multi-feature regression baseline fixtures (R1, R34)
  - **File:** `scripts/test/fixtures/deliver-phase-*` or `wave-*` baseline, `scripts/test/run-deliver-fixtures.sh`
  - **Expected:** existing multi-feature `wave.sh plan`/`integration` behavior has baseline fixtures and stays green
  - **R-IDs:** R1, R34

- [ ] 13.3 Regenerate `core/` + `dist/` + update layout reference (R33, R31)
  - **File:** run `scripts/copy-to-core.sh`, `python3 -m sw generate --all`; `.sw/layout.md`, `core/sw-reference/layout.md`
  - **Expected:** `sw-deliver` artifacts in dist; layout documents `sw-deliver-plan.json`; emitter/parity fixtures green; no hand-edits under `dist/`
  - **R-IDs:** R33, R31

- [ ] 13.4 User-facing documentation for phase-mode play button (R31)
  - **File:** `README.md`, `documentation/commands.md`
  - **Expected:** documents `/sw-deliver run <frozen-tasks>`, mode auto-detect, single terminal merge gate, resumption, `--dry-run`
  - **R-IDs:** R31

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1 |
| 5 | 2 |
| 6 | 2, 5 |
| 7 | 5 |
| 8 | 4, 6, 7 |
| 9 | 8 |
| 10 | 8, 9 |
| 11 | 10 |
| 12 | 7 |
| 13 | 11, 12 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 2.1, 13.2 | deliver-mode-detect: task-list → phase-mode; multi-feature baseline fixtures green |
| R2 | 2.1 | deliver-mode-detect: item set/`--edges` → multi-feature |
| R3 | 2.1 | deliver-mode-detect: pre-flight echoes mode + `<type>/<slug>` + waves |
| R4 | 2.1 | deliver-mode-detect: both inputs → disambiguation halt |
| R5 | 3.1 | deliver-phase-plan-explicit: Phase Dependencies table parsed as authoritative edges |
| R6 | 3.1 | deliver-phase-plan-explicit: table is machine-parseable inside task-list artifact |
| R7 | 2.2 | deliver-phase-plan-explicit: cycle in declared edges → refuse |
| R8 | 2.3, 3.2 | deliver-phase-sequential-fallback: no table → sequential edges + notice |
| R9 | 2.2 | deliver-phase-plan-explicit: each `### N.` maps to one orchestrated unit |
| R10 | 2.2 | deliver-phase-plan-explicit: dependency-ordered waves persisted in plan |
| R11 | 6.1 | deliver-phase-contention: overlapping file paths force serialization + notice |
| R12 | 6.1 | deliver-phase-contention-cycle: injected edge closing cycle → refuse |
| R13 | 8.1 | deliver-phase-noninteractive: full `/sw-ship` chain per phase, no bypass |
| R14 | 6.2 | deliver-phase-contention: parallel wave batch bounded by ceiling |
| R15 | 6.2 | deliver-phase-contention: dispatch obeys subagent-dispatch hard stops |
| R16 | 7.1, 7.3 | deliver-phase-auto-merge: phases run in worktrees, not bare main |
| R17 | 8.2 | deliver-phase-auto-merge: merge only on live green gate |
| R18 | 4.1 | deliver-phase-noninteractive: no terminal pause; exit without merging |
| R19 | 8.2 | deliver-phase-auto-merge: single merge in flight despite concurrent phases |
| R20 | 7.2 | deliver-phase-resume: dependents advance to new `<type>/<slug>` tip |
| R21 | 7.2 | deliver-phase-auto-merge: worktree teardown via `git worktree remove` |
| R22 | 11.1 | deliver-phase-auto-merge: terminal PR only when all phases green-merged |
| R23 | 11.1 | deliver-phase-auto-merge: terminal gate halts without merge to main |
| R24 | 11.1 | deliver-phase-auto-merge: terminal report states gate verdict + readiness |
| R25 | 10.2 | deliver-phase-blast-radius: siblings continue; dependents blocked |
| R26 | 10.2 | deliver-phase-blast-radius: single consolidated blocker report |
| R27 | 10.3 | deliver-phase-blast-radius: blocked phase routes to `/sw-stabilize` |
| R28 | 5.1 | deliver-phase-resume: run-state records pending/in-flight/green-merged/blocked |
| R29 | 11.2 | deliver-phase-resume: skips green-merged; reconciles against remote tip |
| R30 | 11.2 | deliver-phase-resume: interrupt/resume without duplicate branches/PRs |
| R31 | 1.2, 13.3, 13.4 | docs review + emitter fixtures: command/skill document both modes |
| R32 | 1.2 | grep: sw-deliver description states scope and non-goals |
| R33 | 13.3 | emitter + parity fixtures green after dist regenerate |
| R34 | 13.1, 13.2 | run-deliver-fixtures.sh wired into verify.test |
| R35 | 2.4, 7.1 | deliver-phase-branch-type: `<type>/<slug>` and per-phase branch convention |
| R36 | 2.4, 5.1 | deliver-phase-plan-explicit: plan and run-state are separate artifacts |
| R37 | 3.1 | deliver-phase-plan-explicit: `## Phase Dependencies` table format |
| R38 | 5.1, 8.5 | deliver-phase-noninteractive: durable status path survives sw-tmp clean |
| R39 | 10.1 | deliver-phase-revert: incremental verify failure triggers revert + block |
| R40 | 7.2 | deliver-phase-blast-radius: forward-merge conflict surfaces as blocked |
| R41 | 2.5 | deliver-phase-plan-explicit: `--dry-run` and `--from` prerequisite guard |
| R42 | 2.5 | deliver-phase-frozen-guard: unfrozen task list halts |
| R43 | 2.4, 11.4 | deliver-phase-resume: plan/state bind source_task_list + PRD number |
| R44 | 6.2 | deliver-phase-contention: ceiling counts wave worktrees only |
| R45 | 9.2, 10.4 | deliver-phase-revert: git revert on bad merge; dependents re-blocked |
| R46 | 10.4, 11.1 | deliver-phase-deny: rejected terminal state; resume does not re-present |
| R47 | 5.1 | deliver-phase-noninteractive: orchestrator-owned per-phase status path |
| R48 | 4.1 | deliver-phase-noninteractive: phase-mode contract halts → blocked status |
| R49 | 12.1 | deliver-phase-base-preflight: non-default-base CI misconfig → actionable error |
| R50 | 8.2, 11.2 | deliver-phase-merge-method: merge commits + ancestry reconciliation |
| R51 | 5.2 | deliver-phase-interrupt-lock: flock refuse + journal no double-merge |
| R52 | 8.3 | deliver-phase-async-review: pending review blocks auto-merge |
| R53 | 7.1 | deliver-phase-auto-merge: dedicated orchestrator worktree for merge queue |
| R54 | 5.3 | deliver-phase-resume: append-only run log on state transitions |
| R55 | 8.4 | deliver-phase-auto-merge: terminal report links per-phase PRs |
| R56 | 1.3, 11.3 | config-schema: deliver.phaseAckCadence default 0; K>0 pauses |
| R57 | 8.4 | deliver-phase-changelog: Conventional Commits on phase PR titles |
| R58 | 9.1 | deliver-phase-changelog: Unreleased entry per green merge |
| R59 | 9.1, 9.2 | deliver-phase-changelog: orchestrator-only writes; revert removes entry |
| R60 | 9.1 | deliver-phase-version: release-please-compatible Unreleased + version.txt |
| R61 | 12.2 | deliver-phase-auto-merge: frozen PRD/tasks readable in phase worktree |
| R62 | 12.3 | memory-redact fixture: distilled patterns only, no transcripts |
| R63 | 4.2 | deliver-phase-noninteractive: inline review fallback documented post-spike |
| R64 | 1.1, 1.2 | grep: no `/sw-wave` command; artifacts use sw-deliver-* paths |
