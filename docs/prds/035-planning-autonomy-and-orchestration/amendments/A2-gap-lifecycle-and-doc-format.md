---
date: 2026-06-29
amends: docs/prds/035-planning-autonomy-and-orchestration/035-prd-planning-autonomy-and-orchestration.md
absorbs:
  - GAP-043
  - GAP-044
  - GAP-045
  - GAP-046
frozen: true
frozen_at: 2026-06-29
---

# Amendment A2: Gap lifecycle mechanics + shared doc-format tokenizer

## Overview

Four open gaps block trustworthy planning automation and overlap parent PRD 035 pull-in goals (R1–R5, R17,
minimum-recall fixture `min-recall-gap-043-044-046`):

- **GAP-043** — `open` → `resolved` flip on PRD ship is not mechanical; binary status model adopted
  2026-06-29 but tooling still stale.
- **GAP-044** — gap ID append protocol + index integrity guard (manual today).
- **GAP-046** — `open` → `planned` flip at freeze/absorption not mechanical (upstream half of GAP-043).
- **GAP-045** — model-dependent doc formatting breaks spec-rigor/traceability; parsers disagree; no shared
  tokenizer (PRD 031 scope residual).

This amendment continues the parent + A1 namespace at **R51–R58** and tightens parent R5 minimum-recall
acceptance.

## Context

Parent PRD 035 already proposes pull-in at `/sw-prd` and `/sw-tasks` with human confirm (R1–R2) and expects
GAP-043/044/046 in the minimum-recall corpus (R5). Without mechanical gap-row lifecycle and a canonical
doc-format normalizer, pull-in proposals will drift from GAP-BACKLOG reality and spec-rigor will keep
rejecting semantically valid PRD/amendment bodies.

## Goals

1. **Binary gap status contract** — `resolved` | `open — <schedule>` only; mechanical flip on PRD ship.
2. **Absorption-time flip** — frozen PRD/amendment `absorbs:` frontmatter updates backlog schedule at freeze.
3. **Append protocol** — stable `GAP-NNN` IDs, index/table integrity CI guard.
4. **Shared tokenizer** — pre-freeze structural normalizer for R-ID/D-ID bullets consumed by spec-rigor and
   traceability (PRD 031 seam).

## Non-Goals

- Replacing hand-maintained gap narrative bodies with projection stubs (PRD 031 cutover guard remains).
- Auto-absorb without human confirm (parent R1–R2).
- Deliver-loop fixes (PRD 035 A1).

## Requirements

- **R51** (closes GAP-043) `living-status` gap-resolve MUST flip GAP-BACKLOG rows from `open — PRD <n>` (or
  `open — PRD <n> A<k>`) to `resolved — PRD <n>` when the absorbing unit reaches `complete`, using stable
  `GAP-NNN` id match (not table row number). Fixture: `gap-resolve-on-prd-ship`.
- **R52** (closes GAP-046) `/sw-freeze` on PRD/amendment MUST, when frontmatter lists `absorbs: [GAP-NNN, …]`,
  rewrite matching backlog Status to `open — PRD <n>` or `open — PRD <n> A<k>` (schedule, not `resolved`).
  Fixture: `freeze-absorbs-flips-gap-schedule`.
- **R53** (closes GAP-044) Document append protocol in `core/skills/living-status/SKILL.md` and
  `.sw/layout.md`: next id = max+1, never reuse; cross-links use `GAP-NNN`. Fixture:
  `gap-backlog-index-integrity` asserts index counts match table binary statuses.
- **R54** (closes GAP-044) `scripts/gap-backlog.sh` (or extend `living-status` scripts) MUST expose
  `list --json` for CI guard; `docs-currency-gate.sh` validates index/table consistency. Fixture:
  `gap-backlog-ci-guard`.
- **R55** (closes GAP-045) A shared **doc-format tokenizer** module (`scripts/doc_format_tokenizer.py`) MUST
  canonicalize R-ID/D-ID bullet shapes, heading levels, and amendment task checkbox lines **before**
  `spec-rigor-check.sh` / `traceability-check.sh` — opt-in per command via `--normalize` on freeze path.
  Fixture: `doc-format-normalize-before-rigor`.
- **R56** (closes GAP-045) Spec-rigor and traceability MUST share one bullet regex source imported from the
  tokenizer package (no divergent patterns). Fixture: `spec-rigor-traceability-regex-parity`.
- **R57** Parent R5 minimum-recall fixture `min-recall-gap-043-044-046` MUST pass on the migrated corpus
  after R51–R52 land (acceptance gate for this amendment).
- **R58** `/sw-feedback` gap-capture route MUST prefer planning gap units over raw GAP-BACKLOG append when
  PRD 031 graph is active (parent R21 cross-ref); GAP-BACKLOG remains relief valve with R53 protocol.

## Testing Strategy

| Fixture | R-IDs |
|---------|-------|
| `gap-resolve-on-prd-ship` | R51 |
| `freeze-absorbs-flips-gap-schedule` | R52 |
| `gap-backlog-index-integrity` | R53 |
| `gap-backlog-ci-guard` | R54 |
| `doc-format-normalize-before-rigor` | R55 |
| `spec-rigor-traceability-regex-parity` | R56 |
| `min-recall-gap-043-044-046` | R57 |

## Implementation note (task integration)

Add **Phase 8 — Gap lifecycle + doc format** to `tasks-035-…` after Phase 7 (A1). Phase 8 may start in
parallel with Phase 1 scanner once tokenizer module exists (feeds `/sw-prd` pull-in proposal formatting).

## Documentation deliverables

- `core/skills/living-status/SKILL.md` — binary status contract, R51–R53.
- `core/commands/sw-freeze.md` — R52 `absorbs:` behavior.
- `core/commands/sw-feedback.md` — R58 routing.
- `skills/spec-rigor/SKILL.md` — R55–R56 normalize hook.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Binary status only | Operator policy 2026-06-29; retires `planned` / `partially resolved` in tooling. |
| DL-2 | Tokenizer on freeze path | Spec-rigor stays fail-closed; normalizer runs opt-in before rigor, not silent auto-fix mid-authoring. |
| DL-3 | Co-locate with 035 pull-in | GAP-043/046 are upstream of mechanical `resolved` flip; scanner minimum-recall depends on accurate backlog. |

## Gap resolution (on ship)

| ID | Expected status |
|----|-----------------|
| GAP-043 | `resolved — PRD 035 A2 R51` |
| GAP-044 | `resolved — PRD 035 A2 R53–R54` |
| GAP-045 | `resolved — PRD 035 A2 R55–R56` |
| GAP-046 | `resolved — PRD 035 A2 R52` |
