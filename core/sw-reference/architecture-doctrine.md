# Architecture doctrine reference (Shipwright)

Durable, human-reviewable architecture statements for opt-in assessment (PRD 326 R13; PRD 330 R3–R5,
R8, R10). This file is **Shipwright-self reference only** — bundled plugin workflow law, not consumer
project architecture authority.

## Scope and ownership boundary

| Surface | Authority | Role |
| --- | --- | --- |
| **Shipwright-self doctrine** (`AD-<n>` below) | Bundled reference for the Shipwright plugin repository | Opt-in assessment via `.cursor/architecture-assessment.yaml` |
| **Consumer `ProjectDoctrine@v1`** | Repo-local `.sw/project-doctrine.json` (sole SoT) | Consumer architecture vocabulary + assessment data |
| **Codebase design** | Reference and assessment input only | Read-only; informs evaluation — **not** a duplicate SoT or workflow command |

Consumer architecture vocabulary — **modules**, **interfaces**, **seams**, **adapters**, and
**locality** — is owned by the consumer repo-local `ProjectDoctrine@v1` `architecture` object (see
`core/sw-reference/project-doctrine.schema.json`). Issue-store copies are projection-only.

**Excluded from consumer doctrine authority:** product roadmap, org chart, and runtime runbook scope.
Codebase-design notes and assessment YAML may reference those topics for human review but must not
grant autonomous product, organization, or operations authority.

**No `/sw-codebase-design` command.** Codebase-design remains a reference/assessment input surfaced
through init, doctrine lifecycle, and `architecture_assessment.py` — never a top-level `sw-`
workflow entry point. Future exploration interfaces (for example `/sw-explore`) are out of scope for
this release.

Valid consumer pointers to this bundled reference use `shipwrightSelfRef` with `kind: pointer` and a
`shipwright-self:` URI — never copied bundled law in consumer-owned fields (see
`scripts/project_doctrine_leakage.py`).

## Consumer architecture vocabulary

| Term | Consumer-owned meaning |
| --- | --- |
| **modules** | Cohesive units of consumer code or deployable boundaries |
| **interfaces** | Stable contracts between modules or external systems |
| **seams** | Intentional extension or substitution boundaries |
| **adapters** | Boundary translators between interfaces and external shapes |
| **locality** | Data/process placement and affinity constraints |

Assessment evaluates entries from consumer doctrine `architecture` and optional `assessment` data
(or a read-only YAML artifact referenced by `assessment.artifactPath`). Repo-local doctrine
ownership is preserved — bundled `AD-<n>` ids are not reused as consumer entry ids.

## Shipwright-self doctrine

**Owner:** platform-team (Shipwright plugin — not consumer repositories)  
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
