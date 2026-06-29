---
date: 2026-06-29
topic: doc-review-persona-selection-accuracy
absorbs: [GAP-047]
depends: [021]
frozen: true
frozen_at: 2026-06-29
---

# PRD 037 — Doc-review persona selection accuracy (heading matcher)

## Overview

PRD 021 shipped the capability manifest and deterministic selector (`scripts/capability_select.py`,
`scripts/doc-review-select.sh`, `core/sw-reference/capability-index.json`). The `text_token` trigger path
already uses whole-token matching (`\bUI\b`), but **`match_heading()` still uses substring containment**
(`needle in compare`), so every PRD whose body includes `## Requirements` falsely activates
`sw-design-reviewer` because `"ui"` is a substring of `"requirements"`.

**Impact:** signal-driven doc review spuriously dispatches (or proposes) the design persona on nearly every
PRD, wasting panel slots and model budget and diluting review signal. PRD 031 planning-feedback-lifecycle
reviews manually suppressed the persona; the defect is mechanical, not contextual.

This PRD closes **GAP-047**. PRD 021 is **complete** — this is a successor PRD, not an amendment. Scope is
limited to heading-trigger semantics, fixture coverage, and doc contract alignment; it does not reopen the
021 migration or change orchestration policy.

## Goals

- Eliminate the `## Requirements` → design false-positive class without regressing legitimate design triggers.
- Unify heading-trigger semantics with the existing `text_token` whole-token contract.
- Prove the fix with negative and positive persona-selection fixtures wired into `verify.test`.
- Update operator-facing doc-review selection prose where the heading contract is described.

## Non-Goals

- Amending or reopening PRD 021 (complete).
- Changing the always-on doc-review core panel (coherence, feasibility, scope-guardian, product,
  adversarial, docs-currency).
- Broadening or narrowing which `text_token` or `link_pattern` triggers fire — heading matcher only unless
  audit discovers the same substring class elsewhere.
- Code-review specialist selection (`code-review` family) — out of scope unless audit finds identical bug
  (separate follow-up).
- Parallel dispatch-preflight or model-tier binding (PRD 024 A2 territory).

## Requirements

- **R1** `match_heading()` MUST NOT use raw substring containment (`needle in compare`) for trigger
  headings. Heading triggers MUST match using the same whole-token semantics as `text_token` with
  `match: whole_token` — i.e. `\b<token>\b` boundaries on the heading text after stripping markdown `#`
  prefixes — OR require exact equality between the normalized heading text and the trigger token (configurable
  per trigger; default whole-token for short tokens like `UI`/`UX`).
- **R2** A PRD whose **only** design-adjacent signal is the standard `## Requirements` section MUST NOT
  select `sw-design-reviewer`. Verified by a negative persona-selection fixture.
- **R3** Legitimate design triggers MUST continue to fire: unambiguous `text_token` terms, structural headings
  (`## UI`, `## UX`, `## Screens`, `## Mockups`), and design-tool `link_pattern` entries per the manifest.
  Existing positive fixtures (`design-unambiguous`, `design-structural`, `design-polysemous-only`) MUST remain
  green.
- **R4** Audit every `heading`-type trigger in `core/sw-reference/capability-index.json` (doc-review and
  code-review families) for the substring-containment false-positive class; fix or document any additional
  hits in the PRD Decision Log.
- **R5** No regression to PRD 021 selector parity: `run-migration-parity-fixtures.sh` /
  `migration-parity-doc-review` corpus stays byte-identical except for the intentional
  Requirements-false-positive correction.
- **R6** Operator docs (`core/skills/doc-review/SKILL.md`, `core/sw-reference/capability-manifest.md` if
  heading contract is stated) MUST describe heading matching as whole-token or exact, not substring.
- **R7** On ship, GAP-047 status flips to `resolved` via the living-status / gap-resolve path (or manual
  reconcile until PRD 033 cutover).

## Technical Requirements

- **R8** Implement the heading matcher fix in `scripts/capability_select.py` (`match_heading`); propagate
  via `copy-to-core` + emitter to `core/scripts/` and both `dist/` trees.
- **R9** Add fixture `scripts/test/fixtures/persona-selection/design-requirements-false-positive.md` with
  `<!-- expected-personas: core-only (Requirements heading must not fire design) -->` and wire it through
  `scripts/test/run-persona-selection-fixtures.sh`.
- **R10** If whole-token heading match requires manifest schema extension (e.g. `match: whole_token` on
  `heading` triggers), extend `core/sw-reference/capability-manifest.schema.json` + validators
  (`capability_manifest_validate.py`, `capability_manifest_lint.py`) and document in the manifest contract.
- **R11** Optional shared helper: factor `heading_has_token()` alongside `text_has_token()` /
  `whole_token_pattern()` so `text_token` and `heading` triggers cannot drift again.

## Security & Compliance

- **R12** Selection changes are deterministic and offline — no new network surface, credentials, or private
  body handling. Redaction and visibility contracts (PRD 034) are unchanged.

## Testing Strategy

- Negative fixture (R2): `design-requirements-false-positive.md` → core-only panel.
- Positive regression (R3): existing `design-unambiguous`, `design-structural`, `design-polysemous-only`
  fixtures remain green.
- Parity (R5): `run-migration-parity-fixtures.sh` doc-review family passes with documented delta for the
  Requirements false-positive case only.
- CI: `run-persona-selection-fixtures.sh` registered in `verify.test` (already present — extend corpus).
- Manual smoke: run `doc-review-select.sh` against a minimal PRD body snapshot containing only
  `## Requirements` → `design` absent from activation record.

## Rollout Plan

1. **Matcher fix** — implement `match_heading` whole-token semantics + unit-level tests if needed.
2. **Fixtures** — add negative fixture; confirm positive corpus green.
3. **Audit** — scan capability-index heading triggers (R4); log findings in Decision Log.
4. **Docs + propagate** — update doc-review SKILL / manifest prose; `copy-to-core` + `sw generate --all`.
5. **Gap close** — flip GAP-047 on ship.

## Decision Log

- **D1** Successor PRD rather than PRD 021 amendment — parent is `complete`; GAP-047 is post-ship defect
  repair with a narrow blast radius.
- **D2** Fix the matcher implementation, not the manifest alone — removing `UI`/`UX` from heading triggers
  would drop legitimate `## UI` section matches; whole-token heading match preserves both correctness and
  manifest expressiveness.
- **D3** Default heading match mode is `whole_token` (aligned with `text_token`); exact equality remains
  available for multi-word heading targets if added later.

## Open Questions

- None — GAP-047 investigation confirmed root cause (`needle in compare` on heading text). Proceed to
  implementation.
