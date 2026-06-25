# Getting started with Shipwright

Shipwright is a Cursor and Claude Code plugin that structures agentic development: traceable specs,
a gated ship loop, and compounding memory.

**Start here:** [README](../../README.md) for prerequisites, installation (Cursor and Claude Code),
configuration via `/sw-setup`, and the lifecycle overview.

This guide covers three persona paths after setup, plus the key invariants that govern all workflows.

## Two places, two jobs

| Where | What you do |
|-------|-------------|
| **This machine (once)** | Clone Shipwright, run `./scripts/install.sh`, reload your editor |
| **Each project repo** | Run `/sw-setup` so commands know your providers, memory store, and guardrails |

The plugin lives globally; configuration and artifacts live in the **target repository** you build in.

## Doc → implementation boundary (`doc.afterTasks`)

After `/sw-tasks` freezes the task list, `doc.afterTasks` controls what happens next (default **`confirm`**):

| Mode | Behavior |
|------|----------|
| `stop` | Halt after the frozen task list (print-only); print the docs-only seed command onto `<type>/<slug>` and `/sw-deliver run <frozen-tasks>`. |
| `confirm` | Show the full task list; require `proceed` or `yes`; seed frozen spec onto `<type>/<slug>`; dispatch `/sw-deliver run <frozen-tasks>`. |
| `auto` | Seed frozen spec onto `<type>/<slug>` and dispatch `/sw-deliver run <frozen-tasks>` without a second prompt. |

Override per run: `/sw-doc --after-tasks=<mode>` or `/sw-deliver run` at the frozen-task-list boundary.

## Worktree invariant

**No implementation files are written on bare `main`.** `/sw-deliver` provisions worktrees
automatically. For manual paths, use a linked worktree and phase branch (`/sw-worktree`, `/sw-start`).
`scripts/sw-assert-worktree.sh` enforces this at implementation entry.

## Single-pass `/sw-tasks`

`/sw-tasks` generates the **complete** frozen task list in one pass (parent phases, executable
sub-tasks, and `## Traceability`) — there is no "Go" gate or mid-generation pause. Run standalone,
it outputs the list and stops without prompting for implementation.

## Review gating (default off)

The schema default for `review.provider` is **`none`** (review gating off). CodeRabbit is **opt-in**
— set `review.provider: "coderabbit"` explicitly to enable external review on PRs. The **canonical way to disable** external AI review is `review.provider: "none"`.

`/sw-setup` writes these defaults; `/sw-ready` and `/sw-status` echo `review: off` from the CI gate
when reporting merge readiness.

## Path 1: New feature (Standard or Full tier)

Use when scope spans multiple files or needs a written spec.

1. Install the plugin (see [README](../../README.md#install)).
2. Open your **target repo** and run `/sw-setup`.
3. Run `/sw-doc` — triage classifies tier; Full tier includes brainstorm before PRD.
4. Respond to the `doc.afterTasks` checkpoint after frozen tasks (or use `auto` mode).
5. Run **`/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md`** — orchestrates all phases to
   one terminal merge gate.
6. Merge the terminal PR when `/sw-ready` reports merge-ready.

**Manual alternative:** `/sw-worktree provision` → `/sw-start` → `/sw-ship` per phase.

## Path 2: Quick fix (Quick tier)

Use for bounded, low-risk changes that skip the doc pipeline. **No frozen task list** — `/sw-deliver`
does not apply; use the manual `/sw-ship` atomics directly.

1. Install the plugin and ensure target repo has `/sw-setup` or zero-config memory.
2. Run `/sw-triage` — expect **Quick** for 0–1 file scope without risk keywords.
3. Run `/sw-worktree provision` → `/sw-start` with prefix `fix/`.
4. Run `/sw-execute` for the slice, then `/sw-ship` (or atomic commit → pr → stabilize).

**Done when:** small PR is green; merge manually.

Quick tier **does not** enter `/sw-doc` — no brainstorm, PRD, or task freeze.

## Path 3: Production incident

Use when a production signal (Sentry, deploy log, user report) needs diagnosis.

1. In the target repo, run `/sw-feedback` with the signal (or `/sw-debug` directly).
2. `/sw-feedback` normalizes and routes — confirm the suggested route before dispatch.
3. `/sw-debug` runs RCA and routes: small fix → worktree + `/sw-ship`; large fix → `/sw-amend` or
   `/sw-brainstorm`.

**Done when:** fix is shipped and `/sw-feedback-close` closes the signal (if tracked).

## Post-merge

After you merge, run `/sw-compound-ship` in the target repo to capture retro learnings and sync
memory. When `/sw-deliver` detects the feature branch has merged, it suggests `/sw-cleanup` to prune
merged branches and stale worktrees (dry-run by default — confirm before deleting).

## Migration notes

### Duplicate plugins

Remove other workflow plugin directories under `~/.cursor/plugins/local/` before installing
Shipwright. Duplicate installs can surface two commands with the same `sw-` name.

### From compound-engineering (`ce-`)

Shipwright uses the `sw-` prefix exclusively. Remove co-installed workflow plugins that register
overlapping commands. Shipwright orchestrators (`/sw-doc`, `/sw-deliver`, `/sw-ship`, `/sw-debug`,
`/sw-feedback`) replace ad-hoc chains; see [commands](commands.md) for the full taxonomy.

## Next steps

- [Workflow guide](workflows.md) — tiers, per-workstream flows, all diagrams, sample prompts
- [Command reference](commands.md) — full taxonomy
- [Configuration](configuration.md) — `/sw-setup` walkthrough and every config key
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — developing Shipwright itself
