# Shipwright


## sw-freeze-guardrail

---
description: Never edit a file with frozen: true in frontmatter. Post-freeze changes use /sw-amend only.
alwaysApply: true
---

# Frozen artifact guardrail

Files with `frozen: true` in YAML frontmatter are **immutable**. Do not edit, rename, or delete them.

## If change needed

1. Run `/sw-amend` to create a sibling amendment file.
2. Review via `/sw-doc-review` (coherence + scope-guardian always run against parent).
3. Freeze the amendment via `/sw-freeze`.

## Enforcement layers

- This rule — agent instruction (early warning).
- `hooks/pre-commit-frozen.sh` — local commit block (bypassable with `--no-verify`).
- `scripts/check-frozen.sh` — CI required-check (authoritative; not bypassable).

There is **no unfreeze** command.


## sw-git-conventions

---
description: Single-source git conventions for Shipwright — branch names, Conventional Commits, PR/merge templates, docs-on-a-branch. Reference skills/git-workflow; do not duplicate.
alwaysApply: true
---

# sw-git-conventions

**Authoritative reference:** `skills/git-workflow/SKILL.md`. This rule encodes enforceable guardrails only.

## Branch names

- Pattern: `<type>/<slug>` or `docs/<topic>` where `type` ∈ `release-please-config.json` changelog types.
- Enforced by `scripts/branch-name-guard.sh` at worktree/branch creation (`scripts/worktree_lib.py` for Python).
- `pf/<name>` is prohibited. Fail closed on non-conforming names.

## Commit messages

- Conventional Commits: `type(scope): description` or `type!: description` for breaking changes.
- Types single-sourced from `release-please-config.json`.
- Enforced by `scripts/commit-msg-guard.sh` via `core/hooks/commit-msg`.

## PR / merge bodies

- Templates: `core/sw-reference/templates/pr-body.md`, `merge-commit.md`.
- Required fields validated by `scripts/git_template_lib.py`; host `pr-create` fails closed on missing fields.

## Documentation authoring

- Brainstorm/PRD/doc pipeline work occurs on `docs/<topic>` in a dedicated worktree (`scripts/docs_worktree.sh`).
- Never create local commits on the protected default branch for doc authoring.
- Docs reach trunk via `scripts/docs_pr.sh` (docs-only PR), not direct push.
- Feature-branch `spec-seed` (PRD 013) remains for implementation handoff; docs durability is separate (R32).



## Two-track doc edits (PRD 035 R10–R14)

- **Mechanical** — reconciler-generated artifacts only (INDEX `derived` region, SUPERSEDED manifest, gap index):
  batched via `scripts/docs-merge.sh` with CI-gated auto-merge or direct-to-trunk when protection probe permits.
- **Substantive** — any path under `docs/planning/<unit-id>/` (body or frontmatter): auto-driven docs worktree +
  PR via `scripts/docs-edit-route.sh route-substantive` → `docs_worktree.sh` / `docs_pr.sh`.
- **`inFlight` region** — never mechanically edited (PRD 032 deliver writer sole region).
- Branch protection is detected via host API; ambiguous/missing auth fails closed to the PR path — never bypass
  the protected trunk merge gate.

## Provenance

Conventions informed by [netresearch/git-workflow-skill](https://github.com/netresearch/git-workflow-skill)
(CC-BY-SA-4.0 / MIT), adapted for Shipwright trunk-based worktrees.


## sw-naming

---
description: sw- command namespace, orchestrator vs atomic boundaries, and naming conventions for Shipwright.
alwaysApply: true
---

# sw- naming and command boundaries

All plugin commands, skills exposed as commands, and user-facing workflow entry points use the **`sw-`**
prefix (e.g. `/sw-review`, `/sw-stabilize`, `/sw-memory-sync`). This namespace is distinct from unprefixed
legacy commands and compound-engineering (`ce-`).

## Orchestrators vs atomic commands

- **Orchestrators** chain multiple phases:
  - `/sw-doc` — brainstorm → PRD → persona panel → freeze → tasks (tier-gated; see documentation workstream).
  - `/sw-deliver` — drives a frozen task list's phases to one merge gate (phase-mode) or runs multi-feature waves to `integration/<stamp>`; does not bypass `/sw-ship` or auto-merge to `main`.
  - `/sw-cleanup` — dry-run default enumeration of merged branches, stale worktrees, and completed deliver run-state; deletes only after confirm; does not drop in-flight runs or use `rm -rf` on worktrees.
  - `/sw-ship` — execute → verify → review → gaps → commit → pr → watch-ci → stabilize → ready (halts at merge gate).
  - `/sw-retrospective` — retro → compound write (internal) → memory-sync → status; `--pre-merge` / `--post-merge` phase dispatch; does not merge or auto-promote rules.
  - `/sw-debug` — triage signal → Sentry enrich (optional) → RCA core (debug entry) → route by fix size; does not implement or merge.
  - `/sw-feedback` — normalize + redact inbound signals → route to debug, gap-capture, or brainstorm; does not analyze or author.
  Their descriptions must state the full chain and which atomic commands they subsume.
- **Atomic commands** perform one bounded step (e.g. `/sw-watch-ci`, `/sw-memory-sync`, `/sw-triage`). Their descriptions
  must state what they do **and what they do not do** (e.g. "polls CI; does not merge or fix failures").

## Triage boundary

`/sw-triage` classifies tier only — it does not draft docs, freeze artifacts, or start implementation. Routing after triage is explicit in the triage output.

## Documentation orchestrator boundary

`/sw-doc` delegates to atomic doc commands; it does not reimplement their procedures. Each atomic (`/sw-brainstorm`, `/sw-prd`, `/sw-doc-review`, `/sw-freeze`, `/sw-tasks`) remains independently runnable. After task freeze, `doc.afterTasks` (`stop` | `confirm` | `auto`) is the sole checkpoint before implementation: `stop` prints the docs-only seed command onto `<type>/<slug>` plus `/sw-deliver run <frozen-task-list-path>`; `confirm` and `auto` seed the frozen `docs/prds/<n>-<slug>/` set onto `<type>/<slug>` then dispatch `/sw-deliver run <frozen-task-list-path>`, but the doc orchestrator **never inlines implementation** in any mode.

## Debug orchestrator boundary

`/sw-debug` diagnoses via `skills/rca-core` (debug entry) and routes — it does not run `/sw-execute`, `/sw-ship`, or patch on bare `main`. Small fixes hand off to `/sw-worktree` + `/sw-start`; substantial fixes hand off to `/sw-brainstorm` or `/sw-amend`. `/sw-stabilize` remains the in-loop PR blocker surface.

## Feedback orchestrator boundary

`/sw-feedback` normalizes and routes inbound signals — it does not run `/sw-debug` analysis, `/sw-amend` authoring, or task execution. Production signals with error/crash/regression markers dispatch to `/sw-debug`; PR-extending work splits to `/sw-amend` or a canonical **gap unit** under `docs/planning/<gap-unit-id>/` via `planning_gap_capture.py` (legacy `GAP-BACKLOG.md` is read-only projection only); new scope dispatches to `/sw-brainstorm`. Human confirmation required before dispatching any route (including agent callers).

## Naming rules

1. Prefix every command file with `sw-` (e.g. `commands/sw-review.md`).
2. Skill directories use descriptive kebab-case without the prefix (e.g. `skills/checks-gate/`).
3. Rules use `sw-` when they encode plugin-specific guardrails (e.g. `sw-naming.mdc`, `sw-guardrails.mdc`).
4. Provider adapters live under `providers/`; executable adapters use `.sh` (e.g. `providers/review/coderabbit.sh`).

## Deprecated aliases (one release)

- `/sw-setup` — **deprecated** delegate to **`/sw-init`** (identical behavior; one-release alias).
- `/sw-compound-ship` and `/sw-compound` are **deprecated** shims routing to `/sw-retrospective` (R4). Live routing,
  conductor handoffs, and deliver terminal paths MUST reference `/sw-retrospective` — not the old names.

## Description contract

Every command frontmatter `description` must be one sentence on scope plus one on explicit non-goals when
ambiguity is likely.

## Model tier floor (R9)

Semantic tiers (`cheap`/`build`/`deep`) live in `workflow.config.json` `models.tiers` only — not in agent
`model:` frontmatter. Reviewer agents use `model: inherit` or a concrete platform ID. Validated by
`scripts/model-tier-check.sh` (config + concrete models); runtime R9 for `inherit` reviewers is enforced at
dispatch by `/sw-doc-review` and `rules/sw-subagent-dispatch.mdc`. See `.sw/models-tiering.md`.

## Planning full-conductor boundary (PRD 035 R9)

`scripts/planning_autonomy.py` under `planning.autonomy: full-conductor` is a **bounded planning driver**,
not an orchestrator. It may enqueue atomic handoffs (`/sw-prd`, `/sw-tasks`, `planning-graph.sh reconcile`)
but **must not** invoke `/sw-deliver`, `/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback`, `/sw-cleanup`, or
`/sw-retrospective` from within its loop. An explicit halt applies between a reconcile batch and any downstream
dispatch. Nested orchestrator dispatch is a naming/conductor boundary violation — use enqueue-handoff-only.


