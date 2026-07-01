---
absorbs: [GAP-076]
brainstorm: docs/brainstorms/2026-07-01-spec-rigor-brainstorm-profile-and-stdlib-coverage-requirements.md
date: 2026-07-01
topic: spec-rigor-brainstorm-profile-and-stdlib-coverage
visibility: public
frozen: true
frozen_at: 2026-07-01
---
# PRD 051 — spec-rigor brainstorm artifact profile & stdlib-only coverage tooling

## Overview

Two small, unrelated-but-similarly-orphaned gaps: `gap-001` (`scripts/spec-rigor-check.py` has `prd`,
`decision`, and `tasks` artifact profiles but no `brainstorm` profile, so non-canonical brainstorm docs —
missing required sections, broken R-ID numbering — can silently reach `/sw-prd` uncaught) and `GAP-076` (no
code-coverage tool exists for `scripts/`; the obvious fix, `pytest-cov`/`coverage.py`, conflicts with the
stdlib-first policy, `rules/sw-python-first.mdc` R11/R12, and `scripts/_sw/depmanifest.json`'s empty
`allowed` list).

`GAP-076` was deliberately captured rather than resolved on the spot (memory #2266) pending a dedicated
brainstorm on approach. That brainstorm (see `brainstorm:` above) investigated the actual constraint —
`scripts/test/_runner.py` invokes every `.test`/fixture-suite as a **subprocess**, so any coverage mechanism
must instrument across subprocess boundaries — and confirmed a fully stdlib-compliant path exists: the
`trace` module (`python -m trace --count --coverdir=<dir>`), the same subprocess-boundary problem
`coverage.py` solves via `COVERAGE_PROCESS_START`, solved here with zero non-stdlib imports. Per operator
confirmation during the brainstorm, this PRD ships that approach rather than a `depmanifest.json` exception
or a status-quo close of `GAP-076`.

## Goals

1. `spec-rigor-check.py` gains a `brainstorm` artifact profile, mechanically enforcing
   `requirements-sections.md`'s required sections and R-ID hygiene rules, closing the same class of gap the
   `prd`/`decision`/`tasks` profiles already close for their artifact types.
2. `scripts/` gains a first, stdlib-only, opt-in line-coverage mechanism with zero new entries in
   `scripts/_sw/depmanifest.json`.
3. Neither change alters default (non-coverage, non-brainstorm-artifact) test/CI behavior — both are
   additive.
4. `gap-001` and `GAP-076` flip to genuinely `resolved` once both ship with passing fixtures.

## Non-Goals

- Branch/statement-level coverage — the `trace --count` mechanism reports line-execution counts only; a
  future gap can revisit richer coverage instrumentation if line coverage proves insufficient.
- Enforcing a minimum coverage percentage as a CI gate — this PRD establishes the mechanism and a first
  baseline report only; threshold enforcement is a follow-on decision once a baseline exists.
- Per-PR diff-coverage reporting or historical coverage-trend tracking.
- Retrofitting the `brainstorm` artifact profile onto already-frozen historical brainstorm docs — the gate
  applies going forward from `/sw-brainstorm`'s next write.
- Reopening or editing any `complete` PRD in place.

## Requirements

### Thread A — spec-rigor brainstorm artifact profile (`gap-001`)

- **R1** (origin: `gap-001`) — `scripts/spec-rigor-check.py` MUST accept `--artifact brainstorm` and validate
  the target document against `skills/brainstorm/references/requirements-sections.md`'s required sections:
  Summary, Problem Frame, Key Decisions, Requirements, Success Criteria, Scope Boundaries, and Open Questions
  (Open Questions may be explicitly marked "none" rather than omitted, but must not be entirely absent as a
  heading).
- **R2** (origin: `gap-001`, brainstorm R2) — The `brainstorm` profile MUST validate R-ID hygiene: at least
  one `R<n>` requirement present, monotonically increasing, no duplicate IDs. Non-contiguous numbering across
  amendment boundaries (e.g., `R11+` continuing after a parent document ending at `R10`) MUST NOT be flagged
  as an error — the gate checks strict monotonic increase, not contiguity.
- **R3** (origin: `gap-001`) — Missing required sections and R-ID violations MUST be `error` severity,
  consistent with the existing `prd`/`decision` profiles' severity conventions.
- **R4** (origin: `gap-001`, D5) — The `brainstorm` profile MUST be a **hard-blocking** gate at `/sw-brainstorm`
  Phase 2 write (same posture as `spec-rigor-check.py --artifact prd` on `/sw-prd`) and remain available to
  `/sw-doc-review` for advisory re-check on draft PRDs sourced from brainstorms.
- **R5** (origin: `gap-001`) — A regression fixture MUST prove: a brainstorm doc missing a required section
  (e.g., no Success Criteria heading) fails the gate; a compliant doc passes.

### Thread B — stdlib-only coverage tooling for `scripts/` (`GAP-076`)

- **R6** (origin: `GAP-076`) — A coverage collection mechanism MUST be introduced using only the Python
  standard library (the `trace` module), adding zero entries to `scripts/_sw/depmanifest.json`.
- **R7** (origin: `GAP-076`) — `scripts/test/_runner.py` MUST support an opt-in coverage mode (flag or
  environment variable) that launches `.test`/suite subprocesses via `python -m trace --count
  --coverdir=<dir>` instead of a bare `sys.executable` invocation, without changing default (non-coverage)
  behavior.
- **R8** (origin: `GAP-076`) — A merge/report step MUST aggregate the per-process `.cover` count files
  produced by R7 into one summary report: executed-lines/total-lines per script under `scripts/`, plus an
  aggregate percentage across the run.
- **R9** (origin: `GAP-076`) — Coverage collection MUST be strictly additive: the default
  `verify`/`run-manifest`/CI test invocation path MUST run identically (same exit codes, same duration
  characteristics) when coverage mode is not enabled.
- **R10** (origin: `GAP-076`) — This PRD establishes the mechanism and a first baseline report only; no
  minimum coverage percentage is enforced as a CI gate in this scope.
- **R11** (origin: `GAP-076`) — A regression fixture MUST prove: running coverage mode over a small
  representative test subset produces a report that correctly identifies at least one executed line and one
  un-executed line in a known target script.

## Technical Requirements

- **TR1** (R1/R2/R3) — Add a `brainstorm` branch to `spec-rigor-check.py`'s `_run()` dispatcher (alongside
  the existing `prd`/`decision`/`tasks` branches), parsing required headings via the same markdown-heading
  scan already used for `prd`, and R-ID extraction/monotonicity check reusing the existing R-ID regex helper
  if one exists in the module, else adding one scoped to this branch.
- **TR2** (R4, D5) — Wire `spec-rigor-check.py --artifact brainstorm` as a **blocking** post-write gate in
  `core/commands/sw-brainstorm.md` Phase 2 (halt on exit `20`, same as `/sw-prd`); note advisory re-check
  availability to `/sw-doc-review`. No change to `/sw-doc-review`'s command file when artifact-type detection
  is already generic.
- **TR3** (R5) — Fixture `spec-rigor-brainstorm-profile-required-sections`: one negative case (missing
  Success Criteria) and one positive case using `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-
  requirements.md` (the exemplar already cited in `requirements-sections.md`) or an equivalent compliant
  fixture doc.
- **TR4** (R6/R7, D6) — Implement the coverage mode in `scripts/test/_runner.py`: a new `--coverage` flag (or
  `SW_COVERAGE=1` env var) on `run_test_file`/`run_suite_module`/`run_manifest` that swaps subprocess
  invocations from `[sys.executable, str(path)]` to `[sys.executable, "-m", "trace", "--count",
  f"--coverdir={coverdir}", str(path)]`. When coverage is enabled, `run_suite_module` for `.py` suites MUST
  use the same subprocess+`trace` path (not in-process `importlib`) so subprocess-boundary coverage matches
  `.test` files. `coverdir` defaults to gitignored scratch `.cursor/sw-coverage/<run-id>/` (add to
  `.gitignore` if absent); no committed coverage artifacts in v1.
- **TR5** (R8) — Add a `coverage-report` subcommand (or a post-run step in `run-manifest`/`verify`) that
  parses all `.cover` files under the run's `coverdir`, sums executed vs. total countable lines per source
  file under `scripts/`, and prints a summary table plus an aggregate percentage; keep the parser
  stdlib-only (`trace`'s own `.cover` file format is plain text, parseable without additional imports).
- **TR6** (R9) — Ensure the coverage-mode subprocess command swap is behind the flag/env-var check only; add
  a fixture asserting identical exit codes for a representative `.test` file run with and without coverage
  mode enabled.
- **TR7** (R11) — Add a synthetic fixture script under `scripts/test/fixtures/` with one deliberately
  unreached conditional branch; fixture `stdlib-coverage-report-executed-and-unexecuted-lines` runs it under
  coverage mode and asserts the report shows ≥1 executed line and ≥1 un-executed line for that file.
- Emitter parity: no `core/skills/` doc changes required for TR4–TR7; TR2's `core/commands/sw-brainstorm.md`
  update requires `python3 scripts/build-chain-sync.py` before freeze (R32 Python entrypoint model /
  build-chain SoT) if `core/commands/` mirrors to `dist/`.

## Security & Compliance

- No new dependencies, no new network/credential surface — `trace` is Python stdlib; the coverage mechanism
  reads/writes only local scratch files under `.cursor/`.
- `scripts/_sw/depmanifest.json`'s `allowed: []` list remains unchanged (R6) — this PRD is evidence the
  stdlib-first policy (`rules/sw-python-first.mdc` R11/R12) can accommodate coverage tooling without an
  exception.

## Testing Strategy

- `spec-rigor-brainstorm-profile-required-sections` (R1–R3/R5, TR1/TR3).
- `stdlib-coverage-mode-no-behavior-change` (R9, TR6) — same test run, same exit code, with/without
  `--coverage`.
- `stdlib-coverage-report-executed-and-unexecuted-lines` (R11, TR7).
- Register all three fixtures in `core/sw-reference/pr-test-plan.manifest.json`.
- No regression to the existing `prd`/`decision`/`tasks` spec-rigor profiles or to `scripts/test/_runner.py`'s
  default (non-coverage) invocation path.
- Re-run `gap_backlog.py check` after shipping to confirm `gap-001` and `GAP-076` both show `resolved`.

## Rollout Plan

1. Implement Thread A (R1–R5, TR1–TR3) first — small, independent, immediately useful for any brainstorm
   written after this PRD ships (including this PRD's own future siblings).
2. Implement Thread B (R6–R11, TR4–TR7) — independent of Thread A; can parallelize if phase capacity allows.
3. On ship, flip `gap-001` and `GAP-076` via `gap_backlog.py flip --resolve` (or automatically if PRD 048's
   mechanical flip has shipped by then).

## Decision Log

- **D1 (2026-07-01):** Resolve GAP-076's deliberately-deferred design question (custom stdlib coverage vs.
  scoped `depmanifest.json` exception vs. status quo) in favor of stdlib `trace`-module coverage, after
  investigating and confirming the concrete subprocess-boundary constraint (`scripts/test/_runner.py` invokes
  tests via `subprocess.run([sys.executable, ...])`) and presenting it alongside the three alternatives for
  explicit operator confirmation.
- **D2 (2026-07-01):** Bundle `gap-001` and `GAP-076` into one PRD despite being topically unrelated, per
  explicit operator direction — both are small, orphaned backlog items with no natural open-PRD home.
- **D3 (2026-07-01):** Coverage is opt-in/informational only in this PRD's scope (R10) — no CI gate — to
  avoid destabilizing CI with a brand-new, unbaselined mechanism; threshold enforcement is deferred to a
  future decision once a baseline exists.
- **D4 (2026-07-01):** R2's monotonicity check explicitly permits non-contiguous R-ID numbering across
  amendment boundaries, to avoid false-positive failures on the documented, intentional `R11+`-after-`R10`
  amendment pattern (`requirements-sections.md`'s own R-ID rules).
- **D5 (2026-07-01, doc-review):** The `brainstorm` artifact profile is **hard-blocking** at `/sw-brainstorm`
  Phase 2 write — consistent with the `prd` profile on `/sw-prd` — not advisory-only at `/sw-doc-review`.
- **D6 (2026-07-01, doc-review):** Coverage `coverdir` output is **gitignored scratch** under
  `.cursor/sw-coverage/<run-id>/`; the aggregate summary prints to stdout/CI log only — no committed coverage
  artifacts in v1.

## Open Questions

none
