---
brainstorm: docs/brainstorms/2026-06-27-doc-format-parser-robustness-requirements.md
date: 2026-06-27
topic: doc-format-parser-robustness
absorbs: [GAP-045]
frozen: true
frozen_at: 2026-06-27
---
# PRD 029 — Doc-format parser robustness and parser unification

## Overview

The doc-authoring chain generates markdown from prose skill instructions (`skills/prd`, `skills/tasks`,
`skills/spec-rigor`) but validates it with regex-strict gates that each accept a different canonical shape.
As a result, freeze, union, and traceability pass for some models and fail for others on semantically
identical content, and the parsers disagree with one another: `spec-union.sh` accepts three R/D-ID forms,
`spec-rigor-check.sh` accepts only one, `traceability-check.sh` requires single-ID cells, and
`wave_deliver.py` requires a single phase-heading and exact-table shape. There is no machine-readable
template the model fills, and no pre-freeze structural normalizer — `spec-rigor` is explicitly "no auto-fix"
(it rejects, never canonicalizes). Separately, `parse_frontmatter_list` reads `supersedes`/`retracts` only as
inline lists, so a YAML block list is silently dropped, corrupting the spec union with no error.

This PRD makes doc-format parsing deterministic across models by introducing a single shared doc-format
tokenizer that defines the canonical grammar once, is consumed by all four parsers in `--check` mode, and is
exposed as a structural normalizer in `--write` mode — so gates and normalizer cannot diverge. It adds
machine-readable slot-filling templates for the authoring commands, fixes the directive-list silent-drop with
fail-closed parsing, resolves the Decision-Log D-ID dodge structurally, and proves both behavior and
backward compatibility with a fixture and golden-corpus suite. It absorbs GAP-045.

## Goals

- Make the four doc-format parsers agree token-for-token by sourcing one shared tokenizer, so a doc that
  passes any structural gate passes all of them.
- Catch non-canonical or ambiguous structure before freeze with precise, line-anchored errors, and offer a
  deterministic structural normalizer that never touches content.
- Make authoring commands emit a canonical machine-readable skeleton so models fill structure rather than
  reverse-engineer it.
- Eliminate silent directive loss (`supersedes`/`retracts`/`absorbs`) and the Decision-Log D-ID dodge.

## Non-Goals

- Semantic/content validation of requirements — the existing gates retain their content rules; this PRD
  unifies only structural shape and token grammar.
- The GAP-BACKLOG status lifecycle (GAP-043/044/046, PRD 028) — consumed/cross-linked, not re-implemented;
  the `absorbs:` directive parsing here is shared with that effort's linkage.
- The in-flight authoring guard (GAP-038) — separate PRD.
- Any change to the human merge gate or to frozen-artifact immutability.

## Requirements

- **R1** A single shared doc-format tokenizer library defines the canonical grammar for R/D-ID bullets,
  section headings, traceability cells, phase headings, and frontmatter directive lists, and is the sole
  source of accepted forms across the doc toolchain.
- **R2** `spec-union.sh`, `spec-rigor-check.sh`, `traceability-check.sh`, and `wave_deliver.py` parse these
  tokens exclusively via the shared tokenizer; none retains an independent regex for them, so they cannot
  disagree on what is a valid R-ID, D-ID, section heading, traceability cell, or phase heading.
- **R3** The tokenizer's `--check` mode fails closed with precise, line-anchored, actionable diagnostics
  (file:line, expected canonical form, found form) for every non-canonical or ambiguous token; no token is
  silently ignored or dropped.
- **R4** The tokenizer's `--write` mode canonicalizes structural shape only — R/D-ID bullets to `- **R12**`,
  section headings to `## Name`, traceability cells to one `R\d+` per cell/row (expanding comma lists and
  `R1–R3` ranges), and phase headings to `### N. Title` — and never alters prose or content. `--write` is
  idempotent: after `--write`, `--check` passes, and a second `--write` is a no-op.
- **R5** The tokenizer canonicalizes or precisely rejects every verified divergence class: (1) R/D-ID bullet
  variants (`- **R12.**`, `- **R12:**`, `* **R12**`, indented, numbered, `R-12`, code-span); (2) the
  three-form vs one-form parser disagreement; (3) section-heading parentheticals/numbering/extra words;
  (4) traceability list and range cells; (5) phase-heading and `## Phase Dependencies` table-shape variants.
- **R6** Frontmatter directive lists (`supersedes`, `retracts`, `absorbs`) parse both inline (`[a, b]`) and
  YAML block-list forms through the shared tokenizer; a non-empty directive key that yields zero parsed IDs
  fails closed rather than being silently dropped.
- **R7** `/sw-prd`, `/sw-tasks`, and `/sw-amend` emit machine-readable slot-filling templates whose structure
  is exactly the tokenizer's canonical shape, so generated artifacts are canonical by construction.
- **R8** A pre-freeze structural check runs the tokenizer in `--check` mode (offering `--write`) in the freeze
  path and in `/sw-doc-review`, so non-canonical structure is caught before union/traceability evaluation
  rather than surfacing as a late false-negative.
- **R9** Decision Log entries are parsed as decisions by structural position under the `## Decision Log`
  section rather than by a dodged bullet shape, eliminating the deliberate `- **D1.**` workaround and the
  collision between the real-D-ID and "do-not-extract" forms.
- **R10** Backward compatibility is enforced by a golden-corpus regression test asserting that every
  currently-passing frozen PRD, amendment, and task list still passes `--check`, and that the four consumers
  agree token-for-token, before and after the tokenizer swap.
- **R11** A format-lint fixture set proves each divergence class (1)–(6) is either normalized by `--write` or
  rejected by `--check` with an actionable message, including the supersedes/retracts block-list parse and
  fail-closed-on-empty cases; wired into `verify.test` and `/sw-doc-review`.
- **R12** No consumer regresses: `spec-union` requirement/traceability extraction, `spec-rigor` gating, and
  `wave_deliver` phase detection produce identical results on the existing frozen corpus after adoption.

## Technical Requirements

- **TR1** (R1, R2) Implement the tokenizer as `scripts/doc_format.py` exposing pure functions
  (`parse_requirement_id`, `parse_section_heading`, `parse_traceability_cell`, `parse_phase_heading`,
  `parse_directive_list`) plus a `scripts/doc-format-normalize.sh` CLI wrapper (`--check` / `--write`).
  `spec-union.sh`, `spec-rigor-check.sh`, and `traceability-check.sh` import the Python functions in their
  embedded `python3 - <<PY` blocks; `wave_deliver.py` imports the module directly.
- **TR2** (R3) Diagnostics are structured (JSON `findings` with `file`, `line`, `expected`, `found`, `class`)
  and also rendered human-readably; exit codes follow the established `0 pass / 10 warn / 20 fail` convention.
- **TR3** (R4) `--write` operates on a parsed token stream and rewrites only the matched spans, preserving
  surrounding prose, whitespace policy, and trailing content; range expansion (`R1–R3` → `R1, R2, R3` cells)
  is deterministic and order-preserving.
- **TR4** (R5) Encode each divergence class as a tokenizer rule with an explicit canonical target and an
  ambiguity policy (canonicalize vs reject); ambiguous forms that cannot be safely rewritten reject under
  `--check` with the class identifier.
- **TR5** (R6) Replace the inline-only `parse_frontmatter_list` in `spec-union.sh` (and any duplicate in
  `doc_link.py`) with the shared `parse_directive_list`, which accepts inline and block-list YAML and raises a
  fail-closed error when a present key yields zero IDs.
- **TR6** (R7) Add template emission to the `prd` / `tasks` / `amend` skills (and any scaffolding script) as a
  canonical skeleton; document the slot contract in the skills. Regenerate `dist/` via the emitter.
- **TR7** (R8) Wire `doc-format-normalize.sh --check` into the freeze path and the `/sw-doc-review`
  pre-checks, before `spec-union` / `traceability-check`, with a `--write` remediation hint in the failure
  output.
- **TR8** (R9) `spec-union` D-ID extraction keys on the `## Decision Log` section boundary (decisions) vs the
  `## Requirements` section (requirements) rather than on bullet punctuation, via the shared
  section-heading tokenizer.
- **TR9** (R10, R12) Add a golden-corpus test that runs all four parsers over the frozen `docs/prds/**`
  corpus and asserts identical pre/post token sets and gate verdicts; fail the suite on any drift.
- **TR10** (R11) Add fixtures under the doc-format fixture harness (new `scripts/test/run-doc-format-fixtures.sh`
  or extend an existing harness); wire into `verify.test`; regenerate `dist/` and the golden parity manifest
  after any `core/` change.

## Security & Compliance

- No new external surface, host verb, or network call; the tokenizer operates only on local markdown.
- `--write` never alters prose/content, only structural token shape, so it cannot exfiltrate or inject
  content; redaction and secret-scan chokepoints are unaffected.
- Frozen-artifact immutability is preserved: the pre-freeze check runs before stamping; `--write` is offered
  only on not-yet-frozen artifacts and is opt-in.
- The push and merge chokepoints and the `main` human gate are unchanged.

## Testing Strategy

Fixtures (failing-before / passing-after), wired into the doc-format suite and `verify.test`:

| Fixture | Asserts | R-IDs |
| --- | --- | --- |
| `rid-bullet-variants-normalized` | `- **R12.**` / `- **R12:**` / `* **R12**` / indented / `R-12` / code-span normalize to `- **R12**` or reject with class id | R4, R5 |
| `parser-agreement-rid` | union, spec-rigor, and traceability accept exactly the same R/D-ID token set | R2, R5 |
| `section-heading-variants` | `## Requirements (Functional)` / `## Non Goals` / `## 4. Requirements` canonicalize or reject precisely | R4, R5 |
| `traceability-list-range-expanded` | `R1, R2` and `R1–R3` expand to discrete `R\d+` cells; coverage no longer silently drops | R4, R5 |
| `phase-heading-variants` | `### Phase 1:` / `### 1 —` / wrong-level normalize to `### N. Title`; `## Phase Dependencies` shape variants handled | R4, R5 |
| `directive-block-list-parsed` | `supersedes:`/`retracts:`/`absorbs:` block lists parse; a non-empty key with zero IDs fails closed | R6 |
| `decision-log-did-structural` | Decision Log `- **D1.**` is parsed as a decision by section position; no extraction collision | R9 |
| `check-fails-closed-actionable` | `--check` emits file:line + expected/found for each non-canonical token | R3 |
| `write-idempotent` | `--write` then `--check` passes; second `--write` is a no-op | R4 |
| `golden-corpus-no-regression` | all four parsers produce identical verdicts/token sets on the frozen corpus pre/post adoption | R10, R12 |

Regression guard: the existing spec-union, spec-rigor, traceability, and deliver phase-detection fixtures
must remain green.

## Rollout Plan

- **Phase 1 — Tokenizer library + CLI (R1, R3, R4).** Build `doc_format.py` + `doc-format-normalize.sh` with
  `--check`/`--write` and full divergence-class rules; pure functions with unit fixtures. No consumer changes
  yet — lowest risk.
- **Phase 2 — Consumer adoption (R2, R5, R6, R9).** Swap `spec-union`, `spec-rigor`, `traceability-check`, and
  `wave_deliver` onto the shared tokenizer; replace `parse_frontmatter_list`; key D-ID extraction on section
  position. Guarded by the golden-corpus test.
- **Phase 3 — Templates + pre-freeze wiring (R7, R8).** Slot-filling templates in `prd`/`tasks`/`amend`;
  `--check` in the freeze path and `/sw-doc-review`.
- **Phase 4 — Fixtures + backward-compat proof (R10, R11, R12).** Full format-lint fixtures, golden-corpus
  regression test, `verify.test` wiring, and `dist/` + golden-manifest regeneration.

Backward compatible: canonical forms already used by the frozen corpus are accepted unchanged; `--write` is
opt-in and never required for conforming docs.

## Decision Log

- **D1** One shared tokenizer exposed as both `--check` (all four gates) and `--write` (normalizer) — chosen
  over a tolerant-tokenizer-only or normalizer-only approach because a single library makes the gates and the
  normalizer incapable of disagreeing by construction.
- **D2** `--check` fails closed with line-anchored diagnostics by default; `--write` canonicalizes structural
  shape only and never content — relaxing "no auto-fix" for shape alone preserves the strict content posture.
- **D3** Include machine-readable slot-filling templates so authoring commands produce canonical structure by
  construction, rather than relying solely on post-hoc normalization.
- **D4** Fix `supersedes`/`retracts`/`absorbs` parsing to accept block lists and fail closed on a non-empty
  key with zero IDs — chosen over silent inline-only parsing, which corrupts the spec union without error.
- **D5** Resolve the Decision-Log D-ID dodge structurally (extract by `## Decision Log` section position) —
  chosen over keeping the collision-prone `- **D1.**` workaround.
- **D6** Enforce backward compatibility with a golden-corpus regression test rather than trusting manual
  review, because the corpus is the contract the tokenizer must not break.
- **D7** Standalone PRD 029, distinct from the living-status lifecycle (PRD 028) and the in-flight authoring
  guard (GAP-038), but sharing the `absorbs:`-directive parsing with PRD 028's linkage.

## Open Questions

None — strategy (D1), auto-fix posture (D2), template inclusion (D3), and the directive-parsing fix (D4) were
all resolved with the operator before drafting.
