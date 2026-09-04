---
name: prd
description: Generate a PRD or decision-record draft for Full or Standard tier. Use when requirements are brainstormed and a written spec is needed before persona review. Does not freeze, run doc-review, or generate tasks.
---
# PRD / decision-record draft (`/sw-prd`)

Port of v1 `spec-prd` under `sw-`. Freeze and task generation are separate steps. Generalized into a typed frozen-deliverable author via `--type`.


**Model tier:** deep — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill prd`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Deliverable types

| `--type` | Path | ID namespace | Brainstorm guard |
|----------|------|--------------|------------------|
| `prd` (default) | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | R-IDs | Full tier requires brainstorm |
| `decision` | `docs/decisions/<n>-<slug>.md` | D-IDs | optional (up-front decisions) |

## PRD sections (required, `--type prd`)

1. Overview
2. Goals
3. Non-Goals
4. Requirements (stable R-IDs; carry forward from brainstorm when present)
5. Technical Requirements
6. Security & Compliance
7. Testing Strategy
8. Rollout Plan
9. Decision Log
10. Open Questions

## Decision-record sections (required, `--type decision`)

1. Context
2. Decision (stable D-IDs as bullets: `- **D1** ...`)
3. Rationale
4. Alternatives
5. Consequences

The decision section contract must stay in lockstep with `scripts/spec-rigor-check.py --artifact decision`.


## Issue-store authoring (PRD 056 R11–R12)

When effective backend is `issue-store`:

1. **Never** create or edit files under `docs/prds/` in the code repo.
2. Allocate the next PRD number by scanning the issue index / planning graph (not `docs/prds/` directory listing).
3. Persist via `planning_store.put` with stable unit id `<n>-prd-<slug>` and virtual body-path `docs/prds/<n>-<slug>/<n>-prd-<slug>.md`.
4. Frontmatter traceability uses the same virtual paths; write refs via:

   ```bash
   python3 scripts/doc_link.py write-backref --brainstorm <body-path> --prd <body-path>      [--brainstorm-unit-id <id>] [--prd-unit-id <id>]
   ```

5. Handoffs cite **unit id** + virtual `body-path` — not code-repo file paths.

File-store repos: unchanged — paths and file writes below apply.

## Path

- PRD: `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` per `.shipwright/layout.md`.
- Decision: `docs/decisions/<n>-<slug>.md` per `.shipwright/layout.md`.

## Tier routing (PRD only)

- **Full:** require brainstorm doc path as input; refuse to draft without it (R6 ordering).
- **Standard:** accept triaged request directly (no brainstorm required).

## Frontmatter traceability (Full tier — R52/R53)

At save time on the Full path:

1. Write `brainstorm: <repo-relative-path>` on the PRD via
   `python3 scripts/doc_link.py write-backref --brainstorm <body-path> --prd <body-path> [--brainstorm-unit-id …] [--prd-unit-id …]`.
2. When the brainstorm is not frozen, write the forward `prd:` reference via
   `python3 scripts/doc_link.py write-forwardref --brainstorm <brainstorm> --prd <prd>`.

`/sw-freeze` re-verifies linkage (`doc-link-check.py`, R55) and may write the forward ref if still writable (R53).
Fields are documented in `.shipwright/layout.md`.

## DecisionGraph scope (PRD 280 R15)

When a PRD drives engineering decisions that require a `DecisionGraph`:

1. Persist the graph via `planning_store.put` with unit id `<prd-unit-id>-decision-graph` and virtual body-path `docs/planning/decision/<unit-id>/decision-graph.json` (`sw:decision` issue type).
2. Link PRD ↔ graph without code-repo file writes:

   ```bash
   python3 scripts/doc_link.py write-decision-graph-link --prd <prd-body-path> [--prd-unit-id <id>] [--graph-unit-id <id>]
   ```

3. Doc-review and freeze gates validate the `decision-graph` back-reference resolves via issue-store handles.

## Collision policy

- Same feature/topic, new run: increment `<n>`, distinct slug; do not overwrite.
- Update existing: edit in place only with explicit user confirmation + Decision Log entry (PRD) or amendment (frozen decision).
- Default: never overwrite without confirmation.
- Refuse to draft over an existing **frozen** decision record without explicit confirmation.

## Numbering

- PRD: scan `docs/prds/` for highest `<n>`, increment, zero-pad to 3 digits.
- Decision: scan `docs/decisions/` for highest `<n>`, increment, zero-pad to 3 digits — **separate counter**.

## Domain vocabulary divergence (PRD 280 R10, D4)

After persisting a **PRD draft** (`--type prd` only — skip decision records):

1. Run terminology drift detection against the saved body:

   ```bash
   # file-store (body on disk)
   python3 scripts/domain_vocabulary.py check-divergence --file <prd-path>

   # issue-store (authoritative body in planning store)
   python3 scripts/domain_vocabulary.py check-divergence --unit-id <prd-unit-id>
   ```

2. **Advisory default** — `planning.intelligence.vocabulary.strictMode` defaults `false`; `verdict: pass`
   with `maxSeverity: warn` does **not** block handoff to `/sw-doc-review`.
3. **Strict escalation** — when `strictMode: true` (config or CLI `--strict`), `verdict: fail` with exit code
   `20` halts `/sw-prd` before doc-review handoff (fail-closed).
4. **Artifact** — results persist read-only at `.cursor/sw-vocabulary-divergence/last.json` for downstream
   doc-review (coherence persona).
5. **No canonical promotion** — divergence output is `humanGated`; this step never calls `put-term` or mutates
   the vocabulary registry.

Surface a short divergence summary in the `/sw-prd` report when `divergence` is non-empty (concepts,
`maxSeverity`, artifact path).

## Handoff

→ `/sw-doc-review` (not `/sw-freeze` or `/sw-tasks`). Resolve Open Questions before freeze (spec-rigor clarify gate on Full tier PRDs).

## Open questions

GitHub tracking-issue convention deferred to implementation workstream (`003`). Default: index + git are the status source — no issue opened unless user requests.
