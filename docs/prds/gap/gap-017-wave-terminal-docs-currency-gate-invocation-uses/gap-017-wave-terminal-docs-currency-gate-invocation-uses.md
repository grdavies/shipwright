---
id: gap-017-wave-terminal-docs-currency-gate-invocation-uses
type: gap
status: scheduled
schedule: PRD 050 A3
title: wave-terminal docs-currency-gate invocation uses wrong argv contract
visibility: public
tags: [source:feedback, prd-050-a3, signal:feedback-prd-052-deliver-terminal-observations-2026-07-02, prd-052]
source_pr: 52
absorbs: []
---

# wave-terminal docs-currency-gate invocation uses wrong argv contract

_Captured from feedback signal `feedback-prd-052-deliver-terminal-observations-2026-07-02` during PRD 052 terminal deliver._

## Summary

`wave_terminal.run_docs_currency_gate()` invokes `docs-currency-gate.py` with a single flag-style argument
(`--state-root <root>`), but the script expects **four positional arguments**:

1. repo root
2. state root
3. deliver state JSON path
4. deliver plan JSON path

The mismatch raises `IndexError: list index out of range` at `sys.argv[3]` and hard-blocks terminal ship
(`terminal-local-prepare`, `terminal-pr-prepare`, and related paths) before living-doc drift can be evaluated.

## PRD 052 evidence

- Operator blocked on automated terminal PR path; created manual PR via `gh` (`feat/test-suite-registration-single-source` → `main`).
- Repro: `python3 scripts/docs-currency-gate.py --state-root .` → traceback (exit 1).
- Correct contract (fixtures): `python3 scripts/docs-currency-gate.py <root> <state_root> <state.json> <plan.json>`.

## Root cause

```564:574:scripts/wave_terminal.py
def run_docs_currency_gate(root: Path) -> None:
    ...
    proc = subprocess.run(
        [sys.executable, str(script), "--state-root", str(root)],
```

```17:20:scripts/docs-currency-gate.py
    root = Path(sys.argv[1])
    state_root = Path(sys.argv[2])
    state = json.loads(Path(sys.argv[3]).read_text())
    plan = json.loads(Path(sys.argv[4]).read_text()) if Path(sys.argv[4]).is_file() else {}
```

`wave.py docs-currency` dispatches positional args correctly via `_python("docs-currency-gate.py", root, rest)`.

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **gap-013** | Manual terminal PR via `gh` — template validation gap; PRD 052 operator also used manual PR, but this argv bug is the immediate hard-block |
| **gap-007** | INDEX status stale after deliver — separate living-docs reconcile gap |
| **gap-015** | visibility public at spec-seed — PRD 052 unblocked by adding frontmatter manually |

## Remediation direction

1. Align `run_docs_currency_gate()` with the four-arg contract (derive state/plan paths from `root`).
2. Add fixture asserting terminal ship calls docs-currency-gate without traceback.
3. Optionally add argparse to `docs-currency-gate.py` for `--state-root` shim with deprecation window.

## Schedule

**PRD 050 A3** (`A3-wave-terminal-docs-currency-gate-argv-contract.md`) — absorbed 2026-07-02.