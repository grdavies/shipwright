# Configuration

Shipwright configures **per target repo** — open your project and run `/sw-init` (`/sw-setup` is a
deprecated alias with identical behavior).

## Scripts resolution (consumer repos)

Consumer repos receive **no** repo-local Shipwright scripts tree. `/sw-init` configures
`.cursor/workflow.config.json` only — it does **not** emit façade forwarders under `scripts/`. Runtime
helpers resolve from the installed plugin through the canonical bootstrap CLI:

```bash
python3 scripts/sw_bootstrap.py --print check-gate.py
python3 scripts/sw_bootstrap.py check-gate.py
python3 scripts/sw_bootstrap.py host.py -- pr-view --number 42
```

| Precedence | Source | When |
| --- | --- | --- |
| 1 | Self-repo `scripts/` | Shipwright plugin source / harness checkout only |
| 2 | `SHIPWRIGHT_SCRIPTS` | Trusted absolute override (must contain trust markers) |
| 3 | Plugin install | `~/.cursor/plugins/local/shipwright/scripts` or marketplace/cache roots |

**Operator default:** copy-paste bootstrap argv from guides and command procedures — not absolute plugin
paths and not repo-root façade emit instructions.

**Legacy façades:** repos that previously received forwarders can detect and remove them via `/sw-init` doctor
(`core/commands/sw-init.md` §6c) or:

```bash
python3 scripts/sw_bootstrap.py init_scripts_facade.py -- . detect
python3 scripts/sw_bootstrap.py init_scripts_facade.py -- . remove --confirm
```

**Troubleshooting-only:** when bootstrap resolution fails, verify the plugin install path exists and contains
`check-gate.py` (for example `~/.cursor/plugins/local/shipwright/scripts`). Reinstall from the Shipwright
source repo with `python3 scripts/install.py` when the tree is missing.

## Credential references and machine-local selector

Shipwright stores **non-secret credential references** in committed config and resolves secret material
through the credential broker at runtime. Tokens never belong in config bodies, selector files, or journals.

### Project id (`projectId`)

Every target repo declares a top-level `projectId` — a stable slug matching `^[a-z][a-z0-9-]*$`. The broker
binds each `credentialRef` to this project id and to the repository remote for pairing checks. `/sw-init`
seeds `projectId` during guided credential migration.

```json
{
  "projectId": "my-app",
  "host": { "credentialRef": "github-work" }
}
```

### Committed credential surfaces

| Surface | Config path | `credentialRef` role |
| --- | --- | --- |
| **Host** (CI, PR, merge gate) | `host.credentialRef` | Resolves GitHub/GitLab/Bitbucket REST transport |
| **Planning store** (issue-store) | `planning.store.issues.credentialRef` | Resolves issue API mutations (independent of `host.credentialRef`) |
| **Memory** (external providers) | `memory.credentialRef` | Resolves memory REST/MCP auth when the catalog provider requires it |

**Precedence:** `credentialRef` wins when both `credentialRef` and the one-release `tokenEnv` compatibility
alias are set — remove `tokenEnv` before the deprecation cutover. Surfaces with neither reference resolve as
explicitly no-auth (tri-state `unresolved`) rather than falling back to ambient workstation defaults.

### Machine-local selector file

Secret backends and scope live in a **user-owned** selector document — never committed to the code repo:

| Property | Value |
| --- | --- |
| Default path | `$XDG_CONFIG_HOME/shipwright/credential-selector.json` (typically `~/.config/shipwright/credential-selector.json`) |
| Schema | `core/sw-reference/credential-selector.schema.json` |
| File mode | `0600` (user read/write only) |
| Parent dir mode | `0700` |
| Ownership | Current user only — symlinks rejected fail-closed |

**Selector entry shape** (no secret-valued properties):

```json
{
  "version": 1,
  "entries": {
    "github-work": {
      "backend": "environment",
      "provider": "github",
      "hostname": "github.com",
      "account": "work",
      "allowedRepos": ["my-org/my-app"],
      "allowedProjectIds": ["my-app"],
      "allowedEndpoints": ["https://api.github.com"]
    }
  }
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `backend` | yes | One of `environment`, `github_cli`, `git_credential`, `keystore` |
| `provider` | yes | Provider id (`github`, `gitlab`, `recallium`, …) |
| `hostname` | optional | Host hint for `git_credential` / identity probes |
| `account` | optional | Operator-facing account label (keystore account name) |
| `allowedRepos` | yes | Non-empty `owner/repo` allowlist — scope enforcement fails closed outside the list |
| `allowedProjectIds` | yes | Non-empty list — must include committed `projectId` for resolution |
| `allowedEndpoints` | yes | Non-empty `https://…` allowlist — broker refuses downgrade or off-list hosts |

Manage entries with `/sw-init` guided migration or:

```bash
python3 scripts/sw-configure.py credential selector-add \
  --ref github-work --backend environment --provider github \
  --hostname github.com --account work \
  --allowed-repo my-org/my-app --allowed-project-id my-app \
  --allowed-endpoint https://api.github.com
```

**CI declaration:** GitHub Actions runners without a machine-local selector require an explicit repository
selector at `.sw/credential-ci-selector.json` (same entry schema; `skip_integrity` at load). Declare via
`python3 scripts/sw-configure.py credential declare-ci --confirm`.

### Per-platform backend matrix

| Backend | macOS | Windows | Linux | Containers | Secret material source |
| --- | --- | --- | --- | --- | --- |
| `environment` | yes | yes | yes | yes (with CI declaration) | Explicitly declared env var only (`host.tokenEnv` names presence during alias window) |
| `github_cli` | yes | yes | yes | when GitHub CLI is available | Isolated `GH_CONFIG_DIR` subprocess auth |
| `git_credential` | yes | yes | yes | when helper is available | Git credential helper for scoped hostname |
| `keystore` | yes (Keychain) | yes (Credential Manager) | **no** | **no** | Native OS secret store (`shipwright.credential/<ref>` service namespace) |

Selecting `keystore` on Linux or inside a container fails closed with remediation to `environment` or
`github_cli`. Shipwright does **not** depend on the Python `keyring` package — native keystore uses ctypes
bindings to macOS Security and Windows CredRead only.

### Pairing, provenance, and doctor

Trust-on-first-use pairing records live at `$XDG_CONFIG_HOME/shipwright/credential-pairings.json` (same
permission contract as the selector). The append-only provenance journal is
`$XDG_CONFIG_HOME/shipwright/credential-provenance.journal.jsonl` (`pairing_approval`, `scope_change`,
`rotation` events — metadata strings only, no secrets).

Diagnose resolution per surface:

```bash
python3 scripts/credentials-doctor.py --root .
```

The JSON report lists configured `references` (backend + scope + last successful resolution) and per-surface
`credentialRef` / pairing / required-operation verdicts. See [commands — Credential operations](commands.md#credential-operations).

## Greenfield on-ramp

New repos follow one ordered path through `/sw-init` and `sw-configure` — credentials, CI presence, curated
profile defaults, and the annotated example config. Nothing in this path forces a `.env` file or reads
ambient tokens without a declared `environment` backend entry.

### 1 — Credential checklist (broker-only)

`/sw-init` and `python3 scripts/sw_bootstrap.py sw-configure.py -- credential plan` emit the **same four steps** in order:

| Step | Meaning |
| --- | --- |
| Identity source | `github_cli` when authenticated, else a declared env/keystore backend |
| `credentialRef` binding | Committed config references (`host`, planning, memory) point at selector entries |
| Selector allowlists | Machine-local `allowedRepos`, `allowedProjectIds`, `allowedEndpoints` for fail-closed scope |
| Resolution probe | `python3 scripts/sw_bootstrap.py credentials-doctor.py -- --root .` — terminal green path per checklist step |

The selector holds **metadata and allowlists only** — never secret material. Apply with:

```bash
python3 scripts/sw_bootstrap.py sw-configure.py -- credential plan
python3 scripts/sw_bootstrap.py sw-configure.py -- credential apply --confirm
```

### 2 — Named `tokenEnv` (multi-account)

When init detects multi-repo or multi-account risk (more than one remote owner, or an existing selector entry
for a different account), guided apply offers a **named** `tokenEnv` (for example `SW_GITHUB_TOKEN_WORK`)
bound through an explicitly declared `environment` backend — not ambient `GITHUB_TOKEN`. Single-account
`github_cli` remains the default and is not outranked automatically.

Undeclared ambient resolution is **not-ready** in `credentials-doctor` — name the env var in config and
declare the backend in the selector before expecting green.

### 3 — `.env` is optional, never primary

Init never creates or loads `.env` as the primary credential path. An example env file is emitted only on
explicit operator request, appended to `.gitignore`, and consumable solely through a declared
`environment` backend entry in the selector.

### 4 — Consent-gated CI stub

When the repo has no PR workflow or only a default-branch-restricted `pull_request` trigger, offer a
consent-gated stub so `base-preflight:ci-or-review` can satisfy CI presence:

```bash
python3 scripts/sw_bootstrap.py sw-configure.py -- ci-stub plan
python3 scripts/sw_bootstrap.py sw-configure.py -- ci-stub apply --confirm
```

`plan` is read-only (target path + rendered body). `apply` without `--confirm` refuses. Re-apply when a
workflow already exists is an idempotent no-op that preserves operator edits. Explicit decline is recorded at
`.cursor/sw-init-ci-stub.json` so preflight reports decline rather than a silent gap.

### 5 — Curated greenfield profile and annotated example

`/sw-init` seeds **seven** recommended posture keys for hands-off deliver (see **Greenfield init posture**
below). Classification (`present` / `defaulted` / `unset` / `deprecated`) and the annotated reference
config are single-sourced from `init_profile_report`:

```bash
python3 scripts/sw_bootstrap.py init_profile_report.py -- classify --markdown
python3 scripts/sw_bootstrap.py sw-configure.py -- findings
```

Annotated reference (neutral, no dev-harness paths): `core/sw-reference/workflow.config.example.json`.
Copy manually when skipping `/sw-init`:

```bash
cp core/sw-reference/workflow.config.example.json .cursor/workflow.config.json
```

Doctor surfaces drift on re-run and **never silently overwrites** explicit operator values without
`--confirm` on profile refresh.

## `/sw-init`

Run `/sw-init` in your **target project repo**. It walks through setup and writes
`.cursor/workflow.config.json`. Re-run at any time — it acts as a **doctor** against an existing
config, validates project-type detection, surfaces **version drift** when `configuredWith` differs from
the installed plugin, and offers consent-gated refresh without overwriting user-set verify or base branch.

### Step 1 — Memory provider

`memory.provider` is an **open string** — not a closed enum. Operators select a **catalog-registered**
provider id (`^[a-z0-9-]+$`). Shipwright validates the id against `.sw/memory-provider-catalog.json`
(emit: `core/sw-reference/memory-provider-catalog.json`) via `scripts/memory_provider_register.py` on
config write, startup/preflight, and hook trust. **Unknown or invalid ids fail closed** — there is no
legacy two-provider fallback.

| Seeded id | Notes |
|-----------|-------|
| **`in-repo`** (default) | Committed markdown store; zero external dependency; `sourceOfTruthClass: repo-authoritative` |
| `recallium` | External REST/MCP store; requires reachable `memory.connection.restBaseUrl`; `sourceOfTruthClass: memory-authoritative` |
| `mempalace` | Local palace directory + MemPalace MCP (agent session); hook rule-fetch via `providers/mempalace-rules.py`; `sourceOfTruthClass: memory-authoritative` |
| `basic-memory` | Dual-mode Markdown knowledge graph (local loopback MCP or Basic Memory Cloud); hook rule-fetch via `providers/basic-memory-rules.py`; `sourceOfTruthClass: memory-authoritative` |
| `obsidian` | Obsidian vault + Local REST API MCP on loopback; hook rule-fetch via `providers/obsidian-rules.py`; `sourceOfTruthClass: memory-authoritative` |

**Authors register; operators select.** Plugin authors add a catalog row + adapter doc + rules script
(checklist: `core/skills/memory/CAPABILITIES.md` **Adapter registration checklist**). Operators only set
`memory.provider` to a registered id in `.cursor/workflow.config.json` or the zero-config marker
`.cursor/sw-memory.provider` — they do not edit the catalog.

Example operator config:

```json
{
  "memory": {
    "provider": "in-repo",
    "project": "my-app",
    "inRepo": { "commitMode": "committed" }
  }
}
```

**Write binding hard-cut:** `/sw-memory-sync` and other mutating store paths refuse when the
repo has no explicit binding. Binding is either:

| Binding | Requirement |
| --- | --- |
| Config | `memory.provider` **and** non-empty `memory.project` |
| Marker | `.cursor/sw-memory.provider` containing literal `in-repo` (project = workspace basename) |

Remote/external markers (e.g. `recallium`) without `memory.project` refuse. There is **no** ambient
Recallium write default and **no** auto-migration into a machine-local MCP project. Unbound reads may
still resolve for display (`displayGuidance=in-repo`) without authorizing writes. Assert locally with
`python3 scripts/sw_bootstrap.py memory_preflight.py -- assert-sync-store`.

Reject examples (config write / hook resolve): `unknown-vendor`, `../traversal`, empty string, or a
catalog row missing adapter integrity or rules script.

**D7 — revocation is both sides.** Revoking a rule updates `.cursor/sw-memory-rule-allowlist.json`
**and** inactivates the provider record (soft-delete for `in-repo`; adapter inactivate otherwise).
Drop the id from `.cursor/sw-memory/rules-cache.json` so `rules-load` cannot serve a stale cached body.

For **in-repo**, choose commit mode:
- `committed` (default) — store lives in `.cursor/sw-memory/`; PR-reviewable
- `local` — gitignored at `.cursor/sw-memory-local/`

For **recallium**: setup warns if the health check fails but still allows save.

#### `memory.sourceOfTruth` migration

Decision-class records only. Provider selection (`memory.provider`) and authority selection
(`memory.sourceOfTruth`) are independent.

| Knob state | Memory-authoritative provider | Repo-authoritative provider (`in-repo`) |
| --- | --- | --- |
| **Key omitted** | Fail closed — export decision bodies, then set the knob explicitly | Resolves to `repo` (no migration) |
| **`"auto"` explicit** | Preserves today’s provider-derived behavior | Preserves today’s repo behavior |
| **`"repo"` or `"memory"` explicit** | Operator-bound authority | Operator-bound authority |

**Explicit `auto` is not the same as an omitted key.** Only an omitted key on a memory-authoritative
provider changes behavior at upgrade: `planning-doctor.py` classifies it as `migration-required` and
blocks until you materialize provider-side decision bodies and set the knob.

```bash
# 1) Export provider decision bodies into docs/decisions/
python3 scripts/memory-decision-snapshot.py export

# 2) Set the knob explicitly (example: keep auto semantics on Recallium)
# Edit .cursor/workflow.config.json:
#   "memory": { "sourceOfTruth": "auto", ... }
```

Shipwright’s own repo sets `"sourceOfTruth": "auto"` explicitly at migration so Recallium behavior is
unchanged. Refusal-ledger bounds (`planning.refusalLedger.path`, `ttlSeconds`, `maxSizeBytes`) are
documented in `core/sw-reference/config.schema.json` — storage is gitignored under
`.cursor/sw-refusal-ledger` by default.

For **mempalace**: `/sw-init` catalog-detects the provider but **does not auto-install** the package.
Validate `memory.mempalace.palacePath` and the supported package range when configured; see
**MemPalace memory provider** below.

#### MemPalace memory provider

MemPalace stores distilled drawers in a **local palace directory** on disk. Agent-session memory ops use
MemPalace MCP; guardrail hooks use the fixed-argv out-of-band script `providers/mempalace-rules.py` (never
MCP from hooks). Adapter contract: `core/providers/mempalace.md`.

**Install (operator — no auto-install):** Shipwright documents the supported range only; install the tool
yourself before live use:

```bash
uv tool install 'mempalace>=3.6.0,<4.0.0'
```

Pin is also recorded as `memory.mempalace.supportedPackage` (default matches the line above).

**Schema-valid example** (local palace + project wing):

```json
{
  "memory": {
    "provider": "mempalace",
    "project": "my-app",
    "sourceOfTruth": "auto",
    "mempalace": {
      "palacePath": "/home/you/.mempalace/my-app",
      "rulesRoom": "rules",
      "searchExcludeRooms": ["transcripts"],
      "ruleCacheTtlSec": 300,
      "failClosed": true,
      "redactOnWrite": true,
      "supportedPackage": "mempalace>=3.6.0,<4.0.0"
    }
  }
}
```

`memory.mempalace` rejects unknown keys (`additionalProperties: false`). `palacePath` must be a **local**
filesystem path — remote URLs are rejected in v1.

**Hook rule-fetch recipes**

| Posture | Recipe |
| --- | --- |
| **Local (default)** | Hooks invoke `providers/mempalace-rules.py` with a fixed argv template (`python -c <list_drawers snippet>`). Palace path and `rulesRoom` are passed only via config + `MEMPALACE_*` env vars set by the script — no free-form caller args. |
| **Docker bind-mount** | Mount the host palace read-only and the repo workspace; point `memory.mempalace.palacePath` at the in-container mount (e.g. `/palace`). Same fixed argv; optional `ruleFetchCommand` override must match the exact allowlisted template (no shell / eval). |

Example Docker sketch (adjust image paths to your plugin install):

```bash
docker run --rm \
  -v /host/palace:/palace:ro \
  -v /host/repo:/workspace:ro \
  -e SW_WORKSPACE_ROOT=/workspace \
  python:3.12 python /plugin/providers/mempalace-rules.py
```

Rule cache: atomic TTL cache under `.cursor/` state, bound to `provider` + `palacePath` with checksum
integrity — tamper → cache miss; see `core/providers/mempalace-rules.py`.

**Break-glass / palace-unreachable**

When `memory.mempalace.failClosed` is `true` (default), unreachable palace, missing package, or rule-fetch
failure **fails closed** for `guardrails.enforceBeforeSubmit` — prompts do not proceed without rules.
Break-glass (emergency only): set `failClosed: false` to degrade-open on hook rule-fetch failure. This
weakens submit enforcement; restore `true` after the palace is healthy. `/sw-init` doctor surfaces palace
path and package probe failures when `memory.provider` is `mempalace`.

**Transcripts + `rulesRoom`**

| Control | Behavior |
| --- | --- |
| `searchExcludeRooms` | Default `["transcripts"]` — verbatim / non-summarized material is excluded from default `search` and `memory-preflight`. |
| Opt-in transcripts | Removing `transcripts` from exclusions or explicit transcripts retrieval MUST emit an operator warning that excluded/verbatim material is requested. |
| `rulesRoom` (default `rules`) | Always excluded from ordinary search/preflight — hook `rules-load` only. Never inject `rulesRoom` drawers into agent preflight search. |
| Redaction on write | `redactOnWrite: true` (default) pipes every store through `scripts/memory-redact.py` before palace writes. Transcripts-room writes: redaction is **non-bypassable** in v1. |
| Ordinary writes to `rulesRoom` | Refused — rule-class drawers only via `/sw-memory-audit` / human-gated promotion. |

**Purge vs inactivate; capability degrades**

MemPalace has `softDelete: false` in the catalog — no native soft-delete.

| Verb | Behavior |
| --- | --- |
| **Inactivate (default)** | Non-destructive: superseding drawer + KG edge invalidate (or equivalent degrade). Prefer over hard delete. |
| **Hard purge** | Distinct confirmed destructive path → `mempalace_delete_drawer`; orphan-invalidate inbound KG edges; never cascade unrelated drawers. |

`tasks: false` — MemPalace has no native task board; `tasks.*` ops **degrade-open** to the local phase-board
registry without failing unrelated memory surfaces.

**Live-smoke checklist** (operator, not CI)

Run after install + config write when you want confidence before relying on MemPalace in production flows:

1. `uv tool install 'mempalace>=3.6.0,<4.0.0'` (or equivalent venv) and confirm `python -c "import mempalace"` succeeds.
2. Palace directory exists and is readable at `memory.mempalace.palacePath`.
3. `python3 providers/mempalace-rules.py` (from repo root with `SW_WORKSPACE_ROOT=.`) returns `"ok": true` and a `rules` array (may be empty).
4. Agent MCP: `mempalace_status` + `mempalace_get_taxonomy` for wing `memory.project`; `mempalace_search` returns without `rulesRoom` / `transcripts` unless opt-in.
5. Store path: redacted `store` to a canonical room (not `rulesRoom`); `expand` round-trips the drawer id.
6. Optional edge smoke: `mempalace_kg_add` + `mempalace_traverse` with a typed relationship; dangling target degrades without failing the whole read path.

Hermetic regression lives under `scripts/test/fixtures/mempalace/` (offline — no live daemon required for CI).

For **basic-memory**: `/sw-init` catalog-detects the provider but **does not auto-install** the package
or provision a cloud account/workspace. Set `memory.basicMemory.mode` explicitly (`local` | `cloud`);
there is no silent cross-mode fallback. See **Basic Memory provider** below.

#### Basic Memory provider

`memory.provider: "basic-memory"` selects the dual-mode Markdown knowledge-graph adapter. Agent sessions
use the basic-memory MCP; guardrail hooks use `providers/basic-memory-rules.py` (never MCP from hooks).
Adapter contract: `core/providers/basic-memory.md`.

**Install (operator — no auto-install / no cloud auto-provision):** Shipwright documents the supported
range only; install the tool yourself before local live use. Cloud mode still requires you to create the
Basic Memory Cloud account and API key outside Shipwright:

```bash
uv tool install 'basic-memory>=0.22.0,<1.0.0'
```

Pin is also recorded as `memory.basicMemory.supportedPackage` (default matches the line above).

**Mode selection (required — no silent fallback)**

| Mode | Transport | Credentials | Host policy |
| --- | --- | --- | --- |
| **`local`** (default) | Local MCP (stdio / loopback) + on-disk `projectPath` | None | Loopback only (`localhost` / `127.0.0.1` / `::1`) |
| **`cloud`** | Allowlisted Basic Memory Cloud MCP/API | `memory.credentialRef` → selector backend (or `tokenEnv` alias during deprecation) | Default `https://cloud.basicmemory.com`; fail closed on host allowlist mismatch |

Switching `local` ↔ `cloud` is an explicit `memory.basicMemory.mode` edit. Runtime MUST NOT auto-promote
local to cloud, degrade cloud to local, or rewrite mode when the configured endpoint fails.

**Schema-valid local example:**

```json
{
  "memory": {
    "provider": "basic-memory",
    "project": "my-app",
    "sourceOfTruth": "auto",
    "basicMemory": {
      "mode": "local",
      "projectPath": "/home/you/basic-memory/my-app",
      "memoriesDirectory": "memories",
      "rulesDirectory": "rules",
      "ruleCacheTtlSec": 300,
      "failClosed": true,
      "redactOnWrite": true,
      "supportedPackage": "basic-memory>=0.22.0,<1.0.0"
    }
  }
}
```

**Cloud mode example** (reference + selector — never embed tokens in config):

```json
{
  "memory": {
    "provider": "basic-memory",
    "project": "my-app",
    "credentialRef": "memory-work",
    "basicMemory": {
      "mode": "cloud",
      "apiBase": "https://cloud.basicmemory.com",
      "failClosed": true,
      "redactOnWrite": true,
      "supportedPackage": "basic-memory>=0.22.0,<1.0.0"
    }
  }
}
```

Point `memory-work` at an `environment` or `keystore` backend in the machine-local selector; scope
`allowedEndpoints` must include the configured `apiBase` host. During the one-release alias window,
`memory.basicMemory.tokenEnv` may still name the presence env var — `credentialRef` wins when both are set.

`memory.basicMemory` rejects unknown keys (`additionalProperties: false`). `mode` is required for
dual-mode correctness. Local `projectPath` must be a **local** filesystem path — remote URLs are rejected.

**SSRF / host policy**

| Mode | Allowed |
| --- | --- |
| `local` | Loopback hosts only. Reject private, metadata, and link-local targets unless an explicitly justified + tested exception exists. Local mode MUST NOT open cloud hosts. |
| `cloud` | Allowlisted `cloud.basicmemory.com` (or configured `apiBase` that stays on that allowlist). Bearer from selector backend only. |

**Hook rule-fetch**

Hooks invoke `providers/basic-memory-rules.py` (fixed argv; never MCP). Local mode reads the configured
`rulesDirectory` under `projectPath` on disk. Cloud mode uses the allowlisted API base + bearer. Optional
`ruleFetchCommand` overrides must match the exact allowlisted template (no shell / eval). Rule cache is
mode-partitioned (`provider` + `mode` + project).

**Break-glass / unreachable mode**

When `memory.basicMemory.failClosed` is `true` (default), unreachable configured mode, missing package
(local), missing cloud token, or rule-fetch failure **fails closed** for `guardrails.enforceBeforeSubmit`.
Break-glass (emergency only): set `failClosed: false` to degrade-open on hook rule-fetch failure, or change
`memory.provider` explicitly — never a silent switch to another provider or mode. Restore `failClosed: true`
after recovery. `/sw-init` doctor surfaces mode, path/token, and package probe failures when
`memory.provider` is `basic-memory`.

**Rules directory + redaction**

| Control | Behavior |
| --- | --- |
| `rulesDirectory` (default `rules`) | Hook `rules-load` only — always excluded from ordinary search / memory-preflight |
| `memoriesDirectory` (default `memories`) | Ordinary typed notes by category folder |
| Opt-in rules in search | Explicit rules-folder retrieval MUST warn that excluded material is requested |
| Redaction on write | `redactOnWrite: true` (default) pipes every store through `scripts/memory-redact.py` |
| Ordinary writes to rules dir | Refused — rule-class notes only via `/sw-memory-audit` / human-gated promotion |

**Capability degrades**

| Verb / flag | Behavior |
| --- | --- |
| `tasks: false` | `tasks.*` ops **degrade-open** to the local phase-board registry — do not fail unrelated memory surfaces |
| `filePathSearch: false` | Embed the path string in the semantic `search_notes` query (no ILIKE file filter) |
| `softDelete: false` | Prefer non-destructive edit / supersede; hard `delete_note` only on confirmed purge |
| `link` without create-edge | Degrade with operator-visible notice; preserve best-effort `links[]` on interchange synthesis |
| Unreachable mode (agent) | Report provider unreachable; do not mutate unrelated workflow surfaces or silently cross modes |

**Live-smoke checklist** (operator, not CI)

Run after install + config write when you want confidence before relying on Basic Memory in production flows:

1. Set `memory.basicMemory.mode` explicitly (`local` or `cloud`) — confirm there is no silent fallback path.
2. **Local:** `uv tool install 'basic-memory>=0.22.0,<1.0.0'` (or equivalent) and `python -c "import basic_memory"` (or package probe your install uses) succeeds; `projectPath` exists and is readable.
3. **Cloud:** `memory.credentialRef` resolves via the selector; `apiBase` stays on the allowlisted host.
4. `python3 providers/basic-memory-rules.py` (from repo root with `SW_WORKSPACE_ROOT=.`) returns `"ok": true` and a `rules` array (may be empty) for the configured mode.
5. Agent MCP: `list_memory_projects` (+ `cloud_info` in cloud); `search_notes` returns without the rules directory unless opt-in.
6. Store path: redacted `store` → `write_note` under `memoriesDirectory` (not `rulesDirectory`); `read_note` / `expand` round-trips the permalink.
7. Optional graph smoke: `build_context` traverse; dangling target degrades without failing the whole read path.

Hermetic regression lives under `scripts/test/fixtures/basic-memory/` (offline — no live cloud required for CI).

For **obsidian**: `/sw-init` catalog-detects the provider but **does not auto-install** Obsidian, the
Local REST API community plugin, or an API key. Point `memory.obsidian.vaultPath` at an existing vault
and enable the plugin yourself; see **Obsidian memory provider** below.

#### Obsidian memory provider

`memory.provider: "obsidian"` selects the Obsidian vault adapter. Agent sessions use the **Local REST API**
plugin's MCP/HTTP surface on loopback; guardrail hooks use `providers/obsidian-rules.py` (never MCP from
hooks). Adapter contract: `core/providers/obsidian.md`.

**Install (operator — no auto-install):** Shipwright documents enablement only; you install and configure
Obsidian yourself before live use:

1. Install [Obsidian](https://obsidian.md/) and open (or create) a vault at `memory.obsidian.vaultPath`.
2. Settings → Community plugins → enable **Local REST API** (supported plugin range is pinned in
   `scripts/test/fixtures/obsidian/compat-tool-schemas.json` at implement time).
3. Configure `memory.credentialRef` and add a selector entry (`environment` or `keystore` backend) — never
   commit API keys:

```json
{
  "memory": {
    "provider": "obsidian",
    "project": "my-app",
    "credentialRef": "memory-work",
    "obsidian": {
      "vaultPath": "/home/you/vaults/my-app",
      "mcpBaseUrl": "http://127.0.0.1:27123",
      "failClosed": true
    }
  }
}
```

During the one-release alias window, `memory.obsidian.tokenEnv` (default `OBSIDIAN_API_KEY`) may name the
presence env var for an `environment` backend entry — `credentialRef` wins when both are set.

Shipwright **never** auto-installs Obsidian, the plugin, or provisions the vault.

**HTTP vs HTTPS (loopback only)**

| Setting | Default | Notes |
| --- | --- | --- |
| `memory.obsidian.mcpBaseUrl` | `http://127.0.0.1:27123` | **HTTP** on loopback — Local REST API's default local binding |
| Host policy | Loopback only | `localhost` / `127.0.0.1` / `::1` — reject private, metadata, and link-local hosts |
| HTTPS | Operator-local only | If your plugin serves HTTPS on loopback, set `mcpBaseUrl` explicitly (e.g. `https://127.0.0.1:27124`) — still loopback-only; never point at remote cloud hosts |

Bearer auth resolves through `memory.credentialRef` and the selector backend — never embed tokens in config
bodies.

**Schema-valid example** (vault + project folder):

```json
{
  "memory": {
    "provider": "obsidian",
    "project": "my-app",
    "sourceOfTruth": "auto",
    "obsidian": {
      "vaultPath": "/home/you/vaults/my-app",
      "mcpBaseUrl": "http://127.0.0.1:27123",
      "memoriesDirectory": "memories",
      "rulesDirectory": "rules",
      "ruleCacheTtlSec": 300,
      "failClosed": true,
      "redactOnWrite": true
    }
  }
}
```

`memory.obsidian` rejects unknown keys (`additionalProperties: false`). `vaultPath` must be an **absolute**
local filesystem path — runtime resolves **realpath** and confines all note ids under the vault root;
traversal (`..`), symlink escapes, and paths outside the vault are rejected fail-closed.

**Hook rule-fetch**

Hooks invoke `providers/obsidian-rules.py` (fixed argv; never MCP). Primary path reads the configured
`rulesDirectory` under `vaultPath` on disk; loopback REST fallback uses the same host + credential policy
as agent ops. Optional `ruleFetchCommand` overrides must match the exact allowlisted template (no shell /
eval). Rule cache is partitioned (`provider` + `vaultPath` + project).

**Unreachable Obsidian / closed app (no silent fallback)**

When Obsidian is not running, the vault is missing, the Local REST API plugin is disabled, or the loopback
endpoint is unreachable:

| Surface | Contract |
| --- | --- |
| Agent session | Report provider unreachable — **do not** silently switch `memory.provider` or mutate unrelated workflow surfaces |
| Guardrail hooks | When `memory.obsidian.failClosed` is `true` (default), rule-fetch failure **fails closed** for `guardrails.enforceBeforeSubmit` |
| Break-glass (emergency only) | Set `failClosed: false` to degrade-open on hook rule-fetch failure, or change `memory.provider` explicitly — restore `true` after Obsidian is healthy |

`/sw-init` doctor surfaces vault path, `credentialRef` resolution (never prints secret values), and
loopback reachability when `memory.provider` is `obsidian`.

**Rules directory + redaction**

| Control | Behavior |
| --- | --- |
| `rulesDirectory` (default `rules`) | Hook `rules-load` only — always excluded from ordinary search / memory-preflight |
| `memoriesDirectory` (default `memories`) | Ordinary typed notes under `memories/<memory.project>/` by category folder |
| Opt-in rules in search | Explicit rules-folder retrieval MUST warn that excluded material is requested |
| Redaction on write | `redactOnWrite: true` (default) pipes every store through `scripts/memory-redact.py` |
| Ordinary writes to rules dir | Refused — rule-class notes only via `/sw-memory-audit` / human-gated promotion |

**Capability degrades**

| Verb / flag | Behavior |
| --- | --- |
| `tasks: false` | `tasks.*` ops **degrade-open** to the local phase-board registry — do not fail unrelated memory surfaces |
| `semanticSearch: false` | Keyword/path search only — do not claim embedding search |
| `filePathSearch: true` | Prefer vault-relative path filters when the caller supplies a path |
| `softDelete: false` | Prefer non-destructive edit / supersede; hard delete only on confirmed purge |
| Unreachable vault (agent) | Report provider unreachable; never silently cross providers |

**Live-smoke checklist** (operator, not CI)

Run after vault + plugin enablement + config write when you want confidence before relying on Obsidian in
production flows:

1. Obsidian is running with the configured vault open at `memory.obsidian.vaultPath`.
2. Local REST API community plugin is enabled; `memory.credentialRef` resolves (selector + pairing approved).
3. Loopback probe succeeds, e.g. `curl -fsS -H "Authorization: Bearer $OBSIDIAN_API_KEY" http://127.0.0.1:27123/` (adjust host/port to `mcpBaseUrl`).
4. `python3 providers/obsidian-rules.py` (from repo root with `SW_WORKSPACE_ROOT=.`) returns `"ok": true` and a `rules` array (may be empty).
5. Agent MCP: Local REST API list/search under `memories/<memory.project>/` — results exclude `rulesDirectory` unless opt-in.
6. Store path: redacted `store` under `memoriesDirectory` (not `rulesDirectory`); `expand` round-trips the vault-relative path id.
7. Optional link smoke: wikilink / frontmatter relation; dangling target degrades without failing the whole read path.

Hermetic regression lives under `scripts/test/fixtures/obsidian/` (offline — no live Obsidian required for CI).

### Step 2 — Review provider

| Choice | `review.provider` | Notes |
|--------|-------------------|-------|
| **none** (default) | `none` | Review gating off; CI can still pass without external review |
| coderabbit | `coderabbit` | AI review on PRs; install CodeRabbit CLI for local flows |

Canonical opt-out: `review.provider: "none"`. Do not use `review.enabled: false` (deprecated).

### Step 3 — Doc→implementation boundary

| Mode | `doc.afterTasks` | Behavior |
|------|-----------------|----------|
| **confirm** (default) | `confirm` | Show frozen task list, then a dedicated **Implementation checkpoint** (heading + direct question + paused-state line); require `proceed` or `yes`; seed frozen spec onto `<type>/<slug>`; dispatch `/sw-deliver run <frozen-tasks>`. Un-acked returns re-emit the checkpoint. |
| stop | `stop` | Halt after frozen tasks (print-only); print docs-only seed command onto `<type>/<slug>` and `/sw-deliver run <frozen-tasks>` |
| auto | `auto` | Seed frozen spec onto `<type>/<slug>` and dispatch `/sw-deliver run <frozen-tasks>` without a second prompt |


### Greenfield init posture

`/sw-init` and `python3 scripts/sw-configure.py write-draft` seed **seven** recommended keys for
hands-off deliver on greenfield repos. Schema defaults and write-draft stay aligned; doctor surfaces
drift on re-run and **never silently overwrites** explicit operator values without consent.

| Key | Greenfield default | Role |
|-----|-------------------|------|
| `orchestration.planPolicy` | `proposed` | Agent may propose phase step plans on `/sw-deliver` within kernel envelope |
| `delegation.mode` | `heuristic` | Documented inline heuristics for small steps; non-trivial Tasks stay bound |
| `planning.autonomy` | `full-conductor` | Bounded auto-absorb for gap/absorption-class planning decisions |
| `deliver.autonomy.mode` | `autonomous` | Minimal legitimate-halt set through terminal merge gate |
| `deliver.loop.drainMechanical` | `true` | Deliver-loop drains mechanical actions in-process |
| `inefficiency.enabled` | `true` | Process inefficiency scanner on deliver/retro surfaces |
| `execute.enabled` | `true` | Execute-tier sub-task fan-out inside `/sw-ship --phase-mode` |

Tighten to `bind-only`, `canonical`, or `maintenance-only` when you need stricter ceremony.

### Step 4 — Guardrails

| Setting | Default | Meaning |
|---------|---------|---------|
| `guardrails.enforceBeforeSubmit` | `true` | Memory guardrails run before prompts submit |
| `guardrails.requireRuleClass` | `false` | Set `true` in mature repos requiring allowlisted rules |

### Step 4b — Model tier defaults

Detect platform (`cursor` or `claude-code`) and seed the `models` block:

| Key | Purpose |
|-----|---------|
| `models.tiers` | Four semantic tiers → concrete dispatch IDs (`cheap`, `build`, `mid`, `deep`) |
| `models.aliases` | e.g. `fast` → `cheap` |
| `models.roles` | `builder` and `reviewer` floors (reviewer ≥ builder) |
| `models.routing` | Per `sw-*` command and skill tier; `inherit` for orchestrators |
| `models.routing.agents` | Per reviewer/persona/native-panel agent id → semantic tier (`build`/`mid`/`deep`) |

Scaffold writes the full block from `scripts/seed-model-config.py` and
`core/sw-reference/model-routing.defaults.json`. Doctor offers add/repair without overwriting user-edited tiers
unless confirmed. See `.sw/models-tiering.md` for platform catalogs, `models.routing.agents`, and resolver usage.

**Dispatch binding:** before spawning reviewer/persona Tasks, resolve
`python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --agent <id>` and run
`python3 scripts/reviewer-dispatch-check.py --agent <id> --parent-model <parent-concrete-id>`;
stamp the resolved concrete `model:` on the Task (do not rely on `model: inherit` from the parent session).

**Task model allowlist:** concrete Task spawn IDs are single-sourced from
`core/sw-reference/task-model-allowlist.json`. `resolve-model-tier.py` and `dispatch-check.py` emit or
accept only allowlisted IDs (or mapped aliases); unknown models fail closed with
`binding:model-not-allowlisted` before spawn. Maintenance cadence and validation commands:
`core/sw-reference/models-tiering.md` (Task model allowlist section). Regression:
`scripts/unit_tests/dispatch/test_task_model_allowlist.py`.

#### ModelPolicy and tier order

Semantic tier **order** is derived solely from `models.tiers` keys via shared `ModelPolicy`
(`scripts/model_policy_lib.py`) — not from agent frontmatter, private tuples, or routing maps. The canonical
four-tier vocabulary is `cheap` → `build` → `mid` → `deep`; escalation floors (`schema-failure`,
`verifier-disagreement` → at least `deep`) and graph cost telemetry read the same policy object.

**Missing `mid` — single preflight:** when `models.tiers` omits `mid`, `dispatch-check.py` emits one advisory
payload before spawn (`model-policy:missing-mid-defaulted` when `build` exists — `mid` defaults to the build
concrete id; `model-policy:missing-mid` when neither is present). There is no second silent default path.
Declare `models.tiers.mid` explicitly in mature repos; `/sw-init` doctor seeds all four tiers from the
platform catalog.

```bash
python3 scripts/dispatch-check.py --config .cursor/workflow.config.json --command sw-execute
# inspect modelPolicyAdvisory in JSON when mid is omitted
```

Full policy surface: `core/sw-reference/models-tiering.md` (ModelPolicy section).

### Graph execution defaults (`graphExecution.*`)

WorkflowGraph scheduler defaults for compiled orchestrator plans. **Cache and `maxConcurrency` are
independently tunable** — serial-equivalent `maxConcurrency: 1` does not imply cache on or off.

| Key | Default | Meaning |
| --- | --- | --- |
| `graphExecution.resourceLimits.maxConcurrency` | `1` | Serial-equivalent mitigation lane; raising concurrency is a cutover/scheduling-mode concern |
| `graphExecution.resourceLimits.maxDurationSeconds` | `86400` | Run-level wall clock for compiled graphs |
| `graphExecution.cache.enabled` | `true` | Content-addressed node cache; set `false` to disable reuse while keeping `maxConcurrency: 1` |
| `graphExecution.execution.backend` | `local-sync` | ExecutionBackend selection (`local-sync` default; `container` opt-in after conformance green) |
| `graphExecution.execution.container.image` | `shipwright/graph-node:latest` | OCI image for container backend node execution |
| `graphExecution.execution.container.credentialRef` | — | Broker ref for mutating container credential injection (`purpose: graph-container-exec`) |

Compiled `WorkflowGraph` IR carries `spec.resourceLimits.maxConcurrency` per plan; workflow defaults apply when
the compile target omits limits. Operator surfaces stay on existing commands (`/sw-deliver --explain-plan`,
`/sw-status` `graph-progress` / `explain`) — no `/sw-graph-*` slash commands. See
[`commands.md`](commands.md#graph-execution-runtime) and [`graph-domain-terminology.md`](graph-domain-terminology.md).

### Deliver autonomy (`deliver.autonomy`)

| Key | Default | Meaning |
|-----|---------|---------|
| `deliver.autonomy.mode` | `autonomous` | `autonomous` — minimal legitimate-halt set; `supervised` — adds per-phase acknowledgement halts |
| `deliver.autonomy.maxRunMinutes` | unset | Run-level wall-clock ceiling → consolidated halt |
| `deliver.autonomy.maxIterations` | `500` | In-turn `deliver-loop` hard stop |

### Deliver loop drain (`deliver.loop`) — /

| Key | Default | Meaning |
| --- | --- | --- |
| `deliver.loop.drainMechanical` | `true` | When true, `wave_deliver_loop` drains mechanical actions in-process until `awaitAgent`, `awaitInFlight`, or halt; `false` restores one step per invocation |

Log events (`run.log`) include `elapsedMs` on `driver-transition` and `execute-mechanical` for operator timing
— numeric only, no secret argv.

### Cleanup autonomy (`cleanup.autonomy`) — /

| Key | Default | Meaning |
| --- | --- | --- |
| `cleanup.autonomy` | `confirm` | `confirm` — agent-driven ack before apply; `auto` — post-merge autonomous apply when deliver verdict is terminal (`complete`/`rejected`) and merge status is not `indeterminate` |

Inflight protection is **scoped** to the active deliver run/worktree — unrelated in-flight runs do not block
terminal orchestrator cleanup. Non-terminal verdicts (`running`, `blocked`, `halted`, `watching`) remain protected.

### Planning unit status vocabulary — four-state reference map

Unified status surface (`scripts/planning_unit_status.py`):

| Canonical state | Meaning | Gates |
| --- | --- | --- |
| `backlog` | Not yet scheduled / open gap | Non-terminal |
| `planned` | Eligible but not in-flight | Non-terminal |
| `in-progress` | Active deliver or implementation | Non-terminal |
| `complete` | Terminal success | May green-light dependency gates |
| `unknown` / `unauthorized` | Backend miss or auth failure | **Non-terminal** — never treated as complete; auth errors fail-closed |

Backend-native strings map into the canonical four-state surface; cross-backend string identity is not required.

### Execute tier (`execute.*`)

Sub-task orchestration under `/sw-ship --phase-mode`. **Default-on** (`execute.enabled: true`); escape hatch
`execute.enabled: false` restores monolithic `/sw-execute`.

Frozen docs still hand off via `/sw-deliver run <frozen-tasks>` per `doc.afterTasks` (Step 3) — execute tier only subdivides phase work inside `/sw-ship --phase-mode`.

| Key | Default | Meaning |
| --- | --- | --- |
| `execute.enabled` | `true` | When true and phase has ≥2 executable sub-tasks, validate execute plan and fan out per ref before `sw-verify` |
| `execute.subBranchCeiling` | `null` | Max concurrent execute sub-branches; `null` resolves to `intraPhase.parallelBudget` |
| `execute.maxExpansionDepth` | `2` | Runtime recursive expansion depth cap for oversized refs |
| `execute.sizing.thresholds` | see schema | Scorer thresholds for runtime synthetic child refs |

**Sub-branch naming:** `feat/<slug>-phase-<phase-slug>--task-<ref>` — does not count toward `worktree.parallelCeiling`.

**Autonomy × execute halts:**

| `deliver.autonomy.mode` | Execute behavior |
| --- | --- |
| `autonomous` | Auto-propose/dispatch/remediate to budget; no plan-confirmation halt |
| `supervised` | One DAG confirm halt per phase (`execute:supervised-plan-confirm`); fail-fast on first sub-task failure |

**`planPolicy` interaction:** `orchestration.planPolicy: canonical` emits linear execute batches (width 1)
except contention-forced serial edges. `proposed` allows parallel batches within `intraPhase.parallelBudget`
and global cap. Recorded `planPolicy` on the execute plan is authoritative on resume.

** supersede (D-053-7):** sub-task parallelism is execute-tier under `/sw-ship`; wave-tier batching
unchanged.

Fixture suite: `python3 scripts/test/run_execute_orchestration_fixtures.py` (registered as
`execute-orchestration-fixtures` in the PR test-plan manifest).


### Project intelligence — evidence and promotion (`planning.intelligence.triageEvidence.*`, `planning.intelligence.capabilityPromotion.*`)

Advisory project intelligence for triage, doc entry, and dispatch compression shares one config namespace
under `planning.intelligence`. Schema authority: `core/sw-reference/config.schema.json`. No property in this
namespace overrides safety-kernel vetoes.

#### TriageEvidence weights and freshness

| Key | Default | Meaning |
| --- | --- | --- |
| `planning.intelligence.triageEvidence.weights.architecture-radar` | `0.6` | Weight for architecture-radar producer (0.0–1.0) |
| `planning.intelligence.triageEvidence.weights.workflow-history` | `0.4` | Weight for historical workflow outcomes |
| `planning.intelligence.triageEvidence.weights.exploration-findings` | `0.5` | Weight for exploration findings when producer is present |
| `planning.intelligence.triageEvidence.weights.decision-graph` | `0.5` | Weight for DecisionGraph uncertainty signal |
| `planning.intelligence.triageEvidence.weights.verification-capability` | `0.3` | Weight for verification capability signal |
| `planning.intelligence.triageEvidence.freshness.defaultTtlSeconds` | `86400` | Default freshness envelope TTL (60–604800 seconds) |

**Freshness semantics:** evidence envelopes bind `digest` to producer payload bytes — not clock-only
freshness. Expired envelopes, digest mismatches, and invalidated records exclude signals from weighted merge
(`excludedStale`). Missing producers emit `absent` with an explicit reason; absent signals are never coerced
to numeric zero.

#### CapabilityPromotion family thresholds

Registry families and config keys align one-to-one:

| Family key | Capability id | Consumer |
| --- | --- | --- |
| `triage-recommendation` | `triage.recommendation` | `/sw-triage`, doc rescore |
| `exploration-inference` | `exploration.inference` | TriageEvidence producer contract only (no execution UX) |
| `context-compression` | `context.compression` | `dispatch_prompt.py` measured rollout |

Each family accepts the same metric object (`capabilityPromotionFamilyThresholds`):

| Metric | Default | Meaning |
| --- | --- | --- |
| `minQualifyingRuns` | `3` | Qualifying runs required before `candidate → active` (1–100) |
| `maxFalsePositiveRate` | `0.05` | Upper bound on false-positive rate across the qualifying window |
| `maxVetoConflictRate` | `0.02` | Upper bound on safety-veto conflicts vs advisory recommendations |
| `minShadowAgreement` | `0.85` | Minimum shadow agreement before activation |

**Promotion states:** `shadow` (advisory recorded, not applied) → `candidate` (metrics accumulating) →
`active` (advisory may apply when veto-safe) → `rolled_back` (restores prior active revision + evidence ref).
Illegal transitions fail closed in `scripts/capability_promotion.py`. Stale or insufficient qualifying-run
evidence cannot advance a revision.

**Rollback:** regression (veto-conflict rate, false-positive rate, or shadow agreement breach) triggers
`rolled_back`, restoring the prior active revision and its `evidenceRef`. Dispatch and triage paths record
qualifying runs without adding commands.

#### Terminology parity

Use the same vocabulary across this guide, `docs/guides/workflows.md`, `core/commands/sw-status.md`, and
`.shipwright/layout.md`:

| Term | Meaning |
| --- | --- |
| `TriageEvidence@v1` | Versioned advisory evidence bundle with weighted signals and explain payload |
| `freshness envelope` | Digest-bound record: `digest`, `observedAt`, `producerPath`, `producerSignature`, optional `expiresAt`, invalidation |
| `absent` | Producer unavailable — explicit reason, never numeric zero |
| `excludedStale` | Signal rejected by freshness, expiry, or digest mismatch |
| `safety-floor` | Signal class that enforces minimum tier before advisory promotion |
| `non-authoritative` | Explain/status authority label — recommendations do not override deterministic gates |
| `CapabilityPromotion@v1` | Durable registry format at `.cursor/capability-promotion-registry.json` |
| `shadow` / `candidate` / `active` / `rolled_back` | Measured promotion states (only legal transitions permitted) |
| `qualifying run` | One observed dispatch/triage window with fresh `evidenceRef` and family metrics |
| `CompressionEvidence@v1` | Dispatch compression evidence class appended to `.cursor/compression-dispatch-evidence.jsonl` |

### Context compression (`contextCompression.*`)

Task-dispatch prompt construction for `/sw-doc-review`, `/sw-ship`, and gap-check closer dispatches routes
through `scripts/dispatch_prompt.py`. Compression is **available but default-off** — the shipped posture keeps
`contextCompression.enabled: false` until operator promotion evidence satisfies family thresholds.

| Key | Default | Meaning |
| --- | --- | --- |
| `contextCompression.enabled` | `false` | When `true`, large context blocks may be summarized before spawn |
| `contextCompression.phase` | `lossless` | Measured rollout phase: `lossless`, `shadow-lossy`, or `active-lossy` |
| `contextCompression.thresholdTokens` | `8000` | Token-estimate ceiling before compression/path-ref policy applies |
| `contextCompression.strategies.json` | `compress` | Strategy for JSON blocks: `compress`, `path-reference`, or `passthrough` |
| `contextCompression.strategies.diff` | `path-reference` | Unified-diff blocks prefer path references when file-backed |
| `contextCompression.strategies.log` | `compress` | Log excerpt strategy |
| `contextCompression.strategies.prose` | `compress` | Prose strategy |

**Measured rollout phases:**

| Phase | Behavior |
| --- | --- |
| `lossless` | Baseline — path references and lossless transforms only |
| `shadow-lossy` | Lossy output computed and recorded; dispatch context unchanged (non-authoritative) |
| `active-lossy` | Lossy output may replace dispatch context only when `context.compression` registry state is `active` and safety vetoes pass |

`active-lossy` without a valid promotion decision falls back to lossless/shadow behavior. Each dispatch records
`CompressionEvidence@v1` metrics (shadow agreement, veto conflicts, token delta, retrieve-key validity) to
`.cursor/compression-dispatch-evidence.jsonl` for N-run threshold evaluation under
`planning.intelligence.capabilityPromotion.families.context-compression`.

**Path-reference policy :** file-backed blocks that do not need summarization emit a path reference
instead of inlining content. **Recoverable path :** lossy compression stores orchestrator-only CCR keys;
`python3 scripts/dispatch_prompt.py recover --key <key>` retrieves full redacted content for re-dispatch.
`retrieveKey` never appears in subagent-visible prompt text .


**Legitimate halts:** terminal merge to `main`; remediation budget exhausted; merge conflict /
destructive git; `doc.afterTasks: confirm` or supervised mode; phase liveness timeout; CI/external wait
exhausted; run-level budget. Every halt emits one report with an exact resume command.

**Living-doc currency:** mechanical reconcile of the unified `docs/planning/INDEX.md` (post-cutover)
plus legacy projections `docs/prds/INDEX.md`, `COMPLETION-LOG.md`, and `GAP-BACKLOG.md` on the feature
branch; `docs-currency` gate hard-blocks terminal merge on drift. Resolve paths via `planningDir` with
legacy `prdsDir`/`tasksDir` aliases until migration cutover.

### Planning visibility (, three orthogonal axes per )

Per-unit bodies carry `visibility: public|private|memory`. When a unit omits `visibility`, a repo-level
**tier** supplies the default via `scripts/planning_visibility.py` (wrapped by `scripts/visibility-resolve.py`).

Visibility configuration is modeled as **three orthogonal axes** rather than one flat
profile — each is resolved and can be reasoned about independently:

| Axis | Key | Values | Meaning |
|------|-----|--------|---------|
| Visibility (redaction) tier | `planning.visibilityTier` | `all-private` \| `specs-public` (default) \| `all-public` | Closed-world default redaction tier (schema-validated). |
| Store location | `planning.store.storeLocation.mode` | `same-repo` \| `separate-project` | Whether the planning store lives in the code repo or a separate project (see Issue-store section below). |
| Store-host privacy | `planning.store.storeHostPrivacy` (or provider-probed) | `private` \| `public` \| `unknown` | Whether the configured issue-store host itself is private, evaluated per shipped provider via `probe_store_host_privacy`. `not-applicable` for non-issue-store backends (file-store parity, ). |
| — | `planning.privacyAck` | object | Durable acknowledgement gate — see below. |
| — | `planning.store.backend` | `in-repo-public` (default) \| `local-synced` \| `memory` \| `issue-store` | Pluggable planning-unit body backend ( /; `issue-store` opt-in per ). Pinned per deliver run at provision. |

**Tier-first rename + one-release alias map (/):** `planning.visibilityTier` is the current key.
`planning.visibilityProfile` is a **deprecated, one-release back-compat alias** — both are accepted, but
resolution is deterministic: the new key wins when both are set, *except* a mixed old/new config never
resolves to a **less private** tier than the deprecated value (the redaction default is never weakened). A
live config that still sets only the deprecated key resolves identically to pre-rename behavior and emits a
`planning-doctor.py` deprecation finding (`visibility-tier-key-deprecated`) naming the exact rename remediation.

**Public-repo-aware default (, extended by /):** `/sw-init` (and `planning_visibility.py
resolve-default-profile`) probes `origin` **and**, when the effective backend is an issue-store, the
configured store host's privacy — `probe_remote_visibility` is one input, not the sole migration gate. A
**public** origin remote *or* a **public** store host selects `all-private` and sets
`planning.privacyAck.required: true` until the operator acknowledges before the first tracked spec commit (or
first store write). A private/absent/inconclusive remote with a private-or-not-applicable store host selects
`specs-public`. Resolved axes + ack are written to `.cursor/workflow.config.json` and
`.cursor/hooks/state/planning-visibility.json` when seeding with `--write`.

Under `specs-public`, advisory classes (`brainstorm`, `decision`, `learnings`, `gap`) default to `private`;
spec classes (`prd`, `tasks`, `amendment`) default to `public`. Per-unit `visibility` always wins.

**Store-host privacy override is CI-only :** `SW_STORE_HOST_PRIVACY` (`private`\|`public`) is honored only
when an explicit CI-context probe passes (`CI` or `GITHUB_ACTIONS` env set) — never in an operator's
local/interactive run, so a stale override can never silently misclassify a shared/public store host as
private.

**Privacy acknowledgement (`privacyAck`, ):** `planning.privacyAck.recordedAt` — not `ackedAt` — is the key
`planning_visibility.py` actually writes; run `python3 scripts/planning_visibility.py --root . record-privacy-ack`
to set it. `planning-doctor.py` flags a live config with `privacyAck.required: true` and `recordedAt: null` as
an `action-required` finding naming that exact remediation command. See `core/sw-reference/planning-privacy-notice.md`.

**Fail-closed limits :** unknown or unresolved visibility tokens normalize to `private`. Regex/body
redaction at emission points is **not** semantic anonymization — use `all-private` plus `local/synced` store
for truly sensitive specs; keep codenames out of INDEX titles (opaque title) or in private/memory backends.
The memory backend routes bodies through the existing memory adapter and redaction chokepoint — it is never
labeled encrypted or anonymized.



### Issue-store ( — opt-in)

`issue-store` relocates planning artifacts to a provider issue system. **Default is unchanged** — unset config
is byte-identical to today .

| Key | Values | Meaning |
| --- | --- | --- |
| `planning.store.backend` | `issue-store` | Enable issue-backed planning store |
| `planning.store.issuesProvider` | `github-issues` \| `gitlab-issues` \| `jira` \| `linear` \| `notion` \| `none` | Issues adapter (**independent** of `host.provider`) |
| `planning.store.projectKey` | string | Project scoping key (`^[a-z][a-z0-9-]*$`) |
| `planning.store.storeLocation.mode` | `same-repo` \| `separate-project` | Code repo vs shared planning project |
| `planning.store.storeLocation.owner` / `.repo` | strings | Required for `separate-project` |
| `planning.store.issues.credentialRef` | string | Dedicated issue API credential reference (**not** `host.credentialRef`) |
| `planning.store.issues.tokenEnv` | string | One-release alias for issue API presence env (deprecated — use `credentialRef`) |

Example (opt-in):

```json
{
"planning": {
"store": {
"backend": "issue-store",
"issuesProvider": "github-issues",
"projectKey": "my-project",
"storeLocation": { "mode": "same-repo" },
"issues": { "credentialRef": "planning-work" }
}
}
}
```

Point `planning-work` at a selector entry scoped to the issue API endpoints and `projectId`. During the
one-release alias window, `issues.tokenEnv` may still name the presence env var — `credentialRef` wins when
both are set.

**Fallback matrix :** effective backend falls back to `in-repo-public` when `issuesProvider` is `none`/unsupported
or `host.provider` is `none`. A documented notice is emitted; work is never blocked.

**Network dependence (/):** issue-store mode requires API connectivity for planning operations once phase 2+
CRUD is active. Init probes token scope via `python3 scripts/planning_store.py probe-issues-token` (fail-closed on
missing/insufficient scope).

**Deliver-chain parity matrix:** when `storeLocation.mode` is `separate-project`, pollution/currency
guards skip tracked local derived planning artifacts in the code repo — gap capture, spec-seed, reconcile, and gap
resolution write through to the issue store instead. The full command×artifact×backend matrix and CI fixture are
published at `core/sw-reference/planning-deliver-parity-matrix.md` (verified by
`scripts/test/fixtures/planning-deliver-parity/full_matrix.py`).

### Jira Cloud issue-store

When `planning.store.issuesProvider` is `jira`, configure the Jira adapter keys under `planning.store.issues`:

| Key | Values | Meaning |
| --- | --- | --- |
| `planning.store.issues.endpoint` | URL | Jira base URL (`https://<org>.atlassian.net` for Cloud) |
| `planning.store.issues.flavor` | `cloud` (default) \| `dc` | Serialization + auth variant (ADF vs wiki) |
| `planning.store.issues.credentialRef` | string | Dedicated credential reference (preferred) |
| `planning.store.issues.tokenEnv` | string | One-release alias (default `ISSUES_JIRA_TOKEN`) |
| `planning.store.issues.freezeRecordField` | string | Custom field id for write-once freeze record (Cloud) |
| `planning.store.issues.issueType` | string | Mapped issue type for createmeta probe (default `Task`) |
| `planning.store.issues.fieldDefaults` | object | Allowlisted defaults for required custom fields |
| `planning.store.issues.labelSurface` | `labels` \| `components` \| `customField` | Label degradation ladder entry |
| `planning.store.issues.labelCustomField` | string | Optional custom field for label ladder step 3 |
| `planning.store.issues.emailEnv` | string | Cloud auth email env (default `ISSUES_JIRA_EMAIL`) |
| `planning.store.jiraProjectVisibility` | `public` \| `shared` \| `private` | Shared-project privacy probe input |

Example (Jira Cloud + separate planning project — typical for Bitbucket code repos per D25):

```json
{
"planning": {
"store": {
"backend": "issue-store",
"issuesProvider": "jira",
"projectKey": "my-project",
"storeLocation": { "mode": "separate-project" },
"issues": {
"endpoint": "https://my-org.atlassian.net",
"flavor": "cloud",
"credentialRef": "planning-work",
"freezeRecordField": "customfield_10042"
}
}
}
}
```

Init probes (fail-closed): `python3 scripts/planning_store.py probe-jira-init` — auth, privacy, createmeta, label-write.

See `core/providers/issues/jira.md` for LCD mapping, canonical hash, freeze-decoupling, budget, and lifecycle semantics.

### Linear issue-store

When `planning.store.issuesProvider` is `linear`, configure the Linear adapter keys under
`planning.store.issues` and optional operator browse projection under `planning.store.operatorProjection.linear`:

| Key | Values | Meaning |
| --- | --- | --- |
| `planning.store.issues.teamKey` | string | Human Team key/name (e.g. `ENG`) — preferred operator-facing id |
| `planning.store.issues.teamId` | string | Linear GraphQL Team id (alternative to `teamKey`) |
| `planning.store.issues.credentialRef` | string | Dedicated credential reference (preferred) |
| `planning.store.issues.tokenEnv` | string | One-release alias (default `ISSUES_LINEAR_TOKEN`; **not** `host.tokenEnv`) |
| `planning.store.issues.authMode` | `api-key` (default) \| `oauth` | `api-key` sends `Authorization: <API_KEY>`; `oauth` sends `Authorization: Bearer <ACCESS_TOKEN>` |
| `planning.store.issues.oauthSharedCiException` | boolean | Explicit exception allowing `authMode: oauth` via shared CI secret |
| `planning.store.operatorProjection.linear.enabled` | boolean (default `true`) | When `false`, Linear projection browse is skipped |
| `planning.store.operatorProjection.linear.initiativeSubstitute` | `substitute-views` \| `skip` | Degradation when Initiative workspace capability is absent |
| `planning.store.operatorProjection.linear.cycleSharingNotice` | boolean (default `true`) | Loud notice when Cycle wave shares cadence with human Milestones |
| `planning.store.operatorProjection.linear.budget` | object | GraphQL request/complexity budget (`maxCalls`, `maxComplexityPoints`, `maxPaginationDepth`, `cacheTtlSeconds`) |

At least one of `teamKey` or `teamId` is required. Init/probe fails closed on Team mismatch or missing scope.
Prefer a Team-restricted personal API key for dogfood; OAuth is a documented secondary mode — tokens stay
operator-local and must not be committed.

Example (Linear + same-repo planning):

```json
{
"planning": {
"store": {
"backend": "issue-store",
"issuesProvider": "linear",
"projectKey": "my-project",
"storeLocation": { "mode": "same-repo" },
"issues": {
"teamKey": "ENG",
"credentialRef": "planning-work",
"authMode": "api-key"
},
"operatorProjection": {
"linear": {
"enabled": true,
"initiativeSubstitute": "substitute-views",
"cycleSharingNotice": true
}
}
}
}
}
```

Init probes (fail-closed): `python3 scripts/planning_linear_client.py . probe-team` — Team scope and auth;
`python3 scripts/planning_linear_client.py . docs-currency-gate` — operator-guide inventory before terminal merge.

See `core/providers/issues/linear.md` for LCD verbs, stage-1 dogfood checklist, lock/overflow, and OAuth posture.

### Notion issue-store

When `planning.store.issuesProvider` is `notion`, configure the Notion adapter keys under
`planning.store.issues` and optional derived-view budget under `planning.store.requestBudget.notion`:

| Key | Values | Meaning |
| --- | --- | --- |
| `planning.store.issues.notionDatabaseId` | string | Primary Notion database id |
| `planning.store.issues.databaseMap` | object | Artifact-type → database id map |
| `planning.store.issues.workspaceId` | string | Optional workspace id (operator documentation) |
| `planning.store.issues.credentialRef` | string | Dedicated credential reference (preferred) |
| `planning.store.issues.tokenEnv` | string | One-release alias (default `ISSUES_NOTION_TOKEN`; **not** `host.tokenEnv`) |
| `planning.store.issues.notionTitleProperty` | string | Title property (default `Name`) |
| `planning.store.issues.notionStatusProperty` | string | Status property (default `Status`) |
| `planning.store.issues.notionProjectProperty` | string | Project multi-select property (default `Project`) |
| `planning.store.requestBudget.notion` | object | Derived-view budget (`maxCalls`, `maxPaginationDepth`, `cacheTtlSeconds`) |

At least one of `notionDatabaseId` or `databaseMap` is required. Init/probe fails closed on
missing database scope or schema mismatch.

Example (Notion + same-repo planning):

```json
{
"planning": {
"store": {
"backend": "issue-store",
"issuesProvider": "notion",
"projectKey": "my-project",
"storeLocation": { "mode": "same-repo" },
"issues": {
"notionDatabaseId": "00000000-0000-0000-0000-000000000001",
"credentialRef": "planning-work"
},
"requestBudget": {
"notion": {
"maxCalls": 300,
"maxPaginationDepth": 5,
"cacheTtlSeconds": 180
}
}
}
}
}
```

Init probes (fail-closed): `planning_notion_client.probe_token` and `probe_database` via doctor
and init surfaces; fixture mode `SW_NOTION_PROBE_FIXTURE=1` for hermetic CI.

Promotion: `notion` joins the derived `SHIPPED_ISSUES_PROVIDERS` set only after a green LCD
conformance record **and** the `docs-gate` over `core/providers/issues/notion.md` (see
`planning_notion_client.py docs-gate` / `promotion-gate-evidence`).

See `core/providers/issues/notion.md` for LCD verbs, rate-limit profile, and promotion gates.

See `core/providers/planning-store/issue-store.md` and `core/providers/issues/CAPABILITIES.md`.

### Release grouping ( /)

When `planning.store.backend` is `issue-store`, release grouping maps `sw:prd` planning units to provider
milestones or iterations where the `issue-milestone` verb is available. Absent capability → **skip with operator
notice**; deliver continues (normative degradation per ).

| Key | Values | Meaning |
| --- | --- | --- |
| `planning.releaseGrouping.mode` | `milestone` (default) \| `iteration` \| `label` | Native provider grouping; `label` is the flat-label fallback |
| `planning.releaseGrouping.labelPrefix` | string (default `sw:release:`) | Label prefix when falling back to flat labels |

Example (GitHub milestones):

```json
{
"planning": {
"store": { "backend": "issue-store", "issuesProvider": "github-issues", "projectKey": "my-project" },
"releaseGrouping": { "mode": "milestone" }
}
}
```

`/sw-deliver` applies grouping at phase provision when capability is present; otherwise emits a single
operator notice and proceeds. Scheduler integration is owned by — 045 is annotation/grouping only.

Fixture suite: `python3 scripts/test/run-planning-045-doc-impact-fixtures.sh` (`doc-currency-045-p3`).

Fixture suite: `python3 scripts/test/run_visibility_fixtures.py` (registered as `visibility-fixtures` in the PR test-plan manifest).

**Visibility-driven `.gitignore` :** regenerate tracking rules from the resolver via
`python3 scripts/gitignore-generate.py --write`. The generated block is delimited by
`# BEGIN visibility-generated` / `# END visibility-generated` markers in `.gitignore`.

Fixture suite: `python3 scripts/test/run_planning_visibility_acceptance_fixtures.py` (registered as
`planning-visibility-acceptance-fixtures` — emitter parity, public-unit no-regression, doc-impact acceptance).

### Issue-store request budget + query cache

When `planning.store.backend` is `issue-store`, derived INDEX refresh and `/sw-deliver next` share a
documented per-provider request budget. Budget keys live under `planning.store.requestBudget.<provider>`:

| Key | Default (github-issues) | Meaning |
|-----|----------------------|---------|
| `maxCalls` | **750** | Per-run API call ceiling composing with `SW_ISSUES_CALL_BUDGET` ; parallel runs use isolated ledgers |
| `maxPaginationDepth` | 10 | Pagination pages before fail-closed `index-incomplete` |
| `alertThreshold` | 0.8 | Operator-observable alert ratio before ceiling breach |
| `cacheTtlSeconds` | 300 | Poll-on-reconcile query cache TTL floor ; `critical=True` ops bypass cache within TTL |

Example:

```json
{
"planning": {
"store": {
"backend": "issue-store",
"issuesProvider": "github-issues",
"projectKey": "my-project",
"requestBudget": {
"github-issues": {
"maxCalls": 750,
"maxPaginationDepth": 10,
"alertThreshold": 0.8,
"cacheTtlSeconds": 300
}
}
}
}
}
```

Inspect live ledger (counts only — no bodies/tokens): `python3 scripts/planning_request_budget.py . status`.

Fixture suite: `python3 scripts/test/run_pytest.py scripts/unit_tests/planning/test_planning_046_phase2.py -q`.

### Cutover-gate committed derivation

Planning discovery (`scripts/planning_discover.py`, `scripts/planning_region_disposition.py`) needs to know
whether to read planning units from local files or from the configured issue-store backend. That signal
the **cutover gate** — is derived by `scripts/planning_cutover.py`'s `load_cutover_gate`, and its default is
computed entirely from **committed state**, not from a tracked file:

- **Effective backend** — `planning.store.backend` in `.cursor/workflow.config.json`, resolved via
`planning_store.resolve_effective_backend` (provider support + host reachability).
- **Structural marker** — whether the local file-store planning tree (`docs/planning/<type>/<unit-id>/`)
still holds tracked unit bodies on disk. If bodies are still present, the gate stays on `file` even when
the committed backend says `issue-store`, so a mid-flight migration never silently drops units.

When the effective backend is `issue-store` and no tracked file-store bodies remain, `discoverSource` and
`structural` both resolve to `issue`. Otherwise they resolve to `file`. No new tracked file is introduced
a fresh CI checkout (which never has any local override) always computes the correct default.

`.cursor/hooks/state/planning-cutover-gate.json` remains a **local, gitignored override** for manual/operator
testing (`python3 scripts/planning_cutover.py . set --discover-source issue`, for example) — `load_cutover_gate`
layers it on top of the committed default when present. It is **not** a CI authority: its absence must never
produce a wrong default, and `/sw-init` auto-configures it into `.gitignore` via `gitignore-generate --write`
(see `core/commands/sw-init.md`) so it never accidentally lands in the git index.

### Planning autonomy

Posture for planning graph bookkeeping vs content decisions. reads this key and soft-enforces
scheduler confirm when a lower-priority unit is selected under `maintenance-only`.

| Key | Values | Meaning |
|-----|--------|---------|
| `planning.autonomy` | `full-conductor` (greenfield default) \| `maintenance-only` | `full-conductor` elevates gap/absorption-class decisions under bounded limits; `maintenance-only` gates content decisions |
| `planning.fullConductor.confidenceThreshold` | number (default `0.85`) | Minimum edge confidence before auto-absorb under `full-conductor` |
| `planning.fullConductor.mutationBudget` | integer (default `10`) | Per-session autonomous mutation cap → legitimate halt `planning-mutation-budget` |
| `planning.fullConductor.undoWindowSeconds` | integer (default `3600`) | Reversible undo window before reconciler materializes absorption |

**`full-conductor` bounds (–):** elevates only **gap/absorption-class** decisions; never auto-absorbs
`private`/`memory` units; enqueues handoffs only (no nested `/sw-deliver`, `/sw-doc`, or orchestrator dispatch);
never weakens merge-to-`main`. See `core/skills/conductor/SKILL.md` **Bounded planning full-conductor**.

Fixture suite: `python3 scripts/test/run_planning_035_doc_impact_fixtures.py` (`doc-currency-035`, `no-regression-035`).


### Orchestration plan policy (`orchestration.planPolicy`)

| Value | Default | Meaning |
|-------|---------|---------|
| `proposed` | **yes (greenfield)** | Agent may propose phase step plans and wave batching within guideline latitude; validated by `wave.py plan validate` |
| `canonical` | no | Byte-identical to pre-022 behavior; hardcoded chains and plan-time waves only |

- **Kill-switch:** per-repo instant revert to canonical behavior; composes orthogonally with
`deliver.autonomy.mode` and `deliver.phaseAckCadence`.
- **Seeding:** `/sw-init` writes `orchestration.planPolicy: proposed` on greenfield; doctor surfaces current vs schema default and never overwrites explicit values without confirm.
- **Resume:** runs honor the **recorded** `planPolicy` on persisted plans over live config; re-validated against
the current kernel envelope on resume (fail-closed).
- **Default canonical:** nothing observable changes until you set `proposed` **and** pass the PRD-023
pilot guards (TR0 gate, per-run acknowledgement, safe target branch). `/sw-deliver` is the live pilot;
PRD-024 fans out to other orchestrators. Call-site map:
`scripts/test/fixtures/planning-post-migration/022-kernel-classification-and-plan-validation/call-site-map.md`.

** fan-out (all four orchestrators):** `/sw-deliver`, `/sw-debug`, `/sw-doc`, and `/sw-feedback`
read `orchestration.planPolicy` (default `canonical`). Enabling `proposed` on non-deliver orchestrators
remains TR0 + metric-gated.

| Program rule | Meaning |
| --- | --- |
| **** | Inconclusive (insufficient N) = non-positive → program exit (no deferred fan-out) |
| **** | Variance probe at authoring: `canonical ≡ proposed` → **consistency-only** (manifest + selector; proposed pack deferred); `/sw-doc` **defaults consistency-only** |
| **** | Debug/feedback = episodic scratch; deliver/doc handoff = durable run-state |

**Fixture suites:** `python3 scripts/test/run_fanout_fixtures.py` (program gate, per-orchestrator parity,
consistency-only, halts, //); `python3 scripts/test/run_dispatch_foundation_fixtures.py` (A2 parallel
preflight + command-tier binding, /).

Mechanical validation:

```bash
python3 scripts/wave.py plan validate --tier phase --phase-type ship --proposal <path|json>
python3 scripts/wave.py plan validate --tier wave --proposal <path|json> --plan .cursor/sw-deliver-plan.json
python3 scripts/wave.py plan validate --tier orchestrator --orchestrator-type debug --proposal <path|json>
```

### `/sw-cleanup` agent-driven confirm

`/sw-cleanup` defaults to dry-run. The agent presents the `wouldRemove` set and asks for explicit confirm
before running `python3 scripts/cleanup.py --confirm --yes` (or `SW_CLEANUP_CONFIRM=1`) on your behalf.
All fail-closed protections (unmerged branches, in-flight deliver, indeterminate squash, no `rm -rf`) are
unchanged — only the apply trigger moves from manual bash to agent-on-ack.

**PRD frontmatter:** Full-tier PRDs require resolvable `brainstorm:`; `/sw-freeze` verifies linkage.
Writable brainstorms may carry forward `prd:` references.

### Step 5 — Environment doctor (warnings only)

- CodeRabbit CLI on `PATH` when `review.provider` is `coderabbit`
- Recallium reachable when `memory.provider` is `recallium`
- MemPalace palace path + package probe when `memory.provider` is `mempalace` (see **MemPalace memory provider** above; no auto-install)
- Basic Memory mode + local package/`projectPath` or cloud token-env probe when `memory.provider` is
  `basic-memory` (see **Basic Memory provider** above; no auto-install / no cloud account create)
- Obsidian vault path + `OBSIDIAN_API_KEY` / loopback reachability when `memory.provider` is `obsidian`
  (see **Obsidian memory provider** above; no auto-install of Obsidian or the Local REST API plugin)
- Placeholder `verify.*` commands → recommends configuring real lint/typecheck/test commands
- Missing memory dirs → offers `mkdir -p` repair

### Step 6 — Write config

Validates against `core/sw-reference/config.schema.json`, then writes `.cursor/workflow.config.json`.

## Manual config

```bash
mkdir -p .cursor
cp core/sw-reference/workflow.config.example.json .cursor/workflow.config.json
# edit memory.project, verify.*, providers
```

## All config keys

| Key | Purpose |
|-----|---------|
| `projectId` | Stable repo slug (`^[a-z][a-z0-9-]*$`) — pairs credential references to this project |
| `host.credentialRef` | Non-secret selector reference for host transport (preferred over `host.tokenEnv`) |
| `host.tokenEnv` | One-release alias naming presence env for `environment` backend (deprecated) |
| `planning.store.issues.credentialRef` | Issue-store credential reference (independent of host) |
| `memory.credentialRef` | External memory provider credential reference |
| `agentsFile` | `AGENTS.md` | Standing agent guidance pointer file |
| `architecture.assessment.mode` | Opt-in doctrine assessment posture — `off` (default), `advisory`, or `blocking` |
| `architecture.assessment.path` | Per-repo assessment YAML (default `.cursor/architecture-assessment.yaml`) |
| `planningDir` | Canonical planning-unit tree (`docs/planning` post-cutover; legacy paths until migration `--verify`) |
| `prdsDir` | Legacy PRD directory alias (defaults to `docs/prds` until `planningDir` cutover) |
| `tasksDir` | Frozen task-list alias (defaults to `prdsDir` until cutover) |
| `decisionsDir` | Decision-record root |
| `doc.afterTasks` | After frozen tasks: `stop` \| `confirm` (default) \| `auto` |
| `communication.defaultIntensity` | Caveman chat intensity when no active command (`full` default) |
| `communication.routing.commands` | Per `sw-*` command intensity: `normal` \| `lite` \| `full` \| `ultra` \| `inherit` |
| `models.tiers` | Semantic tier → platform model ID (`cheap`, `build`, `mid`, `deep`) |
| `models.aliases` | Tier aliases (e.g. `fast` → `cheap`) |
| `models.roles` | `builder` and `reviewer` policy floors |
| `models.routing.commands` | Per `sw-*` command model tier (`inherit` for orchestrators) |
| `models.routing.skills` | Per skill directory model tier |
| `models.routing.agents` | Per reviewer/persona/native-panel agent id → semantic tier |
| `graphExecution.resourceLimits.maxConcurrency` | WorkflowGraph serial-equivalent default (`1`); independently tunable from cache |
| `graphExecution.resourceLimits.maxDurationSeconds` | Compiled graph wall-clock ceiling (default **86400**) |
| `graphExecution.cache.enabled` | Content-addressed node cache (default **true**); disable without changing `maxConcurrency` |
| `graphExecution.cache.scope` | Cache trust scope: `run` (default, intra-run memoization) or `repository` (cross-run reuse — only after MAC + gate-eligibility gates are green) |
| `graphExecution.cache.credentialRef` | Broker reference for per-repository cache MAC secret (`purpose: graph-cache-mac`) |
| `graphExecution.cache.maxSizeBytes` | Independent canonical cache ceiling (default **268435456** / 256 MiB) |
| `graphExecution.cache.maxAgeSeconds` | Independent cache retention window (default **2592000** / 30 days) |
| `deliver.remediation.maxAttempts` | Auto-remediation budget per blocked phase before clean halt (default **2**) |
| `memory.provider` | Catalog-registered provider id (default `in-repo`; seeded: `recallium`, `mempalace`, `basic-memory`, `obsidian`). Validated by `memory_provider_register.py` — unknown ids rejected |
| `memory.sourceOfTruth` | `auto` (default), `repo`, or `memory` — authority for **decision** records only (`auto`: external provider → memory, in-repo → repo) |
| `memory.autoSync` | Stop-hook thresholds for `/sw-memory-sync` scheduling |
| `review.provider` | AI review adapter — default **`none`**; `coderabbit` opt-in |
| `quality.provider` | Structural-quality harness — default **`none`** (no-op safe default; `quality:none`) |
| `quality.blockingTier` | Optional triage tier (`quick`/`standard`/`full`) at which a `poor` verdict blocks via gate (unset = advisory only) |
| `architecture.assessment.mode` | Doctrine assessment posture — default **`off`** (evaluator inert); `advisory` reports only; `blocking` fails check-gate on any `fail` |
| `architecture.assessment.path` | Per-repo assessment YAML validated against `architecture-assessment.schema.json` (default `.cursor/architecture-assessment.yaml`) |
| `verify.lint` | Command `/sw-verify` runs for linting |
| `verify.typecheck` | Command `/sw-verify` runs for type checking |
| `verify.test` | Command `/sw-verify` runs for tests (Shipwright dev repos chain fixture suites; user installs use real project tests) |
| `ci.prTestPlanManifest` | Shipwright-CI-only path to `pr-test-plan.manifest.json` (dev/plugin repos; not in shipped example) |
| `verifyE2e.enabled` | Opt-in smoke/E2E adapter — default **`false`** (web-specific) |
| `worktree.scaffold` | Opt-in local port/DB scaffold for web apps — omit for generic repos |
| `review.local.ui.enrich` | Opt-in external UI enrichment — default **`off`** |
| `coderabbit.reviewGraceMinutes` | Gate grace window before absent review = settled |
| `checks.treatNeutralAsPass` | NEUTRAL CI checks count as pass unless allowlisted |
| `checks.neutralAllowlist` | Check names that stay blocking even if neutral |
| `guardrails.enforceBeforeSubmit` | Memory guardrails run before prompts submit |
| `guardrails.requireRuleClass` | Require allowlisted rules before prompts proceed |
| `planning.autonomy` | `full-conductor` (greenfield default) \| `maintenance-only` — planning posture |
| `planning.fullConductor.*` | confidence/mutation/undo knobs under `full-conductor` opt-in |
| `orchestration.planPolicy` | `canonical` (default) \| `proposed` — agent plan proposals vs hardcoded chains; kill-switch |
| `intraPhase.parallelBudget` | Max concurrent intra-phase Task workers per phase (default **2**) |
| `intraPhase.harnessLimit` | Harness-wide cap combined with `worktree.parallelCeiling` (default **8**) |
| `notebook.sessionIndex` | Opt-in session-start injection of a distilled, redacted `/sw-note` index — default **`false`** |

See `core/sw-reference/config.schema.json` for the full schema.

## Architecture doctrine assessment (opt-in)

`architecture.assessment.mode` defaults to **`off`** — the evaluator is inert and existing repos change
behavior only when the key is set to `advisory` or `blocking`.

| Mode | Behavior |
| --- | --- |
| `off` | Skip evaluation (`verdict: skip`, exit 0) |
| `advisory` | Evaluate and print `{verdict,failed,waived,manual}`; never blocks check-gate |
| `blocking` | Same evaluation; any `fail` exits `20` and blocks check-gate |

Assessment YAML lives at `architecture.assessment.path` (default `.cursor/architecture-assessment.yaml`).
Each entry references a doctrine `AD-<n>` id with `verdict` ∈ `pass|fail|waived|manual`. A `waived` entry
**requires** `waiver.{actor,reason,expires}`; expired waivers are treated as `fail`. Waivers must be
authored by a human actor (`python3 scripts/architecture_assessment.py record-waiver …`) — autonomous
dispatch paths refuse waiver authorship (same posture as the sizing freeze override gate).

Bundled `core/sw-reference/architecture-doctrine.md` is **Shipwright-self reference only**. Consumer
project architecture law lives in repo-local ProjectDoctrine (below) — never copy bundled `AD-<n>`
statements into consumer authority.

## Consumer ProjectDoctrine

Consumer repos may adopt a repo-local **ProjectDoctrine** as project architecture law. Effective
workflow defaults stay aligned with config (for example `review.provider` defaults to **`none`**;
CodeRabbit is opt-in via `review.provider: "coderabbit"`). Doctrine adoption is separate from those
defaults and is always consent-gated through `/sw-init`.

### Authority and projection

| Artifact | Path | Role |
| --- | --- | --- |
| **ProjectDoctrine SoT** | `.sw/project-doctrine.json` | Sole consumer doctrine authority |
| **Baseline draft** | `.sw/project-baseline.draft.json` | Advisory draft only — never law until promote |
| **Optional projection** | `.cursor/sw-planning-projections/project-doctrine.json` | Mirror when issue-store planning is effective — **never** read as authority |
| **Decline record** | `.cursor/sw-init-project-doctrine.json` | Durable skip/decline breadcrumb |

Issue-store or planning-store copies are projection-only. Refreshing a projection never promotes law
and never overrides the repo-local SoT.

### Schemas

| Contract | Schema |
| --- | --- |
| `ProjectDoctrine@v1` | `core/sw-reference/project-doctrine.schema.json` |
| `ProjectBaseline@v1` | `core/sw-reference/project-baseline.schema.json` |

Minimum fields on both: `id`, `version`, `provenance`, `confidence` and/or `expiresAt`, and
`sourceRefs[]`. Consumer architecture vocabulary covers modules, interfaces, seams, adapters, and
locality. Product roadmap, org chart, and runtime runbook fields are excluded from doctrine
authority.

### Consent defaults (greenfield vs brownfield)

| Mode | What `/sw-init` may do | Promotes doctrine? |
| --- | --- | --- |
| **Greenfield** | Opt-in empty scaffold after `--confirm` | Only when you explicitly accept the scaffold |
| **Brownfield** | Synthesize a **draft** baseline (`project-baseline-synthesis@v1`) | **Never** auto-promote — draft until explicit promote |

Without `--confirm`, configurator actions return `confirm-required` and write nothing authoritative.

### Explicit promote and leakage

Baseline → doctrine promotion requires an explicit operator command (for example
`python3 scripts/sw-configure.py doctrine accept-promote --confirm`). Acceptance also requires a
**leakage-green** verdict: consumer doctrine must not carry Shipwright-self markers as project law
(`scripts/project_doctrine_leakage.py`). Reject and decline paths leave no durable doctrine (or clear
it) and remain non-authoritative.

Operator surface: `/sw-init` §5f and `python3 scripts/sw-configure.py doctrine …`. Route choices in
the [decision tree](decision-tree.md#projectdoctrine-and-architecture-routing). Layout pointers:
`.shipwright/layout.md`. Self vs consumer reference: `core/sw-reference/README.md`.

## Communication routing (caveman intensity)

Shipwright injects bundled `core/communication/caveman-core.md` on every session start. Intensity applies to
**orchestration chat only** — artifact files (brainstorm, PRD, tasks, commits, PR bodies) always use normal
complete prose.

| Intensity | Chat style |
|-----------|------------|
| `normal` | Standard prose; caveman off (e.g. doc-review, freeze, ready) |
| `lite` | Tight professional (e.g. brainstorm, prd, tasks) |
| `full` | Classic caveman — default workhorse |
| `ultra` | Max compression (e.g. triage, verify, commit) |

`/sw-init` seeds the full command map from `core/sw-reference/communication-routing.defaults.json`. Override
for the current chat with `/sw-caveman <normal|lite|full|ultra>` until the next command dispatch.

Wenyan variants are not supported in Shipwright — attach the external user skill manually if needed.

## Model tier routing

`/sw-init` seeds `models.tiers` from the detected platform catalog and the full command/skill map from
`core/sw-reference/model-routing.defaults.json`. Each `sw-*` command documents its tier in
`**Model tier:**` prose; resolve at runtime:

```bash
python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-prd
python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-doc --delegate sw-prd
```

Orchestrators (`sw-doc`, `sw-ship`, `sw-deliver`, `sw-retrospective`) route at `inherit` — always resolve the
delegated child command. Full policy: `.sw/models-tiering.md`.

## Graph execution cache policy

WorkflowGraph content-addressed caching is configured under `graphExecution.cache` and stored separately
from run journals at `.cursor/sw-graph-cache/` (see `.shipwright/layout.md`).

`GraphScheduler` owns the single owning loop; node work crosses `ExecutionBackend` with host-authoritative terminal envelopes (`scripts/graph/execution_backend.py`). Orchestrator conductor fan-out is orthogonal — not a substitute for graph concurrency.

| Key | Default | Meaning |
| --- | --- | --- |
| `graphExecution.cache.enabled` | `true` | When `false`, the scheduler does not consult the canonical cache store |
| `graphExecution.cache.scope` | `run` | `run` = intra-run memoization only (dogfood default). `repository` enables cross-run reuse only after MAC authenticity and gate-eligibility are mechanically green — never document run scope as “cross-run cache”. |
| `graphExecution.cache.credentialRef` | — | Broker selector ref resolving per-repo MAC material (`purpose: graph-cache-mac`) |
| `graphExecution.cache.maxSizeBytes` | `268435456` | Independent cache store ceiling (not shared with journal limits) |
| `graphExecution.cache.maxAgeSeconds` | `2592000` | Independent cache retention window |

**Receipt-visible hits:** cache hits stamp `cacheSource: cache`, `cacheKey`, and `originalRunId` on the
run-scoped receipt. `/sw-status` graph-progress surfaces reuse from these fields.

**Gate eligibility:** mechanical verify, review, ready-gate, and equivalent gate nodes are non-cacheable.
Nodes with missing or `"default"` identity components (`repo_state_identity`, `trust_domain`,
`scope_identity`, `repository_identity`) are cache-ineligible.

## Capability selection (manifest + selector)

Signal-driven eligibility for skills, personas, providers, rules, and hooks is declared in per-artifact
`capability` frontmatter, aggregated into `core/sw-reference/capability-index.json`, and resolved by
`scripts/capability-select.py` over a versioned `signal_context`. Contract:
`core/sw-reference/capability-manifest.md`.

| Concept | Meaning |
| --- | --- |
| **Eligibility** | Selector output — which capabilities match the snapshotted `signal_context` |
| **Authorization** | Named trust/config gate for executables only — `check-gate.py`, `memory-preflight`, hook slots |
| **Model tier** | Orthogonal — `models.routing` + `resolve-model-tier.py`; not chosen by the selector |

**No new `workflow.config.json` keys** — existing keys (`review.provider`, `review.local.provider`,
`memory.provider`, `verify.provider`, etc.) are read into `signal_context.config` at selection time via
manifest `config_flag` triggers. Provider configuredness (absent / `none` / unconfigured) matches
`check-gate.py` / `wave_preflight` verdicts.

**Freshness:** regenerate dist after manifest edits (`python3 -m sw generate --all`); stale index fails
`scripts/test/run_emitter_fixtures.py` and pre-selection preflight.

Fixture suites: `scripts/test/run_capability_select_fixtures.py`,
`scripts/test/run_capability_lint_fixtures.py`, `scripts/test/run_migration_parity_fixtures.py`.

## Retrospective compounding (`compound.autonomy`)

`/sw-retrospective` is the consolidated post-delivery chain (`retro → compound write → memory-sync → status`).
Deprecated aliases `/sw-compound-ship` and `/sw-compound` route to it for one release.

| Mode | `compound.autonomy` | Behavior |
|------|---------------------|----------|
| **supervised** (default) | `supervised` | Preserve retro/compound approval and merge-ack prompts |
| hands-off pre-merge | `auto` | Run the pre-merge chain when the terminal PR is green without re-prompting; merge detection still gates INDEX → `complete` |

Inspect at runtime: `python3 scripts/wave.py retrospective autonomy`. Autonomy never bypasses fail-closed
memory writes or rule-class human gates.

### Retrospective gap capture

Namespace **`retrospective.gapCapture`** controls supervised draft capture from retro `kind:painful` items.
This is separate from **`deliver.terminal.gapCapture`** (terminal metric-based gap mint at deliver
completion).

| Key | Default | Meaning |
| --- | --- | --- |
| `retrospective.gapCapture.enabled` | **`false`** | When true, retro painful items may emit redacted gap inbox drafts only — never auto-mint |
| `retrospective.gapCapture.maxCapturesPerRun` | **`3`** | Per retrospective run cap; overflow stops drafting and prints an operator message |

Example (opt-in):

```json
{
  "retrospective": {
    "gapCapture": {
      "enabled": true,
      "maxCapturesPerRun": 5
    }
  }
}
```

**Eligibility:** only structured retro items with `kind: painful` are drafted; `well` and `change` are
excluded. Hook or unattended callers may draft when enabled but materialization always requires persisted
per-item human acknowledgement bound to the redacted draft digest.

**Route-record layout:** durable audit/resume JSON per captured item lives under
`.cursor/hooks/state/retro-gap-routes/<signalId>.json` (relative to repo root). Each record tracks
`signalId`, `dedupKey`, lifecycle `action` (`draft` | `confirmed` | `materialized`), and digest fields.
See also `.shipwright/layout.md` (session hook state) and `scripts/planning_gap_capture.py`
(`RETRO_GAP_ROUTE_REL`).

Schema source: `core/sw-reference/config.schema.json` → `retrospective.gapCapture`.

## Zero-config fast path

A repo can work without `workflow.config.json` if you commit:

```text
.cursor/sw-memory.provider # file containing: in-repo
.cursor/sw-memory/memories/ # empty
.cursor/sw-memory/rules/ # empty
```

The fail-closed hook engages via the marker. Run `/sw-init` when you want full config.

## Base branch

Workflow entry resolves and **persists** your trunk base (branch name + SHA) before any feature worktree
is created. Precedence: explicit `--base` → user-set `defaultBaseBranch` → captured HEAD at entry.

- **Trunk base** — terminal PR target; secret-scan and frozen checks diff against this OID.
- **Integration base** — `<type>/<slug>` parent for phase-mode deliver; distinct from trunk base.

One-line disclosure at entry names the source, e.g. `base: dev (captured from HEAD)`.
Detached HEAD or Shipwright feature-branch HEAD is refused with recovery copy — re-enter from trunk or pass `--base`.

## Dev vs product boundary

The **shipped example** config (`core/sw-reference/workflow.config.example.json`) is neutral: no dev-harness
fixture paths, no `ci.*` keys. The **Shipwright source repo** carries a `.shipwright-dev` sentinel — it gates
CI generator tooling and template selection only; **never** weakens secret-scan, frozen guard, or push hooks.

User installs receive a closed `core/sw-reference/` emit set (schema, layout, example, routing defaults,
verify presets) via the plugin bundle — not the full dev `.sw/` tree.

## GitHub / CI ceiling

The merge-readiness gate (`/sw-watch-ci`, `/sw-stabilize`) observes **GitHub Actions** via the GitHub host
adapter (`scripts/host.py` over REST). Set `host.credentialRef` to a selector entry scoped to
`https://api.github.com` (or the enterprise API base in `allowedEndpoints`). During the one-release alias
window, `host.tokenEnv` (default `GITHUB_TOKEN`) names the presence env var for an `environment` backend —
`credentialRef` wins when both are set. No host CLI is required.

Repos without a resolved host credential or Actions can still use local `/sw-verify`, but cannot pass the
CI-readiness gate until GitHub CI is available — `/sw-init` host doctor warns about this honestly.

## Web-specific opt-in knobs

| Knob | Default | Enable when |
|------|---------|-------------|
| `worktree.scaffold` | omitted | Local web app needs port/DB isolation per worktree |
| `verifyE2e` | `enabled: false` | Smoke/E2E routes after static verify |
| `review.local.ui.enrich` | `off` | External design enrichment beyond native WCAG checklist |

Neutral shipped example omits scaffold; dogfood repos may set scaffold explicitly.

## Workflow extensions

Opt-in rollout flags under `workflow.extensions.*` (default **`false`** until cutover evidence).
Operator surfaces stay on existing `sw-*` commands and planning-store verbs — no parallel
`/sw-graph-*` family.

| Flag | Default | Surface |
|------|---------|---------|
| `workflow.extensions.externalIntake` | `false` | External intake lifecycle via `/sw-feedback` → planning-store `external-intake-*` verbs |
| `workflow.extensions.handoffBundle` | `false` | Portable **HandoffBundle**@v1 via `/sw-status --export-handoff` / `wave_status.py export-handoff` |
| `workflow.extensions.packageSdk` | `false` | **workflow-pack-sdk** conformance CLI (`scripts/workflow_pack_sdk.py`) + digest-bound adoption |

Example (all off until cutover):

```json
{
  "workflow": {
    "extensions": {
      "externalIntake": false,
      "handoffBundle": false,
      "packageSdk": false
    }
  }
}
```

Issue-store `separate-project` mode remains authoritative via `planning_store.put`; the code repo
receives projections only through **materialize at deliver entry** (`.cursor/planning-materialized/`).
Helper: `scripts/workflow_extensions.py` (`require_extension`, `extension_enabled`).

**Explore ↔ doc handoff (same helper module):** when explore maps and `/sw-doc` exchange routes,
`workflow_extensions.py` owns proposal/confirm/decline helpers (`propose_explore_forward_handoff`,
`propose_doc_backward_route`, `apply_*_confirm` / `apply_*_decline` / `apply_doc_backward_cancel`),
loop-guard recovery (`recover_from_loop_guard`), and contract validation
(`validate_doc_explore_handoff_contract`). Operator UX stays on `/sw-explore handoff` and `/sw-doc`
backward readiness — no nested orchestrator dispatch. See `docs/guides/workflows.md` (Explore
workstream) for the human-facing route table.

## External eval corpus, HandoffBundle, and provider stubs

Shipped in this release train: the **external consumer eval corpus**, **HandoffBundle** cross-harness
runtime, **planning-store semantic parity** harness, and **program priority authority**. P2/P3 platform
providers (GitLab planning store, remote execution, upstream provenance, WorkflowPackage marketplace) ship
as **specification + conformance stubs only** — default-off, not registered as shipped backends.

### Eval corpus configuration

| Surface | Path / command | Role |
| --- | --- | --- |
| Schema | `core/sw-reference/eval-corpus.schema.json` | Versioned manifest contract (repository mix, holdout, fixture revisions) |
| Fixture manifest | `scripts/test/fixtures/external-consumer-eval/corpus.json` | Deterministic public/synthetic fixtures — no production secrets |
| Runner | `scripts/eval_corpus.py` | Deterministic metrics: scenario pass rate, semantic parity, handoff continuity, false-positive rate, elapsed time |
| CI workflow | `.github/workflows/eval-corpus.yml` | Scheduled (Mondays 07:00 UTC) + `workflow_dispatch` + path-filtered PR runs |

**Composition rules:** at least three external repositories spanning greenfield, brownfield, and mixed
planning-store modes; holdout fixtures are isolated from release-gate metrics. Release readiness requires
corpus green **or** an attributable waiver (`SW_EVAL_CORPUS_WAIVER` env var pointing at a signed waiver
document). See [glossary](glossary.md) for **corpus** and **holdout** definitions.

### HandoffBundle configuration

| Surface | Config / command | Role |
| --- | --- | --- |
| Extension flag | `workflow.extensions.handoffBundle` | Default `false` until operator opt-in |
| Schema | `core/sw-reference/handoff-bundle.schema.json` | Portable bundle with transition provenance and digest validation |
| Runtime | `scripts/handoff_bundle.py` | Export/import across Cursor and Claude Code harnesses |
| Context-switch hook | `core/hooks/context_switch_handoff.py` | Validated export on pause; fail-closed on export failure |
| Status export | `/sw-status --export-handoff` / `wave_status.py export-handoff` | Operator surface when extension is enabled |

**Transition matrix:** session resume/switch, same-model and model-change cells, stale/tampered bundles,
missing durable state, and partial import failures are all covered by conformance tests. Recovery routing:
see [decision tree](decision-tree.md#adoption-and-provider-readiness).

### Program priority authority

| Surface | Path | Role |
| --- | --- | --- |
| Authority | `.sw/program-priorities.json` | Sole authoritative P0–P3 ranking and release sequence |
| Projection | `scripts/planning_priority_projection.py` | Read-only labels/index/graph metadata — **not** authority |

Projections MUST NOT be edited as planning truth. Priority tier and provider follow-on order (GitLab →
remote execution → upstream provenance → marketplace) are defined only in the authority file.

### Planning-store provider configuration

| Provider | Status | Spec / stub | Shipped? |
| --- | --- | --- | --- |
| Issue-store (GitHub) | **shipped** | `planning.store.backend: issue-store` | yes |
| GitLab planning store | **spec + stub** | `core/providers/planning-store/gitlab.md`, `scripts/planning/backends/gitlab.py` | **no** — not in shipped registry |
| Remote execution | **spec + stub** | `core/providers/execution/remote.md`, `scripts/graph/remote_execution_backend.py` | **no** — default-off |
| Upstream provenance | **spec + stub** | `core/providers/provenance/upstream.md`, `scripts/upstream_provenance.py` | **no** — not-enabled response only |
| WorkflowPackage marketplace | **spec + stub** | `core/providers/workflow-package/marketplace.md`, `scripts/graph/packages/marketplace.py` | **no** — disabled resolver |

**Capability matrix:** `core/providers/planning-store/CAPABILITIES.md` (matrix version `2.0.0`) is the
authoritative contract for semantic parity claims. Conformance evidence binds via
`scripts/planning/provider_conformance.py` to eval-corpus scenario identifiers. Parity claims without
corpus evidence fail closed.

### `/sw-status` visibility

`/sw-status` surfaces deliver-run progress, phase verdict, and gate evidence for the active worktree.
When `workflow.extensions.handoffBundle` is enabled, status also exposes HandoffBundle export guidance
(`--export-handoff`). Eval corpus gate results publish as CI artifacts under
`.cursor/sw-eval-corpus/` when the workflow runs; operators inspect `report.json` and `gate.json` for
release readiness. Program priority projections appear in planning graph/index views when
`planning_priority_projection.py` is invoked — always derived from `.sw/program-priorities.json`.

**Do not** configure P2/P3 stubs as shipped providers. Enabling them requires a follow-on delivery unit
with green corpus and conformance evidence.

## Optional integrations

| Integration | Config | When to enable |
|-------------|--------|----------------|
| **CodeRabbit** | `review.provider: "coderabbit"` | AI review on PRs |
| **Recallium** | `memory.provider: "recallium"` | Seeded external memory store (catalog-registered) instead of in-repo markdown |
| **MemPalace** | `memory.provider: "mempalace"` | Local palace + MCP; install `mempalace>=3.6.0,<4.0.0` yourself — see **MemPalace memory provider** |
| **Basic Memory** | `memory.provider: "basic-memory"` | Dual-mode local MCP or cloud; set `memory.basicMemory.mode` explicitly — see **Basic Memory provider** |
| **Obsidian** | `memory.provider: "obsidian"` | Vault + Local REST API on loopback; enable plugin + `OBSIDIAN_API_KEY` yourself — see **Obsidian memory provider** |
| **Sentry** | Production signals via `/sw-feedback` or `/sw-debug` | Route production errors into the debug workstream |

Provider **credentials** resolve through committed `credentialRef` values and the machine-local selector (or
`.sw/credential-ci-selector.json` in CI) — never commit secrets. See **Credential references and
machine-local selector** above.

## PR test-plan CI enforcement (FEAT PRs)

Shipwright dev repos single-source test-suite classification in
`core/sw-reference/suite-registry.json` (schema: `suite-registry.schema.json`). Downstream enforcement
surfaces are **projections** of registry lanes — not independent hand lists:

| Lane | Projection | Consumer |
| --- | --- | --- |
| `pr-ci` | `scripts/suite_registry.py` → `manifest_entries` | `core/sw-reference/pr-test-plan.manifest.json` |
| `pr-ci` | `scripts/generate-pr-test-plan-ci-workflow.py` | `.github/workflows/pr-test-plan-ci.yml` |
| `verify` | `scripts/suite_registry.py` → `verify_bundle_entries` | `scripts/test/run_verify_bundle.py` |
| `doc` | `scripts/suite_registry.py` → `doc_lane_entries` | `CONTRIBUTING.md` (drift-guarded) |

**Regenerate workflow after manifest or registry `pr-ci` changes:**

```bash
python3 scripts/generate-pr-test-plan-ci-workflow.py \
core/sw-reference/pr-test-plan.manifest.json \
.github/workflows/pr-test-plan-ci.yml \
.
```

Local `verify.test` runs the PR manifest set via `scripts/test/run_pr_test_plan_manifest.py`; CI runs the
same jobs via `.github/workflows/pr-test-plan-ci.yml`. Config key `ci.prTestPlanManifest` points at the
manifest path — it is not under `verify.*`.

Each manifest entry carries **`required`** (merge-blocking) or **`advisory`** (visible in the all-checks
readiness verdict but non-blocking). `scripts/check-gate.py` loads the manifest and exposes
`requiredFailingChecks` / `advisoryFailingChecks` in gate JSON; `/sw-stabilize` remediates through the
existing gate path. The PR template references CI **job names** as the authoritative gate — not a manual
script checklist.

Drift fixtures (run locally and in CI): `python3 scripts/test/run_suite_registry_fixtures.py` (registry
lanes, manifest, workflow, verify bundle, CONTRIBUTING `doc` lane) and
`python3 scripts/test/run_pr_test_plan_fixtures.py` (manifest/workflow generator parity).


## Workflow optimizer and capability registry

### Plan-policy promotion evidence

Promoting a workflow template from `orchestration.planPolicy: canonical` to `proposed`, then to
`canonical` as the live default, requires **integrity-scoped evidence** — successful history is
evidence, not automatic authority. The gate (`scripts/graph/workflow_library.py`
`gate_plan_policy_promotion`) enforces:

| Requirement | Detail |
| --- | --- |
| **Sample floor** | At least three runs with graph `runId` telemetry |
| **Input strata** | Both `dogfood-deliver` and `non-dogfood-deliver` strata represented |
| **Prediction error** | Bounded per sample (default max **0.25**) |
| **Required-capability** | Zero regressions across samples |
| **Ready without rework** | Each sample run reached ready without human rework |
| **Named authorizer** | Allowlisted promotion authorizer id |
| **Digest confirmation** | Digest-bound human confirmation on `/sw-deliver` matching the template digest |
| **Integrity digests** | Receipts and calibration tables verified as authorization inputs |

Promotion and demotion events are recorded on engine receipts
(`scripts/graph/execution_receipts.py`). Operator-facing shadow comparison and digest confirmation
prose lives in [`core/commands/sw-deliver.md`](../../core/commands/sw-deliver.md) (phase 12).

### Demotion and in-run kill switch

| Control | Effect |
| --- | --- |
| **Defined regressions** | Prediction error exceeded, required-capability regression, human rework, metrics over budget, or receipts/calibration digest mismatch → demote template to `canonical` and drop `proposed` |
| **In-run kill switch** | Operator kill switch (`scripts/graph/cutover.py` `InRunKillSwitch`) takes effect **within the active run**; `effective_plan_policy()` returns `canonical` while active |
| **Config kill-switch** | Per-repo instant revert via `orchestration.planPolicy: canonical` — composes orthogonally with `deliver.autonomy.mode` (see [Orchestration plan policy](#orchestration-plan-policy-orchestrationplanpolicy)) |

Demotion requires a named actor and a triggered regression record; integrity-scoped demotion verifies
observed receipts/calibration digests against the authorization envelope.

### Registry-sourced capability docs

Capability families (issues providers, model tiers, graph node kinds, artifact schemas, command catalog,
workflow template versions) are declared in **`core/sw-reference/capability-registry.json`** and
**`core/sw-reference/kernel-classification.json`**. Shipped vs deferred sets are derived from the
registry — not hand-edited in markdown.

| Artifact | Source |
| --- | --- |
| [`CAPABILITIES.md`](../../CAPABILITIES.md) | Root capability matrix (includes `linear` when shipped) |
| [`core/providers/issues/CAPABILITIES.md`](../../core/providers/issues/CAPABILITIES.md) | Issues-provider slice — cannot drift from registry |
| [`core/sw-reference/capability-family-matrices.{json,md}`](../../core/sw-reference/capability-family-matrices.json) | Model-tier, node-kind, schema, command, and template-version matrices |

A provider row may render **shipped** only when a referenced green conformance record exists.
CI regenerates in place and fails on a dirty tree — there is no update flag in CI.

```bash
# Regenerate locally after registry edits
python3 scripts/capability_docs.py generate

# CI / pre-commit parity check (default command)
python3 scripts/capability_docs.py check

# Fail when regenerate would dirty the tree
python3 scripts/capability_docs.py regen-check
```

Do not edit generated capability markdown by hand; change the registry and re-run `generate`.

## Deliver plan-policy pilot

`/sw-deliver` is the live pilot for `orchestration.planPolicy: proposed`. Default stays `canonical`.

| Guard | Meaning |
| --- | --- |
| TR0 dependency gate | `proposed` refused until PRD-022 exec-fidelity + resume fixtures pass |
| Pilot acknowledgement | Real repos require explicit per-run opt-in + integration/non-`main` target |
| Driver budgets | `runStartedAt`, `driverIterationCount`, `noProgressStreak` on shared run-state |
| Benefit metric | Numeric/enumerated `benefitMetric`; soak via `wave.py plan benefit-report` |

Fixture suite: `python3 scripts/test/run_pilot_fixtures.py` (pilot-e2e, intra-phase-*, budget-*, benefit-*).
After `core/` pilot prose changes: `python3 -m sw generate --all` + `run_emitter_fixtures.py`.

## fixture suites (kernel / gate / plan policy)

After editing `core/sw-reference/kernel-classification.*`, `guidelines.*`, or orchestration prose under
`core/`, regenerate dist trees before opening a PR:

```bash
python3 -m sw generate --all
python3 scripts/test/run_emitter_fixtures.py
```

| Suite | Scope |
| --- | --- |
| `run_kernel_classification_fixtures.py` | Kernel membership, ordering, completeness lint |
| `run_guidelines_floor_fixtures.py` | Guideline harness reuse + floor matrix |
| `run_plan_validate_fixtures.py` | `wave.py plan validate` gate |
| `run_plan_persist_fixtures.py` | Two-tier persist + single-writer guard |
| `run_plan_killswitch_fixtures.py` | `orchestration.planPolicy` kill-switch + resume |
| `run_plan_proposed_parity_fixtures.py` | Kernel chokepoint parity under `proposed` |

All registered in `verify.test` for Shipwright dev repos.

## Gate classes, bypass flags, and ship lease

Gate classes are declared in `core/sw-reference/gate-manifest.json` and resolved by
`scripts/gate_manifest.py`. Config MAY promote optional→mandatory or adjust advisory classification;
the **kernel floor** (verification-gate, check-gate, gap-check, secret-scan) is never demotable or
bypassable by config or flags.

| Bypass flag | Permitted scope | Record |
| --- | --- | --- |
| `--fast` | Optional/advisory gates only | Durable skip record with actor+reason |
| `--skip-local` | Optional/advisory gates only | Same |
| `--skip-simplify` | `sw-simplify` (agent-classified optional) | Same |

`merge-ready-green` (`scripts/ship-phase-status.py`) refuses when any **mandatory** gate lacks a
binding-valid evidence record at `.cursor/sw-deliver-runs/<phaseSlug>/gate-evidence/<gateId>.status.json`.

### Ship lease TTL

Per-phase inline dispatch acquires a durable ship lease before `dispatch-ship` runs. Stale leases
(reclaimable) use heartbeat freshness:

| Env var | Default | Meaning |
| --- | --- | --- |
| `SW_SHIP_LEASE_STALE_SECONDS` | `300` | Lease considered stale when `heartbeatAt` exceeds this many seconds |

Clear dead leases under `.cursor/sw-deliver-locks/` when PIDs are no longer live before resuming deliver.

### Phase-sizing override attribution

When `/sw-tasks` freeze scores a list as `large`, a blocking gate applies unless a durable human override
is recorded:

```bash
python3 scripts/phase_sizing.py override --task-list <path> --actor <who> --reason "<why>"
```

Overrides land in `.cursor/sw-sizing-overrides/` with required `actor` + `reason` attribution.
Autonomous `/sw-doc` → `/sw-tasks` dispatch paths refuse override without explicit operator ack.

## Task phase sizing (`tasks.sizing`)

adds a deterministic phase-sizing heuristic for `/sw-tasks` and advisory split suggestions.
Defaults are **calibrated from the frozen task-list corpus** (SC6) — not author-tuned.

Re-run calibration (read-only):

```bash
PYTHONPATH=scripts python3 scripts/phase_sizing_corpus.py --root . audit
```

Artifacts land under `scripts/test/fixtures/phase-sizing/` (`baseline-distribution.json`,
`corpus-manifest.json`, `sizing-defaults.json`). Fixture gate:
`python3 scripts/test/run_phase_sizing_corpus_fixtures.py`.

| Key | Calibrated default | Meaning |
|-----|-------------------|---------|
| `tasks.sizing.thresholds.filesTouched.small` | 6 | `small` when unique `**File:**` paths ≤ this (p50) |
| `tasks.sizing.thresholds.filesTouched.medium` | 10 | `medium` when ≤ this (p75); above → `large` |
| `tasks.sizing.thresholds.traceabilityScenarios.small` | 3 | Traceability rows mapped to the phase (p50) |
| `tasks.sizing.thresholds.traceabilityScenarios.medium` | 6 | p75 cut |
| `tasks.sizing.thresholds.subTaskCount.small` | 3 | Sub-task bullets under the phase heading (p50) |
| `tasks.sizing.thresholds.subTaskCount.medium` | 5 | p75 cut |
| `tasks.sizing.thresholds.distinctDirs.small` | 4 | Distinct parent directories among touched files (p50) |
| `tasks.sizing.thresholds.distinctDirs.medium` | 6 | p75 cut |
| `tasks.sizing.thresholds.depFanOut.small` | 1 | Outgoing dependency edges from the phase (p50) |
| `tasks.sizing.thresholds.depFanOut.medium` | 2 | p75 cut |
| `tasks.sizing.minPhaseFiles` | 2 | Minimum-viable-phase floor (files); splitting below is not rewarded |
| `tasks.sizing.minPhaseScenarios` | 1 | Minimum traceability scenarios floor |
| `tasks.sizing.maxPhaseCount` | 13 | Granularity DoS cap per task list |

Corpus snapshot (2026-06-30): 43 frozen task lists, 239 phase samples. Baseline also records realized
wave-width distribution (`waveWidth`) used to validate that split suggestions preserve throughput.

The scorer (`scripts/phase_sizing.py`, Phase 2+) reads these keys when present; unconfigured repos keep
backward-compatible defaults from the latest corpus audit.

## Reviewer effectiveness metrics semantics

Offline calibration constants — advisory only; no workflow config keys gate live review on these values.

| Constant | Module | Semantics |
| --- | --- | --- |
| `MIN_RANKING_N` (10) | `graph.reviewer_metrics.ranking` | Ranking reports `unknown` and suppresses ordering when cohort sample size is below 10; `recommend` stays `false` |
| Unlabeled → censored | `graph.reviewer_metrics.surviving` | Findings without exogenous labels are censored — excluded from Elo losses and negative calibration |
| `ELO_GATING_ENABLED` (`false`) | `graph.reviewer_metrics.elo` | Pairwise ratings never authorize/deny reviewers or alter panel composition |
| `RANKING_GATING_ENABLED` (`false`) | `graph.reviewer_metrics.ranking` | Rankings never bind reviewer selection |

Operator CLI: `python3 scripts/reviewer-metrics.py`. Storage authority: `.cursor/sw-learning-store/` via
`ReviewerMetricsStoreAdapter` — see `.shipwright/layout.md` and `docs/guides/workflows.md`.

### Bounded selection (`review.selection`)

Harvest-ranked truncation for doc-review personas and code-review specialists. When no harvest record
exists, selector output is byte-identical to the capability selector fallback.

| Key | Default | Meaning |
| --- | --- | --- |
| `review.selection.maxPersonas` | `32` | Upper bound on dispatched reviewers after harvest re-rank |
| `review.selection.minPersonas` | `1` | Floor — selection fails closed (`selection-floor`) rather than dispatching zero reviewers |
| `review.selection.costCeiling` | `null` | Optional USD dispatch ceiling enforced by `graph.reviewer_metrics.cost` before dispatch |

Stable tie-break: reviewer id ascending when harvest scores tie.

## Self-improving loop — inefficiency scanner

Process inefficiency detection. Greenfield default **enabled** (`inefficiency.enabled: true`); opt out by setting `false`.

| Key | Default | Meaning |
|-----|---------|---------|
| `inefficiency.enabled` | `true` (greenfield) | Run scanner on deliver/retro surfaces |
| `inefficiency.thresholds.slowTestSeconds` | `30` | Flag slow per-test durations (JUnit XML when present) |
| `inefficiency.thresholds.slowCiJobSeconds` | `300` | Flag slow CI jobs (`.cursor/sw-ci-timing.json` or gate `checkDurations`) |
| `inefficiency.allowlist.manualSteps` | `[]` | Manual commands excluded from repeated-step detection |

Detection classes: long single-threaded tests, slow CI jobs, serialized-but-parallelizable phases
(`waveBatchingPlan` vs `greedy_wave_batches`), repeated manual steps (`run.log`). Items route to
`.cursor/sw-meta-inbox/` as drafts (human-confirmed); skips with a notice when timing/sizing sources are absent.

Fixture suite: `python3 scripts/test/run_inefficiency_scan_fixtures.py`.

Behavioral-anomaly guardrails run in the `/sw-ship` chain after execute/verify — see
`core/skills/verification-gate/SKILL.md`. Fixture suite:
`python3 scripts/test/run_behavioral_anomaly_fixtures.py`.

## Self-improving loop — loop-health

Downstream-cost diagnostic metrics. Default **disabled** (`loopHealth.enabled: false`). Read-only — never gates CI or merge.

| Key | Default | Role |
| --- | --- | --- |
| `loopHealth.enabled` | `false` | Persist aggregated metrics to `${GIT_DIR}/shipwright-loop-health.json` |
| `loopHealth.staleInboxDays` | `14` | Flag meta-inbox drafts older than this in living-status |

CLI: `python3 scripts/loop_health.py` (`--summary`, `--stale-alerts`).

## Self-improving loop — auto-propose driver ( /)

Bounded draft-only driver (`scripts/loop_autonomy.py`). Default **disabled**.

| Key | Default | Role |
| --- | --- | --- |
| `loop.autoPropose.enabled` | `false` | Allow draft proposals + inert handoff queue entries |
| `loop.autoPropose.maxPerDay` | `5` | Runaway cap per UTC day |
| `loop.autoPropose.dedupWindow` | `3600` | Seconds before repeating the same `signalId` |
| `loop.autoPropose.cooldownMinutes` | `30` | Minimum spacing between proposals |
| `loop.autoPropose.maxOpenMetaUnits` | `10` | Halt when open meta-inbox drafts exceed cap |
| `loop.autoPropose.scheduler` | `manual` | `scheduled` runs are maintenance-only only |

Fixture suite: `python3 scripts/test/run_loop_autonomy_invariant_fixtures.py`.


### deliver.preflight.timeoutSeconds

Hard timeout (seconds) for deliver base-branch preflight probes. Default **90**.
On timeout the driver fails closed with `halt: preflight-timeout` and a resume command.

`--skip-base-check` does not re-probe: it reads `.cursor/sw-deliver-preflight-cache.json` written by the last successful probe when present ; otherwise skips without failing.

## Notebook session index

`/sw-note` always writes to your local `.cursor/sw-notebook/` regardless of this setting. `notebook.sessionIndex`
only controls whether a distilled summary of your **open** notebook items is injected at session start.

| Key | Default | Meaning |
|-----|---------|---------|
| `notebook.sessionIndex` | `false` | Opt-in session-start injection of a distilled, redacted index of open notebook items. |

The distilled index always passes through the same redaction chokepoint as every other persisted or
re-injected content. If redaction fails for any reason, injection is skipped entirely for that session —
the raw index is never injected as a fallback.

## Delegation mode

`delegation.mode` controls how aggressively Shipwright binds delegated Task work to concrete models and
intensity (via dispatch preflight). It sits alongside other `/sw-init` knobs in `.cursor/workflow.config.json`.

| Value | Behavior |
|-------|----------|
| `bind-only` | Strictest: every delegated Task must pass mechanical `dispatch preflight` + binding checks before spawn. |
| `heuristic` | Allows documented inline heuristics for small/mechanical steps while still binding non-trivial Task spawns. |
| `default` | Balanced default: bind delegated atomics; keep conductor-inline allowlists for durable driver steps. |

Relationship to inline work:

- Conductor-owned mechanical steps (deliver-loop state, merge bookkeeping, halt reports) stay inline per the
command allowlist—`delegation.mode` does not force those onto Tasks.
- Agent implementation/review work still goes through dispatch binding when a Task is spawned.
- Intensity directives remain prompt-literal; model tiers resolve through `models.tiers` / resolve-model-tier.

Greenfield `/sw-init` seeds `heuristic`. Tighten to `bind-only` when you need fail-closed binding for every spawn.

### Release-please effective-config auto-regen

On `release-please--branches--main` heads, the **Release dist regen** workflow
(`.github/workflows/release-dist-regen.yml`) runs `python3 scripts/effective_config_gen.py all --write`
alongside `python3 -m sw generate --all` and commits refreshed `dist/` plus projection outputs
(`docs/guides/configuration.md`, `core/sw-reference/generated/effective-config.json`,
`core/sw-reference/generated/upgrade-manifest-*.json`) in a single chore commit when anything drifts.

Local remediation when automation has not run (or you are off the release-please head) remains:

```bash
python3 scripts/effective_config_gen.py all --write
```

<!-- effective-config:begin generated (scripts/effective_config_gen.py) -->
## Effective configuration (generated)

Machine-readable defaults for workflow settings. Regenerate with:

```bash
python3 scripts/effective_config_gen.py generate --write
python3 scripts/effective_config_gen.py project-docs --write
```

Shipwright `2.9.0` · schema `config.schema.json`

| Setting | Schema default | Greenfield | Migration | Runtime fallback | Deprecated | Removed |
| --- | --- | --- | --- | --- | --- | --- |
| `agentsFile` | `AGENTS.md` | `AGENTS.md` | `AGENTS.md` | `AGENTS.md` | `—` | `—` |
| `architecture.assessment.mode` | `off` | `off` | `off` | `off` | `—` | `—` |
| `architecture.assessment.path` | `.cursor/architecture-assessment.yaml` | `.cursor/architecture-assessment.yaml` | `.cursor/architecture-assessment.yaml` | `.cursor/architecture-assessment.yaml` | `—` | `—` |
| `checks.treatNeutralAsPass` | `true` | `true` | `true` | `true` | `—` | `—` |
| `checks.watch.maxWaitMinutes` | `20` | `20` | `20` | `20` | `—` | `—` |
| `checks.watch.pollSeconds` | `45` | `45` | `45` | `45` | `—` | `—` |
| `cleanup.autonomy` | `confirm` | `confirm` | `confirm` | `confirm` | `—` | `—` |
| `coderabbit.noDefer` | `true` | `true` | `true` | `true` | `—` | `—` |
| `coderabbit.reviewGraceMinutes` | `15` | `15` | `15` | `15` | `—` | `—` |
| `communication.defaultIntensity` | `full` | `full` | `full` | `full` | `—` | `—` |
| `compound.autonomy` | `supervised` | `supervised` | `supervised` | `supervised` | `—` | `—` |
| `contextCompression.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `contextCompression.phase` | `lossless` | `lossless` | `lossless` | `lossless` | `—` | `—` |
| `contextCompression.strategies.diff` | `path-reference` | `path-reference` | `path-reference` | `path-reference` | `—` | `—` |
| `contextCompression.strategies.json` | `compress` | `compress` | `compress` | `compress` | `—` | `—` |
| `contextCompression.strategies.log` | `compress` | `compress` | `compress` | `compress` | `—` | `—` |
| `contextCompression.strategies.prose` | `compress` | `compress` | `compress` | `compress` | `—` | `—` |
| `contextCompression.thresholdTokens` | `8000` | `8000` | `8000` | `8000` | `—` | `—` |
| `decisionsDir` | `docs/decisions` | `docs/decisions` | `docs/decisions` | `docs/decisions` | `—` | `—` |
| `defaultBaseBranch` | `main` | `main` | `main` | `main` | `—` | `—` |
| `delegation.mode` | `heuristic` | `heuristic` | `heuristic` | `heuristic` | `—` | `—` |
| `deliver.autonomy.maxIterations` | `500` | `500` | `500` | `500` | `—` | `—` |
| `deliver.autonomy.maxRunMinutes` | `1440` | `1440` | `1440` | `1440` | `—` | `—` |
| `deliver.autonomy.mode` | `autonomous` | `autonomous` | `autonomous` | `autonomous` | `—` | `—` |
| `deliver.loop.drainMechanical` | `true` | `true` | `true` | `true` | `—` | `—` |
| `deliver.loop.maxStepsPerInvocation` | `12` | `12` | `12` | `12` | `—` | `—` |
| `deliver.phaseAckCadence` | `0` | `0` | `0` | `0` | `—` | `—` |
| `deliver.remediation.maxAttempts` | `2` | `2` | `2` | `2` | `—` | `—` |
| `deliver.targetLock.staleSeconds` | `300` | `300` | `300` | `300` | `—` | `—` |
| `deliver.terminal.autonomy` | `supervised` | `supervised` | `supervised` | `supervised` | `—` | `—` |
| `deliver.watchdog.phaseTimeoutMinutes` | `240` | `240` | `240` | `240` | `—` | `—` |
| `deliver.watchdog.stalenessClassifier.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `deliver.watchdog.stalenessClassifier.stuckThresholdMinutes` | `30` | `30` | `30` | `30` | `—` | `—` |
| `deliver.watchdog.stalenessClassifier.waitingOnHumanBoost` | `0.35` | `0.35` | `0.35` | `0.35` | `—` | `—` |
| `deliver.watchdog.stalenessClassifier.workingThresholdMinutes` | `5` | `5` | `5` | `5` | `—` | `—` |
| `dispatch.complexityProbe.bandCeiling` | `deep` | `deep` | `deep` | `deep` | `—` | `—` |
| `dispatch.complexityProbe.bandFloor` | `cheap` | `cheap` | `cheap` | `cheap` | `—` | `—` |
| `dispatch.complexityProbe.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `dispatch.tokenBudget.advisory` | `32000` | `32000` | `32000` | `32000` | `—` | `—` |
| `doc.afterTasks` | `confirm` | `confirm` | `confirm` | `confirm` | `—` | `—` |
| `doc.loop.drainMechanical` | `true` | `true` | `true` | `true` | `—` | `—` |
| `doc.loop.maxStepsPerInvocation` | `8` | `8` | `8` | `8` | `—` | `—` |
| `execute.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `execute.maxExpansionDepth` | `2` | `2` | `2` | `2` | `—` | `—` |
| `execute.sizing.thresholds.distinctDirs` | `2` | `2` | `2` | `2` | `—` | `—` |
| `execute.sizing.thresholds.filesTouched` | `3` | `3` | `3` | `3` | `—` | `—` |
| `execute.sizing.thresholds.traceabilityScenarios` | `2` | `2` | `2` | `2` | `—` | `—` |
| `gapCheck.ruleVerifierSweep.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `graphExecution.budget.haltOnExhaustion` | `true` | `true` | `true` | `true` | `—` | `—` |
| `graphExecution.budget.maxExecutionsPerNode` | `8` | `8` | `8` | `8` | `—` | `—` |
| `graphExecution.cache.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `graphExecution.cache.maxAgeSeconds` | `2592000` | `2592000` | `2592000` | `2592000` | `—` | `—` |
| `graphExecution.cache.maxSizeBytes` | `268435456` | `268435456` | `268435456` | `268435456` | `—` | `—` |
| `graphExecution.cache.scope` | `run` | `run` | `run` | `run` | `—` | `—` |
| `graphExecution.execution.backend` | `local-sync` | `local-sync` | `local-sync` | `local-sync` | `—` | `—` |
| `graphExecution.execution.container.image` | `shipwright/graph-node:latest` | `shipwright/graph-node:latest` | `shipwright/graph-node:latest` | `shipwright/graph-node:latest` | `—` | `—` |
| `graphExecution.execution.container.resourceLimits.cpuMillis` | `1000` | `1000` | `1000` | `1000` | `—` | `—` |
| `graphExecution.execution.container.resourceLimits.memoryMb` | `512` | `512` | `512` | `512` | `—` | `—` |
| `graphExecution.execution.container.resourceLimits.timeoutSeconds` | `3600` | `3600` | `3600` | `3600` | `—` | `—` |
| `graphExecution.profiles.optimization` | `balanced` | `balanced` | `balanced` | `balanced` | `—` | `—` |
| `graphExecution.resourceLimits.maxConcurrency` | `1` | `1` | `1` | `1` | `—` | `—` |
| `graphExecution.resourceLimits.maxDurationSeconds` | `86400` | `86400` | `86400` | `86400` | `—` | `—` |
| `host.rateLimit.baseBackoffMs` | `1000` | `1000` | `1000` | `1000` | `—` | `—` |
| `host.rateLimit.capBackoffMs` | `60000` | `60000` | `60000` | `60000` | `—` | `—` |
| `host.rateLimit.jitter` | `true` | `true` | `true` | `true` | `—` | `—` |
| `host.rateLimit.maxAttempts` | `5` | `5` | `5` | `5` | `—` | `—` |
| `host.rateLimit.maxCumulativeWaitMs` | `300000` | `300000` | `300000` | `300000` | `—` | `—` |
| `host.rateLimit.mutatingMinDelayMs` | `1000` | `1000` | `1000` | `1000` | `—` | `—` |
| `host.rateLimit.nearLimitThreshold` | `5` | `5` | `5` | `5` | `—` | `—` |
| `host.remote` | `origin` | `origin` | `origin` | `origin` | `—` | `—` |
| `host.tokenEnv` | `—` | `—` | `—` | `—` | `legacy` | `—` |
| `inefficiency.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `inefficiency.thresholds.slowCiJobSeconds` | `300` | `300` | `300` | `300` | `—` | `—` |
| `inefficiency.thresholds.slowTestSeconds` | `30` | `30` | `30` | `30` | `—` | `—` |
| `intraPhase.harnessLimit` | `8` | `8` | `8` | `8` | `—` | `—` |
| `intraPhase.parallelBudget` | `2` | `2` | `2` | `2` | `—` | `—` |
| `invariantsOptional` | `false` | `false` | `false` | `false` | `—` | `—` |
| `loop.autoPropose.cooldownMinutes` | `30` | `30` | `30` | `30` | `—` | `—` |
| `loop.autoPropose.dedupWindow` | `3600` | `3600` | `3600` | `3600` | `—` | `—` |
| `loop.autoPropose.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `loop.autoPropose.maxOpenMetaUnits` | `10` | `10` | `10` | `10` | `—` | `—` |
| `loop.autoPropose.maxPerDay` | `5` | `5` | `5` | `5` | `—` | `—` |
| `loop.autoPropose.scheduler` | `manual` | `manual` | `manual` | `manual` | `—` | `—` |
| `loopHealth.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `loopHealth.staleInboxDays` | `14` | `14` | `14` | `14` | `—` | `—` |
| `memory.autoSync.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.autoSync.minMinutes` | `120` | `120` | `120` | `120` | `—` | `—` |
| `memory.autoSync.minTurns` | `10` | `10` | `10` | `10` | `—` | `—` |
| `memory.basicMemory.apiBase` | `https://cloud.basicmemory.com` | `https://cloud.basicmemory.com` | `https://cloud.basicmemory.com` | `https://cloud.basicmemory.com` | `—` | `—` |
| `memory.basicMemory.failClosed` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.basicMemory.memoriesDirectory` | `memories` | `memories` | `memories` | `memories` | `—` | `—` |
| `memory.basicMemory.mode` | `local` | `local` | `local` | `local` | `—` | `—` |
| `memory.basicMemory.redactOnWrite` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.basicMemory.ruleCacheTtlSec` | `300` | `300` | `300` | `300` | `—` | `—` |
| `memory.basicMemory.rulesDirectory` | `rules` | `rules` | `rules` | `rules` | `—` | `—` |
| `memory.basicMemory.supportedPackage` | `basic-memory>=0.22.0,<1.0.0` | `basic-memory>=0.22.0,<1.0.0` | `basic-memory>=0.22.0,<1.0.0` | `basic-memory>=0.22.0,<1.0.0` | `—` | `—` |
| `memory.basicMemory.tokenEnv` | `BASIC_MEMORY_API_KEY` | `BASIC_MEMORY_API_KEY` | `BASIC_MEMORY_API_KEY` | `BASIC_MEMORY_API_KEY` | `—` | `—` |
| `memory.connection.restBaseUrl` | `http://localhost:8001` | `http://localhost:8001` | `http://localhost:8001` | `http://localhost:8001` | `—` | `—` |
| `memory.guardrails.allowEmptyRules` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.guardrails.enforceBeforeSubmit` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.guardrails.requireRuleClass` | `false` | `false` | `false` | `false` | `—` | `—` |
| `memory.inRepo.commitMode` | `committed` | `committed` | `committed` | `committed` | `—` | `—` |
| `memory.inRepo.storeDir` | `.cursor/sw-memory` | `.cursor/sw-memory` | `.cursor/sw-memory` | `.cursor/sw-memory` | `—` | `—` |
| `memory.mempalace.failClosed` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.mempalace.redactOnWrite` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.mempalace.ruleCacheTtlSec` | `300` | `300` | `300` | `300` | `—` | `—` |
| `memory.mempalace.rulesRoom` | `rules` | `rules` | `rules` | `rules` | `—` | `—` |
| `memory.mempalace.searchExcludeRooms` | `["transcripts"]` | `["transcripts"]` | `["transcripts"]` | `["transcripts"]` | `—` | `—` |
| `memory.mempalace.supportedPackage` | `mempalace>=3.6.0,<4.0.0` | `mempalace>=3.6.0,<4.0.0` | `mempalace>=3.6.0,<4.0.0` | `mempalace>=3.6.0,<4.0.0` | `—` | `—` |
| `memory.obsidian.failClosed` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.obsidian.mcpBaseUrl` | `http://127.0.0.1:27123` | `http://127.0.0.1:27123` | `http://127.0.0.1:27123` | `http://127.0.0.1:27123` | `—` | `—` |
| `memory.obsidian.memoriesDirectory` | `memories` | `memories` | `memories` | `memories` | `—` | `—` |
| `memory.obsidian.redactOnWrite` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.obsidian.ruleCacheTtlSec` | `300` | `300` | `300` | `300` | `—` | `—` |
| `memory.obsidian.rulesDirectory` | `rules` | `rules` | `rules` | `rules` | `—` | `—` |
| `memory.obsidian.tokenEnv` | `OBSIDIAN_API_KEY` | `OBSIDIAN_API_KEY` | `OBSIDIAN_API_KEY` | `OBSIDIAN_API_KEY` | `—` | `—` |
| `memory.playbooks.activeMinConfidence` | `0.6` | `0.6` | `0.6` | `0.6` | `—` | `—` |
| `memory.playbooks.confidenceStep` | `0.05` | `0.05` | `0.05` | `0.05` | `—` | `—` |
| `memory.playbooks.demoteMaxSuccessRate` | `0.4` | `0.4` | `0.4` | `0.4` | `—` | `—` |
| `memory.playbooks.demoteMinUsage` | `5` | `5` | `5` | `5` | `—` | `—` |
| `memory.playbooks.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `memory.playbooks.injectMinConfidence` | `0.75` | `0.75` | `0.75` | `0.75` | `—` | `—` |
| `memory.playbooks.promoteMinSuccessRate` | `0.8` | `0.8` | `0.8` | `0.8` | `—` | `—` |
| `memory.playbooks.promoteMinUsage` | `5` | `5` | `5` | `5` | `—` | `—` |
| `memory.provider` | `in-repo` | `in-repo` | `in-repo` | `in-repo` | `—` | `—` |
| `memory.sourceOfTruth` | `auto` | `auto` | `auto` | `auto` | `—` | `—` |
| `memory.tokenEnv` | `—` | `—` | `—` | `—` | `legacy` | `—` |
| `notebook.sessionIndex` | `false` | `false` | `false` | `false` | `—` | `—` |
| `orchestration.planPolicy` | `proposed` | `proposed` | `proposed` | `proposed` | `—` | `—` |
| `planning.autonomy` | `full-conductor` | `full-conductor` | `full-conductor` | `full-conductor` | `—` | `—` |
| `planning.fullConductor.confidenceThreshold` | `0.85` | `0.85` | `0.85` | `0.85` | `—` | `—` |
| `planning.fullConductor.mutationBudget` | `5` | `5` | `5` | `5` | `—` | `—` |
| `planning.fullConductor.undoWindowSeconds` | `300` | `300` | `300` | `300` | `—` | `—` |
| `planning.inFlight.stalenessTtlHours` | `72` | `72` | `72` | `72` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.context-compression.maxFalsePositiveRate` | `0.05` | `0.05` | `0.05` | `0.05` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.context-compression.maxVetoConflictRate` | `0.02` | `0.02` | `0.02` | `0.02` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.context-compression.minQualifyingRuns` | `3` | `3` | `3` | `3` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.context-compression.minShadowAgreement` | `0.85` | `0.85` | `0.85` | `0.85` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.exploration-inference.maxFalsePositiveRate` | `0.05` | `0.05` | `0.05` | `0.05` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.exploration-inference.maxVetoConflictRate` | `0.02` | `0.02` | `0.02` | `0.02` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.exploration-inference.minQualifyingRuns` | `3` | `3` | `3` | `3` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.exploration-inference.minShadowAgreement` | `0.85` | `0.85` | `0.85` | `0.85` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.triage-recommendation.maxFalsePositiveRate` | `0.05` | `0.05` | `0.05` | `0.05` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.triage-recommendation.maxVetoConflictRate` | `0.02` | `0.02` | `0.02` | `0.02` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.triage-recommendation.minQualifyingRuns` | `3` | `3` | `3` | `3` | `—` | `—` |
| `planning.intelligence.capabilityPromotion.families.triage-recommendation.minShadowAgreement` | `0.85` | `0.85` | `0.85` | `0.85` | `—` | `—` |
| `planning.intelligence.radar.postMerge` | `false` | `false` | `false` | `false` | `—` | `—` |
| `planning.intelligence.radar.windows.activityBiasLastPrs` | `30` | `30` | `30` | `30` | `—` | `—` |
| `planning.intelligence.radar.windows.activityBiasMinPrCount` | `3` | `3` | `3` | `3` | `—` | `—` |
| `planning.intelligence.radar.windows.gitChurnDays` | `30` | `30` | `30` | `30` | `—` | `—` |
| `planning.intelligence.triageEvidence.freshness.defaultTtlSeconds` | `86400` | `86400` | `86400` | `86400` | `—` | `—` |
| `planning.intelligence.triageEvidence.weights.architecture-radar` | `0.6` | `0.6` | `0.6` | `0.6` | `—` | `—` |
| `planning.intelligence.triageEvidence.weights.decision-graph` | `0.5` | `0.5` | `0.5` | `0.5` | `—` | `—` |
| `planning.intelligence.triageEvidence.weights.exploration-findings` | `0.5` | `0.5` | `0.5` | `0.5` | `—` | `—` |
| `planning.intelligence.triageEvidence.weights.verification-capability` | `0.3` | `0.3` | `0.3` | `0.3` | `—` | `—` |
| `planning.intelligence.triageEvidence.weights.workflow-history` | `0.4` | `0.4` | `0.4` | `0.4` | `—` | `—` |
| `planning.intelligence.vocabulary.strictMode` | `false` | `false` | `false` | `false` | `—` | `—` |
| `planning.privacyAck.required` | `false` | `false` | `false` | `false` | `—` | `—` |
| `planning.refusalLedger.maxSizeBytes` | `52428800` | `52428800` | `52428800` | `52428800` | `—` | `—` |
| `planning.refusalLedger.path` | `.cursor/sw-refusal-ledger` | `.cursor/sw-refusal-ledger` | `.cursor/sw-refusal-ledger` | `.cursor/sw-refusal-ledger` | `—` | `—` |
| `planning.refusalLedger.ttlSeconds` | `2592000` | `2592000` | `2592000` | `2592000` | `—` | `—` |
| `planning.releaseGrouping.labelPrefix` | `sw:release:` | `sw:release:` | `sw:release:` | `sw:release:` | `—` | `—` |
| `planning.releaseGrouping.mode` | `milestone` | `milestone` | `milestone` | `milestone` | `—` | `—` |
| `planning.store.backend` | `in-repo-public` | `in-repo-public` | `in-repo-public` | `in-repo-public` | `—` | `—` |
| `planning.store.issues.tokenEnv` | `—` | `—` | `—` | `—` | `legacy` | `—` |
| `planning.store.operatorProjection.githubProjects.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `planning.store.operatorProjection.linear.cycleSharingNotice` | `true` | `true` | `true` | `true` | `—` | `—` |
| `planning.store.operatorProjection.linear.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `planning.store.operatorProjection.linear.initiativeSubstitute` | `substitute-views` | `substitute-views` | `substitute-views` | `substitute-views` | `—` | `—` |
| `planning.visibilityProfile` | `specs-public` | `specs-public` | `specs-public` | `specs-public` | `—` | `—` |
| `planningDir` | `docs/planning` | `docs/planning` | `docs/planning` | `docs/planning` | `—` | `—` |
| `prdsDir` | `docs/prds` | `docs/prds` | `docs/prds` | `docs/prds` | `—` | `—` |
| `quality.provider` | `none` | `none` | `none` | `none` | `—` | `—` |
| `rca.fanout.ambiguity_trigger` | `true` | `true` | `true` | `true` | `—` | `—` |
| `rca.fanout.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `rca.fanout.max_width` | `4` | `4` | `4` | `4` | `—` | `—` |
| `rca.fanout.min_hypotheses` | `3` | `3` | `3` | `3` | `—` | `—` |
| `recurrence.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `recurrence.threshold` | `3` | `3` | `3` | `3` | `—` | `—` |
| `retrospective.gapCapture.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `retrospective.gapCapture.maxCapturesPerRun` | `3` | `3` | `3` | `3` | `—` | `—` |
| `review.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `review.local.apply` | `auto` | `auto` | `auto` | `auto` | `—` | `—` |
| `review.local.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `review.local.gate.haltOn` | `[]` | `[]` | `[]` | `[]` | `—` | `—` |
| `review.local.gate.surface` | `["P0", "P1", "P2", "P3"]` | `["P0", "P1", "P2", "P3"]` | `["P0", "P1", "P2", "P3"]` | `["P0", "P1", "P2", "P3"]` | `—` | `—` |
| `review.local.grouping` | `auto` | `auto` | `auto` | `auto` | `—` | `—` |
| `review.local.provider` | `native` | `native` | `native` | `native` | `—` | `—` |
| `review.local.ui.enrich` | `off` | `off` | `off` | `off` | `—` | `—` |
| `review.provider` | `none` | `none` | `none` | `none` | `—` | `—` |
| `review.selection.maxPersonas` | `32` | `32` | `32` | `32` | `—` | `—` |
| `review.selection.minPersonas` | `1` | `1` | `1` | `1` | `—` | `—` |
| `stabilizeLoop.sameStageEscalation.enabled` | `true` | `true` | `true` | `true` | `—` | `—` |
| `stabilizeLoop.sameStageEscalation.escalateAfterFailures` | `2` | `2` | `2` | `2` | `—` | `—` |
| `stabilizeLoop.sameStageEscalation.personaFallback` | `adversarial` | `adversarial` | `adversarial` | `adversarial` | `—` | `—` |
| `stateFile` | `.git/shipwright.json` | `.git/shipwright.json` | `.git/shipwright.json` | `.git/shipwright.json` | `—` | `—` |
| `tasks.sizing.maxPhaseCount` | `13` | `13` | `13` | `13` | `—` | `—` |
| `tasks.sizing.minPhaseFiles` | `2` | `2` | `2` | `2` | `—` | `—` |
| `tasks.sizing.minPhaseScenarios` | `1` | `1` | `1` | `1` | `—` | `—` |
| `tasksDir` | `docs/prds` | `docs/prds` | `docs/prds` | `docs/prds` | `—` | `—` |
| `tournament.cost_ceiling` | `0` | `0` | `0` | `0` | `—` | `—` |
| `tournament.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `tournament.n` | `3` | `3` | `3` | `3` | `—` | `—` |
| `verify.allowUnconfigured` | `false` | `false` | `false` | `false` | `—` | `—` |
| `verify.watchdog.maxMinutes` | `120` | `120` | `120` | `120` | `—` | `—` |
| `verifyE2e.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `verifyE2e.provider` | `none` | `none` | `none` | `none` | `—` | `—` |
| `verifyMutation.enabled` | `false` | `false` | `false` | `false` | `—` | `—` |
| `verifyMutation.provider` | `none` | `none` | `none` | `none` | `—` | `—` |
| `workflow.extensions.externalIntake` | `false` | `false` | `false` | `false` | `—` | `—` |
| `workflow.extensions.handoffBundle` | `false` | `false` | `false` | `false` | `—` | `—` |
| `workflow.extensions.packageSdk` | `false` | `false` | `false` | `false` | `—` | `—` |
| `worktree.parallelCeiling` | `4` | `4` | `4` | `4` | `—` | `—` |
| `worktree.scaffold.portRangeEnd` | `9199` | `9199` | `9199` | `9199` | `—` | `—` |
| `worktree.scaffold.portRangeStart` | `9100` | `9100` | `9100` | `9100` | `—` | `—` |
<!-- effective-config:end generated -->
<!-- currency: refreshed 2026-08-27T15:30:00Z for workflow.extensions / handoff_bundle bindings -->
