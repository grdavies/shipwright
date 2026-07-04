---
date: 2026-07-04
amends: docs/prds/055-workflow-fidelity-gap-closure/055-prd-workflow-fidelity-gap-closure.md
absorbs:
  - gap-026-parity-compare-full-dist-bash-subprocess-per-file
  - gap-027-post-merge-full-verify-lacks-wall-clock-budget
frozen: true
frozen_at: 2026-07-04
---

# Amendment A1: PRD 054 verify performance gaps (parity compare + post-merge watchdog)

## Overview

PRD 054 terminal deliver dogfood surfaced two gaps not in the original nine absorbed units. This amendment
schedules **gap-026** and **gap-027** into PRD 055 as **Thread F** without re-opening frozen PRD 054.

Parent PRD 055 namespace continues at **R28–R32**.

## Requirements (Thread F)

- **R28** (gap-026) — Pure Python parity compare; no bash hot path in `parity_compare.py`.
- **R29** (gap-026) — FullName dist compare only in `full` scope + CI + `build-chain-sync --check`.
- **R30** (gap-026) — Fixture proves compare correctness unchanged after port.
- **R31** (gap-027) — Per-suite progress + halt on verify budget exhaustion.
- **R32** (gap-027) — `verify.watchdog.maxMinutes` config; scoped post-merge default when widen list absent.

## Technical Requirements

- **TR10** (R28–R30) — Python parity compare; tier gate; testing guide update.
- **TR11** (R31–R32) — Verify watchdog; config schema; `verify-watchdog-exhaustion` fixture.

## Non-Goals

- Parallelizing `_runner.py verify` internally (PRD 054 non-goal).
- Re-opening frozen PRD 054.
