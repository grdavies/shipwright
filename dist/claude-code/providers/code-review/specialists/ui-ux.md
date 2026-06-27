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
            - "*.tsx"
            - "*.jsx"
            - "*.vue"
            - "*.svelte"
            - "*.css"
            - "*.scss"
            - "*.less"
            - "*.styles.ts"
            - "*.css.ts"
            - "*.swift"
            - "*.kt"
            - "*.dart"
            - "*.storyboard"
            - "*.xib"
            - "**/components/**"
            - "**/ui/**"
            - "**/styles/**"
            - "**/theme/**"
            - "**/res/layout/*.xml"
        - type: change_digest
          predicate: regex_in_added_lines
          patterns:
            - "\\b(styled|makeStyles|createGlobalStyle)\\b"
            - "css`"
  metadata:
    specialistId: ui-ux
    selectionFamily: code-review
---

# Code-review specialist — ui-ux

Signal-gated native panel specialist (parity with `code-review-select.sh`).
