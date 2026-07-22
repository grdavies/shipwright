---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: obsidian
    metadata:
      providerFamily: memory
      adapterId: obsidian
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: obsidian

Maps the Shipwright memory capability spec ([`skills/memory/CAPABILITIES.md`](../skills/memory/CAPABILITIES.md))
onto Obsidian **Local REST API** built-in MCP tools (agent session) and `providers/obsidian-rules.py`
(hook rule-fetch). Selected when `workflow.config.json` → `memory.provider` is `obsidian`.

**Catalog authority (PRD 071 / 076):** this adapter is registered in `.sw/memory-provider-catalog.json`
(emit: `core/sw-reference/memory-provider-catalog.json`). Capability flags, hook transport, interchange
modes, and `sourceOfTruthClass` in the catalog row are authoritative — the JSON block below must stay
in sync.

**Local REST API MCP (stance B):** agent ops use the Obsidian Local REST API plugin's MCP/HTTP surface
on **loopback only** (default `http://127.0.0.1:27123`). Obsidian + the Local REST API plugin must be
running for agent ops. Bearer token from `OBSIDIAN_API_KEY` (env / secret-store only). There is **no
silent fallback** to another memory provider when Obsidian is closed or unreachable.

Supported Local REST API plugin range is pinned at implement/release (compat fixture under
`scripts/test/fixtures/obsidian/`). Tool names below follow the Local REST API MCP vocabulary
(vault file read/write/search); exact tool ids may use the plugin's published MCP names —
adapters treat path-addressable notes as first-class.

| Catalog field | Value |
| --- | --- |
| `sourceOfTruthClass` | `memory-authoritative` — distilled notes are provider-SoT; repo decision records stay pointers only |
| `interchange.jsonl` | `synthesized` — `/sw-memory-export` / `/sw-memory-import` synthesize neutral JSONL |
| `interchange.okf` | `synthesized` — same synthesis path into OKF v0.1 bundles (redaction before write) |
| `credentials.location` | `env-only` — `OBSIDIAN_API_KEY` from environment / secret-store-only |

`<project>` below is `memory.project`. Vault-relative paths are the memory identity. Global scope uses
the literal `__global__` (explicit user direction only).

## Dual-transport

| Path | Mechanism | Notes |
| --- | --- | --- |
| Agent session | Local REST API MCP / HTTP on loopback | All abstract ops below except hook-only rules enumeration |
| Guardrail hooks | `providers/obsidian-rules.py` (fixed-argv, non-MCP) | `rules-load` for startup / project switch only |

Hooks MUST NOT open an MCP handshake. Rule fetch uses vault filesystem under `vaultPath` and/or
loopback REST with the same credential + host policy as agent ops. Rule cache keys include
`provider` + project.

## Capability flags

```json
{
  "typedMemories": true,
  "filePathSearch": true,
  "categoryFilter": true,
  "recencyControl": true,
  "rulesAtStartup": true,
  "tasks": false,
  "export": true,
  "import": true,
  "softDelete": false,
  "semanticSearch": false
}
```

- `filePathSearch: true` — vault-relative path / filename filters are first-class (Local REST API
  file search / path list). Prefer path filters over free-text when the caller supplies a path.
- `semanticSearch: false` — **honest partial**: do not claim embedding/semantic search. Free-text
  search uses Local REST API content/path search only; degrade semantic intent to keyword/path query.
- `categoryFilter: true` — via folder under `memoriesDirectory`, frontmatter `category` / tags.
- `tasks: false` — degrade-open to the local phase-board registry; never fail unrelated memory
  surfaces (R21).
- `softDelete: false` — no native soft-delete; prefer non-destructive edit / supersede / archive
  frontmatter; hard delete only on confirmed purge.
- `export`/`import` are plugin-side synthesis (not a native Obsidian export tool).

## Operation mapping

| Abstract op | Local REST API / Obsidian surface | Call shape / notes |
| --- | --- | --- |
| `load-context` | list / recent vault notes under project folder | Orient on `memoriesDirectory/<project>/`; skip `rulesDirectory` |
| `rules-load` | Hook: `providers/obsidian-rules.py`; agent: path-scoped list under rules dir | Hook enumerates configured rules directory only. Never inject rules into ordinary preflight search |
| `search` | Local REST API search / list by path + content | Honor project folder scope; **always** exclude `rulesDirectory` from ordinary search (R14). Prefer path filters when `filePathSearch` applies |
| `expand` | read vault file by vault-relative path id | Path id is the memory id |
| `store` | R41 redact → create/append note under category folder | Frontmatter + tags; refuse rules-folder writes (human-gated only) |
| `modify` | update note / confirmed delete | Prefer edit; hard delete only on confirmed purge (`softDelete: false`) |
| `list-recent` | mtime / recency-filtered list under project folder | Same exclusions as ordinary search |
| `link` | wikilink / frontmatter relation, or degrade | Preserve `links[]` on interchange synthesis when create-edge is not first-class |
| `traverse` | follow wikilinks / related paths (bounded) | Dangling targets degrade |
| `export` / `import` | synthesized via search+expand | Neutral JSONL / OKF; path-id preserve/remap |
| `tasks.*` | — | **Degrade** to local registry (`tasks: false`); do not invent Obsidian task MCP calls (R21) |

### `load-context` contract (R16)

1. Resolve `vaultPath` (absolute) + `memoriesDirectory` / project folder.
2. List recent notes under the active project folder, **skipping** `rulesDirectory`.
3. Rules arrive separately via hook `rules-load` — not mixed into step 2.

### `search` / `memory-preflight` contract (R17)

- Prefer vault-relative **path** filters when the caller supplies a file path (`filePathSearch: true`).
- Free-text / keyword search via Local REST API content search — **not** semantic embeddings
  (`semanticSearch: false`).
- Scope to `memory.project` folder under `memoriesDirectory`. **Never** search the whole vault by
  default.
- **Always** exclude configured `rulesDirectory` (default `rules/`) from ordinary search and
  memory-preflight.
- Recency OFF by default unless the task is explicitly recent (`recencyControl`).

### `expand` / `list-recent` contract (R20)

- `expand` → read note by vault-relative path id (include frontmatter when metadata is required).
- `list-recent` → mtime-ordered list under the project folder, with the same rules-folder
  exclusions as ordinary search.

### `store` / `modify` contract (R18, R19)

- Redact via `scripts/memory-redact.py` when `redactOnWrite: true` (default) — R41 before any write.
- Map canonical category → folder under `memoriesDirectory/<project>/` (+ frontmatter `category` /
  tags). Prefer vault-relative path as the memory identity.
- Ordinary `store`/`modify` MUST refuse writes into the rules folder — rule-class notes only via
  `/sw-memory-audit` / human-gated promotion.
- While `softDelete: false`, abstract **inactivate** MUST NOT map to silent delete — use a
  non-destructive degrade (status frontmatter / superseding note). Hard **purge** is a distinct
  confirmed path that deletes the note and documents irreversibility.

### Path confinement (R8 / R20)

All reads and writes resolve through `memory.obsidian.vaultPath` with **realpath** containment:
resolved absolute paths MUST stay under the vault root. Traversal (`..`), symlink escapes, and
absolute paths outside the vault are rejected fail-closed.

### `tasks.*` degrade (R21)

`tasks: false` — all `tasks.*` abstract ops **degrade-open** to the local Shipwright phase-board
registry. Do not invent Obsidian task calls; do not fail unrelated memory surfaces when the task
board is empty.

## Category map → folder / frontmatter / tags (R14)

Canonical CAPABILITIES categories map onto folders under
`memory.obsidian.memoriesDirectory` / `<project>/` and optional frontmatter `category` + tags.
Banned catch-alls (`feature`, `general`, `project-*` mirrors) remain banned — never create folders
or tags for them.

| Canonical category | Folder (under memories/`<project>/`) | Frontmatter / tags | Notes |
| --- | --- | --- | --- |
| `decision` | `decision/` | `category: decision` | |
| `learning` | `learning/` | `category: learning` | |
| `debug` | `debug/` | `category: debug` | Prefer related-file path hints in body/tags |
| `design` | `design/` | `category: design` | |
| `code-context` | `code-context/` | `category: code-context` | |
| `playbook` | `playbook/` | `category: playbook` | |
| `research` | `research/` | `category: research` | |
| `discussion` | `discussion/` | `category: discussion` | Distilled only — never raw transcript |
| `progress` | `progress/` | `category: progress` | Sparingly |
| `rule` | *(rules directory, not memories)* | `category: rule` | Hook / human-gated only — excluded from ordinary search |

### Reserved directories (not canonical write categories)

| Path (config) | Purpose |
| --- | --- |
| `rules/` (`memory.obsidian.rulesDirectory`) | Guardrail / rule-class notes; hook rule-fetch only |
| `memories/` (`memory.obsidian.memoriesDirectory`) | Ordinary typed memories by project + category folder |

## Project scope mapping (R15)

| Scope | Resolution |
| --- | --- |
| Project memory | Folder `memoriesDirectory/<memory.project>/` under `vaultPath` |
| Global memory | Literal `__global__` folder under `memoriesDirectory` — **only** on explicit user direction |

Memory **ids** are vault-relative paths (posix), e.g. `memories/shipwright/decision/2026-07-21-foo.md`.
Interchange preserve/remap keeps path ids stable across in-repo ↔ obsidian when folder layout matches.

## Loopback transport contracts (R7–R10)

| Concern | Contract |
| --- | --- |
| Host policy | Loopback only (`localhost` / `127.0.0.1` / `::1`). Reject private, metadata, and link-local hosts (catalog `restFetchPolicy`) |
| Credentials | `Authorization: Bearer $OBSIDIAN_API_KEY` (or `memory.obsidian.tokenEnv`); never catalog/config bodies |
| Default base | `memory.obsidian.mcpBaseUrl` default `http://127.0.0.1:27123` |
| No silent fallback | Do not switch to another `memory.provider` when Obsidian is unreachable (R9) |

### Unreachable Obsidian / Local REST API (R10)

| Surface | Contract |
| --- | --- |
| Guardrail hooks | Fail closed when `enforceBeforeSubmit` / `memory.obsidian.failClosed` apply (default true) |
| Agent session | Report provider unreachable; do not mutate unrelated workflow surfaces |
| Cross-provider | Never silently switch providers to recover |

### Hook transport

`providers/obsidian-rules.py` (core: `core/providers/obsidian-rules.py`) is the fixed-argv, non-MCP
rule-fetch path. It reads the configured rules folder under `vaultPath` (realpath-confined) and/or
loopback REST with the same host + credential policy. Optional `ruleFetchCommand` overrides must
match the allowlisted executable after fixed-argv validation. Catalog membership alone does not
grant hook trust — `capability_trust` authorizes the rules script.

## Install / operator notes (no auto-install)

Adapters and `/sw-init` **document** Obsidian + Local REST API plugin enablement; they never
auto-install Obsidian or the plugin (R31). See `docs/guides/configuration.md` (obsidian section)
and `/sw-init` doctor when `memory.provider: obsidian` is configured.
