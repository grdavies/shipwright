---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: planning.store.issuesProvider
      equals: "none"
  metadata:
    providerFamily: issues
    adapterId: none
    selectionFamily: providers
    gateRef: check-gate.py
---

# Issues provider: none

Selected when `planning.store.issuesProvider` is `none` or unset while `planning.store.backend` is
`issue-store`.

## Behavior (R3)

All issue verbs are unavailable. The planning store **falls back** to `in-repo-public` file-store with a
documented notice — work is never blocked.

No token probe runs for this adapter.

