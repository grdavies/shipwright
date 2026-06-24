---
date: 2026-06-24
topic: artifact-consolidation-under-docs
---

# Requirements: Artifact consolidation under docs/

## Outcome

All phase-flow user-facing artifact directories live under a single `docs/` tree so adopters can gitignore that directory to keep workflow artifacts local. All plugin reference files move to `.pf/`, a hidden plugin-namespaced directory, eliminating the generic `config/` directory and avoiding collisions with user repo conventions.

## Hard floor

- `docs/` must be the sole parent of all plugin-written artifact directories.
- `.pf/` must be the sole home for plugin reference files — no plugin meta-files remain in `docs/` or at repo root.
- `config/` must be eliminated entirely (no files remain there).
- `workflow.config.example.json` default values for `prdsDir` and `decisionsDir` must reflect the new paths.
- All hardcoded `decisions/` and `prds/` path strings in commands, skills, and scripts must be updated.
- Existing content in this repo must be migrated (not left in old locations).

## Target directory layout

```
.pf/
  layout.md                      # path contract (was docs/layout.md)
  config.schema.json             # JSON schema for workflow.config.json (was docs/config.schema.json)
  models-tiering.md              # model tier reference (was docs/models-tiering.md)
  workflow.config.example.json   # user-facing config template (was config/workflow.config.example.json)

docs/                            # gitignore-able artifact tree
  brainstorms/                   # unchanged path
  plans/                         # unchanged path
  prds/                          # was root prds/
  decisions/                     # was root decisions/
```

`.cursor/` internals, worktree state, and hook state are unaffected.

## Artifact path changes

| Artifact | Old path | New path |
|----------|----------|----------|
| PRD | `prds/<n>-<slug>/` | `docs/prds/<n>-<slug>/` |
| Task list | `prds/<n>-<slug>/tasks-...md` | `docs/prds/<n>-<slug>/tasks-...md` |
| PRD index | `prds/INDEX.md` | `docs/prds/INDEX.md` |
| Completion log | `prds/COMPLETION-LOG.md` | `docs/prds/COMPLETION-LOG.md` |
| Gap backlog | `prds/GAP-BACKLOG.md` | `docs/prds/GAP-BACKLOG.md` |
| Decision record | `decisions/<n>-<slug>.md` | `docs/decisions/<n>-<slug>.md` |
| Decision index | `decisions/INDEX.md` | `docs/decisions/INDEX.md` |
| Superseded log | `decisions/SUPERSEDED.log` | `docs/decisions/SUPERSEDED.log` |
| Path contract | `docs/layout.md` | `.pf/layout.md` |
| Config schema | `docs/config.schema.json` | `.pf/config.schema.json` |
| Model tiers doc | `docs/models-tiering.md` | `.pf/models-tiering.md` |
| Config template | `config/workflow.config.example.json` | `.pf/workflow.config.example.json` |

## Config key changes

`workflow.config.example.json` (and `/pf-setup` defaults):

```json
"prdsDir": "docs/prds",
"decisionsDir": "docs/decisions"
```

`tasksDir` co-locates with PRDs, so it follows: `"tasksDir": "docs/prds"`.

The `$schema` reference in `workflow.config.example.json` must update from `"../docs/config.schema.json"` to `"../.pf/config.schema.json"`.

## Reference sweep scope

Files containing hardcoded `decisions/` or `prds/` paths that must be updated:

- `commands/` — `pf-amend.md`, `pf-prd.md`, `pf-freeze.md`, `pf-doc-review.md`, `pf-status.md`, `pf-execute.md`, `pf-tasks.md`, `pf-feedback-close.md`, `pf-feedback.md`, `pf-debug.md`, `pf-stabilize.md`, `pf-memory-import.md`
- `skills/` — `doc-review/SKILL.md`, `memory/SKILL.md`, `spec-union/SKILL.md`, `prd/SKILL.md`, `compound/SKILL.md`, `wave/SKILL.md`, `living-status/SKILL.md`, `tasks/SKILL.md`, `feedback-closure/SKILL.md`, `feedback/SKILL.md`, `spec-rigor/SKILL.md`, `feedback/references/route-record.md`
- `scripts/` — `test/run-doc-fixtures.sh`, `test/run-impl-fixtures.sh`, `test/run-memory-provider-fixtures.sh`, `test/run-code-review-fixtures.sh`, `test/run-improvement-fixtures.sh`, `scripts/wave.sh`
- `docs/layout.md` itself (update tree + table before moving to `.pf/layout.md`)

Files containing `docs/layout.md`, `docs/config.schema.json`, or `docs/models-tiering.md` references that must be updated:

- `commands/` — `pf-brainstorm.md`, `pf-prd.md`, `pf-setup.md`, `pf-doc-review.md`
- `skills/` — `brainstorm/SKILL.md`, `brainstorm/references/requirements-sections.md`, `prd/SKILL.md`, `tasks/SKILL.md`, `wave/SKILL.md`
- `scripts/` — `test/run-doc-fixtures.sh`, `test/run-impl-fixtures.sh`, `test/run-memory-provider-fixtures.sh`, `test/run-code-review-fixtures.sh`, `test/run-improvement-fixtures.sh`

## /pf-setup behaviour

After writing `workflow.config.json`, `/pf-setup` emits an opt-in gitignore hint:

```
Tip: add docs/ to .gitignore to keep workflow artifacts local (brainstorms, PRDs, decisions).
```

It does not modify `.gitignore` automatically.

## Success criteria

1. `docs/prds/` and `docs/decisions/` exist and hold the migrated content.
2. `prds/` and `decisions/` no longer exist at repo root.
3. `config/` no longer exists at repo root.
4. `.pf/` contains all four plugin reference files.
5. `workflow.config.example.json` defaults to `docs/prds` and `docs/decisions`.
6. All existing test fixtures pass against the new paths.
7. A user can add `docs/` to `.gitignore` without hiding any plugin reference or config files.

## Scope boundaries

**Deferred for later:**
- Auto-migration script for existing user repos (they update `workflow.config.json` manually or re-run `/pf-setup`).
- Enforcing gitignore — remains opt-in, never forced.

**Out of scope:**
- Worktree state (`.git/worktrees/*/phase-flow.json`), hook state (`.cursor/hooks/`), wave plan (`.cursor/pf-wave-plan.json`).
- `integration/<stamp>` — this is a git branch naming pattern, not a filesystem directory.
- Renaming `docs/brainstorms/` or `docs/plans/` (already correctly located).
