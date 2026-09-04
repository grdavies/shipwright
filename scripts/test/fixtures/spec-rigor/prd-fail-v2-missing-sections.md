---
frozen: false
prdBodyContract: v2
---
# Example PRD missing v2 sections

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

## Rollout Plan

Wire into sw-freeze and sw-tasks.

## Decision Log

- none

## Open Questions

(none)
