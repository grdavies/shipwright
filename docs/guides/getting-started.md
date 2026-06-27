# Getting started with Shipwright

Shipwright is a Cursor and Claude Code plugin that structures agentic development: traceable specs,
a gated ship loop, and compounding memory.

**Start here:** [README](../../README.md) for prerequisites, installation (Cursor and Claude Code),
configuration via `/sw-init`, and the lifecycle overview.

This guide covers three persona paths after setup, plus the key invariants that govern all workflows.

## Two places, two jobs

| Where | What you do |
|-------|-------------|
| **This machine (once)** | Clone Shipwright, run `./scripts/install.sh`, reload your editor |
| **Each project repo** | Run `/sw-init` so commands know your providers, verify commands, memory store, and guardrails |

The plugin lives globally; configuration and artifacts live in the **target repository** you build in.
Running `install.sh` inside a git repo prints an opt-in reminder to run `/sw-init` for that repo only —
the installer never configures projects for you.

## Doc → implementation boundary (`doc.afterTasks`)

After `/sw-tasks` freezes the task list, `doc.afterTasks` controls what happens next (default **`confirm`**):

| Mode | Behavior |
|------|----------|
| `stop` | Halt after the frozen task list (print-only); print the docs-only seed command onto `<type>/<slug>` and `/sw-deliver run <frozen-tasks>`. |
| `confirm` | Show the full task list, then a dedicated **Implementation checkpoint** block (heading + direct question + paused-state line); require `proceed` or `yes`; seed frozen spec onto `<type>/<slug>`; dispatch `/sw-deliver run <frozen-tasks>`. Unrelated messages while pending re-emit the checkpoint — nothing dispatches until you ack. |
| `auto` | Seed frozen spec onto `<type>/<slug>` and dispatch `/sw-deliver run <frozen-tasks>` without a second prompt. |

Override per run: `/sw-doc --after-tasks=<mode>` or `/sw-deliver run` at the frozen-task-list boundary.

## Agent-driven `/sw-cleanup`

After merge, `/sw-cleanup` enumerates merged branches and stale worktrees in **dry-run** mode. The agent
presents the `wouldRemove` set and asks you to confirm before applying removals; on explicit ack it runs
`bash scripts/cleanup.sh --confirm --yes` for you. Declined or ambiguous replies leave the dry-run report
as-is — use the manual escape hatch if you prefer to apply yourself.

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

`/sw-init` writes these defaults; `/sw-ready` and `/sw-status` echo `review: off` from the CI gate
when reporting merge readiness.

## Deliver autonomy and living docs (PRD 009)

- **`deliver.autonomy`** — default `autonomous`; runs `/sw-deliver` to the terminal gate without routine
  re-prompts. Set `supervised` for extra acknowledgement halts.
- **Legitimate halts** — only terminal `main` merge, exhausted remediation, destructive git, configured
  checkpoints, phase timeout, external-wait exhaustion, or run-level budget.
- **Living-doc currency** — `INDEX.md`, `COMPLETION-LOG.md`, and `GAP-BACKLOG.md` stay accurate on the
  feature branch; terminal merge is blocked on drift.
- **Frontmatter traceability** — Full-tier PRDs carry `brainstorm:`; `/sw-prd` and `/sw-freeze` enforce
  resolvable `brainstorm:` / `prd:` links.

## Orchestration plan policy (PRD 022 — default canonical)

`/sw-init` seeds `orchestration.planPolicy: canonical`. With this default, deliver and ship behavior is
**byte-identical** to pre-022 — no plan proposals, no observable change. Opt-in `proposed` (after PRD-023
pilot) lets agents propose step plans and wave batching within validated guidelines; rejections fall back to
the canonical chain automatically. See [workflows](workflows.md#orchestration-plan-policy-prd-022) and
[configuration](configuration.md#orchestration-plan-policy-orchestrationplanpolicy).

## Path 1: New feature (Standard or Full tier)

Use when scope spans multiple files or needs a written spec.

1. Install the plugin (see [README](../../README.md#install)).
2. Open your **target repo** and run `/sw-init`.
3. Run `/sw-doc` — triage classifies tier; Full tier includes brainstorm before PRD.
4. Respond to the **Implementation checkpoint** after frozen tasks — reply `proceed` or `yes` (or use
   `auto` mode to skip the prompt). `/sw-doc` dispatches **`/sw-deliver run <frozen-task-list-path>`**
   on ack; you do not need to type the command yourself when using `confirm`/`auto`.
5. When using `stop` mode, run **`/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md`** yourself —
   orchestrates all phases to one terminal merge gate.
6. Merge the terminal PR when `/sw-ready` reports merge-ready.

**Manual alternative:** `/sw-worktree provision` → `/sw-start` → `/sw-ship` per phase.

## Path 2: Quick fix (Quick tier)

Use for bounded, low-risk changes that skip the doc pipeline. **No frozen task list** — `/sw-deliver`
does not apply; use the manual `/sw-ship` atomics directly.

1. Install the plugin and ensure target repo has `/sw-init` or zero-config memory.
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
merged branches and stale worktrees. **`/sw-cleanup` is dry-run by default** — the agent presents the
`wouldRemove` set and asks you to confirm; on explicit ack it runs the apply step for you (or you can
use the manual `bash scripts/cleanup.sh --confirm --yes` escape hatch).

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
- [Configuration](configuration.md) — `/sw-init` walkthrough and every config key
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — developing Shipwright itself
