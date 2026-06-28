---
date: 2026-06-27
amends: docs/prds/027-deliver-terminal-finalization-robustness/027-prd-deliver-terminal-finalization-robustness.md
retracts: [D1, D2, D3, D4, D5, D6, D7]
frozen: false
---

# Amendment A1: exclude Decision-Log IDs from the requirement union

## Overview

The parent PRD 027 authored its Decision Log as enumerated `- **D1**` … `- **D7**` bullets. The shared
`scripts/spec-union.sh` extractor treats that `- **D<n>**` syntax as requirement IDs (it is dual-purpose for
PRDs and decision records), so the effective requirement union for PRD 027 wrongly includes D1–D7 alongside the
real requirements R1–R13. At task-freeze this makes `scripts/traceability-check.sh` fail closed (exit 20):
the traceability table maps only requirement IDs (`^R\d+$`), so D1–D7 can never be "covered" and the gate
blocks — a failure unfixable from the task list.

This amendment uses the sanctioned post-freeze correction path to **exclude D1–D7 from the effective
requirement union** via `retracts:`. It is a bookkeeping correction of a parser mis-classification, not a
change to the specification. The parent file stays byte-stable (per `/sw-amend`).

## Context

- Parent requirements are **R1–R13** (unchanged by this amendment).
- Parent Decision Log entries **D1–D7** are *decisions*, not requirements; they were never intended to enter
  the requirement union, and they generate no tasks or tests.
- Root cause is the shared doc-format parser (GAP-045). The durable fix is PRD 031's shared tokenizer, which
  makes the `- **D<n>**` form harmless; this amendment is the **bridge** until that lands. Per PRD 031 R28,
  such supersession/exclusion edges are reversible, so this amendment can be retired once the tokenizer ships.
- A tooling change to the gate was explicitly declined for this work; the correction is therefore made in the
  spec graph (amendment), leaving `scripts/spec-union.sh` / `scripts/traceability-check.sh` untouched.

## Goals

1. Make the PRD 027 requirement union resolve to exactly R1–R13 so `traceability-check` passes at task-freeze.
2. Preserve the parent verbatim and preserve every decision D1–D7 in force.

## Non-Goals

- Changing, adding, or removing any requirement (R1–R13 are untouched).
- Retracting, weakening, or re-deciding any Decision-Log decision — D1–D7 remain authoritative as written.
- Editing the parent file (never written per `/sw-amend`).
- Changing the shared parser / gate tooling (deferred to PRD 031).

## Requirements

No new requirements are introduced and none are modified. This amendment carries a single frontmatter
directive, `retracts: [D1, D2, D3, D4, D5, D6, D7]`, whose sole effect is to drop the mis-extracted
Decision-Log IDs from the effective requirement union. The decisions they label are unchanged.

## Testing Strategy

- `bash scripts/spec-union.sh <parent-prd>` resolves `requirements` to exactly R1–R13 (D1–D7 appear under
  `retracted`, not `requirements`).
- `bash scripts/traceability-check.sh --prd <parent-prd> --tasks <task-list>` returns `complete` (exit 0)
  with R1–R13 fully covered.
- Existing PRD-level `spec-rigor-check` on the parent and on this amendment remains green.

## Documentation deliverables (amendment delta)

None beyond the INDEX amendment-link refresh registered at freeze. No user-guide, dist, or skill surface is
affected (no requirement or tooling change).

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Amend rather than edit/un-freeze the parent | Freeze is irreversible and `check-frozen.sh` (non-bypassable CI) blocks any modification to a frozen artifact; an amendment is the sanctioned post-freeze correction with the parent left byte-stable. |
| DL-2 | Use `retracts: [D1..D7]` to fix the union, not a tooling change | A gate/parser change was explicitly declined and is owned by PRD 031; `retracts` corrects the *effective union* without touching shared scripts. |
| DL-3 | Frame as a parser-misclassification correction, not a decision retraction | D1–D7 are decisions, never requirements; only their spurious extraction as requirement IDs is removed. The decisions remain in force verbatim in the parent. |
| DL-4 | Treat as a reversible bridge to PRD 031 | PRD 031's shared tokenizer makes `- **D<n>**` harmless; per PRD 031 R28 the edge is reversible, so this amendment can be retired post-031 with no spec loss. |

## Open Questions

None.
