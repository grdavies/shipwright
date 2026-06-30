---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: quality.provider
      equals: "none"
  metadata:
    providerFamily: quality
    adapterId: none
    selectionFamily: providers
    gateRef: check-gate.py
---

# quality adapter: `none`

Structural-quality harness disabled. `scripts/quality-provider.py` selects this when `quality.provider` is
`none` or unset. Emits `verdict: none` (`quality:none`) — **zero loop-behavior change** (SC5).
