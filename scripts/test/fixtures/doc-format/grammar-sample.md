---
date: 2026-06-27
topic: sample
absorbs:
  - GAP-045
supersedes: [R2]
retracts: [R1]
frozen: true
---

# Sample PRD

## Overview

Body text.

## Requirements

- **R11** Tokenizer defines canonical grammar.
- **D1** Decision bullet for union tests.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |

### 1. Shared doc-format tokenizer engine — L

- [ ] 1.1 Module
  - **File:** `scripts/doc_format.py`, `scripts/doc-format-normalize.py`
  - **Expected:** tokenize/emit API.

### 2. Adoption — L

- [ ] 2.1 Check modes
  - **File:** `scripts/doc_format.py`

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R11 | 1.1 | doc-format-grammar-tokenizes |
| R22 | 1.2 | call-site-map-exhaustion |
