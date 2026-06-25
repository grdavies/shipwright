---
description: Push the phase branch and create or update its PR against the recorded parent. Does not commit or merge.
alwaysApply: false
---

# `/sw-pr`

Push after `/sw-commit`; create/update PR against the real parent branch.

## Parent resolution

1. `gh pr view --json number,url,baseRefName,headRefName,isDraft,state` on current branch.
2. If no PR → `scripts/shipwright-state.sh read` → `parentBranch`.
3. Never guess from `main` or merge-base.

## Procedure

1. `memory-preflight` read (light) for reviewer context.
2. Clean worktree (`git status --short`).
3. `bash scripts/git-push.sh -u origin HEAD` (first) or `bash scripts/git-push.sh` — never raw
   `git push` in workflow; the wrapper runs `secret-scan.sh` pre-push (R41/R50).
4. Create/update PR with Summary, Issues (`issueNumbers`), Verification, Next (`/sw-watch-ci`).
5. PR body may include `prd:<slug>` for living-status linkage (R14).
6. Return PR URL → `/sw-watch-ci`.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-pr`.

## Guardrails

- Does not commit, merge, or fix code.
- PR base must match recorded `parentBranch`.
