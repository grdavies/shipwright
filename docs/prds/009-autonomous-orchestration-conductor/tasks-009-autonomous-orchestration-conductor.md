---
date: 2026-06-25
topic: autonomous-orchestration-conductor
prd: docs/prds/009-autonomous-orchestration-conductor/009-prd-autonomous-orchestration-conductor.md
frozen: true
frozen_at: 2026-06-25
---

# Tasks — PRD 009 Autonomous orchestration conductor

Generated from the frozen PRD `009-prd-autonomous-orchestration-conductor.md` plus amendments
`amendments/A1-doc-integrity-and-traceability.md` and `amendments/A2-user-docs-refresh.md`
(effective union R1–R57 via `scripts/spec-union.sh`).
Phases are dependency-ordered: primitive reliability hardening and the per-orchestrator audit land first;
the conductor contract, autonomous loop, halts/liveness, and parallel dispatch build on top; living-doc
currency and brainstorm↔PRD traceability harden documentation integrity; the `/sw-deliver` pilot, surface
docs, and emitter regen close the run; the adopter-facing README + user-guide refresh lands once the
documented behavior exists.

## Tasks

### 1. Primitive reliability hardening (M)

- [x] 1.1 `spec-seed` idempotent state record (R25)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/wave.sh`
  - **Expected:** the idempotent-skip path sets `state.specSeed`; `compute_next_action` never returns
    `spec-seed` again once the seed commit exists
- [x] 1.2 Merge post-verify routing without silent revert (R26)
  - **File:** `scripts/wave_merge.py`, `scripts/wave_failure.py`
  - **Expected:** a post-merge verify failure routes to `/sw-stabilize` and marks the phase `blocked`; the
    default path issues no `git revert`; state stays re-drivable; any revert is explicit + logged
- [x] 1.3 `wave.sh` dispatcher argument hygiene (R27)
  - **File:** `scripts/wave.sh`
  - **Expected:** `status`, `merge`, and `report` dispatchers forward `${@:2}`; `wave.sh status collect`,
    `wave.sh merge run-next`, and `wave.sh report terminal` succeed end-to-end via the shell entrypoint
- [x] 1.4 Structured driver error paths (`fail()` keyword-collision) (R28)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/wave_deliver.py`
  - **Expected:** colliding `error` key stripped before `**data` splat; any sub-step failure emits
    `{"verdict":"fail", …}` JSON and exits cleanly with no `TypeError`/stack trace
- [x] 1.5 Phase status-vocabulary guard (R29)
  - **File:** `scripts/wave_state.py`, `scripts/wave_merge.py`
  - **Expected:** a guard rejects any status write outside `pending | in-flight | green-merged | blocked |
    rejected`; the merge primitive continues to set `green-merged`
- [x] 1.6 Stale-state guard with resume discrimination (R30, R43)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** loop entry compares requested run identity (canonical task-list path / run-id) to state; a
    match resumes, a true mismatch aborts with a consolidated halt or clears under `--reset`; relative/relocated
    same-run paths do not false-abort
- [x] 1.7 Detached-head-safe orchestrator provision (R31)
  - **File:** `scripts/wave_lifecycle.py`
  - **Expected:** clean primary-on-target-branch is auto-handled (detach / checkout `origin/HEAD`); a dirty
    primary on the target still fails closed with remediation
- [x] 1.8 Wire R25–R31 regression fixtures into the gate (R32)
  - **File:** `scripts/test/run-deliver-fixtures.sh`, `scripts/test/run-deliver-loop-fixtures.sh`, `scripts/test/run-state-fixtures.sh`
  - **Expected:** each of R25–R31 has a failing-before / passing-after fixture invoked by `verify.test`

### 2. Per-orchestrator audit + adoption enumeration (S/M)

- [x] 2.1 Audit `/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback` for turn-yield + missed parallelism (R33)
  - **File:** `docs/prds/009-autonomous-orchestration-conductor/orchestrator-adoption-audit.md`
  - **Expected:** each orchestrator's unnecessary turn-yields and unparallelized independent work enumerated
- [x] 2.2 Enumerate sequenced adoption requirements referencing the shared contract (R35)
  - **File:** `docs/prds/009-autonomous-orchestration-conductor/orchestrator-adoption-audit.md`
  - **Expected:** per-orchestrator adoption requirements, sequenced after the pilot, each referencing (not
    duplicating) the conductor contract

### 3. Conductor contract + config knobs (M)

- [x] 3.1 Conductor contract skill + thin guardrail rule (R1, R3)
  - **File:** `core/skills/conductor/SKILL.md`, `core/rules/sw-conductor.mdc`
  - **Expected:** one referenced contract specifying self-continuation, legitimate-halt set, parallel
    dispatch, and resumption; invokes `wave_*.py` primitives, never re-implements state logic in prose
- [x] 3.2 Durable-state resumption clause for a fresh agent (R4)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** a fresh agent resumes from `.cursor/sw-deliver-state.json` + plan + run log and continues
    to the next legitimate halt
- [x] 3.3 Default no-reprompt behavior (R13)
  - **File:** `core/skills/conductor/SKILL.md`, `core/commands/sw-deliver.md`
  - **Expected:** with no extra config a frozen task list delivers end-to-end to the terminal-PR gate with
    zero re-prompts
- [x] 3.4 `deliver.autonomy` knob + run-level budget (R42)
  - **File:** `.cursor/workflow.config.json` (schema + example), `core/scripts` setup seeding
  - **Expected:** `deliver.autonomy: supervised|autonomous` (default `autonomous`) and a run-level ceiling
    (`deliver.autonomy.maxRunMinutes` / total-iteration) that converts a runaway run to a clean halt

### 4. Autonomous self-continuation + self-wake (M/L)

- [x] 4.1 In-turn self-continuation over the driver (R2, R6, R7)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/deliver/SKILL.md`
  - **Expected:** after `awaitAgent: true` the conductor does the agent work and re-invokes `deliver-loop`
    in-turn; it never ends the turn while `nextAction` is runnable and no halt condition is met
- [x] 4.2 Conductor loop hard-stop + no-progress circuit breaker (R38)
  - **File:** `rules/sw-subagent-dispatch.mdc`, `core/skills/conductor/SKILL.md`
  - **Expected:** documented max-iteration bound; identical `nextAction` + unchanged state signature N× →
    clean consolidated halt
- [x] 4.3 Self-wake sentinel + per-run teardown (R8, R9)
  - **File:** `core/skills/conductor/SKILL.md`, `core/commands/sw-deliver.md`
  - **Expected:** terminal-PR CI arms a uniquely-named `notify_on_output` shell keyed on run id; all
    watchers/heartbeats torn down on terminal halt; no orphaned processes
- [x] 4.4 External-wait exhausted → clean halt + re-derive (R40)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** `checks.watch.maxWaitMinutes` expiry routes to a consolidated halt; a wake re-derives next
    action from durable state
- [x] 4.5 Parallel-wave completion wait contract (R44)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** bounded poll of the durable `status.json` set or self-wake on status appearance, then
    autonomous resume; mechanism is specified, not implicit
- [x] 4.6 Self-wake environment fallback (R46)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** where output-notification auto-resume is unavailable (cloud/headless), degrade to a bounded
    in-turn poll up to `maxWaitMinutes` then one consolidated halt

### 5. Legitimate halts + consolidated reports + liveness (M)

- [x] 5.1 Legitimate-halt set (R10)
  - **File:** `core/skills/conductor/SKILL.md`, `core/rules/sw-conductor.mdc`
  - **Expected:** halts only on main-merge, exhausted remediation budget, ambiguous/destructive action,
    configured checkpoint, phase-liveness timeout, and external-wait exhaustion
- [x] 5.2 No routine halts (R11)
  - **File:** `core/skills/conductor/SKILL.md`, `core/commands/sw-deliver.md`
  - **Expected:** no halt for per-phase progression, status collection, wave advancement, or bookkeeping
- [x] 5.3 Consolidated halt report (R12)
  - **File:** `scripts/wave.sh`, `core/skills/conductor/SKILL.md`
  - **Expected:** every halt emits one actionable report (what is blocked, why, exact resume command), never
    a bare "continue?" prompt
- [x] 5.4 Phase liveness watchdog (R37)
  - **File:** `scripts/wave.sh`, `scripts/wave_state.py`, `core/skills/conductor/SKILL.md`
  - **Expected:** per-phase timeout/heartbeat; expiry without terminal `status.json` marks the phase
    `blocked`, emits the consolidated report, and is a legitimate halt

### 6. Conductor-level parallel dispatch + safety under concurrency (L)

- [x] 6.1 Parallel wave dispatch: greedy batches, ceiling-bounded, orchestrator-level (R14, R15, R16)
  - **File:** `core/skills/conductor/SKILL.md`, `scripts/wave.sh` (schedule consumption)
  - **Expected:** all dependency-ready phases dispatched as background `Task` sub-agents in disjoint
    worktrees bounded by `parallelCeiling`; over-ceiling waves run in greedy batches; a running phase is
    never unwound; all dispatch from the conductor level (no nested dispatch)
- [x] 6.2 Intra-phase gating, ceiling accounting, degrade-to-inline (R17, R18, R45)
  - **File:** `core/skills/conductor/SKILL.md`, `rules/sw-subagent-dispatch.mdc`
  - **Expected:** intra-phase dispatch only when `sw-subagent-dispatch` heuristics trip (decision logged);
    it does not consume ceiling slots; a backgrounded phase degrades intra-phase dispatch to inline review
- [x] 6.3 Outcomes from durable status only (R19)
  - **File:** `core/skills/conductor/SKILL.md`, `scripts/wave.sh`
  - **Expected:** phase outcomes read solely from `.cursor/sw-deliver-runs/<phase>/status.json`, never from
    ephemeral sub-agent logs
- [x] 6.4 Mechanical contention serialization (R20, R39)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** contention edges injected at plan time from declared/derived touch paths
    (migration paths, `INDEX.md`/numbering, `CHANGELOG.md`/`version.txt`); contended phases land in different
    waves; ambiguous cases fail safe to sequential
- [x] 6.5 Single-flight, conductor-serialized merge with atomic lock (R21, R41)
  - **File:** `scripts/wave_merge.py`, `scripts/wave_state.py`
  - **Expected:** concurrent phase completion yields exactly one merge; the queue lock acquires atomically;
    phase sub-agents never call `merge run-next`
- [x] 6.6 Green-gate, no-main-merge, push chokepoint (R22, R23)
  - **File:** `scripts/wave_merge.py`, `scripts/git-push.sh`
  - **Expected:** a phase merges only when green + review-satisfied; the conductor never merges `main`; all
    pushes route through `git-push.sh` (no raw `git push`)
- [x] 6.7 Blast-radius blocking (R24)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** a blocked phase blocks only its transitive dependents; green siblings continue and may
    auto-merge

### 7. Pilot validation + surface docs + emitter (M)

- [x] 7.1 `/sw-deliver` pilot adoption + R6–R20 end-to-end validation (R34)
  - **File:** `core/commands/sw-deliver.md`, `scripts/test/run-deliver-loop-fixtures.sh`
  - **Expected:** `/sw-deliver` consumes the conductor contract without re-authoring loop logic and is
    validated against R6–R20 end-to-end (observable peak concurrency ≥2 on a parallelizable task list)
- [x] 7.2 Surface documentation updates (R36)
  - **File:** `core/commands/sw-deliver.md`, `core/skills/conductor/SKILL.md`, `docs/guides/*`
  - **Expected:** autonomy/parallelism behavior and the legitimate-halt set documented at user-read surfaces
- [x] 7.3 Emitter propagation + freshness gate (R5)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** the platform-neutral `core/` contract is emitted to both `dist/cursor` and
    `dist/claude-code`; `scripts/test/run-emitter-fixtures.sh` passes

### 8. Living-doc currency hardening (M)

- [x] 8.1 INDEX status reconcile primitive from merge state (R47)
  - **File:** `scripts/reconcile-status.sh`, `core/skills/living-status/SKILL.md`
  - **Expected:** sets `docs/prds/INDEX.md` status from durable run/merge state on the correct PRD row; a
    shipped PRD is never left `not-started`; the status enum (`not-started | in-progress | complete`) is
    single-sourced in `living-status`
- [x] 8.2 Idempotent COMPLETION-LOG append primitive (R48)
  - **File:** `scripts/reconcile-status.sh`
  - **Expected:** a single primitive appends date/PRD/phase/PR/SHA; re-running on resume never
    double-appends and never omits a shipped PRD
- [x] 8.3 GAP-BACKLOG structured status + resolve-on-absorb (R49)
  - **File:** `scripts/reconcile-status.sh`, `core/skills/living-status/SKILL.md`, `docs/prds/GAP-BACKLOG.md`
  - **Expected:** entries carry structured status + resolving PRD/R-IDs; when an absorbing PRD reaches
    `complete` the matching `open` gaps flip to `resolved` with the PRD/PR reference; non-matching gaps
    untouched; file stays hand-appendable for new gaps
- [x] 8.4 Documentation-currency drift gate (current-run scoped, hard-block) (R50)
  - **File:** `scripts/docs-currency-gate.sh`, `scripts/wave.sh`
  - **Expected:** before the terminal merge gate, drift in the current run's INDEX row / COMPLETION-LOG
    entry / absorbed gaps hard-blocks until reconciled; pre-existing unrelated historical drift does not block
- [x] 8.5 Commit living-doc updates in-loop on the feature branch (R51)
  - **File:** `scripts/wave.sh`, `core/skills/conductor/SKILL.md`
  - **Expected:** INDEX/COMPLETION-LOG/GAP-BACKLOG updates are committed pre-merge so the terminal PR
    reflects accurate ledger state

### 9. Brainstorm↔PRD frontmatter traceability (S/M)

- [x] 9.1 PRD `brainstorm:` back-reference written by `/sw-prd` (R52)
  - **File:** `core/commands/sw-prd.md`, `.sw/layout.md`
  - **Expected:** a Full-tier PRD draft carries a repo-relative `brainstorm:` reference that resolves to an
    existing brainstorm
- [x] 9.2 Brainstorm forward `prd:` reference when writable (R53)
  - **File:** `core/commands/sw-prd.md`, `core/commands/sw-freeze.md`
  - **Expected:** an unfrozen source brainstorm gains a forward `prd:` reference (list when multiple); a
    frozen brainstorm is never edited and the PRD back-reference remains authoritative
- [x] 9.3 Fail-closed frontmatter-traceability gate + layout docs (R54)
  - **File:** `scripts/doc-link-check.sh`, `.sw/layout.md`
  - **Expected:** dangling/missing `brainstorm:`/`prd:` references fail closed for a Full-tier PRD; gate
    wired into the doc/test suite; layout documents the fields
- [x] 9.4 `/sw-freeze` verifies PRD↔brainstorm linkage (R55)
  - **File:** `core/commands/sw-freeze.md`, `scripts/doc-link-check.sh`
  - **Expected:** a Full-tier PRD freeze is blocked when the `brainstorm:` back-reference is missing or
    unresolvable

### 10. Adopter-facing README + user-guide refresh (S/M)

- [ ] 10.1 README + guides refresh for 009/A1/A2 command/workflow/usage changes (R56)
  - **File:** `README.md`, `docs/guides/getting-started.md`, `docs/guides/workflows.md`, `docs/guides/configuration.md`, `docs/guides/commands.md`
  - **Expected:** README + each guide reflects conductor autonomy/parallelism behavior and the
    legitimate-halt set, the `deliver.autonomy` knob + run-level budget (with defaults), living-doc currency
    (INDEX/COMPLETION-LOG/GAP-BACKLOG) behavior, and the brainstorm↔PRD frontmatter fields; complements the
    command-surface descriptions from 7.2 (R36) without duplicating them
- [ ] 10.2 Docs presence check + legacy-reference removal, wired into the gate (R57)
  - **File:** `scripts/docs-presence-check.sh`, `scripts/wave.sh`
  - **Expected:** the check asserts README/guides name the new autonomy/config/living-doc/frontmatter
    surfaces and that no `/pf-*` / `pf-` legacy command references remain in `README.md` or `docs/guides/*`;
    failing-before / passing-after fixtures wired into `verify.test`

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 1, 2 |
| 4 | 3 |
| 5 | 3 |
| 6 | 4, 5 |
| 7 | 4, 5, 6, 8, 9 |
| 8 | 3 |
| 9 | none |
| 10 | 4, 5, 6, 8, 9 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 3.1 | conductor-contract-single-source |
| R2 | 4.1 | conductor-drives-without-human-step |
| R3 | 3.1 | conductor-contract-single-source |
| R4 | 3.2 | conductor-fresh-agent-resume |
| R5 | 7.3 | conductor-emitter-freshness |
| R6 | 4.1 | deliver-loop-self-continue-in-turn |
| R7 | 4.1 | deliver-loop-self-continue-in-turn |
| R8 | 4.3 | conductor-self-wake-ci-wait |
| R9 | 4.3 | conductor-watcher-teardown |
| R10 | 5.1 | conductor-legitimate-halts-only |
| R11 | 5.2 | conductor-no-routine-halt |
| R12 | 5.3 | conductor-consolidated-halt-report |
| R13 | 3.3 | conductor-default-no-reprompt |
| R14 | 6.1 | conductor-parallel-wave-dispatch |
| R15 | 6.1 | conductor-greedy-batch-ceiling |
| R16 | 6.1 | conductor-parallel-wave-dispatch |
| R17 | 6.2 | conductor-intra-phase-gated |
| R18 | 6.2 | conductor-ceiling-accounting |
| R19 | 6.3 | conductor-status-from-durable-only |
| R20 | 6.4 | conductor-contention-serialized |
| R21 | 6.5 | conductor-single-flight-merge |
| R22 | 6.6 | conductor-green-gate-no-main-merge |
| R23 | 6.6 | conductor-push-chokepoint |
| R24 | 6.7 | conductor-blast-radius |
| R25 | 1.1 | spec-seed-idempotent-state |
| R26 | 1.2 | merge-postverify-no-silent-revert |
| R27 | 1.3 | wave-dispatch-arg-hygiene |
| R28 | 1.4 | driver-error-structured-json |
| R29 | 1.5 | phase-status-vocabulary-guard |
| R30 | 1.6 | stale-state-refuses-start |
| R31 | 1.7 | provision-detached-head-safe |
| R32 | 1.8 | reliability-regressions-wired |
| R33 | 2.1 | orchestrator-adoption-audit-present |
| R34 | 7.1 | deliver-pilot-validated |
| R35 | 2.2 | adoption-requirements-enumerated |
| R36 | 7.2 | surface-docs-updated |
| R37 | 5.4 | conductor-phase-liveness-timeout |
| R38 | 4.2 | conductor-no-progress-circuit-breaker |
| R39 | 6.4 | conductor-contention-mechanical |
| R40 | 4.4 | conductor-ci-wait-exhausted-halt |
| R41 | 6.5 | conductor-merge-serialized-atomic |
| R42 | 3.4 | conductor-run-budget-halt |
| R43 | 1.6 | conductor-resume-not-false-aborted |
| R44 | 4.5 | conductor-parallel-completion-wake |
| R45 | 6.2 | conductor-no-nested-dispatch-under-parallel |
| R46 | 4.6 | conductor-self-wake-cloud-fallback |
| R47 | 8.1 | index-status-reconcile-from-merge |
| R48 | 8.2 | completion-log-idempotent-append |
| R49 | 8.3 | gap-backlog-resolve-on-absorb |
| R50 | 8.4 | docs-currency-gate-block |
| R51 | 8.5 | living-docs-committed-in-loop |
| R52 | 9.1 | prd-brainstorm-backref-written |
| R53 | 9.2 | brainstorm-prd-forwardref-written |
| R54 | 9.3 | doc-link-traceability-gate |
| R55 | 9.4 | freeze-verifies-doc-linkage |
| R56 | 10.1 | user-docs-009-coverage |
| R57 | 10.2 | user-docs-no-legacy-refs |
