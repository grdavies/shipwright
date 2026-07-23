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

0. **Authoring-guard preflight (PRD 032 R5/R6/R7/R8/R14)** — before the first substantive mutation on a planning unit, run `python3 scripts/authoring-guard.py preflight --path <unit-artifact> --command sw-amend`; on a genuinely in-flight unit, pass `--handoff <reason>` instead of mutating (R6). `/sw-amend` is permitted only when the unit consumer status is `planned` or `in-progress`; on `complete` units the guard **refuses in-place amend** and returns a **route** to fork a new `extends:`/`supersedes:` unit or append a gap (exit `21`, `outcome: route`).
1. **Pre-work search (mandatory)** — before the first substantive mutation, run `memory-preflight` **pre-work
   search** per `skills/memory/SKILL.md` **Pre-work search (mandatory)** (scoped to the parent PRD/decision
   domain and amendment paths; classes `rule`, `decision`, `learning`, `code-context`, `design` via
   `providers/<memory.provider>.md` — no direct provider call). Surface hits and reconcile applicable
   rules/contradicting decisions — especially against the frozen parent — before drafting.
2. Read frozen parent; extract highest R-ID or D-ID and existing amendments.
3. Assign next amendment number `A<k>` in the parent's amendment directory.
4. Draft delta-only body with IDs continuing parent namespace (R-IDs for PRDs, D-IDs for decisions).
5. Optional frontmatter directives:
   - `supersedes: [R<n>|D<n>, ...]` — inline replacement (PRD) or record-level drop (decision).
   - `retracts: [R<n>|D<n>, ...]` — parent requirement dropped (record rationale in body).
   - `replacement: <path>` — **decision record-level supersede only**: forward pointer to frozen
     replacement record (target must have `frozen: true`; blocks at author time if missing or unfrozen).
6. Run `/sw-doc-review` — floor per doc type (PRD amendment: coherence + scope-guardian; decision amendment:
   raised floor per `skills/doc-review/SKILL.md`).
7. Freeze amendment via `/sw-freeze`.
8. **File-store only:** update `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` amendment links. Under
   issue-store (below), INDEX rows are issue-derived — never hand-edit living projections in the code repo.
9. On decision record-level supersede: `python3 scripts/sw_bootstrap.py reconcile-status.py -- append-superseded --path <parent-record> --replacement <replacement-record>`.

## Issue-store mode (PRD 061 R23)

When `planning.store.backend` is `issue-store` (effective):

1. **PRD amendments** — persist via the planning store facade only; do not author tracked bodies under
   `docs/prds/<n>-<slug>/amendments/` in the code repo when `storeLocation.mode` is `separate-project`:
   ```bash
   python3 scripts/planning_store.py put \
     --unit-id <parent-prd-unit>-amend-A<k>-<short> \
     --body-path docs/prds/<n>-<slug>/amendments/A<k>-<short>.md \
     --content @amendment-draft.md
   ```
   Carry `amends:` / `sw:amends:` edges on the parent issue via store-native label projection (same as PRD
   `depends` edges).
2. **Freeze** — `python3 scripts/planning_store.py freeze --unit-id <amendment-unit> --body-path <virtual-path>`.
3. **Decision amendments** remain **file-native** (D8) — `docs/decisions/.../amendments/` in the code repo;
   only PRD amendments are store-only under issue-store.
4. **Doctor** — `python3 scripts/planning_store.py doctor` fails closed on dirty banned-path writes if a local
   amendment body appears under `separate-project`.

**Communication intensity:** lite

**Model tier:** deep — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-amend`.

## Guardrails

- Parent file is never written.
- **Complete-unit refusal (R7/R8):** do not amend units with consumer status `complete`; follow the routed `extends:`/`supersedes:` unit or gap from the preflight `route` payload.
- **Allowed amend statuses (R7):** `planned`, `in-progress` only.
- Undeclared contradiction with parent → failure mode; declared supersede/retract → sanctioned.
- Record-level decision supersede does **not** inline replacement content — pointer only (KTD3).
- Forward-pointer target must be `frozen: true`.

## Exemplar

`docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.amendments/A1-fail-closed-enforcement-point.md`
