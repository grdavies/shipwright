---
frozen: false
reviewedLiterals:
  - TODO
---
# Reviewed-literal exact allowlist

## Overview

Product brand uses an all-caps token that would otherwise fail the gate.

## Goals

- Prove exact reviewedLiterals suppression

## Non-Goals

- Case-fold exemptions

## Requirements

- **R1** Product name TODO ships as the brand label in UI copy

## Technical Requirements

list-capable reviewedLiterals frontmatter.

## Security & Compliance

Allowlist entries are public planning metadata.

## Testing Strategy

Golden fixture for exact-token allowlist.

## Rollout Plan

Ship with PRD 361.

## Decision Log

- Allowlisted TODO as the product brand name, not unfinished authoring work.

## Open Questions

(none)
