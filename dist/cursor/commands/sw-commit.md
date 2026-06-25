---
description: Commit the current phase after verify and review. Does not push or open a PR.
alwaysApply: false
---

# `/sw-commit`

Phase-scoped commit after `/sw-verify` (and `/sw-review` when configured).

## Procedure

1. Confirm `/sw-verify` passed and verify status exists (resolve run dir via `scripts/sw-tmp.sh resolve`,
   defaulting to `/tmp/sw-verify.status.json` when unset).
2. **Verification gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.sh` with
   `--verify-status <resolved>/sw-verify.status.json`, optional `--review-status <resolved>/sw-review.status.json`
   (absent when review disabled), and `--pr-context on` when a PR is open. Policy by `inconclusiveClass`:
   - **`verified`** — proceed.
   - **`missing-required`** — **block** (do not commit).
   - **`no-baseline` / `unattributed`** — require a **logged auditable override** before proceeding (loud
     prompt → user reason → persist record).
3. **Override record** (when inconclusive is overridden) — append via `scripts/shipwright-state.sh override-add`:

   ```bash
   REASON_REDACTED=$(printf '%s' "$USER_REASON" | bash scripts/memory-redact.sh)
   WHO=$(git config user.email)
   WHEN=$(date -u +%Y-%m-%dT%H:%M:%SZ)
   bash scripts/shipwright-state.sh override-add "$(jq -n \
     --arg who "$WHO" --arg when "$WHEN" --arg ic "$INCONCLUSIVE_CLASS" \
     --arg reason "$REASON_REDACTED" --arg vo "inconclusive" \
     '{who:$who,when:$when,verdictOverridden:$vo,inconclusiveClass:$ic,reason:$reason}')"
   ```

   Emit the same redacted fields in a **commit trailer** (`Verification-Override:`). Any lightweight/trivial
   path writes this same record — no unlogged exception. Override **never** suppresses a red
   `check-gate.sh`/CI verdict.
4. Complete `/sw-review` when review is enabled; address actionable findings; re-run the verification gate if
   review or fixes changed the delta materially.
5. `memory-preflight` checkpoint for durable learnings (redact before store).
6. Review delta; stage only phase files.
7. **Exclude** per-worktree state (`shipwright.json`), memory-sync markers, provider cache, and
   `/sw-deliver` living artifacts (`.cursor/sw-deliver-plan.json`, `.cursor/sw-deliver-state.json`,
   `.cursor/sw-deliver.lock`, `.cursor/sw-deliver-runs/`).
8. Commit with heredoc message matching repo style (include override trailer when applicable).
9. Hand off to `/sw-pr`.

## Guardrails

- Verification gate override is auditable only — cannot suppress red `check-gate.sh`/CI.
- Block on `missing-required`; logged decision required on `no-baseline` / `unattributed`.
- No unrelated dirty-tree files.
- Never commit `shipwright.json` or `.git/shipwright-memory-sync.json`.
- Never commit `.cursor/sw-deliver-*` orchestrator artifacts (plan, state, lock, runs).
- Does not push or open PR.
