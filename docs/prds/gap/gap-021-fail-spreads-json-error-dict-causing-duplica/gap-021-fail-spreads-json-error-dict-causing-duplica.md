---
id: gap-021-fail-spreads-json-error-dict-causing-duplica
type: gap
status: scheduled
schedule: PRD 050 A6
title: fail() spreads JSON error dict causing duplicate error kwarg TypeError
visibility: public
tags: [source:feedback, recallium:2280, recallium:2295, signal:feedback-recallium-debug-2026-07-02]
source_pr:
absorbs: []
---

# fail() spreads JSON error dict causing duplicate error kwarg TypeError

_Captured from Recallium debug memories #2280 and #2295 during `/sw-feedback` Recallium triage (2026-07-02)._

## Summary

Several wave subprocess error paths call `fail(err.get("error", ...), **err)` (or equivalent `**out` spread)
when forwarding JSON error payloads. If the parsed dict already contains an `"error"` key, Python raises
`TypeError: fail() got multiple values for argument 'error'`, masking the underlying subprocess failure
(dirty worktree teardown, `gh pr create` failure, forward-merge failure, etc.).

## Evidence

| Recallium | Context |
|-----------|---------|
| **#2280** | `cmd_phase_teardown_run` — phase-teardown subprocess failure masked when worktree dirty |
| **#2295** | `host_pr_create` — `gh pr create` failure during PRD 052 terminal ship masked by same TypeError |

## Affected call sites

```488:488:scripts/wave_lifecycle.py
            fail(err.get("error", "forward-merge failed"), exit_code=proc.returncode, **err)
```

```517:517:scripts/wave_lifecycle.py
        fail(err.get("error", "phase teardown failed"), exit_code=proc.returncode, **err)
```

```644:644:scripts/wave_lifecycle.py
            fail(err.get("error", "materialize provision failed"), exit_code=20, **err)
```

```633:633:scripts/wave_terminal.py
        fail(resolved.get("error", "phase-pr-base"), exit_code=20, **{k: v for k, v in resolved.items() if k != "verdict"})
```

```648:648:scripts/wave_terminal.py
            fail(out.get("error") or out.get("reason", "phase-pr-create-failed"), exit_code=20, **out)
```

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **gap-009** | Orphan worktree after failed provision — teardown failure symptom; this gap is the error-forwarding footgun that hides root cause |
| **gap-013** | Terminal PR template validation — orthogonal to fail() spread |
| **gap-017** | docs-currency-gate argv — co-observed in #2295 but separate bug |
| **PRD 050** | Deliver terminal robustness — natural schedule target when amendment added |

## Remediation direction

1. Introduce a shared `fail_from_payload(message_key="error", payload: dict)` helper that strips `error` before `**extra` spread (or use `extra={k:v for k,v in payload.items() if k != "error"}`).
2. Fix the five call sites above; grep for similar `fail(..., **dict_with_error)` patterns in wave scripts.
3. Fixture: subprocess stub emitting `{"error": "real cause"}` must surface `real cause`, not TypeError.

## Schedule

**PRD 050 A6** (`A6-subprocess-json-fail-payload-forwarding.md`) — absorbed 2026-07-02.
