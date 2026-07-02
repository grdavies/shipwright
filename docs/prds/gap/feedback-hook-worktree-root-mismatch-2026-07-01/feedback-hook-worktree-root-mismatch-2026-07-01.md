---
id: feedback-hook-worktree-root-mismatch-2026-07-01
type: gap
status: resolved
schedule: PRD 050 A1
title: Hook-state worktree root mismatch causes false prework/preflight denials
visibility: public
resolvedBy: PRD 050 A1
tags: [source:feedback, signal:feedback-hook-worktree-root-mismatch-2026-07-01, plugin-self, meta-shipwright]
absorbs: []
---

# Hook-state worktree root mismatch causes false prework/preflight denials

_Captured from feedback signal `feedback-hook-worktree-root-mismatch-2026-07-01` during concurrent PRD creation._

## Summary

Ephemeral hook state (`.cursor/hooks/state/` prework search records and dispatch-preflight nonces) was written
from worktree `cwd` while `preToolUse` hooks read from Cursor `workspace_roots[0]` (primary checkout). Agents
running prework/preflight from a docs or phase worktree received false `missing-prework-search-record` and
`missing-preflight-nonce` denials even when operating correctly.

## Remediation (PRD 050 A1)

- R20–R22: `workspace_root()` prefers cwd git toplevel when valid worktree alignment applies.
- R25–R26: script-side fail-closed guard with `move_agent_to_root` remediation when alignment unavailable.
- R27–R30: offline fixtures prove alignment, dispatch preflight, primary no-regression, and ambiguous fail-closed.

## Schedule

**PRD 050 A1** (`A1-hook-state-worktree-alignment.md`) — resolved after R27–R30 fixtures green.
