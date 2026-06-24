---
date: 2026-06-22
topic: memory-single-source-of-truth
frozen: true
frozen_at: 2026-06-23
---
# Memory as single source of truth (R32)

## Context

phase-flow v2 needs one evolving knowledge layer for doctrine, decisions, and learnings. A parallel repo doctrine layer would duplicate the store and create conflict-of-authority with the memory provider.

## Decision

- **D1** All evolving project doctrine, decisions, and learnings live only in the swappable memory system with relationships first-class
- **D2** Plugin behavior rules and frozen/living artifacts stay in the repo as version-controlled deliverables — not accumulated knowledge
- **D3** Decision records (`decisions/`) are frozen file deliverables; `decision`-class memory links via `relatedFiles`, never copies body content

## Rationale

Single store avoids rot and authority conflicts. Frozen artifacts (PRDs, decision records) remain CI-enforceable deliverables; memory points at them.

## Alternatives

- Repo `docs/solutions/` doctrine layer — rejected (competing store)
- Memory-native decision records — rejected (no CI freeze, no before-build review)

## Consequences

`/pf-compound` writes through memory seam only. Cross-cutting decisions get addressable frozen records per plan 006.
