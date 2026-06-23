---
description: Commit the current phase after verify and review. Does not push or open a PR.
alwaysApply: false
---

# `/pf-commit`

Phase-scoped commit after `/pf-verify` (and `/pf-review` when configured).

## Procedure

1. Confirm `/pf-verify` passed and `/tmp/pf-verify.status.json` exists.
2. **Verification gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.sh` with
   `--verify-status /tmp/pf-verify.status.json` and optional `--review-status /tmp/pf-review.status.json`
   (absent when review disabled). Proceed only when verdict is `verified`, or when the user records a
   **single logged auditable override** (R42-style: who, why, timestamp — never suppress a red
   `check-gate.sh`/CI verdict).
3. Complete `/pf-review` when review is enabled; address actionable findings; re-run the verification gate if
   review or fixes changed the delta materially.
4. `memory-preflight` checkpoint for durable learnings (redact before store).
5. Review delta; stage only phase files.
6. **Exclude** per-worktree state (`phase-flow.json`), memory-sync markers, provider cache.
7. Commit with heredoc message matching repo style.
8. Hand off to `/pf-pr`.

## Guardrails

- Verification gate override is R42-style auditable only — cannot suppress red `check-gate.sh`/CI.
- No unrelated dirty-tree files.
- Never commit `phase-flow.json` or `.git/phase-flow-memory-sync.json`.
- Does not push or open PR.
