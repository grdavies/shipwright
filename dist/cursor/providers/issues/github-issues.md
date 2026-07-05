---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: planning.store.issuesProvider
      equals: "github-issues"
  metadata:
    providerFamily: issues
    adapterId: github-issues
    selectionFamily: providers
    gateRef: check-gate.py
---

# GitHub Issues adapter

Selected when `planning.store.issuesProvider` is `github-issues` (independent of `host.provider`).

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
    "linked-pr-introspection": true
  },
  "graphql": {
    "issue-lock": false,
    "issue-search": false,
    "linked-pr": false
  },
  "lcd": ["title", "body", "comments", "state", "labels"]
}
```

## REST mapping (primary)

| Verb | Transport |
| --- | --- |
| `issue-create` | `POST /repos/{owner}/{repo}/issues` |
| `issue-get` | `GET /repos/{owner}/{repo}/issues/{n}` |
| `issue-update` | `PATCH /repos/{owner}/{repo}/issues/{n}` |
| `issue-comment` | `POST /repos/{owner}/{repo}/issues/{n}/comments` |
| `issue-label` | `POST /repos/{owner}/{repo}/issues/{n}/labels` |
| `issue-lock` | `PUT /repos/{owner}/{repo}/issues/{n}/lock` |
| `issue-search` | `GET /search/issues` (project-scoped query) |

## Auth

Token from `planning.store.issues.tokenEnv` (default `ISSUES_GITHUB_TOKEN`). Minimum scope: `repo`
or `public_repo`. Never stored in config.


## Phase 2 artifact CRUD (PRD 043)

Planning artifacts (PRD/gap/tasks/brainstorm) are created via `issue-create` with:

- Title: `[<projectKey>] <type>:<unitId>`
- Labels: `sw:project:<key>` + `sw:<type>`
- Body: canonical markers + markdown + optional `sw-edges` block

Mutations use `issue-update` with `If-Match` / etag preconditions (R36). Hermetic CI uses
`SW_ISSUES_FIXTURE=1` — no live API calls.
