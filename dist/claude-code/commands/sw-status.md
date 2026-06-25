---
description: Derive and reconcile PRD living status from git facts. Does not modify frozen PRDs or merge PRs.
alwaysApply: false
---

# `/sw-status`

Git-derived living status over `docs/prds/INDEX.md` and `docs/prds/COMPLETION-LOG.md`.

Load `skills/living-status/SKILL.md`.

## Procedure

1. `bash scripts/reconcile-status.sh derive` — show per-PRD status + task/PR linkage.
2. On user request or post-merge: `reconcile` to update INDEX Status column.
3. After shipped phase: `append-log` for completion log entry.
4. Include GAP-BACKLOG summary (read-only).
5. **Review echo (R29)** — when the current branch has an open PR, run `scripts/check-gate.sh` and include in
   the status summary:
   - `coderabbitState: off` → `review: off`
   - `coderabbitState: unconfigured` → `review: not configured`
   - otherwise → `review: <coderabbitState>` (per `skills/living-status/SKILL.md`).

**Communication intensity:** ultra

## Guardrails

- Frozen artifacts never modified.
- Task checkboxes are derivation inputs only.
