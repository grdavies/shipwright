---
name: sw-doc-review
description: Review PRD drafts with parallel persona sub-agents and a synthesizer that auto-applies safe fixes. Signal-driven panel (five-persona core + gated security/design); Quick tier skips review.
---

# Document review (`/sw-doc-review`)

Multi-persona review for PRDs and decision records. Pattern borrowed from compound-engineering `ce-doc-review` (slim vendored adaptation).


**Model tier:** inherit — runtime parent floor (R9); `resolve-model-tier.sh --skill doc-review` returns inherit with `modelId: null`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Doc types

| Doc type | Path pattern | Panel |
|----------|--------------|-------|
| PRD draft | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | Signal-driven (see Selection) |
| Decision-record draft | `docs/decisions/<n>-<slug>.md` | **Full** — all seven personas |
| PRD amendment | `docs/prds/<n>-<slug>/amendments/A<k>-*.md` | Coherence + scope-guardian |
| Decision amendment | `docs/decisions/<n>-<slug>.amendments/A<k>-*.md` | Raised floor (see Decision amendment review) |

## Tier gate (review runs or not)

| Tier | Panel |
|------|-------|
| Quick | None — do not invoke |
| Standard / Full | Per doc type above |

**PRD tier no longer selects personas** — only whether review runs. Quick skips; PRD reviews use signal-driven
selection. **Decision-record drafts always use the Full panel** (all seven) regardless of tier, because they
govern multiple plans by definition.

## Selection

Deterministic — same inputs → same panel. Not model judgment.

### Always-on core (non-Quick)

These five personas run on every non-Quick review:

- `sw-coherence-reviewer`
- `sw-feasibility-reviewer`
- `sw-scope-guardian-reviewer`
- `sw-product-reviewer`
- `sw-adversarial-reviewer`

### Signal-gated specialists

| Persona | Fires when |
| --- | --- |
| `sw-security-reviewer` | Any **`security`-tagged** keyword from `skills/triage/SKILL.md` "Risk triggers" matches the PRD (case-insensitive). Tags `data-migration` and `billing-routing` floor triage tier but do **not** fire security. |
| `sw-design-reviewer` | **Either** (a) one **unambiguous** UI term is present (`UI`, `UX`, `wireframe`, `modal`, `button`, `navigation`, `responsive`, `accessibility`, `user flow`), **or** (b) a **structural UI signal** exists: a `UI` / `UX` / `Screens` / `Mockups` section heading, a design-tool link (e.g. Figma), or an explicit interaction-state enumeration. Bare polysemous tokens (`component`, `view`, `page`, `form`) do **not** count alone. |

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

Mirrors `sw-triage` `--tier` override recording.

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

**Binding (R2–R4):** before each persona Task spawn, resolve and preflight:

```bash
PARENT_MODEL="<concrete platform model id of the dispatching agent session>"
AGENT="sw-coherence-reviewer"   # example persona id

RESOLVED=$(bash scripts/resolve-model-tier.sh --agent "$AGENT")
MODEL_ID=$(echo "$RESOLVED" | python3 -c "import json,sys; print(json.load(sys.stdin)['modelId'])")
bash scripts/reviewer-dispatch-check.sh --agent "$AGENT" --parent-model "$PARENT_MODEL"
# Task spawn MUST use model: <MODEL_ID> — not inherit
```

Repeat for every selected persona. Halt on preflight exit 20; do not spawn on unresolved `inherit`.

1. Detect doc type from path (see Doc types).
2. **Decision-record draft** (`docs/decisions/<n>-<slug>.md`): run all seven personas (`--all` equivalent); record
   `override: decision-record full panel` in the activation record.
3. **Decision amendment** (`docs/decisions/...amendments/A<k>-*.md`): run Decision amendment review floor — skip
   full selection unless `--personas` / `--all` override.
4. **PRD amendment** (`docs/prds/.../amendments/A<k>-*.md`): run **coherence** + **scope-guardian** only per
   Amendment review (U7) — skip the full selection algorithm unless `--personas` / `--all` override.
5. Resolve tier — if Quick, report "no panel for Quick" and stop.
6. **PRD draft:** run selection algorithm; announce activation record (core + any fired gates + matched signals).
7. Read full document (no section splitting) — each selected persona is a parallel sub-agent (R28/R31).
8. Each agent returns JSON per `references/findings-schema.json`.
9. Synthesizer follows `references/synthesis.md`.
10. Apply `safe_auto` silently; gate `gated_auto` and `manual`.

## Invariants (non-negotiable constraint class)

When `invariantsFile` is configured:

- Load the file relative to the **ref under review** (not always `main`).
- Pass content to every dispatched persona as a flagged non-negotiable block.
- Findings that violate an invariant are **hard** issues, not advisory.
- Missing/unreadable on the ref → block **this review only** with a config error (fail-closed).
- `--no-invariants` or `invariantsOptional: true` logs an override so fix-PRs are not deadlocked.

## Decision-record draft review

When reviewing `docs/decisions/<n>-<slug>.md` drafts (pre-freeze, not under `.amendments/`):

- Dispatch **all seven** personas: coherence, feasibility, scope-guardian, product, adversarial, security, design.
- Treat as top blast-radius by definition — floor-only relative to PRD signal-driven selection; never subtracts
  personas plan 004 would add on a PRD.
- Quick tier: no panel (parity with PRD Quick behavior).

## Decision amendment review

When reviewing `docs/decisions/<n>-<slug>.amendments/A<k>-*.md` drafts:

- **Always run:** coherence, scope-guardian, adversarial, feasibility against the frozen parent (read-only).
- **Additionally run security** when the decision touches auth, data, or migrations (same security signal
  enumeration as PRD selection).
- This is a **raised floor** above the generic PRD amendment path (coherence + scope-guardian only) — applies
  **only** when the frozen parent lives under `docs/decisions/`.
- Verify every `supersedes`/`retracts` target exists; record-level supersede must carry a `replacement:` forward
  pointer to a frozen target.
- Never edit the parent file — fixes apply only to the amendment draft.

## Amendment review (U7)

When reviewing `docs/prds/<n>-<slug>/amendments/A<k>-*.md` drafts:

- **coherence** + **scope-guardian** always run against the frozen parent (read-only) — not the full
  signal-driven panel.
- Verify every `supersedes`/`retracts` target exists in the parent effective spec.
- Reject targets already retracted; require rationale for each retract.
- Flag undeclared contradictions with parent requirements; declared directives are the sanctioned path.
- Never edit the parent file — fixes apply only to the amendment draft.

## Handoff

→ `/sw-freeze` when no blocking manual trade-offs remain.
