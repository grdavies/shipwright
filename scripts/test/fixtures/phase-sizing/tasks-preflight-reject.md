---
prd: docs/prds/040-phase-granularity-parallelism/040-prd-phase-granularity-parallelism.md
date: 2026-06-30
topic: phase-sizing-preflight-reject-max
visibility: local
frozen: false
---
# Tasks — preflight width-1 collapse fixture

## Tasks

### 1. Generator contention — forced serial split

- [ ] 1.1 Touch dist tree
  - **File:** `dist/cursor/scripts/wave_deliver.py`
- [ ] 1.2 Touch core mirror
  - **File:** `core/scripts/wave_deliver.py`
  - Run `python3 -m sw generate --all` after edits.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R17 | 1.1 | phase-sizing-preflight-reject-cycle-or-max |

## Relevant Files

- `dist/cursor/scripts/wave_deliver.py`
- `core/scripts/wave_deliver.py`
