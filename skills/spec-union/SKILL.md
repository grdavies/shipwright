---
name: pf-spec-union
description: Resolve a frozen PRD plus amendments into one effective spec — adds, supersedes, retracts in amendment order. Read-only on parent.
---

# Spec union resolver

Single read-time view of PRD + amendments (R12). Parent is never mutated.

## Resolution rules

Apply amendments in filename sort order (`A1`, `A2`, …):

1. **Add** — new R-IDs from amendment body enter the effective spec.
2. **Supersede** — `supersedes: [R<n>]` removes parent R<n>; replacement is the new continued R-ID in the amendment body.
3. **Retract** — `retracts: [R<n>]` drops R<n> from effective spec (rationale in amendment body).

Later amendments can supersede earlier amendment requirements.

## Consumers

- **Agent:** load this skill when reading spec for `/pf-execute` or gap-check.
- **Deterministic:** `scripts/spec-union.sh <prd-path>` → JSON effective requirements.

## Interface stability

This resolver is a published contract for implementation workstream (`003`). Do not change output shape without coordinating.

## Example

```bash
bash scripts/spec-union.sh prds/001-feature/001-prd-feature.md
```
