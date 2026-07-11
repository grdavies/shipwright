---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: any_of
        selectionFamily: code-review
        triggers:
          -
            type: change_digest
            predicate: path_match
            globs:
              - "*.d.ts"
          -
            type: change_digest
            predicate: regex_in_added_lines
            patterns:
              - "\\b(interface|type|class|struct|enum)\\b"
    metadata:
      specialistId: type-design
      selectionFamily: code-review
---

# Code-review specialist — type-design

Signal-gated native panel specialist (parity with `code-review-select.py`).
