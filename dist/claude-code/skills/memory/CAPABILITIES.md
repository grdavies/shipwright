# Memory provider capability spec

This is the provider-agnostic contract for durable memory in Shipwright. Commands and skills speak
**only** this vocabulary. A provider adapter (`providers/<name>.md`) maps each abstract operation to
concrete tool calls. To support a new provider, add an adapter that implements these operations and
declares its capability flags — change no command.

## Operations

| Op | Inputs | Returns | Purpose |
| --- | --- | --- | --- |
| `load-context` | project, days_back? | rules + recent activity + open tasks | One-shot session warmup. |
| `rules-load` | scope (project/global) | behavioral rules | Load guardrails (startup, project switch). |
| `search` | query, {filePath?, category?, recentOnly?, scope?, mode?} | ranked memories (summary + id) | Targeted retrieval. |
| `expand` | ids[] | full memory content | Fetch full text after a search. |
| `store` | content, category, {relatedFiles?, tags?, importance?, scope?, links?, session?} | memory id | Write a distilled memory. |
| `modify` | id, action(update/inactivate/reactivate), fields? | confirmation | Edit / soft-delete / restore. |
| `list-recent` | project, days_back? | recent memories + tasks | Activity recap. |
| `tasks` *(optional)* | create/update/complete/list, fields | task id / list | Cross-repo phase board. |
| `link` *(optional)* | from-id, to-ids | confirmation | Knowledge-graph links. |
| `export` *(optional)* | project, scope? | neutral JSONL | Portability snapshot. |
| `import` *(optional)* | neutral JSONL | ids[] | Ingest portability snapshot. |

## Capability flags

Each adapter declares these so commands can degrade gracefully:

| Flag | Meaning | Degradation when false |
| --- | --- | --- |
| `typedMemories` | distinct categories beyond a free-text note | store everything as a single note type; skip category narrowing in search |
| `filePathSearch` | search by file-path pattern | fall back to semantic search on the path string |
| `categoryFilter` | filter search by category | post-filter client-side or skip |
| `recencyControl` | toggle recency on/off | accept provider default |
| `rulesAtStartup` | load behavioral rules | rely on `agentsFile` only |
| `tasks` | native task board | use local registry fallback for the phase board |
| `export` / `import` | neutral interchange | provider swap requires manual re-distillation from raw transcripts |
| `softDelete` | inactivate vs hard delete | treat modify-inactivate as best effort |
| `semanticSearch` | vector / embedding search | use keyword + frontmatter filtering (`scripts/in-repo-memory-search.sh` for in-repo) |

## Canonical category map (write contract)

Adapters map these canonical categories to provider-native types.

| Canonical | When | Notes |
| --- | --- | --- |
| `decision` | chosen approach + alternatives + why-not | rationale, not just the choice |
| `learning` | durable lesson / footgun discovered | the thing you'd want to not relearn |
| `debug` | bug root-cause + fix | `relatedFiles` required |
| `design` | architecture / performance rationale | |
| `code-context` | file-linked implementation context | `relatedFiles` required |
| `research` | external findings, audits, doc reads | |
| `discussion` | **distilled** conversation / debate / session recap | never verbatim transcript |
| `progress` | milestone / checkpoint | sparingly; prefer tasks |
| `rule` | durable behavioral guardrail | **explicit user request only** |

Banned as catch-alls: a generic `feature` bucket, `general`, and any `project-*` mirror type (those are
repo docs, referenced by pointer, not copied into memory).

### Write requirements

- Always set `relatedFiles` for `debug` / `code-context` (and whenever a memory concerns specific files).
- Always set stable `tags`: `prd-<n>`, `task-<n>`, and a `surface:` tag (`execute|review|stabilize|sync`).
- Set `importance` deliberately: `0.9` critical, `0.7` important, `0.5` normal, `0.3` minor.
- Default `scope` = project. Global only when the user explicitly directs it.
- Search before store (idempotency): if a near-duplicate exists, `modify` it instead of adding a second.

## Read recipe (used by `memory-preflight`)

1. Recency OFF by default (`recentOnly: false`) — durable facts are not recent-only.
2. Run scoped searches, not one broad query:
   - file-path search on the changed paths,
   - semantic search on the change-type / PRD / surface,
   - optional category narrowing (when `categoryFilter`).
3. Default search target is distilled memories; only escalate to "everything / full context" for
   "what happened" recaps.
4. `expand` only the handful of ids that look relevant.

## Redaction chokepoint (R41 — live)

`scripts/memory-redact.sh` is the single deterministic filter every ingestion edge invokes before
`store`, re-injection, or compounding. Same input → same redacted output; offline; no provider calls.

## Neutral interchange format (export/import)

One JSON object per line:

```json
{"content":"...","category":"decision","tags":["prd-12","surface:execute"],"relatedFiles":["server/x.ts"],"importance":0.7,"scope":"project","createdAt":"2026-06-17T00:00:00Z","links":[]}
```

Raw chat transcripts are **not** part of this format and are never stored in a provider; they remain in
the platform's `agent-transcripts/*.jsonl` and stay re-distillable.

## Relationship edges (first-class)

Neutral JSONL `links[]` entries use typed edges:

| Edge | Meaning |
|------|---------|
| `supersedes` | newer memory replaces older |
| `relates-to` | soft association |
| `file-linked` | ties memory to repo paths |

Recallium is **edge-degraded**: native `link_task_memories` is untyped. Live ops store flat memories +
a typed `relationships` sidecar in export/import. Full typed-edge round-trip validated against a stub
edge-capable provider.

## Ingestion redaction (R41)

All write paths run the shared redaction chokepoint before `store` (see `rules/memory-guardrails.mdc`).
