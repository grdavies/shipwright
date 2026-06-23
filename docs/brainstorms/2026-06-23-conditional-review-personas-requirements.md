---
date: 2026-06-23
topic: conditional-review-personas
---

# Conditional Review-Persona Selection

## Summary

Replace tier-driven review-panel selection with a **signal-driven** model: every non-Quick review runs a fixed
**always-on core** plus **deterministic, signal-gated specialists**, and each activation is logged with the
signal that triggered it. This removes the current "Full tier loads all seven personas" behavior in
doc-review, gates the two personas that have crisp signals (`security`, `design`), keeps the rest always-on
(because their triggers are inherently semantic and resist deterministic gating), and records the same
always-on-core + signal-gated rule as the standard the code-review panel must follow. Selection stays
deterministic and auditable — same inputs produce the same panel — with a logged `--personas`/`--all` override
for deliberate deep audits.

## Problem Frame

phase-flow runs parallel sub-agent "review teams" at two stages: pre-implementation document review
(`/pf-doc-review` + `skills/doc-review`, over `agents/pf-*-reviewer.md`) and code review during implementation
(`/pf-review` phase 1, via the `ce-code-review` adapter). The concern raised: the teams load all personas
rather than conditioning on the change.

Grounding the premise against the code shows it is **partly true**:

- **Doc review is already partly conditional, but not at Full tier.** `skills/doc-review/SKILL.md` scales by
  triage tier: **Full = all seven** (coherence, feasibility, product, scope-guardian, security, design,
  adversarial); **Standard = coherence + scope-guardian floor + content-triggered extras**; **Quick = none**.
  So at Standard it already content-triggers `security`/`design`/etc., but at **Full it force-loads every
  persona regardless of the change** — the over-loading the concern is about. A Full-tier doc with no UI still
  gets `design`; with no auth surface still gets `security`.
- **Code review already conditions on content.** The `ce-code-review` adapter (from the local-code-review
  workstream) selects personas by diff content internally — 4 always-on + conditional cross-cutting
  (security, performance, api-contract, data-migration, reliability) + stack-specific. No "load all" path.

So the actionable pf-owned gap is the **doc-review panel's Full-tier all-on behavior**, plus codifying the
selection rule so the (deferred) `native` code panel inherits it.

**How compound engineering behaves (the explicit question).** CE never force-loads everything. Both review
skills use a small always-on core + content-conditional specialists, selected by **agent judgment on the
actual change, not keyword matching**:

- `ce-doc-review`: always-on `coherence` + `feasibility`; conditional `product-lens`, `design-lens`,
  `security-lens`, `scope-guardian`, `adversarial` activated by document content signals. Even a large doc only
  gets the personas whose signals fire.
- `ce-code-review`: 4 always-on + 2 CE agents + conditional cross-cutting + stack-specific, gated on diff
  content — *"the model naturally right-sizes."*

phase-flow adopts CE's **always-on-core + conditional-specialist** shape, but keeps selection **deterministic**
(not judgment) to preserve its auditable "same inputs → same panel" identity.

## Key Decisions

- **Selection is deterministic, not judgment-based (Q1).** Personas activate on auditable signals (file globs,
  risk keywords, structural markers), so the same change always yields the same panel. This diverges from CE
  (which uses orchestrator judgment) deliberately: phase-flow's triage is explicitly "same inputs → same tier…
  not model judgment," and persona selection inherits that property. Selection logic extends the existing
  `pf-triage` signal rubric rather than introducing a parallel judgment layer.
- **Tier no longer selects personas; it only decides whether review runs (Q2).** The Quick/Standard/Full tier
  stops choosing the panel. **Quick still skips review entirely;** any non-Quick review runs the same
  signal-driven panel. The old `Full = all seven` rule is removed. (Tier remains meaningful elsewhere — routing,
  doc pipeline — just not for persona selection.)
- **Always-on core for the doc panel: `coherence` + `feasibility` + `scope-guardian` (Q3), extended with
  `product` + `adversarial` (Q4).** The core is the set whose concerns are either universal or resist clean
  deterministic gating. `coherence` (internal consistency), `feasibility` (will it survive contact with
  reality), and `scope-guardian` (scope discipline — a standing risk given the plugin's freeze model) are
  universal. `product` (challengeable premise / strategic weight) and `adversarial` (new abstraction / scope
  extension) are **inherently semantic** — CE fires them on judgment — so rather than encode fragile keyword
  proxies, they run **always**. Net core = five personas.
- **Only `security` and `design` are signal-gated (consequence of Q4).** These are the two doc personas with
  crisp, auditable signals, so they are the only ones gated. This is the elegant resolution of the
  deterministic-vs-semantic tension: everything hard to gate runs always; only clean-signal specialists gate.
- **Code review conforms; the rule is shared (Q2 scope).** The `ce-code-review` adapter already selects by diff
  content and needs no change. This requirements doc records **always-on-core + deterministic signal-gated
  specialists** as the standard the deferred `native` code panel must implement when built.
- **Every activation is logged with its trigger; a logged override exists (Q5).** Each review reports which
  personas ran and, for gated ones, which signal fired (and for always-on, that they are core). A
  `--personas <list>` / `--all` override lets a human force-add personas or run a full deep-audit panel; the
  override and its reason are recorded, preserving auditability. Mirrors `pf-triage`'s existing `--tier`
  override.

## Selection Model

### Doc-review panel

| Persona | Activation | Signal (deterministic) |
| --- | --- | --- |
| `coherence` | always-on (core) | — |
| `feasibility` | always-on (core) | — |
| `scope-guardian` | always-on (core) | — |
| `product` | always-on (core) | — (semantic trigger → promoted to core) |
| `adversarial` | always-on (core) | — (semantic trigger → promoted to core) |
| `security` | signal-gated | auth, authn, authz, login, session, oauth, jwt, payment, billing, PII, credentials, token, encryption, public-api / external-api, webhook |
| `design` | signal-gated | UI/UX, component, screen, page, view, form, button, modal, navigation, wireframe, user flow, responsive, accessibility |

- **Quick tier:** no panel (unchanged).
- **Non-Quick:** the five core personas + any gated persona whose signal fires.
- Security signals reuse the `pf-triage` risk-trigger list, so triage and persona selection share one keyword
  source of truth.

### Code-review panel

- **No change** — `ce-code-review` selects by diff content (4 always-on + conditional). Conforms to the rule.
- **`native` panel (deferred):** when built, it MUST follow always-on-core + deterministic signal-gated
  specialists, mirroring this doc panel's shape with a code-appropriate roster.

### Auditability & override

- Each review emits an activation record: core personas listed as core; gated personas listed with the
  matched signal; skipped gated personas optionally noted. Deterministic ⇒ reproducible.
- `--personas <a,b,...>` force-adds named personas; `--all` runs the full roster (deep audit). The override and
  its reason are recorded in the activation record. Selection is otherwise fully automatic.

## Scope Boundaries

### In scope

- Rewrite `skills/doc-review/SKILL.md` selection: remove tier-based panel scaling and the `Full = all seven`
  rule; define the five-persona core + `security`/`design` signal gates; add the activation-record log and the
  `--personas`/`--all` override.
- Update `commands/pf-doc-review.md` to match (description + dispatch wording; tier no longer picks personas).
- Reuse the `pf-triage` risk-trigger keyword list for `security` gating (single source of truth).
- Record the always-on-core + signal-gated rule as binding on the future `native` code panel.

### Out of scope / deferred

- Building the `native` code-persona panel (still deferred from the local-code-review workstream; it only
  inherits the rule here).
- Any change to `ce-code-review`'s internal persona selection.
- ML/embedding-based or judgment-based selection (explicitly rejected in favor of deterministic signals).
- Changing triage tiers themselves, or tier's role in routing / the doc pipeline.

## Open Questions

- **Design-signal precision.** `design` keywords (e.g. "view", "page", "form") risk false positives in
  non-UI docs. Resolve during planning: scope the signals to UI-context phrases or require ≥2 matches.
- **Activation-record surface.** Whether the activation log is inline in the review report only, or also
  persisted (e.g. to phase state) for later audit — tie to the existing review-report format.

## Sources & Research

- phase-flow v2: `skills/doc-review/SKILL.md` (tier scaling + content triggers), `commands/pf-doc-review.md`,
  `skills/triage/SKILL.md` (deterministic tier rubric + risk triggers), `agents/pf-*-reviewer.md` (the seven
  doc personas), and the local-code-review spec
  (`docs/brainstorms/2026-06-23-local-code-review-loop-integration-requirements.md`) for the `ce-code-review`
  adapter's content-conditional selection.
- compound-engineering: `ce-doc-review` (always-on coherence+feasibility + content-conditional lenses) and
  `ce-code-review` (always-on core + diff-conditional roster, "the model naturally right-sizes").
