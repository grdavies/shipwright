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

## Transport routing (PRD 045 R24; PRD 341)

Resolve `planning.store.backend` from `.cursor/workflow.config.json`:

| Backend | Transport |
| --- | --- |
| `issue-store` | **Facade-only** review-round ops on the PRD artifact issue (GitHub): `post_review_finding` → `open_review_manifest` → `read_review_manifest` / `verify_review_manifest` → `complete_review_round`. Marker-delimited `sw-doc-review` comments; live body witness excluded from stripped canonical hash. |
| **else** (default file-store) | In-IDE parallel sub-agent panel + JSON synthesis — **byte-identical** to pre-341 (R33). |

Under issue-store, dispatch binding and persona selection are unchanged; only the **findings transport**
differs. Do **not** post review findings via public `issue-comment` — that verb stays adapter-internal.
Human review notes use a separate comment channel (no `sw-doc-review` marker). Run dirs under
`.cursor/doc-review-runs/` are **cache-only** (non-authoritative). See `skills/doc-review/SKILL.md`
and `references/synthesis.md`.

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
10. Dispatch selected personas — **issue-store (new rounds):** `post_review_finding` per persona, then
    `open_review_manifest` (post-then-open); **file-store:** parallel sub-agents in-IDE (full document each).
11. On partial failure, log and continue with remaining personas.
12. **Issue-store:** `read_review_manifest` + `verify_review_manifest` before synthesis; then synthesize per
    `skills/doc-review/references/synthesis.md` (max 2 rounds); finish with `complete_review_round`.
13. Apply safe_auto; present gated_auto/manual for user decision.
14. Report result; next step `/sw-freeze` when clear.

**Communication intensity:** normal

**Model tier:** build — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-doc-review`.

## Guardrails

- PRD non-Quick: six-persona always-on core (includes docs-currency) + signal-gated `security` / `design`
  (resolved by `scripts/doc-review-select.py` / manifest triggers).
- Decision-record drafts: all eight personas always (Full blast radius).
- Decision amendments: raised floor only for `docs/decisions/` parents — PRD amendment floor unchanged.
- Quick: no panel.
- `--personas` / `--all` overrides are logged in the activation record.
- Findings failing schema validation are dropped.
- Synthesis loop hard-stops at max rounds / no-progress.

## Doc-impact integration review signal

When reviewing documentation or guide-affecting changes, include an explicit agent judgment that the
docs **read as integrated** with the product surface (not keyword presence alone): style-guide
alignment, glossary links for coined terms, no PRD/R-ID tokens in adopter prose, and decision-tree
routing where command choice is non-obvious. Fail closed on mechanical lint from
`scripts/unit_tests/git/harness_ux_polish.py` (user-guide provenance, `documentation/` absent).

## Reviewer effectiveness capture boundary (PRD 273)

Reviewer-effectiveness metadata persistence uses **`.cursor/sw-learning-store/` as the sole v1 authority**
via `ReviewerMetricsStoreAdapter` (Decision D7). `/sw-doc-review` does not write parallel reviewer-metrics
stores or promote learnings to standing rules — capture flows through the thin adapter only. See
`.shipwright/layout.md` (NP-1) and `scripts/unit_tests/graph/test_reviewer_metrics_no_promotion.py`.

