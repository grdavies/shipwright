---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: memory.provider
      equals: "in-repo"
  metadata:
    providerFamily: memory
    adapterId: in-repo
    selectionFamily: providers
    gateRef: check-gate.sh
---

# Provider adapter: in-repo

Maps the Shipwright memory capability spec ([`skills/memory/CAPABILITIES.md`](../skills/memory/CAPABILITIES.md))
onto committed markdown files with YAML frontmatter. Selected when `workflow.config.json` → `memory.provider`
is `in-repo`, or when `.cursor/sw-memory.provider` marks the repo (zero-config fresh install).

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
createdAt: 2026-06-23T12:00:00Z
---
Distilled memory body here.
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

`semanticSearch` is `false`: retrieval uses `scripts/in-repo-memory-search.sh` (keyword body match +
frontmatter filters). `export`/`import` are native: walk the store and emit/consume neutral JSONL per
`CAPABILITIES.md`.

## Operation mapping

| Abstract op | Implementation | Call shape |
| --- | --- | --- |
| `load-context` | scan store mtime + `rules-load` | list recent files under `memories/`; load rules from `rules/` |
| `rules-load` | read `rules/*.md` | filesystem read of committed rule files |
| `search` | `in-repo-memory-search.sh` | `bash scripts/in-repo-memory-search.sh --store <dir> --query <q> [--category] [--tag] [--file-glob]` |
| `expand` | read file body | read `memories/<id>.md` or `rules/<id>.md` by id |
| `store` | write file after redaction | pipe payload through `scripts/memory-redact.sh`, then write one `.md` file |
| `modify` | update frontmatter / body / `inactive:true` | rewrite the target file |
| `list-recent` | mtime sort under `memories/` | `find` + sort by mtime, cap N |
| `export` | walk store → JSONL | one JSON object per line (frontmatter + body) |
| `import` | JSONL → files | write one file per line after redaction |
| `tasks.*` | — | not supported (`tasks: false`) |
| `link` | frontmatter `links[]` only | store typed edges as-written; **not traversed** (edge-degraded, R13) |

## Canonical category → file location

| Canonical | Location | Notes |
| --- | --- | --- |
| `decision` | `memories/<id>.md` | |
| `learning` | `memories/<id>.md` | |
| `debug` | `memories/<id>.md` | `relatedFiles` required |
| `design` | `memories/<id>.md` | |
| `code-context` | `memories/<id>.md` | `relatedFiles` required |
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

1. Run `scripts/in-repo-memory-search.sh` with the query and optional filters.
2. Results are ranked `{id, summary}` JSON — summary is the first line of the body (trimmed).
3. `expand` reads the full file for selected ids.
4. File-path search: pass `--file-glob` with a path fragment; matches `relatedFiles` frontmatter entries.
5. Category narrowing: pass `--category <canonical>`.
6. Recency: sort by `createdAt` frontmatter or file mtime when `recencyControl` is needed.

Identical inputs → identical ranked output (deterministic).

## Write recipe specifics

1. **Lazy store create:** `mkdir -p` the store dirs on first write — no `/sw-setup` required.
2. **Redaction (R41):** pipe every payload through `scripts/memory-redact.sh` before writing.
3. **Commit mode:** `memory.inRepo.commitMode: committed` (default) writes under `.cursor/sw-memory/memories/`.
   `local` writes non-rule memories under `.cursor/sw-memory-local/memories/` (gitignored).
4. **Rules always committed:** `category: rule` always writes to `.cursor/sw-memory/rules/` regardless of
   commit mode.
5. **No auto-seed:** store starts empty; never create starter rule files.
6. Search before store; on near-duplicate, `modify` instead of a second file.
7. Never auto-store `rule`; never re-store rules just read from `rules-load`.

## Notes / gotchas

- Edge-degraded: `links[]` are stored in frontmatter but not traversed for graph queries.
- Offline-first: no network required for read, write, or guardrail rule injection.
- Fresh-install marker: `.cursor/sw-memory.provider` containing `in-repo` opts the repo into fail-closed
  guardrails without hand-authored `workflow.config.json`.
- Rule trust: committed rule files are untrusted until allowlisted + schema-validated (R42).
