---
description: Explore requirements through collaborative dialogue and write a brainstorm requirements doc. Does not draft a PRD or run the persona panel.
alwaysApply: false
---

# `/sw-brainstorm`

Full-tier brainstorm stage. Produces `docs/brainstorms/...-requirements.md` with stable R-IDs.

## Scope

- Input: feature idea, problem, or vague request (Full tier).
- Output: requirements document per `skills/brainstorm/references/requirements-sections.md`.
- Does **not** produce a PRD, run persona review, or freeze (use `/sw-freeze` separately).

## Procedure

1. Load `skills/brainstorm/SKILL.md` and follow its phases.
2. **Pre-work search (mandatory)** — before the first substantive mutation (including the requirements doc
   write), run `memory-preflight` **pre-work search** per `skills/memory/SKILL.md` **Pre-work search
   (mandatory)** (scoped to the feature domain; classes `rule`, `decision`, `learning`, `code-context`,
   `design` via `providers/<memory.provider>.md` — no direct provider call). Surface hits and reconcile
   applicable rules/contradicting decisions before authoring.
3. One question per turn; synthesis checkpoint before any file write.
4. Write requirements doc to path in `.sw/layout.md`.
5. Report output path; next step is `/sw-prd` (not `/sw-tasks`).

**Communication intensity:** lite

**Model tier:** deep — resolve via `python3 scripts/resolve-model-tier.sh --command sw-brainstorm`.

## Guardrails

- Pipeline-order guard: refuse to draft a PRD in this command.
- Full-fidelity authoring — no caveman/terse compression on requirements text.
- Freezing is a separate explicit step via `/sw-freeze`.
