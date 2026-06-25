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
4. Run `scripts/wave.sh preflight` to echo mode, target branch, and waves (includes CI/review
   base-branch preflight, R49); then `scripts/wave.sh plan`.
5. Supports `--type`, `--dry-run` (no mutations), and `--from <phase>` (resume guard).
6. Detect cycles; refuse invalid plans.
7. Serialize shared-migration overlaps and INDEX/numbering contention per `skills/parallelism/`.

## Procedure (`run`)

0. **Entry guard (R16):** `bash scripts/wave.sh assert-entry` (wraps `sw-assert-worktree.sh`) — refuse
   phase implementation on bare default branch without a linked worktree.
1. Load deliver plan; respect `worktree.parallelCeiling`.
2. **Orchestrator worktree (R53):** `bash scripts/wave.sh orchestrator provision --plan .cursor/sw-deliver-plan.json`
   on `<type>/<slug>` — hosts the serialized merge queue and R40 forward-merges. Does **not** count toward
   `worktree.parallelCeiling`.
3. Wave 1: provision independent phase worktrees via `scripts/wave.sh phase provision --phase-id <id>`.
4. Dispatch full `/sw-ship` per phase (`scripts/wave.sh phase dispatch-env --phase-slug <slug>` exports
   `SW_PHASE_MODE` / `SW_RUN_DIR`); orchestrator **never bypasses** any `/sw-ship` step (R13).
5. Collect outcomes: `scripts/wave.sh status collect --phase-slug <slug>` from durable status path (R38).
6. On `merge-ready-green`: `scripts/wave.sh merge enqueue` then `merge run-next` when gate + review
   barrier settle (R17/R19/R52). `merge run-next` records CHANGELOG / `version.txt` via
   `scripts/wave.sh bookkeeping record` in the orchestrator worktree (R58–R60), then runs incremental
   `verify.*` on `<type>/<slug>` (R39).
7. On verify failure or bad merge: `scripts/wave.sh revert phase` + blast-radius; route to `/sw-stabilize`.
8. After each merge into `<type>/<slug>`, advance dependents with
   `scripts/wave.sh forward-merge --worktree <phase-wt> --base <type>/<slug>` (merge, not rebase); conflicts →
   `blocked`.
9. Teardown completed phases with `scripts/wave.sh phase-teardown --name <worktree-name>` (`git worktree remove`
   + prune only).
10. When all phases `green-merged`: `scripts/wave.sh resume reconcile`, then
    `scripts/wave.sh terminal pr prepare` + `terminal pr gate`, then `scripts/wave.sh report terminal`;
    open/update `<type>/<slug> → main` PR only at this point.
11. Halt at human gate for terminal merge (phase-mode) or dependency-ordered promotion (`promote`, multi-feature).

## Red integration routing

- **Single leaf reproduces failure** → that leaf re-enters `/sw-stabilize`; siblings untouched.
- **Emergent cross-leaf failure** → delta-debug minimal failing subset + escalate to human gate; max re-route forces escalation.

**Communication intensity:** inherit

## Guardrails

- Promotion validates each candidate on a disposable PR head **before** merge to `main`.
- Post-partial-promotion regression: atomic integration PR or revert promoted leaves — never half-promoted red `main`.
- Teardown uses safe worktree/branch removal only.
