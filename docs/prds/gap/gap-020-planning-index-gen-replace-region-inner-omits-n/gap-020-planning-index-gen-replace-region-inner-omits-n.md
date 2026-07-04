---
id: gap-020-planning-index-gen-replace-region-inner-omits-n
type: gap
status: resolved
schedule: — (PRD 055)
title: planning_index_gen replace_region_inner omits newline after structural marker
visibility: public
tags: [source:feedback, recallium:2300, signal:feedback-recallium-debug-2026-07-02]
source_pr:
absorbs: []
---

# planning_index_gen replace_region_inner omits newline after structural marker

_Captured from Recallium debug memory #2300 during `/sw-feedback` Recallium triage (2026-07-02)._

## Summary

Every `planning_index_gen generate` (and callers that splice via `replace_region_inner`) can glue the
`<!-- planning-index:structural begin -->` marker onto the same line as the gap table header row, corrupting
dual-region INDEX boundaries in `docs/prds/INDEX.md`.

## Evidence

- Observed after `planning_index_gen generate` during feedback-session INDEX maintenance (2026-07-02).
- Manual repair: put the structural `begin` marker on its own line before the gap table header.
- Recallium #2300 documents recurrence on every generate.

## Root cause

`replace_region_inner` splices `pre + start + new_inner + end + post` without inserting `\n` after the start
marker. `render_region` (used by `assemble_index`) correctly uses `f"{start}\n{body}{end}"`.

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

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **PRD 031** (complete) | Ships dual-region INDEX generator and read-merge-write seam — this is an unshipped robustness defect in the splice helper |
| **PRD 046** | INDEX write-path safety amendments (A1–A3) — orthogonal; does not fix generator newline |
| **Recallium #2225** | INDEX regression from bare reconcile on main — different failure mode |
| **Recallium #2256** | Living-doc reconcile wiped INDEX — different failure mode |

## Remediation direction

1. Fix `replace_region_inner` to match `render_region` newline contract (or route all splices through `render_region`).
2. Add fixture: generate/regenerate INDEX preserves marker-on-own-line invariant.
3. Extend `index-region-guard.py` (if present) to fail closed on glued seam before commit.

## Schedule

**PRD 046 A4** (`A4-planning-index-gen-region-marker-newline-invariant.md`) — absorbed 2026-07-02.
