---
description: Explore requirements through collaborative dialogue and write a brainstorm requirements doc. Does not draft a PRD or run the persona panel.
alwaysApply: false
---

# `/pf-brainstorm`

Full-tier brainstorm stage. Produces `docs/brainstorms/...-requirements.md` with stable R-IDs.

## Scope

- Input: feature idea, problem, or vague request (Full tier).
- Output: requirements document per `skills/brainstorm/references/requirements-sections.md`.
- Does **not** produce a PRD, run persona review, or freeze (use `/pf-freeze` separately).

## Procedure

1. Load `skills/brainstorm/SKILL.md` and follow its phases.
2. One question per turn; synthesis checkpoint before any file write.
3. Write requirements doc to path in `.pf/layout.md`.
4. Report output path; next step is `/pf-prd` (not `/pf-tasks`).

## Guardrails

- Pipeline-order guard: refuse to draft a PRD in this command.
- Full-fidelity authoring — no caveman/terse compression on requirements text.
- Freezing is a separate explicit step via `/pf-freeze`.
