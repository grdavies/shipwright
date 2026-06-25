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
| `dispatch-ship` | Full `/sw-ship --phase-mode` in the phase worktree (`SW_PHASE_MODE=1`, `SW_PHASE_SLUG`, `SW_RUN_DIR`) |
| `remediate` | `/sw-stabilize` (or scoped fix) for the blocked phase within remediation budget |
| `compound-ship` | `/sw-compound-ship` on the orchestrator worktree after all phases merge |
| `terminal-ship` | Terminal PR CI watch + `/sw-ready` surface; may arm self-wake (below) |

**Orchestrator worktree:** run `deliver-loop` from `.sw-worktrees/<slug>-orchestrator` (or repo root with
state synced). Never hand off with "run deliver-loop next" as the only instruction — run it in-turn.

### Progress rule (R7)

Do not stop after a single mechanical step or one phase ship if `verdict` is still `running` and
`nextAction` is not a legitimate halt. The only acceptable turn endings are legitimate halts or terminal
completion.

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

**Run id** (stable per deliver run): `sw-deliver-<prd_number>-<target.slug>` from
`.cursor/sw-deliver-state.json` (e.g. `sw-deliver-009-autonomous-orchestration-conductor`).

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

## Self-wake environment fallback (R46)

Where the harness cannot auto-resume on `notify_on_output` (cloud/headless agents):

1. **Degrade to bounded in-turn poll:** sleep `checks.watch.pollSeconds` between checks, up to
   `checks.watch.maxWaitMinutes` total wall clock.
2. After expiry → single consolidated halt (R12) with exact resume command.
3. Never busy-spin; never yield with only "waiting for CI" and no halt boundary.

Detect unavailable self-wake when background shell + `notify_on_output` is not offered by the runtime;
default to poll-then-halt rather than indefinite yield.

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
