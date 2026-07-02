---
id: gap-022-prd-054-unit-tests-must-be-excluded-from-copy-to
type: gap
status: scheduled
schedule: PRD 055
title: PRD 054 unit_tests must be excluded from copy-to-core and dist emitter
visibility: public
tags: [source:feedback, signal:feedback-prd054-dist-harness-clarity-2026-07-02, prd-054, build-chain, emitter, testing]
absorbs: []
---

# PRD 054 unit_tests must be excluded from copy-to-core and dist emitter

_Scheduled to PRD 054 (`docs/prds/054-unit-testing-strategy/`, amendment A1 TR10)._

_Captured from feedback signal `feedback-prd054-dist-harness-clarity-2026-07-02` during PRD 054
implementation review._

## Summary

PRD 054 A1 places the sole developer test tree at `scripts/unit_tests/`. The build chain today excludes
only `scripts/test/` from `copy-to-core` and from the `sw` emitter — not `unit_tests/` or `tests/`. Without
an explicit exclude, `python3 scripts/build-chain-sync.py` would propagate pytest modules and fixtures into
`core/scripts/` and committed `dist/{cursor,claude-code}/` install trees. Plugin consumers never execute the
developer harness; shipping it adds noise, bloat, and false parity surface area.

Operator feedback (2026-07-02): no value in distributing Shipwright tests as part of the Cursor/Claude
plugin trees — tests exist for developers changing the plugin in the consumer repo.

## Evidence

| Mechanism | Current exclude | `scripts/unit_tests/` fate |
|-----------|-----------------|------------------------------|
| `scripts/copy-to-core.py` | `test/`, `check-frozen.py` | **Synced** to `core/scripts/unit_tests/` |
| `sw/emitter_base.py` | dir name `test` only | **Emitted** to `dist/*/scripts/unit_tests/` |
| `build-chain-sot.json` `coreScripts.excludes` | `test/`, `check-frozen.py` | **Not listed** |

Legacy `scripts/test/` is correctly developer-only. PRD 054's new path name bypasses that guard.

A related partial leak already exists: `scripts/tests/fixtures/canonical/` (dirname `tests`, not `test`) is
mirrored and emitted — referenced only from fixture harness code, not plugin runtime.

## Relationship to existing coverage

| Item | Overlap |
|------|---------|
| **PRD 038** (build-chain SoT) | Documents `scripts/` harness vs `core/scripts/` mirror vs `dist/` emitter — does not name developer test-tree excludes beyond `test/` |
| **GAP-006 / GAP-054** (resolved) | `scripts/`↔`core/scripts/` parity enforcement — complementary; this gap is **what** must not sync |
| **PRD 054 A1 TR10** | Introduces `scripts/unit_tests/` as sole test tree — must pair with build-chain excludes |
| **gap-019** (resolved) | Fixture-tree immutability during deliver verify — different class (runtime mutation vs dist propagation) |

No existing gap or PRD requirement explicitly forbids `unit_tests/` in `dist/`.

## Remediation direction

1. Extend `core/sw-reference/build-chain-sot.json` `coreScripts.excludes` with `unit_tests/` and
   `tests/` (developer fixture trees).
2. Update `scripts/copy-to-core.py` excludes to match the manifest (single source).
3. Update `sw/emitter_base.py` — add `unit_tests` and `tests` to `EXCLUDE_DIR_NAMES` and/or explicit
   `scripts/` first-segment skip list (parity with `test/`).
4. Add emitter or build-chain fixture asserting `dist/cursor/scripts/unit_tests/` and
   `dist/cursor/scripts/test/` are absent after `build-chain-sync.py`.
5. PRD 054 task 8.2 (`docs/guides/testing.md`): state developer test harness is repo-only; plugin install
   trees ship workflow scripts only.

## Acceptance

- `build-chain-sync.py` on a tree with `scripts/unit_tests/` populated leaves no test modules under
  `dist/*/scripts/unit_tests/` or `dist/*/scripts/test/`.
- `run_core_scripts_parity_fixtures.py` still passes; parity applies to runtime harness scripts only.
- Fixture `emitter-excludes-developer-test-trees` (or extend `run_emitter_fixtures.py`) fails closed if
  test paths appear in dist output.
