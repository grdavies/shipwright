---
name: brainstorm
description: Explore requirements through one-question-at-a-time dialogue, then write a requirements document with stable R-IDs. Use when scope is open or Full-tier work precedes PRD drafting. Does not freeze artifacts or generate tasks.
---
# Brainstorm (`/sw-brainstorm`)

Full-tier requirements exploration. Produces a brainstorm doc for `/sw-prd`. Does **not** draft a PRD.


**Model tier:** deep — resolve via `python3 scripts/resolve-model-tier.py --skill brainstorm`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Core principles

1. **One question per turn** — prefer single-select blocking questions.
2. **Investigate before asking** — on clear inputs, read repo context first.
3. **Synthesis checkpoint** — restate scope and decisions before writing any file.
4. **Full fidelity** — requirements authoring uses complete prose (R30/R31).
5. **Pipeline order** — never draft a PRD in this stage.

## Procedure

### Phase 1: Assess and explore

1. Read `.sw/layout.md` for output path.
2. When `.cursor/sw-context/project-intent.md` exists (optional `/sw-init` capture), read it opportunistically
   for project intent and working-style context — never required, never blocking when absent.
3. If input is vague, ask one clarifying question (blocking tool preferred).
4. Explore alternatives; challenge assumptions; resolve product decisions here.
5. Run the **divergence phase** below before the synthesis checkpoint.
6. Run synthesis checkpoint: restate scope, tier, key decisions; confirm with user before write.

### Divergence phase (mandatory, before synthesis checkpoint)

Precedes requirements convergence — this is the default manual path; the opt-in tournament below is a
selection mechanism layered on top of it, not a replacement.

1. **Name the core tension** in one sentence (the real trade-off this feature forces).
2. **Generate 3–5 deliberate-stance options.** Each stance is a genuine different way to resolve the tension —
   not cosmetic variants — with trade-offs and an effort estimate. At least one stance MUST be an
   **unexpected cross-domain borrow** (a pattern lifted from an unrelated domain, clearly labeled as such).
3. **Present structured selection** — a table: stance | trade-offs | effort | recommended.
4. **Recommend one with conviction** — state which stance you'd pick and why in one or two direct sentences;
   do not hedge across all options equally.
5. **Persist chosen + rejected** — once the operator picks (or accepts the recommendation), record the chosen
   stance and every rejected alternative (with its one-line rejection reason) in the requirements doc's **Key
   Decisions** section before moving to synthesis.

#### Unsure routing (not blind re-asking)

When the operator's response to the divergence selection is "unsure" or equivalent, classify *why* before
picking a next step — never just repeat the same question verbatim:

| Unsure type | Signal | Route |
| --- | --- | --- |
| Ambiguous preference between ~2 viable stances | Operator likes two options roughly equally | `calibration-loop` skill — present one concrete either/or instance, converge on a principle |
| Options too broad/abstract to judge | Operator can't picture the stances concretely | Regenerate a **narrower** stance set (tighter framing, same tension) — do not repeat the wide set |
| No strong opinion, defer to judgment | Operator explicitly defers | **Explicit delegation** — proceed with the recommended stance, record `delegated: true` + rationale in Key Decisions so it is auditable, not silent |

Load `skills/calibration-loop/SKILL.md` for the ambiguous-preference route.

#### Optional persona enrichment (non-blocking)

Before generating stance options, the divergence brief MAY be enriched by dispatching a subset of the
`doc-review` personas (`core/agents/sw-*-reviewer.md`) as read-only advisors on the framed tension — additional
angles only, never a gate. Skip silently on timeout, unavailability, or when the tension is already
well-scoped; never block divergence on persona availability (R31 — optional, never required).

### Divergence tournament (PRD 064 R6, opt-in)

When `tournament.enabled` is true and Phase 1 yields **≥2 viable divergence candidates** at the
**divergence-selection** checkpoint (before the synthesis checkpoint), run the tournament primitive instead of
picking an option inline:

```bash
python3 scripts/tournament.py should-run --divergence "$RUN_DIR/brainstorm-divergence.json"
python3 scripts/tournament.py plan --divergence "$RUN_DIR/brainstorm-divergence.json" > "$RUN_DIR/tournament-plan.json"
```

Load `skills/tournament/SKILL.md` for attempt fan-out, deterministic bracketing, pairwise judges, and
`persist` winner + rationale. Config keys: `tournament.{enabled,n,cost_ceiling}` — default `N=3`, **off** by
default. Other call sites are out of scope (D3).



### Candidate-idea near-duplicate intake (PRD 064 R25)

Before persisting a new brainstorm candidate idea (divergence checkpoint or requirements write), scan
against the live gap-unit corpus. Flag for review only — never auto-suppress or block synthesis (KD5):

```bash
python3 scripts/gap_similarity.py scan   --candidate "$CANDIDATE_IDEA_TEXT"   --out "$RUN_DIR/brainstorm-near-dup-scan.json"   --handoff-out "$RUN_DIR/brainstorm-near-dup-handoff.md"
```

When matches are returned, include `brainstorm-near-dup-handoff.md` in the synthesis checkpoint for
human confirm before continuing to `/sw-prd`.


## Issue-store authoring (PRD 056 R11–R12)

When `python3 scripts/planning_store.py resolve-backend` reports effective `issue-store`:

1. **Never** write under `docs/brainstorms/` in the code repo — no local stub files.
2. Persist via `planning_store.put` only:

   ```bash
   python3 scripts/planning_store.py put --unit-id <unit-id> --body-path docs/brainstorms/<filename>.md --content "$(cat <<'EOF'
   ...
   EOF
   )"
   ```

3. Use a stable **unit id** (e.g. `brainstorm-2026-07-06-<topic>-requirements`) in handoffs — cite unit id + virtual `body-path`, not a git file path.
4. Run spec-rigor against the handle (no on-disk file required):

   ```bash
   python3 scripts/spec-rigor-check.py --artifact brainstorm --path docs/brainstorms/<filename>.md --unit-id <unit-id>
   ```

File-store repos: unchanged — write to `docs/brainstorms/` as below.

### Phase 2: Write requirements doc

1. Load `skills/brainstorm/references/requirements-sections.md`.
2. **File-store:** write to `docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md`. **Issue-store:** `planning_store.put` only (see above).
3. Assign stable R-IDs; include all required sections.
4. **Spec-rigor gate (hard-blocking):** run
   `python3 scripts/spec-rigor-check.py --artifact brainstorm --path <body-path> [--unit-id <unit-id>]` after the put/write.
   Exit `20` halts — fix findings before handoff. Advisory re-check remains available to `/sw-doc-review`.
5. Report path and next step: `/sw-prd` (after `/sw-freeze` if freezing brainstorm first).

## Guardrails

- No PRD output in this stage.
- No `frozen: true` unless user explicitly runs `/sw-freeze` afterward.
- Repo-relative paths only in the document.
- Resume existing brainstorm: update in place after user confirms.

## Handoff

→ `/sw-prd` (Full path requires this doc as input).
