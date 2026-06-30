---
date: 2026-06-24
topic: first-run-onboarding-ux
prd: docs/prds/002-first-run-onboarding-ux/002-prd-first-run-onboarding-ux.md
frozen: true
frozen_at: 2026-06-24
---

# Task list — PRD 002 First-Run Onboarding UX

> **Status: complete.** Delivered in `ad196d7` (feat(onboarding): first-run onboarding UX (PRD 002));
> later built upon by PRD 005 (`doc.afterTasks` dispatch amendments A1/A2) and PRD 007. Checkboxes
> ticked retroactively after verifying landed artifacts and green fixture suites
> (`run-onboarding-ux-fixtures.sh`). No source re-implementation performed.

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Schema / examples | `.sw/config.schema.json`, `.sw/workflow.config.example.json` |
| Gate | `scripts/check-gate.py`, `providers/review/CAPABILITIES.md` |
| Worktree guard | `scripts/sw-assert-worktree.py` (new) |
| Orchestrators | `commands/sw-doc.md`, `commands/sw-tasks.md`, `commands/sw-ship.md`, `commands/sw-setup.md`, `commands/sw-review.md` |
| Skills | `skills/tasks/SKILL.md` |
| Rules | `rules/sw-naming.mdc` |
| Human surfaces | `commands/sw-ready.md`, living-status skill/command |
| Fixtures | `scripts/test/run-gate-fixtures.sh`, `scripts/test/fixtures/onboarding-ux/` (new) |
| Build chain | `scripts/copy-to-core.sh`, `scripts/test/fixtures/parity/cursor-golden.manifest` |
| User docs | `README.md`, `documentation/getting-started.md`, `documentation/commands.md` |

## Tasks

### 1. Review config + gate honesty (S)

- [x] 1.1 Add `doc.afterTasks` to schema and example config (R1, R7)
  - **File:** `.sw/config.schema.json`, `.sw/workflow.config.example.json`
  - **Expected:** `doc.afterTasks` enum `[stop, confirm, auto]`, default `confirm`; schema validates; fixture passes
  - **R-IDs:** R1, R7

- [x] 1.2 Flip `review.provider` default to `none` and deprecate `review.enabled` (R11, R13, R18)
  - **File:** `.sw/config.schema.json`, `.sw/workflow.config.example.json`
  - **Expected:** schema default `none`; `review.enabled` description marked deprecated; config-schema fixture passes
  - **R-IDs:** R11, R13, R18

- [x] 1.3 Update `check-gate.py` fallback, state rename, and honest reasons (R12, R20, R21, R28)
  - **File:** `scripts/check-gate.py`, `providers/review/CAPABILITIES.md`
  - **Expected:** fallback `none`; never-configured → `unconfigured` (not "review landed"); explicit opt-out → `off`; green-reason switch updated; `run-gate-fixtures.sh` passes with `state=off`
  - **R-IDs:** R12, R20, R21, R28

- [x] 1.4 Add gate fixtures: unconfigured vs off, no-disabled-literal grep (R20, R28, R21)
  - **File:** `scripts/test/fixtures/onboarding-ux/gate-*.sh`, `scripts/test/run-onboarding-ux-fixtures.sh` (new)
  - **Expected:** fixtures assert `unconfigured` vs `off` reasons; grep test finds no `disabled` literal in gate code/consumers/fixtures; wired into `verify.test`
  - **R-IDs:** R20, R21, R28

- [x] 1.5 Deprecation warning off stdout JSON contract (R17, R22)
  - **File:** `scripts/check-gate.py`, `commands/sw-setup.md`
  - **Expected:** `review.enabled:false` keeps stdout valid single-object JSON; warning on stderr and/or `deprecations[]` and/or `/sw-setup` doctor; migration fixture passes
  - **R-IDs:** R17, R22

### 2. Deterministic worktree guard (S)

- [x] 2.1 Implement `sw-assert-worktree.py` fail-closed guard (R6, R27)
  - **File:** `scripts/sw-assert-worktree.py` (new)
  - **Expected:** aborts when `HEAD` is default branch with no active worktree gitdir; allows hotfix/release on-main paths; exit 0 on valid worktree
  - **R-IDs:** R6, R27

- [x] 2.2 Worktree guard fixtures (R27)
  - **File:** `scripts/test/fixtures/onboarding-ux/worktree-guard-*.sh`
  - **Expected:** negative fixture blocks simulated impl on bare `main`; positive fixture allows permitted on-main flow; runner exits 0
  - **R-IDs:** R27

### 3. `/sw-tasks` single-pass generation (S)

- [x] 3.1 Remove Go gate from tasks command + skill (R9, R24, R25)
  - **File:** `commands/sw-tasks.md`, `skills/tasks/SKILL.md`
  - **Expected:** no "pause for Go" step; collision policy rewritten for single-pass; guardrail "Go gate is mandatory" removed; doc-pipeline fixture passes
  - **R-IDs:** R9, R24, R25

- [x] 3.2 Add tasks single-pass fixture (R9, R25)
  - **File:** `scripts/test/fixtures/onboarding-ux/tasks-single-pass.sh`
  - **Expected:** fixture asserts complete list (parents + sub-tasks + `## Traceability`) in one pass with no intervention prompt
  - **R-IDs:** R9, R25

### 4. Doc boundary + orchestrator dispatch (M)

- [x] 4.1 Rewrite `/sw-doc` afterTasks branch (stop/confirm/auto-dispatch) (R1–R5, R8, R10, R24, R26)
  - **File:** `commands/sw-doc.md`
  - **Expected:** reads `doc.afterTasks` + `--after-tasks` override; `stop` halts with next commands; `confirm` strict ack (`proceed`/`yes` only); `auto` dispatches impl loop with branch notice; never inlines implementation; Go references removed from procedure/guardrails
  - **R-IDs:** R1, R2, R3, R4, R5, R8, R10, R24, R26

- [x] 4.2 Amend doc-orchestrator naming rule for auto-dispatch (R26)
  - **File:** `rules/sw-naming.mdc`
  - **Expected:** boundary permits provision + dispatch handoff; invariant that doc orchestrator does not inline implementation preserved
  - **R-IDs:** R26

- [x] 4.3 Add `/sw-ship --after-tasks` integration point (R30, R8)
  - **File:** `commands/sw-ship.md`
  - **Expected:** documents flag with real effect at frozen-task-list → implementation-loop boundary; agent `--after-tasks=auto` recorded in run record
  - **R-IDs:** R30, R8

- [x] 4.4 Boundary-mode fixtures (R2–R5, R4, R10)
  - **File:** `scripts/test/fixtures/onboarding-ux/boundary-*.sh`
  - **Expected:** `stop` halts without impl; `confirm` requires strict ack; `Go`/silence → stop; `auto` dispatches on worktree; implementing paths never touch bare `main`
  - **R-IDs:** R2, R3, R4, R5, R10

- [x] 4.5 Wire worktree guard into implementation entry (R6, R27)
  - **File:** `commands/sw-execute.md`, `commands/sw-start.md` (or hook integration point)
  - **Expected:** `sw-assert-worktree.py` invoked before implementation writes; fails closed on bare `main`
  - **R-IDs:** R6, R27

### 5. `/sw-setup` + review command docs (S)

- [x] 5.1 Add `doc.afterTasks` + review choice to `/sw-setup` (R7, R15, R19, R16)
  - **File:** `commands/sw-setup.md`
  - **Expected:** setup writes `doc.afterTasks` default; review choice `coderabbit | none` only (no `disabled`); canonical opt-out documented
  - **R-IDs:** R7, R15, R19, R16

- [x] 5.2 Update `sw-review.md` — CodeRabbit opt-in, not default (R14, R16)
  - **File:** `commands/sw-review.md`
  - **Expected:** no "CodeRabbit default" wording; `none` documented as canonical opt-out
  - **R-IDs:** R14, R16

- [x] 5.3 `/sw-setup` doctor notice for implicit-coderabbit repos (R22)
  - **File:** `commands/sw-setup.md` (doctor section)
  - **Expected:** when CodeRabbit CLI present but `review.provider` unset, doctor surfaces migration notice
  - **R-IDs:** R22

### 6. Human surfaces + review state echo (S)

- [x] 6.1 Echo review state in `/sw-ready` and living-status (R29)
  - **File:** `commands/sw-ready.md`, living-status command/skill
  - **Expected:** summary includes `review: off` or `review: not configured` when gate reports opt-out/unconfigured
  - **R-IDs:** R29

### 7. Build chain regeneration (S)

- [x] 7.1 Regenerate `core/` + `dist/` + parity manifest (R13)
  - **File:** run `scripts/copy-to-core.sh`, `python3 -m sw generate --all`, refresh `scripts/test/fixtures/parity/cursor-golden.manifest`
  - **Expected:** `run-emitter-fixtures.sh` freshness gate green; `run-parity-fixtures.sh` green; no hand-edits under `core/` or `dist/`
  - **R-IDs:** R13

### 8. User-facing documentation (S)

- [x] 8.1 Update onboarding docs for boundary modes + review default (R23)
  - **File:** `documentation/getting-started.md`, `documentation/commands.md`, `README.md`
  - **Expected:** documents `doc.afterTasks` modes, worktree invariant, single-pass `/sw-tasks`, `none` review default, canonical opt-out
  - **R-IDs:** R23

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | config-schema fixture: `doc.afterTasks` accepts stop\|confirm\|auto, default confirm |
| R2 | 4.1, 4.4 | boundary fixture: confirm requires proceed/yes; Go/silence maps to stop |
| R3 | 4.1, 4.4 | boundary fixture: declined/absent ack results in stop behavior |
| R4 | 4.1, 4.4 | boundary fixture: stop halts with task-list path + next commands |
| R5 | 4.1, 4.4 | boundary fixture: auto dispatches impl loop with branch notice on worktree |
| R6 | 2.1, 4.5 | worktree-guard negative fixture: no impl write on bare main |
| R7 | 1.1, 5.1 | setup fixture: writes schema-valid `doc.afterTasks` default |
| R8 | 4.1, 4.3 | boundary fixture: `--after-tasks` override; agent auto choice recorded |
| R9 | 3.1, 3.2 | tasks-single-pass fixture: complete list in one pass, no Go prompt |
| R10 | 4.1, 4.4 | boundary fixture: orchestrator dispatches, never inlines implementation |
| R11 | 1.2 | config-schema fixture: `review.provider` default is none |
| R12 | 1.3 | gate fixture: absent provider fallback none → unconfigured state |
| R13 | 7.1 | emitter + parity fixtures green after regenerate |
| R14 | 5.2 | sw-review.md grep: no "CodeRabbit default" phrasing |
| R15 | 5.1 | setup fixture: default review selection is none |
| R16 | 5.1, 5.2 | docs grep: canonical opt-out is `review.provider:none` |
| R17 | 1.5 | deprecation fixture: stdout JSON valid; warning off-stdout |
| R18 | 1.2 | config-schema fixture: `review.enabled` marked deprecated |
| R19 | 5.1 | setup fixture: review choice coderabbit\|none only |
| R20 | 1.3, 1.4 | gate fixture + grep: no `disabled` literal; state is `off` |
| R21 | 1.3, 1.4 | gate fixture: opt-out reason reads "review gating off", not "review landed" |
| R22 | 1.5, 5.3 | migration fixture: legacy config works; doctor notice for implicit coderabbit |
| R23 | 8.1 | docs review: boundary modes + review default documented |
| R24 | 3.1, 4.1 | tasks-single-pass + boundary: sole human checkpoint is afterTasks |
| R25 | 3.1, 3.2 | tasks-single-pass fixture: standalone /sw-tasks stops without prompt |
| R26 | 4.1, 4.2 | sw-naming.mdc + sw-doc.md: auto-dispatch permitted, no inline impl |
| R27 | 2.1, 2.2 | worktree-guard negative + positive fixtures |
| R28 | 1.3, 1.4 | gate fixture: unconfigured distinct from off; neither says "review landed" |
| R29 | 6.1 | sw-ready fixture: echoes review: off or review: not configured |
| R30 | 4.3 | sw-ship.md + integration fixture: `--after-tasks` has real effect |
