---
date: 2026-07-02
amends: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
absorbs: [gap-021-fail-spreads-json-error-dict-causing-duplica]
signal: feedback-recallium-debug-2026-07-02
frozen: true
frozen_at: 2026-07-02
visibility: public
---

# Amendment A6: subprocess JSON fail-payload forwarding (gap-021)

## Overview

`gap-021` captures a recurring error-forwarding footgun in deliver lifecycle and terminal paths: subprocess
error handlers call `fail(err.get("error", ...), **err)` (or `**out`) when forwarding JSON payloads. When the
parsed dict already contains an `"error"` key, Python raises `TypeError: fail() got multiple values for
argument 'error'`, masking the real failure (dirty worktree teardown, `gh pr create` failure, forward-merge
failure). Recallium #2280 and #2295 document the failure mode during PRD 048/052 deliver sessions.

Parent PRD 050 Thread B (R7–R12) covers orphan worktree adoption and stall classification; Thread C (R13–R16)
covers terminal-finalize idempotency and PR body validation. Neither thread specifies **safe JSON error
payload forwarding** into module-local `fail()` helpers. `wave_failure.py` already implements the correct
pattern (`extra.pop("error", None)` before emit); lifecycle and terminal modules do not.

This amendment extends Thread B/C with **R55–R58** and closes **gap-021** when shipped with green fixtures —
not narrative closure.

## Context

**Evidence (2026-07-02):**

| Recallium | Call site | Masked failure |
|-----------|-----------|----------------|
| **#2280** | `wave_lifecycle.py` `cmd_phase_teardown_run` L517 | Dirty worktree `git worktree remove` |
| **#2295** | `wave_terminal.py` `host_pr_create` L648 | `gh pr create` host failure |

**Additional call sites (same pattern):**

```488:488:scripts/wave_lifecycle.py
            fail(err.get("error", "forward-merge failed"), exit_code=proc.returncode, **err)
```

```644:644:scripts/wave_lifecycle.py
            fail(err.get("error", "materialize provision failed"), exit_code=20, **err)
```

```633:633:scripts/wave_terminal.py
        fail(resolved.get("error", "phase-pr-base"), exit_code=20, **{k: v for k, v in resolved.items() if k != "verdict"})
```

**Canonical pattern (already shipped):**

```71:73:scripts/wave_failure.py
def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)
```

**Relationship to gap-009:** gap-009 captures orphan worktree state after failed provision; gap-021 is the
error-forwarding defect that **hides** the underlying teardown/provision failure from operators and logs.

**Relationship to gap-017:** Co-observed in #2295 during PRD 052 terminal ship; argv mismatch (gap-017)
is a separate hard-block.

## Goals

1. All deliver lifecycle and terminal subprocess error paths forward JSON payloads without duplicate `error`
   kwarg TypeError.
2. A shared helper (or consistent `extra.pop("error", None)` contract) is used across `wave_lifecycle.py`
   and `wave_terminal.py`, aligned with `wave_failure.py`.
3. Operators and fixtures surface the underlying subprocess error string, not a Python TypeError.
4. `gap-021` flips to `resolved` when R55–R58 ship with green fixtures.

## Non-Goals

- Replacing every module-local `fail()` with a single global import (out of scope — shared helper or inline
  pop only).
- Fixing docs-currency-gate argv (gap-017 / A3) or terminal PR template validation (gap-013 / R16).
- Changing subprocess JSON schema for wave scripts wholesale.

## Requirements

### Thread B/C extension — subprocess JSON fail-payload forwarding

- **R55** (origin: gap-021 remediation #1) — Introduce a shared `fail_from_payload(message: str, payload:
  dict[str, Any], *, exit_code: int = 2, message_key: str = "error")` helper (in `scripts/wave_state.py`,
  `scripts/wave_failure.py`, or a small `scripts/wave_errors.py` module) that extracts the message from
  `payload[message_key]` with fallback, strips `message_key` from extras before spread, and emits the same
  JSON shape as existing module `fail()` functions. MUST match `wave_failure.fail` semantics
  (`extra.pop("error", None)`).
- **R56** (origin: gap-021 remediation #2) — Replace unsafe `fail(..., **err)` / `fail(..., **out)` call
  sites in `wave_lifecycle.py` (forward-merge L488, phase-teardown L517, materialize-provision L644) and
  `wave_terminal.py` (`host_pr_create` L633, L648) with `fail_from_payload` or equivalent inline
  `extra.pop("error", None)` before spread. Grep deliver-touched wave modules for the same anti-pattern.
- **R57** (origin: gap-021 remediation #3) — Fixture `deliver-fail-payload-forwards-subprocess-error` MUST
  assert that a subprocess stub returning `{"error": "real cause", "halt": "blocked"}` surfaces
  `"real cause"` in JSON output with exit code from payload (or caller default), not `TypeError`.
- **R58** (origin: gap-021 closure) — On ship, flip
  `gap-021-fail-spreads-json-error-dict-causing-duplica` unit frontmatter to `resolved` referencing PRD
  050 A6 only after R55–R57 fixtures are green.

## Technical Requirements

- **TR31** (R55) — Add shared helper; document import path in `.sw/layout.md` deliver error-forwarding note
  (if present) or amendment task notes only.
- **TR32** (R56) — Patch five known call sites; run ripgrep for `fail\([^)]+\*\*(err|out|resolved)` in
  `wave_lifecycle.py`, `wave_terminal.py`, `wave_deliver_loop.py`; fix deliver-surface matches or document
  exclusions in task notes.
- **TR33** (R57–R58) — Add harness under `scripts/test/fixtures/deliver-concurrency/`; register
  `deliver-fail-payload-forwards-subprocess-error` in `core/sw-reference/pr-test-plan.manifest.json` as
  `required`; wire gap flip into task 5.2 extension.

Roll into parent Thread B/C (tasks 2.x / 3.x) after A4 resume-reconcile work (Decision D-A6-2).

## Testing Strategy

Add to parent Testing Strategy:

- `deliver-fail-payload-forwards-subprocess-error` (R57, TR33)

Preserve `orphan-phase-worktree-adopt-or-teardown` (R7) and A4
`resume-reconcile-unpushed-local-merge-promotes`. No regression to A3
`terminal-docs-currency-gate-invocation-valid`.

## Rollout Plan

1. Land TR31 + R55 (shared helper aligned with `wave_failure.fail`).
2. Land TR32 + R56 (five call sites + grep sweep).
3. Land TR33 + R57 fixture registration.
4. On ship: flip gap-021 to `resolved`; attach fixture output to PR.

## Decision Log

- **D-A6-1 (2026-07-02):** Host gap-021 on **PRD 050 A6** (Thread B/C extension) — deliver lifecycle +
  terminal error surfacing; PRD 042 cross-platform standardization is `complete`.
- **D-A6-2 (2026-07-02):** Reuse `wave_failure.fail` pop semantics via shared helper rather than importing
  `wave_failure` from lifecycle (avoid circular imports — thin `wave_errors.py` acceptable).
- **D-A6-3 (2026-07-02):** Fixture uses subprocess stub JSON, not live dirty-worktree repro — deterministic
  offline CI.

## Security & Compliance

- Error message forwarding only; no new secret or network surface.

## Open Questions

None — gap-021 remediation direction is fully specified.
