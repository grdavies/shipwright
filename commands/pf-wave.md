---
description: Plan and run dependency-ordered build waves with worktree stacking and integration branch. Does not bypass /pf-ship or auto-merge to main.
alwaysApply: false
---

# `/pf-wave`

Multi-item wave orchestrator above `/pf-ship`. Sequences independent leaves in parallel, stacks dependents on green unmerged branches, merges into `integration/<stamp>` for whole-suite testing, then halts at the human merge gate.

## Subcommands

| Subcommand | Scope |
|------------|-------|
| `plan` | Emit a dependency-ordered wave plan artifact from work items + edges |
| `run` | Provision worktrees, run `/pf-ship` per item, stack dependents, create integration branch |
| `promote` | Human-gated dependency-ordered promotion with per-candidate pre-merge validation |

## Scope

- Input: task list path, explicit item set, or wave-plan artifact.
- Output: wave plan JSON; green leaf branches; `integration/<stamp>` test surface.
- Does **not** bypass `/pf-ship`, auto-merge to `main`, or unwind green siblings on single-leaf red integration.

## Procedure (`plan`)

1. Load `skills/wave/SKILL.md`.
2. Parse work items and dependency edges.
3. Detect cycles; refuse invalid plans.
4. Serialize shared-migration overlaps and INDEX/numbering contention per `skills/parallelism/`.
5. Emit wave plan via `scripts/wave.sh plan`.

## Procedure (`run`)

1. Load wave plan; respect `worktree.parallelCeiling`.
2. Wave 1: provision independent leaves in parallel worktrees.
3. Run `/pf-ship` per item; advance only on green.
4. Wave N: provision dependents with `scripts/worktree.sh provision --base <dep-branch>`.
5. On all green: `scripts/wave.sh integration` merges leaves into `integration/<stamp>` and runs whole-suite check.
6. Halt at human gate for dependency-ordered promotion (`promote`).

## Red integration routing

- **Single leaf reproduces failure** → that leaf re-enters `/pf-stabilize`; siblings untouched.
- **Emergent cross-leaf failure** → delta-debug minimal failing subset + escalate to human gate; max re-route forces escalation.

## Guardrails

- Promotion validates each candidate on a disposable PR head **before** merge to `main`.
- Post-partial-promotion regression: atomic integration PR or revert promoted leaves — never half-promoted red `main`.
- Teardown uses safe worktree/branch removal only.
