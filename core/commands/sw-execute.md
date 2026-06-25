---
description: Execute one phase-sized slice on the current branch using the spec union and per-task execute discipline. Does not commit, push, or open a PR.
alwaysApply: false
---

# `/sw-execute`

Implement exactly one planned phase on the current branch inside the worktree. Uses **per-task execute
discipline** (`skills/execute-discipline/SKILL.md`): plan self-review → TDD red-green → two-stage review.

## Procedure

1. **Worktree guard** — run `bash scripts/sw-assert-worktree.sh` before any implementation write. Exit `1` → halt
   (bare default branch without linked worktree). Exit `2` → configuration error; halt.
2. Load the task file from `tasksDir` for this phase; resolve requirements via **spec union**:

   ```bash
   bash scripts/spec-union.sh <frozen-prd-path>
   ```

   Load `skills/spec-union/SKILL.md`. Parse `## Traceability` for R-ID → test scenario per task ref.
   Load open `docs/prds/GAP-BACKLOG.md` items (`bash scripts/feedback-backlog.sh list --open-only`) linked to
   this PR/PRD as supplemental scope (`skills/feedback-closure/SKILL.md`).
3. Verify branch matches `scripts/shipwright-state.sh read` → `currentBranch`.
4. `memory-preflight` read: PRD/task, target files, prior learnings.
5. Load `agentsFile` + applicable doctrine + `skills/execute-discipline/SKILL.md`.
6. `TodoWrite` for the phase checklist items.
7. **Per task ref** (sub-task granularity, e.g. `1.1`, `1.2`):
   1. `bash scripts/plan-self-review.sh --tasks <task-file> --task-ref <ref>` — halt on `fail`.
   2. **TDD red** — run traced test from traceability; write `/tmp/sw-tdd.status.json` with `red` observed failing.
   3. Implement the slice; keep todos and checkboxes current.
   4. **TDD green** — re-run test; update status with `green` passing.
   5. `bash scripts/tdd-gate.sh --status /tmp/sw-tdd.status.json` — halt on `fail` (`20`).
   6. **Two-stage review** (fresh subagent when delegated — `rules/sw-subagent-dispatch.mdc`):
      - Stage 1: spec-compliance (task + union R-IDs)
      - Stage 2: code-quality (no scope expansion)
8. Optional issue comments when `issueNumbers` set (`gh issue comment`).
9. `memory-preflight` write for durable decisions only (redact via `scripts/memory-redact.sh` first).
10. Subagents per `rules/sw-subagent-dispatch.mdc` for independent parallel work **within** a task only when
   file sets are disjoint; never skip the per-task TDD + two-stage sequence.
11. Leave uncommitted for `/sw-verify`, `/sw-review`, `/sw-commit`.

**Communication intensity:** full

## Guardrails

- One phase per invocation; read spec union, not bare parent PRD alone.
- Per-task TDD gate consumes U6 traceability — no implementation without observed red (or logged `skipped`).
- Do not weaken tests to force green; `testWeakened: true` fails the gate.
- Per-worktree state is authoritative for parent/phase context.
- Does not push or open PR.
