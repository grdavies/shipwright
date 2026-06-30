---
date: 2026-06-25
topic: mempalace-memory-provider
brainstorm: docs/brainstorms/2026-06-23-mempalace-memory-provider-requirements.md
frozen: true
frozen_at: 2026-06-25
---
# PRD 010: MemPalace memory provider

## Overview

Shipwright's durable memory sits behind a provider-agnostic capability spec (`skills/memory/CAPABILITIES.md`).
Two adapters exist today — `recallium` (MCP + localhost REST sidecar) and `in-repo` (committed markdown).
Teams that want a **local-only**, verbatim-capable knowledge graph with no cloud dependency have no supported
path.

This PRD adds **MemPalace** as a third first-class, swappable `memory.provider` (`"mempalace"`). MemPalace is
an open-source MCP server (Python + ChromaDB + SQLite) that stores content verbatim in a Wing→Room→Hall→Drawer
hierarchy with a real knowledge graph. Integration follows the existing adapter contract: `providers/mempalace.md`
for agent-session ops (via `CallMcpTool`) and `providers/mempalace-rules.sh` for the fail-closed guardrail hook
(which cannot speak MCP).

**Two transport paths** are designed independently:

1. **Agent session (primary)** — `memory-preflight`, `search`, `store`, `expand`, `link`, export/import via
   MemPalace MCP tools.
2. **Fail-closed hook** — `hooks/before-submit-guardrails.py` runs a configurable JSON-emitting
   `ruleFetchCommand` with TTL cache; MemPalace's stdio-only MCP server has no daemon socket.

MemPalace becomes the plugin's first **edge-capable** provider (`linkEdges: true`); Recallium and in-repo remain
edge-degraded. Verbatim storage is embraced but scoped via a dedicated `transcripts` Room excluded from default
search. R41 redaction stays ON by default.

**Input:** [docs/brainstorms/2026-06-23-mempalace-memory-provider-requirements.md](../../brainstorms/2026-06-23-mempalace-memory-provider-requirements.md) (Full tier).

## Goals

1. **Provider swap parity** — Users set `memory.provider: "mempalace"` and run existing memory commands with no
   command-surface changes. Adapter docs MUST call out MemPalace-specific semantics (`softDelete: false` hard
   delete, `tasks` local fallback) so swaps are informed, not silent.
2. **Local-only adoption path** — Teams avoiding cloud memory (air-gapped, privacy-sensitive, or offline-first
   workflows) can use a real knowledge graph without Recallium or committed markdown trade-offs.
3. **Dual-transport correctness** — Agent path uses MCP; hook path uses `mempalace-rules.sh` + configurable
   `ruleFetchCommand` with TTL cache and fail-closed default.
4. **Edge-capable backend** — `link` op maps to MemPalace KG triples; export/import round-trips `links[]`.
5. **Precision scoping** — Verbatim/transcript-grade content lands in `transcripts` Room; default search excludes
   it via `searchExcludeRooms`.
6. **Security posture** — R41 redaction ON by default; R43 prefix allowlist on `ruleFetchCommand`; rule size cap.
7. **Deterministic offline tests** — Fixture stub command; no real MemPalace install required for CI.

## Non-Goals

- Agent diaries (MemPalace brands these "Specialist Agents"; `mempalace_diary_*`) — deferred; no
  `agentDiaries` capability in v1 (portability and split-brain risk with portable category store).
- Direct SQLite rule-fetch as default — rejected for Docker named-volume portability on macOS.
- Migrating this repo off Recallium — operational decision separate from this PRD.
- Changes to Recallium or in-repo adapters beyond documenting `linkEdges: false` default.
- Spawning MCP handshake from the hook subprocess.
- MemPalace cloud/hosted deployment — local-only per upstream design.
- `/sw-setup` auto-install of MemPalace — document recipes only in v1.

## Requirements

Requirements distill brainstorm key decisions. Each is testable.

### Provider registration & adapter contract

- **R1** `workflow.config.json` MUST accept `memory.provider: "mempalace"` and resolve the adapter at
  `providers/mempalace.md`.
- **R2** `providers/mempalace.md` MUST declare capability flags per brainstorm (including `linkEdges: true`,
  `filePathSearch: false`, `tasks: false`, `softDelete: false`) and map every abstract op in
  `skills/memory/CAPABILITIES.md` to concrete `mempalace_*` MCP tool calls. The adapter MUST document that
  `softDelete: false` means hard delete only and `modify` inactivation is irreversible.
- **R3** `skills/memory/CAPABILITIES.md` MUST document the new `linkEdges` flag and note MemPalace as the first
  edge-capable provider; Recallium and in-repo default `linkEdges: false`.
- **R4** `hooks/pf_hook_util.py` MUST add `"mempalace"` to `_KNOWN_MEMORY_PROVIDERS` so
  `rules_script_for_provider` resolves `providers/mempalace-rules.sh` without dispatch-logic changes.

### Configuration schema

- **R5** `core/sw-reference/config.schema.json` (regenerate `.sw/config.schema.json` via `python3 -m sw generate`)
  MUST add `"mempalace"` to the `memory.provider` enum.
- **R6** A `memory.mempalace` object MUST be added with `additionalProperties: false` and at minimum:
  `palacePath` (string), `ruleFetchCommand` (string), `ruleCacheTtlSec` (integer, default 300),
  `failClosed` (boolean, default true), `redactOnWrite` (boolean, default true),
  `searchExcludeRooms` (array of strings, default `["transcripts"]`), `rulesRoom` (string, default `"rules"`).
- **R7** Schema validation MUST reject unknown keys under `memory.mempalace`.

### Taxonomy mapping

- **R8** Wing MUST map to `memory.project` (`__global__` for global scope on explicit user direction only).
- **R9** Room MUST map to canonical categories (`decision`, `learning`, `debug`, `design`, `code-context`,
  `research`, `discussion`, `progress`) plus reserved rooms `rules` (guardrails) and `transcripts` (verbatim).
- **R10** Drawer id MUST be the memory `id` for `expand` and `modify`.
- **R11** Default `memory-preflight` search MUST exclude rooms in `searchExcludeRooms` (default `["transcripts"]`).
- **R12** The `rules` Room MUST be read only by the guardrail rule-fetch path, not injected into workflow search.

### Agent-session operations

- **R13** `load-context` MUST use `mempalace_status` + `mempalace_get_taxonomy`.
- **R14** `rules-load` (agent path) MUST use `mempalace_search` scoped to wing=project, room=`rulesRoom`.
- **R15** `search` MUST use `mempalace_search` with wing/room scoping and honor `searchExcludeRooms`.
- **R16** `expand` MUST fetch full drawer content by id (verbatim store returns content directly).
- **R17** `store` MUST run `mempalace_check_duplicate` then `mempalace_add_drawer` with R41 redaction when
  `redactOnWrite: true` (default).
- **R18** `modify` update MUST add a superseding drawer plus KG `supersedes` edge; inactivate MUST call
  `mempalace_delete_drawer` (hard delete) because MemPalace has no update/inactivate API.
- **R19** `list-recent` MUST use `mempalace_search` / taxonomy sorted by recency.
- **R20** `tasks.*` MUST degrade to local registry fallback (same as `in-repo`).
- **R21** `link` MUST map to `mempalace_kg_*` typed triples (`supersedes`, `relates-to`, `file-linked`).
- **R22** `export` / `import` MUST walk drawers to neutral JSONL including `links[]` from KG; replay via
  `add_drawer` + KG triples.

### Hook rule-fetcher (`providers/mempalace-rules.sh`)

- **R23** The script MUST exit non-applicable (ok:false) unless `memory.provider == "mempalace"`.
- **R24** The script MUST run `memory.mempalace.ruleFetchCommand` and require stdout JSON
  `{ok:true, rules:[{id, summary}]}`.
- **R25** Rules MUST live in the `rules` Room under the project Wing; enumeration MUST be room-filtered.
- **R26** Cache MUST be written atomically to `.cursor/pf-memory/.mempalace-rules-cache.json` with TTL
  `ruleCacheTtlSec` (default 300): fresh cache served without re-running command; stale/missing triggers fetch.
  Concurrent hook invocations MUST use file locking (or write-temp-then-rename) so partial writes cannot corrupt
  cache JSON.
- **R27** On fetch failure: when `failClosed: true` (default) the hook MUST block; when `failClosed: false`
  serve last cache (even stale) or `{ok:false}` if no cache exists.
- **R28** `ruleFetchCommand` MUST be validated against a prefix allowlist (`mempalace`, `python`/`python3`,
  `docker`); disallowed prefixes MUST be rejected before exec. Shell metacharacters (`;`, `|`, `&`, `` ` ``,
  `$()`, redirects) MUST be rejected (R43 trust boundary). Invocation MUST use a fixed argv split — not
  `eval` or bare `sh -c` on unsanitized config.
- **R29** Rule summaries MUST be capped at `MAX_RULE_CHARS=2000` (mirror `in-repo-rules.sh`); control characters
  stripped.
- **R30** `hooks/before-submit-guardrails.py` MUST add a `mempalace` branch to `_provider_unreachable_message`
  with remediation (install check, `ruleFetchCommand`, `palacePath`/bind-mount).

### Documentation & setup guidance

- **R31** `commands/pf-setup.md` MUST document MemPalace provider selection, `palacePath`, and shipped
  `ruleFetchCommand` recipes (local Python-API one-liner; Docker via `docker run`/`docker exec`).
- **R32** `commands/pf-memory-export.md` and `commands/pf-memory-import.md` MUST note MemPalace KG edge
  round-trip and `redactOnWrite` behavior.
- **R33** Docs MUST recommend host-visible `palacePath` (bind mount) or warm container for Docker installs;
  named volumes on macOS are not host-readable.

### Testing (deterministic, offline)

- **R34** `scripts/test/run-memory-provider-fixtures.sh` MUST cover: cache miss→write; fresh cache→no command;
  failure+`failClosed:true`→block; `failClosed:false`+stale cache→serve; allowlist rejection; rule size cap;
  room filter.
- **R35** Hook integration MUST be testable via existing `PF_RULES_SCRIPT` override (continue/block paths).
- **R36** Schema fixture MUST accept valid `mempalace` block and reject unknown keys.
- **R37** KG edge round-trip fixture MUST validate export/import `links[]` ↔ KG triples (extends stub edge test).
- **R38** R41 fixture MUST scrub a planted secret when `redactOnWrite: true`; document bypass when `false`.

## Technical Requirements

### MemPalace upstream constraints

- MCP server is **stdio-only** (`mcp_server.py` exposes `--palace PATH` only; no `--host`/`--port`).
- CLI `search` exposes `--wing`, `--room`, `--results` only — no `--hall`, `--json`, or enumerate mode.
- Hard delete via `mempalace_delete_drawer`; no `update_drawer` API.
- HNSW flush windows may transiently degrade to BM25 keyword search — acceptable for rule retrieval.

### Shipped `ruleFetchCommand` recipes

Implementation MUST pin the Python-API enumeration call against the installed MemPalace version during
implementation. Recipes:

- **Local install:** Python one-liner enumerating `rules` Room drawers → JSON.
- **Docker:** same via `docker exec` against a running container with bind-mounted palace.

Direct SQLite read is NOT the default recipe.

### File inventory

| Action | Path |
| --- | --- |
| New | `providers/mempalace.md`, `providers/mempalace-rules.sh` |
| New | `scripts/test/fixtures/mempalace-rules-stub.sh` (or equivalent stub on PATH) |
| Edit | `hooks/pf_hook_util.py`, `hooks/before-submit-guardrails.py` |
| Edit | `.sw/config.schema.json`, `core/sw-reference/config.schema.json` |
| Edit | `core/skills/memory/CAPABILITIES.md` |
| Edit | `scripts/test/run-memory-provider-fixtures.sh` |
| Edit | `core/commands/pf-setup.md`, `core/commands/pf-memory-export.md`, `core/commands/pf-memory-import.md` |
| Regenerate | `dist/cursor/`, `dist/claude-code/` via emitter after `core/` edits |

### Emitter & core mirror

Follow PRD 004/009 discipline: edit `core/` and `scripts/`; run `python3 -m sw generate` and
`python3 scripts/copy-to-core.py` as needed. Do not hand-edit `dist/` or `core/scripts/` without emitter/sync.

## Security & Compliance

- **R41 redaction** — `scripts/memory-redact.py` runs before `store` when `redactOnWrite: true` (default).
  Local storage does not eliminate re-injection or `/pf-memory-export` leak vectors.
- **R43 trust boundary** — `ruleFetchCommand` is configurable exec; prefix allowlist is mandatory. Committed
  config cannot trigger arbitrary shell.
- **Rule injection** — Strip control characters from rule summaries; cap size; enforce room=`rules` filter.
- **No secrets in config** — `palacePath` and command strings only; no API keys in `workflow.config.json`.
- **Fail-closed default** — `failClosed: true` aligns with `memory.guardrails.enforceBeforeSubmit`.

## Testing Strategy

| Area | Fixture / scenario |
| --- | --- |
| Rule cache | miss→fetch→write; fresh→skip command; stale+fail→block or serve per `failClosed` |
| Allowlist | disallowed prefix rejected before exec |
| Rule cap | summary > 2000 chars skipped or truncated per in-repo parity |
| Hook | `PF_RULES_SCRIPT` override continue/block |
| Schema | valid block passes; unknown key fails |
| KG edges | export `links[]` round-trip through import |
| R41 | planted secret scrubbed with `redactOnWrite: true` |
| Provider enum | `mempalace` in `_KNOWN_MEMORY_PROVIDERS` resolves correct rules script |

All scenarios run offline via stub command — no live MemPalace MCP server in CI.

## Rollout Plan

1. Land schema + hook registration + `mempalace-rules.sh` with fixtures (hook path testable without MCP).
2. Land `providers/mempalace.md` adapter doc + `CAPABILITIES.md` `linkEdges` flag.
3. Land export/import KG round-trip fixtures.
4. Update setup/export/import command docs; regenerate dist.
5. Dogfood optional: switch `.cursor/workflow.config.json` to `mempalace` in a follow-up operational PR
   (not required for merge).

## Decision Log

| ID | Decision | Rationale |
| --- | --- | --- |
| D1 | Full first-class provider (not spike) | Swappable like recallium/in-repo; brainstorm Q-scope |
| D2 | Verbatim embraced with `transcripts` Room exclusion | Prevents workflow retrieval degradation; Q-verbatim |
| D3 | R41 redaction ON by default | Protects re-injection and export; one-line `redactOnWrite` toggle |
| D4 | KG edges core (`linkEdges: true`) | First real edge-capable backend; Q-approach Full B |
| D5 | Hook fetch via configurable JSON command + TTL cache | MemPalace stdio-only; no REST sidecar; Q-rulefetch/Q-cache |
| D6 | Agent diaries deferred | Provider-local feature; split-brain risk; Q-diaries |
| D6a | Tasks fallback to local registry | MemPalace has no native task board; parity with in-repo |
| D7 | `softDelete: false` | MemPalace hard delete only; supersede-by-new-drawer for updates |
| D8 | SQLite-direct rule fetch rejected as default | Docker named volumes not host-readable on macOS |

## Open Questions

None. Brainstorm risks are resolved in Decision Log (D1–D8) or deferred as non-goals. Python-API recipe
pinning and hard-delete semantics are tracked as implementation notes in the task list (phases 2 and 3).
