# Shipwright commands

Shipwright exposes `sw-` commands in Cursor and Claude Code. **Orchestrators** chain phases; **atomics** do one
bounded step. For full procedure text, open the linked command file under `core/commands/`.

## Orchestrators

| Command | Scope | Does not |
|---------|-------|----------|
| [`/sw-doc`](../core/commands/sw-doc.md) | Doc pipeline: triage → brainstorm (Full) → PRD → review → freeze → **single-pass** `/sw-tasks`; then `doc.afterTasks` (`stop` \| `confirm` \| `auto`) | Implement, merge, or skip human gates |
| [`/sw-deliver`](../core/commands/sw-deliver.md) | **Primary** implementation orchestrator — frozen task-list phase-mode or multi-feature wave | Bypass `/sw-ship`, auto-merge to `main`, or re-author frozen tasks |
| [`/sw-ship`](../core/commands/sw-ship.md) | **Manual** single-phase loop: execute → verify → review → commit → PR → CI → stabilize → ready; also runs **inside** each `/sw-deliver` phase | Merge (halts at merge gate) |
| [`/sw-debug`](../core/commands/sw-debug.md) | Production/dev RCA and route by fix size | Implement, commit, or merge |
| [`/sw-feedback`](../core/commands/sw-feedback.md) | Normalize inbound signals and route to debug, gaps, or brainstorm | Analyze, author, or dispatch without confirmation |
| [`/sw-compound-ship`](../core/commands/sw-compound-ship.md) | Post-merge: retro → compound → optional memory-sync | Merge or auto-promote rules |

### `/sw-deliver` — phase-mode and multi-feature

**Phase-mode (default after `/sw-doc`):**

```text
/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
```

- **Mode auto-detect:** `--task-list` → phase-mode; `--items`/`--edges` → multi-feature; both → halt.
- **Single terminal merge gate:** per-phase PRs auto-merge into `<type>/<slug>` on green; one human-gated
  `<type>/<slug> → main` PR at the end.
- **Resumption:** re-run `run` after interrupt; `plan --from <phase>` when resuming mid-wave.
- **Dry-run:** `scripts/wave.sh plan --task-list <path> --dry-run` — plan JSON only, no artifact write.

**Multi-feature mode:** `plan`/`run` with `--items` and `--edges`; integration surface at
`integration/<stamp>`; promotion via `promote` (human-gated).

See [`core/commands/sw-deliver.md`](../core/commands/sw-deliver.md) and [`skills/deliver/SKILL.md`](../core/skills/deliver/SKILL.md).

## Entry points

| Command | When to use | Does not |
|---------|-------------|----------|
| [`/sw-triage`](../core/commands/sw-triage.md) | Classify Quick / Standard / Full before doc or impl | Draft docs or implement |
| [`/sw-setup`](../core/commands/sw-setup.md) | First run in a target repo — providers, `doc.afterTasks`, memory store, doctor | Scaffold CI or migrate memories |
| [`/sw-worktree`](../core/commands/sw-worktree.md) | Isolate work in a per-item worktree (required before impl on bare `main`) | Run phase loop or merge |
| [`/sw-start`](../core/commands/sw-start.md) | Open a phase branch inside the active worktree; worktree guard runs before writes | Push or open PR |

## Doc pipeline atomics

| Command | Role |
|---------|------|
| [`/sw-brainstorm`](../core/commands/sw-brainstorm.md) | Requirements exploration (Full tier) |
| [`/sw-prd`](../core/commands/sw-prd.md) | PRD or decision-record draft |
| [`/sw-doc-review`](../core/commands/sw-doc-review.md) | Persona panel on spec drafts |
| [`/sw-freeze`](../core/commands/sw-freeze.md) | Irreversible artifact freeze |
| [`/sw-tasks`](../core/commands/sw-tasks.md) | Complete frozen task list in **one pass** (no Go gate); standalone run stops without implementation prompt |
| [`/sw-amend`](../core/commands/sw-amend.md) | Post-freeze PRD amendment |

`doc.afterTasks` is the sole human checkpoint between PRD freeze and implementation when using `/sw-doc`.

## Ship loop atomics (selected)

These commands compose the **single-phase** ship loop. In normal use you invoke **`/sw-deliver run`** instead —
it dispatches this chain per phase automatically. Use the atomics directly for Quick-tier hotfixes, debugging one
phase, or when you deliberately skip the orchestrator.

| Command | Role |
|---------|------|
| [`/sw-execute`](../core/commands/sw-execute.md) | One phase-sized implementation slice; worktree guard before writes |
| [`/sw-verify`](../core/commands/sw-verify.md) | Scoped local verification |
| [`/sw-review`](../core/commands/sw-review.md) | Local then provider code review (`review.provider`; default **`none`**) |
| [`/sw-commit`](../core/commands/sw-commit.md) | Commit after verify + review |
| [`/sw-pr`](../core/commands/sw-pr.md) | Push and open/update PR |
| [`/sw-watch-ci`](../core/commands/sw-watch-ci.md) | Poll PR checks via `check-gate.sh` |
| [`/sw-stabilize`](../core/commands/sw-stabilize.md) | Clear CI + review blockers |
| [`/sw-ready`](../core/commands/sw-ready.md) | Terminal readiness report; echoes `review: off` or `review: not configured` from gate JSON |

**Worktree invariant:** never write implementation files on bare `main` — use a worktree + phase branch.

## Review providers

- **Default:** `review.provider: "none"` — review gating off; CI can still pass without external review.
- **Opt-in:** `review.provider: "coderabbit"` — enable CodeRabbit for phase-2 `/sw-review` and CI review barrier.
- **Canonical opt-out:** `review.provider: "none"` (single supported disable path; `review.enabled: false` is deprecated).

## Memory and compounding

| Command | Role |
|---------|------|
| [`/sw-memory-sync`](../core/commands/sw-memory-sync.md) | Distill transcript deltas to durable memory |
| [`/sw-memory-audit`](../core/commands/sw-memory-audit.md) | Read-only memory hygiene audit |
| [`/sw-compound`](../core/commands/sw-compound.md) | Distill retro into memories |
| [`/sw-retro`](../core/commands/sw-retro.md) | Post-ship retrospective (report-only) |

> **Depth:** 34 commands exist today. This table lists orchestrators and common atomics only. Grep
> `core/commands/sw-*.md` for the complete set.

See [Getting started](getting-started.md) for boundary modes and worktree rules.
