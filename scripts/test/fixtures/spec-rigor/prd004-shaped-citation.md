---
frozen: false
prdBodyContract: v2
---
# PRD004-shaped citation labels (saved representative)

## Overview

Saved NOR-7 / PRD004-shaped body used as the in-repo oracle for citation-label wrapper regression (PRD 364 R7). R-ID bodies use the citation label `Source:` only — not unfinished-work colon wraps.

## Goals

- Prove citation labels are not punctuation-wrapper hits after PRD 364

## Non-Goals

- Live portfolio scan of 28 PRDs

## Requirements

- **R1** Source: approved specification.
- **R2** Source: approved specification for scope boundaries.
- **R3** Source: approved specification for rollout constraints.

## Technical Requirements

Golden fixture under `scripts/test/fixtures/spec-rigor/`.

## Security & Compliance

No secrets in gate output.

## Testing Strategy

Run `spec-rigor-check.py --artifact prd --path` on this file; no ambiguity finding whose only match is ordinary citation punctuation.

## Acceptance Scenarios

- **Given** this saved body, **when** spec-rigor runs, **then** R1–R3 do not fail on citation-label wrapper hits alone.

## Success Criteria

- Citation-label colons are not treated as colliding placeholder wraps.

## Rollout Plan

Land with PRD 364 phase 1 fixtures before matcher narrowing.

## Decision Log

- 2026-09-19: Vendored saved representative for PRD 364 R7 oracle (not a live PRD004 amend).

## Open Questions

(none)
