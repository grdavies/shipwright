---
description: Close a routed feedback backlog signal after verification confirms the fix shipped. Human-gated; does not merge or dispatch routes.
alwaysApply: false
---

# `/sw-feedback-close`

Closure step for trivial-gap backlog items (IM8). Marks an open `docs/prds/GAP-BACKLOG.md` entry closed when
verify evidence passes. **Requires explicit human confirmation** before mutating the backlog.

## Scope

- Input: `--signal-id <id>` (from backlog line `signal:<id>`).
- Output: updated backlog checkbox + `/tmp/sw-feedback-close.status.json`.
- Does **not** merge, push, or re-run `/sw-feedback` routing.

## Procedure

1. Load `skills/feedback-closure/SKILL.md`.
2. **Human confirm** — surface signal summary; proceed only on explicit user OK (same bar as `/sw-feedback` dispatch).
3. Run eligibility gate:

   ```bash
   bash scripts/feedback-closure-gate.sh \
     --backlog docs/prds/GAP-BACKLOG.md \
     --signal-id <id> \
     --verify-status /tmp/sw-verify.status.json \
     [--gate-json /tmp/sw-gate.json --require-gate]
   ```

4. Halt on `not-closable` (20); log `inconclusive` (10) without closing.
5. On `closable`, close backlog entry:

   ```bash
   bash scripts/feedback-backlog.sh close --signal-id <id> --backlog docs/prds/GAP-BACKLOG.md
   ```

6. `memory-preflight` write closure record (redacted summary; tag `surface:feedback-closure`).
7. Emit `/tmp/sw-feedback-close.status.json` with `{signalId, verdict: closed, date}`.

## Guardrails

- Never auto-close from hooks/monitors without human confirmation.
- R41 on all persisted closure text.
- Does not edit frozen artifacts — backlog file only.
