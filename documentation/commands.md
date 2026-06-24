# Shipwright commands

Shipwright exposes `sw-` commands in Cursor and Claude Code. **Orchestrators** chain phases; **atomics** do one
bounded step. For full procedure text, open the linked command file under `core/commands/`.

## Orchestrators

| Command | Scope | Does not |
|---------|-------|----------|
| [`/sw-doc`](../core/commands/sw-doc.md) | Doc pipeline: triage → brainstorm (Full) → PRD → review → freeze → tasks | Implement, merge, or skip human gates |
| [`/sw-ship`](../core/commands/sw-ship.md) | Phase loop: execute → verify → review → commit → PR → CI → stabilize → ready | Merge (halts at merge gate) |
| [`/sw-debug`](../core/commands/sw-debug.md) | Production/dev RCA and route by fix size | Implement, commit, or merge |
| [`/sw-feedback`](../core/commands/sw-feedback.md) | Normalize inbound signals and route to debug, gaps, or brainstorm | Analyze, author, or dispatch without confirmation |
| [`/sw-compound-ship`](../core/commands/sw-compound-ship.md) | Post-merge: retro → compound → optional memory-sync | Merge or auto-promote rules |

## Entry points

| Command | When to use | Does not |
|---------|-------------|----------|
| [`/sw-triage`](../core/commands/sw-triage.md) | Classify Quick / Standard / Full before doc or impl | Draft docs or implement |
| [`/sw-setup`](../core/commands/sw-setup.md) | First run in a target repo — providers, memory store, doctor | Scaffold CI or migrate memories |
| [`/sw-worktree`](../core/commands/sw-worktree.md) | Isolate work in a per-item worktree | Run phase loop or merge |
| [`/sw-start`](../core/commands/sw-start.md) | Open a phase branch inside the active worktree | Push or open PR |

## Doc pipeline atomics

| Command | Role |
|---------|------|
| [`/sw-brainstorm`](../core/commands/sw-brainstorm.md) | Requirements exploration (Full tier) |
| [`/sw-prd`](../core/commands/sw-prd.md) | PRD or decision-record draft |
| [`/sw-doc-review`](../core/commands/sw-doc-review.md) | Persona panel on spec drafts |
| [`/sw-freeze`](../core/commands/sw-freeze.md) | Irreversible artifact freeze |
| [`/sw-tasks`](../core/commands/sw-tasks.md) | Task list from frozen PRD |
| [`/sw-amend`](../core/commands/sw-amend.md) | Post-freeze PRD amendment |

## Ship loop atomics (selected)

| Command | Role |
|---------|------|
| [`/sw-execute`](../core/commands/sw-execute.md) | One phase-sized implementation slice |
| [`/sw-verify`](../core/commands/sw-verify.md) | Scoped local verification |
| [`/sw-review`](../core/commands/sw-review.md) | Local then provider code review |
| [`/sw-commit`](../core/commands/sw-commit.md) | Commit after verify + review |
| [`/sw-pr`](../core/commands/sw-pr.md) | Push and open/update PR |
| [`/sw-watch-ci`](../core/commands/sw-watch-ci.md) | Poll PR checks |
| [`/sw-stabilize`](../core/commands/sw-stabilize.md) | Clear CI + review blockers |
| [`/sw-ready`](../core/commands/sw-ready.md) | Terminal readiness report |

## Memory and compounding

| Command | Role |
|---------|------|
| [`/sw-memory-sync`](../core/commands/sw-memory-sync.md) | Distill transcript deltas to durable memory |
| [`/sw-memory-audit`](../core/commands/sw-memory-audit.md) | Read-only memory hygiene audit |
| [`/sw-compound`](../core/commands/sw-compound.md) | Distill retro into memories |
| [`/sw-retro`](../core/commands/sw-retro.md) | Post-ship retrospective (report-only) |

> **Depth:** 34 commands exist today. This table lists orchestrators and common atomics only. Grep
> `core/commands/sw-*.md` for the complete set.
