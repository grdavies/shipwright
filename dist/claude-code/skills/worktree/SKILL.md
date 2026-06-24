---
name: sw-worktree
description: USE WHEN following the Shipwright workflow — command ordering, worktree isolation, and per-worktree state. Provision per-work-item git worktrees with env scaffold (ports, DB strategy) and safe teardown. Enforces parallelism ceiling.---

# Worktree provisioning

Every work item runs in its own worktree (R18). Bare `main` is not an implementation surface.

## Provision

```bash
bash scripts/worktree.sh provision <name> [--base <ref>] [--branch <branch>] [--tier T] [--workstream W]
```

Creates `.sw-worktrees/<name>`, branches `pf/<name>` by default, allocates a unique port from the configured
pool, records scaffold + tier in per-worktree state (`skills/phase-state`).

## List / index

```bash
bash scripts/worktree.sh list
bash scripts/worktree.sh list --json   # includes per-worktree state snapshot
bash scripts/worktree.sh ceiling-check  # swWorktrees count (main excluded) + verdict
```

## Teardown (safe-by-construction)

```bash
bash scripts/worktree.sh teardown <name|path> [--force]
```

Always `git worktree remove` + `git worktree prune`. **Never `rm` the directory** — the script refuses
unsafe deletes and surfaces reclaimed disk.

## Scaffold config

Declare in `workflow.config.json` → `worktree.scaffold`:

- `portRangeStart` / `portRangeEnd` — unique port per worktree
- `dbStrategy` — `schema-prefix` | `isolated-db` | `shared`
- `dbTemplate` — optional DSN template for isolated DB

## Parallelism

`worktree.parallelCeiling` (default 4). Beyond ceiling → run recombination (`skills/parallelism`) before
provisioning another worktree.
