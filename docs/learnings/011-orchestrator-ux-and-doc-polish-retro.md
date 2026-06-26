# PRD 011 retro — orchestrator UX and doc polish

**Branch:** `feat/orchestrator-ux-and-doc-polish` @ `1a3de5c`  
**Status:** completed-pending-merge (pre-merge compound-ship)

## Went well

- Four focused phases mapped cleanly to GAP-BACKLOG rows (sw-doc surface, confirm prominence, sw-cleanup confirm, link-check).
- `run-ux-polish-fixtures.sh` gives durable regression coverage for command-doc UX (40 scenarios).
- Phase-mode deliver with orchestrator worktree kept feature branch linear.

## Painful

- Initial verify blocked on missing `communication-routing.defaults.json` (PRD 006 artifact never landed).
- Each phase merge required dist + `cursor-golden.manifest` regen before post-merge verify passed.
- Full `verify.test` in consumer repo can overwrite active deliver state (restore + reconcile required).
- Local-evidence merge path needed manual `status.json` gate `green` when no open PR.

## Process candidates (for `/sw-compound`)

- Treat post-phase-merge `sw generate --all` + golden refresh as a standard deliver bookkeeping step.
- Avoid running full verify in repo root while an active deliver loop is in flight.
- Document local-evidence gate expectations in merge troubleshooting.
