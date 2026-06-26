# Shipwright commands

Shipwright exposes `sw-` commands in Cursor and Claude Code. **Orchestrators** chain phases;
**atomics** do one bounded step. For full procedure text, open the linked command file under
`core/commands/`.

## Orchestrators

| Command | Scope | Does not |
|---------|-------|----------|
| [`/sw-doc`](../../core/commands/sw-doc.md) | Doc pipeline: triage → brainstorm (Full) → PRD → review → freeze → **single-pass** `/sw-tasks`; then `doc.afterTasks` (`stop` \| `confirm` \| `auto`) | Implement, merge, or skip human gates |
| [`/sw-deliver`](../../core/commands/sw-deliver.md) | **Primary** implementation orchestrator — frozen task-list phase-mode or multi-feature wave | Bypass `/sw-ship`, auto-merge to `main`, or re-author frozen tasks |
| [`/sw-ship`](../../core/commands/sw-ship.md) | **Manual** single-phase loop: execute → verify → review → commit → PR → CI → stabilize → ready; also runs **inside** each `/sw-deliver` phase | Merge (halts at merge gate) |
| [`/sw-debug`](../../core/commands/sw-debug.md) | Production/dev RCA and route by fix size | Implement, commit, or merge |
| [`/sw-feedback`](../../core/commands/sw-feedback.md) | Normalize inbound signals and route to debug, gaps, or brainstorm | Analyze, author, or dispatch without confirmation |
| [`/sw-compound-ship`](../../core/commands/sw-compound-ship.md) | Pre-merge (in-loop) or post-merge: retro → compound → optional memory-sync | Merge or auto-promote rules |
| [`/sw-cleanup`](../../core/commands/sw-cleanup.md) | Dry-run default cleanup of merged branches, stale worktrees, completed run-state; agent asks for confirm before apply | Delete without confirm or drop in-flight runs |

### `/sw-deliver` — phase-mode and multi-feature

**Phase-mode (default after `/sw-doc`):**

```text
/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
```

- **Mode auto-detect:** `--task-list` → phase-mode; `--items`/`--edges` → multi-feature; both → halt.
- **Single terminal merge gate:** per-phase PRs auto-merge into `<type>/<slug>` on green; one
  human-gated `<type>/<slug> → main` PR at the end.
- **Resumption:** re-run `run` after interrupt; durable `deliver-loop` cursor in
  `.cursor/sw-deliver-state.json`; `plan --from <phase>` when resuming mid-wave.
- **Pre-merge compounding:** full `/sw-compound-ship --pre-merge` before the terminal human merge gate;
  completion stays `completed-pending-merge` until merge is detected.
- **Dry-run:** `scripts/wave.sh plan --task-list <path> --dry-run` — plan JSON only, no artifact write.

**Autonomy (PRD 009):** default `deliver.autonomy.mode: autonomous` — conductor in-turn loop to terminal
gate. **Legitimate halts** only (see [`configuration.md`](configuration.md)). Parallel phases when the
plan allows; outcomes from durable `status.json` only.

**Living-doc currency:** INDEX / COMPLETION-LOG / GAP-BACKLOG reconcile in-loop; `docs-currency` blocks
terminal merge on drift.

**Frontmatter:** Full-tier PRDs require `brainstorm:`; `/sw-freeze` verifies linkage.

**Multi-feature mode:** `plan`/`run` with `--items` and `--edges`; integration surface at
`integration/<stamp>`; promotion via `promote` (human-gated).

See [`core/commands/sw-deliver.md`](../../core/commands/sw-deliver.md) and
[`core/skills/deliver/SKILL.md`](../../core/skills/deliver/SKILL.md).

**Push safety:** workflow pushes route through `scripts/git-push.sh` → `scripts/secret-scan.sh`
before `git push` (including `sw-pr` and stabilize re-pushes).

## Entry points

| Command | When to use | Does not |
|---------|-------------|----------|
| [`/sw-triage`](../../core/commands/sw-triage.md) | Classify Quick / Standard / Full before doc or impl | Draft docs or implement |
| [`/sw-setup`](../../core/commands/sw-setup.md) | First run in a target repo — providers, `doc.afterTasks`, memory store, doctor | Scaffold CI or migrate memories |
| [`/sw-worktree`](../../core/commands/sw-worktree.md) | Isolate work in a per-item worktree (required before impl on bare `main`) | Run phase loop or merge |
| [`/sw-start`](../../core/commands/sw-start.md) | Open a phase branch inside the active worktree; worktree guard runs before writes | Push or open PR |

## Doc pipeline atomics

| Command | Role |
|---------|------|
| [`/sw-brainstorm`](../../core/commands/sw-brainstorm.md) | Requirements exploration (Full tier) |
| [`/sw-prd`](../../core/commands/sw-prd.md) | PRD or decision-record draft |
| [`/sw-doc-review`](../../core/commands/sw-doc-review.md) | Persona panel on spec drafts |
| [`/sw-freeze`](../../core/commands/sw-freeze.md) | Irreversible artifact freeze |
| [`/sw-tasks`](../../core/commands/sw-tasks.md) | Complete frozen task list in **one pass** (no Go gate); standalone run stops without implementation prompt |
| [`/sw-amend`](../../core/commands/sw-amend.md) | Post-freeze PRD amendment |

`doc.afterTasks` is the sole human checkpoint between PRD freeze and implementation when using
`/sw-doc`. In **`confirm`** mode, `/sw-doc` emits a dedicated **Implementation checkpoint** block
(heading + direct question + paused-state line) — only `proceed`/`yes` continues; unrelated messages
re-emit the checkpoint. On ack, `/sw-doc` dispatches **`/sw-deliver run <frozen-task-list-path>`**
(the primary post-freeze implementation entry).

## Ship loop atomics

These compose the **single-phase** ship loop. In normal use, invoke **`/sw-deliver run`** instead —
it dispatches this chain per phase automatically. Use the atomics directly for Quick-tier hotfixes,
debugging one phase, or when you deliberately skip the orchestrator.

| Command | Role |
|---------|------|
| [`/sw-execute`](../../core/commands/sw-execute.md) | One phase-sized implementation slice; worktree guard before writes |
| [`/sw-verify`](../../core/commands/sw-verify.md) | Scoped local verification |
| [`/sw-review`](../../core/commands/sw-review.md) | Local then provider code review (`review.provider`; default **`none`**) |
| [`/sw-commit`](../../core/commands/sw-commit.md) | Commit after verify + review |
| [`/sw-pr`](../../core/commands/sw-pr.md) | Push and open/update PR |
| [`/sw-watch-ci`](../../core/commands/sw-watch-ci.md) | Poll PR checks via `check-gate.sh` |
| [`/sw-stabilize`](../../core/commands/sw-stabilize.md) | Clear CI + review blockers |
| [`/sw-ready`](../../core/commands/sw-ready.md) | Terminal readiness report; echoes `review: off` or `review: not configured` from gate JSON |

**Worktree invariant:** never write implementation files on bare `main` — use a worktree + phase
branch.

## Memory and compounding

| Command | Role |
|---------|------|
| [`/sw-memory-sync`](../../core/commands/sw-memory-sync.md) | Distill transcript deltas to durable memory |
| [`/sw-memory-audit`](../../core/commands/sw-memory-audit.md) | Read-only memory hygiene audit |
| [`/sw-compound`](../../core/commands/sw-compound.md) | Distill retro into memories |
| [`/sw-retro`](../../core/commands/sw-retro.md) | Post-ship retrospective (report-only) |

## Quick reference — commands you invoke directly

| Command | One-line use case |
|---------|-------------------|
| `/sw-setup` | First run or doctor in a target repo |
| `/sw-triage` | How much ceremony does this work need? |
| `/sw-doc` | Full documentation pipeline |
| `/sw-deliver run` | **Primary** — implement frozen tasks to one terminal merge gate |
| `/sw-ship` | Manual single-phase verify → PR → CI loop (Quick tier / debug) |
| `/sw-debug` | Diagnose production or CI failure |
| `/sw-feedback` | Intake and route external signals |
| `/sw-worktree` | Isolate work in a git worktree (manual path) |
| `/sw-start` | Start a phase branch (manual path) |
| `/sw-execute` | Implement one task slice (manual path) |
| `/sw-status` | Reconcile PRD status from git facts |
| `/sw-memory-sync` | Distill session into durable memory |
| `/sw-memory-audit` | Audit memory hygiene (read-only) |
| `/sw-compound` | Turn retro into memories |
| `/sw-retro` | Post-ship retrospective report |

> 34 commands exist today. This table lists orchestrators and common atomics only. Grep
> `core/commands/sw-*.md` for the complete set.

See [Getting started](getting-started.md) for boundary modes and worktree rules.

**Review opt-out:** the canonical way to disable external review is `review.provider: "none"` (schema default). CodeRabbit is opt-in only.
