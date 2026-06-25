---
name: sw-worktree
description: Provision per-work-item git worktrees with env scaffold (ports, DB strategy) and safe teardown. Enforces parallelism ceiling.
---

# Worktree provisioning

Every work item runs in its own worktree (R18). Bare `main` is not an implementation surface.


**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill worktree`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Provision

```bash
bash scripts/worktree.sh provision <name> [--base <ref>] [--branch <branch>] [--tier T] [--workstream W]
```

Creates `.sw-worktrees/<name>`, allocates a unique port from the configured pool, records scaffold + tier in
per-worktree state (`skills/shipwright-state`). Branch name is derived from `--branch <ref>` or a
conforming type-prefixed derivation from `<name>` — `pf/<name>` is never produced (R22/R23). Pass
`--branch <type>/<slug>` explicitly or let the script derive a conforming name; provisioning without a
conforming branch name fails closed with remediation.

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

**Orchestrator exclusion (R53):** worktrees with `worktreeRole: orchestrator` (or
`countsTowardCeiling: false`) are excluded from `ceiling-check` counts — only phase `/sw-ship` slots
count toward the ceiling.
