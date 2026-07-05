---
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: providers
      scope: issues-contract
  metadata:
    providerFamily: issues
    selectionFamily: providers
---

# Issues provider capabilities (PRD 043)

Neutral contract for issue-backed planning storage. Consumers route through `issues.*` verbs;
adapters are selected by `planning.store.issuesProvider` (independent of `host.provider`).

## Verb contract (REST-primary)

| Verb | Purpose |
| --- | --- |
| `issue-create` | Create a planning artifact issue |
| `issue-get` | Read issue title/body/state/comments |
| `issue-update` | Mutate title/body/state with optimistic concurrency |
| `issue-comment` | Append or update ordered comments (chunk overflow) |
| `issue-label` | Apply flat labels (`sw:project:<key>`, type markers) |
| `issue-lock` | Lock issue at freeze |
| `issue-search` | Project-scoped issue queries |
| `issue-close` | **045 R67** — explicit idempotent close for separate-repo planning store (`runId+issueRef` key) |
| `linked-pr-introspection` | **045 R73** — verify-only PR↔issue linkage (GraphQL behind flag; REST/body fallback) |
| `issue-milestone` | **045 R71** — assign `sw:prd` units to provider milestone/iteration; flat-label fallback when absent |

GraphQL is permitted **only** behind an explicit per-verb capability flag when REST lacks parity (R50).
The selector fails closed when a required capability is absent — no silent partial behavior (R31).

### GraphQL linked-PR scopes (PRD 043 R37 / 045 R73)

| Verb | GraphQL flag | Minimum scopes (GitHub) |
| --- | --- | --- |
| `linked-pr-introspection` | `graphql.linked-pr` | `read:project`, `read:org` (issue ↔ PR linkage query only) |

Probed at init via `python3 scripts/planning_store.py probe-issues-token`. Annotation comments remain the
linkage source of truth — GraphQL/REST introspection is verify-only and fails closed on disagreement.

## Lowest-common-denominator (LCD) contract (R30)

Portable core fields every adapter must surface:

- **title** — plain text with `[<projectKey>]` prefix convention
- **body** — markdown artifact payload + machine markers
- **comments** — ordered thread (chunk manifest lives here when body overflows)
- **state** — open/closed (mapped from provider-native states)
- **labels** — flat string labels only (no nested label groups in portable core)

## Token probe (R44)

Issue-store credentials use `planning.store.issues.tokenEnv` — **distinct** from `host.tokenEnv`.

| Provider | Default `tokenEnv` | Minimum scopes |
| --- | --- | --- |
| `github-issues` | `ISSUES_GITHUB_TOKEN` | `repo` or `public_repo` |
| `gitlab-issues` | `ISSUES_GITLAB_TOKEN` | `api` |
| `jira` | `ISSUES_JIRA_TOKEN` | `read:jira-work`, `write:jira-work` (PRD 047) |
| `none` | — | skipped (file-store fallback) |

Probe at init via `python3 scripts/planning_store.py probe-issues-token` — fail-closed on
missing/insufficient scope; token values never appear in output or logs.

## Per-provider degradation matrix

Selector requires the verb capability; absent capability → fail-closed halt.

| Verb / feature | github-issues | gitlab-issues | jira | none |
| --- | --- | --- | --- | --- |
| `issue-create` | REST | REST | REST (`/rest/api/3/issue` Cloud; `/rest/api/2/issue` DC) | — (fallback) |
| `issue-get` | REST | REST | REST (`GET /rest/api/3/issue/{key}`) | — |
| `issue-update` | REST + ETag | REST + ETag | REST (`PUT /rest/api/3/issue/{key}`) | — |
| `issue-comment` | REST | REST | REST (`POST .../comment`) | — |
| `issue-label` | REST | REST | REST (`update.labels`) | — |
| `issue-lock` | REST (lock conversation) | REST (issue lock) | **degraded** (hash-authoritative; R104) | — |
| `issue-search` | REST | REST | REST (JQL `POST /rest/api/3/search`) | — |
| `issue-close` | REST (`PATCH` state=closed) | REST | REST (transition idempotent close) | — |
| `linked-pr-introspection` | gated `graphql.linked-pr` + REST fallback | REST (notes) | — | — |
| `issue-milestone` | REST (milestone field) | REST (iteration) | — (047 TBD) | — (skip+notice) |
| `issue-lock` GraphQL fallback | gated `graphql.issue-lock` | — | — | — |
| `issue-search` GraphQL fallback | gated `graphql.issue-search` | — | — | — |
| Native confidential/private issues | not portable guarantee | bonus only | **unsupported** (project-level; R105) | — |
| Flat labels | yes | yes | labels → components → custom field (R109) | — |

`none` always routes to `in-repo-public` file-store fallback (R3) with a documented notice — never blocks work.


### Epic/sub-issue hierarchy (R94)

Task lists map to a provider **epic** with one **sub-issue per phase** where the hierarchy verbs are
present; otherwise deliver degrades to a checkbox/body-encoded phase list embedded in the epic body
(mandatory fallback — deliver continues with operator notice).

| Verb | Purpose |
| --- | --- |
| `issue-epic-create` | Create parent epic for frozen task list |
| `issue-sub-issue-create` | Create per-phase child issue |
| `issue-sub-issue-update` | Update child state/labels as phases merge |
| `issue-sub-issue-link` | Link child to parent (native link or body `sw-edges`) |

GraphQL is permitted only behind an explicit per-verb capability flag when REST lacks parity (R50).

| Verb / feature | github-issues | gitlab-issues | jira | none |
| --- | --- | --- | --- | --- |
| `issue-epic-create` | REST | REST | pending (047) | — (checkbox fallback) |
| `issue-sub-issue-create` | REST | REST | pending (047) | — |
| `issue-sub-issue-update` | REST | REST | pending (047) | — |
| `issue-sub-issue-link` | REST | REST | pending (047) | — |
| Checkbox/body fallback | yes | yes | yes | yes (only path) |
| Per-phase API budget (R81) | composes with requestBudget | composes | composes | n/a |

`none` and providers lacking hierarchy verbs emit a single skip notice and continue with checkbox/body
fallback — never block deliver.

### `issue-milestone` degradation (R71)

When `planning.releaseGrouping.mode` is `milestone` or `iteration` but the configured provider lacks
`issue-milestone`, `/sw-deliver` emits a single skip with operator notice and continues with flat-label fallback
(`planning.releaseGrouping.labelPrefix`, default `sw:release:`). Deliver is never blocked.

| Provider | `issue-milestone` | Native field |
| --- | --- | --- |
| `github-issues` | yes | GitHub milestone |
| `gitlab-issues` | yes | GitLab iteration |
| `jira` | pending (047) | fixVersion / sprint |
| `none` | skip+notice | flat-label only |



## Jira Cloud vs DC/Server (PRD 047 R100)

| Concern | Cloud | DC/Server |
| --- | --- | --- |
| Description format | ADF | Wiki markup |
| Auth | Email + API token | PAT required (password/basic rejected) |
| REST API | `/rest/api/3/` | `/rest/api/2/` |
| `issue-lock` | degraded (hash-authoritative) | degraded |
| Per-issue privacy | unsupported | unsupported |
| Canonical normalization | `adf_to_markdown` | `wiki_to_markdown` |

Adapter spec: `core/providers/issues/jira.md`.
