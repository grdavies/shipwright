---
name: git-workflow
description: Shipwright trunk-based git conventions — branch names, Conventional Commits, PR/merge bodies, and docs-on-a-branch policy. Host-agnostic; references sw-git-conventions rule.
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: providers
      scope: git-conventions
  metadata:
    skill: git-workflow
    selectionFamily: providers
---

# git-workflow

Native Shipwright git conventions. **Single source of truth** for branch naming, commit messages, and
PR/merge bodies — reference this skill and `rules/sw-git-conventions.mdc`; do not duplicate prose elsewhere.

Informed by and crediting [netresearch/git-workflow-skill](https://github.com/netresearch/git-workflow-skill)
(CC-BY-SA-4.0 / MIT). Adapted for Shipwright's trunk-based-with-worktrees model and sw-namespaced tooling.

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill git-workflow`.

## Trunk model

- **Trunk** = `defaultBaseBranch` from `workflow.config.json` (usually `main`). Protected; never commit
  implementation or documentation authoring directly on trunk.
- **Feature branches** = `<type>/<slug>` where `type` is a Conventional Commit type from
  `release-please-config.json` (`feat`, `fix`, `docs`, …). Enforced by `scripts/branch-name-guard.sh`.
- **Phase branches** = `<type>/<slug>-phase-<phase-slug>` (deliver phase-mode).
- **Docs branches** = `docs/<topic>` for brainstorm/PRD/doc-pipeline authoring (R28). Provisioned via
  `scripts/docs_worktree.sh`; merged to trunk via `scripts/docs_pr.sh` (R30).
- **Integration branches** = `<type>/<slug>` stacking deliver phases before terminal merge.
- **Worktrees** isolate concurrent efforts under `.sw-worktrees/<name>/`.

Legacy `pf/<name>` prefixes are **prohibited** (PRD 007).

## Branch naming

| Pattern | Use |
| --- | --- |
| `<type>/<slug>` | Feature / fix / chore implementation |
| `docs/<topic>` | Documentation pipeline (brainstorm → PRD → tasks) |
| `integration/<stamp>` | Multi-feature wave assembly |

Validation (fail-closed):

```bash
bash scripts/branch-name-guard.sh validate <branch>
bash scripts/branch-name-guard.sh derive <name> [type]
```

Python consumers: `python3 scripts/worktree_lib.py validate <branch>`.

Allowed types are **single-sourced** from `release-please-config.json` `changelog-sections[].type`.

## Conventional Commits

Commit subjects must match:

```
<type>(<optional-scope>): <description>
<type>!: <description>          # breaking change
```

Types from `release-please-config.json`. Enforced at commit time:

```bash
bash scripts/commit-msg-guard.sh validate "<message>"
```

Hook: `core/hooks/commit-msg` (install via `git config core.hooksPath` pointing at emitted hooks dir).

## PR / merge bodies

Standard templates live under `core/sw-reference/templates/`:

| Template | Purpose |
| --- | --- |
| `pr-body.md` | PR/MR description (required: Summary, Test plan) |
| `merge-commit.md` | Squash/merge commit body |

Render and validate:

```bash
python3 scripts/git_template_lib.py render pr-body --context-json '{"summary":"…","test_plan":"…"}'
python3 scripts/git_template_lib.py validate pr-body --body-file path.md
```

Host adapters apply `pr-body.md` at `pr-create` time; missing required fields fail closed (R26).

## Docs-on-a-branch policy (R28–R32)

1. **Provision** — `bash scripts/docs_worktree.sh provision --topic <topic>` creates `docs/<topic>` +
   worktree under `.sw-worktrees/docs-<topic>/`.
2. **Author** — run `/sw-doc` chain inside the docs worktree; never commit doc artifacts on trunk.
3. **Durability** — `bash scripts/wave_spec_seed.py <root> docs-commit --topic <topic>` commits brainstorms
   and PRD artifacts on the docs branch (R31).
4. **Implementation handoff** — `bash scripts/wave.sh spec-seed --task-list <path>` still seeds frozen PRD/tasks
   onto `<type>/<slug>` for `/sw-deliver` (PRD 013 reconcile, R32).
5. **Merge docs** — `bash scripts/docs_pr.sh --topic <topic>` opens a docs-only PR to trunk (R30).

## Two-track doc edits (PRD 035 R10–R14)

The two-track driver (`scripts/docs-edit-route.sh`, `scripts/two_track_lib.py`) classifies planning graph
edits as **mechanical** vs **substantive**:

| Track | Allowlist (R11) | Route |
| --- | --- | --- |
| Mechanical | INDEX **`derived` region only**, SUPERSEDED manifest, generated gap index | `docs-edit-route.sh route` → batched `docs-merge.sh` (CI auto-merge or direct-to-trunk when permitted) |
| Substantive | Any `docs/planning/<unit-id>/` path (body or frontmatter) | `docs-edit-route.sh route-substantive --topic <topic>` → docs worktree + `docs_pr.sh` |

The INDEX **`inFlight` region is never mechanical** — it is the PRD 032 deliver writer's sole region. Branch
protection is probed live via the host API (`scripts/host_lib.py`); when detection is ambiguous or `gh` auth
is missing, the driver defaults to the PR path and never attempts a direct push to a protected default branch.

Mechanical batched PRs embed a monotonic content-hash covering both INDEX regions (`derived` + `inFlight`) at
open; auto-merge aborts if either region advanced since (R14 stale-PR guard).


## Guardrails

- Never push directly to a protected default branch.
- Never mint non-conforming branch names — use `derive` when unsure.
- Never bypass `commit-msg-guard` for workflow commits.
- Reference this skill for conventions; do not restate branch/commit/PR rules in command prose.
