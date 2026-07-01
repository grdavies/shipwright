---
date: 2026-07-01
topic: fixture-brainstorm-pass
---

# Fixture — compliant brainstorm

## Summary

Minimal compliant brainstorm for spec-rigor positive case.

## Problem Frame

Gate should accept all required sections and monotonic R-IDs.

## Key Decisions

- **D1** Keep the fixture minimal while satisfying every required heading.

## Requirements

- **R1** The gate must pass when all required sections are present.
- **R11** Non-contiguous R-ID numbering after an amendment boundary is permitted.

## Success Criteria

- `spec-rigor-check.py --artifact brainstorm` exits 0 on this document.

## Scope Boundaries

- Non-goals: parity with the full unified-dev-workflow exemplar.

## Open Questions

- none
