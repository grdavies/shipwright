---
date: 2026-06-26
topic: pervasive-subagent-delegation
brainstorm: docs/brainstorms/2026-06-26-pervasive-subagent-delegation-requirements.md
frozen: true
frozen_at: 2026-06-26
---

# PRD 017 — Pervasive sub-agent delegation with per-task model + caveman binding

## Overview

Two distinct problems motivate this PRD, and the persona panel made clear they must not be conflated:

1. **The observed-parallelism gap is a driver-wiring bug, not a policy gap.** Parallel background sub-agent
   phase dispatch is specced (PRD 004 R17/R18; PRD 009 conductor R14–R20) but never fires because
   `scripts/wave_deliver_loop.py compute_next_action` returns a single `dispatch-ship` per loop iteration —
   the driver provisions one phase per step, so the conductor never has a batch of independent phases to
   dispatch concurrently. **R22/TR5 close this**, and R11 is observability over it.
2. **Delegation and binding are inconsistent.** Orchestrators mostly run steps inline; when they do delegate,
   per-task model and caveman intensity are not reliably bound (the Cursor `Task` model-injection hook is a
   no-op per PRD 012 DL-2), and there is no mechanical floor forcing binding.

This PRD therefore: (a) **wires real parallel phase dispatch** in the deliver driver; (b) makes
**delegate-by-default** the standing policy across all five orchestrators (`/sw-doc`, `/sw-ship`,
`/sw-deliver`, `/sw-debug`, `/sw-feedback`), tunable via a new `delegation.mode` knob; (c) **binds per-task
model and caveman intensity** at dispatch with a fail-closed mechanical gate; and (d) **hardens the conductor
in-turn loop** so the recurring "paused mid-implementation" failures stop. It references — and does not
re-specify — the frozen conductor/parallel contracts (PRD 009 R14–R20, PRD 004 R17/R18); R11–R13 are deltas
over those, not restatements. It derives from the frozen brainstorm
`docs/brainstorms/2026-06-26-pervasive-subagent-delegation-requirements.md` (R1–R21), extends the namespace
with R22–R28 for panel-driven additions, and consumes the open `GAP-BACKLOG.md` rows for status-pause framing,
post-remediation completeness, `dispatch-ship` completion, and eager worktree teardown.

> **R-ID namespace note.** PRD 017 R14–R16 are *conductor-hardening* requirements. They are unrelated to
> PRD 009 R14–R16 (*parallel dispatch*). External references are always qualified as "PRD 009 R<n>".

## Goals

1. Independent wave phases are dispatched as concurrent background sub-agents (observed peak concurrency ≥2),
   because the deliver driver emits a multi-phase batch action — closing the operator's "never observed
   parallelism" pain.
2. Every substantive orchestrated step delegates by default (tunable via `delegation.mode`), with only an
   enumerated inline exception set running inline.
3. Every delegated dispatch is bound to the concrete model and caveman intensity defined for that task,
   enforced by a fail-closed mechanical gate — never relying on `model: inherit` from the parent session.
4. The conductor in-turn loop reliably drives a frozen task list to the terminal merge gate without spurious
   turn-boundary pauses, and merged-phase worktrees are reclaimed immediately.

## Non-Goals

- Auto-merging to `main`, force-push, or changing the terminal human merge gate (PRD 004/007 invariants).
- **Amending** frozen PRD 009 / 004 / 007 — their conductor/parallel/teardown contracts are referenced as the
  single source; this PRD wires and observes them, it does not re-specify them.
- Rewriting doc-review human gates (`gated_auto` / `manual`) or re-architecting the `/sw-doc` panel or
  `/sw-feedback` human handoff gates — R1 for those orchestrators means delegating their *substantive
  atomics*, not changing their human gates.
- Changing the memory/freeze contracts (PRD 013 / PRD 015 territory) or per-branch deliver state/lock scoping
  (PRD 013); R17 implements the already-documented PRD 007 TR1 teardown lifecycle only.
- Changing harness active-subagent capacity defaults; R10/R28 govern how capacity limits are *handled*, not
  raised.
- Making the Cursor `Task` model-injection hook authoritative — forward-compatible defense-in-depth only
  (PRD 012 DL-2).
- Proxying interactive prompts through a sub-agent boundary (rejected; see DL-1).
- Cross-repository parallelism.

## Requirements

R1–R21 are carried forward from the frozen brainstorm (stable namespace; do not renumber). R22–R28 are
panel-driven additions introduced by this PRD. Requirement text receives only clarifying edits.

### Delegation invariant + escape hatch

- **R1** A delegate-by-default invariant MUST govern all five orchestrators (`/sw-doc`, `/sw-ship`,
  `/sw-deliver`, `/sw-debug`, `/sw-feedback`): every substantive orchestrated step MUST be dispatched as a
  sub-agent via the `Task` tool rather than executed inline, subject to `delegation.mode` (R22a).
- **R2** A **closed, enumerated inline exception set** MUST define the only steps that run inline: interactive
  gates (brainstorm Q&A, `doc.afterTasks: confirm`, the terminal merge gate, driver-detected
  ambiguity/destructive halts per R28) and an explicit per-orchestrator allowlist of trivial bookkeeping/state
  verbs. Anything not on the allowlist MUST delegate; "trivial bookkeeping" MUST NOT be an open category.
- **R3** `rules/sw-subagent-dispatch.mdc` MUST be updated so the standing policy is delegate-by-default with
  the R2 exception set, superseding the prior heuristic gate (~8+ files / parallelizable) as the gate on
  *whether* to delegate; the heuristics remain only as guidance for intra-step granularity.

### Per-task model + caveman binding

- **R4** Every delegated dispatch MUST resolve the model tier for that task from
  `models.routing.{commands,skills,agents}` via `scripts/resolve-model-tier.sh` and pass the resolved concrete
  model as an explicit `model:` argument on the `Task` call (never `model: inherit` from the parent session,
  per PRD 012 DL-2).
- **R5** Every delegated dispatch MUST resolve the caveman intensity for that task and inject it into the
  sub-agent context. Caveman binding is **best-effort by nature** (prompt-level, not platform-enforced) and is
  treated as such in Success Criteria — distinct from model binding (R4), which the mechanical gate enforces.
- **R6** `communication.routing` MUST be extended with `skills` and `agents` maps (mirroring `models.routing`),
  so caveman intensity is independently tunable per skill and per agent. Resolution precedence is
  command → skill → agent, falling back to `communication.defaultIntensity` only when no routing entry exists.
- **R7** `.sw/config.schema.json` MUST accept the new `communication.routing.skills` and
  `communication.routing.agents` maps, and `/sw-setup` seeding MUST seed defaults from the bundled
  `core/sw-reference/communication-routing.defaults.json` (extended with the new maps).
- **R8** The model-binding hook (`core/hooks/before_task_dispatch.py`) MUST remain registered as
  forward-compatible defense-in-depth and MUST NOT be relied upon as the binding mechanism; explicit `model:`
  on dispatch (R4), enforced by R23, is authoritative.
- **R24** Caveman intensity precedence MUST be defined and implemented: a dispatch-bound intensity (R5) MUST
  take precedence over `sessionStart`-injected caveman in the spawned sub-agent. The implementation MUST
  either pass `--skill`/`--agent` routing context into the delegated session or suppress `sessionStart`
  caveman resolution for dispatch-bound sub-agents, so the two cannot disagree.

### Enforcement

- **R9** A generalized, fail-closed dispatch-check (a new `scripts/dispatch-check.sh` with
  `--command|--skill|--agent`; `scripts/reviewer-dispatch-check.sh` becomes a thin wrapper) MUST validate that
  a delegated dispatch has a resolved model and a resolved intensity, applying the builder-floor rule **only**
  to reviewer/persona agents (not to cheap-tier mechanical or `generalPurpose` dispatch). It MUST fail closed
  with actionable remediation; the only bypass is a recorded `--override` (R26).
- **R10** The dispatch-check MUST emit a structured `cause` enum distinguishing **binding** failures
  (`binding:no-model`, `binding:no-intensity`) from **harness** backpressure (`harness:capacity`). The
  orchestrator MUST halt on `binding:*` causes regardless of retry count, and MUST treat only `harness:*` as
  retryable with bounded parallelism. An agent MUST NOT reclassify a binding cause as backpressure.
- **R23** Binding MUST have a mechanical pre-`Task` floor, not procedural-only enforcement: a pre-dispatch
  preflight (e.g. `scripts/wave.sh dispatch preflight`) MUST record a per-dispatch artifact (resolved model +
  intensity + dispatch nonce) immediately before the `Task` spawn for bound targets, and the registered
  `preToolUse` hook MUST deny a `Task` spawn for a bound target when no fresh preflight record exists for it.
  (On Cursor the hook cannot inject the model, but it CAN deny — denial is honored even though `updated_input`
  is not.)
- **R26** The `--override` bypass MUST require a durable, audited record (`scripts/shipwright-state.sh
  override-add` or a `run.log` JSONL event) capturing actor, timestamp, dispatch id, and the binding fields
  skipped, written **before** the dispatch; the dispatch-check MUST refuse `--override` absent such a record.
  An override MUST NOT bypass redaction (R25) or the push/merge chokepoints (R13).

### Parallel dispatch (wire + observe the frozen contract)

- **R22** The deliver driver (`scripts/wave_deliver_loop.py`) MUST emit a **batch dispatch action** for a wave:
  when a wave contains N independent ready phases, `compute_next_action` MUST return a single action that
  marks all N `in-flight` atomically and instructs the conductor to spawn N background `Task` sub-agents
  (`run_in_background: true`), rather than returning one `dispatch-ship` per phase. This is the concrete fix
  for the never-observed parallelism (PRD 004 R17/R18 + PRD 009 R14–R20 intent).
  - **R22a** A `delegation.mode` config knob (`bind-only` | `heuristic` | `default`) MUST select delegation
    aggressiveness: `bind-only` = bind model/intensity when delegating but keep today's heuristic gate on
    *whether* to delegate; `heuristic` = today's gate, no binding change; `default` = the R1 delegate-by-default
    invariant. The shipped default value is decided in the Rollout Plan / Open Questions gate.
- **R11** When the driver emits a batch (R22), the conductor MUST dispatch the phases concurrently up to
  `worktree.parallelCeiling`, observe peak concurrency ≥2 on parallelizable plans, and read outcomes **only**
  from durable `status.json` (never chat logs). This is a delta over PRD 009 R14–R20 (observability +
  driver-emitted batch), not a re-specification of the contract.
- **R12** Intra-phase / intra-step sub-agents MUST NOT consume `worktree.parallelCeiling` slots; only
  wave-level phase worktrees count (preserves PRD 004 R17/R18 — referenced, not restated).
- **R13** Only the conductor MUST call `merge enqueue` / `merge run-next` / `lock acquire`. Delegated phase
  sub-agents MUST NOT merge, acquire the lock, or perform a **raw** `git push`; all workflow pushes MUST route
  through `scripts/git-push.sh` (preserving the PRD 009 R23 / PRD 007 secret-scan push chokepoint — phase
  ships still push via `git-push.sh`).
- **R27** When multiple phases are `in-flight`, merge readiness MUST be collected and enqueued
  deterministically (e.g. phase-id sort) via an explicit `collect-all-ready` step before `merge run-next`, so
  two simultaneous `merge-ready-green` phases are both enqueued within bounded iterations. A background phase
  `Task` that fails or never writes terminal `status.json` MUST be marked `blocked` on harness
  completion/failure signal or a `deliver.watchdog.backgroundTaskTimeoutMinutes`, not left `in-flight` until
  the full phase-liveness timeout.

### Conductor-reliability hardening (consumes open GAP rows)

- **R14** While `verdict: running`, the conductor turn MUST end **only** via `report blockers` / `report
  terminal` with `halt: true`, or a row in the legitimate-halt table. Emitting any user-visible prose
  containing a status note plus a scope-confirmation/resume prompt (e.g. "Want me to continue?") is forbidden;
  remediation/status context goes to `run.log`. The prohibition is categorical (pattern class), not limited
  to the literal example.
- **R15** A phase whose final `status.json` is `merge-ready-green` MUST be treated as complete regardless of
  the remediation path it took. Additionally, while a phase is `in-flight` with remediation budget remaining,
  the conductor MUST NOT scope-pause; it may only `halt-blocked` on budget exhaustion (R28-detected halts
  excepted).
- **R16** After a `dispatch-ship` agent step begins, the conductor MUST NOT emit any user-visible text until
  the phase has written a terminal `status.json` (`merge-ready-green` or `blocked`); it MUST re-invoke the
  driver in the same turn. Incomplete ship work (uncommitted drafts, unwritten status) is not a turn boundary.
- **R28** Subjective "ambiguity / destructive action" MUST NOT be a freeform inline halt. Only
  **driver-detected** conditions qualify as inline legitimate halts (e.g. `merge run-next` conflict exit code,
  a `wave.sh` destructive-op denylist hit). Any other uncertainty MUST route through `report blockers` with a
  `cause`, never inline scope prose.
- **R17** A phase worktree MUST be torn down (`git worktree remove` + `prune`; never raw `rm`) promptly after
  the phase reaches `green-merged` AND post-merge incremental verify passes AND all affected dependents have
  forward-merged the new tip — via a `green-merged → teardown-pending → teardown-complete` transition that
  guards against an `in-flight`/`pending` dependent still referencing the worktree path. Before teardown the
  phase branch ref and final `status.json` MUST be retained in the run dir so a later bad-merge can
  re-provision. The orchestrator worktree persists until terminal completion; `phaseWorktrees[<id>]` is
  cleared on `teardown-complete`.

### Security

- **R25** All non-config context assembled into a delegated `Task` prompt (feedback text, Sentry payloads,
  diffs, run-log excerpts, memory-preflight results) MUST pass `scripts/memory-redact.sh` before dispatch, and
  untrusted blobs MUST be fenced (datamark-style) so a sub-agent cannot be prompt-injected by forwarded
  content. Raw transcript/memory payloads MUST NOT be forwarded. Delegated sub-agents that write memory MUST
  route through `memory-preflight` + `memory-redact.sh` (never a direct provider call), and phase
  `status.json` / `run.log` writes that may carry runtime text MUST be redacted before persist.

### Cross-cutting

- **R18** The conductor contract (`core/skills/conductor/SKILL.md` + `core/rules/sw-conductor.mdc`) remains the
  single source for the loop, legitimate-halt set, and parallel-dispatch behavior; each orchestrator command
  references it and MUST NOT duplicate the loop prose.
- **R19** All behavior authored in `core/` MUST propagate to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all`, with the emitter freshness gate (`scripts/test/run-emitter-fixtures.sh`)
  passing.
- **R20** New behaviors MUST be covered by fixtures (see Testing Strategy), including per-orchestrator
  delegation coverage and integration-style (not doc-grep-only) concurrency/binding assertions.
- **R21** Documentation MUST be updated — `rules/sw-subagent-dispatch.mdc`, `core/skills/conductor/SKILL.md`,
  the five orchestrator command files, `core/sw-reference/communication-routing.defaults.json`,
  `core/sw-reference/models-tiering.md`, `.sw/layout.md`, and the relevant guides.

## Technical Requirements

- **TR1 — Dispatch policy rewrite + closed exception sets.** Rewrite `core/rules/sw-subagent-dispatch.mdc` to
  the delegate-by-default standing gate honoring `delegation.mode`; demote the file-count/parallelizable
  heuristics to granularity guidance (R1–R3, R22a). Each orchestrator command enumerates its **closed**
  inline bookkeeping allowlist (R2, R18).
- **TR2 — Intensity resolver + extended routing.** Add `communication.routing.skills`/`agents` to the bundled
  defaults, `.sw/config.schema.json`, and `/sw-setup` seeding (R6, R7). Add `scripts/resolve-intensity.sh`
  (or a `resolve-model-tier.sh`-adjacent verb) returning intensity for `--command|--skill|--agent` with the
  R6 precedence, and implement the R24 precedence (dispatch > sessionStart) in `guardrail_core` session-context
  assembly for delegated sessions.
- **TR3 — Dispatch binding + redaction contract.** Orchestrators resolve model (`resolve-model-tier.sh`) and
  intensity (TR2), redact/fence context (R25), and pass explicit `model:` + injected intensity on every
  `Task` (R4, R5, R25). The hook stays registered, no-op-tolerant on Cursor (R8).
- **TR4 — Generalized dispatch-check + mechanical gate.** Add `scripts/dispatch-check.sh`
  (`--command|--skill|--agent`, model + intensity validation, structured `cause` enum, reviewer-only builder
  floor; `reviewer-dispatch-check.sh` wraps it) (R9, R10). Add `scripts/wave.sh dispatch preflight` recording a
  per-dispatch nonce artifact, and extend `core/hooks/before_task_dispatch.py` to **deny** a bound `Task`
  spawn lacking a fresh preflight record (R23). Wire `--override` durable audit (R26).
- **TR5 — Parallel batch driver + wiring.** Add the batch dispatch primitive to `scripts/wave_deliver_loop.py`
  (`compute_next_action` returns a batch action marking N phases `in-flight` atomically; `persist_cursor`
  updates after merge) and the conductor dispatch of ≥2 background Tasks per batch; `collect-all-ready` +
  deterministic enqueue + background-Task failure/timeout handling (R11, R22, R27). Fixtures observe runtime
  concurrency, not `wave.sh schedule` JSON alone.
- **TR6 — Conductor loop guarantees (mechanical, not prose-only).** Encode R14–R16/R28 in
  `core/skills/conductor/SKILL.md` + `core/rules/sw-conductor.mdc` + the `/sw-deliver` loop, backed by a
  mechanical handshake: a driver flag/state that suppresses user-visible output while `verdict: running`
  pending a terminal phase `status.json`, plus a post-turn linter fixture that fails on status-pause / proxy
  prose patterns (R14, R16). R15/R28 add the in-flight-remediation and driver-detected-halt rules.
- **TR7 — Safe eager teardown.** Wire teardown into the merge path after `verify run-after-merge` and after
  dependent forward-merge, via the `teardown-pending → teardown-complete` state with dependent-reference and
  retained-ref guards; clear `phaseWorktrees[<id>]` only on completion; keep the orchestrator worktree (R17).
- **TR8 — Per-orchestrator adoption (bounded to the audit).** Apply the delegation invariant + binding + halts
  per the PRD 009 adoption audit deltas — `/sw-ship` (SHIP-A1..A4) → `/sw-debug` (DBG-A1..A2) → `/sw-doc`
  (DOC-A1..A2) → `/sw-feedback` (FB-A1..A2) — referencing the conductor contract. Adoption is **bounded to the
  audit IDs**; doc/feedback adoption means delegating substantive atomics, not re-architecting their human
  gates (R18, R1). (Deliver-loop hardening is Rollout Phase 2, not part of TR8.)
- **TR9 — Emitter + docs + fixtures.** Regenerate `dist/` (freshness gate passing); update the R21 docs; add
  the Testing Strategy fixtures (R19–R21).

## Security & Compliance

The new surface is **how sub-agents are dispatched and what context is injected into them**; pervasive
delegation and parallelism amplify that surface, so it is addressed explicitly rather than asserted unchanged.

- **Dispatch-prompt assembly (R25).** Every non-config blob injected into a delegated prompt is redacted via
  `scripts/memory-redact.sh` and untrusted content is fenced; raw transcripts/memory payloads are never
  forwarded. This is the primary new exposure and is fail-closed (redaction failure aborts the dispatch).
- **Override audit (R26).** `--override` is durably recorded (actor, time, dispatch id, skipped fields) and
  cannot bypass redaction or the push/merge chokepoints.
- **Push / merge chokepoint (R13).** Conductor-only merge/lock; no raw `git push`; workflow pushes use
  `scripts/git-push.sh` (PRD 007 secret-scan pre-push preserved). No `main` auto-merge.
- **Memory redaction (R41) on delegated paths.** Delegated sub-agents reach memory only through
  `memory-preflight` + `memory-redact.sh`; no direct provider calls (sw-guardrails). Phase `status.json` /
  `run.log` writes are redacted (R25).
- **Concurrency amplification (R11).** Peak concurrent background sub-agents multiply shared parent tool/env
  access and provider-bound context; sensitive context in phase-level dispatch prompts is capped, and this
  amplification is documented (not a new credential scope — R43 trust boundary unchanged in kind).
- **Mechanical binding gate (R23).** The `preToolUse` deny path closes the procedural-only gap so a forgotten
  `model:` cannot silently regress to session inherit for bound targets.

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test`. Concurrency and
binding fixtures MUST be integration-style (observe runtime dispatch/state), not doc-grep-only.

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `delegation-default-invariant` | substantive steps delegate under `delegation.mode: default`; closed inline exceptions run inline | R1, R2 |
| `delegation-mode-knob` | `bind-only` / `heuristic` / `default` select the correct gate behavior | R22a |
| `dispatch-rule-default-gate` | dispatch rule standing gate is delegate-by-default; heuristics demoted | R3 |
| `dispatch-binds-model` | every delegated dispatch carries an explicit resolved `model:` (no `inherit`) | R4 |
| `dispatch-hook-forward-compat` | the model hook is registered and no-op-tolerant on Cursor (deny works; inject does not) | R8 |
| `dispatch-binds-intensity` | delegated dispatch injects the resolved intensity; best-effort recorded | R5 |
| `intensity-routing-extended` | schema accepts `communication.routing.skills`/`agents`; precedence command→skill→agent→default | R6, R7 |
| `intensity-precedence-no-double-resolve` | dispatch-bound intensity wins over `sessionStart` caveman for delegated sub-agents | R24 |
| `dispatch-check-fail-closed` | unbound dispatch refused; recorded `--override` bypass only; reviewer-only builder floor | R9 |
| `dispatch-check-cause-enum` | `binding:*` halts regardless of retry; only `harness:*` retried as backpressure | R10 |
| `dispatch-preflight-nonce-gate` | `preToolUse` denies a bound `Task` lacking a fresh preflight record | R23 |
| `dispatch-override-audited` | `--override` refused without a durable audit record; record captures actor/time/dispatch/fields | R26 |
| `dispatch-prompt-redacted` | non-config dispatch context is redacted + fenced; raw payloads not forwarded | R25 |
| `parallel-batch-driver` | `compute_next_action` emits a batch marking N phases `in-flight` atomically | R22 |
| `parallel-peak-concurrency-runtime` | ≥2 background Tasks dispatched concurrently (observed in state, not schedule JSON) | R11 |
| `parallel-collect-all-ready` | two simultaneous `merge-ready-green` phases both enqueued, deterministic order | R27 |
| `parallel-background-task-failure` | a crashed/never-writing background phase Task → `blocked`, not stuck `in-flight` | R27 |
| `ceiling-slot-accounting` | intra-step sub-agents excluded from `parallelCeiling`; only phase worktrees count | R12 |
| `conductor-only-merge-lock` | phase sub-agents cannot `merge`/`lock acquire` | R13 |
| `phase-push-chokepoint` | phase pushes route through `git-push.sh`; no raw `git push` | R13 |
| `conductor-no-status-pause` | proxy-halt pattern matrix: no status+scope prose turn-end while `verdict: running` | R14 |
| `conductor-post-remediation-complete` | remediated → `merge-ready-green` is complete; in-flight remediation does not scope-pause | R15 |
| `conductor-reinvoke-after-dispatch-ship` | no user-visible text after `dispatch-ship` until terminal phase status; driver re-invoked | R16 |
| `conductor-driver-detected-halt-only` | only driver-detected ambiguity/destructive conditions halt inline; else `report blockers` | R28 |
| `phase-teardown-eager-safe` | teardown after green-merged + verify + dependent forward-merge; ref/status retained; `phaseWorktrees[id]` cleared on complete; orchestrator worktree persists | R17 |
| `conductor-single-source` | orchestrator commands reference the conductor contract; no duplicated loop prose | R18 |
| `orchestrator-delegation-per-command` | `/sw-ship`,`/sw-debug`,`/sw-doc`,`/sw-feedback` delegate substantive atomics with bound model+intensity | R1, R4, R5, TR8 |
| `delegation-emitter-freshness` | `dist/` regenerated and fresh | R19 |
| `delegation-docs-presence` | dispatch rule, conductor skill, five commands, routing defaults, tiering ref, layout, guides describe the changes | R21 |

R20 is satisfied by this fixture set itself. Per-R traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/pervasive-subagent-delegation`, delivered in dependency-ordered phases.
  **Conductor reliability lands before orchestrator-wide delegation** (resolves the panel's ordering finding
  and DL-6):
  1. **Binding + enforcement foundation** — dispatch policy rule, intensity resolver + extended
     routing/schema/seeding, generalized dispatch-check, mechanical preflight/hook gate, override audit,
     dispatch redaction (R4–R10, R23–R26, R25, TR1–TR4).
  2. **Deliver reliability** — parallel batch driver + runtime concurrency, conductor loop guarantees,
     safe eager teardown, on `/sw-deliver` (R11–R17, R22, R27, R28, TR5–TR7). **Hard gate:** Phase 2 fixtures
     (parallel concurrency + conductor hardening + teardown) MUST be green, and a supervised **live
     acceptance run** (frozen task list with ≥2 independent phases → observed concurrent phase worktrees, no
     status-pause to the terminal gate, logged per-phase model IDs) MUST pass, before Phase 3.
  3. **Per-orchestrator adoption** — `/sw-ship` → `/sw-debug` → `/sw-doc` → `/sw-feedback`, bounded to the
     PRD 009 audit IDs (R18, TR8). Optionally split into two waves (ship+debug, then doc+feedback).
  4. **Docs + dist + fixtures** (R19–R21, TR9).
- **`delegation.mode` default (Open Question OQ1).** Shipped default is `default` (delegate-by-default, the
  operator's stated intent) **iff** the Phase 2 live-acceptance gate passes; otherwise ship `bind-only` and
  flip to `default` in a follow-up once reliability is proven. Operators can always set the knob per repo.
- **Backward compatible.** Existing `models.routing` resolution preserved; new `communication.routing`
  maps default to today's behavior when unseeded; the dispatch-check fails closed only for delegated dispatch.
- **Bootstrap caution.** First delivery SHOULD be supervised (`doc.afterTasks: confirm` / `--after-tasks
  stop`) until Phase 1–2 fixtures are green (mirrors PRD 007/013).
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Delegate-by-default with a closed inline exception set (not "literally everything", not "keep heuristic gate") | Captures pervasive-delegation intent while keeping interactive gates inline; proxying interactive prompts is disproportionate (operator selection). |
| DL-2 | New PRD 017, not an amendment to frozen PRD 013/015 | Cross-cutting across five orchestrators; the planned PRD 009 R35 follow-on plus scope expansion. Amending an unrelated frozen PRD breaches freeze discipline (scope-guardian lens). |
| DL-3 | Extend `communication.routing` with `skills` + `agents` maps | Mirrors `models.routing` so "settings defined for that task" is real at every granularity (operator selection). |
| DL-4 | Bind via explicit `Task` dispatch args; hook is forward-compatible only | Cursor ignores `updated_input.model` on `Task` (PRD 012 DL-2); explicit dispatch is the only reliable binding (feasibility lens). |
| DL-5 | Fail-closed dispatch-check + mechanical `preToolUse` deny as the enforcement floor | The hook cannot inject model on Cursor, but it CAN deny; a procedural check plus a deny gate closes the silent-regression gap the panel found (adversarial + reliability lenses). |
| DL-6 | Fold conductor-reliability hardening (R14–R17, R27, R28) into this PRD, but sequence it BEFORE orchestrator-wide delegation | Delegate-by-default amplifies the in-turn loop; shipping policy on an unreliable loop worsens the pain. Phase 2 hard gate enforces ordering (operator selection + product/adversarial lenses). |
| DL-7 | `/sw-ship` is in scope as a fifth orchestrator | It is Wave 1 of the audit and the engine where most delegatable atomics live; pervasive binding is meaningless without it (feasibility lens). |
| DL-8 | Conductor contract is the single source; R11–R13 are deltas, not re-spec | Prevents drift from frozen PRD 009 R14–R20 / PRD 004 R17/R18 (coherence + scope-guardian lenses; PRD 009 R18 single-source continuity). |
| DL-9 | Rollout is reliability-first with a supervised live-acceptance gate; `delegation.mode` default is conditional on it | The observed-parallelism pain is the R22 driver bug; success must be operator-observable, not fixture-only (product lens). |
| DL-10 | Caveman binding is best-effort (prompt-level); only model binding is mechanically enforced | Intensity injection is unenforceable like the old model hook; over-claiming parity would mislead. Dispatch-check enforces model, records intensity (feasibility lens). |
| DL-11 | Eager teardown uses a `teardown-pending → teardown-complete` state with dependent + retained-ref guards | A bare teardown after green-merged risks ENOENT for dependents and lost recovery context on bad merge (adversarial lens). |

## Open Questions

None. The shipped `delegation.mode` default is resolved (operator-confirmed at the doc-review gate): ship
`default` (delegate-by-default) gated on the Phase 2 supervised live-acceptance run passing; fall back to
`bind-only` and flip to `default` in a follow-up if reliability is not proven at ship time. Recorded in
Rollout Plan and DL-9.
