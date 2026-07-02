---
date: 2026-07-02
amends: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
absorbs: [gap-017-wave-terminal-docs-currency-gate-invocation-uses]
signal: feedback-prd-052-deliver-terminal-observations-2026-07-02
frozen: true
frozen_at: 2026-07-02
visibility: public
---

# Amendment A3: wave-terminal docs-currency-gate argv contract (gap-017)

## Overview

`gap-017` captures a hard-block on automated terminal ship observed during PRD 052 deliver: `wave_terminal.run_docs_currency_gate()` invokes `docs-currency-gate.py` with a single `--state-root` flag, but the script expects **four positional arguments** (repo root, state root, deliver state JSON, deliver plan JSON). The mismatch raises `IndexError` at `sys.argv[3]` before living-doc drift is evaluated, forcing operators to create terminal PRs manually via `gh`.

Parent PRD 050 Thread C (R13–R16) covers terminal-finalize idempotency and PR body template validation (R16 / gap-013) but does not specify the **docs-currency gate invocation contract** on the terminal ship path. `wave.py docs-currency` already dispatches positional args correctly; only `wave_terminal.py` is wrong.

This amendment extends Thread C with **R43–R46** and closes **gap-017** when shipped with green fixtures — not narrative closure.

## Context

**PRD 052 evidence (2026-07-02):**

- Operator blocked on `terminal-local-prepare` / `terminal-pr-prepare`; manual PR created (`feat/test-suite-registration-single-source` → `main`).
- Repro: `python3 scripts/docs-currency-gate.py --state-root .` → traceback (exit 1).
- Correct contract (fixtures): `python3 scripts/docs-currency-gate.py <root> <state_root> <state.json> <plan.json>`.

**Root cause:**

```564:571:scripts/wave_terminal.py
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

**Relationship to gap-013:** gap-013 covers terminal PR **body template validation**; gap-017 is the **immediate argv crash** that prevents reaching template validation on the automated path. Both may contribute to manual `gh pr create` during the same deliver session.

## Goals

1. Terminal ship paths (`terminal-local-prepare`, `terminal-pr-prepare`, and any other `run_docs_currency_gate` call sites) invoke `docs-currency-gate.py` with the same four-arg contract as `wave.py docs-currency` and living-doc fixtures.
2. A regression fixture proves terminal gate invocation does not traceback on a minimal deliver-state fixture.
3. `gap-017` flips to `resolved` when R43–R46 ship with green fixtures.

## Non-Goals

- Redesigning `docs-currency-gate.py` drift semantics (R50 living-doc currency rules unchanged).
- Fixing gap-007/gap-008 INDEX reconcile on `main` (separate gaps; PRD 046 A2 dependency unchanged).
- Re-opening PRD 052 or PRD 027 in place.

## Requirements

### Thread C extension — docs-currency gate argv contract

- **R43** (origin: gap-017 remediation #1) — `wave_terminal.run_docs_currency_gate()` MUST invoke
  `docs-currency-gate.py` with four positional arguments: `(repo_root, state_root, state_json_path,
  plan_json_path)`, deriving `state_json_path` and `plan_json_path` from the same branch-scoped conventions
  `wave.py docs-currency` and `wave_deliver_loop.py` use (`.cursor/sw-deliver-state.json` or slug-scoped
  variant when present). It MUST NOT pass `--state-root` alone.
- **R44** (origin: gap-017 remediation #2) — Fixture `terminal-docs-currency-gate-invocation-valid` MUST
  assert `run_docs_currency_gate` (or equivalent subprocess invocation used by terminal ship) completes without
  traceback and returns `verdict: pass` on a minimal fixture tree with aligned INDEX/state/plan.
- **R45** (origin: gap-017 remediation #3, optional) — `docs-currency-gate.py` MAY add an argparse
  `--state-root` entrypoint that expands to the four positional paths for backward compatibility; if added, it
  MUST delegate to the same core logic and emit a one-release deprecation advisory on stderr — not a second
  drift implementation.
- **R46** (origin: gap-017 closure) — On ship, flip `gap-017-wave-terminal-docs-currency-gate-invocation-uses`
  unit frontmatter to `resolved` referencing PRD 050 A3 only after R43–R44 fixtures are green.

## Technical Requirements

- **TR22** (R43) — Refactor `run_docs_currency_gate(root: Path)` in `scripts/wave_terminal.py` to resolve
  state/plan paths from `root` (mirror `wave_deliver_loop.load_plan` / scoped state file discovery); pass
  positional args to subprocess; preserve fail-closed JSON error surfacing on non-zero exit.
- **TR23** (R44) — Add harness under `scripts/test/fixtures/deliver-concurrency/` (or extend
  `run_living_doc_fixtures.py`) for `terminal-docs-currency-gate-invocation-valid`; register in
  `core/sw-reference/pr-test-plan.manifest.json` as `required`.
- **TR24** (R45, optional) — If argparse shim is implemented, use `argparse` in `docs-currency-gate.py` main;
  keep positional argv path as canonical for `wave.py` dispatch; document in `.sw/layout.md` terminal gate
  section if present.

Roll into parent Thread C (tasks 3.x) alongside R16 terminal PR template work (Decision D-A3-2).

## Testing Strategy

Add to parent Testing Strategy:

- `terminal-docs-currency-gate-invocation-valid` (R44, TR23)

No regression to parent R16 / gap-013 `terminal-pr-body-template-valid` fixture or PRD 046 A2 TR10 hook.

Re-run `docs-currency-gate.py` via `wave.py docs-currency` after TR22 to confirm positional dispatch unchanged.

## Rollout Plan

1. Implement TR22 + R43 (argv alignment) — unblocks automated terminal ship gate immediately.
2. Land TR23 + R44 fixture registration.
3. Optional TR24 argparse shim if operator scripts still pass `--state-root` (one-release advisory).
4. On ship: flip gap-017 to `resolved`; attach `gap_backlog.py check` output to PR.

## Decision Log

- **D-A3-1 (2026-07-02):** Host gap-017 on **PRD 050 A3** (Thread C extension) rather than PRD 027 because PRD
  027 is `complete` and PRD 050 is amendable with existing terminal-finalize scope; argv mis-invocation is a
  terminal-ship robustness defect aligned with R13–R16.
- **D-A3-2 (2026-07-02):** Ship TR22 before R16 template work when the operator's immediate blocker is terminal
  gate traceback — template validation (gap-013) is unreachable until R43 lands.
- **D-A3-3 (2026-07-02):** Positional four-arg contract remains canonical; optional `--state-root` shim (R45) is
  compatibility-only, not a second code path for drift logic.

## Security & Compliance

- No new network or credential surface; subprocess invokes existing local script only.
- Fail-closed posture preserved: non-zero `docs-currency-gate.py` exit still blocks terminal ship.

## Open Questions

None — gap-017 remediation direction is fully specified.
