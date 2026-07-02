---
date: 2026-07-01
topic: operator-worktree-contract-and-cwd-guard
frozen: true
frozen_at: 2026-07-01
---

# Tasks excerpt — PRD 049 phase 2

### 2. In-flight cwd guard + canonical state read (L)

- [ ] 2.1 Implement `deliver_cwd_guard.py` (R3, R7)
  - **File:** `scripts/deliver_cwd_guard.py`
  - **Expected:** fail-closed cwd guard module
- [ ] 2.2 Wire guard into R3's minimum surfaces
  - **File:** `scripts/wave_living_docs.py`, `scripts/reconcile.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** guarded surfaces refuse on primary checkout
- [ ] 2.3 Add `sync_canonical_state_read()` (R4)
  - **File:** `scripts/wave_state.py`
  - **Expected:** canonical state reader with skew threshold
- [ ] 2.4 Wire terminal deliver actions (R4)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** terminal actions read repo-root state
- [ ] 2.5 Fixtures guard + terminal read (TR1, TR2)
  - **File:** `scripts/test/run_deliver_cwd_guard_fixtures.py`, `scripts/test/run_terminal_state_read_fixtures.py`
  - **Expected:** fixtures registered and green

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R3 | 2.1, 2.2 | deliver-cwd-guard-blocks-main-living-doc |
| R4 | 2.3, 2.4 | terminal-reads-repo-root-state |
| R3 | 2.5 | deliver-cwd-guard-blocks-main-living-doc |
