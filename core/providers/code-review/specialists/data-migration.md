---
capability:
  version: 1
  triggers:
    - type: change_digest
      selectionFamily: code-review
      predicate: path_match
      globs:
        - "**/migrations/**"
        - "**/migrate/**"
        - "**/schema.sql"
        - "*backfill*"
  metadata:
    specialistId: data-migration
    selectionFamily: code-review
---

# Code-review specialist — data-migration

Signal-gated native panel specialist (parity with `code-review-select.py`).
