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

GraphQL is permitted **only** behind an explicit per-verb capability flag when REST lacks parity (R50).
The selector fails closed when a required capability is absent — no silent partial behavior (R31).

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
| `issue-create` | REST | REST | REST (047) | — (fallback) |
| `issue-get` | REST | REST | REST (047) | — |
| `issue-update` | REST + ETag | REST + ETag | REST (047) | — |
| `issue-comment` | REST | REST | REST (047) | — |
| `issue-label` | REST | REST | REST (047) | — |
| `issue-lock` | REST (lock conversation) | REST (issue lock) | REST (047) | — |
| `issue-search` | REST | REST | REST (047) | — |
| `issue-lock` GraphQL fallback | gated `graphql.issue-lock` | — | — | — |
| `issue-search` GraphQL fallback | gated `graphql.issue-search` | — | — | — |
| Native confidential/private issues | not portable guarantee | bonus only | project-dependent | — |
| Flat labels | yes | yes | mapped | — |

`none` always routes to `in-repo-public` file-store fallback (R3) with a documented notice — never blocks work.

