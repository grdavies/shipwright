---
name: memory-preflight
description: Provider-agnostic durable-memory access for the Shipwright workflow. Use at the start of any phase command (execute, coderabbit, stabilize, watch-ci) to load relevant memories and rules, and at the end to store distilled memories. Routes through the configured memory provider adapter so no command names a provider directly.
---

# memory-preflight

The single entry point every Shipwright command uses to read and write durable memory. It hides the
provider behind the capability spec in [`CAPABILITIES.md`](CAPABILITIES.md), so swapping providers is a
config change, never a command edit.


**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill memory`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Resolve the provider (first step, always)

1. Read `.cursor/workflow.config.json` → `memory.provider`, `memory.project`, `memory.defaultScope`.
   When no config exists, check `.cursor/sw-memory.provider` (per-repo marker) — if present, provider is
   `in-repo` with project = workspace basename. Fall back to documented defaults (`provider: in-repo` when
   marker present, else `recallium`, `defaultScope: project`).
2. Load the adapter at `providers/<memory.provider>.md` from the plugin. It defines the concrete tool
   calls and declares capability flags.
3. If the provider is unreachable, degrade: continue using `agentsFile` + repo docs, and tell the user
   memory is offline. Never block the workflow on a memory outage.

## Read mode (preflight)

Run before doing the command's real work. Follow the read recipe in `CAPABILITIES.md`:

- recency OFF unless the task is explicitly "recent",
- scoped searches (file-path + semantic + optional category), not one broad query,
- `expand` only the few relevant hits.

Per-command read templates:

| Command | What to retrieve |
| --- | --- |
| `/phase-execute` | PRD/task memories; `code-context` for the target files (file-path search); domain `decision`/`learning`. |
| `/coderabbit` | known false-positives; review patterns; `code-context` for changed paths. |
| `/stabilize-pr` | prior CI-failure `debug`; bot-pattern `learning`; changed-path context. |
| `/watch-ci` | lazy — only search on a red run, scoped to the failing job/check. |
| `/phase-start` | only on a non-routine branch decision (parent ambiguity, prior workflow correction). |

Memory is an input, not an authority: git state, the per-repo `stateFile`, `agentsFile`, and repo
doctrine remain the sources of truth — except for the `decision` doc class when memory-SoT is active
(see **Source of truth resolution** below).

## Source of truth resolution (decision class only — R1–R3)

The `decision` doc class has a provider-conditional authoritative side. All other classes
(`learning`, `design`, `debug`, etc.) remain **distillation-only** — the SoT switch does not apply.

Single source for freeze, compound, and audit:

```bash
bash scripts/memory-sot.sh resolve --class decision --json
# effective: repo | memory

bash scripts/memory-sot.sh resolve --class learning --json
# effective: distillation (scope guard)
```

**Config:** `memory.sourceOfTruth` — `repo` | `memory` | `auto` (default `auto`).

| Knob | Provider | Effective SoT |
| --- | --- | --- |
| `auto` | `recallium` (external) | `memory` |
| `auto` | `in-repo` / none | `repo` |
| `repo` | any | `repo` |
| `memory` | any | `memory` |

Default `auto` + `in-repo` preserves today's R32/KTD3 behavior (no change for existing repos).

## Redaction chokepoint (R41 — mandatory before persist/re-inject)

Before **any** `store`, transcript distillation (`/sw-memory-sync`), or compounding write, pipe content
through the executable filter:

```bash
bash scripts/memory-redact.sh <<'EOF'
<payload>
EOF
```

Or: `bash scripts/memory-redact.sh path/to/file`. The filter is deterministic (same input → same output),
runs offline, and scrubs the named corpus in `rules/memory-guardrails.mdc` (AWS keys, GitHub PATs, JWTs,
`Bearer` tokens, PEM private keys, emails). Never persist or re-inject unredacted content.

## Write mode (after substantive work)

Store distilled memories per the write contract in `CAPABILITIES.md`:

- pick the canonical category (decision / learning / debug / design / code-context / research /
  discussion); never a generic catch-all,
- set `relatedFiles` + stable tags (`prd-<n>`, `task-<n>`, `surface:<cmd>`),
- **run `scripts/memory-redact.sh` on the payload first** (R41 chokepoint),
- search before store; `modify` a near-duplicate instead of adding a second,
- project scope by default; global only on explicit user direction,
- store the distilled substance, never a raw transcript dump.

Store on: a decision with rationale, a non-obvious lesson, a bug root-cause+fix, an architecture choice,
a notable review/CI pattern, or a distilled session recap. Do not store routine, recoverable steps.

## Capability degradation

Check the adapter's flags and adjust:

- no `semanticSearch` → run `scripts/in-repo-memory-search.sh` (keyword + frontmatter filters) instead of
  vector search; results feed `expand`,
- no `tasks` → the phase board uses the local registry fallback,
- no `filePathSearch` → semantic search on the path string,
- no `categoryFilter` → skip category narrowing / post-filter,
- no `export` → provider swap relies on re-distillation from raw transcripts.

## In-repo provider specifics (`memory.provider: in-repo`)

**Read:** when `semanticSearch:false`, call:

```bash
bash scripts/in-repo-memory-search.sh \
  --store .cursor/sw-memory \
  --query "<terms>" \
  [--category decision] [--tag prd-1] [--file-glob src/auth.ts]
```

Then `expand` by reading `memories/<id>.md` (or `rules/<id>.md` for rule category).

**Write:**

1. Lazy-create store dirs on first write: `mkdir -p .cursor/sw-memory/memories .cursor/sw-memory/rules`.
2. Pipe payload through `scripts/memory-redact.sh` (R41) before any file write.
3. Default `commitMode: committed` → write non-rule files under `.cursor/sw-memory/memories/`.
4. `commitMode: local` → non-rule files under `.cursor/sw-memory-local/memories/` (gitignored).
5. **`category: rule` always writes to `.cursor/sw-memory/rules/`** — offline hook reads committed rules.
6. Never auto-seed starter rules; store starts empty.

## Decision records (file-linked deliverables)

**Boundary rule (R32 / KTD3 + provider-conditional SoT):**

Resolve authority first: `bash scripts/memory-sot.sh resolve --class decision --json`.

| Effective SoT | Authoritative artifact | Memory role |
| --- | --- | --- |
| `repo` | Decision record (`docs/decisions/<n>-<slug>.md`) | Pointer via `relatedFiles` only |
| `memory` | Provider `decision` record (redacted) | Content-bearing; git snapshot is pointer |

| Artifact | Role | Mutable | CI freeze |
|----------|------|---------|-----------|
| Decision record (`docs/decisions/<n>-<slug>.md`) | Up-front, reviewed-before-build deliverable | Only via amendment | Yes |
| `decision`-class memory | Retrospective knowledge distillation | Yes | No |

When repo-SoT is active (default for `in-repo`):

- Read: load the record from git; memory may point at it via `relatedFiles` but is not authoritative.
- Write: store a pointer (`relatedFiles: [docs/decisions/...]`), never the record body.
- Flag content-bearing `decision` memories that duplicate an existing record — they should become pointers.

When memory-SoT is active, the provider record is authoritative; the committed git snapshot carries a
forward pointer (see PRD 015).
**Supersede reconciliation (`docs/decisions/SUPERSEDED.log`):**

On record-level supersede, the superseded path is appended to the committed manifest. `/sw-memory-sync`
reconciles `decision`-class memories still linking a `SUPERSEDED.log` path — best-effort re-point to the
replacement record. Pointer freshness is **auditable, not transactional** (provider out of CI reach).

## Boundaries

- Never call a provider tool directly from a command; always go through this skill + the adapter.
- Never write `rule`-category memories unless the user explicitly asks ("remember this", "add a rule").
- Never store secrets, credentials, tokens, or raw transcript content.
