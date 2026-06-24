---
date: 2026-06-22
topic: amendments-sibling-frozen-delta
frozen: true
frozen_at: 2026-06-23
---
# Amendments as sibling frozen files (R12)

## Context

Frozen PRDs and decision records must not be edited in place after handoff. Corrections and extensions need a reviewed, immutable path that implementation can consume as a precedence-aware union.

## Decision

- **D1** Frozen parents are never mutated — changes flow through sibling amendment files reviewed and frozen separately
- **D2** Amendments carry `supersedes` / `retracts` directives; implementation reads the spec union, not the bare parent
- **D3** Freeze is enforced by flag, agent guardrail, pre-commit hook, and CI — no unfreeze path

## Rationale

Preserves review audit trail while allowing correction. Union resolver (`scripts/spec-union.sh`) is the single read-time view.

## Alternatives

- Edit frozen parents with audit log — rejected (breaks immutability contract)
- Parallel decision-specific resolver — rejected (rots; generalize one resolver)

## Consequences

`/pf-amend` + `spec-union.sh` are shared across PRDs and decision records. Implementation workstream consumes union output (plan 003).
