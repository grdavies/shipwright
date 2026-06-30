---
name: memory-preflight
description: Provider-agnostic durable-memory access for the Shipwright workflow. Use at the start of any phase command (execute, coderabbit, stabilize, watch-ci) to load relevant memories and rules, and at the end to store distilled memories. Routes through the configured memory provider adapter so no command names a provider directly.
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: memory
      command: sw-memory-sync
  metadata:
    skill: memory
    selectionFamily: memory
---

# memory-preflight

The single entry point every Shipwright command uses to read and write durable memory. It hides the
provider behind the capability spec in [`CAPABILITIES.md`](CAPABILITIES.md), so swapping providers is a
config change, never a command edit.


**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.sh --skill memory`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Resolve the provider (first step, always)

1. Read `.cursor/workflow.config.json` → `memory.provider`, `memory.project`, `memory.defaultScope`.
   When no config exists, check `.cursor/sw-memory.provider` (per-repo marker) — if present, provider is
   `in-repo` with project = workspace basename. Fall back to documented defaults (`provider: in-repo` when
   marker present, else `recallium`, `defaultScope: project`).
2. Load the adapter at `providers/<memory.provider>.md` from the plugin. It defines the concrete tool
   calls and declares capability flags.
3. If the provider is unreachable, degrade: continue using `agentsFile` + repo docs, and tell the user
   memory is offline. Never block the workflow on a memory outage.

## Pre-work search (mandatory)

Every **work-performing** command MUST run a scoped `memory-preflight` **search** (read mode) before its
first substantive mutation. The enumerated surfaces are: `/sw-execute`, `/sw-debug` (`rca-core` entry),
`/sw-prd`, `/sw-brainstorm`, `/sw-amend`, `/sw-review`, `/sw-stabilize`. Route through this skill +
`providers/<memory.provider>.md` only — never call a provider tool directly (`sw-guardrails`).

### Scoped read recipe

Follow `CAPABILITIES.md` **Read recipe**, scoped to the surface being touched:

1. **Recency OFF** (`recentOnly: false`) — durable facts are not recent-only.
2. Run **scoped searches**, not one broad query:
   - **file-path** search on the paths the command will touch,
   - **semantic** search on the change type / PRD / feature / surface,
   - **category** narrowing when the adapter supports `categoryFilter`.
3. Search these classes: `rule`, `decision`, `learning`, `code-context`, `design`.
4. `expand` only the handful of ids that look relevant before mutation.

Per-command scope hints remain in the table under **Read mode (preflight)** below; the obligation and
recipe above apply to every enumerated work-performing surface.

### Surface and reconcile

Hits MUST be **surfaced to the acting agent before mutation** and **reconciled** against found
rules/decisions:

- An **applicable `rule`** or a **contradicting prior `decision`** is a reconcile obligation — record
  alignment or an explicit conflict + how it is resolved; never silently ignore.
- A direct conflict with a **frozen** decision/rule that cannot be reconciled is a **blocker** — halt per
  the invoking command's halt contract (do not proceed with mutation).
- Memory remains an input, not an authority — except `decision`-class SoT per **Source of truth
  resolution** when memory-SoT is active.

### Recording (mechanical)

Record the pre-work search breadcrumb before the first substantive mutation:

```bash
python3 scripts/wave.sh memory prework record \
  --surface sw-execute \
  --scope "core/skills/memory/SKILL.md" \
  --classes rule,decision,learning,code-context,design \
  [--hit-count N]
```

The shared recorder (`scripts/wave_memory_prework.py`) writes a redacted per-surface artifact to
`.cursor/hooks/state/memory-prework-search.json` and appends an auditable line to
`.cursor/sw-deliver-runs/run.log`. Outcomes:

| Probe / search | `outcome` | Gate behavior |
| --- | --- | --- |
| Provider unreachable (mechanical probe) | `memory:offline` | Satisfies degrade-open gate (R6) |
| Search completed, zero relevant hits | `memory:none` | Satisfies gate (R7) |
| Search completed with hits | `memory:hits` | Satisfies gate; hits surfaced + reconciled (R5) |

Offline is **probe-gated** — never agent-asserted. Enforcement at the first file-mutating tool call
reuses the PRD 017 `preToolUse` deny path (Phase 3).

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
python3 scripts/memory-sot.sh resolve --class decision --json
# effective: repo | memory

python3 scripts/memory-sot.sh resolve --class learning --json
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
python3 scripts/memory-redact.sh <<'EOF'
<payload>
EOF
```

Or: `python3 scripts/memory-redact.sh path/to/file`. The filter is deterministic (same input → same output),
runs offline, and scrubs the named corpus in `rules/memory-guardrails.mdc` (AWS keys, GitHub PATs, JWTs,
`Bearer` tokens, PEM private keys, emails). Never persist or re-inject unredacted content.

**Fail-closed (R10):** if `memory-redact.sh` exits non-zero, abort the provider write **and** any snapshot
write (`scripts/memory-decision-snapshot.sh write` propagates the failure). A provider outage after a
successful snapshot stamp degrades to the committed snapshot with a warning — never block freeze/CI.

## Write mode (after substantive work)

Store distilled memories per the write contract in `CAPABILITIES.md`:

- pick the canonical category (decision / learning / debug / design / code-context / research /
  discussion); never a generic catch-all,
- set `relatedFiles` + stable tags (`prd-<n>`, `task-<n>`, `surface:<cmd>`),
- **run `scripts/memory-redact.sh` on the payload first** (R41 chokepoint),
- search before store; `modify` a near-duplicate instead of adding a second,
- project scope by default; global only on explicit user direction,
- store the distilled substance, never a raw transcript dump.

For **`decision`-class** writes, resolve the inverted pointer recipe first (R6):

```bash
python3 scripts/memory-sot.sh pointer-recipe --path docs/decisions/<n>-<slug>.md [--memory-id <provider-id>] --json
```

| Effective SoT | Provider write | Git snapshot |
| --- | --- | --- |
| `repo` | Pointer only — `relatedFiles: [docs/decisions/...]`; never the record body | Authoritative (`snapshotRole: authoritative`) |
| `memory` | Content-bearing authoritative record (redacted) | Pointer (`snapshotRole: pointer`, `memoryPointer`) |

Exactly one side is authoritative at a time; the recipe JSON names `authoritative` vs `nonAuthoritative`.

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
python3 scripts/in-repo-memory-search.sh \
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

## Planning store memory backend (PRD 034 R11/R23)

When `planning.store.backend` is `memory`, unit **bodies** route through this skill's provider adapter and
`scripts/memory-redact.sh` on read and write — **body storage only**; the memory backend does not alter
source-of-truth for any planning class. Decision-class units under `docs/planning/decision/` still follow
the PRD-015 committed redacted snapshot + pointer flow regardless of `visibility`. The authoritative
decision record paths remain `docs/decisions/<n>-<slug>.md` (repo-SoT) or the provider record (memory-SoT)
per **Source of truth resolution** below — the planning-store memory backend never replaces that contract.

## Decision records (file-linked deliverables)

**Boundary rule (R32 / KTD3 + provider-conditional SoT):**

Resolve authority first: `python3 scripts/memory-sot.sh resolve --class decision --json`.

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
forward pointer (`memoryPointer` in frontmatter — see `scripts/memory-decision-snapshot.sh write`).

**Supersede reconciliation (`docs/decisions/SUPERSEDED.log`):**

On record-level supersede, append the superseded path via:

```bash
python3 scripts/reconcile-status.sh append-superseded --path docs/decisions/<old>.md --replacement docs/decisions/<new>.md
```

`/sw-memory-sync` runs `python3 scripts/reconcile-status.sh supersede-reconcile --json` after distillation and
best-effort re-points the **non-authoritative** side per the active SoT (provider `relatedFiles` under
repo-SoT; git snapshot pointer under memory-SoT). Pointer freshness is **auditable, not transactional**
(provider out of CI reach).

## Boundaries

- Never call a provider tool directly from a command; always go through this skill + the adapter.
- Never write `rule`-category memories unless the user explicitly asks ("remember this", "add a rule").
- Never store secrets, credentials, tokens, or raw transcript content.
