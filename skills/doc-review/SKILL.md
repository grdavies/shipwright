---
name: pf-doc-review
description: Review PRD drafts with parallel persona sub-agents and a synthesizer that auto-applies safe fixes. Signal-driven panel (five-persona core + gated security/design); Quick tier skips review.
---

# Document review (`/pf-doc-review`)

Multi-persona PRD review. Pattern borrowed from compound-engineering `ce-doc-review` (slim vendored adaptation).

## Tier gate (review runs or not)

| Tier | Panel |
|------|-------|
| Quick | None — do not invoke |
| Standard / Full | Signal-driven panel (see Selection) |

**Tier no longer selects personas** — only whether review runs. Quick skips; any non-Quick review uses the
same signal-driven panel. There is no `Full = all seven` path.

## Selection

Deterministic — same inputs → same panel. Not model judgment.

### Always-on core (non-Quick)

These five personas run on every non-Quick review:

- `pf-coherence-reviewer`
- `pf-feasibility-reviewer`
- `pf-scope-guardian-reviewer`
- `pf-product-reviewer`
- `pf-adversarial-reviewer`

### Signal-gated specialists

| Persona | Fires when |
| --- | --- |
| `pf-security-reviewer` | Any **`security`-tagged** keyword from `skills/triage/SKILL.md` "Risk triggers" matches the PRD (case-insensitive). Tags `data-migration` and `billing-routing` floor triage tier but do **not** fire security. |
| `pf-design-reviewer` | **Either** (a) one **unambiguous** UI term is present (`UI`, `UX`, `wireframe`, `modal`, `button`, `navigation`, `responsive`, `accessibility`, `user flow`), **or** (b) a **structural UI signal** exists: a `UI` / `UX` / `Screens` / `Mockups` section heading, a design-tool link (e.g. Figma), or an explicit interaction-state enumeration. Bare polysemous tokens (`component`, `view`, `page`, `form`) do **not** count alone. |

**Security signal enumeration** (authoritative; must stay in sync with triage `security` tags):

`auth`, `authn`, `authz`, `authentication`, `authorization`, `login`, `session`, `oauth`, `jwt`, `payment`,
`payments`, `billing`, `PII`, `credentials`, `token`, `encryption`, `public api`, `public endpoint`,
`external api`, `webhook`

Keyword-gated security accepts deliberate false-negative cost on novel phrasing; use `--personas security` for
audits when wording dodges the list.

### Selection algorithm

```
1. If tier is Quick → no panel; stop.
2. Start with always-on core (five personas).
3. Scan PRD text + headings for gated signals (case-insensitive, whole-token match — delimiter-bounded;
   plural inflections do not match unless listed, e.g. `webhooks` ≠ `webhook`).
4. Add each gated persona whose signal fires; record matched signal.
5. If --personas <list> → force-add named personas; record override reason.
6. If --all → run full roster (all seven); record override reason.
7. Emit activation record (below).
```

### Overrides

- `--personas <comma-separated>` — force-add named personas (e.g. `security,design`). Record
  `override: personas <list>` with reason.
- `--all` — run all seven personas (deep audit). Record `override: all`.

Mirrors `pf-triage` `--tier` override recording.

### Activation record

Emit at start of every review (inline in the review report):

```text
Persona activation:
  core: coherence, feasibility, scope-guardian, product, adversarial
  gated:
    - security: matched "<signal>" (if fired)
    - design: matched "<signal>" (if fired)
  skipped_gated: [list gated personas not fired] (optional)
  override: <none|personas <list>|all>
```

## Dispatch

1. If input is an amendment draft (`amendments/A<k>-*.md`), run **coherence** + **scope-guardian** only per
   Amendment review (U7) — skip the full selection algorithm unless `--personas` / `--all` override.
2. Resolve tier — if Quick, report "no panel for Quick" and stop.
3. Run selection algorithm; announce activation record (core + any fired gates + matched signals).
4. Read full PRD (no section splitting) — each selected persona is a parallel sub-agent (R28/R31).
5. Each agent returns JSON per `references/findings-schema.json`.
6. Synthesizer follows `references/synthesis.md`.
7. Apply `safe_auto` silently; gate `gated_auto` and `manual`.

## Amendment review (U7)

When reviewing `amendments/A<k>-*.md` drafts:

- **coherence** + **scope-guardian** always run against the frozen parent (read-only) — not the full
  signal-driven panel.
- Verify every `supersedes`/`retracts` target exists in the parent effective spec.
- Reject targets already retracted; require rationale for each retract.
- Flag undeclared contradictions with parent requirements; declared directives are the sanctioned path.
- Never edit the parent file — fixes apply only to the amendment draft.

## Handoff

→ `/pf-freeze` when no blocking manual trade-offs remain.
