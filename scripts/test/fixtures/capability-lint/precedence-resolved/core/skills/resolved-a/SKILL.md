---
name: resolved-a
capability:
  version: 1
  precedence:
    tier: override
    priority: 0
  triggers:
    - type: path_glob
      selectionFamily: doc-review
      globs:
        - "docs/**/*.md"
---
