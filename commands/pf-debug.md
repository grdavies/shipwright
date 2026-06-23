---
description: Signal-driven production debug — triages deploy/Sentry/user signals through shared RCA and routes a fix without implementing or merging.
alwaysApply: false
trigger: "/pf-debug"
---

# `/pf-debug`

Post-ship debugging orchestrator (R22). Accepts a production signal, runs the bounded RCA loop via
`skills/rca-core` (debug entry), and routes the result by fix size (R24). **Diagnoses and proposes; does
not implement, commit, push, or merge** — scoped fixes go to the implementation worktree loop; substantial
fixes go to brainstorm/PRD amendment.

## Signal forms

- **Sentry** — issue URL, `ORG/PROJECT-123`, or event link
- **Deploy log** — excerpt from Vercel/GitHub Actions/etc.
- **User report** — described broken behavior + environment

## Config

Read `.cursor/workflow.config.json` for `prdsDir`, `agentsFile`, `memory` provider.

## Procedure

1. **Triage** (`skills/debug/SKILL.md` Phase 0) — trivial fast-path offers diagnosis-vs-fix before edits.
2. **Normalize + redact** signal per `skills/rca-core/references/debug-inputs.md`.
3. **Sentry enrich** when applicable (`skills/debug/references/sentry.md`); degrade if MCP unavailable.
4. **Memory preflight** — search prior `debug` memories for the failing area.
5. **RCA** — `skills/rca-core` debug entry (hypotheses → causal-chain gate → root cause + proposed fix).
6. **Route** — classify fix size via triage rubric; hand off:
   - **Small** → `/pf-worktree provision` + `/pf-start` with RCA brief in worktree
   - **Substantial** → `/pf-brainstorm` or `/pf-amend` (frozen PRD scope change) per doc workstream
7. **Record** route + originating signal via `memory-preflight` write (redacted) for compounding.
8. Return structured handoff summary (root cause, proposed fix, route, next command).

## What this command does not do

- Does not run `/pf-ship`, merge PRs, or patch on bare `main`
- Does not mutate Sentry (read-only MCP)
- Does not replace `/pf-stabilize` (in-loop CI/review failures)

## Guardrails

- Every ingestion edge through `bash scripts/memory-redact.sh` (R41).
- RCA hard stops: max 5 iterations, no-progress, human-decision (R29).
- Rejected hypotheses invalidated explicitly — no variant-retry spiral.
