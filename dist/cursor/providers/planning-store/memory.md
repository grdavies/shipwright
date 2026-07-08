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
directory (see `.gitignore`). `configuredProvider` recorded in each cached file's frontmatter names whichever
provider is configured for the skill's *other* memory operations (rules/decisions/etc.); `providerRoundTrip`
(21b, below) records whether *this* body actually round-tripped through it.

All bodies pass `scripts/memory-redact.py` on read and write. Bans `discussion` and `progress` classes;
refuses raw transcript markers. Writes are scoped to `memory.project`.

**Prior behavior (fixed by 21a):** availability used to be gated on a configured `memory.provider` — an
unconfigured provider produced a hard CLI failure (`sys.exit(2)`, verdict `fail`) for what is purely a local
disk write, a CI false-failure with no relationship to actual storage durability. That gate is removed; this
cache always works locally regardless of provider configuration.

## Provider round-trip (21b — PRD 057 R21)

When `memory.provider` is `recallium` and `memory.connection.restBaseUrl` is a reachable, loopback-only REST
base (`scripts/planning_store.py`'s `_is_allowed_recallium_base` — same localhost-only SSRF guard as
`providers/recallium-rules.py`), planning bodies round-trip through a dedicated `/api/projects/<project>/
planning-bodies/<unitId>` REST resource — deliberately **not** the semantically-indexed memory-note
collection used for `rules`/`decisions`/etc., since a full raw body is not a distilled note and would pollute
semantic search (see `providers/recallium.md`). Round-trips never call provider tools directly from
planning-store code (`scripts/planning_store.py` contains no MCP tool invocation) — this is a plain REST call,
the same pattern `providers/recallium-rules.py` already uses for hook-context rule fetches.

- **`put()`** always writes the local cache first (the 21a guarantee never regresses), then best-effort
  round-trips the redacted body through the provider. Frontmatter records `providerRoundTrip: true|false` and
  `providerRoundTripReason` (e.g. `ok`, `provider-not-configured`, `provider-rest-base-unavailable`, or
  `provider-unreachable:<ExceptionType>` / `provider-http-<status>`).
- **`get()`** reads the local cache when present (fast path, unchanged from 21a). When the cache is missing —
  a fresh checkout on another machine, since the cache dir is gitignored — it recovers content through the
  same provider adapter and repopulates the local cache on success.
- **Degrade-open, always:** any provider outage, timeout, non-2xx response, disallowed/unconfigured REST
  base, or non-`recallium` provider falls back to the 21a local-cache-only behavior — never a hard failure.
  `scripts/test/fixtures/memory-roundtrip/harness.py` exercises both the successful round-trip and every
  fallback path (SSRF-guard block, provider outage, clean 404 miss) offline via a fake transport.

Durability is therefore local-disk-first with a best-effort external round-trip layered on top — not a
durability *guarantee* from the provider (Recallium may still be unreachable at read time on a machine that
never had the local cache).
