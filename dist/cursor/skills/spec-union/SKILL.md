---
name: sw-spec-union
description: Resolve a frozen PRD or decision record plus amendments into one effective spec — adds, supersedes, retracts in amendment order. Read-only on parent.
---

# Spec union resolver

Single read-time view of frozen doc + amendments (R12). Parent is never mutated.


**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.sh --skill spec-union`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).


## Structural tokenizer (PRD 031)

`scripts/spec-union.sh` parses exclusively through `scripts/doc_format.py` (shared tokenizer). No
independent structural regex is retained. Pre-freeze docs pass through
`python3 scripts/doc-format-normalize.sh --check|--write` before persisting.

Post-cutover paths live under `planningDir` (default `docs/planning`); pre-cutover repos use legacy
`prdsDir`/`decisionsDir` until migration `--verify` passes. See `core/sw-reference/layout.md`.

## Supported doc types

| Type | Path | ID grammar | Amendment dir |
|------|------|------------|---------------|
| PRD | `<planningDir>/prd/<id>-<slug>/<id>-prd-<slug>.md` (legacy: `prdsDir/<n>-<slug>/...`) | `R\d+` | `parent/amendments/` |
| Decision | `<planningDir>/decision/<id>-<slug>.md` (legacy: `decisionsDir/<n>-<slug>.md`) | `D\d+` | sibling `<stem>.amendments/` |

## Resolution rules

Apply amendments in filename sort order (`A1`, `A2`, …):

1. **Add** — new R-IDs / D-IDs from amendment body enter the effective spec.
2. **Supersede (PRD / inline)** — `supersedes: [R<n>]` removes parent R<n>; replacement is the new continued
   R-ID in the amendment body (positional pairing).
3. **Supersede (decision / record-level)** — `supersedes: [D<n>]` with `replacement: <path>` drops D<n> from
   the effective set and emits a forward pointer — **never inlines** the replacement record's content.
   Handled outside the positional replacement loop.
4. **Retract** — `retracts: [R<n>|D<n>]` drops the ID from effective spec (rationale in amendment body).

Later amendments can supersede earlier amendment requirements.

### Record-level supersede output

```json
"superseded": { "D5": { "replacement": "docs/decisions/009-foo.md" } }
```

PRD inline supersede keeps the `old → new_id` string map. Record-level object values appear only for
decision record-level supersedes — PRD-path output stays byte-identical.

### Transitive chain + cycle guard

Forward pointers are followed to the terminal non-superseded record (D5→D9→D12 ⇒ D12 path). Max depth cap
with hard error on cycles (D5↔D9).

### Empty-union guard

D-ID extraction failure or empty effective union on a non-empty decision doc (without full retract/supersede
coverage) is a hard error.

## Consumers

- **Agent:** load this skill when reading spec for `/sw-execute` or gap-check.
- **Deterministic:** `scripts/spec-union.sh <doc-path>` → JSON effective requirements.

## Interface stability

Published contract for implementation workstream (`003`). PRD-path output must stay byte-identical; decision
path is additive.

## Examples

```bash
python3 scripts/spec-union.sh docs/planning/prd/prd-001-feature/prd-001-feature-prd-feature.md
python3 scripts/spec-union.sh docs/planning/decision/decision-001-my-decision/decision-001-my-decision.md
```
