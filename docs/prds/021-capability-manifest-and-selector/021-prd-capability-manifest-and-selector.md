---
brainstorm: docs/brainstorms/2026-06-26-guidelined-autonomous-orchestration-requirements.md
date: 2026-06-26
topic: capability-manifest-and-selector
frozen: true
frozen_at: 2026-06-26
---
# PRD 021 — Capability manifest and selector

## Overview

This is **PRD-1 of the four-PRD guidelined-autonomous-orchestration program** (021 → 022 → 023 → 024). It
delivers the foundation the rest of the program builds on: a declarative **capability manifest** and a
**deterministic selector** that resolve which skills, personas, providers, rules, and hooks apply to a given
phase/signal context — replacing today's hand-stitched, per-command capability wiring.

It is the **lowest-autonomy-risk** slice: it introduces **no** agent-proposed plans, **no** kernel/plan-policy
split, and **no** orchestrator autonomy changes (those land in 022–024). It only makes capability selection
declarative, deterministic, and drop-in, and migrates existing signal-driven behavior onto the manifest with
**zero behavior change** (parity-proven). Because nothing here changes orchestration decisions, it ships
without the `orchestration.planPolicy` flag and is safe to land ahead of the gate.

It is **not** a trivial slice, and this PRD does not pretend otherwise. To preserve byte-parity, the selector
must reproduce selection that today depends on more than triage tags — document body text and doc-type path
(doc-review persona gating), diff content (code-review specialist gating), and dispatch heuristics
(`sw-subagent-dispatch`). The design choice (see Decision Log) is to **broaden the signal contract to a
versioned, fully *static* `signal_context`** captured/snapshotted at phase entry (R10, TR3) rather than narrow
the migration. This is a real engineering surface and is sized as such in the Rollout Plan and Success
Criteria.

**Standalone value (before 022–024).** Even with zero behavior change, this slice pays off on its own:
(a) *maintainer velocity* — a new capability is added via a single frontmatter edit with no orchestrator prose
changes (R12); (b) *operator auditability* — the run log shows the resolved capability set, "why these
capabilities" (R21 manifest slice); (c) *testability* — an isolated, fixture-pinned selector reduces
regression risk for every later program slice. **Sequencing:** 022 cannot precede 021 because the
plan-validation gate and guidelines consume the resolved capability set and **extend this slice's manifest
validation harness** (brainstorm OQ6, PRD-022 TR3).

Source brainstorm R-IDs are carried forward verbatim (stable namespace; do not renumber). This PRD owns
R9–R14 and R27, plus the manifest-scoped portions of the cross-cutting R21/R24/R25. Enhancements surfaced in
doc-review are folded into Technical Requirements / Security / Testing rather than new R-IDs (the brainstorm
namespace is frozen).

## Goals

1. A single declarative manifest schema lets any capability (skill, persona, provider, rule, hook) state
   *when it applies* in its own per-capability frontmatter, with an emitter-generated, freshness-gated index.
2. A deterministic selector resolves the active capability set for a phase/signal context such that
   identical signals always yield an identical set, and the selector is fixture-testable in isolation.
3. Adding, removing, or re-triggering a capability requires editing **only** that capability's declaration —
   no orchestrator command prose changes — proven by a drop-in fixture. (Non-executable capabilities are
   fully drop-in; executable capabilities are made *eligible* drop-in but remain gated by their existing
   trust/config gate before they can run, per R27.)
4. All existing signal-driven behavior (config-selected providers, triage-gated doc-review personas,
   `sw-subagent-dispatch` heuristics) is migrated onto the manifest with **byte-equivalent** selection
   results, proven by parity fixtures.
5. Executable capabilities (hooks, providers) keep their existing trust boundary: a manifest declaration
   confers *eligibility by signal* only and never auto-elevates or bypasses trust/config gating.

## Non-Goals

- Agent-proposed step plans, the kernel/plan-policy split, the plan-validation gate, and guidelines — all in
  PRD-022.
- Intra-phase parallelism changes, the `/sw-deliver` pilot, and the benefit metric — PRD-023.
- Conductor adoption for `/sw-debug`, `/sw-doc`, `/sw-feedback` — PRD-024.
- The `orchestration.planPolicy` flag — introduced in PRD-022; this slice has no orchestration-decision
  surface to gate.
- Guideline artifact authoring and guideline schema validation — PRD-022 (which extends this slice's manifest
  validation harness; guidelines are a *separate* artifact type).
- Semantic widening of `sw-subagent-dispatch` (budget/heuristic-based intra-phase fan-out) — PRD-023 (R15–R17).
  This slice migrates only the *current* dispatch behavior with byte-equivalent parity; it does not change
  thresholds or add new fan-out latitude.
- Run-log surfacing of *chosen plans* and *plan rejections* — PRD-022/023/024; this slice surfaces the
  resolved **capability set** only.
- A public/general-purpose plugin extension API or marketplace — the manifest is internal capability wiring.
- Any change to what capabilities *do*; only how they are *selected*.

## Success Criteria

Measurable, PRD-local outcomes (not just mechanisms):

1. **SC1 — Drop-in:** a new *non-executable* capability (e.g. a persona) is selected by a single frontmatter
   edit with **zero** orchestrator-command-prose changes, proven by the drop-in fixture (R12).
2. **SC2 — Zero parity regressions:** every migrated family (doc-review personas, code-review specialist
   roster, config-selected providers, current `sw-subagent-dispatch` selection) produces **byte-identical**
   resolved sets versus today across the full golden-fixture corpus (R13, TR6, TR9).
3. **SC3 — Determinism:** identical `signal_context` → byte-identical canonical selector JSON on repeat runs
   and across both dist trees (R10, TR3).
4. **SC4 — Auditability:** the resolved capability set appears in the run log for every selection site
   (R21, TR7).
5. **SC5 — Trust held:** no manifest declaration, config override, or hand-edited index can cause an
   untrusted/unconfigured executable or a non-kernel-ordered safety hook to run — every untrusted fixture
   resolves `eligible:true, executable:true, authorized:false` (R27, TR5).
6. **SC6 — Harness reuse:** the manifest validation lint/harness is extended (not rewritten) by PRD-022 for
   guidelines, confirming the sequencing bet.

## Requirements

R-IDs carried forward from the frozen-namespace brainstorm.

### Owned — capability manifest + selector

- **R9** A capability manifest schema lets skills, personas, providers, rules, and hooks declare their
  trigger conditions (signals such as triage tags, file globs, config flags) and selection metadata in
  **per-capability frontmatter** (the source of truth); an emitter-generated, committed index aggregates
  these declarations and is freshness-gated — there is no hand-maintained central registry.
- **R10** A deterministic selector resolves the active capability set for a given phase/signal context:
  identical signals yield an identical set. Selection signals are drawn from a **versioned, fully static
  `signal_context`** (TR3) — `tier`, `doc_path`/doc-type, a **frozen snapshot** of the review-target body (or
  triage-derived tags computed once from it), the task list's declared `**File:**` paths, a **persisted
  change-digest** (for diff-driven code-review gating), `config`, `phase_type`, `conductor_mode`
  (`inline`/`background_phase`), and CLI `overrides` (`--personas`/`--all`) — **not** the live (evolving)
  working tree. Every signal slot has a documented **fail-closed default** for the absent/unset case (e.g.
  missing triage → empty tag set; unset provider → none), and the resolved `signal_context` is **snapshotted
  to durable state at first selection** so a mid-run resume replays the identical context rather than
  re-reading mutated files — keeping the set available and stable at phase entry.
- **R11** Capability selection has a documented precedence / conflict-resolution policy (e.g. explicit
  config override > signal match > default) with deterministic tie-breaking, enforced at **both** layers:
  an author-time manifest lint (wired into the test gate; see R25) fails on ambiguous/overlapping triggers
  that lack a precedence resolution, and the selector resolves remaining ties deterministically at selection
  time via a documented **total order** (capability-id lexicographic) so equal-precedence overlaps on the
  same trigger predicate cannot produce machine- or emitter-order-dependent set membership or ordering.
- **R12** Adding, removing, or re-triggering a capability requires only changing that capability's declared
  manifest entry — no edit to orchestrator command prose is needed for the workflow to pick it up.
- **R13** Existing signal-driven behavior (config-selected providers, triage-gated doc-review personas,
  `sw-subagent-dispatch` heuristics) is migrated onto the manifest without behavior change, proven by parity
  fixtures. The migration encodes today's behavior as **static, scriptable signals** over the `signal_context`
  (R10): doc-review keyword/heading gates as text-token predicates over the frozen body snapshot, code-review
  specialist gating over the persisted change-digest, and `sw-subagent-dispatch` *current* selection (e.g.
  file-count from declared paths, the durable `inline`/`background_phase` flag). **Model-tier binding stays in
  `resolve-model-tier.sh` / `reviewer-dispatch-check.sh`** (referenced from manifest metadata, not re-encoded),
  and the dispatch rule's *delegate/fan-out budget* widening is explicitly out of scope (PRD-023, see
  Non-Goals).
- **R14** The selector is fixture-testable in isolation (signal inputs → resolved capability set) as part of
  the test gate.
- **R27** Capability manifest entries are schema-validated, and **executable** capabilities (hooks,
  providers) retain their existing trust boundary: a manifest declaration selects *eligibility* by signal
  but never auto-elevates trust or bypasses the provider/hook trust gating — a manifest entry alone cannot
  cause an untrusted or unconfigured executable to run. Declaring a non-executable capability (skill,
  persona, rule) is drop-in; declaring an executable one still requires the existing trust/config gate.

### Cross-cutting (manifest-scoped slice; primary home in this PRD)

- **R21** (manifest slice) The resolved capability set for each phase/run is surfaced in the run log so an
  operator can audit "why these capabilities." (This slice surfaces the **resolved capability set only**;
  plan *rejection* logging is PRD-022 R6, and *chosen-plan* surfacing in the consolidated halt/terminal
  report arrives with the deliver pilot in PRD-023 and the orchestrator fan-out in PRD-024.)
- **R24** (manifest slice) The manifest schema, the generated capability index, the selector, and the
  author-time lint are authored/derived in `core/` and propagated to `dist/cursor` and `dist/claude-code`
  via the emitter with the freshness gate passing.
- **R25** (manifest slice) The selector and the author-time lint each have failing-before / passing-after
  regression fixtures wired into the test gate, alongside the migration parity fixtures (R13).

## Technical Requirements

- **TR1 — Manifest frontmatter schema.** Define a versioned frontmatter block (added to existing
  skill/persona/provider/rule/hook source files in `core/`) declaring `triggers` (triage tags, **text-token
  predicates** over the frozen body snapshot, file/path globs, change-digest predicates, config-flag
  predicates), `precedence`, an explicit **`always_on` / `phase_default`** trigger (so always-applicable
  capabilities — e.g. the six always-on doc-review personas — migrate without a silent default and are
  lint-visible), and selection `metadata`. **Executable `kind` is derived from the canonical source path
  prefix** (`providers/**`, `hooks/**`) — **not** author-declared alone — and the lint rejects any
  `kind`/path mismatch and any index entry that does not reference an existing artifact (anti-spoof, G5).
  Schema documented and validated; absence of the block means "not signal-selected" (back-compat default)
  (R9, R12, R27).
- **TR2 — Generated capability index.** The emitter (`python3 -m sw generate`) aggregates per-capability
  frontmatter into a committed index at **`core/sw-reference/capability-index.json`**, emitted to both dist
  trees. Parsing uses a **structured YAML parser** (not a line-based `key: value` reader) so nested
  `triggers` blocks round-trip. Freshness is enforced **two ways**: the test-gate fixture
  (`scripts/test/run-emitter-fixtures.sh`) fails on a stale index, **and** a **pre-selection/preflight
  freshness check** (wired into `wave_preflight` / the selector entry) fails closed if the runtime index does
  not reproduce from current frontmatter — so a stale or hand-edited local index cannot silently diverge
  before CI (R9, R24).
- **TR3 — Deterministic selector primitive + `signal_context` schema.** A new selector
  (`scripts/capability-select.sh` → `capability_select.py`) takes a **versioned `signal_context`** —
  `{tier, doc_path, body_snapshot|derived_tags, file_paths[], change_digest, config, phase_type,
  conductor_mode, overrides}` with documented **fail-closed defaults** per slot — and returns the resolved
  set as **canonically serialized** JSON (capability ids sorted, fixed field order, membership hash separated
  from presentation metadata). Each entry carries explicit trust fields **`eligible`, `executable`,
  `authorized`, `gateRef`, `refusalReason`** so eligibility is never confused with authorization. Identical
  inputs yield byte-identical output; the resolved `signal_context` is persisted for resume (R10, R27).
- **TR4 — Precedence + author-time lint.** Encode the precedence policy (config override > signal match >
  default) with the documented total-order tie-break (capability-id lexicographic), the conflict taxonomy
  (duplicate id, overlapping globs/predicates at equal precedence, competing defaults), and a manifest lint
  that fails closed on unresolved conflicts; wire the lint into the test gate (R11, R14, R25).
- **TR5 — Trust boundary + execution chokepoint.** Selector output is **non-authorizing**: every executable
  invocation must flow through its **named** existing gate — providers → `check-gate.sh` /
  `review-local-resolve.sh` + the adapter path under `providers/<family>/`; hooks → emitter-registered
  `hooks.json` slots only; memory → `memory-preflight`. **Kernel/safety hooks** (`beforeSubmitPrompt`
  guardrails, memory/redaction hooks) are **excluded from manifest selection and from reordering** — manifest
  hooks may only augment non-safety slots and never run before guardrails. A manifest entry (or config
  override) never elevates trust; unknown/unconfigured executables fail closed (R27, G3, G4).
- **TR6 — Migration with parity (per family).** Migrate as explicit families, each with a **selector-in /
  selector-out golden fixture** (replacing the current grep/prose-sync runner, which is retained only as a
  transitional doc-sync check): (a) **doc-review personas** — tier gate, doc-type routing, security/design
  text-token gates (preserving whole-token / inflection / polysemous-exclusion rules via a shared regex
  table), overrides; (b) **code-review specialist roster** — over the persisted change-digest, parity with
  `code-review-select.sh` / `run-code-review-fixtures.sh`; (c) **config-selected providers** — enumerated
  per family (`review.provider`, `review.local`, `memory.provider`, `verify.provider`) with configuredness
  (absent/`none`/unconfigured) matching `check-gate.sh` / `wave_preflight` verdicts exactly; (d)
  **`sw-subagent-dispatch` current selection** — file-count from declared paths + durable
  `inline`/`background_phase` flag (delegate/fan-out budget widening deferred to PRD-023) (R13).
- **TR7 — Run-log surfacing.** Emit the resolved capability set (inputs hash, resolved set, precedence trace,
  timestamp) into the durable run-log sink for each selection site — deliver `run.log`, the per-phase run
  dir, and alignment with the doc-review activation record (R21).
- **TR8 — Emitter propagation.** Regenerate both dist trees; freshness gate green (R24).
- **TR9 — Integration / call-site map + shadow cutover.** Enumerate every current selection site and its
  replacement selector invocation (`sw-doc-review`, `sw-review` / `code-review-select.sh`, `check-gate.sh`,
  provider resolution, deliver/phase entry, `sw-subagent-dispatch` consumers). Each site cuts over only after
  a **dual-run shadow** period proves the selector output matches the legacy path on the golden corpus; legacy
  selection branches are removed per family only once its parity fixture is authoritative. Without this map,
  a tested selector that nothing calls would leave legacy prose authoritative (R12, R13).

## Documentation deliverables

Parity migration must land with companion documentation so the selection contract is not described two ways.
Tasks generation must include:

- **New:** `core/sw-reference/capability-manifest.schema.json` + `core/sw-reference/capability-manifest.md`
  (frontmatter fields, applicable source kinds, absence-default, precedence/conflict policy R11, executable
  vs non-executable trust boundary R27), emitted to both dist trees.
- **`.sw/layout.md` + `core/sw-reference/layout.md`:** add the capability-manifest frontmatter contract and
  the generated-index path + selector + freshness-gate entries.
- **Selection-doc migrations** (rewrite prose that currently *is* the selection algorithm to point at the
  manifest + selector, retaining tier gate / overrides / activation-record shape): `core/skills/doc-review/SKILL.md`,
  `core/commands/sw-doc-review.md`, `core/commands/sw-doc.md`, `core/rules/sw-subagent-dispatch.mdc`,
  `core/providers/code-review/native.md`, `core/providers/review/CAPABILITIES.md`,
  `core/rules/code-review-automation.mdc`, `core/skills/triage/SKILL.md` (security-tag cross-ref),
  `.sw/models-tiering.md` (capability-select is orthogonal to model-tier resolution).
- **`docs/guides/configuration.md`:** add a capability-selection subsection (eligibility vs config/trust
  gating, R27) and state explicitly that this slice adds **no** new `workflow.config.json` keys.
- **`CONTRIBUTING.md`:** add the capability-select / manifest-lint / parity fixture suites to the local test
  list and the "regenerate dist after core manifest edits" reminder.
- **Out of scope (PRD-009 living-doc gate owns these):** `docs/prds/INDEX.md`, `COMPLETION-LOG.md`,
  `GAP-BACKLOG.md` — not re-gated here.

## Security & Compliance

- **Trust boundary (R27).** Executable capability selection is eligibility-only; hooks/providers still pass
  their existing trust/config gate before running. No manifest declaration **or config override** can cause
  an untrusted executable to run. The `memory` provider trust boundary and redaction chokepoint are unchanged.
- **Execution chokepoint (TR5).** Selector output is non-authorizing: executables are invoked only through
  their named existing gate (`check-gate.sh` / `review-local-resolve.sh` + adapter path; `hooks.json` slots;
  `memory-preflight`). A fixture fails if selector eligibility alone triggers execution.
- **Kernel-hook pinning (TR5).** Kernel/safety hooks (`beforeSubmitPrompt` guardrails, memory/redaction) are
  excluded from manifest selection and reordering; manifest hooks may only augment non-safety slots and never
  run before guardrails. Asserted by `capability-hook-kernel-non-selectable`.
- **Anti-spoof (TR1).** Executable `kind` is derived from the canonical path prefix, not author-declared
  frontmatter; the lint rejects `kind`/path mismatch and entries referencing non-existent artifacts, so a
  malicious PR cannot declare a benign `kind` over an executable.
- **No new execution surface.** The selector resolves *which* declared capabilities apply; it does not invent
  new executables or widen what any capability may do.
- **Memory routing unchanged.** Manifest eligibility for any memory-related capability does **not** bypass
  `memory-preflight` / `providers/<memory.provider>.md`; direct provider calls remain prohibited.
- **Irreversible chokepoints untouched (R23 parity).** The push/secret-scan chokepoint and the redaction
  chokepoint are unchanged; no selector path invokes push or weakens the secret scan.
- **Deterministic, auditable selection.** Selection is rule-based and logged (R21), preserving the plugin's
  "same inputs → same decision" auditability.

## Testing Strategy

- **Selector determinism (R10, R14):** fixtures feeding fixed signal contexts → asserted capability set;
  repeat-run identical output.
- **Precedence + lint (R11):** fixtures with conflicting triggers — lint fails closed without a precedence
  resolution; passes with one.
- **Migration parity (R13, TR6):** **selector-in / selector-out golden fixtures** per family (doc-review
  personas incl. security/design token gates, code-review roster over change-digest, provider families with
  configuredness edges, `sw-subagent-dispatch` current selection) produce byte-identical results versus the
  legacy path; the legacy grep runner is retained only as a transitional doc-sync check.
- **Kernel-hook / anti-spoof (TR1, TR5):** `capability-hook-kernel-non-selectable` (manifest cannot register
  or reorder a hook ahead of guardrails) and `capability-kind-spoof-rejected` (declared `kind` contradicting
  the path fails the lint).
- **Integration / shadow cutover (TR9):** a dual-run fixture asserts selector output equals the legacy
  selection at each migrated call site before the legacy branch is removed.
- **Schema validation (R27):** fixture with malformed/invalid manifest frontmatter fails schema validation
  (failing-before); a valid entry passes (passing-after).
- **Trust boundary (R27):** fixture table mirroring the Security bullets — `capability-trust-unconfigured-provider`,
  `capability-trust-unknown-hook`, `capability-config-override-untrusted` (config override may change
  eligibility only, never authorize an unknown/unconfigured executable), and `capability-index-tamper-reject`
  (a hand-edited phantom/mis-typed index entry fails closed at lint or select time) — each asserts
  `eligible:true, executable:true, authorized:false` for the untrusted case so eligibility never implies
  execution.
- **Run-log surfacing (R21):** for a fixed signal context, the resolved capability set appears in the run log
  at selection time.
- **Drop-in (R12):** fixture adds a new capability via frontmatter only (no command edits) and it is
  selected.
- **Emitter freshness (R24):** stale-index fixture fails the freshness gate.
- **Fixture methodology (R25):** the selector and the author-time lint each ship paired **failing-before /
  passing-after** fixtures, alongside the migration parity fixtures (R13).
- All wired into the existing `scripts/test/run-*-fixtures.sh` suites referenced by `workflow.config.json`
  `verify.test` (R25).

## Rollout Plan

1. Land manifest schema (incl. `always_on`/anti-spoof), emitter index (`capability-index.json`) + freshness
   checks, the selector + `signal_context` schema, and the lint — behind no runtime behavior change.
2. Migrate families one at a time with a **dual-run shadow** period (TR9), each gated by its selector golden
   fixture: doc-review personas → code-review roster → provider families → `sw-subagent-dispatch` current
   selection. Remove a legacy selection branch only once its parity fixture is authoritative.
3. Once parity is green across all families, the manifest is the single source for capability selection;
   PRD-022 consumes it for guidelines and the validation gate (extending this slice's lint/harness).
4. No `orchestration.planPolicy` flag in this slice — there is no orchestration-decision change to gate.

**Sizing note.** Because the signal contract is broadened (Decision Log) rather than narrowed, this slice is a
non-trivial engineering surface (schema + index + selector + lint + four migration families + shadow
cutover). The shadow-per-family rollout makes it incrementally shippable: each family delivers its own
drop-in/auditability win as it cuts over, rather than one big-bang cutover.

## Decision Log

- **Per-capability frontmatter + generated index** chosen over a central registry (brainstorm OQ1): preserves
  drop-in authoring; the index is derived and freshness-gated, never hand-edited.
- **Migration is parity-gated** rather than "best effort": existing selection behavior must be byte-equivalent
  before the manifest becomes authoritative, so this foundational slice cannot silently change today's runs.
- **Trust boundary kept explicit** (brainstorm F2/R27): declaring an executable capability is *not* drop-in —
  it still requires the existing trust/config gate.
- **Broaden the signal contract, do not narrow the migration** (doc-review, scope decision A): rather than
  defer content-/diff-/dispatch-driven selection out of 021, the slice defines a versioned, fully *static*
  `signal_context` (snapshotted at phase entry) so all four families migrate with byte-parity in one slice.
  Accepted cost: a larger selector + signal schema; mitigated by shadow-per-family cutover (TR9).
- **Execution chokepoint + kernel-hook pinning** (doc-review security/adversarial): selector output is
  non-authorizing and routes through named existing gates; kernel/safety hooks are excluded from manifest
  selection/reordering — closing the "eligibility = execution" and "hook ahead of guardrails" gaps.
- **Anti-spoof via path-derived `kind`** (doc-review security): executable classification comes from the
  source path, not author-declared frontmatter, so a malicious entry cannot mislabel an executable.

## Open Questions

None — the program's open questions were resolved in the brainstorm (2026-06-26). Guideline/manifest boundary
(brainstorm OQ6) is settled as "separate artifact types sharing a validation harness" and is exercised in
PRD-022; it imposes no open decision on this slice.
