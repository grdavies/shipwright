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
2. If input is an amendment draft (`amendments/A<k>-*.md`), dispatch coherence + scope-guardian only (U7) unless
   `--personas` / `--all` override — skip full signal-driven selection.
3. If tier is Quick, report "no panel for Quick" and stop.
4. Run signal-driven selection: announce activation record — five core personas plus any gated personas whose
   signals fired (with matched signal text). Honor `--personas` / `--all` overrides when set.
5. Dispatch selected `agents/pf-*-reviewer.md` personas as parallel sub-agents (full PRD each).
6. On partial failure, log and continue with remaining personas.
7. Synthesize per `skills/doc-review/references/synthesis.md` (max 2 rounds).
8. Apply safe_auto; present gated_auto/manual for user decision.
9. Report result; next step `/pf-freeze` when clear.

## Guardrails

- Non-Quick: five-persona always-on core + signal-gated `security` / `design` (tier does not scale the panel).
- Quick: no panel.
- `--personas` / `--all` overrides are logged in the activation record.
- Findings failing schema validation are dropped.
- Synthesis loop hard-stops at max rounds / no-progress.
