---
frozen: false
topic: phase-deps-fail
prd: scripts/test/fixtures/tasks-phase-deps/parent-prd.md
---
# Task list — missing Phase Dependencies (should fail spec-rigor)

## Tasks

### 1. Only phase (S)

- [ ] 1.1 Do thing (R1)
  - **File:** `example/a.ts`
  - **Expected:** R1 covered
  - **R-IDs:** R1

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | tasks-phase-deps-fail: missing table |
| R2 | — | intentionally uncovered for union fail |
