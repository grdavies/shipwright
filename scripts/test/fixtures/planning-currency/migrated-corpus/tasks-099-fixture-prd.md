---
date: 2026-01-01
frozen: true
frozen_at: 2026-01-01
---
# Tasks — Fixture PRD

### 1. Migrated corpus regression — S

- [ ] 1.1 Immutability gate (R1)
  - **File:** `scripts/spec-rigor-check.sh`
  - **Expected:** frozen PRD passes structural + checklist gates.
- [ ] 1.2 Traceability gate (R2, R3)
  - **File:** `scripts/traceability-check.sh`
  - **Expected:** every R-ID maps to a task ref and named scenario.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | no-regression-migrated-corpus |
| R2 | 1.2 | no-regression-migrated-corpus |
| R3 | 1.2 | no-regression-migrated-corpus |
