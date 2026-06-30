---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: verify.provider
      equals: "none"
  metadata:
    providerFamily: verify
    adapterId: none
    selectionFamily: providers
    gateRef: check-gate.py
---

# verify adapter: `none`

E2E/smoke verification disabled. `scripts/verify-e2e.py` selects this when `verifyE2e.provider` is `none` or
`verifyE2e.enabled` is `false`.
