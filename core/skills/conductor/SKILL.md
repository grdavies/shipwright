---
name: conductor
description: Shared autonomous orchestration contract — self-continuation, legitimate halts, parallel phase dispatch, and durable-state resumption. Consumed by orchestrators; never re-authored inline.
---

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
| Durable driver | `scripts/wave.sh deliver-loop` |
| Run-state R/W | `scripts/wave.sh state …` |
| Provision / teardown | `scripts/wave.sh orchestrator provision`, `scripts/wave.sh phase provision` |
| Phase outcomes | `scripts/wave.sh status collect` → `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Merge queue | `scripts/wave.sh merge enqueue`, `scripts/wave.sh merge run-next` |
| Locks / journal | `scripts/wave.sh lock …`, `scripts/wave.sh journal …` |
| Halt report | `scripts/wave.sh report terminal` |

The conductor **invokes** these commands and interprets their JSON — it does not maintain parallel state.

## Durable artifacts (resumption — R4)

A fresh agent with no prior chat context resumes from:

| Artifact | Path |
| --- | --- |
| Run cursor | `.cursor/sw-deliver-state.json` (`nextAction`, `currentWave`, phase statuses) |
| Plan | `.cursor/sw-deliver-plan.json` |
| Per-phase `/sw-ship` status | `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Append-only progress | `.cursor/sw-deliver-runs/run.log` |

Resume command (phase-mode):

```bash
bash scripts/wave.sh deliver-loop --dry-run   # inspect nextAction
bash scripts/wave.sh deliver-loop             # advance one mechanical step or emit awaitAgent
```

Never infer progress from chat history or ephemeral sub-agent logs (R19). Phase outcomes come solely from
`status.json`.

## Default autonomy (R13)

With default configuration (`deliver.autonomy.mode: autonomous`, `phaseAckCadence: 0`, `doc.afterTasks` not
blocking deliver), a frozen task list runs end-to-end to the **terminal-PR human gate** with zero
"continue deliver" style re-prompts. The conductor performs agent work when the driver returns
`awaitAgent: true`, then immediately re-invokes `deliver-loop` within the same turn (R6/R7 — detailed in
phase 4).

## Legitimate-halt set (R10 — summary)

Halt for human input **only** when:

1. Final merge to `main` (terminal gate — never auto-merged).
2. Phase remediation budget exhausted (`deliver.remediation.maxAttempts`).
3. Ambiguous merge conflict or destructive/irreversible action requiring explicit consent.
4. User-configured checkpoint (`doc.afterTasks: confirm`, `deliver.phaseAckCadence: K>0`,
   `deliver.autonomy.mode: supervised`).
5. Phase liveness timeout without terminal `status.json` (R37).
6. External wait exhausted (`checks.watch.maxWaitMinutes`) without a wake signal (R40).
7. Run-level autonomy budget exceeded (`deliver.autonomy.maxRunMinutes` / `maxIterations`) (R42).

**No routine halts (R11):** per-phase progression, status collection, wave advancement, and release
bookkeeping do not pause for the user.

Every halt emits one consolidated report via `scripts/wave.sh report terminal` — what is blocked, why, and
the exact resume command (R12). Never emit a bare "continue?" prompt.

## Parallel dispatch (R14–R20 — summary)

- Compute ready phases: `bash scripts/wave.sh schedule --plan .cursor/sw-deliver-plan.json`.
- Dispatch each ready phase as a background sub-agent in its own phase worktree, bounded by
  `worktree.parallelCeiling`.
- Over-ceiling waves run in greedy sequential batches; never unwind a running phase (R15).
- Dispatch **only** from the conductor level — no nested sub-agent dispatch (R16).
- Intra-phase sub-agent dispatch follows `rules/sw-subagent-dispatch.mdc` heuristics only when the conductor
  runs that phase inline; backgrounded phases use inline two-stage review (R17, R45).
- Only wave-level phase worktrees count toward the ceiling (R18).

Contention serialization is enforced at plan time (`scripts/wave_deliver.py`); honor wave boundaries from
the plan.

## Safety invariants (R21–R24)

- Single-flight merge queue: phase sub-agents never call `merge run-next` (R41).
- Merge only green, review-satisfied phases onto `<type>/<slug>` — never `main` (R22).
- All pushes through `scripts/git-push.sh` — no raw `git push` (R23).
- Blocked phase blocks transitive dependents only; green siblings continue (R24).

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
| `/sw-deliver` | Pilot consumer (R34) — load this skill in `deliver-loop` / `run` |
| `/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback` | Enumerated in `orchestrator-adoption-audit.md`; adopt in follow-on PRDs (R35) |

Reference this skill from orchestrator commands; do not duplicate loop prose.
