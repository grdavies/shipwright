---
date: 2026-07-02
amends: docs/prds/046-issue-store-planning-graph/046-prd-issue-store-planning-graph.md
absorbs: [gap-020-planning-index-gen-replace-region-inner-omits-n]
signal: feedback-recallium-debug-2026-07-02
frozen: true
frozen_at: 2026-07-02
visibility: public
---

# Amendment A4: planning_index_gen region-marker newline invariant (gap-020)

## Overview

`gap-020` captures a recurring INDEX seam corruption defect observed during feedback-session INDEX maintenance
(2026-07-02): `planning_index_gen.replace_region_inner` splices region markers without a newline after the
start marker, gluing `<!-- planning-index:structural begin -->` onto the gap table header row in
`docs/prds/INDEX.md`. Every `planning_index_gen generate` (and reconciler paths that splice via the same
helper) re-corrupts the dual-region boundary. Recallium #2300 documents the failure mode; manual repair is
required after each generate.

Parent PRD 046 phases 1–2 depend on `planning_index_gen.py` for issue-derived INDEX projection (R25, R88) and
shared `discover_units` wiring (R83). Amendments A1–A3 guarded committed **write** paths and terminal
**status currency**; they do not fix the **splice** contract for region markers. PRD 031 R9/R24 shipped the
dual-region generator but left this helper defect unshipped.

This amendment extends phase-1 INDEX generator work with **R100–R103** and schedules **gap-020** for closure
when green fixtures ship — not narrative closure.

## Context

**Evidence (2026-07-02):**

- After `planning_index_gen generate`, structural `begin` marker appeared on the same line as
  `| id | type | title | status | visibility | edges |`.
- Manual repair: marker on its own line before the gap table header.
- Recurs on every generate until `replace_region_inner` is fixed.

**Root cause:**

```131:138:scripts/planning_index_gen.py
def replace_region_inner(content: str, region: str, new_inner: str) -> str:
    ...
    return pre + start + new_inner + end + post
```

```124:126:scripts/planning_index_gen.py
def render_region(region: str, body: str) -> str:
    start, end = REGION_MARKERS[region]
    return f"{start}\n{body}{end}"
```

**Relationship to PRD 031:** R9 read-merge-write and R24 deterministic generator are shipped; this is a
robustness defect in the splice helper, not a missing feature. PRD 046 is the natural schedule host because
046 owns ongoing `planning_index_gen` evolution for issue-store INDEX derivation (tasks 1.1, 1.3, 2.1).

**Relationship to A1–A3:** Orthogonal — A1–A3 address default-branch commit refusal and terminal status
currency; A4 addresses marker-byte integrity during region inner replacement.

## Goals

1. `replace_region_inner` preserves the same newline contract as `render_region` for all three regions
   (`structural`, `derived`, `inFlight`).
2. `planning_index_gen generate` and reconciler splices no longer glue start markers to inner body content.
3. `index-region-guard.py` (or equivalent) fails closed on glued-marker seam before commit when detectable.
4. `gap-020` flips to `resolved` when R100–R103 ship with green fixtures.

## Non-Goals

- Changing INDEX row semantics, gap lifecycle, or issue-derived projection logic (R25/R82 unchanged).
- Replacing dual-region read-merge-write (PRD 031 R9) or region ownership matrix (R80).
- Fixing legacy `docs/prds/INDEX.md` vs `docs/planning/INDEX.md` path divergence (separate cutover work).

## Requirements

### Phase-1 extension — INDEX region splice invariant

- **R100** (origin: gap-020 remediation #1) — `planning_index_gen.replace_region_inner` MUST insert `\n`
  immediately after the region start marker before `new_inner`, matching `render_region`'s
  `f"{start}\n{body}{end}"` contract for `structural`, `derived`, and `inFlight`. Alternatively, route all
  inner splices through `render_region` and delete the divergent splice path — one canonical implementation
  only.
- **R101** (origin: gap-020 remediation #2) — Fixture `planning-index-region-marker-newline-valid` MUST
  assert that `replace_region_inner` / `planning_index_gen generate` on a fixture INDEX with gap rows leaves
  each `<!-- planning-index:* begin -->` marker on its own line (not glued to table header or inner body).
- **R102** (origin: gap-020 remediation #3) — `index-region-guard.py` MUST fail closed when a staged INDEX
  contains a region start marker immediately followed by non-newline content (glued seam), naming the region
  and remediation (`re-run generate after fix` or `repair marker newline`).
- **R103** (origin: gap-020 closure) — On ship, flip
  `gap-020-planning-index-gen-replace-region-inner-omits-n` unit frontmatter to `resolved` referencing PRD
  046 A4 only after R100–R101 fixtures are green and R102 guard is wired.

## Technical Requirements

- **TR-A4-1** (R100) — Fix `replace_region_inner` in `scripts/planning_index_gen.py` (prefer delegating to
  `render_region` for inner replacement); audit all call sites (`generate`, `planning_graph reconcile`
  projection, legacy `docs/prds/INDEX.md` path) for consistent marker bytes.
- **TR-A4-2** (R101) — Add harness under `scripts/test/run_planning_index_fixtures.py` (or extend existing
  planning-index fixtures) for `planning-index-region-marker-newline-valid`; register in
  `core/sw-reference/pr-test-plan.manifest.json` as `required`.
- **TR-A4-3** (R102) — Extend `scripts/index-region-guard.py` with glued-marker detection using the same
  `REGION_MARKERS` constants as `planning_index_gen.py`; hook remains pre-commit scoped to INDEX paths.
- **TR-A4-4** (R103) — Wire gap flip into PRD 046 ship checklist alongside A1–A3 exit-gate notes.

Roll into parent phase 1 (tasks 1.x) alongside R88 serialized regeneration (task 1.3).

## Testing Strategy

| Fixture | Behavior |
|---------|----------|
| `planning-index-region-marker-newline-valid` | `replace_region_inner` / generate preserves marker-on-own-line for all regions |
| `index-region-guard-glued-marker-refuse` | Staged INDEX with glued `structural begin` marker fails guard closed |

Preserve existing PRD 031 planning-index region-integrity fixtures; no regression to A1
`r80-inflight-projection-refuse-default-branch` or A2 terminal reconcile fixtures.

## Rollout Plan

1. Land TR-A4-1 + R100 (splice fix) — unblocks safe `planning_index_gen generate` without manual seam repair.
2. Land TR-A4-2 + R101 fixture registration.
3. Land TR-A4-3 + R102 guard (fail closed before commit).
4. On ship: flip gap-020 to `resolved`; attach fixture output to PR.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A4-1 | Host gap-020 on **PRD 046 A4** rather than reopening PRD 031 | PRD 031 is `complete`; PRD 046 already owns `planning_index_gen` phase-1/2 evolution |
| DL-A4-2 | Continue amendment R band at **R100–R103** | A1–A3 exhausted R95–R99; A4 adds INDEX splice invariant without modifying frozen A1–A3 text |
| DL-A4-3 | Guard + generator fix, not docs-only workaround | Manual INDEX repair after every generate is not durable for issue-store INDEX derivation |

## Security & Compliance

- Marker-byte integrity only; no new network or secret surface.

## Open Questions

None — gap-020 remediation direction is fully specified.
