---
date: 2026-06-26
topic: capability-manifest-and-selector
prd: docs/prds/021-capability-manifest-and-selector/021-prd-capability-manifest-and-selector.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 021 Capability manifest and selector

Generated from the frozen PRD spec union (R9–R14, R21, R24, R25, R27 — no amendments). Phases are
dependency-ordered per the Rollout Plan: schema → generated index + freshness → precedence/lint → selector +
`signal_context` → trust boundary → per-family parity migration (shadow cutover) → run-log surfacing →
docs/dist. The migration phase (6) is parity-gated per family and is the dominant surface (broadened signal
contract per the Decision Log).

## Tasks

### 1. Manifest frontmatter schema + contract — M

- [x] 1.1 Define the capability-manifest frontmatter schema (anti-spoof, path-derived kind) (R9, R27)
  - **File:** `core/sw-reference/capability-manifest.schema.json`
  - **Expected:** versioned frontmatter block declaring `triggers` (triage tags, text-token predicates over the body snapshot, file/path globs, change-digest predicates, config-flag predicates), `precedence`, an explicit `always_on`/`phase_default` trigger, and selection `metadata`; **executable `kind` derived from the canonical source path prefix** (`providers/**`, `hooks/**`), not author-declared; absence of the block ⇒ "not signal-selected" (back-compat). JSON schema validates; `kind`/path mismatch and phantom-artifact entries are rejectable.
  - **R-IDs:** R9, R27
- [x] 1.2 Author the manifest contract doc (drop-in + trust boundary) (R9, R12, R27)
  - **File:** `core/sw-reference/capability-manifest.md`
  - **Expected:** documents frontmatter fields, applicable source kinds, absence-default, the precedence/conflict policy (R11), and the executable-vs-non-executable trust boundary (R27); states that declaring a non-executable capability is drop-in (R12) while executables still require the existing trust/config gate.
  - **R-IDs:** R9, R12, R27
- [x] 1.3 Add per-capability manifest frontmatter to the migrated source families (R9, R12)
  - **File:** `core/skills/**`, `core/agents/sw-*-reviewer.md`, `core/providers/**`, `core/rules/**`, `core/hooks/**`
  - **Expected:** trigger frontmatter added to the families migrated in Phase 6 (no behavior change until the index + selector are authoritative); the six always-on doc-review personas carry an explicit `always_on` trigger (lint-visible, no silent default).
  - **R-IDs:** R9, R12

### 2. Generated capability index + freshness gates — M

- [x] 2.1 Emitter aggregation into `capability-index.json` (structured YAML) (R9, R24)
  - **File:** sw emitter (`python3 -m sw generate`) module + `core/sw-reference/capability-index.json`
  - **Expected:** aggregates per-capability frontmatter into the committed index using a **structured YAML parser** (nested `triggers` round-trip), emitted to `dist/cursor` and `dist/claude-code`; no hand-maintained registry.
  - **R-IDs:** R9, R24
- [x] 2.2 Test-gate index freshness fixture (R24)
  - **File:** `scripts/test/run-emitter-fixtures.sh`
  - **Expected:** a stale/hand-edited index fails the freshness fixture (failing-before / passing-after).
  - **R-IDs:** R24
- [x] 2.3 Pre-selection preflight freshness check (fail-closed) (R9, R24)
  - **File:** `scripts/wave_preflight.*` / selector entrypoint
  - **Expected:** before selection, fail closed if the runtime index does not reproduce from current frontmatter, so a stale local index cannot silently diverge before CI.
  - **R-IDs:** R9, R24

### 3. Precedence policy + author-time lint — M

- [x] 3.1 Encode precedence + documented total-order tie-break (R11)
  - **File:** `core/sw-reference/capability-manifest.md` + selector precedence module
  - **Expected:** precedence `config override > signal match > default`; remaining ties resolved deterministically via a documented total order (capability-id lexicographic) so equal-precedence overlaps cannot be machine-/emitter-order-dependent.
  - **R-IDs:** R11
- [x] 3.2 Author-time manifest lint wired into the test gate (R11, R25, R27)
  - **File:** `scripts/capability-manifest-lint.sh` (registered in `workflow.config.json` `verify.test`)
  - **Expected:** conflict taxonomy (duplicate id, overlapping globs/predicates at equal precedence, competing defaults) fails closed without a precedence resolution; also rejects `kind`/path mismatch and index entries referencing non-existent artifacts (anti-spoof).
  - **R-IDs:** R11, R25, R27
- [x] 3.3 Lint failing-before / passing-after fixtures (R11, R25)
  - **File:** `scripts/test/run-capability-lint-fixtures.sh`
  - **Expected:** `precedence-conflict-lint-fails-closed` (ambiguous triggers fail) and the passing case (precedence resolution present); `capability-kind-spoof-rejected`.
  - **R-IDs:** R11, R25

### 4. Deterministic selector + `signal_context` — L

- [x] 4.1 Versioned `signal_context` schema with fail-closed defaults (R10)
  - **File:** `core/sw-reference/signal-context.schema.json` (+ contract in `capability-manifest.md`)
  - **Expected:** `{tier, doc_path, body_snapshot|derived_tags, file_paths[], change_digest, config, phase_type, conductor_mode, overrides}`, each slot with a documented fail-closed default (missing triage → empty tags; unset provider → none); fully static (not the live working tree).
  - **R-IDs:** R10
- [x] 4.2 Deterministic selector primitive (canonical JSON + trust fields) (R10, R14)
  - **File:** `scripts/capability-select.sh` → `capability_select.py`
  - **Expected:** takes a `signal_context`, returns canonically serialized JSON (ids sorted, fixed field order, membership hash separated from presentation metadata); each entry carries `eligible`, `executable`, `authorized`, `gateRef`, `refusalReason`; identical inputs ⇒ byte-identical output.
  - **R-IDs:** R10, R14
- [x] 4.3 Snapshot `signal_context` to durable state for resume (R10)
  - **File:** `capability_select.py` + durable run-state writer
  - **Expected:** the resolved `signal_context` is snapshotted at first selection; a mid-run resume replays the identical context rather than re-reading mutated files.
  - **R-IDs:** R10
- [x] 4.4 Selector isolation + determinism fixtures (failing-before/passing-after) (R14, R25)
  - **File:** `scripts/test/run-capability-select-fixtures.sh`
  - **Expected:** fixed signal contexts → asserted capability set; repeat-run byte-identical across both dist trees (`selector-determinism-repeat-identical`, `selector-isolation-fixture`).
  - **R-IDs:** R14, R25
- [x] 4.5 Drop-in fixture — frontmatter-only selection (R12)
  - **File:** `scripts/test/run-capability-select-fixtures.sh`
  - **Expected:** a new **non-executable** capability added via frontmatter only (no orchestrator-command edits) is selected (`capability-dropin-frontmatter-only`, SC1).
  - **R-IDs:** R12

### 5. Trust boundary + execution chokepoint + kernel-hook pinning — M

- [x] 5.1 Non-authorizing selector output through named gates (R27)
  - **File:** `capability_select.py` + provider/hook/memory call sites
  - **Expected:** every executable invocation flows through its named existing gate — providers → `check-gate.sh` / `review-local-resolve.sh` + the `providers/<family>/` adapter; hooks → emitter-registered `hooks.json` slots; memory → `memory-preflight`. Eligibility never authorizes; unknown/unconfigured executables fail closed.
  - **R-IDs:** R27
- [x] 5.2 Kernel-hook pinning (exclude safety hooks from selection/reordering) (R27)
  - **File:** emitter hooks registration + manifest lint
  - **Expected:** `beforeSubmitPrompt` guardrails and memory/redaction hooks are excluded from manifest selection and reordering; manifest hooks may only augment non-safety slots and never run before guardrails.
  - **R-IDs:** R27
- [x] 5.3 Trust / anti-spoof / schema fixture table (R27)
  - **File:** `scripts/test/run-capability-select-fixtures.sh` + lint fixtures
  - **Expected:** `capability-trust-unconfigured-provider`, `capability-trust-unknown-hook`, `capability-config-override-untrusted`, `capability-index-tamper-reject` each resolve `eligible:true, executable:true, authorized:false`; `capability-hook-kernel-non-selectable`; malformed manifest frontmatter fails schema validation (failing-before), valid passes.
  - **R-IDs:** R27

### 6. Migration with parity + shadow cutover + call-site map — L

- [ ] 6.1 Integration / call-site map + dual-run shadow harness (R13)
  - **File:** `docs/prds/021-capability-manifest-and-selector/` (map) + dual-run shadow runner
  - **Expected:** enumerate every current selection site and its replacement selector invocation (`sw-doc-review`, `sw-review` / `code-review-select.sh`, `check-gate.sh`, provider resolution, deliver/phase entry, `sw-subagent-dispatch` consumers); a dual-run fixture asserts selector output equals the legacy selection on the golden corpus before any legacy branch is removed.
  - **R-IDs:** R13
- [ ] 6.2 Migrate doc-review personas (parity) (R13)
  - **File:** `core/skills/doc-review/SKILL.md`, `core/commands/sw-doc-review.md`
  - **Expected:** selector-in/out golden fixture covering the tier gate, doc-type routing, security/design text-token gates (shared regex table preserving whole-token / inflection / polysemous-exclusion rules), and overrides; byte-identical to legacy; remove the legacy branch once `migration-parity-doc-review` is authoritative.
  - **R-IDs:** R13
- [ ] 6.3 Migrate code-review specialist roster (parity over change-digest) (R13)
  - **File:** `core/providers/code-review/native.md`, `code-review-select.sh`
  - **Expected:** selection over the persisted change-digest; byte-parity with `code-review-select.sh` / `run-code-review-fixtures.sh` (`migration-parity-code-review`).
  - **R-IDs:** R13
- [ ] 6.4 Migrate config-selected provider families (parity) (R13)
  - **File:** `check-gate.sh` / `wave_preflight` + `core/providers/**`
  - **Expected:** `review.provider`, `review.local`, `memory.provider`, `verify.provider` enumerated; configuredness (absent / `none` / unconfigured) matches `check-gate.sh` / `wave_preflight` verdicts exactly (`migration-parity-providers`).
  - **R-IDs:** R13
- [ ] 6.5 Migrate `sw-subagent-dispatch` current selection (parity, no widening) (R13)
  - **File:** `core/rules/sw-subagent-dispatch.mdc` + dispatch consumers
  - **Expected:** file-count from declared paths + the durable `inline`/`background_phase` flag; model-tier binding stays in `resolve-model-tier.sh` / `reviewer-dispatch-check.sh` (referenced, not re-encoded); delegate/fan-out budget widening explicitly deferred to PRD-023 (`migration-parity-dispatch`).
  - **R-IDs:** R13

### 7. Run-log surfacing — S

- [x] 7.1 Emit resolved capability set into run-log sinks (R21)
  - **File:** deliver `run.log` + per-phase run-dir writer
  - **Expected:** inputs hash, resolved set, precedence trace, and timestamp written to the durable run-log sink at each selection site, aligned with the doc-review activation record.
  - **R-IDs:** R21
- [x] 7.2 Run-log surfacing fixture (R21)
  - **File:** `scripts/test/run-capability-select-fixtures.sh`
  - **Expected:** for a fixed signal context, the resolved capability set appears in the run log at selection time (`run-log-capability-set-surfaced`).
  - **R-IDs:** R21

### 8. Documentation + emitter propagation + freshness — M

- [ ] 8.1 Selection-doc migrations (prose → manifest + selector) (R24)
  - **File:** `core/skills/doc-review/SKILL.md`, `core/commands/sw-doc-review.md`, `core/commands/sw-doc.md`, `core/rules/sw-subagent-dispatch.mdc`, `core/providers/code-review/native.md`, `core/providers/review/CAPABILITIES.md`, `core/rules/code-review-automation.mdc`, `core/skills/triage/SKILL.md`, `.sw/models-tiering.md`
  - **Expected:** prose that currently *is* the selection algorithm now points at the manifest + selector, retaining the tier gate / overrides / activation-record shape; model-tier resolution noted as orthogonal.
  - **R-IDs:** R24
- [ ] 8.2 Layout + configuration + CONTRIBUTING updates (R24)
  - **File:** `.sw/layout.md`, `core/sw-reference/layout.md`, `docs/guides/configuration.md`, `CONTRIBUTING.md`
  - **Expected:** capability-manifest frontmatter contract + generated-index path + selector + freshness-gate entries in layout; configuration capability-selection subsection (eligibility vs config/trust gating, R27) stating **no** new `workflow.config.json` keys; CONTRIBUTING adds the capability-select / manifest-lint / parity fixture suites + "regenerate dist after core manifest edits" reminder.
  - **R-IDs:** R24
- [ ] 8.3 Regenerate both dist trees; freshness gate green (R24)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `scripts/test/run-emitter-fixtures.sh` passes; `dist/` parity with `core/` (schema, index, selector, lint, and migrated docs propagated).
  - **R-IDs:** R24

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 2, 3 |
| 5 | 4 |
| 6 | 4, 5 |
| 7 | 4 |
| 8 | 6, 7 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R9 | 1.1, 1.2, 2.1 | `capability-manifest-schema-valid`; `emitter-freshness-stale-index` |
| R10 | 4.1, 4.2, 4.3 | `selector-determinism-repeat-identical` |
| R11 | 3.1, 3.2, 3.3 | `precedence-conflict-lint-fails-closed` |
| R12 | 1.2, 4.5 | `capability-dropin-frontmatter-only` |
| R13 | 6.1, 6.2, 6.3, 6.4, 6.5 | `migration-parity-doc-review`; `migration-parity-code-review`; `migration-parity-providers`; `migration-parity-dispatch` |
| R14 | 4.2, 4.4 | `selector-isolation-fixture` |
| R21 | 7.1, 7.2 | `run-log-capability-set-surfaced` |
| R24 | 2.1, 2.2, 2.3, 8.3 | `emitter-freshness-stale-index` |
| R25 | 3.3, 4.4 | `precedence-conflict-lint-fails-closed` (lint failing-before/after); `selector-isolation-fixture` (selector failing-before/after) |
| R27 | 1.1, 5.1, 5.2, 5.3 | `capability-trust-unconfigured-provider`; `capability-hook-kernel-non-selectable`; `capability-kind-spoof-rejected`; `capability-index-tamper-reject` |

## Relevant Files

- `core/sw-reference/capability-manifest.schema.json` — manifest frontmatter schema (anti-spoof, path-derived `kind`)
- `core/sw-reference/capability-manifest.md` — frontmatter/precedence/trust contract
- `core/sw-reference/signal-context.schema.json` — versioned `signal_context` (fail-closed defaults)
- `core/sw-reference/capability-index.json` — emitter-generated, freshness-gated index
- `scripts/capability-select.sh` / `capability_select.py` — deterministic selector primitive
- `scripts/capability-manifest-lint.sh` — author-time precedence/conflict/anti-spoof lint
- `scripts/wave_preflight.*` — pre-selection index freshness check
- `scripts/test/run-capability-select-fixtures.sh`, `run-capability-lint-fixtures.sh`, `run-emitter-fixtures.sh` — fixture suites
- Migration targets: `core/skills/doc-review/SKILL.md`, `core/commands/sw-doc-review.md`, `core/providers/code-review/native.md`, `code-review-select.sh`, `check-gate.sh`, `core/rules/sw-subagent-dispatch.mdc`
- `.sw/layout.md`, `core/sw-reference/layout.md`, `docs/guides/configuration.md`, `CONTRIBUTING.md` — docs

## Notes

- **Zero behavior change is the bar.** Each migration family (Phase 6) cuts over only after its selector-in/out
  golden fixture proves byte-parity in a dual-run shadow; legacy selection branches are removed per family, not
  big-bang (TR9).
- **Eligibility ≠ authorization.** The selector is non-authorizing (Phase 5); executables still pass their
  named trust/config gate, and kernel/safety hooks are never manifest-selectable or reorderable.
- **Sequencing bet:** PRD-022 extends this slice's lint/harness for guidelines (SC6) — do not fork a second
  validation harness.
- This slice ships with **no** `orchestration.planPolicy` flag and **no** new config keys.
