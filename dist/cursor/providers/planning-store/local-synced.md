---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: planning.store.backend
      equals: "local-synced"
  metadata:
    providerFamily: planning-store
    adapterId: local-synced
    selectionFamily: providers
---

# Planning store adapter: local/synced

Bodies are stored under `planning.store.localSynced.path` (one file per unit id). Documented as
convenience-not-security; not the public-repo template default. Doctor validates path containment,
rejects symlinks/`..`, enforces mode `0700`, and warns on known cloud-sync roots.
