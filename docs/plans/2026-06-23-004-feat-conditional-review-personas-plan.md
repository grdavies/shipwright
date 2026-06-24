---
title: "feat: Conditional (signal-driven) review-persona selection"
type: feat
date: 2026-06-23
origin: docs/brainstorms/2026-06-23-conditional-review-personas-requirements.md
status: planned
depth: standard
branch: ""
commit: ""
pr: ""
---

# feat: Conditional (signal-driven) review-persona selection

Replace doc-review's tier-driven panel selection (`Full = all seven`) with a **signal-driven** model: every
non-Quick review runs a fixed five-persona **always-on core** plus **deterministic, signal-gated** specialists
(`security`, `design`), with each activation logged and a `--personas`/`--all` override for deep audits.
Selection stays deterministic — same inputs → same panel. Code review already conforms (no change); this plan
records the always-on-core + signal-gated rule as binding on the future `native` code panel.

## Implementation Units

| Unit | Status | Summary |
| --- | --- | --- |
| U1 | planned | Rewrite `skills/doc-review` selection: 5-persona core + `security`/`design` gates + activation log + override |
| U2 | planned | Update `commands/pf-doc-review.md` to match (tier no longer picks personas) |
| U3 | planned | Extend `skills/triage` risk list as the single security-signal source; define `design` signal precision |
| U4 | planned | Record always-on-core + signal-gated rule as binding on the future `native` code panel |
| U5 | planned | Structural fixtures: core always present, gates fire/skip, override logged, Quick still skips |

**Verification:** structural fixtures under `scripts/test/` (persona-selection cases), registered into
`.cursor/workflow.config.json` → `verify.test`.

---

## Summary

phase-flow runs parallel sub-agent review teams at two stages: pre-implementation **document** review
(`/pf-doc-review` + `skills/doc-review` over `agents/pf-*-reviewer.md`) and **code** review (`/pf-review`
phase 1 via the `ce-code-review` adapter). Grounding the concern against the code shows the actionable gap is
narrow:

- **Doc review force-loads at Full tier.** `skills/doc-review/SKILL.md` scales by triage tier — **Full = all
  seven** personas regardless of content; Standard = a floor + content-triggered extras; Quick = none. A
  Full-tier doc with no UI still gets `design`; with no auth surface still gets `security`. That all-on
  behavior is the over-loading to fix.
- **Code review already conditions on content.** The `ce-code-review` adapter selects personas by diff content
  (always-on core + conditional). No "load all" path — no change needed.

This plan adopts compound-engineering's **always-on-core + conditional-specialist** shape for the doc panel,
but keeps selection **deterministic** (auditable signals: file globs, risk keywords, structural markers) to
preserve phase-flow's "same inputs → same panel" identity — diverging from CE's orchestrator-judgment model on
purpose. Tier stops choosing the panel (Quick still skips review entirely; any non-Quick review runs the same
signal-driven panel). The rule is recorded as binding on the deferred `native` code panel.

---

## Problem Frame

`skills/doc-review/SKILL.md` today:

| Tier | Personas |
| --- | --- |
| Full | All seven: coherence, feasibility, product, scope-guardian, security, design, adversarial |
| Standard | coherence + scope-guardian floor + content-triggered extras |
| Quick | none |

So at Standard it already content-triggers `security`/`design`/etc., but at **Full it force-loads every
persona** — the over-loading the concern targets. `commands/pf-doc-review.md` mirrors this ("Full tier: seven
personas in parallel").

The resolution from the origin: most personas are **inherently semantic** and resist clean deterministic
gating (`coherence`, `feasibility`, `scope-guardian` are universal; `product` and `adversarial` fire on
judgment in CE), so rather than encode fragile keyword proxies they run **always** — a five-persona core. Only
`security` and `design` have crisp, auditable signals, so they are the only gated personas. Security signals
reuse the `pf-triage` risk-trigger list (`skills/triage/SKILL.md`) so triage and persona selection share one
keyword source of truth — but that list is currently narrower than the origin's security signal set (it lacks
PII/credentials/token/encryption), so this plan extends it.

---

## Requirements Traceability

Origin decisions Q1–Q5 (`docs/brainstorms/2026-06-23-conditional-review-personas-requirements.md`).

| Origin decision | Units |
| --- | --- |
| Q1 deterministic, signal-based selection (not judgment) | U1, U3 |
| Q2 tier no longer selects personas (Quick still skips) | U1, U2 |
| Q3 core = coherence + feasibility + scope-guardian | U1 |
| Q4 core extended with product + adversarial (net five) | U1 |
| Q4 consequence: only security + design gated | U1, U3 |
| Q2-scope: code review conforms; rule shared | U4 |
| Q5 activation logged; `--personas`/`--all` override | U1 |

---

## Key Technical Decisions

**KTD1 — Selection is deterministic, not judgment-based.** Personas activate on auditable signals (file globs,
risk keywords, structural markers) so the same change always yields the same panel. This diverges from CE
(orchestrator judgment) deliberately — phase-flow triage is explicitly "same inputs → same tier, not model
judgment," and persona selection inherits that property. Selection extends the existing `pf-triage` signal
rubric rather than introducing a parallel judgment layer.

**KTD2 — Tier no longer selects personas; it only decides whether review runs.** Quick still skips review
entirely; any non-Quick review runs the same signal-driven panel. The `Full = all seven` rule is removed.
Tier remains meaningful elsewhere (routing, doc pipeline) — just not for persona selection.

**KTD3 — Five-persona always-on core; only `security` and `design` gated.** Core =
`coherence` + `feasibility` + `scope-guardian` (universal) + `product` + `adversarial` (inherently semantic →
promoted to always-on rather than gated on fragile keyword proxies). The two personas with crisp signals
(`security`, `design`) are the only gated ones — the elegant resolution of the deterministic-vs-semantic
tension: everything hard to gate runs always; only clean-signal specialists gate.

**KTD4 — Security signals are single-sourced from `pf-triage`; the list is extended there.** The `security`
gate reuses `skills/triage/SKILL.md`'s risk-trigger keywords so there is one source of truth. Because the
origin's security signal set is broader than triage's current list (adds PII, credentials, token, encryption
alongside the existing auth/session/oauth/jwt/payment/webhook), U3 **extends the triage list** rather than
maintaining a doc-review-only superset. Triage's existing consumers (tier flooring) benefit from the broader
list too.

**KTD5 — `design` is gated with precision to curb false positives.** Bare keywords like "view"/"page"/"form"
false-positive in non-UI docs. The `design` gate requires **≥2 UI-context matches** (or a scoped UI-context
phrase) before activating. Exact signal scoping decided in U1/U3 (see Open Questions).

**KTD6 — Every activation is logged; a logged override exists.** Each review emits an activation record: core
personas listed as core; gated personas listed with the matched signal; skipped gated personas optionally
noted. `--personas <list>` force-adds named personas; `--all` runs the full roster (deep audit). The override
and its reason are recorded, preserving auditability — mirroring `pf-triage`'s `--tier` override.

**KTD7 — Code review conforms; the rule is recorded, not re-implemented.** The `ce-code-review` adapter
already selects by diff content and needs no change. This plan records always-on-core + deterministic
signal-gated specialists as the standard the deferred `native` code panel must implement when built — it does
not build that panel.

---

## Selection Model

### Doc-review panel (after this plan)

| Persona | Activation | Signal (deterministic) |
| --- | --- | --- |
| `coherence` | always-on (core) | — |
| `feasibility` | always-on (core) | — |
| `scope-guardian` | always-on (core) | — |
| `product` | always-on (core) | — (semantic → promoted to core) |
| `adversarial` | always-on (core) | — (semantic → promoted to core) |
| `security` | signal-gated | `pf-triage` risk-trigger list (extended): auth, authn, authz, login, session, oauth, jwt, payment, billing, PII, credentials, token, encryption, public/external API, webhook |
| `design` | signal-gated | ≥2 UI-context matches: UI/UX, component, screen, page, view, form, button, modal, navigation, wireframe, user flow, responsive, accessibility |

- **Quick tier:** no panel (unchanged).
- **Non-Quick:** the five core personas + any gated persona whose signal fires.

### Code-review panel

- **No change** — `ce-code-review` selects by diff content and conforms.
- **`native` panel (deferred):** when built, MUST follow always-on-core + deterministic signal-gated
  specialists, mirroring the doc panel shape with a code-appropriate roster (recorded in U4).

---

## Implementation Units

Suggested build order: **U3 (triage signal source) → U1 (doc-review selection) → U2 (command) → U4 (recorded
rule) → U5 (fixtures)**. U3 first so U1's `security` gate references the single extended source.

### U3. Extend `pf-triage` risk list as the single security-signal source; define `design` precision

- **Goal:** One keyword source of truth for `security` gating, broadened to the origin's set, plus a
  precise `design` signal definition.
- **Requirements:** Q1, Q4 (gated security); honors triage's deterministic identity.
- **Dependencies:** none.
- **Files:**
  - `skills/triage/SKILL.md` (modify) — extend the "Risk triggers" list with PII, credentials, token,
    encryption (and `authn`/`authz` aliases) so triage flooring and persona gating share it.
  - `skills/doc-review/SKILL.md` (modify) — reference the triage list for `security`; define the `design`
    signal as ≥2 UI-context matches from the listed phrases.
- **Approach:** Keep triage's existing behavior (any match → floor Standard) intact; the list extension only
  broadens what triggers, which is consistent with its risk intent. The `design` precision rule lives in the
  doc-review skill (design is not a triage routing concern).
- **Patterns to follow:** `skills/triage/SKILL.md` "Risk triggers" section.
- **Test scenarios:**
  - `Covers Q4.` A doc mentioning "PII" or "credentials" now matches the security signal (previously did not).
  - Triage regression: existing risk keywords still floor to Standard; the extension does not change tier math
    for previously-matching inputs.
  - `design` precision: a single "view" mention does **not** fire `design`; two UI-context matches do.
- **Verification:** triage + signal fixtures pass; security list is single-sourced.

### U1. Rewrite `skills/doc-review` selection

- **Goal:** Replace tier-based panel scaling with the five-persona core + `security`/`design` gates, an
  activation record, and the `--personas`/`--all` override.
- **Requirements:** Q1, Q2, Q3, Q4, Q5.
- **Dependencies:** U3 (security signal source).
- **Files:**
  - `skills/doc-review/SKILL.md` (modify) — remove the tier-scaling table and the `Full = all seven` rule;
    define the always-on core (coherence, feasibility, scope-guardian, product, adversarial); define the
    `security`/`design` gates (signals from U3); add the activation-record format (core listed as core; gated
    listed with matched signal; skipped gated optionally noted); add the `--personas`/`--all` override with
    recorded reason. Keep Quick = no panel and the amendment-review behavior (coherence + scope-guardian vs
    frozen parent) intact.
  - `scripts/test/fixtures/persona-selection/*` (new) — docs with/without security signals, with/without
    design signals, override cases.
- **Approach:** Selection becomes: if Quick → no panel; else core (always) + each gated persona whose signal
  fires. The activation record is deterministic and reproducible. The override is logged like `pf-triage
  --tier`. Synthesis/apply flow (`references/synthesis.md`, `safe_auto`) is unchanged.
- **Patterns to follow:** `skills/doc-review/SKILL.md` current dispatch + amendment sections;
  `skills/triage/SKILL.md` override-recording pattern.
- **Test scenarios:**
  - `Covers Q3 / Q4.` A non-Quick doc with no security/design signals → exactly the five core personas.
  - `Covers Q4.` A doc with an auth signal → core + `security`; a doc with ≥2 UI signals → core + `design`.
  - `Covers Q2.` Quick → no panel; a former "Full" doc no longer force-loads all seven (only core + fired
    gates).
  - `Covers Q5.` `--personas security,design` force-adds them with a recorded reason; `--all` runs the full
    roster; the activation record lists core-as-core and gated-with-signal.
- **Verification:** persona-selection fixtures pass; no path force-loads all seven; activation record present.

### U2. Update `commands/pf-doc-review.md` to match

- **Goal:** The command description and dispatch wording reflect signal-driven selection (tier no longer
  picks personas).
- **Requirements:** Q2.
- **Dependencies:** U1.
- **Files:**
  - `commands/pf-doc-review.md` (modify) — replace "Full tier: seven personas in parallel" /
    "Standard: coherence + scope-guardian minimum" guardrails with the core + signal-gated model; update the
    description and the dispatch step (announce core personas + any fired gates and the matched signal); keep
    "Quick → no panel" and the schema-drop / synthesis-loop guardrails.
- **Approach:** Documentation/dispatch-wording change tracking U1; behavior lives in the skill. Announce
  selected personas and the signals that fired (auditability surfaced to the user).
- **Patterns to follow:** `commands/pf-doc-review.md` current Procedure/Guardrails.
- **Test scenarios:**
  - `Covers Q2.` Structural: the command no longer references tier-based persona counts; it references the
    core + signal-gated model and the activation announcement.
- **Verification:** structural grep confirms the command matches the new model.

### U4. Record the rule as binding on the future `native` code panel

- **Goal:** Persist the always-on-core + deterministic signal-gated standard so the deferred `native` code
  panel inherits it when built.
- **Requirements:** Q2-scope (shared rule); honors the local-code-review workstream's `native` deferral.
- **Dependencies:** none (independent of U1; can land anytime).
- **Files:**
  - `rules/code-review-automation.mdc` (modify) — add a binding note: any future `native` code-review panel
    MUST use always-on-core + deterministic signal-gated specialists (mirroring the doc panel), with a
    code-appropriate roster; `ce-code-review` already conforms and is unchanged.
- **Approach:** Record-only. Placed in `rules/code-review-automation.mdc` (provider-independent) so it holds
  regardless of whether the local-code-review plan (003) has landed `providers/code-review/` yet.
- **Patterns to follow:** existing binding notes in `rules/code-review-automation.mdc`.
- **Test scenarios:** `Test expectation: none -- documentation-only.` Structural grep (U5): the rule records
  the always-on-core + signal-gated standard for the native panel.
- **Verification:** the rule states the binding standard.

### U5. Structural fixtures

- **Goal:** Lock the selection behavior with structural fixtures.
- **Requirements:** advances Q1–Q5 verification.
- **Dependencies:** U1–U4.
- **Files:**
  - `scripts/test/run-persona-selection-fixtures.sh` (new) — runner over the persona-selection cases + the
    structural greps for the command and the recorded rule.
  - `.cursor/workflow.config.json` / `config/workflow.config.example.json` (modify) — register under
    `verify.test`.
- **Approach:** Follow the established workstream test convention (structural greps + fixture-driven cases),
  mirroring `scripts/test/run-improvement-fixtures.sh`.
- **Patterns to follow:** `scripts/test/run-improvement-fixtures.sh`.
- **Test scenarios:**
  - Core-always: every non-Quick fixture yields the five core personas.
  - Gates: security fires on the extended signal list; design requires ≥2 UI matches; Quick skips.
  - Override + activation record present; runner wired into `verify.test`.
- **Verification:** aggregated runner passes; registered under `verify.test`.

---

## Scope Boundaries

### In scope

- Rewrite `skills/doc-review/SKILL.md` selection (remove tier scaling + `Full = all seven`; five-persona core
  + `security`/`design` gates; activation record; `--personas`/`--all` override).
- Update `commands/pf-doc-review.md` to match.
- Extend the `pf-triage` risk-trigger list as the single security-signal source; define `design` precision.
- Record the always-on-core + signal-gated rule as binding on the future `native` code panel.

### Outside this plan

- Building the `native` code-persona panel (still deferred from the local-code-review workstream; it only
  inherits the rule here).
- Any change to `ce-code-review`'s internal persona selection.
- ML/embedding-based or judgment-based selection (explicitly rejected in favor of deterministic signals).
- Changing triage tiers themselves, or tier's role in routing / the doc pipeline.

---

## Open Questions

- **Design-signal precision (U1/U3).** Whether ≥2 UI-context matches is the right threshold or whether to
  scope to UI-context phrases (e.g. "user flow", "responsive layout") — tune against fixtures to avoid
  false positives in non-UI docs.
- **Activation-record surface (U1).** Whether the activation log is inline in the review report only, or also
  persisted (e.g. to phase state) for later audit — tie to the existing review-report format.

---

## Risks & Dependencies

- **Under-firing security.** A signal-gated `security` persona could miss a security-relevant doc whose
  wording dodges the keyword list; mitigated by the broadened single-source list (U3) and the `--personas`
  override for deliberate audits.
- **Design false positives.** Bare UI keywords false-positive in non-UI docs; mitigated by the ≥2-match
  precision rule (KTD5).
- **Cross-plan coupling.** U4's recorded rule references the `native` panel from the local-code-review
  workstream (plan 003); placing it in `rules/code-review-automation.mdc` keeps it valid regardless of 003's
  status.

---

## Sources & Research

- Origin: `docs/brainstorms/2026-06-23-conditional-review-personas-requirements.md` (Q1–Q5, selection model,
  always-on-core resolution).
- Repo grounding (this session): `skills/doc-review/SKILL.md` (tier scaling + `Full = all seven`),
  `commands/pf-doc-review.md` (tier-based guardrails), `skills/triage/SKILL.md` (deterministic risk-trigger
  list), `agents/pf-*-reviewer.md` (the seven doc personas).
- Related plan: `docs/plans/2026-06-23-003-feat-local-code-review-loop-plan.md` (the `native` panel deferral
  this rule binds).
- compound-engineering: `ce-doc-review` (always-on coherence+feasibility + content-conditional lenses),
  `ce-code-review` (always-on core + diff-conditional roster).
