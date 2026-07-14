# Getting started with Shipwright

Shipwright is a Cursor and Claude Code plugin that structures agentic development: traceable specs,
a gated ship loop, and compounding memory.

**Start here:** [README](../../README.md) for prerequisites, installation, `/sw-init`, and the lifecycle
overview. Style and structure conventions live in the [style guide](style-guide.md). Coined terms are in
the [glossary](glossary.md). Unsure which command to run? Use the [decision tree](decision-tree.md).

## Positioning

| Need | Shipwright | Ad-hoc agent chat |
|------|------------|-------------------|
| Spec → tasks → merge gate | Frozen task lists and `/sw-deliver` | Easy to lose the thread |
| Isolation | Linked worktrees; no bare-`main` implementation | Easy to commit on the wrong branch |
| CI truth | Deterministic check-gate before “ready” | Easy to declare green early |
| Memory | Provider-routed, redacted writes | Easy to paste secrets into chat history |

Shipwright optimizes for **repeatable delivery**, not for skipping human merge judgment.

## Adoption arc

### First session

1. Install the plugin (`python3 scripts/install.py` from the Shipwright clone; reload the editor).
2. In your **project** repo, run `/sw-init` and accept defaults unless you already know your providers.
3. Run a small loop: `/sw-doc` on a tiny idea **or** open an existing frozen task list with
   `/sw-deliver run <path-or-unit>`.
4. Stop at the merge gate—do not force-merge to the default branch from the agent.

### Week two

1. Prefer `/sw-deliver run` for multi-phase work instead of manually chaining `/sw-ship`.
2. Tune only what hurts: `deliver.autonomy`, `review.provider`, memory provider—see
   [configuration](configuration.md).
3. After merges, let `/sw-cleanup` dry-run, then confirm removals.
4. Skim [workflows](workflows.md) for the doc → deliver → ship path you actually use.

### After a month

1. Use issue-store or file-store planning deliberately (configuration guide).
2. Rely on `/sw-status` and living planning indexes instead of tribal chat summary.
3. Route production signals through `/sw-feedback` / `/sw-debug` rather than patching on `main`.
4. Keep user docs free of internal planning IDs ([style guide](style-guide.md)).

## Two places, two jobs

| Where | What you do |
|-------|-------------|
| **This machine (once)** | Clone Shipwright, run `python3 scripts/install.py`, reload your editor |
| **Each project repo** | Run `/sw-init` so commands know your providers, verify commands, memory store, and guardrails |

The plugin lives globally; configuration and artifacts live in the **target repository** you build in.
The installer never configures projects for you.

## Doc → implementation boundary (`doc.afterTasks`)

After `/sw-tasks` freezes the task list, `doc.afterTasks` controls what happens next (default **`confirm`**):

| Mode | Behavior |
|------|----------|
| `stop` | Halt after the frozen task list; print the docs-only seed command and `/sw-deliver run …`. |
| `confirm` | Show the task list and an **Implementation checkpoint**; require `proceed` or `yes`; then seed and deliver. |
| `auto` | Seed and dispatch `/sw-deliver run …` without a second prompt. |

Override per run: `/sw-doc --after-tasks=<mode>`.

## Agent-driven `/sw-cleanup`

After merge, `/sw-cleanup` enumerates merged branches and stale worktrees in **dry-run** mode. The agent
presents the `wouldRemove` set and asks you to confirm before applying removals. Declined or ambiguous
replies leave the dry-run report as-is.

## Worktree invariant

**No implementation files are written on bare `main`.** `/sw-deliver` provisions worktrees automatically.
For manual paths, use `/sw-worktree` and `/sw-start`. `scripts/sw-assert-worktree.py` enforces this at
implementation entry.

## Issue-store adopters

Opt-in via `planning.store.backend: issue-store` in `.cursor/workflow.config.json` (default unchanged).
Under issue-store, planning units and progress live in the issue provider; file-store users keep on-disk
planning trees. See [configuration](configuration.md) and [workflows](workflows.md).

## Single-pass `/sw-tasks`

`/sw-tasks` generates the **complete** frozen task list in one pass (phases, executable sub-tasks, and
traceability). Standalone, it outputs the list and stops without prompting for implementation.

## Review gating (canonical opt-out)

The schema default for `review.provider` is **`none`** (review gating off). CodeRabbit is **opt-in** —
set `review.provider: "coderabbit"` explicitly. The **canonical way to disable** external AI review is
`review.provider: "none"`.

## Deliver autonomy and living docs

- **`deliver.autonomy`** — default `autonomous`; runs `/sw-deliver` to the terminal gate without routine
  re-prompts. Set `supervised` for extra acknowledgement halts.
- **`legitimate.halt`** — only terminal default-branch merge, exhausted remediation, destructive git,
  configured checkpoints, phase timeout, external-wait exhaustion, or run-level budget.
- **Living-doc currency** — generated planning INDEX (`docs/planning/INDEX.md` derived region), legacy
  projections (`docs/prds/INDEX.md`, `GAP-BACKLOG.md`), and `COMPLETION-LOG.md` stay accurate via the
  maintenance reconciler on the feature branch; terminal merge is blocked on drift.
- **Frontmatter traceability** — Full-tier planning docs carry `brainstorm:`; `/sw-prd` and `/sw-freeze` enforce
  resolvable `brainstorm:` / `prd:` links.

## Plan policy (advanced)

`orchestration.planPolicy` defaults to `canonical`. The `proposed` path is pilot-only and refuses silent
opt-in toward shared `main`. See [configuration](configuration.md) and [workflows](workflows.md).

## Persona paths (after setup)

| Persona | Start with |
|---------|------------|
| Feature delivery | `/sw-doc` → freeze → `/sw-deliver run` |
| Quick fix on an existing branch | `/sw-ship` (still halts at merge) |
| Incident / production signal | `/sw-feedback` or `/sw-debug` |

## Next reading

- [Commands](commands.md) — orchestrators vs atomics
- [Workflows](workflows.md) — end-to-end paths
- [Configuration](configuration.md) — knobs including `delegation.mode`
- [Testing](testing.md) — verify and gate expectations
