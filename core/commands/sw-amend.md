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
8. Update `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` amendment links.
9. On decision record-level supersede: `python3 scripts/reconcile-status.py append-superseded --path <parent-record> --replacement <replacement-record>`.

**Communication intensity:** lite

**Model tier:** deep — resolve via `python3 scripts/resolve-model-tier.py --command sw-amend`.

## Guardrails

- Parent file is never written.
- **Complete-unit refusal (R7/R8):** do not amend units with consumer status `complete`; follow the routed `extends:`/`supersedes:` unit or gap from the preflight `route` payload.
- **Allowed amend statuses (R7):** `planned`, `in-progress` only.
- Undeclared contradiction with parent → failure mode; declared supersede/retract → sanctioned.
- Record-level decision supersede does **not** inline replacement content — pointer only (KTD3).
- Forward-pointer target must be `frozen: true`.

## Exemplar

`docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.amendments/A1-fail-closed-enforcement-point.md`
