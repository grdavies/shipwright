---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: quality.provider
        equals: auto
      -
        type: config_flag
        selectionFamily: providers
        key: quality.provider
        equals: builtin
    metadata:
      providerFamily: quality
      adapterId: builtin
      selectionFamily: providers
      gateRef: check-gate.py
---

# quality adapter: `builtin`

Built-in structural-quality metrics for the host repo primary language (PRD 039 R6). Selected when
`quality.provider` is `auto` or `builtin`. Emits delta-oriented signals for the refactor step.
