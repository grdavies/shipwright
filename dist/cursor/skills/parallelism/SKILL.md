---
name: sw-parallelism
description: Bounded parallel worktrees (~2-4 ceiling), cross-branch recombination, merge pre-flight, shared-migration refusal.
---

# Bounded parallelism


**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill parallelism`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Ceiling

`workflow.config.json` → `worktree.parallelCeiling` (default 4).

```bash
bash scripts/worktree.sh ceiling-check
```

Exit 10 = at ceiling → **recombination required** before another provision.

## Recombination (beyond ceiling)

1. List worktrees: `bash scripts/worktree.sh list --json`.
2. Review cross-branch diffs between active streams (orchestrator, not parallel agents).
3. Prefer **rebase** for linear history before dispatching long-running parallel work.
4. Run merge pre-flight: refuse parallel dispatch when migration paths or high-risk shared files overlap.

## Shared-migration refusal

Before parallel provision/dispatch, check for overlapping:

- `db/migrate/*`, `supabase/migrations/*`, `prisma/migrations/*`
- Same files touched on multiple active phase branches
- Living `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`, doc-numbering counters
- `CHANGELOG.md` and `version.txt` (orchestrator bookkeeping contention)

If overlap → serialize; do not parallelize.

Phase-mode `/sw-deliver` runs this net automatically during `wave.sh plan` / `preflight`:

- Parses each phase's `**File:**` paths from the frozen task list
- Injects serialization edges (lower phase number first) for declared-parallel pairs that overlap
- Re-runs cycle detection on declared + injected edges; refuses with `contention-cycle` on conflict
- Emits a `contention:` notice per forced serialization

```bash
scripts/wave.sh plan --task-list docs/prds/<n>-<slug>/tasks-<n>-<slug>.md --dry-run
# inspect notices + contention.injectedEdges in JSON
```

## Pre-flight checklist

1. `ceiling-check` green?
2. No shared-migration overlap?
3. Rebase parent branches current?
4. Recombination review complete if at ceiling?

## Integration

- `/sw-worktree provision` enforces ceiling.
- `/sw-ship` and gap-closers respect dispatch policy (`rules/sw-subagent-dispatch.mdc`).

## Wave-batching proposals + fallbacks (PRD 022)

Under `orchestration.planPolicy: proposed` (PRD-023 pilot), the conductor may propose wave batching at wave
entry. Proposals validate through `bash scripts/wave.sh plan validate --tier wave` against contention edges +
`worktree.parallelCeiling`. On reject or ambiguity:

- Re-derive **canonical waves** from the frozen `.cursor/sw-deliver-plan.json` plan.
- When over-ceiling → `bash scripts/wave.sh schedule --plan .cursor/sw-deliver-plan.json`.
- Undeclared `**File:**` overlaps between parallel phases auto-serialize (PRD-013 R14 precedent).

Default `planPolicy: canonical` uses plan-time `wave.sh plan` waves only — no observable change.

## Intra-phase fan-out vs wave ceiling (PRD 023 R15–R17)

Wave-level phase worktrees count toward `worktree.parallelCeiling`; intra-phase Task/review workers
use a separate `intraPhase.parallelBudget` and never consume wave slots. A **global cap** still holds:

`waveSlots + activeIntraPhase ≤ min(worktree.parallelCeiling, intraPhase.harnessLimit)`

Mechanical guard (disjoint partition, no-nesting, decision log):

```bash
# Stamp conductor_mode at phase entry (inline default; background_phase disables nested Task dispatch)
bash scripts/wave.sh phase dispatch-env --phase-slug <slug> --conductor-mode background_phase

# Evaluate / record before spawning intra-phase workers
bash scripts/intra-phase-dispatch.sh evaluate --context-json '<signal_context>' \
  --wave-slots <n> --active-intra-phase <n> \
  --run-dir .cursor/sw-deliver-runs/<slug> --record
```

Parallel intra-phase workers are read-only on `ship-steps.json` and `status.json` in the phase run dir.
Each parallelization decision is recorded in `dispatch-decisions.json`.
