# Shipwright session context

This repository uses the **Shipwright** (`sw-`) workflow. Route memory through the configured provider
adapter.

## Per-worktree state (R38)

Workflow state lives in each worktree's gitdir (`.git/worktrees/<name>/shipwright.json` for linked
worktrees). Repo-level index is derived at read-time via `git worktree list` — no shared mutable index file.

## Communication style (always active)

Caveman communication policy is **always active**. Intensity is resolved from `communication.routing` for
the active `sw-*` command (or `communication.defaultIntensity` when unknown). Override for the current chat
with `/sw-caveman <normal|lite|full|ultra>`.

Bundled policy: `core/communication/caveman-core.md`. Artifact file content always uses normal complete
prose (R30).

## Workflow

- Doc chain: `/sw-doc` (or atomic `/sw-brainstorm` -> `/sw-prd` -> `/sw-freeze` -> `/sw-tasks`).
- Implementation: `/sw-worktree` -> `/sw-start` -> `/sw-execute` -> `/sw-gaps` -> `/sw-verify` ->
  `/sw-review` -> `/sw-commit` -> `/sw-pr` -> `/sw-watch-ci` -> `/sw-stabilize` -> `/sw-ready`.
- `/sw-ship` drives the chain on green and stops at the human merge gate (never merges).
- Post-ship debug: `/sw-debug` (signal-driven RCA from Sentry/deploy/user reports; routes to worktree loop or doc pipeline — does not implement or merge).
- Post-ship feedback: `/sw-feedback` (unified intake for production/review/retro signals; routes to debug, gap-capture, or brainstorm — does not analyze or author).
- Shipwright state is per-worktree (`scripts/shipwright-state.sh`); repo index is read-time derived.

## Memory

- Use the `memory-preflight` skill, not direct provider calls.
- Read before substantive work; store distilled memories after (decision / learning / debug / design /
  code-context / research / discussion). Never store raw transcripts or secrets.
- Project scope by default; global only when explicitly directed.

- Fail-closed guardrails: enforced at `beforeSubmitPrompt` (A1). `sessionStart` injection is best-effort.
