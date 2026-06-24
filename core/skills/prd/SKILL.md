---
name: sw-prd
description: Generate a PRD or decision-record draft (Full/Standard). Does not freeze, run persona review, or generate tasks.
---

# PRD / decision-record draft (`/sw-prd`)

Port of v1 `spec-prd` under `sw-`. Freeze and task generation are separate steps. Generalized into a typed frozen-deliverable author via `--type`.

## Deliverable types

| `--type` | Path | ID namespace | Brainstorm guard |
|----------|------|--------------|------------------|
| `prd` (default) | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | R-IDs | Full tier requires brainstorm |
| `decision` | `docs/decisions/<n>-<slug>.md` | D-IDs | optional (up-front decisions) |

## PRD sections (required, `--type prd`)

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

## Decision-record sections (required, `--type decision`)

1. Context
2. Decision (stable D-IDs as bullets: `- **D1** ...`)
3. Rationale
4. Alternatives
5. Consequences

The decision section contract must stay in lockstep with `scripts/spec-rigor-check.sh --artifact decision`.

## Path

- PRD: `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` per `.sw/layout.md`.
- Decision: `docs/decisions/<n>-<slug>.md` per `.sw/layout.md`.

## Tier routing (PRD only)

- **Full:** require brainstorm doc path as input; refuse to draft without it (R6 ordering).
- **Standard:** accept triaged request directly (no brainstorm required).

## Collision policy

- Same feature/topic, new run: increment `<n>`, distinct slug; do not overwrite.
- Update existing: edit in place only with explicit user confirmation + Decision Log entry (PRD) or amendment (frozen decision).
- Default: never overwrite without confirmation.
- Refuse to draft over an existing **frozen** decision record without explicit confirmation.

## Numbering

- PRD: scan `docs/prds/` for highest `<n>`, increment, zero-pad to 3 digits.
- Decision: scan `docs/decisions/` for highest `<n>`, increment, zero-pad to 3 digits — **separate counter**.

## Handoff

→ `/sw-doc-review` (not `/sw-freeze` or `/sw-tasks`). Resolve Open Questions before freeze (spec-rigor clarify gate on Full tier PRDs).

## Open questions

GitHub tracking-issue convention deferred to implementation workstream (`003`). Default: index + git are the status source — no issue opened unless user requests.
