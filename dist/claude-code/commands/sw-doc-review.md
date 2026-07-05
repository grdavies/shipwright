---
description: Review a PRD or decision-record draft with parallel persona sub-agents and apply safe fixes via synthesizer. Does not freeze artifacts or generate tasks.
alwaysApply: false
---

# `/sw-doc-review`

Persona panel + synthesis for PRD drafts, decision-record drafts, and amendment drafts.

## Scope

- Input: PRD draft, decision-record draft, or amendment draft path + tier (from triage or user).
- Output: reviewed draft with safe_auto fixes applied; gated/manual items surfaced.
- Does **not** freeze, generate tasks, or run on Quick-tier work.

## Doc-type routing

| Input | Panel |
|-------|-------|
| PRD draft (`docs/prds/...`) | Signal-driven via capability selector — `doc-review` family (`scripts/doc-review-select.py`) |
| Decision-record draft (`docs/decisions/<n>-<slug>.md`) | **Full** — all eight personas (cross-cutting blast radius) |
| Amendment under `docs/prds/.../amendments/` | Coherence + scope-guardian + docs-currency (generic floor) |
| Amendment under `docs/decisions/...amendments/` | Raised floor: coherence + scope-guardian + adversarial + feasibility + docs-currency (+ security when auth/data/migrations) |

Decision-record routing is **floor-only** — it never subtracts a persona the capability selector would add on PRDs.

## Transport routing (PRD 045 R24)

Resolve `planning.store.backend` from `.cursor/workflow.config.json`:

| Backend | Transport |
| --- | --- |
| `issue-store` | Persona + human doc-review via **integrity-checked issue comments** on the PRD artifact issue (R69). Findings post as marker-delimited `sw:doc-review` comments; synthesis reads back under a review-round manifest. |
| **else** (default file-store) | In-IDE parallel sub-agent panel + JSON synthesis — **unchanged** (no regression). |

Under issue-store, dispatch binding and persona selection are unchanged; only the **findings transport**
differs. Human review notes use a separate comment channel (not persona markers). See
`skills/doc-review/SKILL.md` **Issue-store transport** and `references/synthesis.md` **Review-round manifest**.

## Procedure

1. Load `skills/doc-review/SKILL.md`.
2. **Resolve transport** — `issue-store` → comment transport; else → IDE panel (R24).
3. **Dispatch binding (R9):** before each persona Task, run
   `python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <id> --command sw-doc-review --skill doc-review`,
   then `python3 scripts/dispatch-check.py --agent <id> --command sw-doc-review --skill doc-review --parent-model <parent-concrete-id> --dispatch-id <id>`.
   Stamp the resolved concrete `model:` on Task input — reviewer agents keep `model: inherit` in frontmatter
   but dispatch must not rely on session inheritance. Halt on preflight exit 20 unless `--override` has a
   durable audit record.
4. **Invariants (optional):** when `invariantsFile` is set in config, resolve it relative to the ref under
   review. Inject content as a non-negotiable constraints block for all personas. Missing/unreadable on the ref
   blocks **this review only** (fail-closed) unless `invariantsOptional: true` or `--no-invariants` (logged).
5. Detect doc type from path:
   - `docs/decisions/<n>-<slug>.md` (not under `.amendments/`) → decision-record **draft** → Full panel (all eight).
   - `docs/decisions/<n>-<slug>.amendments/A<k>-*.md` → decision **amendment** → raised floor per skill.
   - `.../amendments/A<k>-*.md` under `docs/prds/` → PRD amendment → coherence + scope-guardian + docs-currency (U7).
6. If tier is Quick, report "no panel for Quick" and stop (parity for PRD and decision paths).
7. **PRD drafts:** build `signal_context` (tier, `doc_path`, frozen `body_snapshot`, `derived_tags` from triage,
   `overrides` for `--personas` / `--all`); run
   `python3 scripts/doc-review-select.py --context-json '<signal_context>'`; announce activation record from selector output.
8. **Decision-record drafts:** dispatch all eight `agents/sw-*-reviewer.md` personas (equivalent to `--all`).
9. **Amendments:** dispatch per amendment floor rules in the skill; honor `--personas` / `--all` overrides when set.
10. Dispatch selected personas — **issue-store:** post findings as `sw:doc-review` comments via `issue-comment` verb;
    **file-store:** parallel sub-agents in-IDE (full document each).
11. On partial failure, log and continue with remaining personas.
12. Synthesize per `skills/doc-review/references/synthesis.md` (max 2 rounds; issue-store uses review-round manifest).
13. Apply safe_auto; present gated_auto/manual for user decision.
14. Report result; next step `/sw-freeze` when clear.

**Communication intensity:** normal

**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --command sw-doc-review`.

## Guardrails

- PRD non-Quick: six-persona always-on core (includes docs-currency) + signal-gated `security` / `design`
  (resolved by `scripts/doc-review-select.py` / manifest triggers).
- Decision-record drafts: all eight personas always (Full blast radius).
- Decision amendments: raised floor only for `docs/decisions/` parents — PRD amendment floor unchanged.
- Quick: no panel.
- `--personas` / `--all` overrides are logged in the activation record.
- Findings failing schema validation are dropped.
- Synthesis loop hard-stops at max rounds / no-progress.
