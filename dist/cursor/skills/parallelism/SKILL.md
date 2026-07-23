---
name: parallelism
description: Bounded parallel worktrees (~2–4 ceiling), cross-branch recombination, merge pre-flight, shared-migration refusal. Use when /sw-deliver or /sw-worktree fans out independent heads. Does not bypass merge gates.
---
# Bounded parallelism


**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill parallelism`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Ceiling

`workflow.config.json` → `worktree.parallelCeiling` (default 4).

```bash
python3 scripts/worktree.py ceiling-check
```

Exit 10 = at ceiling → **recombination required** before another provision.

## Recombination (beyond ceiling)

1. List worktrees: `python3 scripts/worktree.py list --json`.
2. Review cross-branch diffs between active streams (orchestrator, not parallel agents).
3. Prefer **rebase** for linear history before dispatching long-running parallel work.
4. Run merge pre-flight: refuse parallel dispatch when migration paths or high-risk shared files overlap.

## Contention families (phase-mode + split suggestions)

`/sw-deliver` phase-mode and PRD 040 split suggestions share the same serializing families via
`wave_deliver.py` (`inject_contention_edges`, `paths_contend`, `expand_generator_contention_paths`). When
authoring phases or reviewing advisory splits, treat these as mandatory serialization edges — never drop one
to gain parallelism:

| Family | Trigger |
|--------|---------|
| Shared migrations | Overlap under `db/migrate/`, `supabase/migrations/`, `prisma/migrations/` |
| Release bookkeeping | Both phases touch `CHANGELOG.md` or `version.txt` |
| Living doc numbering | `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`, doc-numbering counters |
| `**File:**` path overlap | Same normalized path in two parallel phases |
| Generator output | `generator-output` / golden-manifest globs via `expand_generator_contention_paths` |

Split suggestions from `python3 scripts/phase_sizing.py advisory` cite these families when proposing
mandatory internal edges. Simulation uses the same primitives as `scripts/wave.py plan --dry-run`.

## Shared-migration refusal

Before parallel provision/dispatch, check for overlapping:

- `db/migrate/*`, `supabase/migrations/*`, `prisma/migrations/*`
- Same files touched on multiple active phase branches
- Living `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`, doc-numbering counters
- `CHANGELOG.md` and `version.txt` (orchestrator bookkeeping contention)

If overlap → serialize; do not parallelize.

Phase-mode `/sw-deliver` runs this net automatically during `wave.py plan` / `preflight`:

- Parses each phase's `**File:**` paths from the frozen task list
- Injects serialization edges (lower phase number first) for declared-parallel pairs that overlap
- Re-runs cycle detection on declared + injected edges; refuses with `contention-cycle` on conflict
- Emits a `contention:` notice per forced serialization

```bash
scripts/wave.py plan --task-list docs/prds/<n>-<slug>/tasks-<n>-<slug>.md --dry-run
# inspect notices + contention.injectedEdges in JSON
```

## Pre-flight checklist

1. `ceiling-check` green?
2. No shared-migration overlap?
3. Rebase parent branches current?
4. Recombination review complete if at ceiling?


## Execute sub-branches (PRD 053)

Execute-tier sub-branches (`feat/<slug>-phase-<pslug>--task-<ref>`) are provisioned by `execute_plan.py` and
**do not count** toward `worktree.parallelCeiling` (`countsTowardCeiling: false`). Concurrent sub-branches
are capped by `execute.subBranchCeiling` (default: `intraPhase.parallelBudget`). Integrate is single-flight
per phase worktree (`execute_integrate.py`). Parallel execute batches respect `intraPhase.parallelBudget` and
global `min(worktree.parallelCeiling, intraPhase.harnessLimit)`.

## Integration

- `/sw-worktree provision` enforces ceiling.
- `/sw-ship` and gap-closers respect dispatch policy (`rules/sw-subagent-dispatch.mdc`).

## Wave-batching proposals + fallbacks (PRD 022)

Under `orchestration.planPolicy: proposed` (PRD-023 pilot), the conductor may propose wave batching at wave
entry. Proposals validate through `python3 scripts/wave.py plan validate --tier wave` against contention edges +
`worktree.parallelCeiling`. On reject or ambiguity:

- Re-derive **canonical waves** from the frozen `.cursor/sw-deliver-plan.json` plan.
- When over-ceiling → `python3 scripts/wave.py schedule --plan .cursor/sw-deliver-plan.json`.
- Undeclared `**File:**` overlaps between parallel phases auto-serialize (PRD-013 R14 precedent).

Default `planPolicy: canonical` uses plan-time `wave.py plan` waves only — no observable change.

## Intra-phase fan-out vs wave ceiling (PRD 023 R15–R17)

Wave-level phase worktrees count toward `worktree.parallelCeiling`; intra-phase Task/review workers
use a separate `intraPhase.parallelBudget` and never consume wave slots. A **global cap** still holds:

`waveSlots + activeIntraPhase ≤ min(worktree.parallelCeiling, intraPhase.harnessLimit)`

Mechanical guard (disjoint partition, no-nesting, decision log):

```bash
# Stamp conductor_mode at phase entry (inline default; background_phase disables nested Task dispatch)
python3 scripts/wave.py phase dispatch-env --phase-slug <slug> --conductor-mode background_phase

# Evaluate / record before spawning intra-phase workers
python3 scripts/intra-phase-dispatch.py evaluate --context-json '<signal_context>' \
  --wave-slots <n> --active-intra-phase <n> \
  --run-dir .cursor/sw-deliver-runs/<slug> --record
```

Parallel intra-phase workers are read-only on `ship-steps.json` and `status.json` in the phase run dir.
Each parallelization decision is recorded in `dispatch-decisions.json`. The latest validated snapshot
also appears on phase status as `intraPhaseFanOut` (`activeWorkers`, `globalCap`, `partitionSummary`).

Config keys: `intraPhase.parallelBudget` (default 2), `intraPhase.harnessLimit` (default 8).

Example `dispatch-decisions.json` entry:

```json
{
  "timestamp": "2026-06-27T08:00:00Z",
  "signals": {"fileCount": 4, "derivedTags": ["docs"], "conductorMode": "inline", "phaseType": "ship"},
  "declaredPartition": [{"files": ["docs/guides/configuration.md"], "workerId": "w1"}],
  "chosenParallelism": {"workers": 1, "serialized": false},
  "degradeReason": null
}
```
