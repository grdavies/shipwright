---
date: 2026-06-25
topic: caveman-command-loading
prd: docs/prds/006-caveman-command-loading/006-prd-caveman-command-loading.md
frozen: true
frozen_at: 2026-06-25
---

# Task list — PRD 006 caveman command loading

> **Status: complete.** Delivered in `b8145b2` (feat: caveman command loading (PRD 006) (#65));
> `communication-routing.defaults.json` key parity later depended on by PRD 008. Checkboxes ticked
> retroactively after verifying landed artifacts and green fixture suites (`run-doc-fixtures.sh`
> → `communication-routing.sh`). Fixtures live at `scripts/test/fixtures/communication-routing.sh`
> (single file) rather than the `communication-routing/` directory named above. No source
> re-implementation performed.

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Bundled core | `core/communication/caveman-core.md` (new) |
| Session hook | `core/hooks/session-context.md`, `core/hooks/guardrail_core.py` |
| Routing defaults | `core/sw-reference/communication-routing.defaults.json` (new) |
| Override command | `core/commands/sw-caveman.md` (new) |
| All commands | `core/commands/sw-*.md` (34 files) |
| Config | `.sw/config.schema.json`, `core/sw-reference/config.schema.json`, `.sw/workflow.config.example.json` |
| Setup | `core/commands/sw-setup.md` |
| Resolver | `scripts/communication-resolve.sh` (new) |
| Plugin manifest | `.cursor-plugin/plugin.json` |
| Emitter | `platforms/cursor/emitter.py`, `platforms/claude-code/emitter.py` |
| Docs | `docs/guides/configuration.md` |
| Fixtures | `scripts/test/fixtures/communication-*`, `scripts/test/run-doc-fixtures.sh` |
| Dist | `dist/cursor/`, `dist/claude-code/` |

## Notes

- Effective spec union: parent PRD R1–R22 (`spec-union.sh`).
- Intensity vocabulary closed at four values; wenyan excluded everywhere (R10).
- `communication.routing` parallels future `models.routing` key set (R14).
- Artifact file content stays full fidelity at all chat intensities (R8/R30).
- Regenerate `dist/` after `core/` changes; emitter freshness gate must pass (R22).

## Tasks

### 1. Bundled core & session hook (M)

- [x] 1.1 Author `caveman-core.md` (R1, R10)
  - **File:** `core/communication/caveman-core.md`
  - **Expected:** ≤35 lines; four intensity definitions; Auto-Clarity; artifact boundaries; no wenyan
  - **R-IDs:** R1, R10

- [x] 1.2 Rewrite `session-context.md` (R3, R15)
  - **File:** `core/hooks/session-context.md`
  - **Expected:** no `` `/caveman` `` or phantom slash refs; describes routing-based always-on policy
  - **R-IDs:** R3, R15

- [x] 1.3 Update `build_session_context()` (R2, R16, R19, R20)
  - **File:** `core/hooks/guardrail_core.py`
  - **Expected:** injects caveman-core; splices resolved intensity; output has no `` `/caveman` ``; uses `defaultIntensity` when no active command
  - **R-IDs:** R2, R16, R19, R20

### 2. Config, schema & routing defaults (M)

- [x] 2.1 Add `communication-routing.defaults.json` (R5, R14)
  - **File:** `core/sw-reference/communication-routing.defaults.json`
  - **Expected:** all 34 `sw-*` commands mapped; `defaultIntensity: full`; matches PRD routing table
  - **R-IDs:** R5, R14

- [x] 2.2 Extend config schema with `communication` block (R4, R10)
  - **File:** `.sw/config.schema.json`, `core/sw-reference/config.schema.json`
  - **Expected:** intensity enum `normal|lite|full|ultra` only; rejects wenyan; `routing.commands` object
  - **R-IDs:** R4, R10

- [x] 2.3 Update workflow example config (R5, R16)
  - **File:** `.sw/workflow.config.example.json`
  - **Expected:** populated `communication` example block with `defaultIntensity` and sample routing
  - **R-IDs:** R5, R16

- [x] 2.4 Add `communication-resolve.sh` (R6, R17)
  - **File:** `scripts/communication-resolve.sh`
  - **Expected:** given command name + optional config path → JSON `{ "command", "intensity", "source" }`; handles `inherit` orchestrators
  - **R-IDs:** R6, R17

### 3. Commands & override (L)

- [x] 3.1 Author `sw-caveman.md` (R9, R21)
  - **File:** `core/commands/sw-caveman.md`
  - **Expected:** args `normal|lite|full|ultra`; no-arg shows resolved intensity; references caveman-core only
  - **R-IDs:** R9, R21

- [x] 3.2 Register `sw-caveman` in plugin manifest (R21)
  - **File:** `.cursor-plugin/plugin.json`
  - **Expected:** command path declared; Cursor slash UI resolves `/sw-caveman`
  - **R-IDs:** R21

- [x] 3.3 Stamp **Communication intensity** on all `sw-*.md` (R7)
  - **File:** `core/commands/sw-*.md` (34 files)
  - **Expected:** each file has `**Communication intensity:**` line per routing defaults
  - **R-IDs:** R7

- [x] 3.4 Update `sw-setup.md` seeding (R5)
  - **File:** `core/commands/sw-setup.md`
  - **Expected:** seeds `communication.defaultIntensity` and full routing map from defaults JSON
  - **R-IDs:** R5

### 4. Emitter & dist propagation (S)

- [x] 4.1 Update emitters to copy new artifacts (R12)
  - **File:** `platforms/cursor/emitter.py`, `platforms/claude-code/emitter.py`
  - **Expected:** copies `caveman-core.md`, `communication-routing.defaults.json`, `sw-caveman.md`, updated session-context
  - **R-IDs:** R12

- [x] 4.2 Regenerate dist trees (R12, R22)
  - **File:** `dist/cursor/`, `dist/claude-code/`
  - **Expected:** `python3 -m sw generate --all`; `run-emitter-fixtures.sh` passes
  - **R-IDs:** R12, R22

### 5. Documentation (S)

- [x] 5.1 Document communication routing in configuration guide (R13)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** four intensities explained; `communication.routing` shape; `/sw-caveman` override semantics
  - **R-IDs:** R13

### 6. Fixtures & verification (M)

- [x] 6.1 Add communication routing fixtures (R11, R18, R19)
  - **File:** `scripts/test/fixtures/communication-routing/`, updates to `scripts/test/run-doc-fixtures.sh`
  - **Expected:** phantom-slash grep pass; `sw-prd`→`lite`, `sw-triage`→`ultra`, `sw-doc-review`→`normal`; wenyan schema rejection
  - **R-IDs:** R11, R18, R19

- [x] 6.2 Run full verify gate (R22)
  - **File:** `scripts/test/run-gate-fixtures.sh` (and siblings via `workflow.config.json` verify.test)
  - **Expected:** all fixture suites green including emitter and doc fixtures
  - **R-IDs:** R22

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 2 |
| 4 | 1, 3 |
| 5 | 2, 3 |
| 6 | 1, 2, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | communication-caveman-core-line-count fixture |
| R2 | 1.3 | communication-session-inject fixture |
| R3 | 1.2 | communication-no-phantom-slash fixture |
| R4 | 2.2 | communication-schema-enum fixture |
| R5 | 2.1, 3.4 | communication-routing-defaults-complete fixture |
| R6 | 2.4 | communication-resolve-inherit fixture |
| R7 | 3.3 | communication-command-intensity-lines fixture |
| R8 | 1.1 | communication-artifact-boundary fixture (caveman-core prose) |
| R9 | 3.1 | communication-sw-caveman-args fixture |
| R10 | 1.1, 2.2 | communication-no-wenyan fixture |
| R11 | 6.1 | communication-routing-resolution fixture |
| R12 | 4.1, 4.2 | run-emitter-fixtures.sh dist copy |
| R13 | 5.1 | communication-config-guide fixture |
| R14 | 2.1 | communication-routing-key-coverage fixture |
| R15 | 1.2 | communication-normal-suspend fixture |
| R16 | 1.3, 2.3 | communication-default-intensity fixture |
| R17 | 2.4 | communication-resolve.sh stdout JSON |
| R18 | 6.1 | run-doc-fixtures.sh communication scenarios |
| R19 | 1.3 | communication-session-output-grep fixture |
| R20 | 1.3 | communication-intensity-splice fixture |
| R21 | 3.1, 3.2 | communication-sw-caveman-registered fixture |
| R22 | 4.2, 6.2 | run-emitter-fixtures.sh + full verify gate |
