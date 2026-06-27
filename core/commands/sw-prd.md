---
description: Generate a PRD or decision-record draft (Full/Standard). Does not freeze, run persona review, or generate tasks.
alwaysApply: false
---

# `/sw-prd`

Typed frozen-deliverable author. Default `--type prd` writes a PRD; `--type decision` writes a decision record.

## Scope

- Input: brainstorm doc path (Full PRD) or triaged request (Standard PRD); decision records accept optional brainstorm.
- Output: PRD draft (`--type prd`, default) or decision record (`--type decision`).
- Does **not** freeze, run `/sw-doc-review`, or generate tasks.

## Flags

- `--type prd|decision` — deliverable family (default: `prd`).

## Procedure

1. Read `workflow.config.json` (`prdsDir`, `decisionsDir`); load `skills/prd/SKILL.md`.
2. **Pre-work search (mandatory)** — before the first substantive mutation, run `memory-preflight` **pre-work
   search** per `skills/memory/SKILL.md` **Pre-work search (mandatory)** (scoped to the feature domain and
   deliverable paths; classes `rule`, `decision`, `learning`, `code-context`, `design` via
   `providers/<memory.provider>.md` — no direct provider call). Surface hits and reconcile applicable
   rules/contradicting decisions before drafting.
3. Resolve `--type` (default `prd`) and section contract from the skill.
4. **PRD (`--type prd`, default):**
   - Resolve tier:
     - **Full:** require brainstorm doc; refuse if missing (ordering guard).
     - **Standard:** accept triaged request directly.
   - Assign PRD number per collision policy in `.sw/layout.md` (scan `docs/prds/`).
   - Draft all required PRD sections; carry forward brainstorm R-IDs where present.
   - **Frontmatter linkage (Full tier, R52):** write the back-reference via
     `python3 scripts/doc_link.py write-backref --brainstorm <path> --prd <path>` (sets canonical
     `brainstorm:` in PRD frontmatter).
   - **Forward reference (R53):** when the source brainstorm is not frozen, append the PRD path to the
     brainstorm `prd:` field (list when multiple) via
     `python3 scripts/doc_link.py write-forwardref --brainstorm <path> --prd <path>`; skip when frozen.
   - Save to `docs/prds/<n>-<slug>/<n>-prd-<slug>.md`.
5. **Decision record (`--type decision`):**
   - Brainstorm optional — decisions are authored up-front; **do not** apply the "no doc without brainstorm" guard.
   - Assign decision number per collision policy (scan `docs/decisions/` — separate counter from `docs/prds/`).
   - Draft all required decision sections with stable D-IDs.
   - Refuse to overwrite an existing frozen decision record without explicit user confirmation.
   - Save to `docs/decisions/<n>-<slug>.md`.
6. Ask clarifying questions if scope ambiguous; proceed when input provides enough context.
7. Self-audit for consistency, edge cases, gaps.
8. Report path; next step `/sw-doc-review`.

**Communication intensity:** lite

**Model tier:** deep — resolve via `bash scripts/resolve-model-tier.sh --command sw-prd`.

## Guardrails

- PRD Full path: no PRD without brainstorm doc (`--type prd` only).
- No `frozen: true` in this step — freeze is `/sw-freeze`.
- No GitHub tracking issue by default (deferred to `003`).
- Default `--type prd` behavior unchanged from prior `sw-prd` contract.
