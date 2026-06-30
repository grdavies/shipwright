---
description: Provision or tear down a per-work-item git worktree with env scaffold. Does not run the phase loop or merge PRs.
alwaysApply: false
---

# `/sw-worktree`

Provision isolated worktrees with port/DB scaffold, list active worktrees, or tear down safely.

## Subcommands

| Action | Usage |
| --- | --- |
| Provision | `python3 scripts/worktree.py provision <name> [--base <ref>] [--tier T]` |
| List | `python3 scripts/worktree.py list` or `list --json` |
| Ceiling | `python3 scripts/worktree.py ceiling-check` |
| Teardown | `python3 scripts/worktree.py teardown <name>` |

Load `skills/worktree/SKILL.md` for scaffold schema and guardrails.

## Procedure (provision)

1. Read `workflow.config.json` → `worktree`, `defaultBaseBranch`.
2. Run `ceiling-check`; if at ceiling, hand off to recombination (`skills/parallelism`) — do not fan out.
3. Provision via `scripts/worktree.py provision` (parent ref defaults to persisted trunk base via
   `scripts/resolve-base-branch.py`; phase-mode phase worktrees fork from integration base `<type>/<slug>` when `--base` omitted).
4. Print `python3 scripts/resolve-base-branch.py disclose --quiet` when base state exists.
5. `cd` into the new worktree path; confirm state via `scripts/shipwright-state.py read`.
6. Next step: `/sw-start` inside the worktree.

## Procedure (teardown)

1. Confirm no uncommitted work (or user approves discard).
2. `python3 scripts/worktree.py teardown <name>` — never `rm` the directory.
3. Report disk reclaimed from script output.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-worktree`.

## Guardrails

- Never implement in bare `main` — provision a worktree first.
- Teardown is `git worktree remove` + `prune` only.
- Does not commit, push, open PRs, or merge.
