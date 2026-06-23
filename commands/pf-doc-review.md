---
description: Review a PRD draft with parallel persona sub-agents and apply safe fixes via synthesizer. Does not freeze artifacts or generate tasks.
alwaysApply: false
---

# `/pf-doc-review`

Persona panel + synthesis for PRD drafts (and amendment drafts per U7).

## Scope

- Input: PRD draft path + tier (from triage or user).
- Output: reviewed PRD with safe_auto fixes applied; gated/manual items surfaced.
- Does **not** freeze, generate tasks, or run on Quick-tier work.

## Procedure

1. Load `skills/doc-review/SKILL.md`.
2. If tier is Quick, report "no panel for Quick" and stop.
3. Announce selected personas and why.
4. Dispatch tier-selected `agents/pf-*-reviewer.md` personas as parallel sub-agents (full PRD each).
5. On partial failure, log and continue with remaining personas.
6. Synthesize per `skills/doc-review/references/synthesis.md` (max 2 rounds).
7. Apply safe_auto; present gated_auto/manual for user decision.
8. Report result; next step `/pf-freeze` when clear.

## Guardrails

- Full tier: seven personas in parallel.
- Standard: coherence + scope-guardian minimum.
- Findings failing schema validation are dropped.
- Synthesis loop hard-stops at max rounds / no-progress.
