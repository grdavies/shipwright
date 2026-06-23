---
title: "feat: phase-flow v2 documentation workstream (triage + doc pipeline + freeze/amendments)"
type: feat
date: 2026-06-22
origin: docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md
status: done
completed: 2026-06-23
branch: feat/doc-workstream
commit: e4b8f38
pr: https://github.com/grdavies/currsor-phase-flow-2/pull/2
---

# feat: phase-flow v2 documentation workstream (triage + doc pipeline + freeze/amendments)

## Implementation status

| Unit | Status | Notes |
|------|--------|-------|
| U1 | **Done** | `docs/layout.md`, seeded `prds/INDEX.md` / `COMPLETION-LOG.md` / `GAP-BACKLOG.md`, config `prdsDir`/`tasksDir` |
| U2 | **Done** | `/pf-triage`, `skills/triage/SKILL.md` |
| U3 | **Done** | `/pf-brainstorm`, brainstorm skill + requirements sections |
| U4 | **Done** | `/pf-prd`, PRD skill |
| U5 | **Done** | `/pf-doc-review`, seven `pf-*-reviewer` agents, findings schema + synthesis |
| U6 | **Done** | `/pf-freeze`, hooks, `check-frozen.sh`, CI workflow `frozen` |
| U7 | **Done** | `/pf-amend` |
| U8 | **Done** | `skills/spec-union`, `scripts/spec-union.sh` |
| U9 | **Done** | `/pf-tasks`, tasks skill, INDEX registration on freeze |
| U10 | **Done** | `/pf-doc` orchestrator, `pf-naming` boundary, PROVENANCE |

**Verification:** `bash scripts/test/run-doc-fixtures.sh` — 6/6 passing (spec-union, check-frozen, amendment ordering).

**Shipped:** merged to `main` via [PR #2](https://github.com/grdavies/currsor-phase-flow-2/pull/2) (`e4b8f38`).

## Summary

Build the documentation half of phase-flow v2's Phase 1: a triage step that routes work into Quick / Standard / Full tiers, and the full `pf-` doc pipeline (brainstorm → PRD draft → multi-persona review + synthesis → freeze → task list) with sibling-amendment editing. The pipeline produces frozen, version-controlled handoff artifacts the implementation workstream picks up. This plan sits on the shipped foundation (PR #1: gate, memory seam, review seam, RCA core, hooks) and is the first of the two Phase-1 plans; its sibling is the implementation workstream (`003`).

## Problem Frame

The frozen brainstorm (see origin) commits to tiered ceremony with an up-front triage classifier, a heavier doc pipeline only where it changes outcomes, and freeze-in-depth so handoff specs never silently mutate. The foundation plan (`docs/plans/2026-06-22-001-feat-plugin-foundation-infrastructure-plan.md`) deferred all of this — R5 through R12, the triage classifier, the persona panel, and freeze enforcement — to this workstream.

phase-flow v1 ships a doc pipeline (`/spec-prd` → `/spec-tasks`) but it has no brainstorm stage, no persona review, no freeze/amendment model, and no triage. compound-engineering has strong brainstorm and persona-panel **patterns** but is a large sibling plugin this product must not depend on at runtime. So this workstream ports v1's spec pipeline shape under `pf-`, vendors slimmed adaptations of compound-engineering's brainstorm and persona-panel patterns, and adds the triage classifier, freeze enforcement, and the supersede/retract amendment model that neither upstream has.

**Why now:** documentation and implementation are deliberately separate flows — a frozen doc set is a handoff artifact implementation may pick up immediately or much later. Building the doc pipeline first lets the persona panel and freeze model be verified before the phase loop consumes their output.

---

## Requirements Traceability

Carried from origin (documentation-relevant requirements):

- **Triage:** R5 (three-tier Quick/Standard/Full classifier + risk triggers force ≥Standard + manual override + misroute recovery).
- **Pipeline order + brainstorm:** R6 (brainstorm → PRD → review → freeze → tasks, in order; PRD never before brainstorm; brainstorm adapts ce-brainstorm).
- **Persona panel:** R7 (Full = 7 personas in parallel; Standard = reduced, coherence + scope-guardian minimum; Quick = none), R8 (synthesizer auto-applies safe fixes, gates judgment calls).
- **Freeze + amendments:** R9 (freeze-in-depth: `frozen: true` flag + guardrail rule + pre-commit hook + CI required-check; no unfreeze), R10 (sibling amendment files; typed `supersedes`/`retracts`; review scales to tier; coherence + scope-guardian always run against parent), R11 (amendment R-IDs continue parent namespace), R12 (read-time precedence-aware union; parent never mutated).
- **Naming + sub-agents/tokens:** R34 (names signal workstream + boundary), R28/R29 (persona panel uses parallel sub-agents + a bounded synthesis loop), R30/R31 (full fidelity on brainstorm/PRD/persona analysis; structural sub-agent isolation is the dominant token lever).
- **Deferred-to-planning items now resolved here:** the on-disk layout for brainstorms/PRDs/amendments/tasks/index/log (U1); the triage scoring heuristic + conservative default + misroute re-entry (U2).

Consumed from the shipped foundation: the persona sub-agent dispatch follows the same context-isolation discipline the foundation set; freeze enforcement's guardrail rule joins the existing `rules/` set; the CI required-check rides the gate's existing CI surface.

Explicitly **not** here (sibling/later plans): the worktree phase loop, `/pf-ship`, retrospective/compounding, and the git-derived living-status reconciliation (R13/R14 runtime, R15–R21, R33) belong to the implementation workstream (`003`); debugging and feedback (R22–R27) are Phase 2.

---

## Key Technical Decisions

- **Triage is deterministic, not model-judgment.** `/pf-triage` scores tier from explicit signals — changed/likely-touched file count, risk-trigger keyword match (auth, payments, data migration, public API), and ambiguity markers — with a conservative default to Standard when signals are mixed. Rationale: the brainstorm makes the classifier load-bearing ("what keeps 'quicker' honest"); a deterministic rubric is auditable and testable where an LLM judgment call is neither. Risk triggers are a hard floor that overrides the file-count score. (R5)
- **Brainstorm and persona-panel are pattern-borrowed, not code-copied.** `/pf-brainstorm` and `/pf-doc-review` re-derive compound-engineering's dialogue and panel shapes as slim vendored skills/agents under `pf-`, recorded in `PROVENANCE.md`. Rationale: the brainstorm's vendoring decision favors pattern-borrowing so re-derivation stays cheap and `/pf-upstream` drift stays small; copying CE's full agent set would bloat the plugin and couple it to CE's evolving internals. (R6, R7, origin Key Decisions)
- **PRD pipeline ports v1's spec shape minus auto-freeze.** `/pf-prd` and `/pf-tasks` adapt v1 `spec-prd`/`spec-tasks` (including the mandatory "Go" gate before sub-task expansion) but freeze is a separate explicit step (`/pf-freeze`), not implicit on save. Rationale: freeze is a deliberate, enforced handoff event in v2; folding it into save would lose the persona-review-before-freeze ordering R6 requires. (R6)
- **Persona panel scales by tier, with two always-on personas.** Full PRDs get all seven personas (coherence, feasibility, product, scope-guardian, security, design, adversarial); Standard gets a reduced pass with coherence + scope-guardian as the floor; Quick gets none. The same scaling governs amendment review (R10). Rationale: matches origin R7/R10 and CE's always-on/conditional split; coherence + scope-guardian are the two that protect frozen-spec integrity and scope, so they never drop. (R7, R10)
- **Synthesizer routes findings by an autofix class + confidence.** Adapting CE's pipeline: validate findings against a JSON schema, dedup/merge across personas, then route `safe_auto` (silent apply), `gated_auto` (confirm), `manual` (surface as a trade-off for the user). Rationale: R8's "auto-apply clear fixes, surface only genuine trade-offs" is exactly CE's three-tier routing; reusing the shape avoids reinventing finding triage. (R8)
- **Freeze is enforced in depth with the CI check as the only authority.** Local layers (the `frozen: true` flag, a guardrail rule, a pre-commit hook installed by a `core.hooksPath` bootstrap) are early-warning and bypassable (`--no-verify`); the server-side/CI required-check is the non-bypassable guarantee. There is no unfreeze. Rationale: origin R9 and the Success Criteria name the CI check as authoritative; treating local hooks as convenience avoids a false sense of integrity. (R9)
- **A frozen falsehood is corrected only by a declared, reviewed amendment.** `/pf-amend` writes a sibling file with continued R-IDs and optional typed `supersedes: R<n>` / `retracts: R<n>` directives; coherence + scope-guardian verify every target exists, isn't already retracted, and records a rationale. The parent file is never edited. Rationale: origin R10–R12 — an undeclared contradiction is a failure mode; a declared supersede/retract is the sanctioned exception. (R10, R11)
- **The spec is read as a precedence-aware union at implementation time.** A shared union resolver computes PRD + amendments in amendment order (add new, replace `supersedes`d, drop `retracts`d) and is the single reader the implementation workstream's phase-execute and gap-check consume. Rationale: R12 puts every override in the amendment, never the parent; centralizing the resolution keeps consumers from re-implementing precedence. (R12)
- **On-disk layout is fixed now as a shared contract.** Brainstorms in `docs/brainstorms/`, PRDs in `prds/<n>-<slug>/`, amendments in `prds/<n>-<slug>/amendments/A<k>-<short>.md`, task lists alongside, plus the living index and completion-log locations. Rationale: the layout was deferred to planning and is depended on by triage, freeze, amendments, and the implementation workstream's status reconciliation — pinning it once prevents drift across plans. (origin Outstanding Questions)

---

## High-Level Technical Design

Triage routes work into a tier; the tier gates which pipeline stages run. The Full path runs every stage; Standard skips the brainstorm and runs a reduced panel; Quick exits straight to the implementation workstream with no doc artifacts. Freeze is the irreversible handoff event; post-freeze change re-enters only through `/pf-amend`.

```mermaid
flowchart TB
  IN[New work] --> TRIAGE{/pf-triage}
  TRIAGE -->|Quick| IMPL[hand off to implementation workstream 003]
  TRIAGE -->|Standard| PRD[/pf-prd draft]
  TRIAGE -->|Full| BRAIN[/pf-brainstorm]

  BRAIN --> PRD
  PRD --> PANEL[/pf-doc-review: parallel personas + synthesize]
  PANEL -->|safe_auto applied; trade-offs gated| FREEZE[/pf-freeze: flag + hook + CI check]
  FREEZE --> TASKS[/pf-tasks + register in living index]
  TASKS --> IMPL

  FROZEN[(frozen PRD)] -.post-freeze change.-> AMEND[/pf-amend: sibling file + supersedes/retracts]
  AMEND --> PANEL
  UNION[union resolver: PRD + amendments] -.read at impl time.-> IMPL
```

The diagram is authoritative for stage ordering and gating; per-unit Files sections are authoritative for exact paths.

---

## Output Structure

The on-disk layout this workstream establishes (consumed by `003`'s status reconciliation):

```text
docs/
└── brainstorms/
    ├── YYYY-MM-DD-<topic>-requirements.md            # frozen brainstorm output (/pf-brainstorm)
    └── YYYY-MM-DD-<topic>-requirements.amendments/   # brainstorm-level amendments (already used by A1)
prds/
├── INDEX.md                                          # living PRD index (parent→amendment links + status)
├── COMPLETION-LOG.md                                 # append-only shipped-phase log
├── GAP-BACKLOG.md                                    # committed, append-only trivial-gap backlog (/pf-feedback 005 U3 writes; not frozen, not git-derived)
└── <n>-<slug>/
    ├── <n>-prd-<slug>.md                             # frozen PRD (/pf-prd → /pf-freeze)
    ├── tasks-<n>-<slug>.md                           # frozen task list (/pf-tasks)
    └── amendments/
        └── A<k>-<short>.md                           # frozen amendment (/pf-amend)
```

`INDEX.md` and `COMPLETION-LOG.md` are the living layer (R13); their git-derived status reconciliation (R14) is owned by the implementation workstream (`003`). This plan creates the files and registers entries on freeze; it does not implement the derivation. `GAP-BACKLOG.md` is a third living artifact — a committed, append-only list of trivial in-scope gaps written out-of-loop by `/pf-feedback` (`005` U3); unlike the index/log it is hand-appendable (not git-derived) and unlike the task lists it is never frozen. This plan defines its path and seeds it; `005` writes entries and `003` U10 surfaces it.

---

## Implementation Units

Suggested build order within this plan: layout (U1) and triage (U2) first, then the pipeline stages (U3–U5), then freeze/amendment integrity (U6–U8), then task generation and the orchestrator (U9–U10). The union resolver (U8) is a hard dependency for the implementation workstream and should not slip.

### U1. On-disk artifact layout and path conventions

- **Goal:** A documented, single-source layout for brainstorms, PRDs, amendments, task lists, the living index, and the completion log — the contract every later unit and the implementation workstream resolve paths against.
- **Requirements:** R6, R9, R10, R13 (structure only), origin Outstanding Questions (layout).
- **Dependencies:** none.
- **Files:** `docs/layout.md` (or a `## Layout` section in `README.md`), `prds/INDEX.md` (seeded empty), `prds/COMPLETION-LOG.md` (seeded empty), `prds/GAP-BACKLOG.md` (seeded empty).
- **Approach:** Fix the directory shape shown in Output Structure. Define the PRD numbering scheme (`<n>` zero-padded, monotonic), the slug convention, and the amendment naming (`A<k>-<short>`). Document where each command writes and reads. Seed `INDEX.md`, `COMPLETION-LOG.md`, and `GAP-BACKLOG.md` with headers and an empty-state note; document `GAP-BACKLOG.md` as committed, append-only, hand-appendable, and explicitly not subject to freeze (so `005` U3's source-tagged tasks land without touching a frozen file or the freeze CI check). No behavior beyond the convention doc + seed files.
- **Patterns to follow:** the existing brainstorm path already in use (`docs/brainstorms/...-requirements.md` + `.amendments/`); v1 `prdsDir`/`tasksDir` config keys.
- **Test scenarios:**
  - Layout doc names a concrete path for every artifact type (brainstorm, PRD, amendment, task list, index, log, gap backlog).
  - Seed files parse as valid markdown with the documented headers.
  - `Test expectation: structural only — no runtime behavior.`
- **Verification:** A reader can resolve where any artifact lives from the layout doc alone; later units cite it rather than re-deciding paths.

### U2. `/pf-triage` deterministic tier classifier

- **Goal:** A command that classifies work into Quick / Standard / Full from explicit signals, forces ≥Standard on risk triggers, supports a manual override, and offers a misroute re-entry that promotes a Quick item into the pipeline when its scope expands mid-flight.
- **Requirements:** R5, R34.
- **Dependencies:** U1.
- **Files:** `commands/pf-triage.md`, `skills/triage/SKILL.md` (the scoring rubric), `rules/pf-naming.mdc` (extend with the triage boundary statement).
- **Approach:** Define a deterministic rubric: a file-count / scope estimate, a risk-trigger keyword set (auth, payments, data migration, public API) that is a hard floor forcing ≥Standard, and ambiguity markers that bias upward. Mixed/insufficient signals default to Standard (conservative). Output is the chosen tier + the matched signals (auditable). The manual override is a flag/argument. The misroute re-entry is a documented `/pf-triage` re-run that, given an in-flight Quick item whose scope grew, re-scores and routes it into Standard/Full — so recovery does not depend solely on a human remembering the override.
- **Patterns to follow:** v1 has no triage; model the command/skill split on v1 command frontmatter + `skills/*/SKILL.md`. CE `ce-brainstorm` scope-tier assessment is the conceptual analogue (but deterministic here, not dialogue).
- **Test scenarios:**
  - A trivial single-file change with no risk keyword → Quick.
  - A bounded feature touching several files, no risk keyword → Standard.
  - An auth/payments/data-migration/public-API keyword match → at least Standard regardless of size; a small auth change never lands Quick. Covers origin Success Criteria (triage accuracy).
  - Mixed/ambiguous signals → Standard (conservative default).
  - Manual override forces the named tier and records that it was overridden.
  - Misroute re-entry: a Quick item re-scored after scope growth promotes to Standard/Full.
- **Verification:** Tier assignment is reproducible from the same inputs; risk-triggered items never slip into Quick; the rubric is documented and the matched signals are reported.

### U3. `/pf-brainstorm` collaborative brainstorm stage

- **Goal:** A Full-tier brainstorm command adapting the ce-brainstorm pattern — one-question-at-a-time dialogue, scope-tier assessment, a synthesis checkpoint — that produces a frozen brainstorm requirements doc feeding `/pf-prd`.
- **Requirements:** R6, R30, R31, R34.
- **Dependencies:** U1, U2.
- **Files:** `commands/pf-brainstorm.md`, `skills/brainstorm/SKILL.md`, `skills/brainstorm/references/requirements-sections.md`, `PROVENANCE.md` (record the ce-brainstorm pattern source).
- **Approach:** Re-derive a slim version of the dialogue contract: ask one question per turn (prefer a blocking single-select), investigate before asking on clear inputs, run a synthesis checkpoint that restates scope before writing. Output a requirements doc with stable R-IDs and `frozen`/topic frontmatter matching the existing brainstorm doc shape (the origin doc is the worked example). Full-fidelity authoring (no caveman) per R30/R31. The doc is handed to `/pf-prd`; freezing the brainstorm is done via `/pf-freeze` (U6), not inline.
- **Patterns to follow:** compound-engineering `ce-brainstorm` (dialogue, scope tiers, synthesis checkpoint, requirements-doc sections); the existing `docs/brainstorms/2026-06-22-...-requirements.md` as the output exemplar.
- **Test scenarios:**
  - The command asks one question per turn and does not draft a PRD (pipeline-order guard).
  - Output requirements doc has the required frontmatter and stable R-IDs.
  - Synthesis checkpoint restates scope before any file is written.
  - `Test expectation:` dialogue behavior is verified structurally (command contract + output-doc shape); no automated multi-turn harness.
- **Verification:** A brainstorm run yields a well-formed requirements doc ready for `/pf-prd`; no PRD is produced in this stage.

### U4. `/pf-prd` PRD draft

- **Goal:** Generate a PRD draft from a brainstorm requirements doc (Full) or directly from a triaged Standard request, never before brainstorming concludes on the Full path.
- **Requirements:** R6, R34.
- **Dependencies:** U1, U2, U3.
- **Files:** `commands/pf-prd.md`, `skills/prd/SKILL.md`.
- **Approach:** Port v1 `spec-prd` structure (Overview, Goals, Non-Goals, Requirements with R-IDs, Technical/Security/Testing/Rollout, Decision Log, Open Questions) under `pf-`, writing to `prds/<n>-<slug>/<n>-prd-<slug>.md` per U1. On Full, require a brainstorm doc as input and refuse to draft without one (enforces R6 ordering). On Standard, accept the triaged request directly. Carry forward the brainstorm's R-IDs where present. Do not freeze here; hand off to `/pf-doc-review`. Whether to port v1's GitHub tracking-issue convention is decided in U9/`003` (see Open Questions).
- **Patterns to follow:** v1 `commands/spec-prd.md` (sections, collision/numbering policy, clarifying-question pause).
- **Test scenarios:**
  - Full path refuses to draft when no brainstorm doc is supplied (ordering guard); Standard path drafts directly.
  - PRD is written to the U1 path with the documented sections and stable R-IDs.
  - Re-running for the same feature increments `<n>` rather than overwriting (collision policy).
- **Verification:** A PRD draft lands at the correct path with required sections; Full ordering is enforced.

### U5. `/pf-doc-review` persona panel and synthesizer

- **Goal:** Review a PRD draft with parallel persona sub-agents and a synthesizer that auto-applies safe fixes and surfaces only genuine trade-offs — Full = seven personas, Standard = reduced (coherence + scope-guardian minimum), Quick = none.
- **Requirements:** R7, R8, R28, R29, R30, R31.
- **Dependencies:** U4.
- **Files:** `skills/doc-review/SKILL.md`, `skills/doc-review/references/findings-schema.json`, `skills/doc-review/references/synthesis.md`, `commands/pf-doc-review.md`, `agents/pf-coherence-reviewer.md`, `agents/pf-feasibility-reviewer.md`, `agents/pf-product-reviewer.md`, `agents/pf-scope-guardian-reviewer.md`, `agents/pf-security-reviewer.md`, `agents/pf-design-reviewer.md`, `agents/pf-adversarial-reviewer.md`, `PROVENANCE.md` (record CE `ce-doc-review` + reviewer-agent pattern sources).
- **Approach:** Vendor slim `pf-` adaptations of the seven CE reviewer lenses (one-line role each: coherence, feasibility, product, scope-guardian, security, design, adversarial). Dispatch the tier-selected personas as bounded parallel sub-agents, each receiving the full PRD (no section splitting) so their large reads never enter the orchestrator context (R28/R31). The synthesizer validates findings against the JSON schema, dedups/merges across personas, and routes by an `autofix_class`: `safe_auto` applied silently, `gated_auto` confirmed, `manual` surfaced as a trade-off for the user to decide before freeze (R8). Tier scaling: Full dispatches all seven; Standard dispatches coherence + scope-guardian (the floor) plus any content-triggered persona; Quick is not invoked. The synthesis is a bounded loop with a hard stop (max rounds, no-progress detection) per R29. Personas run at full fidelity (R30).
- **Patterns to follow:** compound-engineering `ce-doc-review` (dispatch, findings schema, synthesis pipeline, safe_auto/gated/manual routing) and the seven `ce-*-reviewer` agent lenses — borrowed as patterns, slimmed, not copied.
- **Test scenarios:**
  - Full dispatches seven personas in parallel; Standard dispatches the coherence + scope-guardian floor; Quick invokes none.
  - A `safe_auto` finding is applied without prompting; a `manual` trade-off is surfaced, not auto-applied. Covers origin R8.
  - A single persona sub-agent failure does not block the panel (partial coverage proceeds).
  - The synthesis loop terminates at its max-round / no-progress hard stop (no infinite run). Covers R29.
  - Findings that fail schema validation are dropped.
- **Verification:** The panel produces a synthesized result with safe fixes applied and trade-offs gated; tier scaling and the hard stop hold.

### U6. `/pf-freeze` freeze-in-depth enforcement

- **Goal:** Make a brainstorm doc, PRD, or task list immutable at handoff, enforced by a `frozen: true` flag, a guardrail rule, a pre-commit hook (installed via a `core.hooksPath` bootstrap), and an authoritative CI required-check — with no unfreeze.
- **Requirements:** R9.
- **Dependencies:** U1, U5.
- **Files:** `commands/pf-freeze.md`, `rules/pf-freeze-guardrail.mdc`, `hooks/pre-commit-frozen.sh`, `scripts/install-hooks.sh` (wires `core.hooksPath`), `scripts/check-frozen.sh` (CI required-check), `.github/workflows/` reference doc or example, `PROVENANCE.md`.
- **Approach:** `/pf-freeze` stamps `frozen: true` + `frozen_at` frontmatter and registers the artifact in `INDEX.md`. The guardrail rule instructs the agent never to edit a `frozen: true` file. The pre-commit hook (installed by a bootstrap that sets `core.hooksPath`) blocks local commits touching a frozen file; it is convenience/early-warning and `--no-verify`-bypassable. `check-frozen.sh` is the non-bypassable authority: a CI required-check that rejects any diff modifying a `frozen: true` file. There is no unfreeze command; the only change path is `/pf-amend` (U7). Document the layering (local = early warning, CI = guarantee) explicitly.
- **Patterns to follow:** the foundation's hook/script conventions (`scripts/*.sh`, `hooks/*`); the foundation's existing CI gate as the model for a required-check.
- **Test scenarios:**
  - Freezing stamps `frozen: true` + `frozen_at` and adds an `INDEX.md` entry.
  - Pre-commit hook blocks a commit that edits a frozen file; `--no-verify` bypasses it (documented as expected).
  - `check-frozen.sh` rejects a diff touching a `frozen: true` file and passes a diff that adds a new amendment file. Covers origin Success Criteria (doc-freeze integrity).
  - No unfreeze path exists (the command surface offers only amend).
  - Credential hygiene: hook/CI output contains no secrets.
- **Verification:** No edit to a frozen artifact survives the CI check; local layers warn early; the only post-freeze change path is an amendment.

### U7. `/pf-amend` sibling amendments with supersede/retract

- **Goal:** Extend or correct a frozen PRD via a separate, reviewed, frozen sibling amendment file — continued R-IDs, typed `supersedes`/`retracts` directives — never editing the parent.
- **Requirements:** R10, R11.
- **Dependencies:** U5, U6.
- **Files:** `commands/pf-amend.md`, `skills/doc-review/SKILL.md` (extend: parent-aware checks), `prds/<n>-<slug>/amendments/` (target layout from U1).
- **Approach:** `/pf-amend` creates `amendments/A<k>-<short>.md` referencing the parent, stating only the delta, with R-IDs continuing the parent namespace (parent R1–R10 → amendment R11+). An amendment may add requirements and/or carry typed directives: `supersedes: R<n>` (a new continued R-ID replaces the named parent requirement) or `retracts: R<n>` (the named parent requirement is dropped, with a recorded rationale). Amendment review scales to the amendment's own triage tier, but coherence + scope-guardian always run against the frozen parent and verify every supersede/retract target exists, isn't already retracted, and records a rationale. An undeclared contradiction/duplication of parent requirements is the amendment-specific failure mode; a declared, reviewed directive is the sanctioned exception. The amendment is then frozen via `/pf-freeze`. The parent file is never modified.
- **Patterns to follow:** the existing `A1-fail-closed-enforcement-point.md` amendment (frontmatter `amends`/`supersedes`, delta-only body) as the worked example; U5's panel for the review step.
- **Test scenarios:**
  - An amendment adds R-IDs continuing the parent namespace; the parent's IDs are untouched.
  - `supersedes: R<n>` introduces a new continued R-ID pointing at the replaced parent ID; `retracts: R<n>` records a rationale.
  - Coherence/scope-guardian reject a supersede/retract whose target does not exist or is already retracted.
  - An undeclared contradiction of a parent requirement is flagged; a declared one passes.
  - The parent file is never written during amend.
- **Verification:** Frozen parents stay byte-stable; corrections and extensions land only as reviewed, frozen amendments with valid directives.

### U8. Precedence-aware spec union resolver

- **Goal:** A single read-time resolver that presents a PRD plus all its amendments as one effective spec — adds, supersedes, and retracts applied in amendment order — for downstream consumers.
- **Requirements:** R12.
- **Dependencies:** U7.
- **Files:** `skills/spec-union/SKILL.md`, `scripts/spec-union.sh` (or equivalent resolver the implementation workstream can call), `prds/` (inputs).
- **Approach:** Implement the resolution: start from the parent PRD's requirements, then apply each amendment in order — add new requirements, replace a `supersedes`d parent R-ID with its replacement, remove a `retracts`d parent R-ID. The parent file is read-only input; every override lives in an amendment. Expose the union both as an agent-readable skill (for `/pf-execute`) and as an executable resolver (for deterministic consumers like gap-check) mirroring the foundation's adapter split. This unit's resolver is the contract the implementation workstream (`003`) consumes; its interface must be stable before `003` builds on it.
- **Patterns to follow:** the foundation's markdown-skill + executable-adapter split (e.g. review seam) for dual consumers.
- **Test scenarios:**
  - Union of a PRD + one amendment that adds R11 yields parent R-IDs plus R11.
  - A `supersedes` resolves the parent R-ID to its replacement in the effective spec; the parent file is unchanged on disk.
  - A `retracts` removes the parent R-ID from the effective spec.
  - Multiple amendments apply in order (a later amendment can supersede an earlier amendment's requirement).
  - Covers origin F3 (implementation reads the PRD + amendments union).
- **Verification:** The effective spec matches the precedence rules for add/supersede/retract; the parent is never mutated; the resolver interface is stable for `003`.

### U9. `/pf-tasks` task-list generation and index registration

- **Goal:** Generate a frozen task list from a frozen PRD (plus its amendment union) and register the PRD into the living index — porting v1's "Go"-gated task expansion under `pf-`.
- **Requirements:** R6, R13 (index registration only).
- **Dependencies:** U6, U8.
- **Files:** `commands/pf-tasks.md`, `skills/tasks/SKILL.md`, `prds/INDEX.md` (register entry).
- **Approach:** Port v1 `spec-tasks`: identify parent tasks (phases, dependencies, S/M/L sizing), pause on the mandatory "Respond with 'Go'" gate, then expand to `- [ ]` sub-tasks + "Relevant Files" + "Notes", reading the U8 union so amended requirements are reflected. Write to the U1 task path and freeze via `/pf-freeze`. On freeze, add/refresh the PRD's entry in `INDEX.md` (parent→amendment links, status `not-started`). The git-derived status reconciliation that keeps the index honest (R14) is built in `003`; this unit only seeds the entry.
- **Patterns to follow:** v1 `commands/spec-tasks.md` (parent-task → "Go" gate → sub-task expansion, Relevant Files/Notes).
- **Test scenarios:**
  - The "Go" gate is mandatory: no sub-tasks are generated until the user confirms.
  - The task list reflects amended requirements (reads the U8 union, not the bare parent).
  - Freezing the task list registers/refreshes the PRD entry in `INDEX.md` with status `not-started`.
- **Verification:** A frozen task list exists for the PRD and an index entry is registered; the "Go" gate holds.

### U10. `/pf-doc` orchestrator

- **Goal:** A single documentation orchestrator that chains brainstorm → PRD → persona panel → freeze → tasks with tier gating, while each atomic command stays independently runnable.
- **Requirements:** R6, R34.
- **Dependencies:** U2, U3, U4, U5, U6, U9.
- **Files:** `commands/pf-doc.md`, `rules/pf-naming.mdc` (extend: orchestrator-vs-atomic boundary for the doc surface).
- **Approach:** `/pf-doc` reads the triage tier and runs the appropriate stages: Full runs all stages in order; Standard skips brainstorm and runs the reduced panel; Quick is not entered (it routes to implementation). The orchestrator delegates to the atomic commands (U2–U9) rather than reimplementing them, halting on any blocker or gated trade-off. Its description states the full chain and which atomic commands it subsumes (R34 description contract).
- **Patterns to follow:** v1 `commands/ship.md` as the orchestrator-that-delegates-to-atomic-commands model; `pf-naming` description contract.
- **Test scenarios:**
  - Full runs brainstorm→PRD→panel→freeze→tasks in order; Standard skips brainstorm and uses the reduced panel; Quick is not entered.
  - The orchestrator halts at a gated trade-off rather than auto-deciding.
  - Each subsumed atomic command remains runnable on its own.
- **Verification:** The orchestrator drives the pipeline per tier and stops at human-judgment gates; atomic commands are unaffected when run directly.

---

## Open Questions

- **GitHub tracking-issue carryover.** v1 opens a tracking issue per PRD with a `## Relationships` block. Whether v2 carries this over (and how it links to the living index) is a genuine fork shared with the implementation workstream's R14 status-derivation function — the origin defers it to planning. Resolve jointly with `003` before U9 hard-codes any issue convention; default if undecided is to skip the GitHub issue and let the index + git be the status source.
- **Persona set minimality.** Seven personas mirror CE, but a slimmer set may suffice for this product. The plan vendors all seven; pruning is a post-build optimization, not a blocker.

---

## Scope Boundaries

### Deferred to sibling/later plans

- Git-derived living-status reconciliation (R14) and the completion-log append on ship — implementation workstream (`003`). This plan seeds `INDEX.md`/`COMPLETION-LOG.md` and registers entries on freeze only.
- The worktree phase loop, `/pf-ship`, retrospective, and compounding (R15–R21, R33) — implementation workstream (`003`).
- Debugging and feedback workstreams (R22–R27) — Phase 2 (`004`, `005`).

### Outside this product's identity (from origin)

- A composition that depends on compound-engineering being installed at runtime — the brainstorm and persona patterns are vendored slim, not imported.
- Implementing the workstreams' runtime behavior beyond the documentation pipeline.

---

## Risks & Dependencies

- **Triage classifier reliability is load-bearing.** A misclassification that lands risk-triggered work in Quick defeats the tiering. *Mitigation:* risk triggers are a hard floor over the score, the default is conservative (Standard), and U2's test suite asserts the risk-trigger and ambiguity cases; the misroute re-entry recovers in-flight scope growth.
- **Persona-panel context cost.** Seven parallel sub-agents each reading a full PRD is token-heavy. *Mitigation:* sub-agent isolation keeps their reads out of the orchestrator (the dominant token lever per origin R31); tier scaling means only Full pays for all seven.
- **Pattern re-derivation drift.** Vendoring CE patterns slim risks diverging from upstream improvements. *Mitigation:* `PROVENANCE.md` records the borrowed pattern sources; the deferred `/pf-upstream` (R40) surfaces drift later.
- **Freeze CI-check dependency.** Doc-freeze integrity depends on the CI required-check actually being required on the branch. *Mitigation:* U6 ships the check + an install/bootstrap path and documents that the CI layer is the only authority; local hooks are early-warning.
- **Union resolver is a cross-plan dependency.** `003`'s phase-execute and gap-check consume U8. *Mitigation:* freeze U8's interface early and treat it as a published contract.

---

## Sources & Research

Internal (vendored / ported — recorded in `PROVENANCE.md` per R40):

- phase-flow v1 (`cursor-phase-flow`): `commands/spec-prd.md`, `commands/spec-tasks.md` (PRD + "Go"-gated task pipeline), `commands/ship.md` (orchestrator-delegates-to-atomic pattern), command/skill structure.
- compound-engineering: `ce-brainstorm` (dialogue + scope tiers + synthesis checkpoint), `ce-doc-review` (parallel persona dispatch, findings schema, safe_auto/gated/manual synthesis) and the seven `ce-*-reviewer` agent lenses — borrowed as patterns, slimmed, not copied.

Origin requirements: `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` (frozen) and amendment `A1`. Foundation: `docs/plans/2026-06-22-001-feat-plugin-foundation-infrastructure-plan.md` (shipped, PR #1). Prior decisions: Recallium memories #2003 (triage + documentation workflow shape), #1999 (fresh prefixed plugin).
