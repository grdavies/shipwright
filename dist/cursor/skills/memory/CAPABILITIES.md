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
| `search` | query, {filePath?, category?, recentOnly?, scope?, mode?} | ranked memories (summary + id) | Targeted retrieval; excludes `status: superseded`/`resolved`/tombstone by default. |
| `traverse` | from-id, {edge?, depth?, direction?} | nodes + edges (+ dangling) | Walk `links[]` + inline markdown links; dangling targets tolerated. |
| `expand` | ids[] | full memory content + backlinks | Fetch full text after a search; includes inbound edges. |
| `store` | content, category, {relatedFiles?, tags?, importance?, scope?, links?, session?} | memory id | Write a distilled memory. |
| `modify` | id, action(update/inactivate/reactivate), fields? | confirmation | Edit / soft-delete / restore. |
| `list-recent` | project, days_back? | recent memories + tasks | Activity recap. |
| `tasks` *(optional)* | create/update/complete/list, fields | task id / list | Cross-repo phase board. |
| `link` *(optional)* | from-id, to-ids | confirmation | Knowledge-graph links. |
| `export` *(optional)* | project, scope?, `format` (`jsonl` \| `okf`) | neutral JSONL or OKF bundle dir | Portability snapshot. |
| `import` *(optional)* | neutral JSONL or OKF bundle, `format` | ids[] | Ingest portability snapshot. |

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
| `export` / `import` | neutral JSONL + OKF bundle interchange | provider swap requires manual re-distillation from raw transcripts |
| `softDelete` | inactivate vs hard delete | treat modify-inactivate as best effort |
| `semanticSearch` | vector / embedding search | use keyword + frontmatter filtering (`scripts/in-repo-memory-search.py` for in-repo) |

## Canonical category map (write contract)

Adapters map these canonical categories to provider-native types.

| Canonical | When | Notes |
| --- | --- | --- |
| `decision` | chosen approach + alternatives + why-not | rationale, not just the choice |
| `learning` | durable lesson / footgun discovered | the thing you'd want to not relearn |
| `debug` | bug root-cause + fix | `relatedFiles` required |
| `design` | architecture / performance rationale | |
| `code-context` | file-linked implementation context | `relatedFiles` required |
| `playbook` | repo skill / procedure playbooks with trigger keywords | structured steps + verification; see **Playbook contract** below |
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
- Optional frontmatter: `title`, `description`, `resource` (unknown keys preserved). Body may include a `# Citations` section for external references.
- `memory-preflight` populates `title`/`description` at store time from the distilled first line when omitted.

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

`scripts/memory-redact.py` is the single deterministic filter every ingestion edge invokes before
`store`, re-injection, or compounding. Same input → same redacted output; offline; no provider calls.

## Neutral interchange format (export/import)

One JSON object per line:

```json
{"content":"...","category":"decision","tags":["prd-12","surface:execute"],"relatedFiles":["server/x.ts"],"importance":0.7,"scope":"project","createdAt":"2026-06-17T00:00:00Z","links":[]}
```

Raw chat transcripts are **not** part of this format and are never stored in a provider; they remain in
the platform's `agent-transcripts/*.jsonl` and stay re-distillable.



## OKF bundle interchange (`export` / `import --format okf`)

OKF v0.1 bundles are directories of markdown concept files with YAML frontmatter. Shipwright maps
canonical `category` → required OKF `type`, preserves unknown frontmatter keys, and lays out
per-category subdirectories. Bundle root `index.md` declares `okf_version: "0.1"`.

**In-repo adapter:**

```bash
python3 scripts/in-repo-memory-search.py export --store .cursor/sw-memory --format okf --out /tmp/bundle
python3 scripts/in-repo-memory-search.py import --store .cursor/sw-memory --format okf --source /tmp/bundle
```

**Recallium adapter:** `/sw-memory-export` and `/sw-memory-import` synthesize the same OKF bundle by
walking provider records (`search` + `expand`) into per-category markdown files. Export applies the
`scripts/memory-redact.py` chokepoint before writing bundle files.

**Migration:** bespoke JSONL export remains supported (`--format jsonl`). Round-trip
`jsonl → okf → store → jsonl` preserves neutral fields.

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

## Playbook contract (R26, R33)

`playbook` memories are structured procedural playbooks stored under the in-repo adapter (`category: playbook`).
Each playbook file uses YAML frontmatter plus a body with `# Prerequisites`, `# Steps`, and `# Verification`.

| Field | Required | Purpose |
| --- | --- | --- |
| `triggerKeywords` | yes | Keyword list for dispatch-time primary injection matching |
| `prerequisites` | optional | Preconditions (frontmatter list and/or `# Prerequisites` bullets) |
| `playbookStatus` | yes | `draft` or `active` — only `active` may primary-inject |
| `confidence` | yes | `0.0`–`1.0` usage-derived score (learning/code-context/playbook only) |
| `usage_count` / `success_count` | yes | Audited usage telemetry inputs (D4) |
| `auditTelemetryRef` | for promotion | Path to R3/R4 claims-audit JSON — not self-reported |
| `skepticVerdict` | for promotion | `pass` \| `fail` \| `pending` adversarial verification (R7 pattern) |

Each step in `# Steps` uses `## Step N: <title>` with bullets:

- `command:` shell/command to run
- `expected:` expected stdout/exit semantics
- `fallback:` recovery when expected output is absent

### Playbook operations

```bash
python3 scripts/memory_playbook.py match --signals-json '<signal_context>'
python3 scripts/memory_playbook.py primary-inject --signals-json '<signal_context>'
python3 scripts/memory_playbook.py record-usage --id <playbook-id> [--success]
python3 scripts/memory_playbook.py reconcile-confidence
python3 scripts/memory_playbook.py evaluate-promotion --id <playbook-id> [--promote]
```

**Promotion gate (R33):** `draft` → `active` and primary-injection eligibility require audited claims telemetry (`auditTelemetryRef` resolves to passing R3/R4 output) **and** `skepticVerdict: pass`. Confidence auto-promote/demote (R27) is scoped to `learning`, `code-context`, and `playbook` only — human `rule` promotion is unchanged.

## Adapter registration checklist (PRD 071 R5)

Authors register providers in `.sw/memory-provider-catalog.json` and ship matching adapter docs +
rules scripts. `scripts/memory_provider_register.py` validates charset, catalog membership, adapter
integrity, and rules script reachability before config writes, startup/preflight, or hook trust.

| Checklist item | Catalog / adapter contract |
| --- | --- |
| **Dual-transport** | `hookTransport.agentSession` (`mcp` \| `filesystem` \| `rest`) plus `ruleFetch` (`out-of-band-script` \| `inline-filesystem` \| `none`). `hookTransport.notes` and optional `restFetchPolicy` are policy inputs — not advisory-only. |
| **Category map** | Adapter maps canonical categories in the table above; banned catch-alls remain rejected at store time. |
| **R41 redaction** | Every ingestion edge invokes `scripts/memory-redact.py` before `store` (see **Redaction chokepoint**). |
| **Degrade-open** | Capability flags declare what commands may skip or soften; `false` never blocks unrelated surfaces. |
| **Interchange** | `interchange.jsonl` / `interchange.okf` declare `native` \| `synthesized` \| `unsupported` for export/import flows. |
| **Credentials (secret-store-only)** | `credentials.location` is `none`, `env-only`, or `secret-store`. Secrets live only in environment/secret-store — never catalog rows, config bodies, memory content, or hook stdout. `credentials.notes` documents the secret-store-only binding. |

### REST fetch SSRF policy

Shared REST probes and out-of-band rule-fetch scripts route through `scripts/sw_recallium_url.py`.
Policy is derived from catalog `hookTransport.restFetchPolicy` (with transport-aware defaults):

- **Allowlist first** — explicit `allowedHosts` win.
- **Block by class** — loopback, link-local, private, and cloud-metadata hosts are rejected unless
  the catalog policy opts in (`allowLoopback`, `allowLinkLocal`, `allowPrivate`, `allowMetadata`).
- **Recallium** — localhost-only REST for guardrail rule-fetch; MCP remains the agent-session transport.
- **REST providers** — fail closed until `restFetchPolicy` documents reachable hosts.

Conformance: `scripts/unit_tests/memory/test_adapter_checklist.py` asserts seeded catalog rows satisfy
this checklist (including the credentials clause).

