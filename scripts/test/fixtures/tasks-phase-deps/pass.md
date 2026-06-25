---
frozen: false
topic: phase-deps-pass
prd: scripts/test/fixtures/tasks-phase-deps/parent-prd.md
---
# Task list — phase dependencies pass fixture

## Tasks

### 1. First phase (S)

- [ ] 1.1 Do first thing (R1)
  - **File:** `example/a.ts`
  - **Expected:** R1 covered
  - **R-IDs:** R1

### 2. Second phase (S)

- [ ] 2.1 Do second thing (R2)
  - **File:** `example/b.ts`
  - **Expected:** R2 covered
  - **R-IDs:** R2

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | tasks-phase-deps-pass: phase 1 row present |
| R2 | 2.1 | tasks-phase-deps-pass: phase 2 depends on 1 |
