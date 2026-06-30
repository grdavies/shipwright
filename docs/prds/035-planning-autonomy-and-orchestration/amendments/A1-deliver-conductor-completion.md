---
date: 2026-06-29
amends: docs/prds/035-planning-autonomy-and-orchestration/035-prd-planning-autonomy-and-orchestration.md
absorbs:
  - GAP-012
  - GAP-016
  - GAP-021
  - GAP-022
  - GAP-024
  - GAP-025
  - GAP-026
  - GAP-027
  - GAP-029
  - GAP-030
  - GAP-041
  - GAP-042
  - GAP-048
  - GAP-049
  - GAP-050
  - GAP-051
  - GAP-052
  - GAP-054
  - GAP-057
  - GAP-058
  - GAP-059
  - GAP-060
  - GAP-061
  - GAP-062
  - GAP-064
  - GAP-068
  - GAP-071
  - GAP-072
  - GAP-073
  - GAP-074
frozen: true
frozen_at: 2026-06-29
---

# Amendment A1: Deliver conductor completion + build-chain ship boundary

## Overview

Binary GAP-BACKLOG reconcile (2026-06-29) rescheduled **30 open deliver-friction gaps** to PRD 035 after PRDs
033, 036, and 038 reached `complete` without closing the observed runtime failures (PRD 034
`planning-feedback-lifecycle` deliver retro). Parent PRD 035 is the planning-program capstone; this amendment
adds a **deliver-completion slice** that composes existing conductor/wave primitives (parent non-goal: no
greenfield conductor rewrite) and closes the gap between shipped partial fixes and operator-ready autonomous
deliver.

**Cross-refs (not duplicated here):**

- **PRD 033 A1** — GAP-053, GAP-055, GAP-065, GAP-066, GAP-067, GAP-070 (INDEX reconcile / post-merge
  playbook).
- **PRD 033 A3** — GAP-056 (operator worktree contract).
- **PRD 024 A2** — GAP-009, GAP-039, GAP-040 (dispatch binding; prerequisite for `/sw-doc` adoption).

This amendment continues the parent namespace at **R25–R48**.

## Context

PRD 036 targeted deliver concurrency/remediation; PRD 038 wired build-chain SoT + CI parity. Deliver runs still
hit: (1) **build-chain drift** every phase (`cursor-golden-vs-dist`, emitter freshness — GAP-071/054); (2)
**post-merge integration verify** exhausting remediation budget (GAP-072); (3) **conductor turn-boundary**
halts after remediation or mid-ship (GAP-027/029/058); (4) **terminal path** stalls (`all_phases_merged` vs
`all_phases_green`, hand-authored `status.json` — GAP-041/052); (5) **parallel-wave merge races** and stale
worktrees (GAP-048/050/074/030); (6) **operator handoffs** still bash-first (GAP-026). Config
`deliver.terminal.autonomy: auto` is now set repo-wide; this amendment makes the runtime honor it mechanically.

## Goals

1. **Ship-time build-chain** — any phase commit touching `scripts/`, `core/`, or generated `dist/` MUST run
   `build-chain-sync` before push; post-merge verify classifies golden-only drift as environmental with bounded
   auto-regen.
2. **Remediation routing** — `verify:failed` (regression) reaches stabilize within remediation budget;
   `noProgressStreak` does not pre-empt first remediation.
3. **Conductor continuity** — no illegitimate turn-boundary halts after `green-merged`, during `dispatch-ship`,
   or on `awaitAgent`; same-turn `deliver-loop` re-invoke per R13.
4. **Terminal completeness** — retrospective → terminal PR → watch/stabilize runs hands-off when
   `deliver.terminal.autonomy: auto`; terminal `status.json` is ship-emitted only.
5. **Worktree + batch hygiene** — eager phase teardown, `batchIntegrationHead` reconcile after stabilize,
   whole-batch merge wait, cross-run parallel ceiling preflight.

## Non-Goals

- Re-implementing the wave engine (parent non-goal; compose `wave_deliver_loop.py`, `wave_merge.py`,
  `wave_terminal.py`, `wave_lifecycle.py`).
- Auto-merge to protected `main` or bypassing human merge gate.
- PRD 003 deferred review surface (GAP-011), PRD 008 model-picker deferrals (GAP-014), native review panel
  follow-ons (GAP-013).
- INDEX `derived` reconcile semantics owned by PRD 033 A1 (GAP-053/055/065–067/070).
- Dispatch preflight / command-tier binding (PRD 024 A2).

## Requirements

### Build-chain + verify (GAP-054, GAP-071, GAP-059, GAP-051, GAP-061, GAP-072)

- **R25** `/sw-ship` verify (phase-mode and terminal) MUST run `python3 scripts/build-chain-sync.py --check`
  (or equivalent) before commit when the phase diff touches any path in `core/sw-reference/build-chain-paths.json`
  (or the PRD 038 SoT manifest). Failure is a **hard verify block**, not a post-push CI surprise. Fixture:
  `ship-without-build-chain-sync-fails`.
- **R26** `verify.test` MUST include `run-parity-fixtures.sh` (`cursor-golden-vs-dist`) so local/post-merge
  verify matches `ci.yml` fixtures job. Fixture: `verify-test-includes-parity`.
- **R27** Post-merge integration `verify run-after-merge` MUST classify **build-chain-only** failures
  (golden-manifest / emitter freshness / `dist` drift with no regression signal) as `verify:environmental`
  (exit 10) and MAY auto-run `build-chain-sync` once per remediation attempt when
  `deliver.remediation.autoBuildChain: true` (default `true`). Fixture:
  `post-merge-build-chain-environmental`.
- **R28** Deterministic `merge-queue:conflict` on paths in `deterministic-regen-paths.json` MUST route to
  bounded auto-regen (extends PRD 036 R12); manual-only halt is a failure mode. Fixture:
  `merge-queue-deterministic-regen`.
- **R29** After parallel-wave manifest union merge, deliver MUST run build-chain regen on the integration
  branch before incremental verify. Fixture: `parallel-wave-regen-before-verify`.

### Remediation + merge queue (GAP-049, GAP-062, GAP-060, GAP-050, GAP-073)

- **R30** `wave_deliver_loop.py` `merge-run-next` MUST route `verify:failed` (exit 20) to `remediate` when
  remediation budget remains — same as environmental (exit 10) — not `fail_payload` hard-exit. Fixture:
  `verify-failed-routes-remediate`.
- **R31** `check_budget_halt` / `noProgressStreak` MUST NOT trip before the first `remediate` dispatch when
  `nextAction` is `remediate`; merge-queue stall MUST advance state signature (enqueue attempt counter).
  Fixture: `no-progress-before-first-remediate`.
- **R32** `currentWave` past `plan.waves.length` MUST degrade to terminal routing (not empty batch +
  `await-in-flight` stall). Fixture: `current-wave-overflow-terminal`.
- **R33** Parallel-wave batch queue MUST NOT merge a phase until all siblings in the wave reach
  `green-merged` (R44 enforcement). Fixture: `whole-batch-merge-wait`.
- **R34** After integration-targeted `/sw-stabilize` commits, deliver state MUST atomically refresh
  `batchIntegrationHead` when a batch queue is active. Fixture: `batch-integration-head-reconcile`.

### Conductor continuity (GAP-027, GAP-029, GAP-058, GAP-041)

- **R35** Conductor R11 MUST explicitly forbid post-remediation "status note + continue?" halts; a phase whose
  terminal `status.json` is `merge-ready-green` is complete regardless of remediation history. Fixture:
  `post-remediation-no-status-pause`.
- **R36** `dispatch-ship` MUST complete the full `/sw-ship --phase-mode` chain in-turn before yielding;
  incomplete ship + turn boundary is not a legitimate halt. Fixture: `dispatch-ship-completes-in-turn`.
- **R37** `awaitAgent: true` MUST trigger same-turn `deliver-loop` re-invoke (R13 recurrence); conductor
  skill + `sw-deliver.md` output contract MUST NOT end the turn on await alone. Fixture:
  `await-agent-same-turn-continue`.
- **R38** `all_phases_merged()` and `all_phases_green()` MUST agree on terminal eligibility when phases are
  `teardown-complete` vs `green-merged` (unify predicate or normalize status before terminal routing).
  Fixture: `terminal-eligibility-teardown-green-parity`.

### Terminal path (GAP-021, GAP-022, GAP-024, GAP-052, GAP-064, GAP-048)

- **R39** Deliver-loop terminal path MUST auto-invoke `/sw-retrospective --pre-merge` when
  `deliver.terminal.autonomy: auto` before `terminal-pr` (PRD 013 A1 R20–R21). Fixture:
  `terminal-retro-before-pr-auto`.
- **R40** Terminal ship MUST create/update PR, push, run bounded `check-gate` + `/sw-stabilize` without
  human ack when `deliver.terminal.autonomy: auto` (PRD 013 A1 R22–R24). Fixture:
  `terminal-ship-autonomous-watch`.
- **R41** Phase-mode ship MUST be single-flight per phase head: background `dispatch-ship` MUST NOT race the
  parent (R13); PR creation idempotency via host lookup before `gh pr create`. Fixture:
  `single-flight-phase-ship`.
- **R42** Terminal `status.json` MUST be emitted only by `/sw-ship --phase-mode` / `sw-ready`; driver MUST
  detect non-canonical hand-authored status and route to re-emit. Fixture:
  `terminal-status-provenance-reemit`.
- **R43** `wave_terminal.py` MUST coerce `fail(error=…)` to `str()` and generate commitlint-safe PR titles
  (lowercase `prd` slug). Fixture: `terminal-pr-prepare-commitlint`.

### Worktree + operator UX (GAP-030, GAP-074, GAP-042, GAP-026)

- **R44** `merge-run-next` MUST invoke `phase-teardown` after successful forward-merge (PRD 017 R17); merged
  phase worktrees MUST NOT linger until end-of-run cleanup. Fixture: `eager-phase-teardown-after-merge`.
- **R45** Provision preflight when `parallel ceiling reached` MUST report `wouldFree` worktrees + emit
  `/sw-cleanup` or teardown command in halt payload. Fixture: `parallel-ceiling-would-free`.
- **R46** `status collect` MUST resolve phase worktree path when background ship wrote relative `SW_RUN_DIR`
  (extends PRD 007 R38 / GAP-042). Fixture: `status-collect-background-worktree`.
- **R47** `resume_deliver_command()` and conductor halt payloads MUST emit `/sw-deliver run <task-list>` as
  primary resume (PRD 017 A1 R29). Fixture: `deliver-resume-command-is-sw`.

### Docs durability + projection (GAP-016, GAP-057, GAP-068)

- **R48** Post-freeze docs on the integration branch MUST commit via `wave_spec_seed` / docs-branch path
  without waiting for `deliver-loop` entry (closes data-loss window — GAP-016). `planning_legacy_projection`
  MUST refuse to wipe hand-maintained GAP-BACKLOG/INDEX without `--force` (GAP-068). Durable re-freeze
  contract for amendment companions replaces scoped `check-frozen.py` exceptions (GAP-057). Fixtures:
  `post-freeze-docs-durability`, `projection-refuse-hand-maintained`, `re-freeze-contract-amendment`.

### Deliver deferrals + cleanup (GAP-012, GAP-025)

- **R49** (deferral tracking) Cross-feature waves, rich living-status dashboard, and contention feedback into
  `/sw-tasks` re-run (PRD 013 R13–R16) remain **explicit deferrals** — document in `sw-deliver.md` non-goals;
  no silent partial ship.
- **R50** `cleanup.autonomy: auto` deliver hook MUST apply dry-run `wouldRemove` after deterministic merge
  detection (PRD 013 A1 R25–R26) when configured; default remains `confirm`. Fixture:
  `cleanup-autonomy-auto-post-merge`.

## Testing Strategy

| Fixture cluster | R-IDs | Source gaps |
|-----------------|-------|-------------|
| Build-chain ship + environmental verify | R25–R29 | 054, 071, 059, 051, 061, 072 |
| Remediation + batch queue | R30–R34 | 049, 062, 060, 050, 073 |
| Conductor continuity | R35–R38 | 027, 029, 058, 041 |
| Terminal path | R39–R43 | 021, 022, 024, 052, 064, 048 |
| Worktree + resume | R44–R47 | 030, 074, 042, 026 |
| Docs + deferrals | R48–R50 | 016, 057, 068, 012, 025 |

All fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.

## Implementation note (task integration)

Regenerate `tasks-035-planning-autonomy-and-orchestration.md` before implementation. Suggested **Phase 7 —
Deliver completion** (depends on phases 1–6): group tasks by fixture cluster above; land behind green
fixtures; may run in parallel with Phase 5 emitter parity where file sets do not overlap.

**Dependency:** PRD 024 A2 (dispatch binding) SHOULD ship before or in parallel with Phase 7 — not a hard
blocker for wave scripts but required for full `/sw-doc` + delegated deliver panels.

## Documentation deliverables

- `core/skills/conductor/SKILL.md` — R35–R37, R39–R40 legitimate-halt table updates.
- `core/commands/sw-deliver.md` — resume command, build-chain verify, deferrals R49.
- `core/commands/sw-ship.md` — R25 build-chain check.
- `docs/guides/workflows.md` — post-merge playbook cross-ref PRD 033 A1.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Deliver slice on PRD 035 capstone | Binary reconcile assigned open deliver gaps here; planning + deliver share conductor adoption and gap pull-in. |
| DL-2 | Compose, don't rewrite wave engine | Parent non-goal; fixes are predicates, routing, and verify hooks on existing modules. |
| DL-3 | 033 A1 not reopened | Complete units; cross-ref only for INDEX/post-merge playbook gaps. |
| DL-4 | `deliver.terminal.autonomy: auto` assumed | Operator set config 2026-06-29; R39–R40 make runtime match config. |

## Gap resolution (on ship)

Update GAP-BACKLOG rows listed in `absorbs:` frontmatter to `resolved — PRD 035 A1` when Phase 7 ships.
