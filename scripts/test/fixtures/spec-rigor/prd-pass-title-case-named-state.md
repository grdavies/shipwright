---
frozen: false
---
# NOR-7 shaped Title-case named state

## Overview

Consumer lifecycle labels collide with placeholder vocabulary.

## Goals

- Accept Title-case named states without a reviewed-literal entry

## Non-Goals

- Weakening unresolved-placeholder detection

## Requirements

- **R1** Workflow enters Todo when entry criteria are met and leaves Todo on completion
- **R2** Tags may use idea/todo/note slash-taxonomy without failing the gate

## Technical Requirements

Layered matcher in spec-rigor-check.

## Security & Compliance

No secrets in gate output.

## Testing Strategy

Golden fixture matrix under scripts/test/fixtures/spec-rigor.

## Rollout Plan

Ship with PRD 361.

## Decision Log

## Open Questions

(none)
