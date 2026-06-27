---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: verify.provider
      equals: "stub"
  metadata:
    providerFamily: verify
    adapterId: stub
    selectionFamily: providers
    gateRef: check-gate.sh
---

# verify adapter: `stub`

Writes a passing log to `/tmp/sw-verify.e2e.log` and returns `status: complete`. Use in fixture tests and repos
without browser E2E.
