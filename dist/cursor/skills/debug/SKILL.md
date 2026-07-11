---
name: debug
description: Signal-driven production debugging via shared RCA core. Diagnoses and routes; does not implement or merge fixes.
---

# Debug workflow

Post-ship production signals **and** dev-time test/build failures (R22). Shares `skills/rca-core` with
stabilize (R35). **Diagnoses + proposes; does not implement or merge** — routing hands off to
implementation (`003`) or documentation (`002`).


**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --skill debug`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).


## Orchestrator plan-policy (PRD 024)

Single-tier orchestrator-step plan proposal, validation, and capability selection are owned by
`core/commands/sw-debug.md` + `skills/conductor/SKILL.md` — this skill maps phases to step IDs
(`triage`, `normalize`, `enrich`, `rca`, `route-confirm-halt`, `route`, `rca-human-decision-halt`, `record`).

Under `proposed`, Sentry bodies MUST be redacted via `python3 scripts/memory-redact.py` before any persist or
handoff (including DBG-A2 concurrent enrich + preflight).  Fail-closed on redaction error.

Under `proposed`, R21 surfacing writes `chosenPlan`, `capabilitySet`, and `planRejections` to
`.cursor/sw-debug-runs/<runId>/episodic-run-summary.json` (fixture: `debug-r21-surfacing`).
Driver-enforced budget/no-progress trips after repeated plan rejections (fixture: `debug-budget-trip`).

## Phase 0 — Triage

Parse the inbound signal:

| Input pattern | Normalized type | RCA entry |
|---------------|-----------------|-----------|
| Sentry issue URL/ID | `sentry` | `debug` |
| Deploy log excerpt / CI deploy failure | `deploy_log` | `debug` |
| User-described broken behavior | `user_report` | `debug` |
| Failing test output / assertion | `test_failure` | `dev-time` |
| Build/typecheck/lint failure | `build_failure` | `dev-time` |
| `/sw-verify` failure + log excerpt | `verify_failure` | `dev-time` |

**Dev-time path:** when type is `test_failure`, `build_failure`, or `verify_failure`, skip production-signal
enrichment and invoke `skills/rca-core` **dev-time entry** (strict reproduction-first + failing-regression-test
gate). See **Dev-time gates** below.

**Trivial fast-path:** cause obvious from signal alone (single-line config typo visible in stack, known
missing env var in deploy log). Present diagnosis + proposed one-line fix; offer **Route to scoped phase /
Diagnosis only** — never edit on bare `main`. If the user chooses scoped phase, skip to Phase 3 routing with
the one-line fix as the proposal. Diagnosis-only → skip to Phase 4.

Otherwise → Phase 1.

## Phase 1 — Enrich + memory preflight

1. Normalize to `skills/rca-core/references/debug-inputs.md` shape.
2. **Redact** all text: `python3 scripts/memory-redact.py`.
3. If `type == sentry` → `skills/debug/references/sentry.md` (MCP enrich or degrade).
4. `memory-preflight` **search**: category `debug`, `relatedFiles`, tags for failing area.
5. Attach `priorDebugMemoryIds` to the signal context.

## Phase 2 — RCA

Invoke `skills/rca-core`:

- **Production signals** (`sentry`, `deploy_log`, `user_report`) → **debug entry procedure**
- **Dev-time signals** (`test_failure`, `build_failure`, `verify_failure`) → **dev-time entry procedure**

Shared across entries:

- Rank hypotheses with evidence
- Causal-chain gate before fix proposal
- Invalidate rejected hypotheses explicitly
- Hard stops: max 5 iterations, no-progress, rule-of-three, human-decision (R29)
- Production debug: attempt repro-from-context; local repro optional
- Dev-time: **reproduction-first (strict)** and **failing-regression-test gate** (see below)

## Dev-time gates

Apply when Phase 0 classifies a dev-time signal:

1. **Reproduction-first** — run the narrowest repro command; record exact command + output. If repro cannot
   be established, log attempts and stop at R29 human-decision — no speculative fix.
2. **Failing-regression-test-before-fix** — identify or write a test that fails on current `HEAD`; cite its
   path. The fix is not proposed until this test is red. After fix, the same test must pass without
   weakening assertions.
3. **Optional git-bisect-for-regressions** — when the failure is a regression with unclear introducer, offer
   bisect with a determinism-forcing wrapper (exit `0`/`1`/`125`-skip per `rca-core` dev-time entry).
4. **Rule-of-three** — three identical failed fix attempts (same hypothesis + evidence signature) triggers
   R29 circuit breaker → escalate to architecture review; do not retry variants.

## Phase 3 — Fix-size classification + routing (R24)

After root cause + proposed fix, classify **small** vs **substantial** using `skills/triage/SKILL.md`
rubrics on the **proposed fix scope** (estimated file count, risk triggers, workaround detection):

| Outcome | Route | Handoff |
|---------|-------|---------|
| **Small** — Quick or Standard tier (≤5 files, no risk-floor triggers), no architectural mismatch, not workaround-only | Scoped implementation | `/sw-worktree provision debug-<slug>` → `/sw-start` with RCA output as phase brief |
| **Substantial** — Full tier, wrong interface/requirements, risk-floor triggers, or every fix is a workaround | Documentation | `/sw-brainstorm` (new) or `/sw-amend` + freeze for frozen PRD scope changes |

**Never** patch in place on `main` without worktree + phase loop.

### Workaround detection (bias → substantial)

- Fix only masks symptom (retry loop, broader catch, silent swallow)
- Root cause is missing requirement or wrong abstraction
- Proposed fix contradicts frozen PRD without amendment path

### Routing record (compounding)

After routing decision, `memory-preflight` **write** (redacted):

```json
{
  "category": "debug",
  "tags": ["surface:debug-route", "route:<scoped|brainstorm|amendment>"],
  "relatedFiles": [],
  "summary": "root cause one-liner",
  "originatingSignal": "<type + redacted ref>"
}
```

Feeds `/sw-compound` and future debug preflight.

## Phase 4 — Handoff summary

```markdown
## Signal
[type + redacted ref]

## Root cause
…

## Proposed fix
…

## Route
<scoped phase | brainstorm | amendment> — rationale

## Next command
/sw-worktree … + /sw-start  OR  /sw-brainstorm / amendment path
```

## Guardrails

- Production path is signal-driven (R22); dev-time path is repro-driven with strict gates.
- All Sentry/log text redacted before prompts/memory (R41).
- Bounded RCA loop (R29) — same hard stops as stabilize, including rule-of-three escalation.
- No auto-merge, no silent in-place patches on default branch.
- Sentry MCP read-only; degrade when unavailable.
