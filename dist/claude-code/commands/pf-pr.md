---
description: Push the phase branch and create or update its PR against the recorded parent. Does not commit or merge.
alwaysApply: false
---

# `/pf-pr`

Push after `/pf-commit`; create/update PR against the real parent branch.

## Parent resolution

1. `gh pr view --json number,url,baseRefName,headRefName,isDraft,state` on current branch.
2. If no PR → `scripts/phase-state.sh read` → `parentBranch`.
3. Never guess from `main` or merge-base.

## Procedure

1. `memory-preflight` read (light) for reviewer context.
2. Clean worktree (`git status --short`).
3. `git push -u origin HEAD` (first) or `git push`.
4. Create/update PR with Summary, Issues (`issueNumbers`), Verification, Next (`/pf-watch-ci`).
5. PR body may include `prd:<slug>` for living-status linkage (R14).
6. Return PR URL → `/pf-watch-ci`.

## Guardrails

- Does not commit, merge, or fix code.
- PR base must match recorded `parentBranch`.
