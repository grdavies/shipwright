---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: in-repo
    metadata:
      providerFamily: memory
      adapterId: in-repo
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: in-repo

Maps the Shipwright memory capability spec ([`skills/memory/CAPABILITIES.md`](../skills/memory/CAPABILITIES.md))
onto committed markdown files with YAML frontmatter. Selected when `workflow.config.json` → `memory.provider`
is `in-repo`, or when `.cursor/sw-memory.provider` marks the repo (zero-config fresh install).

**Catalog authority (PRD 071):** this adapter is registered in `.sw/memory-provider-catalog.json` (emit:
`core/sw-reference/memory-provider-catalog.json`). Capability flags, hook transport, interchange modes, and
`sourceOfTruthClass` in the catalog row are authoritative — the JSON block below must stay in sync.
Recallium conformance notes (for cross-provider comparison): [`sw-reference/memory-provider-recallium-conformance.md`](../sw-reference/memory-provider-recallium-conformance.md).

| Catalog field | Value |
| --- | --- |
| `sourceOfTruthClass` | `repo-authoritative` — committed store is SoT; provider holds distilled pointers only when paired |
| `interchange.jsonl` | `native` — `in-repo-memory-search.py export/import --format jsonl` |
| `interchange.okf` | `native` — `in-repo-memory-search.py export/import --format okf` |
| `credentials.location` | `none` — offline-first; no remote credentials |

`<project>` below is `memory.project` from config, or the workspace directory basename when unset.
Global scope uses a dedicated `global/` subfolder under the store (rare; explicit user direction only).

## Store layout

Default committed store: `.cursor/sw-memory/`

```
.cursor/sw-memory/
  memories/          # non-rule memories (committed by default)
    <id>.md          # one file per memory; filename stem = memory id
  rules/             # category:rule files (always committed — offline hook reads these)
    <id>.md
```

Per-user-local opt-out (`memory.inRepo.commitMode: local`): non-rule writes land in
`.cursor/sw-memory-local/memories/` (gitignored by `/sw-setup`). **Rule-class files always write to
`.cursor/sw-memory/rules/`** regardless of commit mode.

Per-memory file shape: YAML frontmatter = neutral interchange fields; distilled note in the body.

```yaml
---
category: decision
tags: [prd-12, surface:execute]
relatedFiles: [server/auth.ts]
importance: 0.7
scope: project
links: []
title: ""
description: ""
resource: ""
confidence: 0.5
usage_count: 0
success_count: 0
playbookStatus: draft
auditTelemetryRef: ""
skepticVerdict: pending
createdAt: 2026-06-23T12:00:00Z
---
Distilled memory body here.

# Citations

- docs/decisions/064-example.md
```

Filename: `<id>.md` where `<id>` is a stable slug (e.g. `20260623-auth-decision`). The filename stem is the
memory id returned by `search` / used by `expand` / `modify`.

## Capability flags

```json
{
  "typedMemories": true,
  "filePathSearch": true,
  "categoryFilter": true,
  "recencyControl": true,
  "rulesAtStartup": true,
  "tasks": false,
  "export": true,
  "import": true,
  "softDelete": true,
  "semanticSearch": false
}
```

`semanticSearch` is `false`: retrieval uses `scripts/in-repo-memory-search.py` (keyword body match +
frontmatter filters). `export`/`import` are native: walk the store and emit/consume neutral JSONL per
`CAPABILITIES.md`.

## Compiled truth and timeline (PRD 077)

Non-rule memories use Brain.md-inspired **truth-with-evidence** sections inside the existing store
(default `.cursor/sw-memory/`). This is **not** a second provider and does **not** introduce a `brain/`
directory or Node Brain.md CLI.

```markdown
## Compiled truth

Current best understanding of this memory.

## Timeline

- `created` @ 2026-07-22T12:00:00Z — Initial memory created
- `truth-updated` @ 2026-07-22T13:00:00Z — Why understanding changed

# Citations

- docs/decisions/example.md
```

- **Compiled truth** is rewritable (current understanding).
- **Timeline** is append-only evidence (`kind`, `at`, `summary`). Ordinary `modify` / `update-truth`
  never edit or delete prior entries.
- **Atomic `update-truth`** rewrites compiled truth and appends exactly one timeline entry in one
  write (temp-file + rename).
- **Legacy** body-only files remain readable: the full body is treated as compiled truth until the
  first `update-truth` / truth-bearing `modify` upgrades the layout (lazy, no bulk migration).
- **Rules** under `rules/` do not require timeline sections.

## Operation mapping

| Abstract op | Implementation | Call shape |
| --- | --- | --- |
| `load-context` | read `index.md` + `rules-load` | read store `index.md` first for orientation; load rules from `rules/` |
| `rules-load` | read `rules/*.md` | filesystem read of committed rule files |
| `search` | `in-repo-memory-search.py` | `python3 scripts/in-repo-memory-search.py --store <dir> --query <q> [--category] [--tag] [--file-glob]` — summaries prefer compiled truth |
| `expand` | `in-repo-memory-search.py expand` | `python3 scripts/in-repo-memory-search.py expand --store <dir> --ids <id>[,...]` — body + `compiledTruth` + `timeline` + backlinks |
| `store` | write file after redaction | `python3 scripts/in-repo-memory-search.py store --store <dir> --id <id> --category <cat> --content <text\|->` — initializes truth + `kind: created` timeline entry |
| `update-truth` | atomic truth rewrite | `python3 scripts/in-repo-memory-search.py update-truth --store <dir> --id <id> --truth <text\|-> --summary <why>` |
| `modify` | update frontmatter / body / `inactive:true` | `python3 scripts/in-repo-memory-search.py modify --store <dir> --id <id> [--content <text\|->] [--inactive true\|false] [--summary <why>]` — truth-bearing changes append timeline evidence |
| `list-recent` | mtime sort under `memories/` | `find` + sort by mtime, cap N |
| `export` | walk store → JSONL or OKF | `python3 scripts/in-repo-memory-search.py export --format jsonl\|okf` — JSONL includes `compiledTruth` + `timeline` |
| `import` | JSONL or OKF → files | `python3 scripts/in-repo-memory-search.py import --format jsonl\|okf`; legacy records get `kind: imported` timeline; regenerates `index.md`/`log.md` |
| `tasks.*` | — | not supported (`tasks: false`) |
| `maintain-derived` | regenerate `index.md` + `log.md` | `python3 scripts/in-repo-memory-search.py maintain-derived --store <dir>` — orientation lines prefer compiled truth; store `log.md` does not replace per-memory timelines |
| `playbook.match` | `memory_playbook.py match` | `python3 scripts/memory_playbook.py match --signals-json '<json>'` |
| `playbook.primary-inject` | `memory_playbook.py primary-inject` | keyword + confidence primary context blocks for dispatch |
| `playbook.record-usage` | `memory_playbook.py record-usage` | increment `usage_count` / optional `success_count`; reconcile confidence |
| `playbook.reconcile-confidence` | `memory_playbook.py reconcile-confidence` | auto promote/demote confidence for learning/code-context/playbook |
| `playbook.evaluate-promotion` | `memory_playbook.py evaluate-promotion` | gate `draft`→`active` on audit telemetry + skeptic pass |
| `traverse` | `in-repo-memory-search.py traverse` | `python3 scripts/in-repo-memory-search.py traverse --store <dir> --from <id> [--edge] [--depth]` |
| `link` | frontmatter `links[]` + inline md links | typed edges stored and traversed; dangling targets tolerated |

## Canonical category → file location

| Canonical | Location | Notes |
| --- | --- | --- |
| `decision` | `memories/<id>.md` | |
| `learning` | `memories/<id>.md` | |
| `debug` | `memories/<id>.md` | `relatedFiles` required |
| `design` | `memories/<id>.md` | |
| `code-context` | `memories/<id>.md` | `relatedFiles` required; optional `confidence`/`usage_count`/`success_count` |
| `playbook` | `memories/<id>.md` | structured playbook (`triggerKeywords`, steps, verification); promotion gated per R33 |
| `research` | `memories/<id>.md` | |
| `discussion` | `memories/<id>.md` | distilled only — never raw transcript |
| `progress` | `memories/<id>.md` | sparingly |
| `rule` | `rules/<id>.md` | **explicit user request only**; always committed |

## Scope mapping

- project memory → `memories/<id>.md` under the repo store (default).
- global memory → `global/memories/<id>.md` under the store (only on explicit user direction).
- search scope: default searches committed `memories/` (+ `global/memories/` when scope is global).

## Read recipe specifics

When `semanticSearch:false` (this provider):

1. Run `scripts/in-repo-memory-search.py` with the query and optional filters.
2. Results are ranked `{id, summary}` JSON — summary prefers the first line of **compiled truth**
   (falls back to the full body for legacy files).
3. `expand` returns frontmatter, `compiledTruth`, `timeline`, remaining body sections (e.g. `# Citations`),
   and backlinks.
4. File-path search: pass `--file-glob` with a path fragment; matches `relatedFiles` frontmatter entries.
5. Category narrowing: pass `--category <canonical>`.
6. Recency: sort by `createdAt` frontmatter or file mtime when `recencyControl` is needed.

Identical inputs → identical ranked output (deterministic).

## Write recipe specifics

1. **Lazy store create:** `mkdir -p` the store dirs on first write — no `/sw-setup` required.
2. **Redaction (R41):** pipe every payload through `scripts/memory-redact.py` before writing
   (`store`, `update-truth`, and `modify` all redact).
3. **Truth writes:** prefer `update-truth` for understanding changes; ordinary `modify` still appends
   timeline evidence and must not silently overwrite history.
4. **Commit mode:** `memory.inRepo.commitMode: committed` (default) writes under `.cursor/sw-memory/memories/`.
   `local` writes non-rule memories under `.cursor/sw-memory-local/memories/` (gitignored).
5. **Rules always committed:** `category: rule` always writes to `.cursor/sw-memory/rules/` regardless of
   commit mode.
6. **No auto-seed:** store starts empty; never create starter rule files.
7. Search before store; on near-duplicate, `modify` / `update-truth` instead of a second file.
8. Never auto-store `rule`; never re-store rules just read from `rules-load`.

## Notes / gotchas

- Playbook confidence (R27): `confidence` (0.0–1.0), `usage_count`, `success_count` on `learning`, `code-context`, and `playbook` records. Auto promote/demote by configured success-rate thresholds; confidence input is audited usage, not self-reported.
- Playbook promotion (R33): `playbookStatus: active` requires `auditTelemetryRef` (R3/R4 claims-audit JSON with pass verdict) and `skepticVerdict: pass`.

- Link traversal: `links[]` frontmatter plus inline markdown links form the edge map; `traverse` and `expand` (backlinks) use it. Unknown frontmatter keys (including `title`, `description`, `resource`) are preserved on read/write.
- Optional `# Citations` body section lists external references (URLs or repo paths) separate from memory-to-memory `links[]`.
- Offline-first: no network required for read, write, or guardrail rule injection.
- Fresh-install marker: `.cursor/sw-memory.provider` containing `in-repo` opts the repo into fail-closed
  guardrails without hand-authored `workflow.config.json`.
- Rule trust: committed rule files are untrusted until allowlisted + schema-validated (R42).

## Non-goals (PRD 077)

- **No second memory provider.** Catalog id remains `in-repo` only — no `brain` / `brain-md` provider row.
- **No `brain/` SoT directory** and no Node Brain.md CLI dependency.
- **No MindMux / external `brain/` interop** in v1 (no bidirectional import/export with external Brain.md trees).
- Does **not** implement MemPalace, basic-memory, Obsidian, Recallium, or `AGENTS.md` provider work
  (portfolio item D is in-repo enhancement only; depends on PRD 071).
