---
id: gap-013-terminal-pr-prepare-body-skips-template-validati
type: gap
status: resolved
schedule: PRD 050
resolvedBy: PRD 050
title: Terminal PR prepare body skips template validation
visibility: public
tags: [source:feedback, signal:feedback-prd-041-terminal-pr-template-2026-07-01, prd-041, plugin-self]
source_pr: 284
absorbs: []
---

# Terminal PR prepare body skips template validation

_Captured from PRD 041 terminal deliver (`feedback-prd-041-terminal-pr-template-2026-07-01`)._

## Summary

`wave_terminal.terminal_pr_body()` builds a minimal markdown list (phase PRs + human-merge note) and passes
it directly to `host_pr_create` — **without** `git_template_lib.py` `render pr-body` / `validate pr-body`.
Phase PRs and docs PRs use the validated template; terminal PRs do not.

Operator observed template validation as "inconsistent" and manually created terminal PR #284 via `gh pr create`
with a proper body, then patched `terminalPr` into deliver state.

## PRD 041 evidence

- Agent message: "template validation appears inconsistent"; manual PR creation chosen over orchestrator hack.
- `cmd_terminal_pr_prepare` (`wave_terminal.py` ~L881) uses `body = terminal_pr_body(state)` only.

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **GAP-022** (scheduled) | Terminal PR autonomy — related but not template-specific |
| **GAP-064** (scheduled) | `wave_terminal.py` TypeError on create — separate bug |
| **docs_pr.py** | Uses `_render_pr_body` + `_validate_pr_body` — pattern terminal should mirror |

## Remediation direction

1. Render terminal PR body via `core/sw-reference/templates/pr-body.md` with context
   (`summary`, `test_plan`, `prd_slug`, phase PR list).
2. Fail closed on template validation before `host_pr_create` (same as `docs_pr.py`).
3. Fixture: `terminal-pr-body-template-valid`.

## Schedule

Triage to **PRD 035 A1** (terminal ship) or **PRD 027** (terminal finalization).
