---
name: sw-deliver
description: Dependency-ordered deliver waves with dependent-branch stacking and integration branch lifecycle.
---

# Deliver orchestration

Layer above `/sw-ship` for **phase-mode** (frozen task-list phases stacking onto `<type>/<slug>`) and
**multi-feature mode** (independent features promoting via `integration/<stamp>`). Reuses `scripts/worktree.sh`
and `skills/parallelism/` wholesale.

## Deliver plan representation

Path: `.cursor/sw-deliver-plan.json` (machine-readable; see `.sw/layout.md`).

```json
{
  "verdict": "pass",
  "mode": "phase",
  "source_task_list": "docs/prds/<n>-<slug>/tasks-<n>-<slug>.md",
  "prd_number": "004",
  "target": {"type": "feat", "slug": "<slug>", "branch": "feat/<slug>"},
  "items": [{"id": "1", "slug": "<phase-slug>", "title": "...", "branch": "feat/<slug>-phase-<phase-slug>"}],
  "edges": [{"from": "1", "to": "2"}],
  "waves": [["1"], ["2", "3"]],
  "contention": {"serialized": ["doc-numbering"], "notes": "..."},
  "notices": []
}
```

Multi-feature mode uses `"mode": "multi-feature"` with `pf/<id>` branches (unchanged).

- **waves:** ordered batches; no intra-wave dependencies.
- **contention:** shared-migration refusal + living INDEX/numbering counters force serialization;
  `injectedEdges` records contention-forced edges merged into `edges` / `waves`.

## Run-state artifacts

| Artifact | Path |
|----------|------|
| Plan | `.cursor/sw-deliver-plan.json` |
| Run state | `.cursor/sw-deliver-state.json` |
| Orchestrator lock | `.cursor/sw-deliver.lock` |
| Per-phase `/sw-ship` status | `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Append-only progress log | `.cursor/sw-deliver-runs/run.log` |

Living artifacts under `.cursor/` are **never committed** (`/sw-commit` excludes them).

### Run-state schema (`.cursor/sw-deliver-state.json`)

Initialized from the phase-mode plan via `scripts/wave.sh state init --plan .cursor/sw-deliver-plan.json`:

```json
{
  "verdict": "running",
  "target": {"type": "feat", "slug": "<slug>", "branch": "feat/<slug>"},
  "source_task_list": "docs/prds/<n>-<slug>/tasks-<n>-<slug>.md",
  "prd_number": "004",
  "phases": {
    "1": {
      "id": "1",
      "slug": "<phase-slug>",
      "title": "...",
      "branch": "feat/<slug>-phase-<phase-slug>",
      "status": "pending",
      "updatedAt": "2026-06-25T00:00:00Z"
    }
  },
  "mergeJournal": null,
  "updatedAt": "2026-06-25T00:00:00Z"
}
```

**Phase status vocabulary:** `pending` | `in-flight` | `green-merged` | `blocked` | `rejected`.

**Helpers:**

```bash
scripts/wave.sh state init --plan .cursor/sw-deliver-plan.json
scripts/wave.sh state phase --id 1 --status in-flight
scripts/wave.sh state phase --slug rename-deliver --status green-merged
scripts/wave.sh state get
scripts/wave.sh state terminal --verdict complete
```

Per-phase `/sw-ship` outcomes live in `sw-deliver-runs/<phase>/status.json` (`merge-ready-green` |
`blocked`); `scripts/ship-phase-status.sh` syncs `blocked` into run-state when present.

### Orchestrator lock + merge journal (R51)

```bash
scripts/wave.sh lock acquire --target feat/<slug> --nonblock   # exit 20 if held
scripts/wave.sh lock release
scripts/wave.sh journal begin --phase <phase-slug> [--head <sha>]
scripts/wave.sh journal complete --phase <phase-slug>
```

- **Lock:** atomic create on `.cursor/sw-deliver.lock` keyed by `<type>/<slug>` metadata; second
  invocation refuses (`exit 20`) until `lock release`.
- **Merge journal:** open entry before phase → `<type>/<slug>` merge; cleared after push + state commit.
  Resume detects interrupted merge via `journal status`.

### Progress log (R54)

Append-only JSON lines at `.cursor/sw-deliver-runs/run.log` on run init, phase transitions, lock
acquire/release, merge journal events, and terminal halt.

```bash
scripts/wave.sh log tail --lines 20
```

Each line: `{ "event": "phase-transition", "phaseId": "1", "from": "pending", "to": "in-flight", "at": "..." }`.

## Parallel scheduler (R14/R44)

After `plan`, compute ceiling-bounded dispatch batches:

```bash
scripts/wave.sh schedule --plan .cursor/sw-deliver-plan.json
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

## Stacking

Dependents provision with:

```bash
scripts/worktree.sh provision <name> --base <dependency-branch> --branch pf/<name>
```

Merge pre-flight from `skills/parallelism/` runs before stacking. No item touches `main` mid-wave.

## Integration branch

After green leaves:

1. Create `integration/<stamp>` from `main`.
2. Merge green leaf branches.
3. Run whole-suite check (`check-gate.sh` on integration PR head).
4. Human gate authorizes `promote` in dependency order.

## Promotion (pre-merge validated)

For each leaf in dependency order:

1. Build disposable candidate ref: `main` + already-promoted + this leaf.
2. Push candidate branch + open short-lived PR.
3. Run `check-gate.sh` on PR head — green only then fast-forward to `main`.
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
