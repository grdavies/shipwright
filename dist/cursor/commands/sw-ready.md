---
description: Terminal readiness report — runs check-gate.sh and never merges. Does not push or fix code.
alwaysApply: false
---

# `/sw-ready`

Confirm merge-readiness via `scripts/check-gate.sh` — terminal report only.

## Procedure

1. `gh pr view --json number,url,isDraft,baseRefName,headRefName,reviewDecision,statusCheckRollup`.
2. No PR → hand off `/sw-pr`.
3. Confirm PR base matches `parentBranch` from per-worktree state.
4. Clean branch; local verify already passed.
5. **Authoritative gate** — do not hand-roll:

   ```bash
   GATE="${CURSOR_PLUGIN_ROOT:-$PWD}/scripts/check-gate.sh"
   if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
   echo "$OUT" | jq .
   ```

6. `merge-ready` only when `GATE_EC == 0` / `verdict == "green"`.
7. `yellow` → `/sw-watch-ci`; `red`/`blocked` → `/sw-stabilize`.
8. Report: `merge-ready` | `ready for next stacked phase` | `not ready` (one blocker).

## Guardrails

- Never merge, push, or resolve threads here.
- Gate script exit code is the verdict — not a CI glance.
- **Does not run verification-gate** — post-push merge readiness uses `check-gate.sh` only; local `/tmp`
  evidence may be stale at this boundary.
