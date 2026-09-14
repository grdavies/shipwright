# Parallel dispatch protocol

## Parallel wave dispatch protocol (R14–R20)

### 1. Plan-time contention (R20, R39)

`python3 scripts/wave.py plan` injects `contention.injectedEdges` from phase `**File:**` paths:

- Shared migration dirs (`db/migrate/`, `supabase/migrations/`, `prisma/migrations/`)
- `CHANGELOG.md`, `version.txt`, `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`
- `doc-numbering` (any `docs/prds/*` or `docs/decisions/*` path except INDEX)

Contended phases are forced into different waves before dispatch. Cycles fail closed (`halt: contention-cycle`).

### 2. Schedule consumption (R14, R15)

```bash
python3 scripts/wave.py schedule --plan .cursor/sw-deliver-plan.json
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
   merge or acquire locks (R41). Workflow pushes use `scripts/git-push.py` only (R23).

### 4. Intra-phase dispatch (R17, R18, R45)

| Phase runs as | Intra-phase sub-agents |
| --- | --- |
| Background parallel Task | **Inline** two-stage review only (R45) |
| Conductor inline | `sw-subagent-dispatch` heuristics when ≥8 files / parallel tasks |

Intra-phase dispatch never consumes `parallelCeiling` slots (R18).

### 5. Outcomes + blast radius (R19, R24)

```bash
python3 scripts/wave.py status collect --phase-slug <slug>
```

- `merge-ready-green` → conductor enqueues merge (serialized queue).
- `blocked` → `blast-radius apply` marks **transitive dependents** only; green siblings continue.

```bash
python3 scripts/wave.py blast-radius dependents --phase-slug <slug>   # inspect
```

## Safety invariants under concurrency (R21–R24)

| Invariant | Enforcement |
| --- | --- |
| Single-flight merge (R21) | `mergeQueue` + `mergeJournal`; one `merge run-next` at a time |
| Atomic lock (R41) | `wave.py lock acquire` uses `O_EXCL` on `.cursor/sw-deliver.lock` |
| No `main` merge (R22) | `merge run-next` target is always `<type>/<slug>` from plan |
| Push chokepoint (R23) | `scripts/git-push.py` only — secret-scan pre-push |
| Blast radius (R24) | `status collect` → `blast-radius apply`; siblings unaffected |

Phase sub-agents **must not** call `merge run-next`, `merge enqueue`, `lock acquire`, or raw `git push`.
All workflow pushes route through `scripts/git-push.py` (secret-scan pre-push preserved).

### Eager phase-worktree teardown (R17)

After `merge run-next` + incremental verify, the driver transitions the phase
`green-merged → teardown-pending → teardown-complete` via `phase-teardown-run` once dependents forward-merge
and retained branch/status refs are safe. `phaseWorktrees[<id>]` clears on `teardown-complete`; the
orchestrator worktree persists until terminal completion. Teardown uses `git worktree remove` + `prune` only.
