---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: planning.store.issuesProvider
        equals: github-issues
    metadata:
      providerFamily: issues
      adapterId: github-issues
      selectionFamily: providers
      gateRef: check-gate.py
      linkedPrGraphqlScopes: "[\"read:project\", \"read:org\"]"
      linkageSoT: "sw:deliver-annotate"
      issueMilestoneVerb: issue-milestone
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
    "linked-pr-introspection": true,
    "issue-milestone": true
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
| `issue-milestone` | `PATCH /repos/{owner}/{repo}/issues/{n}` (`milestone` field) |

## Auth

Issue-store mutations resolve through committed `planning.store.issues.credentialRef` and the
machine-local credential selector — independent of `host.credentialRef`. `scripts/planning_store.py`
calls `credentials.resolver` with `purpose: planning`; secret material is delivered only via
`credentials.send_path` after scope checks pass.

Selector entries must declare non-empty `allowedRepos`, `allowedProjectIds` (must include committed
`projectId`), and `allowedEndpoints` scoped to the issue API base (for example
`https://api.github.com`). The broker refuses out-of-scope remotes, project ids, and endpoints —
enforcement is fail-closed.

During the one-release alias window, `planning.store.issues.tokenEnv` (default
`ISSUES_GITHUB_TOKEN`) may name the presence env var for an `environment` backend —
`credentialRef` wins when both are set. Minimum scope: `repo` or `public_repo`.

Diagnose: `python3 scripts/credentials-doctor.py --root .` and
`python3 scripts/planning_store.py probe-issues-token`. See
[configuration — Credential references](../../docs/guides/configuration.md#credential-references-and-machine-local-selector).


## Phase 2 artifact CRUD (PRD 043)

Planning artifacts (PRD/gap/tasks/brainstorm) are created via `issue-create` with:

- Title: `[<projectKey>] <type>:<unitId>`
- Labels: `sw:project:<key>` + `sw:<type>`
- Body: canonical markers + markdown + optional `sw-edges` block

Mutations use `issue-update` with `If-Match` / etag preconditions (R36). Hermetic CI uses
`SW_ISSUES_FIXTURE=1` — no live API calls.

## Document-review facade (PRD 341)

Public review path is the planning-store facade (`post_review_finding`, `open_review_manifest`,
`read_review_manifest`, `verify_review_manifest`, `complete_review_round`) — **post-then-open** for new rounds.
`issue-comment` remains adapter-internal. Live witnesses use stripped-hash exclusion; run cache is non-authoritative.

