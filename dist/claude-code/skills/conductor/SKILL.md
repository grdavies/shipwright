---
name: conductor
description: Conductor guardrails — legitimate halts only, no nested dispatch, durable-state authority. USE WHEN running /sw-deliver or any orchestrator that adopts the conductor contract. Shared autonomous orchestration contract — self-continuation, legitimate halts, parallel phase dispatch, and durable-state resumption. Consumed by orchestrators; never re-authored inline.
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: phase_default
        selectionFamily: subagent-dispatch
        command: sw-deliver
    metadata:
      skill: conductor
      selectionFamily: subagent-dispatch---

# Conductor contract

Single referenced primitive for agent-native orchestration (PRD 009 R1). Orchestrators (`/sw-deliver` pilot;
`/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback` in follow-on PRDs) **load this skill** and delegate loop
behavior here — they do not re-implement state transitions, merge logic, or halt policy in prose (R3).

**Model tier:** inherit — resolve delegated atomics via `python3 scripts/resolve-model-tier.py --command <child-slug>`.

## Mechanical source of truth

Every state transition, merge-queue operation, gate evaluation, and bookkeeping action runs through the
existing `wave_*.py` primitives behind `scripts/wave.py` — never duplicated in agent instructions:

| Concern | Entrypoint |
| --- | --- |
| Plan + waves | `scripts/wave.py plan`, `scripts/wave.py schedule` |
| Plan validation | `scripts/wave.py plan validate` → `scripts/wave_plan_validate.py` (two-tier, closed-world) |
| Durable driver | `scripts/wave.py deliver-loop` |
| Run-state R/W | `scripts/wave.py state …` |
| Provision / teardown | `scripts/wave.py orchestrator provision`, `scripts/wave.py phase provision` |
| Phase outcomes | `scripts/wave.py status collect` → `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Merge queue | `scripts/wave.py merge enqueue`, `scripts/wave.py merge run-next` |
| Locks / journal | `scripts/wave.py lock …`, `scripts/wave.py journal …` |
| Halt report | `scripts/wave.py report terminal` |
| Living-doc reconcile | `scripts/wave.py living-docs reconcile`, `scripts/wave.py docs-currency` |

The conductor **invokes** these commands and interprets their JSON — it does not maintain parallel state.

## Durable artifacts (resumption — R4)

A fresh agent with no prior chat context resumes from:

| Artifact | Path |
| --- | --- |
| Run cursor (scoped) | `.cursor/sw-deliver-state.<slug>.json` at **repo root** (`nextAction`, `currentWave`, phase statuses) |
| Plan | `.cursor/sw-deliver-plan.json` |
| Concurrent-run index | `.cursor/sw-deliver-runs/index.json` |
| Per-phase `/sw-ship` status | `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Phase step plan | `.cursor/sw-deliver-runs/<phase-slug>/phase-step-plan.json` (executor-owned) |
| Wave batching plan | `waveBatchingPlan` on `.cursor/sw-deliver-state.<slug>.json` (conductor-only) |
| Two-tier lifecycle | `twoTierLifecycle` on shared run-state |
| Append-only progress | `.cursor/sw-deliver-runs/run.log` |

**Per-branch scoped deliver state (PRD 013):** orthogonal feature branches each own
`sw-deliver-state.<slug>.json` + `sw-deliver-<slug>.lock`. The conductor never treats branch B's
in-flight run as stale identity for branch A. All writes use the repo-root canonical path (R28) — not a
duplicate under orchestrator worktree `.cursor/`.

Resume command (phase-mode):

```text
/sw-deliver run <frozen-task-list-path>
# inspect driver cursor (internal mechanical driver):
python3 scripts/wave.py deliver-loop --dry-run
```

User-facing resume/handoff MUST use `/sw-deliver run …`. The bash `deliver-loop` driver is for
conductor in-turn mechanical re-invocation only — never surface it as the operator resume command (R29).

Never infer progress from chat history or ephemeral sub-agent logs (R19). Phase outcomes come solely from
`status.json`.


## Phase status discovery and disambiguation (PRD 059 R5–R6)

Per-phase durable status and gap-check binding use the shared discovery chain
(`scripts/phase_status_discovery.py`): **canonical repo root → phase worktree → glob** under
`.sw-worktrees/*/.cursor/sw-deliver-runs/<phase-slug>/`. Gap-check and merge paths share the helper;
HEAD-stamp disambiguation prefers the current phase head, and **binding halt verdicts win** over stale pass
candidates.

## Terminal blocker recovery shape (PRD 059 R14–R15)

`scripts/wave.py report blockers` maps terminal branch causes to recovery commands without schema changes:

| `cause` | Recovery hint |
| --- | --- |
| `terminal-branch-missing` | Recreate/reprovision target branch, then retry `terminal pr prepare` |
| `terminal-branch-unresolvable` | Retry when host reachable; verify host auth/token via `scripts/host.py` |


## Two-tier plan lifecycle (PRD 022)

Proposals route through `python3 scripts/wave.py plan validate` — **never** hand-author plan JSON in prose.
Kernel invariants live in `core/sw-reference/kernel-classification.md` (single home — do not duplicate the
enumeration here).

| Tier | Proposer | Validated plan | Durable owner | Driver |
| --- | --- | --- | --- | --- |
| Wave | Conductor at wave entry | Wave-batching plan | `waveBatchingPlan` on shared run-state | `wave_deliver_loop` |
| Phase | Phase executor at phase entry | Phase step plan | `.cursor/sw-deliver-runs/<phase-slug>/phase-step-plan.json` | `ship_phase_steps.py` |

**Lifecycle** (`twoTierLifecycle` on shared run-state): `wave-validated` → `phase-plan-pending` →
`phase-plan-validated`. Crash with a validated wave but missing/pending phase plan re-runs phase
proposal+validate only — never partial execution.

**Reject fallbacks:** phase reject → canonical chain from `kernel-classification.json`; wave contention or
dependency violation → canonical waves re-derived from the frozen plan; over-ceiling → `wave.py schedule`.

**Proposed pilot wiring (PRD 023 phase 1):** `/sw-deliver` reads `orchestration.planPolicy` at wave entry and
phase entry. Under `proposed` (after TR0 gate), the conductor proposes → `wave.py plan validate`
(`--record-rejection` on shared state) → persist; `wave_deliver_loop` sets `wave-validated` after wave persist
and routes phase entry through validate-before-persist. Default `canonical` is unchanged.

**`orchestration.planPolicy`:** read at proposal time (default `canonical` — byte-identical to today);
recorded `planPolicy` + `kernelVersion` + `guidelineVersion` stamped on each persisted plan and honored on
resume over live config. Live `proposed` runs on `/sw-deliver` when TR0 passes and pilot opt-in guards are
met; default stays `canonical`. PRD-024 fans the pattern to other orchestrators — see
`docs/prds/022-kernel-classification-and-plan-validation/call-site-map.md`.

## Default autonomy (R13)

With default configuration (`deliver.autonomy.mode: autonomous`, `phaseAckCadence: 0`, `doc.afterTasks` not
blocking deliver), a frozen task list runs end-to-end to the **terminal-PR human gate** with zero
"continue deliver" style re-prompts. See **In-turn self-continuation loop** below (R6/R7).

## In-turn self-continuation loop (R2, R6, R7)

The conductor never ends its turn while `nextAction` is runnable and no legitimate halt applies.

### Driver ↔ agent handshake

1. Invoke `python3 scripts/wave.py deliver-loop` (or `--dry-run` to inspect only).
2. Parse JSON:
   - **`awaitAgent: false`** — driver advanced mechanically; immediately re-invoke `deliver-loop` (same turn).
   - **`awaitAgent: true`** — perform the agent step for `next.action` (see table), then re-invoke
     `deliver-loop` without asking the user to continue.
3. Repeat until `terminal: true`, `halt: true`, or a legitimate halt in **Legitimate-halt set**.

| `next.action` | Agent work (then re-invoke `deliver-loop`) |
| --- | --- |
| `dispatch-batch` | Spawn **N background** `Task` sub-agents (`run_in_background: true`) — one per `phases[]` entry in the batch; each runs provision (if needed) + full `/sw-ship --phase-mode` in its phase worktree |
| `dispatch-ship` | Full `/sw-ship --phase-mode` **inline** in the phase worktree (`SW_PHASE_MODE=1`, `SW_PHASE_SLUG`, `SW_RUN_DIR`); **never** `run_in_background: true` |

### Inline dispatch lease (PRD 063 R7–R9)

- **`dispatch-ship`** acquires a durable per-phase ship lease (`python3 scripts/wave.py ship-lease acquire`) before
  stamping `inlineDispatchedAt`. A second `dispatch-ship` while the lease is live returns `await-in-flight` —
  never spawn a duplicate inline Task.
- **`dispatch-batch`** is the **only** conductor action that may use `run_in_background: true` on `Task` spawns.
- `python3 scripts/dispatch-check.py --dispatch-action dispatch-ship --run-in-background` fails closed unless an
  audited `--override` is recorded.
- Stale lease reclaim (`wave_lock.py`) runs only when heartbeat is stale **and** the phase has no consumable
  terminal `status.json`; crash-after-acquire without spawn is reclaimable; a live inline Task keeps the lease.
- Release the lease on `collect-status` after terminal phase outcomes are collected.
| `remediate` | `/sw-stabilize` (or scoped fix) for the blocked phase within remediation budget |
| `retrospective` | `/sw-retrospective --pre-merge` on the orchestrator worktree after all phases merge (R9; single-sourced chain) |
| `terminal-ship` | After `retrospective` when pre-merge done: terminal PR prepare/gate, CI watch + `/sw-ready`; may arm self-wake (below) |

**Terminal autonomy (PRD 013 A1):** when `deliver.terminal.autonomy: auto`, the conductor runs
`terminal retro run` then `terminal ship run` hands-off (bounded gate watch + `/sw-stabilize` via
`deliver.remediation.maxAttempts`). Merge to `main` stays human-gated. Optional `cleanup.autonomy: auto`
applies safe post-merge cleanup when deterministic.

**Orchestrator worktree:** run `deliver-loop` from `.sw-worktrees/<slug>-orchestrator` (mandatory
orchestrator provisioning — repo root is not an alternate conductor-loop cwd). Repo-root `.cursor/`
updates during deliver are expected conductor runtime, not feature implementation; tracked
`defaultBaseBranch` must not accumulate implementation commits during a run. See `.sw/layout.md`
**Operator worktree contract**. Never hand off with "run deliver-loop next" as the only instruction —
run it in-turn.

### Progress rule (R7)

Do not stop after a single mechanical step or one phase ship if `verdict` is still `running` and
`nextAction` is not a legitimate halt. The only acceptable turn endings are legitimate halts or terminal
completion.

### No status-pause (R14)

While `verdict: running`, never end the turn with user-visible prose that combines a status update with a
scope-confirmation or resume prompt. Remediation context belongs in `run.log` / consolidated halt reports.

### Post-remediation complete (R15)

A phase whose final `status.json` is `merge-ready-green` is complete regardless of remediation path. While
a phase is `in-flight` with remediation budget remaining, do not scope-pause.

### Silent dispatch window (R16)

After `dispatch-ship` or `dispatch-batch`, emit no user-visible text until every dispatched phase has
terminal `status.json`. Poll per **Parallel-wave completion wait** when `awaitInFlight: true`.

### Terminal transition (R14/R16 at terminal boundary)

The `retrospective` and `terminal-ship` driver actions are **awaitAgent-non-optional**: while
`verdict: running`, the conductor performs each terminal step and re-invokes `deliver-loop` in the
**same turn** — never end the turn between them.

At this boundary the **no-status-pause** prohibition (R14) applies with full force: do not emit a
wave-complete status update combined with a scope-confirmation or resume prompt. Terminal remediation
context belongs in `run.log` / consolidated halt reports only.

### Driver-detected halts only (R28)

Subjective ambiguity is not an inline halt. Only driver-detected conditions qualify; other uncertainty
routes through `report blockers` with a `cause`.


## Execute tier fan-out (PRD 053)

Phase executor (not conductor) owns execute-tier lifecycle:

| Step | Owner | Primitive |
| --- | --- | --- |
| Execute plan validate | Phase executor | `wave.py plan validate --tier execute` |
| Per-ref Task dispatch | Phase executor | `intra_phase_dispatch.py` with `conductorMode: execute_fan_out` |
| Sub-branch integrate | Phase executor | `wave.py execute integrate` → `execute_integrate.py` |
| Terminal gate | Phase executor | `execute_ship.py gate-check` before `sw-verify` |

Conductor merge queue (`wave_merge.py`) handles phase→target only. Execute integrate is **never** enqueued
on the conductor merge queue. Background-phase nested Task carve-out: see
`rules/sw-dispatch-background-phase.mdc` execute partition.

## Conductor loop hard-stop (R38)

Register bounds in `rules/sw-subagent-dispatch.mdc` hard-stops table.

| Bound | Source | On trip |
| --- | --- | --- |
| Max driver invocations per turn | `deliver.autonomy.maxIterations` (default **500**) | Consolidated halt; resume via `deliver-loop` |
| No-progress circuit breaker | **3** consecutive invocations with identical `nextAction` **and** identical durable-state signature | Consolidated halt (`cause: conductor:no-progress`) |

**State signature** (canonical JSON of): `verdict`, `nextAction`, `currentWave`, sorted phase
`id→status`, `mergeQueue` length, `mergeJournal` presence. Ignore `driverHeartbeatAt` / `updatedAt`.

On circuit breaker: `python3 scripts/wave.py report terminal` (or `report blocker`) — never spin silently.

## Self-wake sentinel (R8, R9)

For time-gated external waits (terminal-PR CI, long `checks.watch` polls), arm a **uniquely named**
background shell with `notify_on_output` so the conductor resumes without a user message.

**Run id** (stable per deliver run): `sw-deliver-<prd_number>-<target.slug>` from the scoped
`.cursor/sw-deliver-state.<slug>.json` (e.g. `sw-deliver-009-autonomous-orchestration-conductor`).

### Terminal-PR CI wait

After `/sw-pr` on the feature branch:

```bash
RUN_ID="sw-deliver-009-autonomous-orchestration-conductor"   # from state
PR=$(python3 scripts/host.py resolve-pr-for-branch)
python3 scripts/host.py checks --number "$PR"
echo "DELIVER_WAKE_${RUN_ID} {\"phase\":\"terminal-ci\",\"prd\":\"009\"}"
```

### Phase-mode dispatch-ship CI wait (PRD 063 R3)

For phase-PR CI (not terminal), use a **phase-unique** sentinel so concurrent phases do not collide:

```bash
PHASE_SLUG="<phase-slug>"   # from SW_PHASE_SLUG / deliver state
echo "DELIVER_WAKE_${RUN_ID}_${PHASE_SLUG} {\"phaseId\":\"<id>\",\"phaseSlug\":\"${PHASE_SLUG}\"}"
```

Arm with `notify_on_output` matching `^DELIVER_WAKE_${RUN_ID}_${PHASE_SLUG}`. Never reuse terminal-only `DELIVER_WAKE_${RUN_ID}` for in-wave phase CI.

Arm as background shell with `notify_on_output` matching `^DELIVER_WAKE_${RUN_ID}`. Reuse
`checks.watch.pollSeconds` / `checks.watch.maxWaitMinutes` from config — no new knob.

### Teardown (R9)

On any terminal halt (`verdict: complete|blocked|rejected`) or human stop:

- Cancel/kill background shells tagged with `DELIVER_WAKE_<run-id>` and any deliver heartbeats for that run id.
- Never leave orphaned watchers holding tokens after the run ends.

## External-wait exhaustion (R40)

When a self-wake or CI watch reaches `checks.watch.maxWaitMinutes` without a terminal signal:

1. Emit consolidated halt via `scripts/wave.py report terminal` (`cause: external-wait:exhausted`).
2. Do not trust stale log output — re-derive next action from durable state on the next wake or resume.
3. Treat as a legitimate halt (user may merge manually or resume watch).

## Parallel-wave completion wait (R44)

When multiple phases run concurrently, the conductor waits for **all** wave members to publish terminal
`status.json` before enqueue/merge advancement.

**Contract (pick one per environment; both bounded by `checks.watch.maxWaitMinutes`):**

1. **Poll:** every `checks.watch.pollSeconds`, test
   `.cursor/sw-deliver-runs/<phase-slug>/status.json` for each in-flight phase in the current wave batch.
2. **Self-wake:** arm `notify_on_output` on a watcher that tails `run.log` or polls status paths; pattern
   `^DELIVER_PHASE_READY_<run-id>` emitted when all batch members have terminal status.

When every member is `merge-ready-green` or `blocked`, re-invoke `deliver-loop` in-turn — never ask the user
to "check if phases finished".

When the driver returns `awaitInFlight: true`, poll status paths per this section before the next
`deliver-loop` invocation — do not re-dispatch `/sw-ship` for phases already marked `backgroundDispatchedAt`.

### collect-all-ready (R27)

When multiple in-flight phases publish `merge-ready-green` simultaneously, the driver emits
`collect-all-ready` (mechanical) to enqueue all ready phases in deterministic phase-id order before
`merge run-next`. The conductor never merges until the driver advances the merge queue.

## Self-wake environment fallback (R46)

Where the harness cannot auto-resume on `notify_on_output` (cloud/headless agents):

1. **Degrade to bounded in-turn poll:** sleep `checks.watch.pollSeconds` between checks, up to
   `checks.watch.maxWaitMinutes` total wall clock.
2. After expiry → single consolidated halt (R12) with exact resume command.
3. Never busy-spin; never yield with only "waiting for CI" and no halt boundary.

Detect unavailable self-wake when background shell + `notify_on_output` is not offered by the runtime;
default to poll-then-halt rather than indefinite yield.

## Legitimate-halt set (R10)

Halt for human input **only** when one of these applies:

| # | Condition | Detection |
| --- | --- | --- |
| 1 | Final merge to `main` | Terminal gate (`report terminal`); never auto-merged |
| 2 | Remediation budget exhausted | `remediationAttempts[phaseId] >= deliver.remediation.maxAttempts` |
| 3 | Ambiguous merge / destructive action | Merge conflict, explicit revert, or irreversible git op |
| 4 | Configured checkpoint | `doc.afterTasks: confirm`, `deliver.phaseAckCadence: K>0`, `deliver.autonomy.mode: supervised` |
| 5 | Phase liveness timeout (R37) | `phase-timeout:<id>` — in-flight phase exceeds `deliver.watchdog.phaseTimeoutMinutes` without terminal `status.json` |
| 6 | External wait exhausted (R40) | CI/self-wake hits `checks.watch.maxWaitMinutes` without signal |
| 7 | Run-level autonomy budget (R42) | `deliver.autonomy.maxRunMinutes` or `maxIterations` exceeded |
| 8 | No-progress circuit breaker (R38) | 3× identical `nextAction` + unchanged state signature |
| 9 | Driver-enforced budget trip (PRD 023 TR3) | `runStartedAt` / `driverIterationCount` / `noProgressStreak` exceeded; `planRejectionLog` feeds no-progress |

Anything not in this table is **not** a legitimate halt.

### Driver-enforced budgets (PRD 023 TR3)

`wave_deliver_loop.py` maintains durable `runStartedAt`, `driverIterationCount`, and `noProgressStreak` on
shared run-state. Proposal and `plan validate` overhead count separately from execution iterations; persistent
`planRejectionLog` rejections increment no-progress. Budget trip emits `halt-blocked` with merge-queue journal
replayability and scoped lock release (R22). Terminal runs roll up `benefitMetric` and surface chosen plans /
rejections / capability sets via `deliver_plan_surfacing` (R21).

## No routine halts (R11)

The conductor **must not** pause or ask the user to continue for:

- Per-phase `/sw-ship` dispatch or completion
- `status collect`, `merge enqueue`, `merge run-next`, wave advancement
- Release bookkeeping (`bookkeeping record`)
- Living-doc reconcile (`living-docs reconcile` — INDEX, COMPLETION-LOG, GAP-BACKLOG on feature branch, R47–R51)
- Mechanical `deliver-loop` steps with `awaitAgent: false`

These advance in-turn via `deliver-loop` re-invocation. User-facing text like "continue deliver?" is
forbidden when the driver can proceed.

## Consolidated halt report (R12)

Every legitimate halt emits **one** actionable artifact — never a bare "continue?" prompt.

```bash
# Blocker / mid-run halt (blocked phase, watchdog, budget exhausted):
python3 scripts/wave.py report blockers
# Written to .cursor/sw-deliver-runs/blockers.json by deliver-loop halt-blocked

# All phases green — terminal human gate:
python3 scripts/wave.py report terminal
```

Each report includes `resumeCommand` (e.g. `/sw-deliver run docs/prds/…/tasks-….md`),
`blockers` with `recommendedCommand` (`/sw-stabilize` when applicable), and `cause`. Surface all three to
the user in one message.

## Phase liveness watchdog (R37)

Config: `deliver.watchdog.phaseTimeoutMinutes` (default **240**).

```bash
python3 scripts/wave.py watchdog check          # exit 20 when stale/timeout
python3 scripts/wave.py state heartbeat         # refresh driverHeartbeatAt during long agent work
```

`deliver-loop` `compute-next` calls the watchdog internally: an in-flight phase past timeout without
terminal `status.json` routes to `halt-blocked` (`cause: phase-timeout:<id>`), marks the phase `blocked`, and
writes the consolidated blocker report.

Driver heartbeat staleness (`driver-heartbeat-stale`) uses `SW_DRIVER_STALE_SECONDS` (default 4h) — refresh
with `state heartbeat` during long in-turn agent work.


## Parallel wave dispatch protocol (R14–R20)

Plan-time contention, schedule consumption, conductor Task dispatch, intra-phase rules, outcomes/blast radius, and safety invariants: `references/parallel-dispatch-protocol.md`.

## Bounded planning full-conductor (PRD 035 R8–R9, R23)

## Bounded planning full-conductor (PRD 035 R8–R9, R23)

`planning.autonomy` defaults to `maintenance-only`: mechanical/living graph bookkeeping runs autonomously
with **no prompts**; content-authoring decisions (pull-in, amendments, priority changes, cancel/supersede)
are auto-**proposed** and human-confirmed. The opt-in `full-conductor` posture elevates only
**gap/absorption-class** decisions to in-loop auto-decision via `scripts/planning_autonomy.py`.

| Constraint | Enforcement |
| --- | --- |
| Scope | Gap/absorption class only — never private/memory units |
| Confidence | `planning.fullConductor.confidenceThreshold` before auto-decide |
| Undo | `planning.fullConductor.undoWindowSeconds` before reconciler materializes |
| Mutation budget | `planning.fullConductor.mutationBudget` per session → legitimate halt `planning-mutation-budget` |
| No nested dispatch | Driver **enqueues handoffs only** — never `/sw-deliver`, `/sw-doc`, or any orchestrator from its loop |
| Reconcile boundary | Explicit halt between reconcile batch completion and downstream dispatch |
| Merge gate | Never weakens merge-to-`main`; branch protection never bypassed |
| Durable audit | Opt-in, `--override`, `--accept-frozen-impact`, direct-to-trunk logged (who/when/why) |

Entrypoints:

```bash
python3 scripts/planning_autonomy.py . posture
python3 scripts/planning_autonomy.py . evaluate --decision-type gap-absorb --visibility public
python3 scripts/planning_autonomy.py . step --proposals-file proposals.json
python3 scripts/planning_autonomy.py . enqueue-handoff --command "/sw-tasks confirm …"
python3 scripts/planning_autonomy.py . check-dispatch --command "/sw-deliver run …"
```

Resume after `planning-mutation-budget` halt: operator acknowledges and re-runs with explicit confirm or
lower scope — same legitimate-halt model as deliver conductor budgets.



Workflow pushes use `scripts/git-push.py` only (secret-scan pre-push; phase sub-agents never raw `git push`).

## Config knobs

Read from `.cursor/workflow.config.json`:

| Key | Default | Effect |
| --- | --- | --- |
| `deliver.autonomy.mode` | `autonomous` | `supervised` adds acknowledgement halts; `autonomous` uses minimal halt set |
| `deliver.autonomy.maxRunMinutes` | `1440` | Run-level wall-clock ceiling → clean halt (R42) |
| `deliver.autonomy.maxIterations` | `500` | Run-level driver-loop iteration ceiling (R42) |
| `deliver.phaseAckCadence` | `0` | Pause every K phase merges (checkpoint) |
| `deliver.remediation.maxAttempts` | `2` | Per-phase stabilize budget |
| `deliver.loop.drainMechanical` | `true` | Drain mechanical steps in-process until agent wait or halt (PRD 062 R7) |
| `worktree.parallelCeiling` | `4` | Max concurrent phase worktrees |

## Deliver-loop mechanical drain + timing (PRD 062 R7, R9, R19)

`wave_deliver_loop.py` reads `deliver.loop.drainMechanical` (default **`true`**):

| `drainMechanical` | Behavior |
| --- | --- |
| `true` (default) | `deliver-loop` executes mechanical actions in-process until `awaitAgent`, `awaitInFlight`, or a legitimate halt — reduces driver re-invocation churn |
| `false` | One mechanical step per `deliver-loop` invocation (legacy one-step posture) |

**Termination / halt surfaces:**

- **`--max-steps` budget** (default 12 per invocation) — when still mechanical after the budget,
  `conductor:drain-step-budget-exceeded` halts fail-closed (not an unqualified pass).
- **No-progress circuit breaker** — identical `nextAction` + state signature 3× → `conductor:no-progress`.
- **Identical mechanical signature N×** without state advance → stall halt (not pass).

**`elapsedMs` (R9):** `driver-transition` log events and `execute-mechanical` results include wall-clock
`elapsedMs` (optional subprocess timings). Values are numeric only — no secret-bearing argv in logs. Gate
semantics unchanged; timing is diagnostic/operator-observable only.


## PRD 062 release acceptance metrics (R18)

Operator acceptance checks: `references/release-acceptance.md`.


## Orchestrator adoption

| Orchestrator | Run durability | Adoption mode (PRD 024) | Status |
| --- | --- | --- | --- |
| `/sw-deliver` | **Durable** (PRD 007/013 run-state + crash-resume) | `full` when `planPolicy: proposed` | Pilot consumer (R34) — `deliver-loop` / `run` |
| `/sw-ship` | Phase-scoped (in-loop) | N/A (atomic chain) | Adopted (PRD 017) — SHIP-A1..A4 |
| `/sw-debug` | **Episodic** (session scratch; no crash-resume) | `full` | Adopted (PRD 017 + 024) — DBG-A1..A2 |
| `/sw-doc` | **Durable** (docs worktree → `/sw-deliver` handoff) | **`consistency-only` default** (R36c); `full` when variance probe shows latitude | Adopted (PRD 017 + 024) — DOC-A1..A2 |
| `/sw-feedback` | **Episodic** (session scratch; no crash-resume) | `full` | Adopted (PRD 017 + 024) — FB-A1..A2 |

**Durability (R37):** `durable` orchestrators may persist deliver/doc handoff run-state; `episodic`
debug/feedback validate at entry, surface R21 into `.cursor/sw-*-runs/<id>/episodic-run-summary.json`, and
abandon scratch on terminal halt — never deliver-scoped crash-resume.

Reference this skill from orchestrator commands; do not duplicate loop prose.
