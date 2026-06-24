---
frozen: false
---
# Example PRD

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

- 2026-06-23: tier-gated clarify (Full only)

## Open Questions

(none)
