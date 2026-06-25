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
| `deliver-loop` | Durable state-machine driver: plan → provision → dispatch → merge → terminal; resumes from state (R1–R5) |
| `run` | Alias for `deliver-loop` on a frozen task list (phase-mode) |
| `promote` | Human-gated dependency-ordered promotion with per-candidate pre-merge validation |

## Scope

- Input: frozen task list path, explicit item set, or deliver-plan artifact.
- Output: deliver plan JSON; green leaf branches; `integration/<stamp>` test surface (multi-feature mode).
- Does **not** bypass `/sw-ship`, auto-merge to `main`, or unwind green siblings on single-leaf red integration.

## Procedure (`plan`)

1. Load `skills/deliver/SKILL.md`.
2. Auto-detect mode: frozen `--task-list` → **phase-mode**; `--items`/`--edges` → **multi-feature**; both → disambiguation halt.
3. Phase-mode: validate `frozen: true`, resolve `<type>/<slug>`, parse `## Phase Dependencies` (or R8 sequential fallback).
4. Run `scripts/wave.sh preflight` to echo mode, target branch, and waves (includes CI/review
   base-branch preflight, R49); then `scripts/wave.sh plan`.
5. Supports `--type`, `--dry-run` (no mutations), and `--from <phase>` (resume guard).
6. Detect cycles; refuse invalid plans.
7. Serialize shared-migration overlaps and INDEX/numbering contention per `skills/parallelism/`.

## Procedure (`deliver-loop` / `run`)

Phase-mode runs MUST enter through the durable driver — never a manual worktree handoff while progress is
possible (R4).

```bash
bash scripts/wave.sh deliver-loop --task-list <frozen-task-list-path>
# resume (state present):
bash scripts/wave.sh deliver-loop --dry-run
```

0. **Entry guard (R16):** `bash scripts/wave.sh assert-entry` when not resuming from durable state.
1. Driver loads plan from state or runs `plan`; auto-detects in-progress runs on entry (R3).
2. **Orchestrator worktree (R53):** `orchestrator provision` on `<type>/<slug>`.
3. Per wave: `phase provision` → `phase dispatch-env` → full `/sw-ship --phase-mode` in phase worktree
   (agent step; orchestrator never bypasses `/sw-ship`).
4. `status collect` from durable path; advance only from `status.json` (R7).
5. On `merge-ready-green`: `merge enqueue` → `merge run-next` when gate + review barrier settle.
6. On blocker: bounded remediation (`deliver.remediation.maxAttempts`, default **2**), blast-radius for
   siblings, consolidated blocker report on halt (R8–R12).
7. When all phases `green-merged`: `resume reconcile`, terminal PR, compounding (later phases).
8. Halt at human merge gate — never in-flux.

`run` is an alias for `deliver-loop --task-list <path>`.

## Red integration routing

- **Single leaf reproduces failure** → that leaf re-enters `/sw-stabilize`; siblings untouched.
- **Emergent cross-leaf failure** → delta-debug minimal failing subset + escalate to human gate; max re-route forces escalation.

**Communication intensity:** inherit

## Guardrails

- Promotion validates each candidate on a disposable PR head **before** merge to `main`.
- Post-partial-promotion regression: atomic integration PR or revert promoted leaves — never half-promoted red `main`.
- Teardown uses safe worktree/branch removal only.
