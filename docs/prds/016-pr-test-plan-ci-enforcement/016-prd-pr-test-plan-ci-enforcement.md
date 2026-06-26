---
date: 2026-06-26
topic: pr-test-plan-ci-enforcement
frozen: true
frozen_at: 2026-06-26
---

# PRD 016 — PR test-plan CI enforcement

## Overview

Shipwright `FEAT → main` PRs routinely list a test plan in the description — e.g.
`run-ux-polish-fixtures.sh`, `run-doc-fixtures.sh`, `run-cleanup-fixtures.sh`, `docs-link-check.sh` — but those
commands run only if an agent executes them manually. `/sw-watch-ci` therefore cannot catch doc/workflow
regressions: a failing test-plan item surfaces after merge, or not at all. This PRD promotes the recurring
test-plan fixtures to CI jobs so every PR head runs the same set, classifies each as PR-blocking vs advisory
under the `checks-gate` all-checks policy, single-sources the standard FEAT test-plan set so local `verify.test`
and CI run identically, and turns the PR template into a reference to CI job names rather than a manual
checklist. It closes GAP-BACKLOG row 30.

This is a **Standard-tier** PRD (bounded CI/workflow change, no brainstorm).

## Goals

1. Every PR head runs the standard FEAT test-plan fixtures as CI jobs — no reliance on manual agent execution.
2. Each fixture is explicitly classified PR-blocking (required) or advisory, consistent with `checks-gate`.
3. One source of truth for the standard test-plan set, shared by local `verify.test` and the CI workflow.
4. `/sw-stabilize` consumes the new job logs through the existing `check-gate.sh` path — no new remediation
   surface.

## Non-Goals

- Adding new test fixtures or test coverage — this PRD wires *existing* fixtures into CI, it does not author
  tests.
- Changing the `checks-gate` readiness algorithm itself (it already evaluates all checks, not just required).
- Auto-merging or changing the human merge gate (PRD 004/007 invariant).
- Replacing `/sw-watch-ci` or `/sw-stabilize` behavior beyond consuming the promoted job logs.

## Requirements

- **R1** The recurring FEAT test-plan fixtures (the standard set: `run-doc-fixtures.sh`,
  `run-cleanup-fixtures.sh`, `run-ux-polish-fixtures.sh`, `docs-link-check.sh`, and any other fixtures the audit
  in R2 deems recurring) MUST run as CI jobs on every PR head, replacing the manual description checklist as the
  enforcement mechanism.
- **R2** Each promoted fixture MUST be explicitly classified **PR-blocking (required)** or **advisory
  (non-blocking)**, and the classification MUST be consistent with the `checks-gate` all-checks policy (advisory
  jobs still surface in the readiness verdict but do not block).
- **R3** The standard FEAT test-plan set MUST be single-sourced so local `verify.test` and the CI workflow run
  the identical fixture set — no drift between what an agent runs locally and what CI runs.
- **R4** The PR template MUST reference the CI job names (the authoritative gate) instead of enumerating a manual
  test-plan checklist; any residual human note MUST be advisory, not the enforcement path.
- **R5** `/sw-stabilize` MUST be able to consume the promoted CI job logs through the existing `check-gate.sh`
  path, so remediation works on the new jobs with no new log source or parser.
- **R6** The `checks-gate` readiness verdict MUST evaluate the promoted jobs under its existing all-checks (not
  just required) policy, so an advisory failure is visible and a required failure blocks.
- **R7** All `core/` changes MUST propagate to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all` (freshness gate passing), be covered by fixtures, and be documented in the
  workflow YAML, `skills/checks-gate/SKILL.md` / `rules/checks-gate.mdc`, and the CI/contributing guide.

## Technical Requirements

- **TR1 — Single-sourced test-plan set.** Define the standard FEAT test-plan fixture set once (e.g. a manifest
  consumed by both `workflow.config.json` `verify.test` and the CI workflow generator) so R3 holds; classify
  each entry blocking/advisory inline (R1, R2, R3).
- **TR2 — CI workflow jobs.** Generate/extend the GitHub Actions workflow so each set member runs as a named job
  on `pull_request`; required jobs gate the merge, advisory jobs report only (R1, R2).
- **TR3 — PR template.** Update the PR template to reference the CI job names as the gate; remove the manual
  test-plan checklist as the enforcement path (R4).
- **TR4 — Stabilize/gate integration.** Ensure `check-gate.sh` enumerates the promoted jobs and `/sw-stabilize`
  remediates from their logs via the existing path; `checks-gate` verdict covers them under all-checks (R5, R6).
- **TR5 — Emitter + docs + fixtures.** Regenerate `dist/`; update workflow YAML, checks-gate skill/rule, and the
  CI guide; add the Testing Strategy fixtures (R7).

## Security & Compliance

- **No new secret surface.** CI jobs run existing local fixtures; no new credentials or network calls are
  introduced. Any secret-scan/redaction guardrails (PRD 007) remain unchanged and continue to gate the PR.
- **Merge gate unchanged.** Promoting fixtures to required jobs strengthens the gate but does not auto-merge or
  alter the human merge decision (Non-Goals).
- **Least privilege.** Workflow jobs use the repository's existing CI token scope; no elevation is required to
  run fixtures.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `pr-test-plan-set-single-source` | the standard FEAT test-plan set is defined once and consumed by both `verify.test` and the CI workflow (no drift) | R1, R3 |
| `pr-test-plan-jobs-on-pr` | each set member runs as a named CI job on `pull_request` | R1 |
| `pr-test-plan-blocking-classification` | each fixture is classified required/advisory; required blocks, advisory reports | R2, R6 |
| `pr-template-references-jobs` | the PR template references CI job names, not a manual checklist, as the gate | R4 |
| `pr-test-plan-stabilize-consumes` | `/sw-stabilize` + `check-gate.sh` consume the promoted job logs via the existing path | R5 |
| `pr-test-plan-checks-gate-verdict` | `checks-gate` verdict covers the promoted jobs under all-checks policy | R6 |
| `pr-test-plan-emitter-freshness` | `dist/` regenerated and fresh | R7 |
| `pr-test-plan-docs-presence` | workflow YAML, checks-gate skill/rule, and CI guide describe the enforcement | R7 |

Standard-tier spec-rigor: checklist (pre-PRD-freeze), analyze + traceability (pre-task-freeze). Per-R
traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/pr-test-plan-ci-enforcement`, delivered in dependency-ordered phases: (1)
  single-sourced test-plan set + classification (R1–R3); (2) CI workflow jobs + PR template (R1, R2, R4); (3)
  stabilize/gate integration (R5, R6); (4) docs + dist + fixtures (R7).
- **Backward compatible.** Advisory classification lets newly-promoted fixtures land non-blocking first, then be
  flipped to required once green on `main`, avoiding a flag-day red gate.
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Promote existing test-plan fixtures to CI jobs rather than rely on a manual description checklist | A manual checklist runs only if an agent remembers; CI jobs run on every PR head, catching doc/workflow regressions before merge (the row-30 complaint). |
| DL-2 | Classify each fixture required vs advisory under the existing `checks-gate` all-checks policy | Not every fixture should hard-block immediately; advisory-first allows safe promotion to required once stable, while staying visible in the readiness verdict. |
| DL-3 | Single-source the standard test-plan set for both `verify.test` and CI | Two lists drift; one manifest guarantees local and CI run the same fixtures. |
| DL-4 | Reuse `check-gate.sh` / `/sw-stabilize` for the new jobs; no new remediation surface | The existing path already consumes CI logs; adding a parallel parser would duplicate and diverge. |

## Open Questions

None.
