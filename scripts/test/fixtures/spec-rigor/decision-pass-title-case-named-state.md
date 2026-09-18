---
frozen: false
---
# Decision — Title-case named state

## Context

Consumer specs copy Title-case lifecycle labels that collide with placeholder tokens.

## Decision

- **D1** Title-case named state Todo passes the ambiguity matcher with no reviewedLiterals entry

## Rationale

Requiring every consumer PRD to list E04 states would leak Shipwright mechanism into foreign specs.

## Alternatives

- Require reviewedLiterals for every Title-case collision (rejected).

## Consequences

- Unresolved all-caps and punctuation wraps remain fail-closed.
