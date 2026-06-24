# phase-flow v2 artifact layout

Single-source path contract for the documentation pipeline and downstream implementation workstream.
All `pf-` doc commands resolve paths from this document — do not re-decide locations in commands.

## Directory tree

```text
docs/
└── brainstorms/
    ├── YYYY-MM-DD-<topic>-requirements.md
    └── YYYY-MM-DD-<topic>-requirements.amendments/
        └── A<k>-<short>.md

prds/
├── INDEX.md
├── COMPLETION-LOG.md
├── GAP-BACKLOG.md
└── <n>-<slug>/
    ├── <n>-prd-<slug>.md
    ├── tasks-<n>-<slug>.md
    └── amendments/
        └── A<k>-<short>.md

decisions/
├── INDEX.md
├── SUPERSEDED.log          # append-only manifest (written on record-level supersede)
├── <n>-<slug>.md
└── <n>-<slug>.amendments/
    └── A<k>-<short>.md

.cursor/
└── pf-wave-plan.json       # wave plan artifact (living, written by /pf-wave plan)
```

## Naming conventions

| Artifact | Path pattern | Written by | Frozen |
|----------|--------------|------------|--------|
| Brainstorm requirements | `docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md` | `/pf-brainstorm` | `/pf-freeze` |
| Brainstorm amendment | `docs/brainstorms/...-requirements.amendments/A<k>-<short>.md` | manual / future | `/pf-freeze` |
| PRD | `prds/<n>-<slug>/<n>-prd-<slug>.md` | `/pf-prd` | `/pf-freeze` |
| Task list | `prds/<n>-<slug>/tasks-<n>-<slug>.md` | `/pf-tasks` | `/pf-freeze` |
| PRD amendment | `prds/<n>-<slug>/amendments/A<k>-<short>.md` | `/pf-amend` | `/pf-freeze` |
| Decision record | `decisions/<n>-<slug>.md` | `/pf-prd --type decision` | `/pf-freeze` |
| Decision amendment | `decisions/<n>-<slug>.amendments/A<k>-<short>.md` | `/pf-amend` | `/pf-freeze` |
| Living index | `prds/INDEX.md` | `/pf-freeze`, `/pf-tasks` | never |
| Decision index | `decisions/INDEX.md` | `/pf-freeze` | never |
| Completion log | `prds/COMPLETION-LOG.md` | implementation workstream | never |
| Gap backlog | `prds/GAP-BACKLOG.md` | `/pf-feedback` (Phase 2) | never |

### PRD numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `prds/` for the highest existing `<n>` and incrementing.
- Collision policy: same feature re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Decision record numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `decisions/` for the highest existing `<n>` and incrementing — **separate counter from `prds/`**.
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
| `/pf-triage` | user input, file list | tier decision (no files) |
| `/pf-brainstorm` | user dialogue | `docs/brainstorms/...-requirements.md` |
| `/pf-prd` | brainstorm (Full) or triaged request (Standard) | `prds/<n>-<slug>/<n>-prd-<slug>.md` |
| `/pf-prd --type decision` | optional brainstorm; up-front cross-cutting decision | `decisions/<n>-<slug>.md` |
| `/pf-doc-review` | PRD or decision-record draft | in-place edits (pre-freeze only) |
| `/pf-freeze` | target artifact | `frozen: true` frontmatter; `prds/INDEX.md` or `decisions/INDEX.md` entry |
| `/pf-amend` | frozen parent PRD | `prds/<n>-<slug>/amendments/A<k>-<short>.md` |
| `/pf-tasks` | frozen PRD + union | `prds/<n>-<slug>/tasks-<n>-<slug>.md`, `INDEX.md` |
| `/pf-doc` | tier from triage | delegates to above |

## Living vs frozen layers

- **Frozen:** brainstorms, PRDs, task lists, amendments — immutable after `/pf-freeze`; change only via new amendments.
- **Living:** `INDEX.md`, `COMPLETION-LOG.md` — updated as work progresses; never frozen.
- **Gap backlog:** `GAP-BACKLOG.md` — committed, append-only, hand-appendable; not frozen, not git-derived.

## Config keys

`workflow.config.json`:

- `prdsDir`: `"prds"` — PRD root (per-PRD subdirs live beneath).
- `tasksDir`: `"prds"` — task lists co-locate with their PRD (`prds/<n>-<slug>/tasks-...`).
- `decisionsDir`: `"decisions"` — decision-record root (flat files + sibling `.amendments/` dirs).
