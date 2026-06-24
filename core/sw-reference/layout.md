# phase-flow v2 artifact layout

Single-source path contract for the documentation pipeline and downstream implementation workstream.
All `sw-` doc commands resolve paths from this document — do not re-decide locations in commands.

## Directory tree

```text
docs/
└── brainstorms/
    ├── YYYY-MM-DD-<topic>-requirements.md
    └── YYYY-MM-DD-<topic>-requirements.amendments/
        └── A<k>-<short>.md

docs/prds/
├── INDEX.md
├── COMPLETION-LOG.md
├── GAP-BACKLOG.md
└── <n>-<slug>/
    ├── <n>-prd-<slug>.md
    ├── tasks-<n>-<slug>.md
    └── amendments/
        └── A<k>-<short>.md

docs/decisions/
├── INDEX.md
├── SUPERSEDED.log          # append-only manifest (written on record-level supersede)
├── <n>-<slug>.md
└── <n>-<slug>.amendments/
    └── A<k>-<short>.md

.cursor/
└── sw-wave-plan.json       # wave plan artifact (living, written by /sw-wave plan)
```

## Naming conventions

| Artifact | Path pattern | Written by | Frozen |
|----------|--------------|------------|--------|
| Brainstorm requirements | `docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md` | `/sw-brainstorm` | `/sw-freeze` |
| Brainstorm amendment | `docs/brainstorms/...-requirements.amendments/A<k>-<short>.md` | manual / future | `/sw-freeze` |
| PRD | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | `/sw-prd` | `/sw-freeze` |
| Task list | `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` | `/sw-tasks` | `/sw-freeze` |
| PRD amendment | `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md` | `/sw-amend` | `/sw-freeze` |
| Decision record | `docs/decisions/<n>-<slug>.md` | `/sw-prd --type decision` | `/sw-freeze` |
| Decision amendment | `docs/decisions/<n>-<slug>.amendments/A<k>-<short>.md` | `/sw-amend` | `/sw-freeze` |
| Living index | `docs/prds/INDEX.md` | `/sw-freeze`, `/sw-tasks` | never |
| Decision index | `docs/decisions/INDEX.md` | `/sw-freeze` | never |
| Completion log | `docs/prds/COMPLETION-LOG.md` | implementation workstream | never |
| Gap backlog | `docs/prds/GAP-BACKLOG.md` | `/sw-feedback` (Phase 2) | never |

### PRD numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `docs/prds/` for the highest existing `<n>` and incrementing.
- Collision policy: same feature re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Decision record numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `docs/decisions/` for the highest existing `<n>` and incrementing — **separate counter from `docs/prds/`**.
- Collision policy: same topic re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Slug (`<slug>`)

- Lowercase kebab-case derived from the feature topic (e.g. `doc-pipeline`, `user-auth`).
- Must be filesystem-safe; no spaces.

### Amendment naming (`A<k>-<short>`)

- `<k>` is a monotonic integer within the parent (`A1`, `A2`, …).
- `<short>` is a brief kebab-case descriptor (e.g. `A1-fail-closed-enforcement-point`).

## Frontmatter contracts

### Brainstorm / PRD / task list (pre-freeze)

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>
---
```

### Frozen artifact

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>          # PRD/task only
frozen: true
frozen_at: YYYY-MM-DD
---
```

### Amendment

```yaml
---
date: YYYY-MM-DD
amends: <parent-path>
frozen: true
frozen_at: YYYY-MM-DD
supersedes: [R<n>, ...]       # optional
retracts: [R<n>, ...]         # optional
---
```

Amendment body is **delta-only** — parent file is never edited.

## Command read/write map

| Command | Reads | Writes |
|---------|-------|--------|
| `/sw-triage` | user input, file list | tier decision (no files) |
| `/sw-brainstorm` | user dialogue | `docs/brainstorms/...-requirements.md` |
| `/sw-prd` | brainstorm (Full) or triaged request (Standard) | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` |
| `/sw-prd --type decision` | optional brainstorm; up-front cross-cutting decision | `docs/decisions/<n>-<slug>.md` |
| `/sw-doc-review` | PRD or decision-record draft | in-place edits (pre-freeze only) |
| `/sw-freeze` | target artifact | `frozen: true` frontmatter; `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` entry |
| `/sw-amend` | frozen parent PRD | `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md` |
| `/sw-tasks` | frozen PRD + union | `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md`, `INDEX.md` |
| `/sw-doc` | tier from triage | delegates to above |

## Living vs frozen layers

- **Frozen:** brainstorms, PRDs, task lists, amendments — immutable after `/sw-freeze`; change only via new amendments.
- **Living:** `INDEX.md`, `COMPLETION-LOG.md` — updated as work progresses; never frozen.
- **Gap backlog:** `GAP-BACKLOG.md` — committed, append-only, hand-appendable; not frozen, not git-derived.
- **Generated install trees:** `dist/cursor/` and `dist/claude-code/` — committed outputs of `python3 -m pf generate`; edit `core/` then regenerate (freshness gate in `scripts/test/run-emitter-fixtures.sh`). Not hand-edited except via emitter changes.

## Config keys

`workflow.config.json`:

- `prdsDir`: `"docs/prds"` — PRD root (per-PRD subdirs live beneath).
- `tasksDir`: `"docs/prds"` — task lists co-locate with their PRD (`docs/prds/<n>-<slug>/tasks-...`).
- `decisionsDir`: `"docs/decisions"` — decision-record root (flat files + sibling `.amendments/` dirs).
