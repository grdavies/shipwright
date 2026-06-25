---
description: Create a sibling amendment for a frozen PRD with continued R-IDs and supersede/retract directives. Does not edit the parent file.
alwaysApply: false
---

# `/sw-amend`

Post-freeze correction path. Parent stays byte-stable.

## Scope

- Input: frozen parent PRD or decision record path + delta description.
- Output:
  - PRD: `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md`
  - Decision: `docs/decisions/<n>-<slug>.amendments/A<k>-<short>.md` (sibling layout)
- Does **not** modify the parent file.

## Procedure

1. Read frozen parent; extract highest R-ID or D-ID and existing amendments.
2. Assign next amendment number `A<k>` in the parent's amendment directory.
3. Draft delta-only body with IDs continuing parent namespace (R-IDs for PRDs, D-IDs for decisions).
4. Optional frontmatter directives:
   - `supersedes: [R<n>|D<n>, ...]` — inline replacement (PRD) or record-level drop (decision).
   - `retracts: [R<n>|D<n>, ...]` — parent requirement dropped (record rationale in body).
   - `replacement: <path>` — **decision record-level supersede only**: forward pointer to frozen
     replacement record (target must have `frozen: true`; blocks at author time if missing or unfrozen).
5. Run `/sw-doc-review` — floor per doc type (PRD amendment: coherence + scope-guardian; decision amendment:
   raised floor per `skills/doc-review/SKILL.md`).
6. Freeze amendment via `/sw-freeze`.
7. Update `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` amendment links.
8. On decision record-level supersede: append superseded parent path to `docs/decisions/SUPERSEDED.log`.

**Communication intensity:** lite

**Model tier:** deep — resolve via `bash scripts/resolve-model-tier.sh --command sw-amend`.

## Guardrails

- Parent file is never written.
- Undeclared contradiction with parent → failure mode; declared supersede/retract → sanctioned.
- Record-level decision supersede does **not** inline replacement content — pointer only (KTD3).
- Forward-pointer target must be `frozen: true`.

## Exemplar

`docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.amendments/A1-fail-closed-enforcement-point.md`
