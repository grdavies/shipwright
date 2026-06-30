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

0. **Authoring-guard preflight (PRD 032 R5/R14)** — before the first substantive mutation on a planning unit, run `python3 scripts/authoring-guard.py preflight --path <unit-artifact> --command sw-prd`; on a genuinely in-flight unit, pass `--handoff <reason>` instead of mutating (R6).
1. Read `workflow.config.json` (`prdsDir`, `decisionsDir`); load `skills/prd/SKILL.md`.
2. **Pre-work search (mandatory)** — before the first substantive mutation, run `memory-preflight` **pre-work
   search** per `skills/memory/SKILL.md` **Pre-work search (mandatory)** (scoped to the feature domain and
   deliverable paths; classes `rule`, `decision`, `learning`, `code-context`, `design` via
   `providers/<memory.provider>.md` — no direct provider call). Surface hits and reconcile applicable
   rules/contradicting decisions before drafting.
3. Resolve `--type` (default `prd`) and section contract from the skill.

   - **Pull-in proposal (R1/R17):** before drafting, run
     `python3 scripts/planning-related.py scan --mode creation --path <unit-artifact>`; surface the
     **confirm-list** (never auto-absorb). Flag stale/already-resolved candidates; human confirms via
     `python3 scripts/planning-related.py confirm --path <unit-artifact> --accept <id>[,...]`. Frozen targets
     route to amendment without `--accept-frozen-impact`.
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
   - **Structural canonicalization (R14):** before persisting the draft, pipe body output through
     `python3 scripts/doc-format-normalize.py --write --inplace <path>` so non-canonical structural shape cannot
     reach freeze; slot-filling templates are available via
     `python3 scripts/doc_format.py template prd_requirement` (and related kinds in `doc_format.SLOT_TEMPLATES`).
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

**Model tier:** deep — resolve via `python3 scripts/resolve-model-tier.py --command sw-prd`.

## Guardrails

- **Complete-unit refusal (R9):** mutations under a `status: complete` unit folder are rejected by the
  completed-unit immutability hook (`core/hooks/pre-commit-completed-unit.py`; see `/sw-freeze`).
- PRD Full path: no PRD without brainstorm doc (`--type prd` only).
- No `frozen: true` in this step — freeze is `/sw-freeze`.
- No GitHub tracking issue by default (deferred to `003`).
- Default `--type prd` behavior unchanged from prior `sw-prd` contract.


## Issue-store mode (PRD 043)

When `planning.store.backend` is `issue-store` (effective):

1. Persist PRD drafts via the planning store (`sw:prd` issues) — do not author stub files under `docs/prds/`.
2. Carry brainstorm linkage in the PRD `sw-edges` block and via
   `python3 scripts/planning_store.py link-brainstorm-prd`.
3. Task lists (`sw:tasks`) and gap units (`sw:gap`) use the same store interface.

Decision records (`--type decision`) remain file-native (D8).
