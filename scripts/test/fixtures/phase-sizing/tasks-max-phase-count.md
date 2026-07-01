---
prd: docs/prds/040-phase-granularity-parallelism/040-prd-phase-granularity-parallelism.md
date: 2026-06-30
topic: phase-sizing-max-phase-count
visibility: local
frozen: false
---
# Tasks — max phase count fixture

## Tasks

### 1. Phase one
- [ ] 1.1 One
  - **File:** `scripts/p01.py`
### 2. Phase two
- [ ] 2.1 Two
  - **File:** `scripts/p02.py`
### 3. Phase three
- [ ] 3.1 Three
  - **File:** `scripts/p03.py`
### 4. Phase four
- [ ] 4.1 Four
  - **File:** `scripts/p04.py`
### 5. Phase five
- [ ] 5.1 Five
  - **File:** `scripts/p05.py`
### 6. Phase six
- [ ] 6.1 Six
  - **File:** `scripts/p06.py`
### 7. Phase seven
- [ ] 7.1 Seven
  - **File:** `scripts/p07.py`
### 8. Phase eight
- [ ] 8.1 Eight
  - **File:** `scripts/p08.py`
### 9. Phase nine
- [ ] 9.1 Nine
  - **File:** `scripts/p09.py`
### 10. Phase ten
- [ ] 10.1 Ten
  - **File:** `scripts/p10.py`
### 11. Phase eleven
- [ ] 11.1 Eleven
  - **File:** `scripts/p11.py`
### 12. Phase twelve
- [ ] 12.1 Twelve
  - **File:** `scripts/p12.py`
### 13. Splittable overflow — max phase count

- [ ] 13.1 Edit script
  - **File:** `scripts/foo.py`
- [ ] 13.2 Edit docs
  - **File:** `docs/bar.md`

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 5 |
| 7 | 6 |
| 8 | 7 |
| 9 | 8 |
| 10 | 9 |
| 11 | 10 |
| 12 | 11 |
| 13 | 12 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R18 | 13.1 | phase-sizing-max-phase-count-bound |

## Relevant Files

- `scripts/foo.py`
- `docs/bar.md`
