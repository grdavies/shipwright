---
description: Plan and run dependency-ordered deliver waves in phase-mode or multi-feature mode. Does not bypass /sw-ship, auto-merge to main, or re-author frozen task lists.
alwaysApply: false
---

# `/sw-deliver`

Orchestrator above `/sw-ship` for frozen task lists and multi-item rounds. Auto-detects **phase-mode** (task-list
path) vs **multi-feature mode** (explicit item set / plan). Sequences independent leaves in parallel, stacks
dependents on green unmerged branches, and halts at the human merge gate.

## Operator surface: list, resume, finalize (PRD 081 R21/R24)

Run-scoped deliver state exposes operator primitives via `scripts/wave_deliver.py` (also
`python3 scripts/wave.py deliver …` where wired):

| Command | Entry | Purpose |
| --- | --- | --- |
| **List** | `python3 scripts/wave_deliver.py <repo> list` | Enumerate runs: `runId`, target branch, unit, stage, lock state, terminal status; legacy runs flagged `requiresAdoption` |
| **Resume locate** | `python3 scripts/wave_deliver.py <repo> resume-locate [--run-id <id>]` | Cardinality guard before `/sw-deliver run` |
| **Run** | `/sw-deliver run [--run-id <id>] [--task-list <path>]` | Resume or start; no-arg resume only when exactly one nonterminal run exists |
| **Finalize** | `python3 scripts/wave_deliver.py <repo> finalize --run-id <id>` | Post-merge lifecycle closure (R24) |

### Resume cardinality (R21)

| Nonterminal runs | No `--run-id` | With `--run-id` |
| --- | --- | --- |
| 0 | `resume:none` halt + enumeration | `resume:run-not-found` |
| 1 | Auto-select sole run | Must match located run |
| 2+ | `resume:ambiguous` halt + full enumeration | Resolves explicit id |

Legacy global-plan runs surface as `requiresAdoption: true` — adopt via `scripts/wave_run_adopt.py`
before resume (single legacy plan read, hash-verified, copied run-scoped).

### Target-lock ordering

Persistent mutations (state writes, merge enqueue, finalize) require the **target lock** for
`target.branch` to be held by the active run (`wave_target_lock.py`). Lock acquire precedes run
directory creation; finalize releases lock + run-local lease after verified terminal merge.

### Drain-budget continuation (R22)

When `deliver.loop.drainMechanical: true` (default), the conductor drains mechanical `deliver-loop`
steps in-process until `awaitAgent`, `awaitInFlight`, or a **legitimate** halt. Step-budget exhaustion
(`conductor:drain-step-budget-exceeded`) is **not** a legitimate halt — re-invoke `deliver-loop` in the
same turn (see `skills/conductor/SKILL.md`).

### Run finalization vs other closures (R24)

| Action | When | What it does | What it is **not** |
| --- | --- | --- | --- |
| **`finalize`** | After verified terminal merge to integration/default | Verifies merge via host broker; writes terminal receipt; releases locks, leases, worktrees; marks run `immutable` | Completion cleanup, gap absorption, planning-unit closure |
| **`finalize-completion`** | All phases `green-merged` (pre-terminal-gate) | Living-docs projection, optional auto-cleanup dry-run | Run finalization — run remains resumable until merge + finalize |
| **Gap-check / gap absorption** | Per-phase ship chain | Captures follow-up gaps; does not close the deliver run | Run or unit lifecycle closure |
| **Planning-unit closure** | Issue-store / graph reconciler | Unit status → `complete` in planning graph | Deliver run immutability (separate concern) |

Unverifiable terminal merge leaves the run **nonterminal** — finalize returns `finalize:merge-unverified`
and does not release resources.

**Merge-drain durability:** after each successful phase merge, `batchIntegrationHead` is re-frozen from the
post-merge state load so parallel batch members do not false-halt on `batch-integration-head-moved`. Host
HTTP verbs pass the broker `credentialObject` into urllib even when `tokenEnv` is empty, so authenticated
checks do not collapse into public-API rate-limit 403s.

## Subcommands

| Subcommand | Scope |
|------------|-------|
| `plan` | Emit a dependency-ordered wave plan artifact from work items + edges |
| `plan validate` | Fail-closed two-tier gate for agent-proposed phase/wave plans (mechanical; PRD 022) |
| `deliver-loop` | Durable state-machine driver: plan → provision → dispatch → merge → terminal; resumes from state (R1–R5) |
| `run` | Alias for `deliver-loop` on a frozen task list (phase-mode) |
| `promote` | Human-gated dependency-ordered promotion with per-candidate pre-merge validation |
| `explain-plan` / `--explain-plan` | Read-only WorkflowGraph plan summary (PRD 269 R10/R12/R17) — see **Graph execution runtime** |

## Graph execution runtime (PRD 269 R17)

Phase-mode and multi-feature deliver compile onto the shared **WorkflowGraph** IR and dispatch through
`GraphScheduler` (`scripts/graph/`). Operator UX stays on existing `/sw-deliver` / `/sw-status` surfaces —
**no** `/sw-graph-*` (or other graph-prefixed) slash commands are introduced.

### Conductor vs GraphScheduler (PRD 271 R15)

The orchestrator **conductor** (`skills/conductor/SKILL.md`) drives wave/phase **fan-out**, merge queues,
and in-turn `deliver-loop` / `doc-loop` self-continuation. It is **not** the `GraphScheduler` **owning loop**
(`scripts/graph/scheduler.py`).

| Layer | Role | Durable state |
| --- | --- | --- |
| Conductor | Parallel phase dispatch, intra-phase execute fan-out, merge queue, legitimate halts | `.cursor/sw-deliver-runs/`, `.cursor/sw-deliver-state.*` |
| `GraphScheduler` | Single owning loop for node admission, pool leases, cancel fencing, cache consult | Receipt journal `.cursor/sw-graph-runs/<runId>/`; cache `.cursor/sw-graph-cache/` |

Node execution delegates through `ExecutionBackend` (`scripts/graph/execution_backend.py`); the host
adjudicates terminal envelopes. Operator UX stays on existing `sw-*` commands — **no** `/sw-graph-*` family.

### `--explain-plan` (read-only)

```bash
python3 scripts/wave_deliver.py <root> --explain-plan [--task-list <path>|--plan <path>|--graph-json <path>] [--compact] [--text]
# equivalents:
python3 scripts/wave_deliver.py <root> explain-plan …
python3 scripts/wave_deliver.py <root> plan --explain-plan …
python3 scripts/wave_deliver.py <root> run --explain-plan …   # prefers explain over mutation
```

Emits node count, parallel branches, `maxConcurrency`, estimated model mix, human gates, and an
estimated/measured/omitted critical path. Refuses `--write` / `--persist`. Default JSON; `--text` for
plain text; `--compact` embeds/shortens the text summary.

### Generic `runId`

Every compiled graph carries a generic graph `runId` in `metadata.runId`, mapped from the deliver
`runId` (or orchestrator id / safety lock owner when that is the durable key). Receipts, in-flight
intents, and status/explain queries index by that same `runId` — not a second graph-specific identity.

### Cutover stages

Graph ownership advances through dogfood-gated stages in `scripts/graph/cutover.py`:

| Stage | Value | Gate highlight |
| --- | --- | --- |
| Dogfood | `dogfood` | Internal-only runs; parity + coverage evidence |
| Limited scope | `limited-scope` | Requires live status/explain before promotion |
| Full ownership | `full-ownership` | Named authorizer + recorded promotion evidence |

Cutover never drops the human merge gate or invents a parallel operator command surface.

### Serial-equivalent `maxConcurrency: 1`

`resourceLimits.maxConcurrency: 1` is the tested serial-equivalent mitigation lane (and the default when
a transient explain-plan is built from a task list). Cache remains independently disableable. Raising
concurrency is a scheduling-mode / cutover concern — not a new slash command.

Live progress and per-node explain live on `/sw-status` (see that command), not on new graph commands.

## Workflow optimizer: shadow comparison and digest confirmation (PRD 270 R2/R8)

When `orchestration.planPolicy: proposed` is active (pilot opt-in — see **Pilot opt-in** below),
`/sw-deliver` scores candidate WorkflowGraph layouts in **shadow mode** before any mutating dispatch.
Shadow is read-only: no credential broker, no outbound adapters, and no write-scoped worktree
(`scripts/graph/isolation_policy.py`). Operator UX stays on `/sw-deliver` and `/sw-status` — no
`/sw-graph-*` commands.

### Shadow comparison output

Shadow evaluation (`scripts/graph/dynamic_proposal.py` — `evaluate_shadow_proposal`,
`run_shadow_evaluation`) compares candidate versus canonical and serializes a `ShadowEvaluationResult`:

| Field | Content |
| --- | --- |
| `comparison.candidate` / `comparison.canonical` | Kernel-derived metrics: `predictedLatencyMs`, `predictedCost`, `parallelism`, `nodeCount`, `resourceDemandSlots`, `verificationCoverage` (aggregate + `byVerifierClass`) |
| `comparison.deltas` | Signed deltas between candidate and canonical for each metric |
| `records[]` | Per-node shadow dispatch: `mode` (`executed` \| `estimated` \| `refused`), `reason`, predicted vs realized telemetry when executed, `refusedWriteLease` / `refusedCredentials` for mutating kinds |

Proposal-supplied metric fields (including any `shadowScore` payload on the proposal document) are
**ignored** — scoring uses kernel metrics only. Mutating node kinds are estimated from receipts rather
than executed; read-only allowlist kinds may execute under `READ_ONLY` / `NONE` isolation. Predicted
versus realized deltas persist on each record when shadow executes a node.

Shadow outcomes are receipt-backed evidence for promotion gates — not automatic dispatch authority.
Live progress and per-node explain for the active `runId` remain on `/sw-status` (`graph-progress`,
`explain <nodeId>`).

### Digest-bound confirmation

Promotion from `proposed` to `canonical` (`scripts/graph/workflow_library.py`
`gate_plan_policy_promotion`) requires **digest-bound human confirmation** on an existing operator
command:

| Field | Requirement |
| --- | --- |
| `confirmation.command` | Must be `sw-deliver` (sole entry in `DIGEST_CONFIRMATION_COMMANDS`) |
| `confirmation.digest` | Must match the expanded template digest byte-for-byte |
| `confirmation.confirmedBy` | Non-empty actor identity |
| `confirmation.confirmedAt` | Timestamp of the binding confirmation |

The gate is fail-closed and also requires: sample floor (≥3 runs with graph `runId` telemetry), both
`dogfood-deliver` and `non-dogfood-deliver` input strata, bounded prediction error (default max
**0.25**), zero required-capability regressions, ready-without-rework on each sample, a named
allowlisted authorizer, and integrity-scoped receipts/calibration digests. Any template or fragment
change alters the digest — operator must re-confirm on `/sw-deliver` with the current digest before
promotion proceeds.

Configuration and demotion/kill-switch detail:
`docs/guides/configuration.md` (Workflow optimizer and capability registry). Domain terms:
`docs/guides/graph-domain-terminology.md` (**shadow score**, **fragment pin**).

## Scope

- Input: frozen task list path, explicit item set, or deliver-plan artifact.
- Output: deliver plan JSON; green leaf branches; `integration/<stamp>` test surface (multi-feature mode).
- Does **not** bypass `/sw-ship`, auto-merge to `main`, or unwind green siblings on single-leaf red integration.

## Procedure (`plan`)

1. Load `skills/deliver/SKILL.md` and `skills/conductor/SKILL.md` (conductor contract — R1/R3).
2. Auto-detect mode: frozen `--task-list` → **phase-mode**; `--items`/`--edges` → **multi-feature**; both → disambiguation halt.
3. Phase-mode: validate `frozen: true`, resolve `<type>/<slug>`, parse `## Phase Dependencies` (required at
   `/sw-tasks` freeze). Legacy lists omitting the table use the PRD 013 fallback ladder at plan time:
   declared edges → `**File:**` file-set inference → sequential+notice (see **Phase dependency fallback**).
4. Run `scripts/wave.py preflight` to echo mode, target branch, and waves (includes CI/review
   base-branch preflight, R49); then `scripts/wave.py plan`.
5. Supports `--type`, `--dry-run` (no mutations), and `--from <phase>` (resume guard).
6. Detect cycles; refuse invalid plans.
7. Serialize shared-migration overlaps and INDEX/numbering contention per `skills/parallelism/`.

## Plan validation primitive (`plan validate`)

Mechanical gate for agent-proposed plans (PRD 022). Invoked by the conductor and phase executor — not
hand-authored in prose:

```bash
# Phase tier — step list for a phase type (ship/deliver):
python3 scripts/wave.py plan validate --tier phase --phase-type ship \
  --proposal /path/to/proposal.json [--signal-context /path/to/signal_context.json]

# Wave tier — batching within contention + parallelCeiling:
python3 scripts/wave.py plan validate --tier wave --proposal /path/to/wave-proposal.json \
  --plan .cursor/sw-deliver-plan.json
```

Returns stable JSON `{verdict: pass|reject|ambiguous, reasons[]}`. Reject → canonical chain (phase) or
canonical waves / `wave.py schedule` (wave). With default `orchestration.planPolicy: canonical`, behavior is
byte-identical to today; live `proposed` on `/sw-deliver` requires pilot opt-in (below).

**Proposed-path wiring (PRD 023):** when `orchestration.planPolicy: proposed` and the TR0 dependency gate
passes (`scripts/pilot_dependency_gate.py` / `scripts/test/pilot_022_prerequisite_check.py`), state init seeds
`twoTierLifecycle` + `planRejectionLog`; wave entry runs `plan validate --tier wave --record-rejection` then
persists `waveBatchingPlan` and sets `wave-validated`; phase entry runs `plan validate --tier phase` before
persisting `phase-step-plan.json`, falling back to the canonical chain on reject.

### Pilot opt-in (PRD 023 rollout)

Default `canonical` is unchanged for all repos. Enabling `proposed` on `/sw-deliver` requires:

1. **TR0 gate green** — PRD-022 execution-fidelity + resume fixtures pass (`pilot-dependency-gate`).
2. **Config** — `orchestration.planPolicy: proposed` (never silently seeded; `/sw-init` writes `canonical`).
3. **Staged blast radius** — hermetic/fixture repos first; real repos need explicit per-run pilot
   acknowledgement and an integration/non-`main` target branch.
4. **Production guard** — `/sw-init` doctor surfaces `planPolicy` vs default and refuses `proposed` toward
   shared `main` without acknowledgement.

Benefit metric soak and default-flip decisions use `python3 scripts/wave.py plan benefit-report --pairs <path>`
(`scripts/wave_plan_benefit.py`); insufficient evidence fails closed to `canonical` (R31).


## Planning-store entry and status (PRD 059 R1–R4)

Phase-mode `run` / `plan` accept **one** of:

```bash
/sw-deliver run <frozen-task-list-path>
/sw-deliver run --unit-id <planning-unit-id>
/sw-deliver run --issue <issue-number>    # issue-store only
```

`--unit-id` / `--issue` materialize through `planning_materialize` to the same local path `--task-list`
would produce. Passing both `--task-list` and `--unit-id`/`--issue` fails closed.

**Issue-store materialize (PRD 062 R1/R2):** under `issue-store`, `planning_materialize.cmd_provision` calls
`ensure_run_entry_materialized` **before** `discover_private_spec_units` — frozen task lists are written to
`.cursor/planning-materialized/docs/prds/<n>-prd-<slug>/` before any discover pass. `--issue <n>` resolves via
`logical_task_list_candidates` with strict leading `tasks-`+NNN normalization (`planning_deliver_gate.py`); interior
`tasks-` in slugs and already-normalized ids are stable; ambiguous candidates fail closed.

Unified unit status (no `docs/prds/INDEX.md` read):

```bash
python3 scripts/planning-graph.py status --unit-id <unit-id>
# `/sw-status` delegates to the same surface for planning-unit queries (R2).
```

Consolidated blocker/terminal reports prefer the `--unit-id` / `--issue` reference form under issue-store
when surfacing `resumeCommand` (R4).


## Procedure (`deliver-loop` / `run`)

Phase-mode runs MUST enter through the durable driver — never a manual worktree handoff while progress is
possible (R4). The **conductor** (`skills/conductor/SKILL.md`) drives the in-turn loop: default
`deliver.autonomy.mode: autonomous` delivers a frozen task list end-to-end to the terminal-PR gate with
zero re-prompts (R13); `supervised` adds acknowledgement halts per `deliver.phaseAckCadence` and
`doc.afterTasks`.

```bash
/sw-deliver run <frozen-task-list-path>
# resume when durable state already holds source_task_list:
/sw-deliver run
# internal driver (conductor in-turn only — not operator-facing resume):
python3 scripts/wave.py deliver-loop --dry-run
```

0. **Entry guard (R16):** `python3 scripts/wave.py assert-entry` when not resuming from durable state.
1. Load `skills/conductor/SKILL.md`; enforce `rules/sw-conductor.mdc`.
2. Driver loads plan from state or runs `plan`; auto-detects in-progress runs on entry (R3).
3. **Orchestrator worktree (R53):** `orchestrator provision` on `<type>/<slug>`.
4. Per wave: `phase provision` → `phase dispatch-env` → full `/sw-ship --phase-mode` in phase worktree
   (agent step; orchestrator never bypasses `/sw-ship`).
5. `status collect` from durable path; advance only from `status.json` (R7).
### Phase acceptance + gap-check gates (PRD 055 R11–R13, R25)

Before `merge-enqueue`, the deliver kernel enforces **in order**:

1. **Phase acceptance** (`scripts/phase_acceptance_gate.py`) — all executable sub-task refs for the active
   phase slug are `done` in `taskLedger` **and** checkboxes toggled in the frozen task file. `declared-partial`
   requires a durable `taskLedger.phases[slug].declaredPartial` record plus explicit `skippedRefs`; silent
   all-open fails closed.
2. **Tasks currency** (`wave_state.py ledger check`) — checkbox↔ledger alignment; with `--merge-ready` +
   `--phase-id`, fails the all-unchecked completed-work case (R12).
3. **Gap-check gate** (`scripts/gap-check-gate.py`) — durable `.cursor/sw-deliver-runs/{slug}/gap-check.status.json`
   with binding `pass|halt`. `ship-phase-status.py` refuses `merge-ready-green` when verdict is `halt`.

**`--fast` gap-check skip is prohibited** on the deliver merge path (`--deliver-merge`). Ship-only fast path
unchanged. On execute ref terminal `green`, `execute_task_status.py` auto-records ledger + checkbox when
`SW_TASK_LIST` and `SW_PHASE_SLUG` are set (R14).


6. **Whole-batch merge (R10):** no phase in a parallel batch merges until every in-flight batch member
   publishes a validated terminal `status.json` (`merge-ready-green` or `blocked`). Multiple greens enqueue via
   `collect-all-ready` in phase-id order; integration HEAD is frozen at `batchIntegrationHead` until the batch
   queue drains — halt if integration moves mid-batch.
7. On `merge-ready-green`: `merge enqueue` → `merge run-next` when gate + review barrier settle.
8. **Deterministic conflict auto-resolve (R12):** `merge-queue:conflict` on golden-manifest / `dist/**` /
   generated mirrors only may auto-regen (`copy-to-core` + `python3 -m sw generate --all`) within
   `deliver.deterministicConflict.maxAttempts` (default 1); semantic or multi-preimage conflicts halt.
9. On blocker: bounded remediation (`deliver.remediation.maxAttempts`, default **2**), blast-radius for
   siblings, consolidated blocker report on halt (R8–R12).
10. When all phases `green-merged`: `resume reconcile`, terminal PR, compounding (later phases).
11. Halt at human merge gate — never in-flux.

When the driver returns `awaitAgent: true`, the conductor performs the agent work and immediately
re-invokes `python3 scripts/wave.py deliver-loop` within the same turn until a legitimate halt (R6/R7 — see
`skills/conductor/SKILL.md` **In-turn self-continuation loop**). A fresh agent resumes from
`.cursor/sw-deliver-state.json` + plan + run log alone (R4).


## Orchestrator worktree auto-adopt (R2)

When durable deliver state records an orchestrator worktree and `/sw-deliver run` resumes, the driver
reuses the recorded path instead of inventing a new one:

| Precondition | Requirement |
| --- | --- |
| Path | Exists under managed `.sw-worktrees/` roots (absolute path in state) |
| Identity | Recorded `branch` matches deliver `target.branch`; slug/name matches the active run |
| Worktree | Valid git worktree with `.git` metadata — not a bare directory |
| Checkout | Orchestrator worktree is on `target.branch` (not detached on the wrong ref) |
| Tree | Clean `git status --porcelain` — dirty trees halt with `dirty-orchestrator` |

**Adopt path:** `scripts/wave.py orchestrator provision` calls `adopt_orchestrator_worktree` when
`.sw-worktrees/<slug>-orchestrator` already exists and passes the checks above (`wave_lifecycle.py`).
Basename-only paths or mismatched slug/branch fail closed with typed halts — never silent invent.

**Resume:** after any legitimate halt, re-run `/sw-deliver run` (or `/sw-deliver run --unit-id <id>` under
issue-store). Consumable durable state with matching `source_task_list` skips nested full preflight on
resume; wrong slug, truncated JSON, terminal verdict, or foreign task-list re-enters preflight or hard-halts.
See `docs/guides/commands.md` for the operator summary.


## Conductor in-turn loop (`run` / `deliver-loop`)

After every `deliver-loop` JSON response:

| Response | Conductor action (same turn) |
| --- | --- |
| `awaitAgent: false` | Re-invoke `python3 scripts/wave.py deliver-loop` immediately |
| `awaitAgent: true` | Run agent step for `next.action` (table in conductor skill), then re-invoke `deliver-loop` |
| `awaitInFlight: true` | Poll phase `status.json` paths (parallel-wave completion wait), then re-invoke `deliver-loop` |
| `halt: true` | Emit consolidated report; stop — legitimate halt only |
| `terminal: true` | Terminal gate; arm self-wake for CI if needed (conductor skill **Self-wake sentinel**) |

**Never** end the turn with only "continue deliver" or "re-run deliver-loop" as the user-facing outcome while
`verdict: running` and no legitimate halt applies (R13).

Hard stops: `deliver.autonomy.maxIterations` (default 500) and no-progress circuit breaker (3× identical
`nextAction` + state signature) — see `rules/sw-subagent-dispatch.mdc` and conductor skill (R38).

**Halts (R10–R12):** only legitimate conditions; emit `python3 scripts/wave.py report blockers` (mid-run) or
`report terminal` (all phases merged) with `resumeCommand` (`/sw-deliver run …`) — never "continue deliver?".

**Re-adopt gate (R6):** `/sw-deliver run` refuses a second driver while `driverHeartbeatAt` is fresh (unless the same-run self-wake carve-out). Stale heartbeat or explicit resume from halt is required.

**Liveness (R37):** `python3 scripts/wave.py state heartbeat` during long agent steps;
`python3 scripts/wave.py watchdog check` probes phase timeout / stale driver heartbeat.

`run` is an alias for `deliver-loop --task-list <path>`.


## Testing / Rollout (PRD 063 R17)

Before gap closure or terminal deliver on PRD 063 workstreams, verify operator-facing surfaces:

| Surface | Requirement |
| --- | --- |
| `core/commands/sw-deliver.md` | Re-adopt gate (R6), inline vs batch dispatch (R9), living-docs deferral (R12) |
| `core/skills/conductor/SKILL.md` | Phase-unique self-wake (`DELIVER_WAKE_*`), hang/desync halts (R5) |
| `core/rules/sw-conductor.mdc` | Legitimate halts override silent window (R12) |
| `docs/guides/workflows.md` | `shipChain` consumability, pre-PR smoke, finalize closure |
| `.sw/layout.md` | Harness roots manifest, dispatch lease, `shipChain` on status |

Run `python3 scripts/wave.py docs-currency` and
`python3 scripts/unit_tests/deliver/test_prd063_release_completeness.py` before closing absorbed gaps.
Harness pollution: `python3 scripts/harness_isolation_lint.py --check` (includes planning-store
`override-add` isolation per `core/sw-reference/harness-roots-manifest.json`).


## Issue-store scheduler (PRD 046 R25)

When issue-store is active and cutover permits issue-derived discovery,
`/sw-deliver next` resolves the next schedulable unit via:

```bash
python3 scripts/planning_scheduler.py <repo-root> next (`schedule-next` action) [--force-refresh]
```

Issue labels (`sw:tier:*`, `sw:priority:*`) drive ordering; frozen/closed units are never
scheduled from stale cache entries. Refuses when derived INDEX is `index-incomplete`.

## Autonomy and parallelism (user surface — R36)

| Knob / concept | Default | User-visible behavior |
| --- | --- | --- |
| `deliver.autonomy.mode` | `autonomous` | Runs to terminal gate without per-phase re-prompts; `supervised` adds acknowledgement halts |
| `deliver.autonomy.maxRunMinutes` | unset | Run-level wall-clock ceiling → consolidated halt |
| `deliver.autonomy.maxIterations` | 500 | In-turn loop hard stop |
| `deliver.loop.drainMechanical` | `true` | Drain mechanical `deliver-loop` steps in-process until `awaitAgent`, `awaitInFlight`, or halt; `false` restores one step per invocation (PRD 062 R7) |
| `worktree.parallelCeiling` | 4 | Max concurrent phase worktrees per wave batch |
| Conductor contract | `skills/conductor/SKILL.md` | Single source for loop, halts, parallel dispatch — referenced, not duplicated |

**Parallel waves:** when the plan places multiple phases in one wave, the conductor dispatches each as a
background sub-agent (peak concurrency ≥2 on parallelizable task lists). **Legitimate halts only:** terminal
`main` merge, exhausted remediation, destructive/ambiguous git, configured checkpoints, phase timeout,
external-wait exhaustion, run-level budget — see conductor skill **Legitimate-halt set**.

## Red integration routing

- **Single leaf reproduces failure** → that leaf re-enters `/sw-stabilize`; siblings untouched.
- **Emergent cross-leaf failure** → delta-debug minimal failing subset + escalate to human gate; max re-route forces escalation.

**Communication intensity:** inherit

**Model tier:** inherit — resolve delegated atomics via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command <child-slug>`; do not dispatch on bare `--command sw-deliver`.

## Delegated Task binding contract

Before each phase/terminal delegated Task from `/sw-deliver`:

1. `python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-deliver --skill conductor`
2. `python3 scripts/dispatch-check.py --agent <agent-id> --command sw-deliver --skill conductor --parent-model <parent-concrete-id> [--dispatch-id <id>]`
3. Dispatch Task with explicit concrete `model:` and resolved caveman intensity context; never rely on inherited model.

Resolve model: `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command <child-slug>` (or `--skill conductor`).
Resolve intensity: `python3 scripts/resolve-intensity.py --command sw-deliver --skill conductor`.

## Inline allowlist (closed)

`/sw-deliver` may remain inline only for:

- Durable driver invocations (`wave.py deliver-loop/state/merge/status/report`).
- Lock/journal bookkeeping and deterministic state transitions.
- Legitimate-halt report emission and resume-command surfacing.

Wave implementation/review remediation work delegates.

## Dispatch context redaction contract

All non-config context passed to delegated Tasks (status excerpts, blocker reports, blast-radius notes,
memory-preflight outputs, diffs) must be redacted via `python3 scripts/sw_bootstrap.py memory-redact.py` and fenced as
`untrusted_payload` before inclusion.


## Planning scheduler and dependency gate (PRD 033)
### Unit-id derivation (gap-051 / PRD 058 R1–R2)

Frozen task lists participate in **two distinct unit-id derivations** — do not conflate them:

| Function | Module | Input | Derived id | Consumer |
| --- | --- | --- | --- | --- |
| `unit_id_from_task_list` | `scripts/planning_deliver_gate.py` | Task-list **parent directory** under `docs/prds/<n>-<slug>/` | `<n>-prd-<slug>` (legacy `prd-<slug>` dirs unchanged) | Planning-graph dependency gate / scheduler |
| `unit_id_from_task_list_rel` | `scripts/planning_materialize.py` | Task-list **filename stem** | `tasks-<n>-<slug>` | Issue-store materialize / run-entry pin |

Example path `docs/prds/058-dispatch-loop-hardening/tasks-058-dispatch-loop-hardening.md`:
- graph unit id → `058-prd-dispatch-loop-hardening`
- materialize/store unit id → `tasks-058-dispatch-loop-hardening`

`dependency_gate` / `run_start_revalidate` fail closed when the derived graph unit is missing and the path is
outside the canonical `docs/prds/<n>-<slug>/` layout; pre-freeze canonical task lists are allowlisted (R5).


Unit-level graph primitives (in addition to phase-mode waves):

| Entry | Command |
| --- | --- |
| Next eligible unit | `python3 scripts/wave_deliver.py <repo> next` |
| Dependency gate | `python3 scripts/wave_deliver.py <repo> dependency-gate preflight --task-list <path>` |
| Run-start revalidation | `python3 scripts/planning_deliver_gate.py <repo> dependency-gate run-start --task-list <path>` |
| Override (logged) | add `--override --override-reason "<why>"` to dependency-gate |

**CI-status capability probe (PRD 079 R12):** deliver entry (`next`, `dependency-gate preflight`, `dependency-gate run-start`) invokes `planning_deliver_gate.enforce_ci_status_capability_deliver` once per run via `host_doctor_lib.probe_ci_status_capability`. **Fail-closed halt** when `ciStatus.capability` is `denied` (exit 30, `halt=ci-status-denied`); `inconclusive` does not authorize merge. `/sw-init` runs the same probe via `host-doctor.py` with warn-only posture.

**Soft-enforce:** when `planning.autonomy` is `maintenance-only` (default) and an explicit `--task-list` targets a lower-priority eligible unit than `next` would pick, preflight returns a confirm prompt — pass `--confirmed` after operator ack.

**Run-start:** both `next` and explicit `--task-list` re-validate eligibility and depends at run-start (refuses `superseded`/`cancelled` races).



## Ship-loop dispatch (PRD 065)

Phase-mode deliver drives `/sw-ship` through the durable ship-loop driver — not ad-hoc command chains:

| Action | Scope | Task spawn |
| --- | --- | --- |
| `dispatch-ship` | One phase worktree | **In-turn** — conductor runs agent steps on `awaitAgent`; driver never spawns Tasks |
| `dispatch-batch` | Parallel wave batch | **Background** — one phase-scoped executor per worktree |

Mechanical classification (`wave_deliver_loop.py` `MECHANICAL_ACTIONS`) lets `deliver-loop` drain
`dispatch-ship` without a chat turn; deferred non-gate steps surface `awaitAgent` for the conductor ship chain.

**Lease + watchdog** — `ship-lease acquire` before inline dispatch; liveness keyed on `heartbeatAt` within
`SW_SHIP_LEASE_STALE_SECONDS` (`wave_lock.py`). Stale heartbeats reclaim via `canonical-reemit`; exhaustion
→ phase `blocked`.

**Terminal acceptance (R14/R24/R30)** — at all-phases-complete, `wave_merge.py report terminal` embeds a
validated record from `wave_acceptance.py`:

- Path: `.cursor/sw-deliver-runs/terminal-acceptance.json`
- Captures per-phase `mergeState`, terminal PR + live `check-gate` evidence, mandatory-gate rollup, and
  legitimate-halt `interactionCount`
- **Halt-resume (R25)** — every legitimate driver halt emits a `haltResume` block (`resumeCommand`,
  `haltCause`, `autonomyDirective`, `runId`, optional `phaseSlug`) via `halt_resume.py`

## Sizing report visibility (`--sizing-report`)

Read-only operator visibility for PRD 040 phase sizing — **does not** feed scheduling,
next-action selection, or wave batching.

```bash
python3 scripts/wave.py sizing-report --task-list <path-to-task-list.md>
```

Emits the same JSON as `python3 scripts/phase_sizing.py score <task-list>` (phase metrics,
split suggestions, `preflight` verdicts, and `costEstimate`). Safe on draft or frozen lists;
use `phase_sizing.py check-frozen` for fail-closed freeze hygiene.

## Phase dependency fallback (PRD 013)

`/sw-tasks` requires `## Phase Dependencies` at freeze (`spec-rigor-check.py`). Phase-mode `/sw-deliver plan`
applies this ladder only when a **legacy** frozen list omits the table (`wave_deliver.deps_to_edges`):

| Step | When | Behavior |
|------|------|----------|
| 1. Declared | `## Phase Dependencies` present | Table rows are authoritative |
| 2. File-set inference | Table absent, overlapping `**File:**` | Infer serializing edges before waves |
| 3. Sequential + notice | Table absent, no file overlap | Strict `1→2→3…` edges + missing-table notice |

Explicit author edges always win. New task lists must emit the table at freeze — never rely on step 2–3.

## Merge policy (PRD 062 R17)

Phase-mode deliver enforces **correctness + terminal before perf/ops** via frozen `## Phase Dependencies`:

| Wave class | Phases | R-IDs | Merge gate |
| --- | --- | --- | --- |
| Correctness + terminal | 1–2 | R1–R5 | Must reach `green-merged` before dependent perf/ops phases ship |
| Perf + ops + docs | 3–5 | R6–R19 | May run in parallel with each other once phases 1–2 are green; still subject to file-contention edges |

Soft-priority scheduling may **provision** phases 1∥2 and 3∥4 concurrently when contention permits, but
**merge-enqueue** for perf/ops phases (3–5) remains blocked until every phase-1/2 member in the batch publishes
`merge-ready-green`. Exceptions require a durable logged override on deliver state (`mergePolicyOverride` with
`reason` + `actor`) — never silent bypass of the dependency table.

## Guardrails

- Promotion validates each candidate on a disposable PR head **before** merge to `main`.
- Post-partial-promotion regression: atomic integration PR or revert promoted leaves — never half-promoted red `main`.
- Teardown uses safe worktree/branch removal only.

## Deliver conductor completion (PRD 035 A1)

- **Build-chain ship verify (R25):** phase `/sw-ship` runs `scripts/ship-build-chain-check.py` before commit when build-chain paths change.
- **Resume (R47):** halt payloads and `report blockers` emit `/sw-deliver run <frozen-task-list>` — never bare `deliver-loop` as operator resume.
- **Deferrals (R49):** cross-feature waves, rich living-status dashboard, and contention feedback into `/sw-tasks` re-run remain explicit non-goals — no silent partial ship.
- **Cleanup autonomy (R50):** when `cleanup.autonomy: auto`, `finalize-completion` applies dry-run `wouldRemove` after deterministic merge detection.

## Deliver driver resilience (PRD 276)

Harden `/sw-deliver` against squash-delete finalize fragility, orchestrator cwd skew after restart, and
multi-agent double-drive of one `runId`. Absorbs planning gaps **#698**, **#704**, and **#705**.

### Absorb map (R17)

| Source | Shipped behavior | Primary touchpoints |
| --- | --- | --- |
| **#698** finalize / mirror | Mirror slug→run-scoped state before terminal-ship; write-ahead finalize checkpoint (`release` → `projection` → `receipt` → `immutable`); host PR merge evidence when the feature branch is deleted post-squash; partial finalize leaves typed `resumeCommand` (release before durable completion ≠ success) | `scripts/wave_state.py`, `scripts/wave_deliver_loop.py` (`finalize-checkpoint.json`) |
| **#704** orch cwd adopt | Valid recorded orch path → validated re-exec/delegate with cwd set; path-record alone insufficient; invalid/missing path fail-closed with typed cause + `resumeCommand`; adoption preserves true dual-drive desync; execution-time identity rebind (git-common-dir, worktree registration, branch HEAD, run identity) | `scripts/wave_deliver_loop.py` (`try_adopt_recorded_orchestrator_worktree`) |
| **#705** exclusive run lease | Acquire exclusive durable runId lease before mutating run state; second adopter → typed lease-held halt + `resumeCommand`; stale TTL/heartbeat reclaim bumps generation; uncertain ownership / cross-clone fail-closed | `scripts/wave_lock.py` (`.cursor/sw-deliver-run-locks/`) |

### Orch cwd auto-adopt (R5–R8, R13–R14)

When durable state records a valid orchestrator worktree, deliver entry **auto-adopts** it (sets cwd /
rebinds identity) instead of message-only halt for recoverable skew. Prefer adopt over asking the operator
to `cd` manually. Missing, invalid, dirty, or dual-drive-fresh paths remain fail-closed — see
**Orchestrator worktree auto-adopt** above for the base path checks; PRD 276 adds execution-time rebind and
desync-preserving refusal.

### Exclusive runId lease — held halt + stale reclaim (R9–R12, R20–R21)

Before mutating run-scoped state, `deliver-loop` acquires an exclusive lease keyed by `runId` under
`.cursor/sw-deliver-run-locks/` (git-common-dir anchored; see `.sw/layout.md` lease taxonomy).

| Condition | Behavior |
| --- | --- |
| Lease held by live peer | Halt with typed cause (lease-held) + `resumeCommand` — do not double-drive |
| Stale heartbeat / dead PID (same host) | Reclaim without manual lock surgery; generation bumps (fencing) |
| Uncertain ownership / cross-clone | Fail closed — no automatic takeover without explicit ack |
| Prior-generation write after reclaim | Refused (generation fencing) |

Heartbeat alone is not sufficient fencing — the durable lease file + generation is authoritative (D3).

### Primary finalize after squash / orch teardown (R1–R4, R15–R16)

Terminal finalize is safely re-runnable from the **primary** checkout after orchestrator teardown:

1. Ensure run-scoped state exists (mirror from slug-scoped when missing) before terminal-ship.
2. Write-ahead `finalize-checkpoint.json` under the run directory; resume from the last incomplete phase.
3. When the feature branch is deleted post-squash-merge, verify via **host PR merge evidence** — not a
   missing local branch tip.
4. Partial finalize after `release_run_resources` returns `finalize:partial` / `finalize:checkpoint-incomplete`
   with `resumeCommand` (`python3 scripts/wave.py finalize --run-id <runId>`) — never silent success.

## Closeout hardening (PRD 278)

Deliver and ship closeout paths gained three mechanical surfaces — phase-ship hygiene auto-repair,
prefer-run-scoped adopt, and numeric absorb exactly-one mapping. Operator UX stays on existing
`/sw-deliver` / `/sw-ship` commands; behavior is fail-closed with typed `cause` + `resumeCommand`
when auto-repair is unsafe.

### Phase-ship hygiene auto-repair (R1, D2, D4)

Under `/sw-ship --phase-mode`, `scripts/phase_ship_hygiene.py` may auto-repair three hygiene halts
**only** from authoritative run-scoped evidence for the exact phase HEAD:

| Halt | Module | Auto-repair action | Refused when |
| --- | --- | --- | --- |
| `gap-check-missing` | `gap-check-gate.py` | Writes binding `gap-check.status.json` after authoritative gap evaluation | Forged pass without `evaluationProvenance`; evaluation head ≠ phase HEAD |
| `tasks-currency-divergence` | `wave_deliver.py` / `wave_deliver_loop.py` | Re-aligns checkbox ledger from `source_task_list` without mutating frozen task-list bytes | Would invent completion for unchecked work |
| `prTestPlan-manifest-missing` | `wave_terminal.py` | Mirrors orchestrator `pr-test-plan.manifest.json` from gate-cache evidence | No safe authoritative manifest source |

Regression: `scripts/unit_tests/planning/test_phase_ship_hygiene_autorepair.py`. See also
`/sw-ship` **Phase-ship hygiene floors**.

### Prefer-run-scoped adopt (R3–R5, D6)

`scripts/wave_run_adopt.py` prefers a proven run-scoped `plan.json` + run identity even when the
legacy global plan belongs to another `runId` (`planHashMismatch`). Adoption binds
`sourceTaskListContentHash` (content-hash of `source_task_list`) and uses an advisory lock/CAS
spanning identity-check → adopt write (`.cursor/sw-deliver-adopt-locks/`). Missing or unproven
run-scoped identity fails closed on finalize/adopt with typed `halt` + `resumeCommand` — no silent
global overwrite. Regression: `scripts/unit_tests/planning/test_wave_run_adopt_prefer_run_scoped.py`.

### Numeric absorb exactly-one (R6–R8, D5)

`scripts/planning_store_facade.py` resolves bare planning-issue numeric absorb refs (hybrid
`planningIssues` / `sw-edges`) to **exactly one** eligible open gap unit id before provenance
closeout. `0` or `N>1` matches → typed `not-ready`; provider/API faults → `not-ready` (not silent
skip). Wired through `close-delivery-units` and deliver finalize paths. Regression:
`scripts/unit_tests/planning/test_numeric_absorb_closeout.py`.

### Absorb acceptance map (R9, D1, D3)

| Source issue | Requirement cluster | PRD 278 scope |
| --- | --- | --- |
| #730 | R1–R2 | Phase-ship hygiene safe auto-repair; forged gap-check refused; frozen-ledger mutation refused |
| #731 | R3–R5 | Prefer run-scoped plan under foreign global `planHashMismatch`; lock/CAS + content-hash bind |
| #739 | R6–R8 | Numeric absorb → exactly-one open gap; provider fault → not-ready |

**Decision stance (D1):** PRD 278 ships as a focused closeout-hardening PRD — not a mega-PRD bundling
unrelated deliver surfaces. **Decision stance (D3):** PRD 278 absorbs #731 dogfood closeout; do not
amend PRD 276 for the same behavior.

Normative path contract and `core-scripts-parity` for touched modules:
`core/sw-reference/layout.md` **PRD 278 closeout surfaces**.

## Phase-mode context currency (PRD 080)

Phase-mode ship steps bind a worktree-scoped context (`SW_PHASE_MODE`, `SW_PHASE_SLUG`, `SW_RUN_DIR`,
integration branch) established by `phase dispatch-env` / harness predicates in `wave_deliver_loop.py`.
Credential lookups that block or time out are legitimate conductor halts — not silent ambient-token
fallbacks. Terminal `list, resume, finalize`, **Resume cardinality**, **Drain-budget** continuation,
**Run finalization vs** merge verification, and `finalize:merge-unverified` remain as documented above.

## Terminal prepare gates (PRD 082 currency)

Before presenting the human merge gate, `scripts/wave_terminal.py` runs living-docs append +
`docs-currency-gate` and tasks-currency corroboration. Drift on command docs bound to
`wave_deliver.py` / `wave_deliver_loop.py` / `wave_terminal.py` / `wave_run_adopt.py` blocks
`terminal pr prepare` fail-closed — refresh the stale command doc (this file or `/sw-freeze`) and
re-run prepare; do not skip the gate.

## Currency (PRD 085 terminal)

Terminal prepare remains gated by `docs-currency-gate` + tasks-currency on bindings to
`wave_deliver.py` / `wave_deliver_loop.py` / `wave_terminal.py` / `wave_run_adopt.py`. Phase acceptance +
gap-check + live host evidence still precede `merge-enqueue`.
On resume after target-lock reacquisition, `deliver-loop` preserves an already-materialized phase map and
skips duplicate state initialization before continuing from the durable cursor.

**Orchestrator cwd (hang-desync):** run `deliver-loop` from `.sw-worktrees/<slug>-orchestrator` (not the
primary checkout). Repo-root cwd with an orchestrator path under `.sw-worktrees/` trips
`deliver:orchestrator-cwd-skew`. Primary↔mirror skew uses `wave_state.sync_canonical_state_read` /
`repair-mirror` before terminal steps.

**Phase-before-orch teardown (PRD 328):** `release_run_resources` tears down phase worktrees before the
orchestrator worktree; terminal closeout reuses the same order. Primary cwd stays when pruning orch;
husk/parked trees do not fail the release path.

<!-- currency: refreshed 2026-09-03T19:55:07Z for terminal prepare -->
