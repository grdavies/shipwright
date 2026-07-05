---
name: sw-doc-review
description: Review PRD drafts with parallel persona sub-agents and a synthesizer that auto-applies safe fixes. Signal-driven panel (six-persona core + gated security/design); Quick tier skips review.
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: doc-review
      command: sw-doc-review
  metadata:
    skill: doc-review
    selectionFamily: doc-review
---

# Document review (`/sw-doc-review`)

Multi-persona review for PRDs and decision records. Pattern borrowed from compound-engineering `ce-doc-review` (slim vendored adaptation).


**Model tier:** inherit — runtime parent floor (R9); `resolve-model-tier.py --skill doc-review` returns inherit with `modelId: null`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Transport (PRD 045 R24/R69)

| `planning.store.backend` | Findings transport |
| --- | --- |
| `issue-store` | Marker-delimited `sw:doc-review` comments on the PRD artifact issue via `issue-comment` verb |
| default (file-store) | In-IDE parallel sub-agent panel + JSON synthesis (unchanged) |

Under issue-store, persona selection and dispatch binding are identical to file-store; only the **transport**
changes. Human review feedback uses a separate comment channel (no `sw:doc-review` marker).

### Issue-store transport

1. Resolve the PRD artifact issue ref from the planning store (`planning_store` + PRD 043 identification).
2. For each selected persona, dispatch the review Task (binding unchanged) and post findings as a structured
   comment on the PRD issue:
   - **Author:** plugin token only (bot-authored; PRD 043 R12 read-time verification).
   - **Marker:** `sw:doc-review` system marker delimits persona payload — **excluded** from PRD 043 R35
     canonicalization (cannot poison freeze verification).
   - **Payload:** JSON findings per `references/findings-schema.json` inside marker fences.
3. **Human channel:** operator notes post as plain comments without the `sw:doc-review` marker.
4. **Synthesis:** open a **review-round manifest** at checkpoint (PRD 043 R33 exclusive checkpoint) pinning
   ordered persona-comment IDs + revisions; fail closed on any add/edit/delete before synthesis completes.
   See `references/synthesis.md` **Review-round manifest (R69)**.
5. Apply `safe_auto` / gate `gated_auto` / `manual` identically to file-store synthesis.

**IDE fallback:** when `backend != issue-store`, the procedure below (parallel panel + JSON synthesis) is the
sole transport — byte-identical behavior to pre-045.

## Doc types

| Doc type | Path pattern | Panel |
|----------|--------------|-------|
| PRD draft | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | Signal-driven (see Selection) |
| Decision-record draft | `docs/decisions/<n>-<slug>.md` | **Full** — all eight personas |
| PRD amendment | `docs/prds/<n>-<slug>/amendments/A<k>-*.md` | Coherence + scope-guardian + docs-currency |
| Decision amendment | `docs/decisions/<n>-<slug>.amendments/A<k>-*.md` | Raised floor (see Decision amendment review) |

## Tier gate (review runs or not)

| Tier | Panel |
|------|-------|
| Quick | None — do not invoke |
| Standard / Full | Per doc type above |

**PRD tier no longer selects personas** — only whether review runs. Quick skips; PRD reviews use the
capability selector (`doc-review` family). **Decision-record drafts always use the Full panel** (all eight)
regardless of tier, because they govern multiple plans by definition.

## Selection

Deterministic — same inputs → same panel. Not model judgment. **Authoritative algorithm:** per-persona
`capability` frontmatter on `core/agents/sw-*-reviewer.md` aggregated into
`core/sw-reference/capability-index.json`, resolved by `python3 scripts/doc-review-select.py` (wraps
`capability-select.py` for the `doc-review` selection family). Contract:
`core/sw-reference/capability-manifest.md` (triggers, precedence, trust boundary).

**Model tier is orthogonal** — persona dispatch tiers resolve via `resolve-model-tier.py --agent <id>`;
capability selection does not choose models.

### Tier gate (selector input)

Quick tier → empty panel; selector is not invoked. Non-Quick PRD drafts build a versioned `signal_context`
(`tier`, `doc_path`, `body_snapshot`, `derived_tags` from triage, `overrides` for CLI flags) and call
`doc-review-select.py`. Decision-record and amendment paths use **floor rules** below (not the PRD selector).

### Always-on core (manifest)

Six personas carry explicit `always_on` triggers (`selectionFamily: doc-review`):

- `sw-coherence-reviewer`, `sw-feasibility-reviewer`, `sw-scope-guardian-reviewer`
- `sw-product-reviewer`, `sw-adversarial-reviewer`, `sw-docs-currency-reviewer`

**Living-doc complementarity:** `sw-docs-currency-reviewer` explicitly scopes out
`docs/prds/INDEX.md`, `docs/prds/COMPLETION-LOG.md`, and `docs/prds/GAP-BACKLOG.md` — those three
living indexes are owned by the PRD 009 living-doc currency gate. This persona must not re-gate or
duplicate that gate; its scope is arbitrary documentation artifacts at spec-time.

### Signal-gated specialists (manifest)

| Persona | Manifest trigger summary |
| --- | --- |
| `sw-security-reviewer` | `text_token` over **`security`-tagged** keywords (sync with `skills/triage/SKILL.md` risk triggers). Tags `data-migration` and `billing-routing` floor triage tier but do **not** fire security. |
| `sw-design-reviewer` | `any_of` unambiguous UI terms (`wireframe`, `modal`, `navigation`, `responsive`, `accessibility`, `user flow`, …), structural headings (`UI` / `UX` / `Screens` / `Mockups`), or design-tool links (e.g. Figma). Heading triggers use **whole-token** or **exact** match on stripped heading text — not substring containment (so `## Requirements` does not fire on embedded `ui`). Bare **polysemous** tokens (`component`, `view`, `page`, `form`) do **not** count alone. |

**Security signal enumeration** (must stay in sync with triage `security` tags and manifest `text_token` triggers):

`auth`, `authn`, `authz`, `authentication`, `authorization`, `login`, `session`, `oauth`, `jwt`, `payment`,
`payments`, `billing`, `PII`, `credentials`, `token`, `encryption`, `public api`, `public endpoint`,
`external api`, `webhook`

Keyword-gated security accepts deliberate false-negative cost on novel phrasing; use `--personas security` for
audits when wording dodges the list.

### Selector invocation

```bash
python3 scripts/doc-review-select.py --context-json '<signal_context>'
```

Returns canonical JSON: resolved persona ids, matched signals, and activation-record fields. Identical
`signal_context` ⇒ byte-identical output. Overrides (`--personas`, `--all`) are carried in
`signal_context.overrides` at selection time.

### Overrides

- `--personas <comma-separated>` — force-add named personas (e.g. `security,design`). Record
  `override: personas <list>` with reason.
- `--all` — run all eight personas (deep audit). Record `override: all`.

Mirrors `sw-triage` `--tier` override recording.

### Activation record

Emit at start of every review (inline in the review report):

```text
Persona activation:
  core: coherence, feasibility, scope-guardian, product, adversarial, docs-currency
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

RESOLVED=$(python3 scripts/resolve-model-tier.py --agent "$AGENT")
MODEL_ID=$(echo "$RESOLVED" | python3 -c "import json,sys; print(json.load(sys.stdin)['modelId'])")
python3 scripts/wave.py dispatch preflight --dispatch-id "$DISPATCH_ID" --agent "$AGENT" --command sw-doc-review --skill doc-review
python3 scripts/dispatch-check.py --agent "$AGENT" --command sw-doc-review --skill doc-review --parent-model "$PARENT_MODEL" --dispatch-id "$DISPATCH_ID"
# Task spawn MUST use model: <MODEL_ID> — not inherit
```

For **N parallel persona Tasks**, run **N independent preflights** with **unique** `--dispatch-id` values
(one record per persona under `.cursor/hooks/state/task-dispatch-preflight/<dispatch-id>.json`);
consuming one record leaves the others valid (R38). Repeat for every selected persona. Halt on preflight
exit 20; do not spawn on unresolved `inherit`.

1. Detect doc type from path (see Doc types).
2. **Decision-record draft** (`docs/decisions/<n>-<slug>.md`): run all eight personas (`--all` equivalent); record
   `override: decision-record full panel` in the activation record.
3. **Decision amendment** (`docs/decisions/...amendments/A<k>-*.md`): run Decision amendment review floor — skip
   full selection unless `--personas` / `--all` override.
4. **PRD amendment** (`docs/prds/.../amendments/A<k>-*.md`): run **coherence** + **scope-guardian** +
   **docs-currency** per Amendment review (U7) — skip the full selection algorithm unless `--personas` / `--all`
   override.
5. Resolve tier — if Quick, report "no panel for Quick" and stop.
6. **PRD draft:** run `python3 scripts/doc-review-select.py --context-json '<signal_context>'`; announce activation record (core + any fired gates + matched signals).
7. **Parallel panel (R38):** for each selected persona, run a **unique** `dispatch preflight` + `dispatch-check` (see Dispatch binding) **before** spawning that persona Task — never reuse a single preflight across N spawns.
8. Read full document (no section splitting) — each selected persona is a parallel sub-agent (R28/R31).
9. Each agent returns JSON per `references/findings-schema.json`.
10. Synthesizer follows `references/synthesis.md`.
11. Apply `safe_auto` silently; gate `gated_auto` and `manual`.

## Invariants (non-negotiable constraint class)

When `invariantsFile` is configured:

- Load the file relative to the **ref under review** (not always `main`).
- Pass content to every dispatched persona as a flagged non-negotiable block.
- Findings that violate an invariant are **hard** issues, not advisory.
- Missing/unreadable on the ref → block **this review only** with a config error (fail-closed).
- `--no-invariants` or `invariantsOptional: true` logs an override so fix-PRs are not deadlocked.

## Decision-record draft review

When reviewing `docs/decisions/<n>-<slug>.md` drafts (pre-freeze, not under `.amendments/`):

- Dispatch **all eight** personas: coherence, feasibility, scope-guardian, product, adversarial, docs-currency,
  security, design.
- Treat as top blast-radius by definition — floor-only relative to PRD signal-driven selection; never subtracts
  personas plan 004 would add on a PRD.
- Quick tier: no panel (parity with PRD Quick behavior).

## Decision amendment review

When reviewing `docs/decisions/<n>-<slug>.amendments/A<k>-*.md` drafts:

- **Always run:** coherence, scope-guardian, adversarial, feasibility, docs-currency against the frozen parent
  (read-only).
- **Additionally run security** when the decision touches auth, data, or migrations (same security signal
  enumeration as PRD selection).
- This is a **raised floor** above the generic PRD amendment path (coherence + scope-guardian + docs-currency) —
  applies **only** when the frozen parent lives under `docs/decisions/`.
- Verify every `supersedes`/`retracts` target exists; record-level supersede must carry a `replacement:` forward
  pointer to a frozen target.
- Never edit the parent file — fixes apply only to the amendment draft.

## Amendment review (U7)

When reviewing `docs/prds/<n>-<slug>/amendments/A<k>-*.md` drafts:

- **coherence** + **scope-guardian** + **docs-currency** always run against the frozen parent (read-only) — not
  the full signal-driven panel.
- Verify every `supersedes`/`retracts` target exists in the parent effective spec.
- Reject targets already retracted; require rationale for each retract.
- Flag undeclared contradictions with parent requirements; declared directives are the sanctioned path.
- Never edit the parent file — fixes apply only to the amendment draft.

## Handoff

→ `/sw-freeze` when no blocking manual trade-offs remain.
