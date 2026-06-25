---
description: Plan and run dependency-ordered deliver waves in phase-mode or multi-feature mode. Does not bypass /sw-ship, auto-merge to main, or re-author frozen task lists.
alwaysApply: false
---

# `/sw-deliver`

Orchestrator above `/sw-ship` for frozen task lists and multi-item rounds. Auto-detects **phase-mode** (task-list
path) vs **multi-feature mode** (explicit item set / plan). Sequences independent leaves in parallel, stacks
dependents on green unmerged branches, and halts at the human merge gate.

## Subcommands

| Subcommand | Scope |
|------------|-------|
| `plan` | Emit a dependency-ordered wave plan artifact from work items + edges |
| `run` | Provision worktrees, run `/sw-ship` per item, stack dependents, create integration branch |
| `promote` | Human-gated dependency-ordered promotion with per-candidate pre-merge validation |

## Scope

- Input: frozen task list path, explicit item set, or deliver-plan artifact.
- Output: deliver plan JSON; green leaf branches; `integration/<stamp>` test surface (multi-feature mode).
- Does **not** bypass `/sw-ship`, auto-merge to `main`, or unwind green siblings on single-leaf red integration.

## Procedure (`plan`)

1. Load `skills/deliver/SKILL.md`.
2. Auto-detect mode: frozen `--task-list` → **phase-mode**; `--items`/`--edges` → **multi-feature**; both → disambiguation halt.
3. Phase-mode: validate `frozen: true`, resolve `<type>/<slug>`, parse `## Phase Dependencies` (or R8 sequential fallback).
4. Run `scripts/wave.sh preflight` to echo mode, target branch, and waves; then `scripts/wave.sh plan`.
5. Supports `--type`, `--dry-run` (no mutations), and `--from <phase>` (resume guard).
6. Detect cycles; refuse invalid plans.
7. Serialize shared-migration overlaps and INDEX/numbering contention per `skills/parallelism/`.

## Procedure (`run`)

1. Load deliver plan; respect `worktree.parallelCeiling`.
2. Wave 1: provision independent leaves in parallel worktrees.
3. Run `/sw-ship` per item; advance only on green.
4. Wave N: provision dependents with `scripts/worktree.sh provision --base <dep-branch>`.
5. On all green: `scripts/wave.sh integration` merges leaves into `integration/<stamp>` and runs whole-suite check.
6. Halt at human gate for dependency-ordered promotion (`promote`).

## Red integration routing

- **Single leaf reproduces failure** → that leaf re-enters `/sw-stabilize`; siblings untouched.
- **Emergent cross-leaf failure** → delta-debug minimal failing subset + escalate to human gate; max re-route forces escalation.

## Guardrails

- Promotion validates each candidate on a disposable PR head **before** merge to `main`.
- Post-partial-promotion regression: atomic integration PR or revert promoted leaves — never half-promoted red `main`.
- Teardown uses safe worktree/branch removal only.
