---
date: 2026-06-22
topic: fresh-prefixed-vendored-plugin
frozen: true
frozen_at: 2026-06-23
---
# Fresh, self-contained, prefixed plugin

## Context

phase-flow v2 merges strengths of v1 and compound-engineering without runtime dependency on either. Command collisions and structural lifecycle gaps block incremental extension of v1.

## Decision

- **D1** Build fresh in `currsor-phase-flow-2` with everything vendored in-tree — no sibling plugin required at runtime
- **D2** All commands use the `pf-` namespace prefix to avoid collisions with v1 and `ce-`
- **D3** Provenance manifest + `/pf-upstream` track borrowed patterns; prefer pattern-borrowing over code copy where re-derivation is cheap

## Rationale

Clean four-workstream architecture, vendored persona/doc pipeline, and uniform `pf-` surface designed from the start. Cost is provenance maintenance and re-porting proven gate/memory/stabilize code.

## Alternatives

- Prefix-and-extend v1 — rejected (structural gaps, not just collisions)
- Runtime dependency on CE — rejected (coupling, load failures)

## Consequences

`PROVENANCE.md` + `/pf-upstream` are first-class. Documentation workstream pattern-borrows CE doc panel without copying full agent set (plan 002).
