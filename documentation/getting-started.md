# Getting started with Shipwright

Shipwright is a Cursor and Claude Code plugin that structures agentic development: traceable specs, a gated
ship loop, and compounding memory.

**Start here:** [README](../README.md) for prerequisites, installation (Cursor and Claude Code), `/sw-setup`,
and expanded workstreams with sample prompts.

This guide covers three persona paths after setup, plus onboarding defaults for the doc → implementation boundary.

## Two places, two jobs

| Where | What you do |
|-------|-------------|
| **This machine (once)** | Clone Shipwright, run `./scripts/install.sh`, reload Cursor |
| **Each project repo** | Run `/sw-setup` (or zero-config memory markers) so commands know your providers and guardrails |

The plugin lives globally; configuration and artifacts live in the **target repository** you are building in.

## Prerequisites

See [README — Prerequisites](../README.md#prerequisites) for install-time tools (git, bash, rsync, Python 3,
`gh`). Optional integrations (CodeRabbit, Recallium, Sentry) are covered in
[plugin setup](../README.md#plugin-setup-and-configuration).

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

## Path 1: New feature (Standard or Full tier)

Use when scope spans multiple files or needs a written spec.

1. Install the plugin (see [README](../README.md#install)).
2. Open your **target repo** in Cursor and run `/sw-setup`.
3. Run `/sw-doc` — triage classifies tier; Full tier includes brainstorm before PRD.
4. After frozen tasks exist, respond to the `doc.afterTasks` checkpoint (or use `auto` mode).
5. Run `/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` to orchestrate all remaining phases to one
   terminal merge gate — or `/sw-worktree provision` then `/sw-start` and `/sw-ship` per phase manually.
6. When `/sw-ready` reports merge-ready on the terminal PR, merge manually.

## Path 2: Quick fix (Quick tier)

Use for bounded, low-risk changes that skip the doc pipeline.

1. Install the plugin and ensure target repo has `/sw-setup` or zero-config memory.
2. Run `/sw-triage` — expect **Quick** for 0–1 file scope without risk keywords.
3. Run `/sw-worktree provision` → `/sw-start` with prefix `fix/`.
4. Run `/sw-execute` for the slice, then `/sw-ship` (or atomic commit → pr → stabilize).

**Done when:** Small PR is green; merge manually.

Quick tier **does not** enter `/sw-doc` — no brainstorm, PRD, or task freeze.

## Path 3: Production incident

Use when a production signal (Sentry, deploy log, user report) needs diagnosis.

1. In the target repo, run `/sw-feedback` with the signal (or `/sw-debug` directly).
2. `/sw-feedback` normalizes and routes — confirm the suggested route before dispatch.
3. `/sw-debug` runs RCA and routes: small fix → worktree + `/sw-ship`; large fix → `/sw-amend` or `/sw-brainstorm`.

**Done when:** Fix is shipped and `/sw-feedback-close` closes the signal (if tracked).

## Post-merge

After you merge, run `/sw-compound-ship` in the target repo to capture retro learnings and sync memory.

## Migration notes

### Duplicate plugins

Remove other workflow plugin directories under `~/.cursor/plugins/local/` before installing Shipwright.
Duplicate installs can surface two commands with the same `sw-` name.

### From compound-engineering (`ce-`)

Shipwright uses the `sw-` prefix exclusively. Remove co-installed workflow plugins that register overlapping
commands. Shipwright orchestrators (`/sw-doc`, `/sw-ship`, `/sw-debug`,
`/sw-feedback`) replace ad-hoc chains; see [commands.md](commands.md) for the full taxonomy.

## Next steps

- [README — Workstreams](../README.md#workstreams) — use cases, sample prompts, command tables
- [Command reference](commands.md) — full taxonomy
- [CONTRIBUTING.md](../CONTRIBUTING.md) — developing Shipwright itself
