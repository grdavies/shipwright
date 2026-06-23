---
name: rca-core
description: Shared hypothesis-driven root cause analysis core for stabilize and debug entry points.
---

# RCA core (shared)

Single analysis discipline with two entry points (R35). Both use the same hypothesis ranking, causal-chain
gate, explicit invalidation, and hard stops — different inputs and downstream routing only.

| Entry | Inputs | Downstream |
|-------|--------|------------|
| `stabilize` | Gate failures + normalized review findings | `/pf-stabilize` → push → `/pf-watch-ci` |
| `debug` | Production signals (Sentry / deploy log / user report) | `/pf-debug` routing → `003` or `002` |

## Shared discipline

1. **Rank hypotheses** — most likely first; evidence for and against each.
2. **Causal-chain gate** — do not propose a fix until trigger → symptom chain is complete, or the user
   explicitly authorizes a best-available hypothesis.
3. **Invalidate explicitly** — a rejected hypothesis is marked invalid; do not retry variants of it.
4. **Hard stops (R29)** — stop when any applies:
   - `maxIterations` (default **5**) reached
   - **No progress** — same top hypothesis + same evidence set on two consecutive iterations
   - **Human decision** — scope/architecture ambiguity blocks a minimal fix
5. **Output shape** — see below; debug adds `routingHint` after U4 classifies fix size.

## Stabilize entry procedure

1. Collect failing check names + logs from gate JSON (`scripts/check-gate.sh`).
2. Collect normalized findings from `review.provider` adapter (inline threads + non-inline bodies).
3. Run the **shared discipline** (hypotheses → gate → fix proposal).
4. Propose minimal fix per top surviving hypothesis; verify against frozen spec / PRD amendments union.
5. Stop when gate returns `green` or stabilize loop hard-stop triggers.

## Debug entry procedure

Inputs: normalized signal per `references/debug-inputs.md` + optional repo context.

1. **Redact** all signal text through `bash scripts/memory-redact.sh` before analysis or memory.
2. `memory-preflight` read: prior `debug` memories for `relatedFiles` / failing area.
3. Enrich Sentry signals per `skills/debug/references/sentry.md` when `type == sentry`.
4. Form ranked hypotheses from signal evidence (stack, breadcrumbs, log excerpt, user report).
5. Run the **shared discipline** — attempt repro-from-context but proceed without local repro if blocked.
6. Emit root cause + proposed fix + verification plan.
7. **Do not implement or merge** — hand off to `/pf-debug` routing (scoped phase vs brainstorm/amendment).

### Debug vs stabilize

| | Stabilize | Debug |
|---|-----------|-------|
| Trigger | In-loop CI/review on a PR | Post-ship production signal |
| Repro | Required via failing checks/tests | Attempted from context; not required |
| Fix execution | In-loop commit/push | Routed to `003`/`002`; never auto-merged |

## Output shape

```markdown
## Hypotheses
1. [hypothesis] — evidence for / against (invalidated hypotheses marked)

## Causal chain
trigger → … → symptom

## Root cause
[one sentence]

## Recommended fix
[minimal change — scope estimate for routing]

## Verification
[how to confirm in prod/staging]

## Routing hint (debug only)
small | substantial — rationale
```
