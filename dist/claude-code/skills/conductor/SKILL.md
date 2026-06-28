---
name: conductor
description: Conductor guardrails — legitimate halts only, no nested dispatch, durable-state authority. USE WHEN running /sw-deliver or any orchestrator that adopts the conductor contract. Shared autonomous orchestration contract — self-continuation, legitimate halts, parallel phase dispatch, and durable-state resumption. Consumed by orchestrators; never re-authored inline.
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: subagent-dispatch
      command: sw-deliver
  metadata:
    skill: conductor
    selectionFamily: subagent-dispatch---

# Conductor contract

Single referenced primitive for agent-native orchestration (PRD 009 R1). Orchestrators (`/sw-deliver` pilot;
`/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback` in follow-on PRDs) **load this skill** and delegate loop
behavior here — they do not re-implement state transitions, merge logic, or halt policy in prose (R3).

**Model tier:** inherit — resolve delegated atomics via `bash scripts/resolve-model-tier.sh --command <child-slug>`.

## Mechanical source of truth

Every state transition, merge-queue operation, gate evaluation, and bookkeeping action runs through the
existing `wave_*.py` primitives behind `scripts/wave.sh` — never duplicated in agent instructions:

| Concern | Entrypoint |
| --- | --- |
| Plan + waves | `scripts/wave.sh plan`, `scripts/wave.sh schedule` |
| Plan validation | `scripts/wave.sh plan validate` → `scripts/wave_plan_validate.py` (two-tier, closed-world) |
| Durable driver | `scripts/wave.sh deliver-loop` |
| Run-state R/W | `scripts/wave.sh state …` |
| Provision / teardown | `scripts/wave.sh orchestrator provision`, `scripts/wave.sh phase provision` |
| Phase outcomes | `scripts/wave.sh status collect` → `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Merge queue | `scripts/wave.sh merge enqueue`, `scripts/wave.sh merge run-next` |
| Locks / journal | `scripts/wave.sh lock …`, `scripts/wave.sh journal …` |
| Halt report | `scripts/wave.sh report terminal` |
| Living-doc reconcile | `scripts/wave.sh living-docs reconcile`, `scripts/wave.sh docs-currency` |

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
bash scripts/wave.sh deliver-loop --dry-run
```

User-facing resume/handoff MUST use `/sw-deliver run …`. The bash `deliver-loop` driver is for
conductor in-turn mechanical re-invocation only — never surface it as the operator resume command (R29).

Never infer progress from chat history or ephemeral sub-agent logs (R19). Phase outcomes come solely from
`status.json`.

## Two-tier plan lifecycle (PRD 022)

Proposals route through `bash scripts/wave.sh plan validate` — **never** hand-author plan JSON in prose.
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
dependency violation → canonical waves re-derived from the frozen plan; over-ceiling → `wave.sh schedule`.

**Proposed pilot wiring (PRD 023 phase 1):** `/sw-deliver` reads `orchestration.planPolicy` at wave entry and
phase entry. Under `proposed` (after TR0 gate), the conductor proposes → `wave.sh plan validate`
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

1. Invoke `bash scripts/wave.sh deliver-loop` (or `--dry-run` to inspect only).
2. Parse JSON:
   - **`awaitAgent: false`** — driver advanced mechanically; immediately re-invoke `deliver-loop` (same turn).
   - **`awaitAgent: true`** — perform the agent step for `next.action` (see table), then re-invoke
     `deliver-loop` without asking the user to continue.
3. Repeat until `terminal: true`, `halt: true`, or a legitimate halt in **Legitimate-halt set**.

| `next.action` | Agent work (then re-invoke `deliver-loop`) |
| --- | --- |
| `dispatch-batch` | Spawn **N background** `Task` sub-agents (`run_in_background: true`) — one per `phases[]` entry in the batch; each runs provision (if needed) + full `/sw-ship --phase-mode` in its phase worktree |
| `dispatch-ship` | Full `/sw-ship --phase-mode` in the phase worktree (`SW_PHASE_MODE=1`, `SW_PHASE_SLUG`, `SW_RUN_DIR`) |
| `remediate` | `/sw-stabilize` (or scoped fix) for the blocked phase within remediation budget |
| `retrospective` | `/sw-retrospective --pre-merge` on the orchestrator worktree after all phases merge (R9; single-sourced chain) |
| `terminal-ship` | After `retrospective` when pre-merge done: terminal PR prepare/gate, CI watch + `/sw-ready`; may arm self-wake (below) |

**Terminal autonomy (PRD 013 A1):** when `deliver.terminal.autonomy: auto`, the conductor runs
`terminal retro run` then `terminal ship run` hands-off (bounded gate watch + `/sw-stabilize` via
`deliver.remediation.maxAttempts`). Merge to `main` stays human-gated. Optional `cleanup.autonomy: auto`
applies safe post-merge cleanup when deterministic.

**Orchestrator worktree:** run `deliver-loop` from `.sw-worktrees/<slug>-orchestrator` (or repo root with
state synced). Never hand off with "run deliver-loop next" as the only instruction — run it in-turn.

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

## Conductor loop hard-stop (R38)

Register bounds in `rules/sw-subagent-dispatch.mdc` hard-stops table.

| Bound | Source | On trip |
| --- | --- | --- |
| Max driver invocations per turn | `deliver.autonomy.maxIterations` (default **500**) | Consolidated halt; resume via `deliver-loop` |
| No-progress circuit breaker | **3** consecutive invocations with identical `nextAction` **and** identical durable-state signature | Consolidated halt (`cause: conductor:no-progress`) |

**State signature** (canonical JSON of): `verdict`, `nextAction`, `currentWave`, sorted phase
`id→status`, `mergeQueue` length, `mergeJournal` presence. Ignore `driverHeartbeatAt` / `updatedAt`.

On circuit breaker: `bash scripts/wave.sh report terminal` (or `report blocker`) — never spin silently.

## Self-wake sentinel (R8, R9)

For time-gated external waits (terminal-PR CI, long `checks.watch` polls), arm a **uniquely named**
background shell with `notify_on_output` so the conductor resumes without a user message.

**Run id** (stable per deliver run): `sw-deliver-<prd_number>-<target.slug>` from the scoped
`.cursor/sw-deliver-state.<slug>.json` (e.g. `sw-deliver-009-autonomous-orchestration-conductor`).

### Terminal-PR CI wait

After `/sw-pr` on the feature branch:

```bash
RUN_ID="sw-deliver-009-autonomous-orchestration-conductor"   # from state
PR=$(gh pr view --json number --jq .number)
gh pr checks "$PR" --watch --fail-fast >/tmp/${RUN_ID}-watch-ci.log 2>&1 || true
echo "DELIVER_WAKE_${RUN_ID} {\"phase\":\"terminal-ci\",\"prd\":\"009\"}"
```

Arm as background shell with `notify_on_output` matching `^DELIVER_WAKE_${RUN_ID}`. Reuse
`checks.watch.pollSeconds` / `checks.watch.maxWaitMinutes` from config — no new knob.

### Teardown (R9)

On any terminal halt (`verdict: complete|blocked|rejected`) or human stop:

- Cancel/kill background shells tagged with `DELIVER_WAKE_<run-id>` and any deliver heartbeats for that run id.
- Never leave orphaned watchers holding tokens after the run ends.

## External-wait exhaustion (R40)

When a self-wake or CI watch reaches `checks.watch.maxWaitMinutes` without a terminal signal:

1. Emit consolidated halt via `scripts/wave.sh report terminal` (`cause: external-wait:exhausted`).
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
bash scripts/wave.sh report blockers
# Written to .cursor/sw-deliver-runs/blockers.json by deliver-loop halt-blocked

# All phases green — terminal human gate:
bash scripts/wave.sh report terminal
```

Each report includes `resumeCommand` (e.g. `/sw-deliver run docs/prds/…/tasks-….md`),
`blockers` with `recommendedCommand` (`/sw-stabilize` when applicable), and `cause`. Surface all three to
the user in one message.

## Phase liveness watchdog (R37)

Config: `deliver.watchdog.phaseTimeoutMinutes` (default **240**).

```bash
bash scripts/wave.sh watchdog check          # exit 20 when stale/timeout
bash scripts/wave.sh state heartbeat         # refresh driverHeartbeatAt during long agent work
```

`deliver-loop` `compute-next` calls the watchdog internally: an in-flight phase past timeout without
terminal `status.json` routes to `halt-blocked` (`cause: phase-timeout:<id>`), marks the phase `blocked`, and
writes the consolidated blocker report.

Driver heartbeat staleness (`driver-heartbeat-stale`) uses `SW_DRIVER_STALE_SECONDS` (default 4h) — refresh
with `state heartbeat` during long in-turn agent work.

## Parallel wave dispatch protocol (R14–R20)

### 1. Plan-time contention (R20, R39)

`bash scripts/wave.sh plan` injects `contention.injectedEdges` from phase `**File:**` paths:

- Shared migration dirs (`db/migrate/`, `supabase/migrations/`, `prisma/migrations/`)
- `CHANGELOG.md`, `version.txt`, `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`
- `doc-numbering` (any `docs/prds/*` or `docs/decisions/*` path except INDEX)

Contended phases are forced into different waves before dispatch. Cycles fail closed (`halt: contention-cycle`).

### 2. Schedule consumption (R14, R15)

```bash
bash scripts/wave.sh schedule --plan .cursor/sw-deliver-plan.json
# optional: --ceiling N overrides worktree.parallelCeiling
```

Read `schedule[].batches[]`:

| Field | Meaning |
| --- | --- |
| `parallel` | Phase ids dispatchable together in one batch |
| `slotCount` | Worktree slots consumed (≤ `parallelCeiling`) |
| `remainderQueued` | `true` when more batches follow in the same wave |

Greedy batches never unwind a running phase to admit a queued one (R15).

### 3. Conductor-level Task dispatch (R16, R22)

For the current wave batch, the conductor (not phase sub-agents):

1. When the driver emits `dispatch-batch`, spawn **N background** `Task` sub-agents in one turn — up to
   `parallelCeiling` concurrent phase worktrees (`run_in_background: true`).
2. Each Task runs full `/sw-ship --phase-mode` in its isolated worktree.
3. Wait per **Parallel-wave completion wait** (R44).
4. Collect outcomes only from `.cursor/sw-deliver-runs/<slug>/status.json` (R19) — never ephemeral logs.
5. A background Task that crashes or never writes terminal `status.json` becomes `blocked` via the driver
   (`background-task-timeout:<id>`) — never left stuck `in-flight` (R27).
6. **Conductor only** calls `merge enqueue` / `merge run-next` / `lock acquire` — phase sub-agents never
   merge or acquire locks (R41). Workflow pushes use `scripts/git-push.sh` only (R23).

### 4. Intra-phase dispatch (R17, R18, R45)

| Phase runs as | Intra-phase sub-agents |
| --- | --- |
| Background parallel Task | **Inline** two-stage review only (R45) |
| Conductor inline | `sw-subagent-dispatch` heuristics when ≥8 files / parallel tasks |

Intra-phase dispatch never consumes `parallelCeiling` slots (R18).

### 5. Outcomes + blast radius (R19, R24)

```bash
bash scripts/wave.sh status collect --phase-slug <slug>
```

- `merge-ready-green` → conductor enqueues merge (serialized queue).
- `blocked` → `blast-radius apply` marks **transitive dependents** only; green siblings continue.

```bash
bash scripts/wave.sh blast-radius dependents --phase-slug <slug>   # inspect
```

## Safety invariants under concurrency (R21–R24)

| Invariant | Enforcement |
| --- | --- |
| Single-flight merge (R21) | `mergeQueue` + `mergeJournal`; one `merge run-next` at a time |
| Atomic lock (R41) | `wave.sh lock acquire` uses `O_EXCL` on `.cursor/sw-deliver.lock` |
| No `main` merge (R22) | `merge run-next` target is always `<type>/<slug>` from plan |
| Push chokepoint (R23) | `scripts/git-push.sh` only — secret-scan pre-push |
| Blast radius (R24) | `status collect` → `blast-radius apply`; siblings unaffected |

Phase sub-agents **must not** call `merge run-next`, `merge enqueue`, `lock acquire`, or raw `git push`.
All workflow pushes route through `scripts/git-push.sh` (secret-scan pre-push preserved).

### Eager phase-worktree teardown (R17)

After `merge run-next` + incremental verify, the driver transitions the phase
`green-merged → teardown-pending → teardown-complete` via `phase-teardown-run` once dependents forward-merge
and retained branch/status refs are safe. `phaseWorktrees[<id>]` clears on `teardown-complete`; the
orchestrator worktree persists until terminal completion. Teardown uses `git worktree remove` + `prune` only.

## Config knobs

Read from `.cursor/workflow.config.json`:

| Key | Default | Effect |
| --- | --- | --- |
| `deliver.autonomy.mode` | `autonomous` | `supervised` adds acknowledgement halts; `autonomous` uses minimal halt set |
| `deliver.autonomy.maxRunMinutes` | `1440` | Run-level wall-clock ceiling → clean halt (R42) |
| `deliver.autonomy.maxIterations` | `500` | Run-level driver-loop iteration ceiling (R42) |
| `deliver.phaseAckCadence` | `0` | Pause every K phase merges (checkpoint) |
| `deliver.remediation.maxAttempts` | `2` | Per-phase stabilize budget |
| `worktree.parallelCeiling` | `4` | Max concurrent phase worktrees |

## Orchestrator adoption

| Orchestrator | Status |
| --- | --- |
| `/sw-deliver` | Pilot consumer (R34) — `deliver-loop` / `run` |
| `/sw-ship` | Adopted (PRD 017 Phase 3) — SHIP-A1..A4 |
| `/sw-debug` | Adopted (PRD 017 Phase 3) — DBG-A1..A2 |
| `/sw-doc` | Adopted (PRD 017 Phase 3) — DOC-A1..A2 |
| `/sw-feedback` | Adopted (PRD 017 Phase 3) — FB-A1..A2 |

Reference this skill from orchestrator commands; do not duplicate loop prose.
