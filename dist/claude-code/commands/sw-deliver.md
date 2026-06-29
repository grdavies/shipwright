---
description: Plan and run dependency-ordered deliver waves in phase-mode or multi-feature mode. Does not bypass /sw-ship, auto-merge to main, or re-author frozen task lists.
alwaysApply: false
---

# `/sw-deliver`

Orchestrator above `/sw-ship` for frozen task lists and multi-item rounds. Auto-detects **phase-mode** (task-list
path) vs **multi-feature mode** (explicit item set / plan). Sequences independent leaves in parallel, stacks
dependents on green unmerged branches, and halts at the human merge gate.

## Subcommands

| Subcommand | Scope |
|------------|-------|
| `plan` | Emit a dependency-ordered wave plan artifact from work items + edges |
| `plan validate` | Fail-closed two-tier gate for agent-proposed phase/wave plans (mechanical; PRD 022) |
| `deliver-loop` | Durable state-machine driver: plan → provision → dispatch → merge → terminal; resumes from state (R1–R5) |
| `run` | Alias for `deliver-loop` on a frozen task list (phase-mode) |
| `promote` | Human-gated dependency-ordered promotion with per-candidate pre-merge validation |

## Scope

- Input: frozen task list path, explicit item set, or deliver-plan artifact.
- Output: deliver plan JSON; green leaf branches; `integration/<stamp>` test surface (multi-feature mode).
- Does **not** bypass `/sw-ship`, auto-merge to `main`, or unwind green siblings on single-leaf red integration.

## Procedure (`plan`)

1. Load `skills/deliver/SKILL.md` and `skills/conductor/SKILL.md` (conductor contract — R1/R3).
2. Auto-detect mode: frozen `--task-list` → **phase-mode**; `--items`/`--edges` → **multi-feature**; both → disambiguation halt.
3. Phase-mode: validate `frozen: true`, resolve `<type>/<slug>`, parse `## Phase Dependencies` (or R8 sequential fallback).
4. Run `scripts/wave.sh preflight` to echo mode, target branch, and waves (includes CI/review
   base-branch preflight, R49); then `scripts/wave.sh plan`.
5. Supports `--type`, `--dry-run` (no mutations), and `--from <phase>` (resume guard).
6. Detect cycles; refuse invalid plans.
7. Serialize shared-migration overlaps and INDEX/numbering contention per `skills/parallelism/`.

## Plan validation primitive (`plan validate`)

Mechanical gate for agent-proposed plans (PRD 022). Invoked by the conductor and phase executor — not
hand-authored in prose:

```bash
# Phase tier — step list for a phase type (ship/deliver):
bash scripts/wave.sh plan validate --tier phase --phase-type ship \
  --proposal /path/to/proposal.json [--signal-context /path/to/signal_context.json]

# Wave tier — batching within contention + parallelCeiling:
bash scripts/wave.sh plan validate --tier wave --proposal /path/to/wave-proposal.json \
  --plan .cursor/sw-deliver-plan.json
```

Returns stable JSON `{verdict: pass|reject|ambiguous, reasons[]}`. Reject → canonical chain (phase) or
canonical waves / `wave.sh schedule` (wave). With default `orchestration.planPolicy: canonical`, behavior is
byte-identical to today; live `proposed` on `/sw-deliver` requires pilot opt-in (below).

**Proposed-path wiring (PRD 023):** when `orchestration.planPolicy: proposed` and the TR0 dependency gate
passes (`scripts/pilot_dependency_gate.py` / `scripts/test/pilot-022-prerequisite-check.sh`), state init seeds
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

Benefit metric soak and default-flip decisions use `bash scripts/wave.sh plan benefit-report --pairs <path>`
(`scripts/wave_plan_benefit.py`); insufficient evidence fails closed to `canonical` (R31).

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
bash scripts/wave.sh deliver-loop --dry-run
```

0. **Entry guard (R16):** `bash scripts/wave.sh assert-entry` when not resuming from durable state.
1. Load `skills/conductor/SKILL.md`; enforce `rules/sw-conductor.mdc`.
2. Driver loads plan from state or runs `plan`; auto-detects in-progress runs on entry (R3).
3. **Orchestrator worktree (R53):** `orchestrator provision` on `<type>/<slug>`.
4. Per wave: `phase provision` → `phase dispatch-env` → full `/sw-ship --phase-mode` in phase worktree
   (agent step; orchestrator never bypasses `/sw-ship`).
5. `status collect` from durable path; advance only from `status.json` (R7).
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
re-invokes `bash scripts/wave.sh deliver-loop` within the same turn until a legitimate halt (R6/R7 — see
`skills/conductor/SKILL.md` **In-turn self-continuation loop**). A fresh agent resumes from
`.cursor/sw-deliver-state.json` + plan + run log alone (R4).

## Conductor in-turn loop (`run` / `deliver-loop`)

After every `deliver-loop` JSON response:

| Response | Conductor action (same turn) |
| --- | --- |
| `awaitAgent: false` | Re-invoke `bash scripts/wave.sh deliver-loop` immediately |
| `awaitAgent: true` | Run agent step for `next.action` (table in conductor skill), then re-invoke `deliver-loop` |
| `awaitInFlight: true` | Poll phase `status.json` paths (parallel-wave completion wait), then re-invoke `deliver-loop` |
| `halt: true` | Emit consolidated report; stop — legitimate halt only |
| `terminal: true` | Terminal gate; arm self-wake for CI if needed (conductor skill **Self-wake sentinel**) |

**Never** end the turn with only "continue deliver" or "re-run deliver-loop" as the user-facing outcome while
`verdict: running` and no legitimate halt applies (R13).

Hard stops: `deliver.autonomy.maxIterations` (default 500) and no-progress circuit breaker (3× identical
`nextAction` + state signature) — see `rules/sw-subagent-dispatch.mdc` and conductor skill (R38).

**Halts (R10–R12):** only legitimate conditions; emit `bash scripts/wave.sh report blockers` (mid-run) or
`report terminal` (all phases merged) with `resumeCommand` (`/sw-deliver run …`) — never "continue deliver?".

**Liveness (R37):** `bash scripts/wave.sh state heartbeat` during long agent steps;
`bash scripts/wave.sh watchdog check` probes phase timeout / stale driver heartbeat.

`run` is an alias for `deliver-loop --task-list <path>`.

## Autonomy and parallelism (user surface — R36)

| Knob / concept | Default | User-visible behavior |
| --- | --- | --- |
| `deliver.autonomy.mode` | `autonomous` | Runs to terminal gate without per-phase re-prompts; `supervised` adds acknowledgement halts |
| `deliver.autonomy.maxRunMinutes` | unset | Run-level wall-clock ceiling → consolidated halt |
| `deliver.autonomy.maxIterations` | 500 | In-turn loop hard stop |
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

**Model tier:** inherit — resolve delegated atomics via `bash scripts/resolve-model-tier.sh --command <child-slug>`; do not dispatch on bare `--command sw-deliver`.

## Delegated Task binding contract

Before each phase/terminal delegated Task from `/sw-deliver`:

1. `bash scripts/wave.sh dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-deliver --skill conductor`
2. `bash scripts/dispatch-check.sh --agent <agent-id> --command sw-deliver --skill conductor --parent-model <parent-concrete-id> [--dispatch-id <id>]`
3. Dispatch Task with explicit concrete `model:` and resolved caveman intensity context; never rely on inherited model.

Resolve model: `bash scripts/resolve-model-tier.sh --command <child-slug>` (or `--skill conductor`).
Resolve intensity: `bash scripts/resolve-intensity.sh --command sw-deliver --skill conductor`.

## Inline allowlist (closed)

`/sw-deliver` may remain inline only for:

- Durable driver invocations (`wave.sh deliver-loop/state/merge/status/report`).
- Lock/journal bookkeeping and deterministic state transitions.
- Legitimate-halt report emission and resume-command surfacing.

Wave implementation/review remediation work delegates.

## Dispatch context redaction contract

All non-config context passed to delegated Tasks (status excerpts, blocker reports, blast-radius notes,
memory-preflight outputs, diffs) must be redacted via `bash scripts/memory-redact.sh` and fenced as
`untrusted_payload` before inclusion.


## Planning scheduler and dependency gate (PRD 033)

Unit-level graph primitives (in addition to phase-mode waves):

| Entry | Command |
| --- | --- |
| Next eligible unit | `python3 scripts/wave_deliver.py <repo> next` |
| Dependency gate | `python3 scripts/wave_deliver.py <repo> dependency-gate preflight --task-list <path>` |
| Run-start revalidation | `python3 scripts/planning_deliver_gate.py <repo> dependency-gate run-start --task-list <path>` |
| Override (logged) | add `--override --override-reason "<why>"` to dependency-gate |

**Soft-enforce:** when `planning.autonomy` is `maintenance-only` (default) and an explicit `--task-list` targets a lower-priority eligible unit than `next` would pick, preflight returns a confirm prompt — pass `--confirmed` after operator ack.

**Run-start:** both `next` and explicit `--task-list` re-validate eligibility and depends at run-start (refuses `superseded`/`cancelled` races).

## Guardrails

- Promotion validates each candidate on a disposable PR head **before** merge to `main`.
- Post-partial-promotion regression: atomic integration PR or revert promoted leaves — never half-promoted red `main`.
- Teardown uses safe worktree/branch removal only.
