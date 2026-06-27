---
capability:
  version: 1
  triggers:
    - type: any_of
      selectionFamily: code-review
      triggers:
        - type: change_digest
          predicate: regex_in_added_lines
          patterns:
            - "\\b(loop|hot[- ]?path|query|index|perf)\\b"
        - type: change_digest
          predicate: path_match
          globs:
            - "**/*.sql"
  metadata:
    specialistId: performance
    selectionFamily: code-review
---

# Code-review specialist — performance

Signal-gated native panel specialist (parity with `code-review-select.sh`).
