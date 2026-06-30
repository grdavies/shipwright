---
description: Push the phase branch and create or update its PR against the recorded parent. Does not commit or merge.
alwaysApply: false
---

# `/sw-pr`

Push after `/sw-commit`; create/update PR against the real parent branch.

## Parent resolution

1. `bash scripts/host.sh resolve-pr-for-branch` then `pr-view` for current branch metadata.
2. If no PR → `scripts/shipwright-state.py read` → `parentBranch`.
3. Never guess from `main` or merge-base.

## Procedure

1. `memory-preflight` read (light) for reviewer context.
2. Clean worktree (`git status --short`).
3. `python3 scripts/git-push.py -u origin HEAD` (first) or `python3 scripts/git-push.py` — never raw
   `git push` in workflow; the wrapper runs `secret-scan.py` pre-push (R41/R50).
4. Create/update PR with Summary, Issues (`issueNumbers`), Verification, Next (`/sw-watch-ci`).
5. PR body may include `prd:<slug>` for living-status linkage (R14).
6. Return PR URL → `/sw-watch-ci`.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-pr`.

## Guardrails

- Does not commit, merge, or fix code.
- PR base must match recorded `parentBranch`.
