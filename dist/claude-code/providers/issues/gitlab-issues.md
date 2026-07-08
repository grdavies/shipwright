---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: planning.store.issuesProvider
      equals: "gitlab-issues"
  metadata:
    providerFamily: issues
    adapterId: gitlab-issues
    selectionFamily: providers
    gateRef: check-gate.py
    issueMilestoneVerb: issue-milestone
---

# GitLab Issues adapter

> **⛔ Deferred / fail-closed (PRD 057 R7 / D1, gap-039).** `gitlab-issues` is
> **not shipped**: it is removed from `SHIPPED_ISSUES_PROVIDERS` and no live
> `planning_gitlab_client.py` adapter is wired into `issues_lib._live_backend`
> for the standard write path. Selecting it for a live issue-store backend
> **fails closed** with the operator message:
>
> > issue provider `gitlab-issues` is deferred (fail-closed): no live adapter is
> > shipped in this release. Select a shipped provider (`github-issues` or `jira`),
> > or use the file-store fallback. A follow-up unit will implement the live
> > `planning_gitlab_client.py` adapter and re-add it to the shipped set
> > (PRD 057 R7 / D1; gap-039).
>
> `gitlab-issues` stays a *recognized* provider (kept in `ISSUES_PROVIDERS` for
> config validation), so an issue-store config that names it resolves to the
> `issues-provider-not-shipped` fallback rather than a partial round-trip.
> **Follow-up unit:** a dedicated unit will land the live adapter at parity and
> re-add `gitlab-issues` to the shipped set. The verb/REST mapping below is the
> target contract for that follow-up and does not describe currently shipped
> behavior.

Selected when `planning.store.issuesProvider` is `gitlab-issues` (independent of `host.provider`).

## Capability flags

```json
{
  "verbs": {
    "issue-create": true,
    "issue-get": true,
    "issue-update": true,
    "issue-comment": true,
    "issue-label": true,
    "issue-lock": true,
    "issue-search": true,
    "issue-close": true,
    "issue-milestone": true
  },
  "graphql": {},
  "lcd": ["title", "body", "comments", "state", "labels"]
}
```

## REST mapping (primary)

| Verb | Transport |
| --- | --- |
| `issue-create` | `POST /projects/{id}/issues` |
| `issue-get` | `GET /projects/{id}/issues/{iid}` |
| `issue-update` | `PUT /projects/{id}/issues/{iid}` |
| `issue-comment` | `POST /projects/{id}/issues/{iid}/notes` |
| `issue-label` | `PUT /projects/{id}/issues/{iid}` (labels array) |
| `issue-lock` | `PUT /projects/{id}/issues/{iid}` (`discussion_locked`) |
| `issue-search` | `GET /projects/{id}/issues` (scoped filters) |
| `issue-milestone` | `PUT /projects/{id}/issues/{iid}` (`iteration_id` when available) |

## Auth

Token from `planning.store.issues.tokenEnv` (default `ISSUES_GITLAB_TOKEN`). Minimum scope: `api`.
Never stored in config.


## Phase 2 artifact CRUD (PRD 043)

Planning artifacts (PRD/gap/tasks/brainstorm) are created via `issue-create` with:

- Title: `[<projectKey>] <type>:<unitId>`
- Labels: `sw:project:<key>` + `sw:<type>`
- Body: canonical markers + markdown + optional `sw-edges` block

Mutations use `issue-update` with `If-Match` / etag preconditions (R36). Hermetic CI uses
`SW_ISSUES_FIXTURE=1` — no live API calls.
