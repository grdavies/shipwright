---
capability:
  version: 1
  triggers:
    - type: any_of
      selectionFamily: code-review
      triggers:
        - type: change_digest
          predicate: path_match
          globs:
            - "*.md"
            - "*.mdx"
        - type: change_digest
          predicate: regex_in_added_lines
          patterns:
            - "^\\s*(//|#|/\\*|\\*|\"\"\"|''')"
  metadata:
    specialistId: comment-accuracy
    selectionFamily: code-review
---

# Code-review specialist — comment-accuracy

Signal-gated native panel specialist (parity with `code-review-select.sh`).
