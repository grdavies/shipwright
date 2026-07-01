---
frozen: false
topic: missing-deps-overlap
---
# Task list — missing Phase Dependencies with file overlap

## Tasks

### 1. Touch shared file

- [ ] 1.1 Edit shared module (R1)
  - **File:** `scripts/shared_module.py`
  - **Expected:** first edit
  - **R-IDs:** R1

### 2. Also touch shared file

- [ ] 2.1 Edit same module (R1)
  - **File:** `scripts/shared_module.py`
  - **Expected:** second edit
  - **R-IDs:** R1

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | overlap fallback |
