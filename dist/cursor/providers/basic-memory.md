---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: basic-memory
    metadata:
      providerFamily: memory
      adapterId: basic-memory
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: basic-memory

Maps the Shipwright memory capability spec ([`skills/memory/CAPABILITIES.md`](../skills/memory/CAPABILITIES.md))
onto Basic Memory MCP tools (agent session) and `providers/basic-memory-rules.py` (hook rule-fetch). Selected when
`workflow.config.json` → `memory.provider` is `basic-memory`.

**Catalog authority (PRD 071 / 075):** this adapter is registered in `.sw/memory-provider-catalog.json` (emit:
`core/sw-reference/memory-provider-catalog.json`). Capability flags, hook transport, interchange modes, and
`sourceOfTruthClass` in the catalog row are authoritative — the JSON block below must stay in sync.

**Dual-mode:** operator sets `memory.basicMemory.mode` to `local` or `cloud`. There is **no silent
local↔cloud fallback** (R9). Local uses loopback MCP / on-disk project; cloud uses allowlisted
`cloud.basicmemory.com` with `BASIC_MEMORY_API_KEY` (**secret-store-only** / env — never catalog or
config bodies). This doc owns dual-mode transport (R7–R10), the abstract→MCP op map including graph
ops (R13, R16–R20), and the category map / project mapping (R11, R14, R15, R21).

Supported package range: `basic-memory>=0.22.0,<1.0.0` (see `memory.basicMemory.supportedPackage`). Tool
names below are pinned against the Basic Memory MCP Tools Reference at PRD 075 authoring; drift outside the
range requires a PRD amendment before catalog release.

| Catalog field | Value |
| --- | --- |
| `sourceOfTruthClass` | `memory-authoritative` — distilled notes are provider-SoT; repo decision records stay pointers only |
| `interchange.jsonl` | `synthesized` — `/sw-memory-export` / `/sw-memory-import` synthesize neutral JSONL |
| `interchange.okf` | `synthesized` — same synthesis path into OKF v0.1 bundles (redaction before write) |
| `credentials.location` | `env-only` — cloud bearer from environment / secret-store-only; local needs no remote token |

`<project>` below is `memory.project` / `memory.basicMemory.project` (or resolved `project_id`). Global
scope uses the literal `__global__` (explicit user direction only).

## Dual-transport

| Path | Mechanism | Notes |
| --- | --- | --- |
| Agent session | Basic Memory MCP (local stdio/loopback or cloud remote MCP) | All abstract ops below except hook-only rules enumeration |
| Guardrail hooks | `providers/basic-memory-rules.py` (fixed-argv, non-MCP) | `rules-load` for startup / project switch only |

Hooks MUST NOT spawn an MCP handshake. Rule cache is **mode-partitioned** (`provider` + `mode` + project).
Cloud hook/CLI auth: `Authorization: Bearer $BASIC_MEMORY_API_KEY` against allowlisted hosts only.

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

- `filePathSearch: false` — Basic Memory search is semantic / note-oriented; degrade file-path intent by
  embedding the path string in the `search_notes` query (no ILIKE file filter).
- `categoryFilter: true` — via `note_type` and/or observation `categories` / folder layout (R14).
- `tasks: false` — degrade-open to the local phase-board registry; never fail unrelated memory surfaces (R21).
- `softDelete: false` — no native soft-delete; prefer non-destructive edit / supersede; hard `delete_note`
  only on confirmed purge.
- `export`/`import` are plugin-side synthesis (not native MCP export tools).

## Operation mapping

| Abstract op | basic-memory tools | Call shape / notes |
| --- | --- | --- |
| `load-context` | `list_memory_projects`, `recent_activity` (+ `cloud_info` in cloud) | Orient on projects; then recent non-rules activity for `<project>` |
| `rules-load` | Hook: `providers/basic-memory-rules.py`; agent: folder/`note_type`-scoped search | Hook enumerates configured rules directory only. Agent path may use `search_notes` scoped to rules folder / rule `note_type` — never inject rules into ordinary preflight search |
| `search` | `search_notes` | Honor project scope; **always** exclude rules directory / rule `note_type` from ordinary search (R14) |
| `expand` | `read_note` | Permalink / stable note id is the memory id |
| `store` | R41 redact → `write_note` | Mapped `note_type`, directory, tags, metadata; refuse rules-folder writes (human-gated only) |
| `modify` | `edit_note` / `write_note` / confirmed `delete_note` | Prefer edit; hard delete only on confirmed purge (`softDelete: false`) |
| `list-recent` | `recent_activity` / recency-filtered `search_notes` | Same exclusions as ordinary search |
| `link` | Relation / wikilink write path, or degrade | When create-edge is not a first-class MCP verb, document degrade and preserve links via interchange synthesis |
| `traverse` | `build_context` | Context graph walk from a note; dangling targets degrade |
| `export` / `import` | synthesized via search+expand (+ context) | Neutral JSONL / OKF; round-trip `links[]` when interchange is exercised |
| `tasks.*` | — | **Degrade** to local registry (`tasks: false`); do not call MCP (R21) |

### `load-context` contract (R16)

1. `list_memory_projects` (and optional `cloud_info` when `mode: cloud`) for orientation.
2. `recent_activity` and/or scoped `search_notes` for the active project, **skipping** the rules
   directory / rule `note_type`.
3. Rules arrive separately via hook `rules-load` — not mixed into step 2.

### `search` / `memory-preflight` contract (R17)

- Use `search_notes` with hybrid/semantic when enabled.
- Scope to `memory.project` / resolved `project_id` (R15). **Never** set `search_all_projects: true`
  by default.
- **Always** exclude the configured rules directory (default `rules/`) and rule-class `note_type` from
  ordinary search and memory-preflight.
- File-path intent: include the path string in the semantic query (`filePathSearch: false` degrade).
- Recency OFF by default unless the task is explicitly recent (`recencyControl`).

### `expand` / `list-recent` contract (R20)

- `expand` → `read_note` (include frontmatter when metadata / permalink identity is required).
- `list-recent` → `recent_activity` or recency-filtered `search_notes`, with the same rules-folder
  exclusions as ordinary search.

### `store` / `modify` contract (R18, R19)

- Redact via `scripts/memory-redact.py` when `redactOnWrite: true` (default) — R41 before any write.
- Map canonical category → `note_type` + folder under `memoriesDirectory` (default `memories/`).
- Prefer stable permalink / note id as the memory identity; document overwrite semantics on
  `write_note` when the upstream tool replaces by permalink.
- Ordinary `store`/`modify` MUST refuse writes into the rules folder — rule-class notes only via
  `/sw-memory-audit` / human-gated promotion.
- `modify` update prefers `edit_note` / `write_note` with overwrite.
- While `softDelete: false`, abstract **inactivate** MUST NOT map to silent `delete_note` — use a
  non-destructive degrade (status metadata / superseding note). Hard **purge** is a distinct
  confirmed path that calls `delete_note` and documents irreversibility.

### `link` / `traverse` (R13)

- `traverse` MUST map to `build_context` (memory:// URL + depth). Missing / deleted targets return a
  dangling marker and continue.
- `link` documents wikilink / relation creation via note-body relations or upstream relation tools
  when available. When create-edge is not a first-class MCP verb, `link` degrades with an
  operator-visible notice and best-effort `links[]` on interchange synthesis.

### `tasks.*` degrade (R21)

`tasks: false` — all `tasks.*` abstract ops **degrade-open** to the local Shipwright phase-board
registry. Do not invent MCP task calls; do not fail unrelated memory surfaces when the task board is
empty.

## Category map → note_type / folder (R14)

Canonical CAPABILITIES categories map onto Basic Memory **`note_type`** values and folders under
`memory.basicMemory.memoriesDirectory` (default `memories/`). Banned catch-alls (`feature`, `general`,
`project-*` mirrors) remain banned — never create note types or folders for them.

| Canonical category | `note_type` | Folder (under memories dir) | Notes |
| --- | --- | --- | --- |
| `decision` | `decision` | `decision/` | |
| `learning` | `learning` | `learning/` | |
| `debug` | `debug` | `debug/` | Prefer related-file hints in body/tags |
| `design` | `design` | `design/` | |
| `code-context` | `code-context` | `code-context/` | |
| `playbook` | `playbook` | `playbook/` | |
| `research` | `research` | `research/` | |
| `discussion` | `discussion` | `discussion/` | Distilled only — never raw transcript |
| `progress` | `progress` | `progress/` | Sparingly |
| `rule` | `rule` | *(rules directory, not memories)* | Hook / human-gated only — excluded from ordinary search |

### Reserved directories (not canonical write categories)

| Path (config) | Purpose |
| --- | --- |
| `rules/` (`memory.basicMemory.rulesDirectory`) | Guardrail / rule-class notes; hook rule-fetch only |
| `memories/` (`memory.basicMemory.memoriesDirectory`) | Ordinary typed memories by category folder |

Observation `categories` / tags MAY mirror the canonical category for filterability; they MUST NOT invent
banned catch-alls.

## Project scope mapping (R15)

| Scope | Resolution |
| --- | --- |
| Project memory | `list_memory_projects` → match `memory.project` / `memory.basicMemory.project` (name/slug) or `memory.basicMemory.projectId` |
| Cloud workspace | Optional `memory.basicMemory.workspace` when writing in cloud mode |
| Global memory | Literal `__global__` — **only** on explicit user direction |

Default agent and preflight ops use the active project mapping. Cloud mode may pass `workspace` +
`project_id` together when the upstream API requires both.

## Dual-mode transport contracts (R7–R10)

| Mode | Agent transport | Hook / CLI credentials | SSRF / host policy |
| --- | --- | --- | --- |
| `local` | Local MCP only — stdio or documented local HTTP | None (no remote bearer) | Loopback only (`localhost` / `127.0.0.1` / `::1`). Reject private, metadata, and link-local hosts unless an explicitly justified + tested exception exists (R7) |
| `cloud` | Cloud MCP / API at allowlisted base | `BASIC_MEMORY_API_KEY` (`bmc_…` bearer) from environment or secret store only — **never** catalog/config bodies (R8) | Default base `https://cloud.basicmemory.com`. Fail closed on host allowlist mismatch |

### Mode selection — no silent fallback (R9)

Switching `local` ↔ `cloud` is an **explicit** `memory.basicMemory.mode` config change. Runtime MUST
NOT auto-promote local to cloud, degrade cloud to local, or otherwise rewrite mode when the
configured endpoint fails.

### Unreachable configured mode (R10)

When the configured mode is unreachable:

| Surface | Contract |
| --- | --- |
| Guardrail hooks | Fail closed when `enforceBeforeSubmit` / `memory.basicMemory.failClosed` apply (default true) |
| Agent session | Report provider unreachable; do not mutate unrelated workflow surfaces |
| Cross-mode | Never silently switch modes to recover |

Catalog `hookTransport.restFetchPolicy` mirrors the same local loopback vs cloud allowlist split.

### Hook transport pointer

`providers/basic-memory-rules.py` (core: `core/providers/basic-memory-rules.py`) is the fixed-argv,
non-MCP rule-fetch path. Mode-aware host gating, rules-folder filter, and mode-partitioned cache are
implemented by that script; this adapter doc owns the contracts above.

## Break-glass / fail-closed

When `memory.basicMemory.failClosed` is true (default) and rule-fetch is unreachable or tampered,
guardrail enforcement before submit MUST block. Operator break-glass follows the shared Shipwright
memory guardrail path — set `failClosed: false` or change `memory.provider` explicitly — not a
silent degrade to another provider or mode.
