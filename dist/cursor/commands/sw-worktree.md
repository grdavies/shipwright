---
description: Provision or tear down a per-work-item git worktree with env scaffold. Does not run the phase loop or merge PRs.
alwaysApply: false
---

# `/sw-worktree`

Provision isolated worktrees with port/DB scaffold, list active worktrees, or tear down safely.

## Subcommands

| Action | Usage |
| --- | --- |
| Provision | `bash scripts/worktree.sh provision <name> [--base <ref>] [--tier T]` |
| List | `bash scripts/worktree.sh list` or `list --json` |
| Ceiling | `bash scripts/worktree.sh ceiling-check` |
| Teardown | `bash scripts/worktree.sh teardown <name>` |

Load `skills/worktree/SKILL.md` for scaffold schema and guardrails.

## Procedure (provision)

1. Read `workflow.config.json` → `worktree`, `defaultBaseBranch`.
2. Run `ceiling-check`; if at ceiling, hand off to recombination (`skills/parallelism`) — do not fan out.
3. Provision via `scripts/worktree.sh provision`.
4. `cd` into the new worktree path; confirm state via `scripts/shipwright-state.sh read`.
5. Next step: `/sw-start` inside the worktree.

## Procedure (teardown)

1. Confirm no uncommitted work (or user approves discard).
2. `bash scripts/worktree.sh teardown <name>` — never `rm` the directory.
3. Report disk reclaimed from script output.

**Communication intensity:** ultra

## Guardrails

- Never implement in bare `main` — provision a worktree first.
- Teardown is `git worktree remove` + `prune` only.
- Does not commit, push, open PRs, or merge.
