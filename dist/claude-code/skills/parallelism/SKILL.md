---
name: pf-parallelism
description: Bounded parallel worktrees (~2-4 ceiling), cross-branch recombination, merge pre-flight, shared-migration refusal.
---

# Bounded parallelism

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

If overlap → serialize; do not parallelize.

## Pre-flight checklist

1. `ceiling-check` green?
2. No shared-migration overlap?
3. Rebase parent branches current?
4. Recombination review complete if at ceiling?

## Integration

- `/pf-worktree provision` enforces ceiling.
- `/pf-ship` and gap-closers respect dispatch policy (`rules/pf-subagent-dispatch.mdc`).
