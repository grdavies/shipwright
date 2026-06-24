# Getting started with Shipwright

Shipwright is a multi-platform (`sw-`) workflow plugin for Cursor and Claude Code. This guide covers
first-run setup and the doc → implementation boundary introduced in the onboarding UX workstream.

## Quick start

1. Install the plugin (`./scripts/install.sh` from the repo, or use committed `dist/cursor/`).
2. In your **target repo**, run `/sw-setup` to scaffold `.cursor/workflow.config.json` (or commit the
   zero-config in-repo memory marker — see [README](../README.md)).
3. Provision a **worktree** before implementation: `/sw-worktree` then `/sw-start` on a phase branch.
4. Run the doc pipeline: `/sw-doc` (or atomic `/sw-brainstorm` → `/sw-prd` → `/sw-freeze` → `/sw-tasks`).

## Doc → implementation boundary (`doc.afterTasks`)

After `/sw-tasks` freezes the task list, `doc.afterTasks` controls what happens next (default **`confirm`**):

| Mode | Behavior |
|------|----------|
| `stop` | Halt after the frozen task list; hand off to `/sw-worktree` + `/sw-start` manually. |
| `confirm` | Show the full task list; require `proceed` or `yes` before dispatching implementation. |
| `auto` | Provision a worktree/branch and dispatch the implementation loop without a second prompt. |

Override per run: `/sw-doc --after-tasks=<mode>` or `/sw-ship --after-tasks=<mode>` at the frozen-task-list
boundary.

## Worktree invariant

**No implementation files are written on bare `main`.** Use a linked worktree and phase branch (`/sw-worktree`,
`/sw-start`). `scripts/sw-assert-worktree.sh` enforces this at implementation entry (`/sw-execute`, `/sw-start`).

## Single-pass `/sw-tasks`

`/sw-tasks` generates the **complete** frozen task list in one pass (parent phases, executable sub-tasks, and
`## Traceability`) — there is no "Go" gate or mid-generation pause. Run standalone, it outputs the list and stops
without prompting for implementation.

## Review gating (default off)

The schema default for `review.provider` is **`none`** (review gating off). CodeRabbit is **opt-in** — set
`review.provider: "coderabbit"` explicitly to enable external review. The canonical opt-out is
`review.provider: "none"` (not a separate `disabled` flag; `review.enabled: false` is deprecated).

`/sw-setup` writes these defaults; `/sw-ready` and `/sw-status` echo `review: off` or `review: not configured`
from the CI gate when reporting merge readiness.

## Next steps

- [Commands reference](commands.md) — orchestrators and atomic `sw-` commands.
- [README](../README.md) — install, config keys, development workflow.
