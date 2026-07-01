---
frozen: false
topic: missing-deps-sequential
---
# Task list — missing Phase Dependencies, no file overlap

## Tasks

### 1. First phase

- [ ] 1.1 Edit module A (R1)
  - **File:** `scripts/module_a.py`
  - **Expected:** edit A
  - **R-IDs:** R1

### 2. Second phase

- [ ] 2.1 Edit module B (R1)
  - **File:** `scripts/module_b.py`
  - **Expected:** edit B
  - **R-IDs:** R1

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | sequential fallback |
