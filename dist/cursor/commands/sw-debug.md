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

Load `skills/conductor/SKILL.md` and enforce `rules/sw-conductor.mdc` — **single source** for in-turn
continuation after route confirmation, parallel I/O dispatch, and legitimate halts (R18). Do not re-implement
loop or halt policy in this file.

## Conductor adoption (DBG-A1..A2)

| ID | Requirement | Contract clause |
| --- | --- | --- |
| DBG-A1 | After one human route confirmation, provision worktree + dispatch `/sw-start` in-turn — no second turn-yield | In-turn self-continuation |
| DBG-A2 | Run Sentry enrich and memory preflight search concurrently after normalize when both are applicable | Parallel dispatch |

Human gates unchanged: RCA human-decision halt, max iterations / no-progress hard stops, Sentry MCP degrade-only.

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

0. Load `skills/conductor/SKILL.md`; enforce `rules/sw-conductor.mdc`.

## Plan-policy adoption (PRD 024)

Read `orchestration.planPolicy` from `.cursor/workflow.config.json` (default **`canonical`**).

- **`canonical`:** steps 1–9 above are unchanged — no orchestrator-step plan artifacts are persisted.
- **`proposed`:** after conductor load and pre-work search, run the episodic entry driver:
  1. `python3 scripts/orchestrator_signal_context.py . capture --orchestrator-type debug --run-id <id> --input '<json>'`
  2. Propose the single-tier debug chain → `python3 scripts/wave.py plan validate --tier orchestrator --orchestrator-type debug --signal-context …`
  3. `python3 scripts/capability-select.py --run-dir .cursor/sw-debug-runs/<id> --context-json …`
  4. Persist validated plan + R21 surfacing under `.cursor/sw-debug-runs/<id>/` via `scripts/orchestrator_run.py entry`
  5. Drive phases from the stored plan; re-validate kernel ordering at each `advance`.

**Preserved halts (R19):** `route-confirm-halt` and `rca-human-decision-halt` are driver-asserted via the debug
guideline pack — plans omitting or reordering them are rejected fail-closed. DBG-A1 in-turn continuation applies
**after** route confirmation only.

1. **Pre-work search (mandatory)** — before the first substantive mutation, run `memory-preflight` **pre-work
   search** per `skills/memory/SKILL.md` **Pre-work search (mandatory)** (scoped to the failing area / touched
   paths; classes `rule`, `decision`, `learning`, `code-context`, `design` via `providers/<memory.provider>.md`
   — no direct provider call). Surface hits and reconcile applicable rules/contradicting decisions before
   proceeding.
2. **Triage** (`skills/debug/SKILL.md` Phase 0) — classify production vs dev-time; trivial fast-path when obvious.
3. **Normalize + redact** signal per `skills/rca-core/references/debug-inputs.md` (extend shape for dev-time).
4. **Sentry enrich** when applicable (`skills/debug/references/sentry.md`); degrade if MCP unavailable.
   - When steps 4 and the pre-work search both apply, run **concurrently** (DBG-A2) — independent I/O; collect
     before RCA.
5. **RCA** — `skills/rca-core` (`rca-core` entry):
   - production signals → **debug entry**
   - test/build/verify failures → **dev-time entry** (repro-first + failing-regression-test gates)
6. **Route** — classify fix size via triage rubric; present handoff and **halt for one human route confirmation**.
7. On confirmed route, **in-turn** (DBG-A1):
   - **Small** → `/sw-worktree provision` + dispatch `/sw-start` with RCA brief (no second turn-yield)
   - **Substantial** → dispatch `/sw-brainstorm` or `/sw-amend` per doc workstream
8. **Record** route + originating signal via `memory-preflight` write (redacted) for compounding.
9. Return structured handoff summary (root cause, proposed fix, route, next command).

## Delegated atomics

| Step | Delegate via | Skill / agent binding |
| --- | --- | --- |
| Sentry enrich | Task when MCP-heavy | `--command sw-debug --skill debug` |
| RCA deep dive | Task | `--command sw-debug --skill rca-core` |
| `/sw-start` (small-fix route) | Task after confirmation | `--command sw-start` |
| `/sw-brainstorm` / `/sw-amend` (substantial) | Task after confirmation | `--command sw-brainstorm` or `--command sw-amend` |

## Delegated Task binding contract

Before dispatching specialist/debug sub-agents from `/sw-debug`:

1. `python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-debug --skill debug`
2. `python3 scripts/dispatch-check.py --agent <agent-id> --command sw-debug --skill debug --parent-model <parent-concrete-id> [--dispatch-id <id>]`
3. Pass explicit concrete `model:` on Task input.

Resolve model: `python3 scripts/resolve-model-tier.py --command <child-slug>` (or `--skill rca-core`).
Resolve intensity: `python3 scripts/resolve-intensity.py --command <child-slug>` (or `--skill|--agent`).


## Cross-run root-cause records (read-only, PRD 041 R24)

`/sw-debug` may **read** escalated root-cause records from `${GIT_DIR}/shipwright-root-cause-records.json`
and anomaly-pattern annotations for context — it does **not** expand orchestrator steps, auto-act on catalog
matches, or write escalation records. Escalation is owned by `scripts/failure-signature-escalate.py` after
recurrence threshold; test-tampering recognition defers to PRD A R9 flags only.

## What this command does not do

- Does not run `/sw-ship`, merge PRs, or patch on bare `main`
- Does not mutate Sentry (read-only MCP)
- Does not replace `/sw-stabilize` (in-loop CI/review failures)

**Communication intensity:** inherit

**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --command sw-debug`.

## Inline allowlist (closed)

`/sw-debug` may remain inline only for:

- Signal normalization/classification and route decision output.
- Redaction/memory-preflight handoff preparation.
- Worktree/doc-route recommendation synthesis.

RCA deep dives and fix authoring delegate.

## Dispatch context redaction contract

Every non-config dispatch payload (Sentry excerpts, deploy logs, user reports, failing traces, memory search
results) must pass `python3 scripts/memory-redact.py` and be fenced as `untrusted_payload` before Task dispatch.

## Guardrails

- Every ingestion edge through `python3 scripts/memory-redact.py` (R41).
- RCA hard stops: max 5 iterations, no-progress, rule-of-three, human-decision (R29).
- Rejected hypotheses invalidated explicitly — no variant-retry spiral.
