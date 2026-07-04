---
id: gap-026-parity-compare-full-dist-bash-subprocess-per-file
type: gap
status: scheduled
schedule: PRD 055
title: Parity compare full-dist scan is O(n) bash subprocess per file
visibility: public
tags: [source:feedback, signal:feedback-prd054-parity-perf-2026-07-04, prd-054, build-chain, testing, parity]
absorbs: []
---

# Parity compare full-dist scan is O(n) bash subprocess per file

_Scheduled to **PRD 055** (amendment A1, Thread F)._

_Captured from feedback signal `feedback-prd054-parity-perf-2026-07-04` during PRD 054 terminal deliver._

## Summary

The `cursor-golden-vs-dist` parity check compares **841 files** under `dist/cursor` against
`scripts/test/fixtures/parity/cursor-golden.manifest`. Despite PRD 042 R27 Python ports, the compare path
still wraps **embedded bash** (`scripts/test/parity_compare.py` → `bash -c` → per-file `shasum` loop +
`find` extra-file scan). PRD 054 dogfood reported ~20 minutes wall clock for this step alone on external
storage; operators see `bash` in `ps`, not `python3`, because the Python entrypoint delegates to bash.

Phase-scope verify runs the full dist compare even when only a handful of scripts changed — defeating PRD 054
scoped-verify latency goals.

## Evidence

| Layer | Behavior |
|-------|----------|
| `test_parity.py` | Loads `harness_parity.py`, which runs embedded bash via `subprocess.run(["bash", "-c", ...])` |
| `run_expect` in harness | Uses `python3` only when path ends in `.py`; after `_harness_runtime.patch_source`, compare path is `.py` |
| `parity_compare.py` | Entry is `python3`, but **internally** spawns another bash subprocess with embedded compare logic |
| Golden manifest | 841 path/hash rows; each row invokes `shasum -a 256` in bash |
| `build-chain-sync --check` | Also runs pytest parity meta suite + `sw generate --all` — amplifies wall clock |

Local timing (same repo, external volume): single compare ~12s; operator report ~20min suggests full
`verify --scope full` + repeated parity passes + I/O-bound sequential hashing.

## Relationship to existing coverage

| Item | Overlap |
|------|---------|
| **PRD 042** R27 | Script port to Python — parity_compare still embeds bash |
| **PRD 054** R4/R5 | Scoped verify tiers — full-dist compare not tier-gated |
| **gap-022** (PRD 055) | Developer test trees in dist — complementary; this gap is compare **performance** |

## Remediation direction

1. Replace embedded bash in `parity_compare.py` with **pure Python** (`hashlib`, single tree walk).
2. **Tier gate:** full 841-file compare reserved for `full` scope, CI, and `build-chain-sync --check`.
3. Retire double-bash wrapper in `harness_parity.py` once pytest calls the Python module directly.
4. Fixture `parity-compare-wall-clock-budget` asserts full-dist compare under documented CI ceiling.

## Acceptance

- `parity_compare.py` runs without spawning bash on the compare hot path.
- `verify --scope phase` does not invoke full dist compare unless widen list matches.
- Fixture proves compare correctness unchanged (happy/missing/extra/hash-diff).
- Document tier matrix in `docs/guides/testing.md`.
