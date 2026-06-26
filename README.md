# Shipwright

[![version](https://img.shields.io/badge/version-1.2.2-blue)](version.txt)
[![license](https://img.shields.io/badge/license-MIT-green)](#license)
[![editors](https://img.shields.io/badge/Cursor-%26%20Claude%20Code-black)](#install)

**A gated agentic dev lifecycle for Cursor and Claude Code.** Traceable specs, a verify → review →
ship loop, and compounding memory — all driven by `sw-` commands.

Orchestrators advance on green and **halt at human gates** (freeze, merge, feedback routing).
Shipwright **never auto-merges**.

- **Traceable specs** — frozen PRDs, tasks, and amendments live in your repo
- **Gated ship loop** — verify, review, CI truth, stabilize; *you* merge
- **Compounding memory** — post-ship retro and durable project learnings

```mermaid
flowchart LR
  DOC["1 · Document<br/>/sw-doc"] --> SHIP["2 · Implement<br/>/sw-deliver"]
  SHIP --> MERGE([You merge — only human gate])
  MERGE --> COMPOUND["3 · Compound<br/>/sw-compound-ship"]
  OPS["Debug & feedback<br/>/sw-debug · /sw-feedback"] -.-> DOC
  COMPOUND -.->|learnings| DOC
```

> New here? Read **[Getting started](docs/guides/getting-started.md)** for guided persona paths, or
> jump to the deep-dive **[workflow guide](docs/guides/workflows.md)**.

## Prerequisites

Check you have the essentials:

```bash
git --version && bash --version && rsync --version && gh --version
```

- [x] **git**, **bash**, **rsync** — clone, run `scripts/install.sh`, copy the plugin tree
- [x] **GitHub CLI (`gh`)** — `/sw-pr`, `/sw-watch-ci`, PR blocker flows (run `gh auth login`)
- [ ] **Python 3** — only for developing Shipwright (`python3 -m sw generate`; see [CONTRIBUTING.md](CONTRIBUTING.md))

## Install

Shipwright installs **once per machine**; you configure it **per project repo**. Once installed,
`sw-` commands appear in the palette (e.g. `/sw-init`, `/sw-doc`).

<details open>
<summary><b>Cursor</b></summary>

```bash
git clone https://github.com/grdavies/shipwright
cd shipwright
./scripts/install.sh          # copies dist/cursor/ → ~/.cursor/plugins/local/shipwright
```

Run **Developer: Reload Window** in Cursor. Override the destination:
`./scripts/install.sh /path/to/dest`.
</details>

<details>
<summary><b>Claude Code</b></summary>

```bash
git clone https://github.com/grdavies/shipwright
cd shipwright
```

Point your Claude Code plugin path at `<shipwright-repo>/dist/claude-code/`, or copy that tree into
your Claude plugins directory per Claude Code docs. Reload Claude Code.
</details>

## Configuration

Install the plugin **once per machine**; configure it **per project repo** with **`/sw-init`**
(`/sw-setup` is a deprecated alias with identical behavior).

Open your **target project repo** and run **`/sw-init`**. It walks through project setup and writes
`.cursor/workflow.config.json`:

1. **Memory provider** — `in-repo` (default, committed markdown store) or `recallium` (external
   REST store). For in-repo, choose `committed` (PR-reviewable) or `local` (gitignored).
2. **Review provider** — `none` (default) or `coderabbit` (opt-in AI review on PRs).
3. **Project type + verify** — detects manifests at repo root and proposes real `verify.*` commands
   from fixed presets (never vacuous placeholders).
4. **Doc→implementation boundary** (`doc.afterTasks`) — `confirm` (default) · `stop` · `auto`.
5. **Guardrails** — `enforceBeforeSubmit` (default on) and `requireRuleClass` (default off).
6. **Model tier defaults** — four-tier `models` block plus per-command routing from bundled defaults.

Re-run `/sw-init` at any time — it acts as a **doctor** against an existing config, surfaces
**version drift** (`configuredWith` stamp vs installed plugin), and offers consent-gated refresh.

**Base branch:** workflow entry captures your trunk base (name + SHA) before worktrees are created;
terminal PRs target that persisted base — not a hardcoded `main`. See [configuration](docs/guides/configuration.md#base-branch).

**Worktree invariant:** implementation never starts on bare trunk — use `/sw-worktree` and a feature branch.
**Review:** `review.provider` defaults to **`none`**; CodeRabbit is opt-in.

Configure `verify.lint` / `verify.typecheck` / `verify.test` so `/sw-verify` runs real checks.
Full walkthrough and schema: **[configuration](docs/guides/configuration.md)**.

### Deliver autonomy (PRD 009)

`/sw-deliver` runs an **autonomous conductor** by default (`deliver.autonomy.mode: autonomous`): it
self-continues through phase dispatch, merge, and bookkeeping without per-step re-prompts. The **legitimate halt** set is minimal — terminal merge to `main`, exhausted remediation, destructive/ambiguous git,
checkpoints (`doc.afterTasks`, supervised mode), phase timeout, external-wait exhaustion, or run-level
budget (`deliver.autonomy.maxRunMinutes` / `maxIterations`). Parallel phases dispatch within
`worktree.parallelCeiling` when the plan allows.

**Living-doc currency:** `docs/prds/INDEX.md`, `COMPLETION-LOG.md`, and `GAP-BACKLOG.md` reconcile
in-loop on the feature branch; drift hard-blocks the terminal gate.

**Doc traceability:** Full-tier PRDs carry `brainstorm:` frontmatter; writable brainstorms gain `prd:`
back-links at draft/freeze time.

## First run

1. **`/sw-doc`** — triage → (brainstorm) → PRD → review → freeze → tasks.
2. **`/sw-deliver run <frozen-tasks>`** — drives every phase to one merge gate; **you merge**.

Quick fixes skip the doc pipeline — see [Getting started](docs/guides/getting-started.md).

## Workstreams

Four lifecycle workstreams sit on the foundation. Each has an **orchestrator** that chains atomic
`sw-` commands; every atomic stays independently runnable.

| Workstream | Orchestrator | Chain | Does not |
|------------|--------------|-------|----------|
| **Document** | `/sw-doc` | triage → brainstorm (Full) → PRD → review → freeze → tasks | implement or merge |
| **Implement** | `/sw-deliver` | `run` → per-phase `/sw-ship` → auto-merge → terminal PR → main | bypass `/sw-ship` or auto-merge to `main` |
| **Debug** | `/sw-debug` | triage signal → RCA → route by fix size | implement or merge |
| **Feedback** | `/sw-feedback` | normalize + redact → route to debug / gaps / brainstorm | analyze or dispatch without confirmation |

**`/sw-deliver` is the default implementation path** once `/sw-doc` produces a frozen task list — the
"play button" that drives every phase of a feature to one human merge gate. Mode auto-detect picks
phase-mode from `--task-list` vs multi-feature from `--items`/`--edges`. Use `--dry-run` for plan-only
output; re-run `run` to **resume** after interrupt. Run the manual `/sw-ship`
atomics directly only for Quick-tier hotfixes, debugging, or single-phase reruns.

**`/sw-cleanup`** is a standalone maintenance utility — not a workstream. After `/sw-deliver` detects
the feature branch has merged it suggests a cleanup run; you confirm before any deletion. Prunes merged
local and remote branches, stale worktrees, and completed deliver run-state. Dry-run by default.

→ Full per-tier flows, diagrams, and sample prompts: **[workflow guide](docs/guides/workflows.md)**.

## Tiers

`/sw-triage` scores work deterministically; `/sw-doc` respects the result.

| | **Quick** | **Standard** | **Full** |
|---|-----------|--------------|----------|
| **Scope** | 0–1 files, low risk | 2–5 files, bounded | 6+ files or ambiguous |
| **Docs** | skipped | PRD → freeze → tasks | brainstorm → PRD → freeze → tasks |
| **Entry** | manual `/sw-ship` | `/sw-deliver run` | `/sw-deliver run` |

**Risk floor:** `auth`, `payment`, `migration`, `webhook` force at least Standard. **Ambiguity bump:**
`maybe`, `explore`, `TBD` push a tier up. Details in the [workflow guide](docs/guides/workflows.md).

## Learn more

| Doc | Audience |
|-----|----------|
| [Getting started](docs/guides/getting-started.md) | First run + persona quick paths |
| [Workflow guide](docs/guides/workflows.md) | Tiers, per-workstream flows, diagrams, prompts |
| [Commands](docs/guides/commands.md) | Full command taxonomy |
| [Configuration](docs/guides/configuration.md) | `/sw-init` + every config key |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Developing the plugin |
| [PROVENANCE.md](PROVENANCE.md) | Upstream sources |

## Acknowledgements

Shipwright builds on ideas and patterns from several open-source projects. We're grateful to their
authors and contributors.

| Project | Role in Shipwright | Repo |
|---------|-------------------|------|
| **compound-engineering** | Persona panel doc review, brainstorm dialogue, retro/compounding chain, and debug RCA patterns — adapted and integrated throughout the documentation and implementation workstreams | [everyinc/compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) |
| **caveman** | Ultra-compressed communication mode that powers Shipwright's token-efficient orchestration chat (lite → full → ultra intensity levels) | [juliusbrussee/caveman](https://github.com/juliusbrussee/caveman) |

The compound-engineering plugin in particular gave Shipwright its doc-review persona panel, the
one-question-at-a-time brainstorm dialogue, and the retro → compound → memory-sync chain. Those
foundations let us focus on the durable delivery loop and gating mechanics rather than rebuilding
from scratch. Thank you.

## License

MIT
