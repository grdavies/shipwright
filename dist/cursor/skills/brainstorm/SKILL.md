---
name: sw-brainstorm
description: Explore requirements through one-question-at-a-time dialogue, then write a requirements document with stable R-IDs. Use for Full-tier work before PRD drafting.
---

# Brainstorm (`/sw-brainstorm`)

Full-tier requirements exploration. Produces a brainstorm doc for `/sw-prd`. Does **not** draft a PRD.

## Core principles

1. **One question per turn** — prefer single-select blocking questions.
2. **Investigate before asking** — on clear inputs, read repo context first.
3. **Synthesis checkpoint** — restate scope and decisions before writing any file.
4. **Full fidelity** — requirements authoring uses complete prose (R30/R31).
5. **Pipeline order** — never draft a PRD in this stage.

## Procedure

### Phase 1: Assess and explore

1. Read `.sw/layout.md` for output path.
2. If input is vague, ask one clarifying question (blocking tool preferred).
3. Explore alternatives; challenge assumptions; resolve product decisions here.
4. Run synthesis checkpoint: restate scope, tier, key decisions; confirm with user before write.

### Phase 2: Write requirements doc

1. Load `skills/brainstorm/references/requirements-sections.md`.
2. Write to `docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md`.
3. Assign stable R-IDs; include all required sections.
4. Report path and next step: `/sw-prd` (after `/sw-freeze` if freezing brainstorm first).

## Guardrails

- No PRD output in this stage.
- No `frozen: true` unless user explicitly runs `/sw-freeze` afterward.
- Repo-relative paths only in the document.
- Resume existing brainstorm: update in place after user confirms.

## Handoff

→ `/sw-prd` (Full path requires this doc as input).
