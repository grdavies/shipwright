---
date: 2026-06-26
topic: pre-work-memory-search-gate
prd: docs/prds/019-pre-work-memory-search-gate/019-prd-pre-work-memory-search-gate.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 019 Pre-work memory-search obligation (read-before-work gate)

Generated from the frozen PRD spec union (R1–R10). Phases are dependency-ordered per the Rollout Plan:
entry obligation → record/degrade-open recorder → enforcement + dispatch inheritance → docs/dist/fixtures.

## Tasks

### 1. Memory-preflight entry obligation — M

The mandatory scoped pre-work search at work-performing command entry, with the surface + reconcile contract.

- [ ] 1.1 Add the mandatory pre-work search to `memory-preflight` + each work-performing command entry
  - **File:** `core/skills/memory/SKILL.md`; procedure blocks in `core/commands/sw-execute.md`, `sw-debug.md`, `sw-prd.md`, `sw-brainstorm.md`, `sw-amend.md`, `sw-review.md`, `sw-stabilize.md`
  - **Expected:** a "pre-work search (mandatory)" section with the scoped read recipe (file-path + semantic + classes `rule`/`decision`/`learning`/`code-context`/`design`); each enumerated command routes the search before its first mutation, via `memory-preflight` + `providers/<memory.provider>.md` (no direct provider call)
  - **R-IDs:** R1, R3, R4
- [ ] 1.2 Surface + reconcile contract
  - **File:** `core/skills/memory/SKILL.md` (reconcile section), enumerated command procedures
  - **Expected:** hits surfaced before mutation; applicable `rule` / contradicting `decision` forces a recorded reconcile (alignment or explicit conflict + resolution); unreconcilable conflict with a frozen rule/decision routes to the command's halt contract — never a silent ignore
  - **R-IDs:** R5

### 2. Search record + degrade-open breadcrumb — M

Single-sourced mechanical recorder of the search artifact / offline / none breadcrumb.

- [ ] 2.1 Search-record recorder with degrade-open + audited breadcrumb
  - **File:** `scripts/wave.sh` (`memory preflight` verb) / shared recorder; `scripts/memory-redact.py` integration; per-repo state / `run.log`
  - **Expected:** records a per-surface search artifact (scope + classes + nonce) on a reachable provider, or a `memory:offline` breadcrumb when the adapter reachability probe fails, or `memory:none` when the search returns nothing; all redacted via `memory-redact.py` (R41); offline is probe-gated, never agent-asserted; single recorder shared by command + dispatch paths
  - **R-IDs:** R6, R7

### 3. Enforcement + dispatch inheritance — M

Mechanical pre-mutation deny (reusing PRD 017 R23), dispatch-rule obligation, and prompt redaction reuse.

- [ ] 3.1 `preToolUse` deny for missing pre-work search record (reuse PRD 017 R23)
  - **File:** `core/hooks/before_task_dispatch.py` / registered `preToolUse` hook
  - **Expected:** the first file-mutating tool call for a work-performing surface is denied when no fresh search record (or `memory:offline` breadcrumb) exists; reuses the PRD 017 R23 deny mechanism (no second hook); degrade-open breadcrumb satisfies the gate
  - **R-IDs:** R8
- [ ] 3.2 Dispatch-rule obligation inheritance
  - **File:** `core/rules/sw-subagent-dispatch.mdc`
  - **Expected:** delegated work-performing sub-agents perform the pre-work search or are handed a fresh redacted result; pure-exploration / mechanical non-mutating dispatch exempt
  - **R-IDs:** R2
- [ ] 3.3 Forwarded memory-result redaction reuse
  - **File:** delegated dispatch-prompt assembly; `scripts/memory-redact.py` (reuse PRD 017 R25 path)
  - **Expected:** memory-search results assembled into a delegated `Task` prompt are redacted + fenced; raw payloads never forwarded
  - **R-IDs:** R9

### 4. Docs + dist + fixtures — M

- [ ] 4.1 Regenerate `dist/` and pass the freshness gate
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `scripts/test/run-emitter-fixtures.sh` passes; `dist/` parity with `core/`
  - **R-IDs:** R10
- [ ] 4.2 Author the fixture suite (integration-style for the deny + recorder)
  - **File:** `scripts/test/run-memory-fixtures.sh` / `run-dispatch-fixtures.sh` (new scenarios)
  - **Expected:** all Testing-Strategy fixtures present and green, including the `preToolUse` deny and degrade-open observation (not doc-grep-only)
  - **R-IDs:** R10
- [ ] 4.3 Update documentation
  - **File:** `core/skills/memory/SKILL.md`, `core/rules/sw-subagent-dispatch.mdc`, the enumerated command files, `.sw/layout.md`, memory guide
  - **Expected:** the pre-work search obligation, degrade-open contract, recorder breadcrumb, and dispatch inheritance documented
  - **R-IDs:** R10

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | `memory-prework-search-entry` |
| R2 | 3.2 | `memory-prework-dispatch-inherited` |
| R3 | 1.1 | `memory-prework-provider-agnostic` |
| R4 | 1.1 | `memory-prework-search-entry` (scoped recipe) |
| R5 | 1.2 | `memory-prework-surface-reconcile` |
| R6 | 2.1 | `memory-prework-degrade-open` |
| R7 | 2.1 | `memory-prework-breadcrumb-audited` |
| R8 | 3.1 | `memory-prework-pretooluse-deny` |
| R9 | 3.3 | `memory-prework-prompt-redacted` |
| R10 | 4.1, 4.2, 4.3 | `memory-prework-emitter-freshness`; `memory-prework-docs-presence` |

## Relevant Files

- `core/skills/memory/SKILL.md` — mandatory pre-work search + scoped recipe + reconcile contract
- `core/rules/sw-subagent-dispatch.mdc` — dispatch inheritance of the obligation
- `core/commands/sw-execute.md`, `sw-debug.md`, `sw-prd.md`, `sw-brainstorm.md`, `sw-amend.md`, `sw-review.md`, `sw-stabilize.md` — entry hooks
- `scripts/wave.sh` (`memory preflight`) / shared recorder, `scripts/memory-redact.py` — record + degrade-open breadcrumb + redaction
- `core/hooks/before_task_dispatch.py` — `preToolUse` deny reuse (PRD 017 R23)
- `.sw/layout.md`, memory guide — documentation

## Notes

- Enforcement (task 3.1) reuses the PRD 017 R23 preflight/`preToolUse` deny mechanism; if PRD 017 has not
  landed, ship the recorder + procedural obligation (Phases 1–2) and wire the deny when 017's hook is present
  (graceful sequencing per the Rollout Plan — not a hard dependency).
- Degrade-open (R6) preserves today's behavior on a memory outage; offline is probe-gated, never agent-asserted.
