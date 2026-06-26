---
date: 2026-06-26
topic: memory-source-of-truth
prd: docs/prds/015-memory-source-of-truth/015-prd-memory-source-of-truth.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 015 Provider-conditional memory source-of-truth

Generated from the frozen PRD `015-prd-memory-source-of-truth.md` (effective union R1–R12). Phases are
dependency-ordered: the resolver + config land first, then the always-committed snapshot + offline-safe freeze,
then pointer inversion + supersede, then compound/audit/migration, then docs/dist/fixtures.

## Tasks

### 1. SoT resolver + config/schema/defaults (M)

- [ ] 1.1 SoT resolution helper (R1, R2)
  - **File:** `scripts/memory-sot.sh`, `skills/memory/SKILL.md`
  - **Expected:** reads `memory.sourceOfTruth` + provider class; returns authoritative side (`repo`|`memory`) for the `decision` class; single-sourced for freeze/compound/audit
- [ ] 1.2 Config knob + schema + seeding (R2)
  - **File:** `.cursor/workflow.config.json`, `.sw/config.schema.json`, `core/sw-reference/` setup defaults
  - **Expected:** `memory.sourceOfTruth` (`repo`|`memory`|`auto`, default `auto`) accepted by schema and seeded
- [ ] 1.3 Decision-only scope guard (R3)
  - **File:** `scripts/memory-sot.sh`, `skills/memory/SKILL.md`
  - **Expected:** SoT switch applies only to `decision`; other classes remain distillation-only

### 2. Always-committed redacted snapshot + offline-safe freeze/CI (M)

- [ ] 2.1 Snapshot writer in freeze decision path (R4, R6, R10)
  - **File:** `core/commands/sw-freeze.md`, `scripts/memory-redact.sh` (invocation)
  - **Expected:** freeze always writes/refreshes a redacted `docs/decisions/<n>-<slug>.md` snapshot, stamps `authoritative: repo|memory` + forward pointer under memory-SoT
- [ ] 2.2 Offline-safe freeze/CI gate (R5)
  - **File:** `scripts/check-frozen.sh`, `core/commands/sw-freeze.md`
  - **Expected:** freeze + `check-frozen.sh` operate only on the committed snapshot, never call the provider; memory-SoT provider write is best-effort with an audit breadcrumb

### 3. Pointer inversion + supersede reconcile (M)

- [x] 3.1 Inverted authority pointer per SoT (R6)
  - **File:** `skills/memory/SKILL.md`, `scripts/memory-sot.sh`
  - **Expected:** repo-SoT → provider points at git record; memory-SoT → snapshot points at provider record; exactly one authoritative
- [x] 3.2 Supersede manifest + reconcile (R7)
  - **File:** `docs/decisions/SUPERSEDED.log` (handling), `scripts/reconcile-status.sh`, `core/commands/sw-memory-sync.md`
  - **Expected:** `SUPERSEDED.log` committed in both modes; `/sw-memory-sync` re-points the non-authoritative side best-effort

### 4. Compound SoT branch + audit conflict + migration (M)

- [x] 4.1 `/sw-retrospective` decision-write SoT branch (R8)
  - **File:** `skills/compound/SKILL.md`, `skills/memory/SKILL.md`
  - **Expected:** pointer under repo-SoT; content-bearing authoritative record under memory-SoT; redaction chokepoint always
- [x] 4.2 SoT-aware audit conflict + legacy reconcile (R9, R11)
  - **File:** `core/commands/sw-memory-audit.md`, `scripts/` (audit helper)
  - **Expected:** flags contradicting content-bearing decision memories; one-time legacy reconcile on mode switch; default `auto`+in-repo is no-change
- [x] 4.3 Fail-closed redaction across writes (R10)
  - **File:** `scripts/memory-redact.sh` (invocation), `skills/memory/SKILL.md`
  - **Expected:** a redaction failure aborts both the provider write and the snapshot write (no raw store); provider outage degrades to snapshot with a warning

### 5. Docs, dist, fixtures (M)

- [x] 5.1 Fixture suite for SoT behaviors (R12)
  - **File:** `scripts/test/run-memory-sot-fixtures.sh`, `.cursor/workflow.config.json`
  - **Expected:** fixtures named in the PRD Testing Strategy exist and pass; suite registered in `verify.test`
- [x] 5.2 Documentation updates (R12)
  - **File:** `skills/memory/SKILL.md`, `rules/memory-guardrails.mdc`, `.sw/layout.md`, `docs/guides/` (memory guide)
  - **Expected:** SoT policy documented; presence asserted by a fixture
- [x] 5.3 Emitter propagation + freshness gate (R12)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 1, 2, 3 |
| 5 | 1, 2, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | memory-sot-resolve-auto |
| R2 | 1.2 | memory-sot-resolve-auto / memory-sot-default-no-change |
| R3 | 1.3 | memory-sot-decision-scope-only |
| R4 | 2.1 | memory-sot-snapshot-always-committed |
| R5 | 2.2 | memory-sot-freeze-offline |
| R6 | 3.1 | memory-sot-pointer-inversion |
| R7 | 3.2 | memory-sot-supersede-reconcile |
| R8 | 4.1 | memory-sot-compound-branch |
| R9 | 4.2 | memory-sot-audit-conflict |
| R10 | 4.3 | memory-sot-redaction-fail-closed |
| R11 | 4.2 | memory-sot-default-no-change |
| R12 | 5.1, 5.2, 5.3 | memory-sot-emitter-freshness / memory-sot-docs-presence |
