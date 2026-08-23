# Architecture doctrine (Shipwright)

Durable, human-reviewable architecture statements for opt-in assessment (PRD 326 R13).
Each statement carries a stable `AD-<n>` id, rationale, and an observable signal — or `manual: true`
when human review is the only check.

**Owner:** platform-team  
**Refresh cadence:** per release (or when a new AD statement is added)

**Version:** 1

## AD-1: Python-first workflow logic

- **Rationale:** Workflow automation must stay stdlib-first Python (R31/R41) so hooks, gates, and
  orchestrators run without shell dependencies or undeclared third-party packages.
- **Signal:** `python3 scripts/zero-shell-guard.py` exits 0 on a clean tree.

## AD-2: CI readiness gate authority

- **Rationale:** Merge readiness is computed only through the shared check-gate library — never
  hand-rolled green verdicts in commands or agents.
- **Signal:** `core/sw-reference/gate-manifest.json` registers a `check-gate` entry with
  `scripts/check-gate.py` as its entrypoint.

## AD-3: Broker-only credential access

- **Rationale:** Host and provider credentials resolve through the credential broker with mandatory
  scope enforcement — ambient env tokens outside declared backends are prohibited.
- **Signal:** `scripts/host_lib.py` imports `credentials.resolver`.

## AD-4: Worktree-isolated delivery

- **Rationale:** Feature implementation and ship loops run on isolated worktrees/branches; protected
  trunk is not a direct edit surface for deliver work.
- **Signal:** `scripts/worktree.py` exposes `cmd_provision` for branch-scoped worktree provisioning.

## AD-5: Mechanical docs reconciliation

- **Rationale:** Derived INDEX regions and mechanical doc projections are reconciler-owned; substantive
  planning edits route through the docs worktree PR path instead of hand edits on trunk.
- **Signal:** `scripts/docs-merge.py` and `scripts/docs-edit-route.py` are present under `scripts/`.

## AD-6: sw- command namespace

- **Rationale:** All plugin workflow entry points use the `sw-` prefix so orchestrators, atomic
  commands, and legacy surfaces remain unambiguous at dispatch time.
- **manual:** true
