---
date: 2026-06-25
topic: mempalace-memory-provider
prd: docs/prds/010-mempalace-memory-provider/010-prd-mempalace-memory-provider.md
frozen: true
frozen_at: 2026-06-25
---

# Task list — PRD 010 MemPalace memory provider

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Adapter doc | `core/providers/mempalace.md` (new) |
| Rule fetcher | `core/providers/mempalace-rules.sh` (new) |
| Hook util | `core/hooks/pf_hook_util.py`, `core/hooks/before-submit-guardrails.py` |
| Capability spec | `core/skills/memory/CAPABILITIES.md` |
| Schema | `core/sw-reference/config.schema.json`, `.sw/config.schema.json` |
| Setup / export / import | `core/commands/pf-setup.md`, `core/commands/pf-memory-export.md`, `core/commands/pf-memory-import.md` |
| Fixtures | `scripts/test/fixtures/mempalace-rules-stub.sh`, `scripts/test/fixtures/mempalace-*` |
| Fixture runner | `scripts/test/run-memory-provider-fixtures.sh` |
| Redaction | `scripts/memory-redact.sh` |
| Build chain | `python3 -m sw generate --all`, `bash scripts/copy-to-core.sh`, `dist/cursor/`, `dist/claude-code/` |

## Notes

- Effective spec union: parent PRD R1–R38 (`spec-union.sh`).
- Two transport paths: agent MCP (`mempalace.md`) and hook CLI (`mempalace-rules.sh`) — design and test independently.
- Python-API `ruleFetchCommand` recipe is provisional — pin exact enumeration call in task 2.2 against installed MemPalace.
- `softDelete: false` — inactivate is hard delete; document prominently in adapter (D7).
- Edit `core/` + `scripts/`; regenerate dist; do not hand-edit `dist/` or `core/scripts/` without emitter/sync.

## Tasks

### 1. Schema & provider registration (M)

- [ ] 1.1 Add `mempalace` to config schema (R5, R6, R7)
  - **File:** `core/sw-reference/config.schema.json`
  - **Expected:** `memory.provider` enum includes `mempalace`; `memory.mempalace` object with `additionalProperties: false` and all required keys + defaults; unknown keys rejected
  - **R-IDs:** R5, R6, R7

- [ ] 1.2 Regenerate `.sw/config.schema.json` from core (R5)
  - **File:** run `python3 -m sw generate`
  - **Expected:** `.sw/config.schema.json` mirrors core schema including `mempalace` block
  - **R-IDs:** R5

- [ ] 1.3 Register provider in hook util (R4)
  - **File:** `core/hooks/pf_hook_util.py`
  - **Expected:** `"mempalace"` in `_KNOWN_MEMORY_PROVIDERS`; `rules_script_for_provider` resolves `providers/mempalace-rules.sh`
  - **R-IDs:** R4

### 2. Hook rule-fetcher & offline fixtures (L)

- [ ] 2.1 Implement `mempalace-rules.sh` core (R23–R29)
  - **File:** `core/providers/mempalace-rules.sh`
  - **Expected:** provider gate; runs `ruleFetchCommand`; JSON contract `{ok, rules:[{id,summary}]}`; TTL cache at `.cursor/pf-memory/.mempalace-rules-cache.json` with atomic write + file lock; `failClosed` behavior; prefix allowlist + metachar rejection; `MAX_RULE_CHARS=2000`; room=`rules` filter
  - **R-IDs:** R23, R24, R25, R26, R27, R28, R29

- [ ] 2.2 Pin Python-API enumeration recipe (R24, R33)
  - **File:** comments in `mempalace-rules.sh` + `core/commands/pf-setup.md`
  - **Expected:** documented local + Docker `ruleFetchCommand` one-liners tested against pinned MemPalace version; bind-mount guidance for macOS Docker
  - **R-IDs:** R24, R31, R33

- [ ] 2.3 Add unreachable-message branch (R30)
  - **File:** `core/hooks/before-submit-guardrails.py`
  - **Expected:** `mempalace` branch in `_provider_unreachable_message` with install, `ruleFetchCommand`, `palacePath`/bind-mount remediation
  - **R-IDs:** R30

- [ ] 2.4 Author rules stub fixture (R34, R35)
  - **File:** `scripts/test/fixtures/mempalace-rules-stub.sh`
  - **Expected:** emits fixture `{ok,rules}` JSON; usable as `ruleFetchCommand` in tests
  - **R-IDs:** R34, R35

- [ ] 2.5 Extend memory-provider fixtures for MemPalace hook path (R34–R36)
  - **File:** `scripts/test/run-memory-provider-fixtures.sh`, `scripts/test/fixtures/mempalace-*`
  - **Expected:** cases for cache miss→write, fresh→skip command, failClosed block, stale serve, allowlist reject, rule cap, room filter, schema accept/reject, `PF_RULES_SCRIPT` hook integration
  - **R-IDs:** R34, R35, R36

### 3. Adapter doc & capability spec (L)

- [ ] 3.1 Document `linkEdges` in CAPABILITIES (R3)
  - **File:** `core/skills/memory/CAPABILITIES.md`
  - **Expected:** `linkEdges` flag documented; MemPalace noted as first edge-capable provider; Recallium/in-repo default `false`
  - **R-IDs:** R3

- [ ] 3.2 Author `mempalace.md` adapter (R1, R2, R8–R22)
  - **File:** `core/providers/mempalace.md`
  - **Expected:** capability flags including `linkEdges:true`, `softDelete:false`; Wing/Room/Drawer taxonomy; op→`mempalace_*` mapping; `searchExcludeRooms`; `redactOnWrite`; hard-delete semantics documented
  - **R-IDs:** R1, R2, R8, R9, R10, R11, R12, R13, R14, R15, R16, R17, R18, R19, R20, R21, R22

### 4. Export/import KG round-trip & R41 fixtures (M)

- [ ] 4.1 KG edge round-trip fixture (R37)
  - **File:** `scripts/test/run-memory-provider-fixtures.sh`, `scripts/test/fixtures/mempalace-kg-*`
  - **Expected:** export `links[]` ↔ KG triples round-trip validated (extends stub edge test with MemPalace provider context)
  - **R-IDs:** R21, R22, R37

- [ ] 4.2 R41 redaction fixture for MemPalace write path (R17, R38)
  - **File:** `scripts/test/run-memory-provider-fixtures.sh`
  - **Expected:** planted secret scrubbed when `redactOnWrite:true`; bypass documented/tested when `false`
  - **R-IDs:** R17, R38

### 5. Command docs, emitter & dist (S)

- [ ] 5.1 Update pf-setup, export, import command docs (R31, R32, R33)
  - **File:** `core/commands/pf-setup.md`, `core/commands/pf-memory-export.md`, `core/commands/pf-memory-import.md`
  - **Expected:** MemPalace provider selection, `palacePath`, shipped recipes, KG edge round-trip, `redactOnWrite` behavior, Docker bind-mount note
  - **R-IDs:** R31, R32, R33

- [ ] 5.2 Regenerate dist and sync core mirrors (R1–R4)
  - **File:** `python3 -m sw generate --all`, `bash scripts/copy-to-core.sh`
  - **Expected:** `dist/cursor/` and `dist/claude-code/` include `mempalace.md`, `mempalace-rules.sh`, hook changes, schema; `core/scripts/` parity maintained
  - **R-IDs:** R1, R4

- [ ] 5.3 Verify full gate fixture suite (R34–R38)
  - **File:** `bash scripts/test/run-memory-provider-fixtures.sh`
  - **Expected:** all MemPalace fixtures pass; wired in `workflow.config.json` `verify.test`
  - **R-IDs:** R34, R35, R36, R37, R38

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 3 |
| 5 | 2, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 3.2, 5.2 | run-memory-provider-fixtures.sh mempalace provider doc |
| R2 | 3.2 | run-memory-provider-fixtures.sh adapter capability flags |
| R3 | 3.1 | run-memory-provider-fixtures.sh linkEdges in CAPABILITIES |
| R4 | 1.3, 5.2 | run-memory-provider-fixtures.sh _KNOWN_MEMORY_PROVIDERS |
| R5 | 1.1, 1.2 | run-memory-provider-fixtures.sh schema enum |
| R6 | 1.1 | run-memory-provider-fixtures.sh mempalace config block |
| R7 | 1.1 | run-memory-provider-fixtures.sh schema rejects unknown keys |
| R8 | 3.2 | run-memory-provider-fixtures.sh taxonomy wing mapping doc |
| R9 | 3.2 | run-memory-provider-fixtures.sh taxonomy room mapping doc |
| R10 | 3.2 | run-memory-provider-fixtures.sh drawer id mapping doc |
| R11 | 3.2 | run-memory-provider-fixtures.sh searchExcludeRooms doc |
| R12 | 3.2 | run-memory-provider-fixtures.sh rules room isolation doc |
| R13 | 3.2 | run-memory-provider-fixtures.sh load-context mapping doc |
| R14 | 3.2 | run-memory-provider-fixtures.sh rules-load agent path doc |
| R15 | 3.2 | run-memory-provider-fixtures.sh search mapping doc |
| R16 | 3.2 | run-memory-provider-fixtures.sh expand mapping doc |
| R17 | 3.2, 4.2 | run-memory-provider-fixtures.sh store redaction |
| R18 | 3.2 | run-memory-provider-fixtures.sh modify hard-delete doc |
| R19 | 3.2 | run-memory-provider-fixtures.sh list-recent mapping doc |
| R20 | 3.2 | run-memory-provider-fixtures.sh tasks fallback doc |
| R21 | 3.2, 4.1 | run-memory-provider-fixtures.sh KG link mapping |
| R22 | 3.2, 4.1 | run-memory-provider-fixtures.sh export/import links |
| R23 | 2.1 | run-memory-provider-fixtures.sh provider gate |
| R24 | 2.1, 2.2 | run-memory-provider-fixtures.sh ruleFetch JSON contract |
| R25 | 2.1 | run-memory-provider-fixtures.sh rules room filter |
| R26 | 2.1 | run-memory-provider-fixtures.sh cache TTL + atomic write |
| R27 | 2.1 | run-memory-provider-fixtures.sh failClosed block |
| R28 | 2.1 | run-memory-provider-fixtures.sh allowlist reject |
| R29 | 2.1 | run-memory-provider-fixtures.sh rule size cap |
| R30 | 2.3 | run-memory-provider-fixtures.sh unreachable message |
| R31 | 2.2, 5.1 | run-memory-provider-fixtures.sh pf-setup mempalace docs |
| R32 | 5.1 | run-memory-provider-fixtures.sh export/import docs |
| R33 | 2.2, 5.1 | run-memory-provider-fixtures.sh docker bind-mount docs |
| R34 | 2.5 | run-memory-provider-fixtures.sh cache scenarios |
| R35 | 2.5 | run-memory-provider-fixtures.sh PF_RULES_SCRIPT hook |
| R36 | 2.5 | run-memory-provider-fixtures.sh schema fixture |
| R37 | 4.1 | run-memory-provider-fixtures.sh KG round-trip |
| R38 | 4.2 | run-memory-provider-fixtures.sh R41 redactOnWrite |
