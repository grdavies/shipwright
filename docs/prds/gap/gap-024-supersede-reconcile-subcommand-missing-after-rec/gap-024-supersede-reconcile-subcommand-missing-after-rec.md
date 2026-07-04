---
id: gap-024-supersede-reconcile-subcommand-missing-after-rec
type: gap
status: scheduled
schedule: PRD 055
title: supersede-reconcile subcommand missing after reconcile.py consolidation
visibility: public
tags: [source:feedback, signal:feedback-supersede-reconcile-missing-2026-07-02, prd-015, prd-042, memory-sot, sw-memory-sync]
absorbs: []
---

# supersede-reconcile subcommand missing after reconcile.py consolidation

_Scheduled to close PRD 015 R7 / task 3.2 (marked complete but not implemented)._

_Captured from feedback signal `feedback-supersede-reconcile-missing-2026-07-02` during PRD 054
implementation — agent log deferred supersede reconcile._

## Summary

`/sw-memory-sync` step 8 and PRD 015 R7 require
`python3 scripts/reconcile-status.py supersede-reconcile --json` to re-point the non-authoritative side for
entries in `docs/decisions/SUPERSEDED.log`. Neither `scripts/reconcile-status.py` nor
`scripts/reconcile.py` implements `supersede-reconcile` (or `append-superseded`). Agents following
`core/commands/sw-memory-sync.md` correctly defer with no `SUPERSEDED.log` actions — but the deferral masks a
**shipped-but-missing** PRD 015 capability, not optional behavior.

## Evidence

```bash
$ python3 scripts/reconcile.py supersede-reconcile --json
unknown command: supersede-reconcile

$ python3 scripts/reconcile-status.py
# Errno 2: No such file or directory
```

- PRD 042 consolidated `reconcile-status.py` → `scripts/reconcile.py` (R22 single reconciler) but did not port
  supersede subcommands.
- PRD 015 task **3.2** is checked `[x]` complete; fixture `memory-sot-supersede-reconcile` **fails** on current
  `main` (`run_memory_sot_fixtures.py`).
- Docs still reference the old entrypoint:
  - `core/commands/sw-memory-sync.md` step 8 → `reconcile-status.py supersede-reconcile`
  - `core/skills/memory/SKILL.md` → `append-superseded` + `supersede-reconcile`
  - `core/commands/sw-amend.md` step 9 → `append-superseded`
- `script-port-ledger.json` still lists `reconcile-status.py` as port target (stale ledger row).

## Operator impact (PRD 054 session)

Agent log observed:

> `scripts/reconcile-status.py supersede-reconcile is not present in this repo (reconcile.py has no
> supersede-reconcile subcommand). Deferred — no SUPERSEDED.log actions taken.`

This is **fail-safe** (no silent corruption) but **R7 is unmet**: superseded decision pointers are not
reconciled during `/sw-memory-sync`.

## Relationship to existing coverage

| Item | Overlap |
|------|---------|
| **PRD 015 R7 / task 3.2** | Declared complete — implementation gap |
| **PRD 042 R22** | `reconcile.py` consolidation — dropped supersede surface |
| **GAP-066** | Bare `reconcile` on `main` — different class (INDEX regression) |
| **gap-004** | Dispatch bash invokes — unrelated |

No existing gap tracks missing `supersede-reconcile` / `append-superseded`.

## Remediation direction

1. Implement in `scripts/reconcile.py` (canonical post-042 surface):
   - `append-superseded --path <old> --replacement <new>` — append to `docs/decisions/SUPERSEDED.log`
   - `supersede-reconcile [--json]` — for each log entry, best-effort re-point per SoT (`memory-sot.py`):
     repo-SoT: `modify` provider `decision` `relatedFiles`; memory-SoT: refresh git snapshot pointer via
     `memory-decision-snapshot.py write`
2. Update docs/commands/skills: `reconcile-status.py` → `reconcile.py` for all subcommands (or add thin
   `reconcile-status.py` shim delegating to `reconcile.py` for backward compat).
3. Refresh `script-port-ledger.json` disposition rows.
4. Make `memory-sot-supersede-reconcile` fixture pass; register in `verify.test` if not already.
5. Regenerate `dist/` via `build-chain-sync.py`.

## Acceptance

- `python3 scripts/reconcile.py supersede-reconcile --json` exits 0 on repo with `SUPERSEDED.log` (or empty
  no-op).
- `python3 scripts/reconcile.py append-superseded --path … --replacement …` appends manifest row.
- `/sw-memory-sync` step 8 succeeds without agent deferral.
- `run_memory_sot_fixtures.py` reports `OK memory-sot-supersede-reconcile`.

