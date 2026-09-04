---
frozen: false
prdBodyContract: v2
---
# Example PRD (v2 contract)

## Overview

Emit structured verdicts from gate scripts.

## Goals

- Reliable pre-freeze quality gates

## Non-Goals

- Auto-fixing PRD content

## Requirements

- **R1** Gate scripts must emit JSON verdict on stdout with stable keys
- **R2** Traceability must map every union R-ID to a named test scenario

## Technical Requirements

Shell + Python inline parsers.

## Security & Compliance

No secrets in gate output.

## Testing Strategy

Golden fixtures in scripts/test/fixtures.

## Acceptance Scenarios

- **Given** a new PRD body with `prdBodyContract: v2`, **when** Acceptance Scenarios and Success Criteria are present, **then** spec-rigor passes.
- **Given** a grandfathered PRD without the contract key, **when** the new sections are absent, **then** spec-rigor still passes.

## Success Criteria

- New PRDs without Acceptance Scenarios or Success Criteria fail spec-rigor at authoring time.
- Existing PRDs without `prdBodyContract: v2` never fail retroactively for those sections.

## Rollout Plan

Wire into sw-freeze and sw-tasks.

## Decision Log

- 2026-09-03: adopt prdBodyContract v2 for unit 4

## Open Questions

(none)
