---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: mempalace
    metadata:
      providerFamily: memory
      adapterId: mempalace
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: MemPalace

Maps the Shipwright memory capability spec ([`skills/memory/CAPABILITIES.md`](../skills/memory/CAPABILITIES.md))
onto MemPalace MCP tools (agent session) and `providers/mempalace-rules.py` (hook rule-fetch). Selected when
`workflow.config.json` → `memory.provider` is `mempalace`.

**Catalog authority (PRD 071 / 074):** this adapter is registered in `.sw/memory-provider-catalog.json` (emit:
`core/sw-reference/memory-provider-catalog.json`). Capability flags, hook transport, interchange modes, and
`sourceOfTruthClass` in the catalog row are authoritative — the JSON block below must stay in sync.

Supported package range: `mempalace>=3.6.0,<4.0.0` (see `memory.mempalace.supportedPackage`). Tool names below
are pinned for that range; drift outside the range requires a PRD amendment before catalog release.

| Catalog field | Value |
| --- | --- |
| `sourceOfTruthClass` | `memory-authoritative` — distilled drawers are provider-SoT; repo decision records stay pointers only |
| `interchange.jsonl` | `synthesized` — `/sw-memory-export` / `/sw-memory-import` synthesize neutral JSONL via search+expand (+ KG) |
| `interchange.okf` | `synthesized` — same synthesis path into OKF v0.1 bundles (redaction before write) |
| `credentials.location` | `none` — local-only `palacePath`; no remote credentials |

`<project>` below is `memory.project` from the config. Global scope uses the literal `__global__` (explicit
user direction only).

## Dual-transport

| Path | Mechanism | Notes |
| --- | --- | --- |
| Agent session | MemPalace MCP (`mempalace-mcp` / `python -m mempalace.mcp_server --palace …`) | All abstract ops below except hook-only rules enumeration |
| Guardrail hooks | `providers/mempalace-rules.py` (fixed-argv, non-MCP) | `rules-load` for startup / project switch only |

Hooks MUST NOT spawn an MCP handshake. Rule cache + argv trust are documented under R22/R23 (rules-script phases).

## Capability flags

```json
{
  "typedMemories": true,
  "filePathSearch": false,
  "categoryFilter": true,
  "recencyControl": true,
  "rulesAtStartup": true,
  "tasks": false,
  "export": true,
  "import": true,
  "softDelete": false,
  "semanticSearch": true
}
```

- `filePathSearch: false` — MemPalace search is wing/room/semantic only; degrade file-path queries by
  embedding the path string in the semantic query (no ILIKE file filter).
- `tasks: false` — degrade-open to the local phase-board registry; never fail unrelated memory surfaces (R18).
- `softDelete: false` — no native soft-delete; see **Modify / purge** below (non-destructive inactivate default).
- `export`/`import` are plugin-side synthesis (not native MCP export tools).

## Operation mapping

| Abstract op | MemPalace tools | Call shape / notes |
| --- | --- | --- |
| `load-context` | `mempalace_status`, `mempalace_get_taxonomy` | Status + taxonomy for `<project>` wing; then recent non-excluded `mempalace_search` (R13) |
| `rules-load` | Hook: `providers/mempalace-rules.py`; agent: room-scoped search | Hook enumerates `rulesRoom` only. Agent path may use `mempalace_search` with `wing=<project>`, `room=<rulesRoom>` — never inject rules into ordinary preflight search (R11) |
| `search` | `mempalace_search` | `{ query, wing: "<project>", room?, … }` honor `searchExcludeRooms` (default `["transcripts"]`) and **always** exclude `rulesRoom` (R14) |
| `expand` | `mempalace_get_drawer` | Drawer id is the stable memory id (R12) |
| `store` | `mempalace_check_duplicate` → `mempalace_add_drawer` | R41 redact first when `redactOnWrite: true` (default); refuse `rulesRoom` writes (R15) |
| `modify` | `mempalace_update_drawer` / supersede + KG; purge → `mempalace_delete_drawer` | Prefer update when available; see soft-delete policy (R16) |
| `list-recent` | `mempalace_search` / taxonomy + recency | Skip excluded rooms by default; transcripts opt-in per R10 (R17) |
| `link` | `mempalace_kg_add` (+ tunnel tools as needed) | **Edge-capable** — typed KG triples (R7) |
| `traverse` | `mempalace_kg_query`, `mempalace_traverse` | Walk KG; dangling / missing targets degrade (see below) |
| `export` / `import` | synthesized via search+expand (+ KG) | Neutral JSONL / OKF; **MUST round-trip `links[]`** when interchange is exercised |
| `tasks.*` | — | **Degrade** to local registry (`tasks: false`); do not call MCP (R18) |

### Edge-capable link / traverse (R7)

MemPalace is the first production **edge-capable** memory provider. Prefer native KG tools over
export-sidecar synthesis for live `link` / `traverse`:

| Abstract | Tool | Shape |
| --- | --- | --- |
| `link` | `mempalace_kg_add` | Subject drawer id → typed predicate → object drawer id (and optional value/metadata). Tunnel helpers may bridge wings when upstream exposes them. |
| `traverse` | `mempalace_kg_query`, `mempalace_traverse` | From-id + optional edge filter / depth / direction → nodes + edges. |
| Interchange | search + expand + KG walk | `/sw-memory-export` / `/sw-memory-import` synthesize neutral `links[]` from KG triples so JSONL/OKF round-trips preserve typed relationships. |

**Typed relationships** align with CAPABILITIES edges (`supersedes`, `relates-to`, `file-linked`) plus
provider-native predicates when they map cleanly; unknown predicates survive interchange as opaque
types rather than being dropped.

**Missing-target degrade:** if `traverse` / `expand` lands on a dangling object id (deleted drawer or
orphan after purge), return the edge with a dangling marker and continue — do not fail the whole
read path. After hard purge, inbound edges MUST orphan-invalidate (R16).

### Modify / purge (`softDelete: false`)

- **Update:** prefer `mempalace_update_drawer` when available; otherwise add a superseding drawer and
  invalidate/replace KG edges.
- **Inactivate (default):** MUST NOT silently hard-delete. Use superseding-drawer + KG-invalidate (or
  equivalent non-destructive degrade).
- **Hard purge:** distinct confirmed destructive path → `mempalace_delete_drawer`; orphan-invalidate
  inbound KG edges; never cascade-delete unrelated drawers.

## Wing / room taxonomy

### Wing → project (R9)

| Scope | Wing |
| --- | --- |
| Project memory | Wing name = `memory.project` (`<project>`) |
| Global memory | Wing `__global__` — **only** on explicit user direction |

### Room → canonical category (R8)

Canonical CAPABILITIES categories map 1:1 onto MemPalace **Rooms** under the project Wing. Banned
catch-alls (`feature`, `general`, `project-*` mirrors) remain banned — never create rooms for them.

| Canonical category | MemPalace Room | Notes |
| --- | --- | --- |
| `decision` | `decision` | |
| `learning` | `learning` | |
| `debug` | `debug` | Prefer related-file hints in drawer body/tags (no native filePathSearch) |
| `design` | `design` | |
| `code-context` | `code-context` | |
| `playbook` | `playbook` | |
| `research` | `research` | |
| `discussion` | `discussion` | Distilled only — never raw transcript |
| `progress` | `progress` | Sparingly |
| `rule` | `rules` (`rulesRoom`, default `rules`) | Hook / human-gated promotion only — not ordinary search (R11) |

### Reserved rooms (not canonical write categories)

| Room (config) | Purpose |
| --- | --- |
| `rules` (`memory.mempalace.rulesRoom`) | Guardrail drawers; hook rule-fetch only |
| `transcripts` (default in `searchExcludeRooms`) | Verbatim / non-summarized post-R41 text; excluded from default search; opt-in retrieval MUST warn (R10) |

## Scope mapping

- project → `wing: "<project>"` with category room (or unset room for cross-room search within the wing).
- global → `wing: "__global__"` only when the user explicitly directs it.
- Default `search` / `memory-preflight` rooms: all canonical rooms **minus** `searchExcludeRooms` **minus**
  `rulesRoom`.

## Search exclusions + load/search contracts

### Transcripts + `rulesRoom` exclusions

| Control | Behavior |
| --- | --- |
| `searchExcludeRooms` | Default `["transcripts"]` — verbatim / non-summarized material is excluded from default `search` and `memory-preflight`. |
| Opt-in transcripts | Removing `transcripts` from exclusions or explicit transcripts retrieval MUST emit an operator warning that excluded/verbatim material is requested. |
| `rulesRoom` (default `rules`) | **Always** excluded from ordinary search/preflight — hook `rules-load` only. Never inject `rulesRoom` drawers into agent preflight search. |
| Redaction on write | `redactOnWrite: true` (default) pipes every store through `scripts/memory-redact.py` before palace writes. Transcripts-room writes: redaction is **non-bypassable** in v1. |
| Ordinary writes to `rulesRoom` | Refused — rule-class drawers only via `/sw-memory-audit` / human-gated promotion. |

Enforcement helpers live in `providers/mempalace-rules.py` (`resolve_search_exclude_rooms`,
`filter_drawers_for_ordinary_search`, `guard_ordinary_search_room`). The hook script is **rules-load
transport only** — it never serves ordinary search or memory-preflight results.

### `load-context` contract

1. `mempalace_status` for the project wing (`memory.project`).
2. `mempalace_get_taxonomy` for wing/room orientation.
3. Recent activity via `mempalace_search` scoped to the project wing, **skipping** `searchExcludeRooms`
   and **always** skipping `rulesRoom`.
4. Rules arrive separately via hook `rules-load` (`providers/mempalace-rules.py`) — not mixed into step 3.

### `search` contract

- Honor `searchExcludeRooms` from config (default `["transcripts"]`).
- **Always** exclude `rulesRoom` even when callers omit room filters or pass a broad wing scope.
- Explicit room filters targeting an excluded room require opt-in handling and operator warning (transcripts
  especially).
- `guard_ordinary_search_room` rejects `room=<rulesRoom>` for search/preflight call sites.


1. Recency OFF by default unless the task is explicitly recent (`recencyControl`).
2. Prefer wing-scoped `mempalace_search`; narrow by room when `categoryFilter` applies.
3. File-path intent: include the path string in the semantic query (degrade from `filePathSearch: false`).
4. `expand` only selected drawer ids via `mempalace_get_drawer`.
5. Opt-in transcripts retrieval must warn that excluded/verbatim material is requested.

## Write recipe specifics

1. **R41 redaction:** pipe every store payload through `scripts/memory-redact.py` when `redactOnWrite: true`
   (default). Unredacted content MUST NOT reach `mempalace_check_duplicate` / `mempalace_add_drawer`.
   Transcripts-room writes: redaction is non-bypassable in v1.
2. Dedup → add: `mempalace_check_duplicate` on the redacted payload, then `mempalace_add_drawer`.
3. Refuse ordinary writes to `rulesRoom`; rule-class drawers only via `/sw-memory-audit` / allowlisted promotion.
4. Search before store; on near-duplicate prefer `modify` / supersede over a second drawer.
5. Never auto-store `rule`; never re-store rules just read from `rules-load`.

## Interchange + credentials

- JSONL/OKF interchange is **synthesized** (walk drawers + KG → neutral records); not a native MemPalace
  export API.
- `credentials.location: none` — local palace path only; never store palace contents or secrets in catalog
  or config secrets. Secret-store-only patterns do not apply to v1 local palace.

## Notes / gotchas

- Drawer id is the stable memory id for `expand` / `modify` / `link` endpoints.
- Edge-capable provider: prefer KG tools for `link`/`traverse`; CAPABILITIES documents the R33
  edge-first acceptance scenario.
- Tasks always degrade-open to the local registry — MemPalace has no native task board (R18).
- Live MCP tool schemas for the supported package range are pinned in hermetic fixtures (compatibility phase).
- Hook rule-fetch: `providers/mempalace-rules.py` (core mirror); full R19–R23 fetch lands in rules-script phases.
