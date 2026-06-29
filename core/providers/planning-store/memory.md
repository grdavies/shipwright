---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: planning.store.backend
      equals: "memory"
  metadata:
    providerFamily: planning-store
    adapterId: memory
    selectionFamily: providers
---

# Planning store adapter: memory

Routes exclusively through the provider-agnostic memory adapter (`memory_sot.resolve_memory_provider`).
Never calls provider MCP tools directly. All bodies pass `scripts/memory-redact.sh` on read and write.
Bans `discussion` and `progress` classes; refuses raw transcript markers. Degrades open when no provider
is configured. Writes are scoped to `memory.project`.
