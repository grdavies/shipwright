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
            predicate: regex_in_added_lines
            patterns:
              - "\\b(retry|timeout|concurrency|error.handling|catch|rescue|panic)\\b"
          -
            type: change_digest
            predicate: regex_in_added_lines
            patterns:
              - "\\b(silent|swallow|ignored.rejection|empty.catch|log.and.continue)\\b"
    metadata:
      specialistId: reliability
      selectionFamily: code-review
---

# Code-review specialist — reliability

Signal-gated native panel specialist (parity with `code-review-select.py`).
