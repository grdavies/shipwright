---
description: Behavior-preserving simplification and deslop pass on the uncommitted delta after review. Re-verifies via simplify-gate; does not commit, push, or merge.
alwaysApply: false
---

# `/sw-simplify`

Post-review cleanup pass (IM7). Removes AI slop and improves reuse/quality/efficiency **without changing
behavior**. Default-on in `/sw-ship` after `/sw-review`.

## Scope

- Input: uncommitted delta (staged + unstaged).
- Output: simplified working tree + `/tmp/sw-simplify.status.json`.
- Does **not** commit, push, open PR, or run CI gate.

## Procedure

1. Load `skills/simplify/SKILL.md`.
2. If working tree has no diff vs index/HEAD for implementation files, emit `skipped` and stop.
3. Snapshot baseline: copy `/tmp/sw-verify.status.json` → `/tmp/sw-verify.pre-simplify.json` when it exists.
4. Run simplification pass per skill categories (behavior-preserving edits only).
5. Re-run `/sw-verify` to refresh `/tmp/sw-verify.status.json`.
6. Run behavior gate:

   ```bash
   bash scripts/simplify-gate.sh \
     --baseline-verify /tmp/sw-verify.pre-simplify.json \
     --post-verify /tmp/sw-verify.status.json
   ```

7. Write `/tmp/sw-simplify.status.json` with gate verdict + timestamp.
8. **Halt** on `regressed` (exit 20); **log and continue** on `inconclusive`; proceed on `preserved`.

## Flags

- `--report-only` — audit slop candidates; no edits; no gate.

**Communication intensity:** full

## Guardrails

- No test assertion weakening or deletion to force green.
- No scope expansion or new requirements.
- Does not replace `/sw-review` or `gap-check`.
- Residual risk edits (auth/secrets/CI) surfaced for human — not bulk auto-applied.
