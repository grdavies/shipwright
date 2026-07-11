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
2. If input is vague, ask one clarifying question (blocking tool preferred).
3. Explore alternatives; challenge assumptions; resolve product decisions here.
4. Run synthesis checkpoint: restate scope, tier, key decisions; confirm with user before write.


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
