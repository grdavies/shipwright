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
8. **Review echo (R29)** — from gate JSON `coderabbitState` (same `OUT` as step 5):
   - `off` → summary line `review: off` (explicit `review.provider: "none"` opt-out)
   - `unconfigured` → summary line `review: not configured` (never onboarded to a review provider)
   - Other states (`landed`, `skipped`, `in-flight`, `absent`) → echo `review: <coderabbitState>` so a green
     gate with no external review is never mistaken for a reviewed change.
9. Report: `merge-ready` | `ready for next stacked phase` | `not ready` (one blocker) — always include the
   review echo line from step 8.

**Communication intensity:** normal

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-ready`.

## Guardrails

- Never merge, push, or resolve threads here.
- Gate script exit code is the verdict — not a CI glance.
- **Does not run verification-gate** — post-push merge readiness uses `check-gate.sh` only; local `/tmp`
  evidence may be stale at this boundary.
