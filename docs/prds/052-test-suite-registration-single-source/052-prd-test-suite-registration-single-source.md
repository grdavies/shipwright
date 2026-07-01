---
date: 2026-07-01
topic: test-suite-registration-single-source
absorbs: [GAP-075]
visibility: public
frozen: true
frozen_at: 2026-07-01
---
frozen: true
frozen_at: 2026-07-01

# PRD 052 — Test-suite registration single-source

## Overview

`GAP-075` documents registration drift across four independently maintained fixture lists
(`core/sw-reference/pr-test-plan.manifest.json`, `scripts/test/run_verify_bundle.py` `SUITES`,
`.github/workflows/ci.yml`, and `CONTRIBUTING.md`). PRD 016 R3 and PRD 042 R27 intended a single source of
truth; in practice the manifest and verify bundle each hold ~52 entries with only **five** in common, and six
named suites (`build_chain_sot`, `capability`, `fanout`, `guardrail_matrix`, `hook`, `relocation`) are wired
into none of the enforcement surfaces (one appears only in CONTRIBUTING prose).

This PRD restores a fail-closed registration model: every `scripts/test/run_*_fixtures.py` on disk is
classified in one committed registry; derived consumer lists (verify bundle, PR test-plan manifest subset,
CONTRIBUTING mentions, workflow generator inputs) are generated or drift-checked against that registry. It
closes the retrospective gap left when PRD 042 shipped R27 porting without completing manifest-registration
for all suites.

This is a **Standard-tier** PRD (bounded CI/registry infrastructure; no brainstorm).

## Goals

- Every `run_*_fixtures.py` suite is classified exactly once in a committed registry with explicit lanes
  (`pr-ci`, `verify`, `ci-yml`, `doc`, `internal` — see Technical Requirements).
- The six GAP-075 orphan suites are registered and run on at least one enforcement path (verify and/or PR
  test-plan CI) with `required`/`advisory` classification.
- `run_verify_bundle.py` `SUITES` is derived from the registry — no hand-maintained duplicate list.
- `pr-test-plan.manifest.json` entries remain the PR CI source of truth, but a drift fixture asserts manifest
  ⊆ registry and workflow matches `generate-pr-test-plan-ci-workflow.py` output.
- `run_pr_test_plan_fixtures.py` calls the Python workflow generator (not the removed `.sh` shim).
- `GAP-075` flips to `resolved` when this PRD ships with passing drift fixtures.

## Non-Goals

- Registering all 115+ discovered suites as required PR test-plan CI jobs (granularity DoS; meta suites stay
  `internal`).
- Changing `checks-gate` readiness semantics or auto-merge behavior.
- pytest/coverage tooling (PRD 051 / `GAP-076`).
- Amending frozen PRD 042 or PRD 016 in place.
- Collapsing `.github/workflows/ci.yml` (emitter/parity smoke jobs) into `pr-test-plan-ci.yml` — the two
  workflows serve different scopes; this PRD documents and registry-classifies them, not merges them blindly.

## Requirements

- **R1** — Introduce `core/sw-reference/suite-registry.json` as the authoritative classification of every
  `scripts/test/run_*_fixtures.py` (and non-suite entries such as `docs-link-check.py` where applicable).
  Each entry MUST declare: `id`, `script`, `lanes` (non-empty subset of `pr-ci`, `verify`, `ci-yml`, `doc`,
  `internal`), and when `pr-ci` is present, `classification` (`required`|`advisory`) plus `ciJobName`.
- **R2** — `scripts/test/run_verify_bundle.py` MUST load its suite list from `suite-registry.json` entries
  where `verify` ∈ `lanes`, in stable sort order — the hardcoded `SUITES` array is removed.
- **R3** — The six GAP-075 orphan suites MUST be registered with at least `verify` lane (and `pr-ci` where
  the suite guards cross-PR regressions): `run_build_chain_sot_fixtures.py`, `run_capability_fixtures.py`,
  `run_fanout_fixtures.py`, `run_guardrail_matrix_fixtures.py`, `run_hook_fixtures.py`,
  `run_relocation_fixtures.py`. Initial classification: `build_chain_sot`, `hook`, `guardrail_matrix` →
  `required` in verify; `capability`, `fanout`, `relocation` → `advisory` in verify unless fixture audit
  proves blocking behavior (task list may adjust with evidence).
- **R4** — `core/sw-reference/pr-test-plan.manifest.json` MUST be generated or validated from registry
  `pr-ci` entries (fail-closed drift check on CI). Manifest edits during this PRD MUST include regenerating
  `.github/workflows/pr-test-plan-ci.yml` via `scripts/generate-pr-test-plan-ci-workflow.py`.
- **R5** — A new fixture suite `run_suite_registry_fixtures.py` MUST assert: (a) every on-disk
  `run_*_fixtures.py` has a registry entry; (b) no registry entry references a missing script; (c) manifest
  `pr-ci` set matches registry; (d) committed workflow matches generator output; (e) verify bundle order
  matches registry `verify` lane.
- **R6** — `scripts/test/run_pr_test_plan_fixtures.py` MUST invoke `generate-pr-test-plan-ci-workflow.py`
  (three-arg CLI) instead of the removed `generate-pr-test-plan-ci-workflow.sh` wrapper.
- **R7** — `CONTRIBUTING.md` fixture-suite section MUST either be generated from registry `doc` lane entries
  or guarded by a drift check in `run_suite_registry_fixtures.py` (hand list allowed only when registry
  `doc` lane matches).
- **R8** — Operator docs (`docs/guides/configuration.md` PR test-plan section) MUST document the registry →
  manifest → workflow → verify derivation chain and the regen command with full CLI args.

## Technical Requirements

- **TR1 — Registry schema.** Add `core/sw-reference/suite-registry.schema.json`; validate in
  `run_suite_registry_fixtures.py` and optionally `scripts/check-gate.py` advisory hook. Version field
  `version: 1`.
- **TR2 — Generator helper.** Add `scripts/suite_registry.py` with `discover_suites(root)`,
  `load_registry(root)`, `verify_lane_entries()`, `manifest_entries()`, `verify_bundle_entries()` —
  reusing `scripts/test/_runner.py::discover_suites` for discovery, not reimplementing glob rules.
- **TR3 — Verify bundle migration.** Replace `SUITES = [...]` in `run_verify_bundle.py` with
  `suite_registry.verify_bundle_entries(root)`; preserve current invocation semantics (`main()` per suite).
- **TR4 — Manifest validation path.** Prefer validate-and-fail in Phase 1: fixture compares committed manifest
  to registry `pr-ci` projection; optional follow-on generator subcommand `suite-registry.py emit-manifest`
  is allowed but not required if validation + manual sync is sufficient for Standard scope.
- **TR5 — PR CI regen.** Document and enforce in task list:
  `python3 scripts/generate-pr-test-plan-ci-workflow.py core/sw-reference/pr-test-plan.manifest.json .github/workflows/pr-test-plan-ci.yml .`
- **TR6 — Register new drift fixture** in `pr-test-plan.manifest.json` as `required` and regen workflow.
- **TR7 — Emitter/docs.** Registry and schema live under `core/sw-reference/` (`coreAuthoredAllowlist`);
  update `docs/guides/configuration.md`; no `core/commands` changes expected.

## Security & Compliance

- No new secrets, network calls, or elevated CI token scope — registry is static JSON; generators read repo
  files only.
- Fail-closed drift checks prevent silent removal of security-relevant suites (`hook`, `guardrail_matrix`,
  `secret_scan` class) from enforcement paths.
- Default-branch policy unchanged: doc/registry commits land via normal PR review, not bare `main` writes.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `run_suite_registry_fixtures.py` | registry ↔ disk ↔ manifest ↔ verify ↔ workflow parity | R1, R4, R5, R7 |
| `run_pr_test_plan_fixtures.py` (updated) | workflow generator uses `.py` CLI; single-source checks pass | R4, R6 |
| `run_build_chain_sot_fixtures.py` | (existing) passes when wired into verify | R3 |
| `run_hook_fixtures.py` | (existing) passes when wired into verify | R3 |
| `run_guardrail_matrix_fixtures.py` | (existing) passes when wired into verify | R3 |
| `run_capability_fixtures.py`, `run_fanout_fixtures.py`, `run_relocation_fixtures.py` | (existing) pass when wired | R3 |

## Rollout Plan

1. **Phase 1 — Registry + drift fixture (read-only classification):** land `suite-registry.json` with all
   suites classified; `run_suite_registry_fixtures.py` fails until lists align (drives migration).
2. **Phase 2 — Verify derivation:** switch `run_verify_bundle.py` to registry; register six orphans in verify
   lane; green `verify.test`.
3. **Phase 3 — PR CI alignment:** sync manifest `pr-ci` entries with registry policy for suites that belong
   on FEAT PRs; regen `pr-test-plan-ci.yml`; fix generator shim reference.
4. **Phase 4 — Docs + GAP close:** update configuration guide and CONTRIBUTING drift guard; flip `GAP-075` to
   `resolved` in `docs/prds/GAP-BACKLOG.md`.

## Decision Log

- **D1 (2026-07-01):** Standalone PRD 052 rather than amending PRD 042 (complete/frozen) or PRD 051 (unrelated
  coverage thread). Absorbs `GAP-075` explicitly.
- **D2 (2026-07-01):** Use a new `suite-registry.json` rather than overloading `pr-test-plan.manifest.json`
  alone — verify bundle and `ci.yml` jobs need lanes manifest was never designed to express (PRD 016 scoped
  manifest to FEAT PR test-plan only).
- **D3 (2026-07-01):** Phase 1 validates manifest against registry before auto-emitting manifest — reduces
  blast radius vs rewriting 52 manifest rows in one commit without classification review.
- **D4 (2026-07-01):** Do not require manifest == verify sets (PRD 016 R3 original intent) in one flag day —
  registry makes the relationship explicit: intersection may grow over time; drift fixture prevents silent
  skew.

## Open Questions

None — classification defaults for the six orphans are initial-task evidence gates (R3); adjust in task list
if fixtures prove blocking.
