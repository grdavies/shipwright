---
description: Generate a PRD draft from a brainstorm doc (Full) or triaged request (Standard). Does not freeze, run persona review, or generate tasks.
alwaysApply: false
---

# `/pf-prd`

PRD draft stage. Writes to `prds/<n>-<slug>/<n>-prd-<slug>.md`.

## Scope

- Input: brainstorm doc path (Full) or Standard-tier feature description.
- Output: PRD draft with required sections and stable R-IDs.
- Does **not** freeze, run `/pf-doc-review`, or generate tasks.

## Procedure

1. Read `workflow.config.json` (`prdsDir`); load `skills/prd/SKILL.md`.
2. Resolve tier:
   - **Full:** require brainstorm doc; refuse if missing (ordering guard).
   - **Standard:** accept triaged request directly.
3. `memory-preflight` read for prior decisions in the feature domain.
4. Ask clarifying questions if scope ambiguous; proceed when brainstorm provides enough context.
5. Assign PRD number per collision policy in `docs/layout.md`.
6. Draft all required sections; carry forward brainstorm R-IDs where present.
7. Self-audit for consistency, edge cases, gaps.
8. Save to `prds/<n>-<slug>/<n>-prd-<slug>.md`.
9. Report path; next step `/pf-doc-review`.

## Guardrails

- Full path: no PRD without brainstorm doc.
- No `frozen: true` in this step — freeze is `/pf-freeze`.
- No GitHub tracking issue by default (deferred to `003`).
