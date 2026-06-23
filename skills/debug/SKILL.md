---
name: pf-debug
description: Signal-driven production debugging via shared RCA core. Diagnoses and routes; does not implement or merge fixes.
---

# Debug workflow

Post-ship, signal-driven RCA (R22). Shares `skills/rca-core` with stabilize (R35). **Diagnoses + proposes;
does not implement or merge** — routing hands off to implementation (`003`) or documentation (`002`).

## Phase 0 — Triage

Parse the inbound signal:

| Input pattern | Normalized type |
|---------------|-----------------|
| Sentry issue URL/ID | `sentry` |
| Deploy log excerpt / CI deploy failure | `deploy_log` |
| User-described broken behavior | `user_report` |

**Trivial fast-path:** cause obvious from signal alone (single-line config typo visible in stack, known
missing env var in deploy log). Present diagnosis + proposed one-line fix; run **Fix it now / Diagnosis only**
before any edit. Fast-path saves ceremony, not the user's choice. Diagnosis-only → skip to Phase 4.

Otherwise → Phase 1.

## Phase 1 — Enrich + memory preflight

1. Normalize to `skills/rca-core/references/debug-inputs.md` shape.
2. **Redact** all text: `bash scripts/memory-redact.sh`.
3. If `type == sentry` → `skills/debug/references/sentry.md` (MCP enrich or degrade).
4. `memory-preflight` **search**: category `debug`, `relatedFiles`, tags for failing area.
5. Attach `priorDebugMemoryIds` to the signal context.

## Phase 2 — RCA (debug entry)

Invoke `skills/rca-core` **debug entry procedure**:

- Rank hypotheses with evidence
- Causal-chain gate before fix proposal
- Invalidate rejected hypotheses explicitly
- Hard stops: max 5 iterations, no-progress, human-decision
- Attempt repro-from-context; local repro optional

## Phase 3 — Fix-size classification + routing (R24)

After root cause + proposed fix, classify **small** vs **substantial** using `skills/triage/SKILL.md`
rubrics on the **proposed fix scope** (estimated file count, risk triggers, workaround detection):

| Outcome | Route | Handoff |
|---------|-------|---------|
| **Small** — Quick-tier fix (0–1 files, no architectural mismatch, not workaround-only) | Scoped implementation | `/pf-worktree provision debug-<slug>` → `/pf-start` with RCA output as phase brief |
| **Substantial** — wrong interface/requirements, 6+ files, risk-floor triggers, or every fix is a workaround | Documentation | `/pf-brainstorm` (new) or amend frozen PRD via doc workstream |

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

Feeds `/pf-compound` and future debug preflight.

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
/pf-worktree … + /pf-start  OR  /pf-brainstorm / amendment path
```

## Guardrails

- Signal-driven — not dev-time test reproduction as the primary trigger.
- All Sentry/log text redacted before prompts/memory (R41).
- Bounded RCA loop (R29) — same hard stops as stabilize.
- No auto-merge, no silent in-place patches on default branch.
- Sentry MCP read-only; degrade when unavailable.
