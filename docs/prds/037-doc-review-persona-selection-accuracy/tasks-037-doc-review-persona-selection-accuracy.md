---
date: 2026-06-29
topic: doc-review-persona-selection-accuracy
prd: docs/prds/037-doc-review-persona-selection-accuracy/037-prd-doc-review-persona-selection-accuracy.md
frozen: true
frozen_at: 2026-06-29
---

# Tasks — PRD 037 Doc-review persona selection accuracy

Generated from the frozen PRD spec union (R1–R12). Phases follow the Rollout Plan: matcher fix → fixtures/parity → docs/propagate.

## Tasks

### 1. Heading matcher fix + manifest audit — S

- [ ] 1.1 Replace substring heading match with whole-token semantics
  - **File:** `scripts/capability_select.py` (`match_heading`)
  - **Expected:** heading triggers use `whole_token_pattern` / exact equality (per R1/D3); `## Requirements` no longer matches `UI`/`UX` triggers; optional shared `heading_has_token()` helper (R11)
  - **R-IDs:** R1, R11
- [ ] 1.2 Audit all `heading`-type triggers in the capability index
  - **File:** `core/sw-reference/capability-index.json`; findings in PRD Decision Log if needed
  - **Expected:** no remaining substring-containment false-positive class in doc-review or code-review families (R4)
  - **R-IDs:** R4
- [ ] 1.3 Extend manifest schema/validators if `match` mode is exposed on heading triggers
  - **File:** `core/sw-reference/capability-manifest.schema.json`, `scripts/capability_manifest_validate.py`, `scripts/capability_manifest_lint.py`
  - **Expected:** optional `match: whole_token|exact` on heading triggers validated and linted (R10)
  - **R-IDs:** R10

### 2. Fixtures + parity — M

- [ ] 2.1 Add negative persona-selection fixture
  - **File:** `scripts/test/fixtures/persona-selection/design-requirements-false-positive.md`
  - **Expected:** `<!-- expected-personas: core-only (Requirements heading must not fire design) -->`; wired in `scripts/test/run-persona-selection-fixtures.sh` (R9)
  - **R-IDs:** R2, R9
- [ ] 2.2 Confirm positive design fixtures remain green
  - **File:** `scripts/test/run-persona-selection-fixtures.sh`
  - **Expected:** `design-unambiguous`, `design-structural`, `design-polysemous-only` pass (R3)
  - **R-IDs:** R3
- [ ] 2.3 Run migration parity with documented delta
  - **File:** `scripts/test/run-migration-parity-fixtures.sh`
  - **Expected:** `migration-parity-doc-review` passes; only intentional delta is Requirements false-positive correction (R5)
  - **R-IDs:** R5

### 3. Docs, propagate, gap close — S

- [ ] 3.1 Update operator-facing selection contract
  - **File:** `core/skills/doc-review/SKILL.md`, `core/sw-reference/capability-manifest.md` (if heading contract stated)
  - **Expected:** heading matching documented as whole-token or exact, not substring (R6)
  - **R-IDs:** R6
- [ ] 3.2 Propagate to core/dist
  - **File:** `core/scripts/capability_select.py`, `dist/cursor/**`, `dist/claude-code/**` via `bash scripts/copy-to-core.sh` + `python3 -m sw generate --all`
  - **Expected:** emitter-freshness + parity fixtures pass (R8)
  - **R-IDs:** R8
- [ ] 3.3 Close GAP-047 on ship
  - **File:** `docs/prds/GAP-BACKLOG.md` (status flip) or gap-resolve path when available
  - **Expected:** GAP-047 marked `resolved — PRD 037` after merge (R7)
  - **R-IDs:** R7

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | `design-requirements-false-positive` |
| R2 | 2.1 | `design-requirements-false-positive` |
| R3 | 2.2 | `design-unambiguous`; `design-structural`; `design-polysemous-only` |
| R4 | 1.2 | heading-trigger audit (manual + lint) |
| R5 | 2.3 | `migration-parity-doc-review` |
| R6 | 3.1 | doc-review SKILL heading contract |
| R7 | 3.3 | GAP-047 resolved |
| R8 | 3.2 | emitter-freshness |
| R9 | 2.1 | `design-requirements-false-positive` |
| R10 | 1.3 | manifest schema heading `match` |
| R11 | 1.1 | shared heading/token helper |
| D1 | 1.1, 3.3 | successor PRD not 021 amendment (design) |
| D2 | 1.1 | matcher fix not manifest-only (design) |
| D3 | 1.1 | whole_token default heading mode (design) |
| R12 | — | no new security surface (review only) |

## Relevant Files

- `scripts/capability_select.py` — `match_heading` fix
- `scripts/test/fixtures/persona-selection/design-requirements-false-positive.md` — negative fixture
- `scripts/test/run-persona-selection-fixtures.sh` — extended corpus
- `core/sw-reference/capability-index.json` — heading trigger audit
- `core/skills/doc-review/SKILL.md` — operator contract

## Notes

- PRD 021 is complete; this is a successor defect-repair PRD (D1).
- The PRD draft itself demonstrated the bug: `doc-review-select.sh` fired `design` on `## Requirements` during `/sw-doc-review` selection.
