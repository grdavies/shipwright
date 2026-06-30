---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: verify.provider
      equals: "playwright"
  metadata:
    providerFamily: verify
    adapterId: playwright
    selectionFamily: providers
    gateRef: check-gate.py
---

# verify adapter: `playwright`

Runs `npx playwright test` when a Playwright config file exists at repo root. Skips (non-blocking) when absent.

Optional `verifyE2e.routes` in config supplies a `--grep` hint for affected-route smoke. Full suite runs when
routes are empty.

Logs tee to `/tmp/sw-verify.e2e.log`.
