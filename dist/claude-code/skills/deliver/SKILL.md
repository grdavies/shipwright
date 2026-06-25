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
- **contention:** shared-migration refusal + living INDEX/numbering counters force serialization.

## Run-state artifacts

| Artifact | Path |
|----------|------|
| Plan | `.cursor/sw-deliver-plan.json` |
| Run state | `.cursor/sw-deliver-state.json` |
| Orchestrator lock | `.cursor/sw-deliver.lock` |
| Per-phase status | `.cursor/sw-deliver-runs/<phase>/status.json` |

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
