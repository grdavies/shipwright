# Parallel Merge And Recovery

## Parallel scheduler (R14/R44)

After `plan`, compute ceiling-bounded dispatch batches:

```bash
scripts/wave.py schedule --plan .cursor/sw-deliver-plan.json
# optional override: --ceiling 2
```

- Reads `worktree.parallelCeiling` from `.cursor/workflow.config.json` (default **4**).
- Each **wave** may require multiple **batches** when `len(wave) > parallelCeiling`.
- Batches are greedy left-to-right chunks; the scheduler **never unwinds** a running phase to
  admit a queued one.
- **Ceiling accounting (R44):** only wave-level `/sw-ship` phase worktrees count toward the ceiling.
  Internal sub-agent dispatch *within* a phase's `/sw-ship` (`rules/sw-subagent-dispatch.mdc`) does
  **not** consume slots. The orchestrator merge queue progresses without holding a phase slot.

Schedule JSON shape:

```json
{
  "parallelCeiling": 4,
  "schedule": [
    {
      "wave": 2,
      "phases": ["2", "3", "4", "5"],
      "batches": [
        {"parallel": ["2", "3", "4", "5"], "slotCount": 4, "remainderQueued": false}
      ],
      "countsTowardCeiling": true
    }
  ]
}
```

When a wave exceeds the ceiling, `batches` splits into sequential chunks (e.g. ceiling 2 with
phases `["2","3","4"]` → `[["2","3"],["4"]]`).

## Conductor parallel dispatch (R14–R16, R22)

When a wave has N independent ready phases, the driver emits **`dispatch-batch`** — one action marking all N
`in-flight` atomically. The conductor spawns N background `Task` sub-agents (up to `parallelCeiling`):

1. Driver `provision-phase` (mechanical) until worktrees exist for the batch.
2. Driver returns `dispatch-batch` → conductor spawns N background Tasks (`run_in_background: true`).
3. Wait for durable `status.json` per **Parallel-wave completion wait** in `skills/conductor/SKILL.md`.
4. Driver `collect-all-ready` enqueues simultaneous greens in phase-id order → `merge run-next`
   (conductor only). **Whole-batch gate (R10):** the driver never `merge-enqueue`s a lone ready member while
   sibling in-flight phases lack validated terminal status; integration HEAD is pinned at collect-all-ready.
5. **Deterministic merge conflicts (R12):** conflicts confined to `core/sw-reference/deterministic-regen-paths.json`
   auto-resolve via regenerate-and-restage in the orchestrator worktree; semantic paths halt.

On `status collect` with `blocked`, `blast-radius apply` blocks transitive dependents only (R24):

```bash
scripts/wave.py status collect --phase-slug <phase-slug>
scripts/wave.py blast-radius apply --phase-slug <upstream-slug>
```

## Branch topology (R35/R53)

Operator worktree contract (PRD 049 R1/R2 — full table in `.sw/layout.md`):

| Role | Branch | Worktree path | Agent cwd |
|------|--------|---------------|-----------|
| Primary | `defaultBaseBranch` | repo root | operator shell only — no implementation commits during deliver |
| Feature base | `<type>/<slug>` | `.sw-worktrees/<slug>-orchestrator` | conductor loop (`deliver-loop`) |
| Phase unit | `<type>/<slug>-phase-<phase-slug>` | `.sw-worktrees/<slug>-phase-<phase-slug>` | `/sw-ship` / `/sw-execute` |

Repo-root `.cursor/` is **conductor runtime** (canonical deliver state, locks, run logs) — updates during
deliver are expected and must not be committed as feature work. `status.json` mirrors **phase → repo root**
only; never a general root→worktree sync.

Phase branches come from the deliver plan `items[].branch`. The orchestrator worktree checks out
`<type>/<slug>` (detached at the target tip when that branch is already checked out elsewhere) and does
**not** consume a `parallelCeiling` slot (`countsTowardCeiling: false` in per-worktree state).

```bash
scripts/wave.py assert-entry
scripts/wave.py orchestrator provision --plan .cursor/sw-deliver-plan.json
scripts/wave.py orchestrator status
scripts/wave.py phase provision --phase-id 1 --plan .cursor/sw-deliver-plan.json
scripts/wave.py forward-merge --worktree .sw-worktrees/<slug>-phase-<phase> --base feat/<slug>
scripts/wave.py phase-teardown --name <slug>-phase-<phase>
```

**Forward-merge (R20/R40):** after a sibling merges into `<type>/<slug>`, integrate the new tip into a
dependent phase branch via **merge** (never rebase a published phase branch). Conflicts surface as
`blocked` with `cause: forward-merge:conflict`.

**Teardown (R21):** only `git worktree remove` + `prune` — never `rm` the directory.

## Stacking

Dependents provision with:

```bash
scripts/worktree.py provision <name> --base <dependency-branch> --branch <type>/<name>
```

`<type>` must be drawn from `release-please-config.json` `changelog-sections[].type` (e.g. `feat`, `fix`,
`chore`). `pf/<name>` is prohibited; the branch-name guard (`scripts/branch-name-guard.py`) refuses
non-conforming names at creation time (R22–R25).

Merge pre-flight from `skills/parallelism/` runs before stacking. No item touches `main` mid-wave.

## Integration branch

After green leaves:

1. Create `integration/<stamp>` from `main`.
2. Merge green leaf branches.
3. Run whole-suite check (`check-gate.py` on integration PR head).
4. Human gate authorizes `promote` in dependency order.

## Promotion (pre-merge validated)

For each leaf in dependency order:

1. Build disposable candidate ref: `main` + already-promoted + this leaf.
2. Push candidate branch + open short-lived PR.
3. Run `check-gate.py` on PR head — green only then fast-forward to `main`.
4. Red candidate halts promotion before `main` is touched.

## Attributability

| Integration red type | Action |
|---------------------|--------|
| Reproduces in one leaf | Route to that leaf's stabilize loop |
| Every leaf/pair green in isolation | Delta-debug minimal subset + human escalation |

## High-contention surfaces

Living `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`, and doc-numbering counters are shared mutable state — serialize doc-creation across a wave or late-bind numbering at integration.

## Phase `/sw-ship` dispatch (R48/R18)

Each phase runs the full `/sw-ship` chain inside an isolated worktree. The orchestrator MUST dispatch with the
non-interactive contract:

```bash
export SW_PHASE_MODE=1
export SW_PHASE_SLUG=<phase-slug>
export SW_RUN_DIR=.cursor/sw-deliver-runs/<phase-slug>
# invoke /sw-ship --phase-mode in the phase worktree
```

On completion, read `$SW_RUN_DIR/status.json` (or `.cursor/sw-deliver-runs/<phase>/status.json`):

| `verdict` | Orchestrator action |
| --- | --- |
| `merge-ready-green` | Enqueue serialized merge into `<type>/<slug>` (R19); never merge to `main` here |
| `blocked` | Record `blocked` in run-state; apply blast-radius (R25/R26); surface `cause` |

Terminal pause is suppressed; `/sw-deliver` must not wait on human input for per-phase outcomes.

## Conductor in-turn loop (R2, R6, R7, R13)

`/sw-deliver` consumes `skills/conductor/SKILL.md` for the autonomous loop. Summary:

1. Run `python3 scripts/wave.py deliver-loop` from the orchestrator worktree.
2. While `verdict: running` and no legitimate halt:
   - `awaitAgent: false` → re-invoke `deliver-loop` immediately (same turn).
   - `awaitAgent: true` → execute `next.action` (`dispatch-ship`, `remediate`, `retrospective`, or
     `terminal-ship`), then re-invoke `deliver-loop`.
3. Never end the turn asking the user to "continue deliver" when progress is still possible (R13).

**Retrospective handoff (R9):** when `next.action` is `retrospective`, run **`/sw-retrospective --pre-merge`**
on the orchestrator worktree only — do not inline retro/compound/memory/status. Respect `compound.autonomy`
via `python3 scripts/wave.py retrospective autonomy`. Then re-invoke `deliver-loop` for `terminal-ship`.

**Self-wake (R8/R9):** terminal-PR CI uses `notify_on_output` on `^DELIVER_WAKE_<run-id>`; tear down all
watchers on terminal halt. **Parallel-wave wait (R44):** poll or self-wake on durable `status.json` set.
**Headless fallback (R46):** bounded poll to `checks.watch.maxWaitMinutes`, then one consolidated halt.

**Hard stop (R38):** `deliver.autonomy.maxIterations` + 3× no-progress on `(nextAction, stateSignature)` —
see `rules/sw-subagent-dispatch.mdc`.

## Sub-agent dispatch spike (R63)

**Spike conclusion (2026-06):** Cursor's parent agent can launch **background** subagents via the Task tool
(`run_in_background: true`), but **nested** dispatch (a subagent launching its own subagents) is not a reliable
platform contract — depth and tool availability vary by runtime.

**Default / fallback:** per-phase `/sw-execute` uses **inline two-stage review** from
`rules/sw-subagent-dispatch.mdc` (spec-compliance → code-quality) when:

- nested background dispatch is unavailable or untested for the active runtime, or
- the phase touches ≤3 files with sequential edits (inline is already preferred).

When background dispatch **is** available at the orchestrator level, `/sw-deliver` may dispatch phase
`/sw-ship` as a background Task; the orchestrator still collects outcomes from the durable
`sw-deliver-runs/<phase>/status.json` path — never from ephemeral `sw-tmp` run dirs alone.
