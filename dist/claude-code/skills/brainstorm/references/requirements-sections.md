# Requirements document sections

Output shape for `/sw-brainstorm`. Full fidelity authoring (R30/R31) — no terse compression.

## Frontmatter

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>
---
```

Add `frozen: true` and `frozen_at: YYYY-MM-DD` only via `/sw-freeze` — not during brainstorm.

## Required sections

1. **Summary** — what we're building and why (2–4 sentences).
2. **Problem Frame** — context, pain, constraints.
3. **Key Decisions** — decisions with rationale (bullets with sub-bullets for alternatives considered).
4. **Requirements** — stable R-IDs (`R1`, `R2`, …); each requirement is one testable statement.
5. **Success Criteria** — how we know it worked.
6. **Scope Boundaries** — explicit non-goals and deferred items.
7. **Open Questions** — unresolved items for planning (if any).

## R-ID rules

- Monotonic `R<n>` across the document.
- Never reuse or renumber after draft.
- Amendments continue the namespace (`R11+` if parent ends at `R10`).

## Path

`docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md` per `.sw/layout.md`.

## Exemplar

`docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md`
