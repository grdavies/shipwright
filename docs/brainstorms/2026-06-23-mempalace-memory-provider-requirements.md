---
date: 2026-06-23
topic: mempalace-memory-provider
---

# MemPalace as a Memory Provider

## Summary

Add **MemPalace** as a first-class, swappable memory provider (`memory.provider: "mempalace"`),
selected behind the existing capability spec ([`skills/memory/CAPABILITIES.md`](../../skills/memory/CAPABILITIES.md))
so **no command changes**. MemPalace is a local-only MCP server that stores content verbatim in a
Wing→Room→Hall→Drawer hierarchy with a real knowledge graph. The integration has two transport paths that
must be designed separately: the **agent-session path** uses MemPalace's MCP tools (via `CallMcpTool`),
and the **fail-closed guardrail-hook path** — which cannot speak MCP — fetches rule-class guardrails
out-of-band via a configurable JSON-emitting command with a TTL cache. We embrace MemPalace's verbatim
storage but scope it so it never pollutes workflow retrieval, keep R41 redaction on by default, and adopt
MemPalace's knowledge graph as the plugin's first **non-edge-degraded** provider. Agent diaries
("Specialist Agents") are considered and deliberately deferred.

## Problem Frame

phase-flow's durable memory sits behind a provider-agnostic capability spec. Two adapters exist today —
`recallium` (MCP tools + a localhost REST sidecar) and `in-repo` (committed markdown). Adding a provider
means supplying an adapter doc, an executable rule-fetcher for the fail-closed hook, registering the
provider name, and extending the config schema — without touching any command.

**What MemPalace is** (sources: `github.com/MemPalace/mempalace`, `mempalaceofficial.com`, `mcp_server.py`):
an open-source, **local-only** MCP server (Python + ChromaDB vectors + SQLite metadata + a
`knowledge_graph.sqlite3`). It stores content **verbatim** (no summarization) in a spatial hierarchy —
**Wings** (projects) → **Rooms** (topics) → **Halls** (memory types) → **Drawers** (entries) — plus
per-agent diaries and a knowledge graph. ~33–35 MCP tools (`mempalace_status`, `mempalace_search`,
`mempalace_add_drawer`, `mempalace_check_duplicate`, `mempalace_get_taxonomy`, `mempalace_kg_*`,
`mempalace_diary_*`, `mempalace_delete_drawer`).

**Two transport paths (the crux).** They have different reachability and must be designed independently:

- **Path 1 — agent session (primary).** `memory-preflight`, `search`, `store`, `expand`, `link`, and
  export/import run through MemPalace's MCP tools via the agent's `CallMcpTool`, exactly like the Recallium
  adapter calls Recallium's MCP tools.
- **Path 2 — fail-closed guardrail hook.** `hooks/before-submit-guardrails.py` is a non-agent subprocess
  with no handle to the agent's MCP client, so it cannot call `CallMcpTool`. Recallium works here only
  because it *also* exposes a persistent localhost REST API (`:8001`) the hook can `curl`. MemPalace's MCP
  server is **stdio-only** (`mcp_server.py` argparse exposes only `--palace PATH`; no `--host`/`--port`),
  so there is no daemon socket to hit. The hook therefore needs an out-of-band fetch.

## Key Decisions

- **Scope: full first-class provider (Q-scope).** Adapter doc + rule-fetcher + hook/schema/test wiring,
  production-ready and swappable like `recallium`/`in-repo` — not a spike or memo.
- **Verbatim is embraced, but precision is protected (Q-verbatim).** MemPalace stores verbatim; we accept
  that (it is a local store, same trust profile as Recallium-with-Ollama). To stop verbatim content from
  degrading workflow retrieval, verbatim/transcript-grade content lands in a dedicated **`transcripts`
  Room** that `memory-preflight` search excludes by default. The exposure argument for dropping redaction
  was conceded, but **R41 redaction stays ON by default** (cheap, deterministic, and the real leak vectors
  — re-injection into the model and `/pf-memory-export` — survive "it's local"); it is a one-line config
  toggle (`redactOnWrite`).
- **Agent-session path uses MCP (Q-transport, Path 1).** Not in question — the adapter maps capability ops
  onto `mempalace_*` tools via `CallMcpTool`.
- **Knowledge-graph edges are core, not optional (Q-approach: Full B).** The optional `link` op maps to
  MemPalace KG triples (`mempalace_kg_*`), making MemPalace the plugin's first **edge-capable** provider.
  `CAPABILITIES.md` notes Recallium and in-repo are both "edge-degraded" and typed-edge round-trip is only
  validated against a stub; MemPalace becomes the real backend. A new `linkEdges` capability flag is
  introduced.
- **Hook rule-fetch is CLI-only via a configurable JSON command (Q-rulefetch).** The hook runs
  `memory.mempalace.ruleFetchCommand` — a configurable command that must emit the `{ok, rules:[{id,
  summary}]}` contract. A bare `mempalace search` is insufficient: its CLI exposes only
  `--wing`/`--room`/`--results` (no `--hall`, no `--json`, no enumerate), so deterministic machine-readable
  rule enumeration is brittle. Shipped recipes: local install = a MemPalace **Python-API** one-liner
  enumerating the rules Room → JSON; Docker = the same via `docker run`/`docker exec`. Direct SQLite read
  was considered and rejected as the default because Docker named volumes (the README default) are not
  host-readable on macOS.
- **Rule cache is configurable; fail-closed is a knob (Q-cache).** `mempalace-rules.sh` caches the last
  successful fetch with a TTL (`ruleCacheTtlSec`, default 300). Fresh cache → serve it; stale/missing → run
  the command; on failure, `failClosed` (default `true`) blocks, else serve last cache (or `{ok:false}` if
  none).
- **Agent diaries deferred (Q-diaries).** See *Deferred Alternatives*.

## Architecture & Taxonomy Mapping

MemPalace structure is Wing → Room → Hall → Drawer. Because the CLI scopes only by `--wing`/`--room`,
**Room is the primary phase-flow scoping axis** so both transport paths align:

- **Wing** = `memory.project` (`__global__` for global scope, explicit user direction only).
- **Room** = canonical category: `decision`, `learning`, `debug`, `design`, `code-context`, `research`,
  `discussion`, `progress`; plus two reserved rooms — **`rules`** (rule-class guardrails, read by the hook)
  and **`transcripts`** (verbatim content).
- **Drawer** = the memory entry; its MemPalace drawer id is the `id` used by `expand`/`modify`.
- **Precision scoping:** `memory-preflight` `search` excludes the `transcripts` Room by default
  (`searchExcludeRooms`, default `["transcripts"]`); `rules` is read only by the guardrail path.

## Capability Flags

```json
{
  "typedMemories": true,
  "filePathSearch": false,
  "categoryFilter": true,
  "recencyControl": false,
  "rulesAtStartup": true,
  "tasks": false,
  "export": true,
  "import": true,
  "softDelete": false,
  "semanticSearch": true,
  "linkEdges": true
}
```

- `filePathSearch:false` → semantic search on the path string + `relatedFiles` carried in drawer metadata.
- `tasks:false` → local-registry fallback for the phase board (same as `in-repo`).
- `softDelete:false` → `mempalace_delete_drawer` is a hard delete (see `modify` below).
- `linkEdges:true` → **new flag**; documented in `CAPABILITIES.md`. Other providers default it `false`.

## Operation Mapping (capability op → MemPalace)

| Capability op | MemPalace |
| --- | --- |
| `load-context` | `mempalace_status` + `mempalace_get_taxonomy` |
| `rules-load` | agent path: `mempalace_search` (wing=project, room=`rules`); hook path: `ruleFetchCommand` JSON |
| `search` | `mempalace_search` { query, wing, room?, results, max_distance?/min_similarity? }, excluding `transcripts` |
| `expand` | fetch full drawer by id (verbatim store already returns content) |
| `store` | `mempalace_check_duplicate` → `mempalace_add_drawer` { wing, room=category, content } (R41-redacted unless toggled) |
| `modify` | update → add superseding drawer + KG `supersedes` edge; inactivate → `mempalace_delete_drawer` (hard) |
| `list-recent` | `mempalace_search` / taxonomy, sorted |
| `tasks.*` | unsupported → local registry fallback |
| `link` | `mempalace_kg_*` typed triple (`supersedes` / `relates-to` / `file-linked`) — **core** |
| `export` / `import` | walk drawers → neutral JSONL incl. `links[]` from KG; replay via `add_drawer` + KG triples |

**`modify` semantics:** MemPalace has no `update_drawer`, so update = supersede-by-new-drawer + KG edge;
inactivate = hard delete. This is why `softDelete:false`.

## Rule-Fetch Hook (`providers/mempalace-rules.sh`)

1. Resolve config; exit non-applicable unless `memory.provider == "mempalace"`.
2. Run `memory.mempalace.ruleFetchCommand`, which must emit `{ok:true, rules:[{id, summary}]}`. Rules live
   in the `rules` Room under the project Wing.
3. **Cache** at `.cursor/pf-memory/.mempalace-rules-cache.json`, TTL = `ruleCacheTtlSec` (default 300).
   Fresh → serve cached; stale/missing → run command; success refreshes cache.
4. **On failure:** `failClosed` (default `true`) → block; else serve last cache (even stale), or `{ok:false}`
   if no cache exists.
5. **Hardening (R43 trust boundary):** validate `ruleFetchCommand` against an allowlist of prefixes
   (`mempalace`, `python`/`python3`, `docker`) so committed config cannot trigger arbitrary exec; strip
   control chars; cap rule size (mirror `in-repo-rules.sh` `MAX_RULE_CHARS=2000`); enforce room=`rules`.

## Hook, Util & Schema Wiring

- `hooks/pf_hook_util.py`: add `"mempalace"` to `_KNOWN_MEMORY_PROVIDERS`. The generic
  `rules_script_for_provider` then resolves `providers/mempalace-rules.sh`; no dispatch-logic change.
- `hooks/before-submit-guardrails.py`: add a `mempalace` branch to `_provider_unreachable_message` with
  concrete remediation (check install, `ruleFetchCommand`, `palacePath`/bind-mount).
- `docs/config.schema.json`: add `"mempalace"` to the `memory.provider` enum; add a `memory.mempalace`
  object (`additionalProperties:false`): `palacePath` (string), `ruleFetchCommand` (string),
  `ruleCacheTtlSec` (int, default 300), `failClosed` (bool, default true), `redactOnWrite` (bool, default
  true), `searchExcludeRooms` (array, default `["transcripts"]`), `rulesRoom` (string, default `"rules"`).

## Files Touched

- **New:** `providers/mempalace.md`, `providers/mempalace-rules.sh`, test fixtures (+ a stub command).
- **Edit:** `hooks/pf_hook_util.py`, `hooks/before-submit-guardrails.py`, `docs/config.schema.json`,
  `skills/memory/CAPABILITIES.md` (document `linkEdges` + edge-capable note),
  `scripts/test/run-memory-provider-fixtures.sh`, and provider-aware bits of `commands/pf-setup.md` /
  `commands/pf-memory-export.md` / `commands/pf-memory-import.md`.

## Testing (deterministic, offline)

- **Stub command on PATH** emitting fixture `{ok,rules}` JSON — no real MemPalace required. Cases: cache
  miss → command runs → cache written; cache fresh → command NOT run; failure + `failClosed:true` → block;
  `failClosed:false` + cache present → serve stale; `ruleFetchCommand` allowlist rejects a disallowed
  prefix; rule size cap + room filter.
- Hook integration via the existing `PF_RULES_SCRIPT` override → continue/block paths.
- Schema validation: accepts a `mempalace` block, rejects unknown keys.
- KG edge round-trip: export/import `links[]` ↔ KG triples (extends the existing stub edge test, now backed
  by a real edge-capable provider).
- R41: redaction scrubs a planted secret when `redactOnWrite:true`; documented bypass when `false`.

## Scope Boundaries

### In scope

- The `mempalace` adapter doc, rule-fetcher, provider registration, schema block, and fixtures above.
- KG-edge mapping for the `link` op (core).
- Verbatim handling via the `transcripts` Room + `searchExcludeRooms` precision scoping.

### Out of scope / deferred

- **Agent diaries** (see *Deferred Alternatives*).
- Direct SQLite rule-fetch (rejected as default; may return as a fast-path optimization for bind-mount
  installs).
- Migrating this repo off Recallium — provider swap is a separate operational decision.
- Any change to the Recallium or in-repo adapters beyond adding the `linkEdges` flag default.

## Risks & Open Questions

- **`ruleFetchCommand` is configurable exec** → mitigated by the prefix allowlist (R43). Confirm the
  allowlist covers the shipped recipes and nothing broader.
- **Python-API enumeration recipe is provisional.** The MCP tools and the `search`/`mine` CLI are
  confirmed from source; the exact Python-API call to enumerate the `rules` Room as JSON must be pinned
  against the installed MemPalace version during implementation.
- **Docker named-volume on macOS** is not host-readable — the reason the hook is CLI/command-based. Docs
  must recommend a host-visible `palacePath` (bind mount) or a warm container; otherwise cold-start can
  brush the budget (mitigated by cache + `failClosed`).
- **HNSW flush windows / BM25 fallback.** MemPalace can transiently degrade to keyword search after bulk
  writes; acceptable for rule retrieval (keyword is fine for rules).
- **`softDelete:false`** — inactivate is destructive; confirm no workflow relies on reversible
  inactivation when on MemPalace.

## Deferred Alternatives

- **Agent diaries ("Specialist Agents").** Considered folding MemPalace's per-agent diary streams
  (`mempalace_diary_write`/`read`, keyed by a stable `agent_name` → `wing_<name>/diary`, AAAK-compressed)
  onto phase-flow's seven `pf-*-reviewer` personas for cross-session pattern continuity. **Deferred.**
  Reasons: (1) it is a MemPalace-only feature with no analog in `recallium`/`in-repo`, so it would have to
  be capability-gated and kept out of the portable contract; (2) split-brain risk between the portable
  category store and a provider-local diary sink; (3) the concept is narrower than the docs imply —
  MemPalace ships diaries only, **not** an agent registry or `mempalace_list_agents` (the README oversold
  it). Easy revisit later as an optional `agentDiaries` capability (read-at-dispatch seeding is the
  lowest-risk first step).
- **Embrace verbatim with a flat corpus** (no precision scoping) — rejected; it degrades every preflight
  retrieval.
- **Drop R41 redaction for this provider** — rejected; redaction protects re-injection and export, which
  survive "it's local."
- **Approach A (thin parity, no KG)** and **Approach C (parity + KG + diaries, superset memory OS)** —
  rejected in favor of Full B (parity + KG edges core, diaries deferred).
- **Hook fetch via SQLite-direct / spawned MCP handshake** — rejected as default (named-volume/macOS
  portability; cold-start fragility under the fail-closed budget).

## Sources & Research

- phase-flow v2: `skills/memory/CAPABILITIES.md` (capability spec + flags), `providers/recallium.md` and
  `providers/in-repo.md` (existing adapters), `providers/recallium-rules.sh` / `providers/in-repo-rules.sh`
  (rule-fetchers), `hooks/before-submit-guardrails.py` + `hooks/pf_hook_util.py` (fail-closed dispatch,
  `_KNOWN_MEMORY_PROVIDERS`, `rules_script_for_provider`), `docs/config.schema.json` (provider enum),
  `rules/memory-guardrails.mdc` (R41/R42/R43).
- MemPalace: `github.com/MemPalace/mempalace` (README, `mempalace/mcp_server.py` — stdio-only, `--palace`,
  SQLite palace + BM25 fallback), `mempalaceofficial.com/reference/cli.html` (CLI surface:
  `search --wing/--room/--results`, no `--hall`/`--json`/enumerate), `mempalaceofficial.com/guide/mcp-integration.html`
  (tool list), `mempalaceofficial.com/concepts/agents.html` (diaries only; no registry / `mempalace_list_agents`).
- Distilled durable memories from this work: #2031 (MemPalace research), #2030 (hook-transport learning).
