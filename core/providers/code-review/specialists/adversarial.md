---
capability:
  version: 1
  triggers:
    - type: any_of
      selectionFamily: code-review
      triggers:
        - type: change_digest
          predicate: executable_lines_gte
          threshold: 50
        - type: change_digest
          predicate: regex_in_added_lines
          patterns:
            - "\\b(auth|payment|stripe|mutation|external.api|webhook)\\b"
  metadata:
    specialistId: adversarial
    selectionFamily: code-review
---

# Code-review specialist — adversarial

Signal-gated native panel specialist (parity with `code-review-select.py`).
