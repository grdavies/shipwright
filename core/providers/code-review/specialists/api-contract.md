---
capability:
  version: 1
  triggers:
    - type: any_of
      selectionFamily: code-review
      triggers:
        - type: change_digest
          predicate: regex_in_path
          patterns:
            - "openapi"
            - "swagger"
            - "\\.proto$"
            - "graphql"
            - "/routes?/"
            - "handler"
            - "/api/"
            - "\\.openapi\\."
        - type: change_digest
          predicate: regex_in_added_lines
          patterns:
            - "openapi"
            - "swagger"
            - "\\.proto$"
            - "graphql"
            - "/routes?/"
            - "handler"
            - "/api/"
            - "\\.openapi\\."
  metadata:
    specialistId: api-contract
    selectionFamily: code-review
---

# Code-review specialist — api-contract

Signal-gated native panel specialist (parity with `code-review-select.sh`).
