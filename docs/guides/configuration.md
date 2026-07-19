# Configuration

Shipwright configures **per target repo** — open your project and run `/sw-init` (`/sw-setup` is a
deprecated alias with identical behavior).

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

Reject examples (config write / hook resolve): `unknown-vendor`, `../traversal`, empty string, or a
catalog row missing adapter integrity or rules script.

For **in-repo**, choose commit mode:
- `committed` (default) — store lives in `.cursor/sw-memory/`; PR-reviewable
- `local` — gitignored at `.cursor/sw-memory-local/`

For **recallium**: setup warns if the health check fails but still allows save.

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
`python3 scripts/resolve-model-tier.py --agent <id>` and run
`python3 scripts/reviewer-dispatch-check.py --agent <id> --parent-model <parent-concrete-id>`;
stamp the resolved concrete `model:` on the Task (do not rely on `model: inherit` from the parent session).

**Task model allowlist:** concrete Task spawn IDs are single-sourced from
`core/sw-reference/task-model-allowlist.json`. `resolve-model-tier.py` and `dispatch-check.py` emit or
accept only allowlisted IDs (or mapped aliases); unknown models fail closed with
`binding:model-not-allowlisted` before spawn. Maintenance cadence and validation commands:
`core/sw-reference/models-tiering.md` (Task model allowlist section). Regression:
`scripts/unit_tests/dispatch/test_task_model_allowlist.py`.

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


### Context compression (`contextCompression.*`)

Task-dispatch prompt construction for `/sw-doc-review`, `/sw-ship`, and gap-check closer dispatches routes
through `scripts/dispatch_prompt.py`. Compression is **available but default-off** — the shipped posture keeps
`contextCompression.enabled: false` until the Phase 12 parity milestone passes.

| Key | Default | Meaning |
| --- | --- | --- |
| `contextCompression.enabled` | `false` | When `true`, large context blocks may be summarized before spawn |
| `contextCompression.thresholdTokens` | `8000` | Token-estimate ceiling before compression/path-ref policy applies |
| `contextCompression.strategies.json` | `compress` | Strategy for JSON blocks: `compress`, `path-reference`, or `passthrough` |
| `contextCompression.strategies.diff` | `path-reference` | Unified-diff blocks prefer path references when file-backed |
| `contextCompression.strategies.log` | `compress` | Log excerpt strategy |
| `contextCompression.strategies.prose` | `compress` | Prose strategy |

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
| `planning.store.issuesProvider` | `github-issues` \| `gitlab-issues` \| `jira` \| `linear` \| `none` | Issues adapter (**independent** of `host.provider`) |
| `planning.store.projectKey` | string | Project scoping key (`^[a-z][a-z0-9-]*$`) |
| `planning.store.storeLocation.mode` | `same-repo` \| `separate-project` | Code repo vs shared planning project |
| `planning.store.storeLocation.owner` / `.repo` | strings | Required for `separate-project` |
| `planning.store.issues.tokenEnv` | string | Dedicated issue API token env (**not** `host.tokenEnv`) |

Example (opt-in):

```json
{
"planning": {
"store": {
"backend": "issue-store",
"issuesProvider": "github-issues",
"projectKey": "my-project",
"storeLocation": { "mode": "same-repo" },
"issues": { "tokenEnv": "ISSUES_GITHUB_TOKEN" }
}
}
}
```

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
| `planning.store.issues.tokenEnv` | string | Dedicated token env (default `ISSUES_JIRA_TOKEN`) |
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
"tokenEnv": "ISSUES_JIRA_TOKEN",
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
| `planning.store.issues.tokenEnv` | string | Dedicated token env (default `ISSUES_LINEAR_TOKEN`; **not** `host.tokenEnv`) |
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
"tokenEnv": "ISSUES_LINEAR_TOKEN",
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
| `deliver.remediation.maxAttempts` | Auto-remediation budget per blocked phase before clean halt (default **2**) |
| `memory.provider` | Catalog-registered provider id (default `in-repo`; seeded: `recallium`). Validated by `memory_provider_register.py` — unknown ids rejected |
| `memory.sourceOfTruth` | `auto` (default), `repo`, or `memory` — authority for **decision** records only (`auto`: external provider → memory, in-repo → repo) |
| `memory.autoSync` | Stop-hook thresholds for `/sw-memory-sync` scheduling |
| `review.provider` | AI review adapter — default **`none`**; `coderabbit` opt-in |
| `quality.provider` | Structural-quality harness — default **`none`** (no-op safe default; `quality:none`) |
| `quality.blockingTier` | Optional triage tier (`quick`/`standard`/`full`) at which a `poor` verdict blocks via gate (unset = advisory only) |
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
python3 scripts/resolve-model-tier.py --command sw-prd
python3 scripts/resolve-model-tier.py --command sw-doc --delegate sw-prd
```

Orchestrators (`sw-doc`, `sw-ship`, `sw-deliver`, `sw-retrospective`) route at `inherit` — always resolve the
delegated child command. Full policy: `.sw/models-tiering.md`.

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
adapter (`scripts/host.py` over REST). Set `host.tokenEnv` (default `GITHUB_TOKEN`) — no host CLI is required.
Repos without a token or Actions can still use local `/sw-verify`, but cannot pass the CI-readiness gate until
GitHub CI is available — `/sw-init` host doctor warns about this honestly.

## Web-specific opt-in knobs

| Knob | Default | Enable when |
|------|---------|-------------|
| `worktree.scaffold` | omitted | Local web app needs port/DB isolation per worktree |
| `verifyE2e` | `enabled: false` | Smoke/E2E routes after static verify |
| `review.local.ui.enrich` | `off` | External design enrichment beyond native WCAG checklist |

Neutral shipped example omits scaffold; dogfood repos may set scaffold explicitly.

## Optional integrations

| Integration | Config | When to enable |
|-------------|--------|----------------|
| **CodeRabbit** | `review.provider: "coderabbit"` | AI review on PRs |
| **Recallium** | `memory.provider: "recallium"` | Seeded external memory store (catalog-registered) instead of in-repo markdown |
| **Sentry** | Production signals via `/sw-feedback` or `/sw-debug` | Route production errors into the debug workstream |

Provider **credentials** come from the environment or your secret store — never commit secrets.

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

