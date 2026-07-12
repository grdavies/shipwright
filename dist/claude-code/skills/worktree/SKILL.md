---

name: worktree
description: USE WHEN following the Shipwright workflow — command ordering, worktree isolation, and per-worktree state. Provision per-work-item git worktrees with env scaffold (ports, DB strategy) and safe teardown. Use when starting isolated implementation or docs work under the parallelism ceiling. Enforces ceiling; does not merge.
---

# Worktree provisioning

Every work item runs in its own worktree (R18). Bare `main` is not an implementation surface.


**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --skill worktree`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Provision

```bash
python3 scripts/worktree.py provision <name> [--base <ref>] [--branch <branch>] [--tier T] [--workstream W]
```

Creates `.sw-worktrees/<name>`, allocates a unique port from the configured pool, records scaffold + tier in
per-worktree state (`skills/shipwright-state`). Branch name is derived from `--branch <ref>` or a
conforming type-prefixed derivation from `<name>` — `pf/<name>` is never produced (R22/R23). Pass
`--branch <type>/<slug>` explicitly or let the script derive a conforming name; provisioning without a
conforming branch name fails closed with remediation.

## List / index

```bash
python3 scripts/worktree.py list
python3 scripts/worktree.py list --json   # includes per-worktree state snapshot
python3 scripts/worktree.py ceiling-check  # swWorktrees count (main excluded) + verdict
```

## Teardown (safe-by-construction)

```bash
python3 scripts/worktree.py teardown <name|path> [--force]
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

**Orchestrator exclusion (R53):** worktrees with `worktreeRole: orchestrator` (or
`countsTowardCeiling: false`) are excluded from `ceiling-check` counts — only phase `/sw-ship` slots
count toward the ceiling.
