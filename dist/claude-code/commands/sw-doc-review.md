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
| PRD draft (`docs/prds/...`) | Signal-driven core + gated specialists (see skill) |
| Decision-record draft (`docs/decisions/<n>-<slug>.md`) | **Full** — all eight personas (cross-cutting blast radius) |
| Amendment under `docs/prds/.../amendments/` | Coherence + scope-guardian + docs-currency (generic floor) |
| Amendment under `docs/decisions/...amendments/` | Raised floor: coherence + scope-guardian + adversarial + feasibility + docs-currency (+ security when auth/data/migrations) |

Decision-record routing is **floor-only** — it never subtracts a persona signal-driven selection would add on PRDs.

## Procedure

1. Load `skills/doc-review/SKILL.md`.
2. **Dispatch binding (R9):** before each persona Task, run
   `bash scripts/wave.sh dispatch preflight --dispatch-id <id> --agent <id> --command sw-doc-review --skill doc-review`,
   then `bash scripts/dispatch-check.sh --agent <id> --command sw-doc-review --skill doc-review --parent-model <parent-concrete-id> --dispatch-id <id>`.
   Stamp the resolved concrete `model:` on Task input — reviewer agents keep `model: inherit` in frontmatter
   but dispatch must not rely on session inheritance. Halt on preflight exit 20 unless `--override` has a
   durable audit record.
3. **Invariants (optional):** when `invariantsFile` is set in config, resolve it relative to the ref under
   review. Inject content as a non-negotiable constraints block for all personas. Missing/unreadable on the ref
   blocks **this review only** (fail-closed) unless `invariantsOptional: true` or `--no-invariants` (logged).
4. Detect doc type from path:
   - `docs/decisions/<n>-<slug>.md` (not under `.amendments/`) → decision-record **draft** → Full panel (all eight).
   - `docs/decisions/<n>-<slug>.amendments/A<k>-*.md` → decision **amendment** → raised floor per skill.
   - `.../amendments/A<k>-*.md` under `docs/prds/` → PRD amendment → coherence + scope-guardian + docs-currency (U7).
5. If tier is Quick, report "no panel for Quick" and stop (parity for PRD and decision paths).
6. **PRD drafts:** run signal-driven selection; announce activation record.
7. **Decision-record drafts:** dispatch all eight `agents/sw-*-reviewer.md` personas (equivalent to `--all`).
8. **Amendments:** dispatch per amendment floor rules in the skill; honor `--personas` / `--all` overrides when set.
9. Dispatch selected personas as parallel sub-agents (full document each).
10. On partial failure, log and continue with remaining personas.
11. Synthesize per `skills/doc-review/references/synthesis.md` (max 2 rounds).
12. Apply safe_auto; present gated_auto/manual for user decision.
13. Report result; next step `/sw-freeze` when clear.

**Communication intensity:** normal

**Model tier:** build — resolve via `bash scripts/resolve-model-tier.sh --command sw-doc-review`.

## Guardrails

- PRD non-Quick: six-persona always-on core (includes docs-currency) + signal-gated `security` / `design`.
- Decision-record drafts: all eight personas always (Full blast radius).
- Decision amendments: raised floor only for `docs/decisions/` parents — PRD amendment floor unchanged.
- Quick: no panel.
- `--personas` / `--all` overrides are logged in the activation record.
- Findings failing schema validation are dropped.
- Synthesis loop hard-stops at max rounds / no-progress.
