---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: recallium
    metadata:
      providerFamily: memory
      adapterId: recallium
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: Recallium

Maps the Shipwright memory capability spec ([`skills/memory/CAPABILITIES.md`](../skills/memory/CAPABILITIES.md))
onto the Recallium MCP tools. Selected when `workflow.config.json` → `memory.provider` is `recallium`.

`<project>` below is `memory.project` from the config. Global scope uses the literal `__global__`.

## Capability flags

```json
{
  "typedMemories": true,
  "filePathSearch": true,
  "categoryFilter": true,
  "recencyControl": true,
  "rulesAtStartup": true,
  "tasks": true,
  "export": false,
  "import": false,
  "softDelete": true,
  "semanticSearch": true
}
```

`export`/`import` are `false` at the MCP layer. Shipwright's `/sw-memory-export` and `/sw-memory-import`
synthesize neutral interchange by paging `search_memories` + `expand_memories` into JSONL or an OKF v0.1
bundle (per-category markdown, `category` → `type`, redaction via `scripts/memory-redact.py`). Provider
swaps become bundle round-trips. Treat these as plugin-side, not native MCP ops.

## Operation mapping

| Abstract op | Recallium tool | Call shape |
| --- | --- | --- |
| `load-context` | `recallium` | `{ project_name: "<project>", days_back: 7 }` |
| `rules-load` | `get_rules` | `{ project_name: "<project>" }` (include_global defaults true); `"__global__"` for global only |
| `search` | `search_memories` | `{ query, project_name, recent_only: false, search_target: "memories", search_mode: "semantic", file_path?, memory_type? }` |
| `expand` | `expand_memories` | `{ ids: [...] }` |
| `store` | `store_memory` | `{ content, project_name, memory_type, related_files?, tags?, importance_score?, related_memory_ids?, session_name? }` |
| `modify` | `modify_memory` | `{ memory_id, action: "update"\|"inactivate"\|"reactivate", content?, memory_type?, tags?, importance_score?, reason? }` |
| `list-recent` | `session_recap` | `{ project_scope: "current", project_name: "<project>", days_back: 7 }` |
| `tasks.create` | `create_task` | `{ project_name, task_description }` |
| `tasks.update` | `update_task` | per `update_task` schema |
| `tasks.complete` | `complete_task` | per `complete_task` schema |
| `tasks.list` | `list_tasks` | per `list_tasks` schema |
| `link` | `link_task_memories` / `related_memory_ids` on store | link tasks↔memories, or pass `related_memory_ids` |

## Canonical category → `memory_type`

| Canonical | `memory_type` |
| --- | --- |
| `decision` | `decision` |
| `learning` | `learning` |
| `debug` | `debug` |
| `design` | `design` |
| `code-context` | `code-snippet` |
| `research` | `research` |
| `discussion` | `discussion` |
| `progress` | `progress` |
| `rule` | `rule` (explicit user request only) |

Recallium's `feature`, `task`, `working-notes` are intentionally not targets of the canonical map: use
`create_task` for tasks, and prefer specific categories over `working-notes`. Reserve `feature` for
genuine shippable-capability recaps if ever needed (not a default).

## Scope mapping

- project memory → `project_name: "<project>"`.
- global memory → `project_name: "__global__"` (only on explicit user direction).
- search scope: omit `project_name` to search all projects; pass `"<project>"` to scope to it + linked
  projects (Recallium expands `full`-visibility links and reports them under "Also searched").

## Read recipe specifics

- Always pass `recent_only: false` unless the task is explicitly recent.
- File-path search: `file_path` uses ILIKE wildcards — `"%LoginForm%"`, `"server/utils/auth/%"`.
- Use `search_mode: "keyword"` for exact identifiers (function names, error codes) when semantic is noisy.
- `search_target: "memories"` for distilled notes; `"documents"` only when explicitly hunting uploaded
  files; `"all"` for "check everywhere" recaps.

## Write recipe specifics

- `related_files` is required for `code-snippet`/`debug` (and any file-scoped memory) — it builds the
  bidirectional file↔memory graph that powers `file_path` search.
- For cross-cutting decisions with a frozen decision record, link `related_files: ["docs/decisions/<n>-<slug>.md"]`
  — pointer only; never store the record body (R32). Re-point on supersede via `/sw-memory-sync` +
  `docs/decisions/SUPERSEDED.log` reconciliation.
- Pass `tags` (`prd-<n>`, `task-<n>`, `surface:<cmd>`); Recallium merges them with auto-tags.
- `importance_score` is 0.0–1.0.
- Search before store; on a near-duplicate use `modify_memory` with `action: "update"`.
- Never auto-store `rule`; never re-store rules just read from `get_rules`/`recallium`.

## Planning store adapter (PRD 034 R11/R23; PRD 057 R21 — 21b provider round-trip)

When selected as the `planning.store` **memory** backend, Recallium is **storage-only** for planning-unit
bodies — it does not alter source-of-truth for decision-class units. Decision paths under
`docs/planning/decision/` follow the PRD-015 committed snapshot flow; authoritative decision records remain
at `docs/decisions/<n>-<slug>.md` (repo-SoT) or the provider record (memory-SoT). All body reads/writes pass
through the provider-agnostic memory adapter and `scripts/memory-redact.py` — never direct MCP calls from
planning-store code (`scripts/planning_store.py` calls the REST base directly, the same pattern
`providers/recallium-rules.py` uses for hook-context rule fetches — never an MCP tool).

**Dedicated REST resource (21b):** planning bodies round-trip via `PUT`/`GET
{restBaseUrl}/api/projects/<project>/planning-bodies/<unitId>` — a document-style resource keyed by
`unitId`, deliberately separate from the `/memories` operation mapping above. A full planning body is not a
distilled memory note; indexing it alongside `store`/`search` targets would pollute semantic search (see
"Notes / gotchas" below). `restBaseUrl` is validated loopback-only (same guard as `providers/
recallium-rules.py`); any outage, disallowed host, or non-2xx response degrades to the planning store's
local-only cache (`MemoryLocalCacheBackend` 21a fallback) — never a hard failure. See
`core/providers/planning-store/memory.md` for the full backend-side contract.

## Cross-project recall (PRD 046 R90)

Recallium-backed cross-project recall is routed through `scripts/planning_cross_project_recall.py` and the
memory skill — not direct MCP calls from planning code.

| Requirement | Recallium mapping |
| --- | --- |
| Project scope | `project_name` on `search_memories` / `expand_memories` |
| Authorization | Caller `projectKey` must match source or appear in `authorizedProjects` |
| Redaction | `expand` output piped through `memory-redact.py`; private units opaque |
| Ranking | Deterministic sort before filter (`projectKey`, `unitId`, `memoryId`) |

`private`/`memory` pointers return `{unitId}: [private]` to unauthorized callers — never raw excerpts.


## Notes / gotchas

- Recallium runs locally with Ollama embeddings here — no external API cost or data egress.
- `recallium` (summon) is the cheap one-shot warmup; prefer it over many `search_memories` calls at
  startup, then use targeted `search_memories` during the task.
- There is no exclusion filter on raw content, which is one reason raw transcripts stay out of the
  provider (they would pollute precision search).

## Issue-store brainstorm distillation (PRD 043)

At PRD freeze in `issue-store` mode, rationale excerpts are redacted via `memory-redact.py` then
stored as `memory_type: research` with `related_files` pointing at the brainstorm issue path and
tags `prd-<unit>`, `brainstorm-<unit>`. Bidirectional pointers are recorded on the issue comments
(`sw-memory-pointer`); the brainstorm issue is closed, not deleted.

