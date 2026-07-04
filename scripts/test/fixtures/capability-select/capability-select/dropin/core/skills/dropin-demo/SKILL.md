---
name: dropin-demo
capability:
  version: 1
  triggers:
    - type: text_token
      selectionFamily: doc-review
      source: body_snapshot
      match: whole_token
      tokens:
        - dropin-marker
  metadata:
    skill: dropin-demo
    selectionFamily: doc-review
---
