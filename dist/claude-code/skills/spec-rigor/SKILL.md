---
name: spec-rigor
description: Pre-freeze spec quality gates (clarify, checklist, analyze) and R-ID to task to test traceability. Use when validating PRD quality before /sw-freeze on Standard or Full tier. Blocks freeze on hard failures.
---
# Spec-rigor gates (IM4)

Pre-freeze quality and traceability discipline for the doc workstream. Complements `skills/doc-review` (persona
panel) — structural gates run **after** panel synthesis and **before** `/sw-freeze`.


**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill spec-rigor`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Tier policy

| Tier | Pre-PRD-freeze | Pre-task-freeze |
| --- | --- | --- |
| **Full** | clarify + checklist | analyze + traceability |
| **Standard** | checklist only | analyze + traceability |
| **Quick** | — (doc chain not entered) | — |

**Clarify** is Full-only because `/sw-brainstorm` + `/sw-prd` dialogue already reduces ambiguity on Standard.
**Analyze** and **traceability** always run before task-list freeze — every tier that reaches tasks needs
spec↔task consistency and R-ID→test coverage.


## Structural tokenizer (PRD 031)

All spec-rigor and traceability parsing flows through the shared doc-format tokenizer
(`scripts/doc_format.py` via `scripts/doc-format-normalize.py`). Before freeze:

- `python3 scripts/doc-format-normalize.py --check <path>` — fail-closed `file:line` diagnostics.
- `python3 scripts/doc-format-normalize.py --write <path>` — shape-only canonicalization (idempotent).

Authoring commands emit slot-filling templates matching the canonical shape; non-empty directive keys
(`absorbs`/`supersedes`/`retracts`) that yield zero parsed ids fail closed.

Paths resolve through `planningDir` from `workflow.config.json` (legacy `prdsDir`/`tasksDir` aliases
pre-cutover). See `core/sw-reference/layout.md` for the unit tree and INDEX regions.

## Consumer `--root` and asterisk RID (PRD 358 R7/R8)

Installed `spec-rigor-check.py` **requires** consumer `--root`. Artifact resolve, `load_workflow_config`,
and `get_backend` use that root — not `SCRIPT_DIR.parent`. Omit `--root`, or pass a root that resolves
to the package `scripts/` parent, fails closed. Split roots: `--root` for workflow config and
issue-store get; `SCRIPT_DIR` for `spec-union.py` and packaged helpers. Consumer repos have no
`scripts/` tree.

R/D bullets parse both hyphen and **asterisk** Markdown list markers (Linear Public Markdown):
`- **R1** …` and `* **R1** …` (plus Linear spacing). `RID_BULLET`, `RID_BULLET_ALT`,
`RID_BULLET_NONCANON`, tokenizer `RD_ID_BULLET`, `extract_rd_bullets`, spec-rigor,
`doc-format-normalize`, and traceability all accept `*`. A hyphen-only diagnostic copy is not a
passing artifact. Parser success on a truncated Linear stump is **not** freeze authority.

## Passes

### Clarify (ambiguity — Full, pre-PRD-freeze)

Resolve or explicitly defer every open question before freeze:

- Scan `## Open Questions` — no unresolved bullets (`- [ ]`, unresolved placeholders, `???`).
- Scan requirement / decision bodies with the **layered** ambiguity matcher in
  `scripts/spec-rigor-check.py` (same helper on PRD, brainstorm, decision, and Full Open Questions).
- Unresolved placeholders still fail closed: all-caps `TBD`/`TODO`/`FIXME`, casual lowercase of those
  tokens, `to be determined`, and `???`.
- Context-aware defaults (no allowlist required): Title-case named states (e.g. NOR-7 **Todo**) and
  lowercase slash-taxonomy segments (`idea/todo/note`) do **not** fail.
- **Vocab-restricted punctuation wraps (PRD 364):** only unfinished-work tokens `TODO` / `TBD` / `FIXME`
  (case-insensitive) count as wrap hits — `token:` or `[token]`. Any other word plus colon, or any other
  bracket span, is **not** a wrapper hit. Wrap scans skip Markdown link/autolink **destinations** only;
  colliding link **labels** still fail. Wraps run before Title-case masking in the layered matcher.
- Optional frontmatter `reviewedLiterals` (YAML list of exact strings) suppresses exact matches only;
  a non-empty list requires a Decision Log entry naming each token. Not every case-insensitive
  word-boundary hit is unfinished work.
- Surface blocking questions to the user; do not freeze until cleared or moved to Decision Log with rationale.

### Checklist (requirement quality — pre-PRD-freeze)

Deterministic PRD checks via `scripts/spec-rigor-check.py --artifact prd`:

- At least one stable R-ID in Requirements.
- No duplicate R-IDs.
- No unresolved ambiguity markers in requirement text (layered matcher above).
- Required PRD sections present (Overview, Goals, Non-Goals, Requirements, Testing Strategy).
- New PRDs (`prdBodyContract: v2`) also require Acceptance Scenarios and Success Criteria; existing bodies without the contract key are grandfathered.

### Analyze (spec↔task consistency — pre-task-freeze)

Via `scripts/spec-rigor-check.py --artifact tasks`:

- Task file references every effective R-ID from `scripts/spec-union.py` (union, not parent-only).
- Parent tasks are dependency-ordered; no orphan R-IDs in union without a task reference.
- `## Traceability` table present and parseable.
- Task lists must not contain `## Sizing & Split Suggestions` at freeze; strip via `python3 scripts/phase_sizing.py strip-advisory --inplace <path>`.

### Traceability (R-ID → task → test — pre-task-freeze)

Via `scripts/traceability-check.py`:

- Each effective R-ID maps to a **task ref** (and **ZOMBIES checklist** when test scenarios are bound — `references/zombies.md`) (e.g. `1.2`, `2`) and a **named test scenario** (fixture name,
  test file path, or explicit scenario label — not "add tests later").
- Uncovered R-IDs block task-list freeze (`verdict: gaps`, exit `20`).
- Output is stable JSON for fixtures and downstream U7 TDD gate consumption.

## Canonical scripts

```bash
# Pre-PRD-freeze (pass --tier full|standard) — paths relative to planningDir or legacy prdsDir
python3 scripts/spec-rigor-check.py --root <consumer-repo> --artifact prd --path <planningDir>/prd/prd-031-.../prd-031-....md --tier full

# Pre-task-freeze
python3 scripts/spec-rigor-check.py --root <consumer-repo> --artifact tasks --path <planningDir>/prd/prd-031-.../tasks-prd-031-....md --prd <prd-body>
python3 scripts/traceability-check.py --prd <prd-body> --tasks <tasks-path>
```

### Verdict contract

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `pass` | All applicable gates satisfied | `0` |
| `warn` | Advisory findings only (e.g. short requirement text) | `10` |
| `fail` | Hard blocker — do not freeze | `20` |

`warn` allows freeze to proceed with logged findings. `fail` halts until fixed.

## Task-list traceability shape

Every frozen task list includes:

```markdown
## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.2 | run_gate_fixtures.py frozen guard |
| R2 | 2.1 | spec-union supersede fixture |
```

Task items cite R-IDs inline: `- [ ] 1.2 Implement gate (R1)`.

## Integration points

| Command | When |
| --- | --- |
| `/sw-freeze` | PRD → spec-rigor PRD gates; task list → analyze + traceability |
| `/sw-tasks` | Generate traceability table during expansion; run checks before freeze |
| `/sw-doc` | Chain includes spec-rigor before each freeze step |

## Guardrails

- Gates are **additive** — they do not replace doc-review or freeze CI (`check-frozen.py`).
- No auto-fix of PRD/task content — surface findings; human or synthesizer fixes.
- Redact any persisted gate summary through `python3 scripts/sw_bootstrap.py memory-redact.py` (R41).
