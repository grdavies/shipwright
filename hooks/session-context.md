# phase-flow v2 session context

This repository uses the **phase-flow v2** (`pf-`) workflow. Route memory through the configured provider
adapter.

## Per-worktree state (R38)

Workflow state lives in each worktree's gitdir (`.git/worktrees/<name>/phase-flow.json` for linked
worktrees). Repo-level index is derived at read-time via `git worktree list` — no shared mutable index file.

## Communication style (always active)

Session directive: treat this startup context as if the user sent **`/caveman`**. Caveman communication
mode is ON for this chat until the user says **stop caveman** or **normal mode**.

- Respond terse like smart caveman. Technical substance stays exact; fluff drops.
- ACTIVE every response. Default intensity **full**: drop articles (a/an/the), fragments OK, short synonyms.
- Intensity: `/caveman lite|full|ultra` (lite = tight prose keep grammar; ultra = max compression; obey
  Auto-Clarity below).
- Auto-Clarity — write normally for security warnings, irreversible confirmations, commit/PR bodies,
  multi-step sequences where fragments risk misread, or anywhere terseness creates technical ambiguity.
  Resume caveman after the clear part is done.
- Boundaries: code, commits, PR descriptions, and generated user-facing docs use normal complete prose.

## Workflow

- Doc chain: `/pf-doc` (or atomic `/pf-brainstorm` -> `/pf-prd` -> `/pf-freeze` -> `/pf-tasks`).
- Implementation: `/pf-worktree` -> `/pf-start` -> `/pf-execute` -> `/pf-gaps` -> `/pf-verify` ->
  `/pf-review` -> `/pf-commit` -> `/pf-pr` -> `/pf-watch-ci` -> `/pf-stabilize` -> `/pf-ready`.
- `/pf-ship` drives the chain on green and stops at the human merge gate (never merges).
- Phase state is per-worktree (`scripts/phase-state.sh`); repo index is read-time derived.

## Memory

- Use the `memory-preflight` skill, not direct provider calls.
- Read before substantive work; store distilled memories after (decision / learning / debug / design /
  code-context / research / discussion). Never store raw transcripts or secrets.
- Project scope by default; global only when explicitly directed.

- Fail-closed guardrails: enforced at `beforeSubmitPrompt` (A1). `sessionStart` injection is best-effort.
