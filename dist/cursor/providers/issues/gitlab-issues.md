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
