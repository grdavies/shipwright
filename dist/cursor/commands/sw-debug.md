---
description: Signal-driven production debug — triages deploy/Sentry/user signals through shared RCA and routes a fix without implementing or merging.
alwaysApply: false
trigger: "/sw-debug"
---

# `/sw-debug`

Production-signal and dev-time debugging orchestrator (R22). Runs bounded RCA via `skills/rca-core`
(**debug** or **dev-time** entry) and routes by fix size (R24). **Diagnoses and proposes; does not implement,
commit, push, or merge** — scoped fixes go to the implementation worktree loop; substantial
fixes go to brainstorm/PRD amendment.

## Signal forms

**Production (debug entry):**

- **Sentry** — issue URL, `ORG/PROJECT-123`, or event link
- **Deploy log** — excerpt from Vercel/GitHub Actions/etc.
- **User report** — described broken behavior + environment

**Dev-time (dev-time entry):**

- **Test failure** — failing test output, assertion, or `pytest`/`vitest`/`npm test` excerpt
- **Build failure** — compiler, typecheck, or lint error with repro command
- **Verify failure** — `/tmp/sw-verify.status.json` + `/tmp/sw-verify.*.log` from a failed `/sw-verify`

Dev-time signals use strict reproduction-first and failing-regression-test gates (`skills/debug/SKILL.md`).

## Config

Read `.cursor/workflow.config.json` for `prdsDir`, `agentsFile`, `memory` provider.

## Procedure

1. **Triage** (`skills/debug/SKILL.md` Phase 0) — classify production vs dev-time; trivial fast-path when obvious.
2. **Normalize + redact** signal per `skills/rca-core/references/debug-inputs.md` (extend shape for dev-time).
3. **Sentry enrich** when applicable (`skills/debug/references/sentry.md`); degrade if MCP unavailable.
4. **Memory preflight** — search prior `debug` memories for the failing area.
5. **RCA** — `skills/rca-core`:
   - production signals → **debug entry**
   - test/build/verify failures → **dev-time entry** (repro-first + failing-regression-test gates)
6. **Route** — classify fix size via triage rubric; hand off:
   - **Small** → `/sw-worktree provision` + `/sw-start` with RCA brief in worktree
   - **Substantial** → `/sw-brainstorm` or `/sw-amend` (frozen PRD scope change) per doc workstream
7. **Record** route + originating signal via `memory-preflight` write (redacted) for compounding.
8. Return structured handoff summary (root cause, proposed fix, route, next command).

## What this command does not do

- Does not run `/sw-ship`, merge PRs, or patch on bare `main`
- Does not mutate Sentry (read-only MCP)
- Does not replace `/sw-stabilize` (in-loop CI/review failures)

**Communication intensity:** inherit

**Model tier:** build — resolve via `bash scripts/resolve-model-tier.sh --command sw-debug`.

## Guardrails

- Every ingestion edge through `bash scripts/memory-redact.sh` (R41).
- RCA hard stops: max 5 iterations, no-progress, rule-of-three, human-decision (R29).
- Rejected hypotheses invalidated explicitly — no variant-retry spiral.
