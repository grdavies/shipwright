---
date: 2026-01-01
topic: fixture
frozen: true
frozen_at: 2026-01-01
---
# PRD 099 — Fixture PRD

## Overview

Fixture corpus for post-migration spec-rigor and traceability regression.

## Goals

- Preserve gate behavior over the shared tokenizer.

## Non-Goals

- Relocation mechanics (covered by migration fixtures).

## Requirements

- **R1** Frozen immutability is preserved after migration.
- **R2** Traceability tables remain parseable through the tokenizer.
- **R3** Spec-rigor analyze pass succeeds on migrated task lists.

## Testing Strategy

Fixture-driven regression in `run-planning-currency-fixtures.sh`.
