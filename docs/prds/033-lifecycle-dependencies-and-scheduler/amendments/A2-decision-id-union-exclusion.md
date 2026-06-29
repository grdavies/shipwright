---
date: 2026-06-29
amends: docs/prds/033-lifecycle-dependencies-and-scheduler/033-prd-lifecycle-dependencies-and-scheduler.md
retracts: [D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12]
frozen: false
---

# Amendment A2: exclude Decision-Log IDs from the requirement union

## Overview

The parent PRD 033 authored its Decision Log as enumerated `- **D1** … - **D12**` bullets. The shared
`scripts/spec-union.sh` extractor treats that `- **D<n>**` syntax as requirement IDs (it is dual-purpose for
PRDs and decision records), so the effective requirement union for PRD 033 wrongly includes D1–D12 alongside
the real requirements (parent R1–R28 plus amendment A1 R29–R36). At task-freeze this makes
`scripts/traceability-check.sh` and `scripts/spec-rigor-check.sh` fail closed: the traceability table maps
only requirement IDs, so D1–D12 can never be "covered" and the gates block — a failure unfixable from the
task list.

This amendment uses the sanctioned post-freeze correction path to **exclude D1–D12 from the effective
requirement union** via `retracts:`. It is a bookkeeping correction of a parser mis-classification, not a
change to the specification. It mirrors PRD 027 amendment A1 (`decision-id-union-exclusion`).

## Context

- Parent requirements are **R1–R28**; amendment **A1** adds **R29–R36** (post-merge INDEX reconcile safety +
  completion-finalize chokepoint). The effective requirement union is therefore **R1–R36**.
- Parent Decision Log entries **D1–D12** are *decisions*, not requirements; they were never intended to enter
  the requirement union, and they generate no tasks or tests.
- Root cause is the shared doc-format parser (GAP-045). The durable fix is PRD 031's shared tokenizer, which
  makes the `- **D<n>**` form harmless; this amendment is the **bridge** until that lands. Per PRD 031 R28,
  such supersession/exclusion edges are reversible, so this amendment can be retired once the tokenizer ships.
- Sequencing note specific to PRD 033: the parent Decision Log originally used the `- **D<n>.**` (trailing
  period) variant, which the current tokenizer **hard-rejects** (so the union could not be computed at all).
  A format-only normalization (`D1.` → `D1`) of the parent — permitted by the `check-frozen.sh`
  format-normalization exception (semantics provably unchanged) — restores a parseable Decision Log; this A2
  then drops the now-parseable D-IDs from the requirement union. No requirement or decision text changes.

## Goals

1. Make the PRD 033 requirement union resolve to exactly **R1–R36** so `traceability-check` and
   `spec-rigor-check` pass at task-freeze.
2. Preserve the parent's decisions D1–D12 in force (verbatim) — only their spurious extraction as requirement
   IDs is removed.

## Non-Goals

- Changing, adding, or removing any requirement (R1–R36 are untouched).
- Retracting, weakening, or re-deciding any Decision-Log decision — D1–D12 remain authoritative as written.
- Changing the shared parser / gate tooling (deferred to PRD 031).

## Requirements

No new requirements are introduced and none are modified. This amendment carries a single frontmatter
directive, `retracts: [D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12]`, whose sole effect is to drop the
mis-extracted Decision-Log IDs from the effective requirement union. The decisions they label are unchanged.

## Testing Strategy

- `bash scripts/spec-union.sh <parent-prd>` resolves `requirements` to exactly R1–R36 (D1–D12 appear under
  `retracted`, not `requirements`).
- `bash scripts/traceability-check.sh --prd <parent-prd> --tasks <task-list>` returns `complete` (exit 0)
  with R1–R36 fully covered.
- Existing PRD-level `spec-rigor-check` on the parent and on this amendment remains green.

## Documentation deliverables (amendment delta)

None beyond the INDEX amendment-link refresh registered at freeze. No user-guide, dist, or skill surface is
affected (no requirement or tooling change).

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A2-1 | Amend rather than edit/un-freeze the parent's requirement set | Freeze is irreversible; an amendment is the sanctioned post-freeze correction with the parent's requirements left intact. |
| DL-A2-2 | Use `retracts: [D1..D12]` to fix the union, not a permanent parser change | Mirrors PRD 027 A1; the durable parser fix is owned by PRD 031. `retracts` corrects the *effective union* without a behavioral tooling change. |
| DL-A2-3 | Frame as a parser-misclassification correction, not a decision retraction | D1–D12 are decisions, never requirements; only their spurious extraction as requirement IDs is removed. The decisions remain in force verbatim in the parent. |
| DL-A2-4 | Treat as a reversible bridge to PRD 031 | PRD 031's shared tokenizer makes `- **D<n>**` harmless; per PRD 031 R28 the edge is reversible, so this amendment can be retired post-031 with no spec loss. |

## Open Questions

None.
