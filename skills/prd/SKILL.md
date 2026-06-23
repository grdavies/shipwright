---
name: pf-prd
description: Generate a PRD draft from a brainstorm doc (Full) or triaged request (Standard). Does not freeze, run persona review, or generate tasks.
---

# PRD draft (`/pf-prd`)

Port of v1 `spec-prd` under `pf-`. Freeze and task generation are separate steps.

## Sections (required)

1. Overview
2. Goals
3. Non-Goals
4. Requirements (stable R-IDs; carry forward from brainstorm when present)
5. Technical Requirements
6. Security & Compliance
7. Testing Strategy
8. Rollout Plan
9. Decision Log
10. Open Questions

## Path

`prds/<n>-<slug>/<n>-prd-<slug>.md` per `docs/layout.md`.

## Tier routing

- **Full:** require brainstorm doc path as input; refuse to draft without it (R6 ordering).
- **Standard:** accept triaged request directly (no brainstorm required).

## Collision policy

- Same feature, new run: increment `<n>`, distinct slug; do not overwrite.
- Update existing: edit in place only with explicit user confirmation + Decision Log entry.
- Default: never overwrite without confirmation.

## Numbering

Scan `prds/` for highest `<n>`, increment, zero-pad to 3 digits.

## Handoff

→ `/pf-doc-review` (not `/pf-freeze` or `/pf-tasks`). Resolve Open Questions before freeze (spec-rigor clarify gate on Full tier).

## Open questions

GitHub tracking-issue convention deferred to implementation workstream (`003`). Default: index + git are the status source — no issue opened unless user requests.
