---
date: 2026-06-22
topic: frozen-specs-living-status
frozen: true
frozen_at: 2026-06-23
---
# Frozen specs, living status

## Context

Engineering handoff needs immutable reviewed specs while progress tracking must stay mutable without mutating frozen artifacts.

## Decision

- **D1** Brainstorms, PRDs, task lists, and decision records freeze at handoff and are never edited afterward
- **D2** Living layers (`prds/INDEX.md`, `decisions/INDEX.md`, `COMPLETION-LOG.md`) track progress and are never frozen
- **D3** Gap backlog is append-only committed state, not frozen, not git-derived

## Rationale

Separates reviewed deliverables from operational status. INDEX reconciliation can derive from git without touching frozen parents.

## Alternatives

- Mutable PRDs with version tags — rejected (weakens review gate)
- Git-only status with no INDEX — rejected (poor handoff visibility)

## Consequences

`/pf-freeze` stamps parents; `/pf-tasks` and implementation update living indexes only.
