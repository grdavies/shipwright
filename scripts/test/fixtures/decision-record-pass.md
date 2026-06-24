---
date: 2026-06-23
topic: example-decision
frozen: false
---
# Example decision record

## Context

Cross-cutting workflow decisions need an addressable frozen deliverable.

## Decision

- **D1** Decision records live under `decisions/<n>-<slug>.md` with a distinct D-ID namespace
- **D2** Authoring reuses `/pf-prd --type decision` rather than a dedicated command

## Rationale

Reuses freeze/review/amend machinery without duplicating authoring surfaces.

## Alternatives

- Dedicated `/pf-decision` command — rejected as tooling duplication
- Memory-native storage — rejected (no CI freeze)

## Consequences

- Plans and memory link to frozen files via `relatedFiles`
- Spec-rigor gate gains an `--artifact decision` branch
