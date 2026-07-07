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

## Local-only cache (21a — PRD 057 R21)

Bodies are cached under `.cursor/sw-memory/planning-bodies/<memory.project>/` — a **local-only, gitignored**
directory (see `.gitignore`). This is a local disk cache, not a provider round-trip: put/get/exists/
materialize never call `memory.provider` (or any other provider) to store or retrieve content, and are
available unconditionally, whether or not a memory provider is configured. `configuredProvider` recorded in
each cached file's frontmatter is informational only — it names whichever provider is configured for the
skill's *other* memory operations (rules/decisions/etc.), not a claim that this body round-tripped through it.

Never calls provider MCP tools directly. All bodies pass `scripts/memory-redact.py` on read and write.
Bans `discussion` and `progress` classes; refuses raw transcript markers. Writes are scoped to
`memory.project`.

**Prior behavior (fixed by 21a):** availability used to be gated on a configured `memory.provider` — an
unconfigured provider produced a hard CLI failure (`sys.exit(2)`, verdict `fail`) for what is purely a local
disk write, a CI false-failure with no relationship to actual storage durability. That gate is removed; this
cache always works locally regardless of provider configuration.

## Provider round-trip (21b — later, PRD 057 R21)

A true round-trip through the memory provider adapter, with this local cache retained as a fallback when the
provider is unavailable, is a separate later unit (not implemented by 21a). Until 21b lands, this backend's
durability guarantee is local-disk-only — it is **not** synced to, or recoverable from, any external
provider.
