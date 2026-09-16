---
name: decoy
capability:
  version: 1
  triggers:
    - type: text_token
      selectionFamily: doc-review
      source: body_snapshot
      match: whole_token
      tokens:
        - decoy-only-marker
  metadata:
    skill: decoy
    selectionFamily: doc-review
---

# Decoy source-tree skill (must not drive installed freshness)
