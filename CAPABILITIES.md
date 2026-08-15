# Shipwright shipped capability matrix

Authoritative summary of which storage backends and issue-store providers are
**shipped** (wired to a live adapter) versus **deferred** (recognized but
fail-closed until a follow-up unit lands the adapter).
Generated from `core/sw-reference/capability-registry.json` via `scripts/capability_docs.py` — do not edit by hand.

> **Deferred / fail-closed — `gitlab-issues` (PRD 057 R7 / D1, gap-039).**
> The GitLab Issues provider is **not shipped**: no live `planning_gitlab_client.py`
> adapter is wired into `issues_lib._live_backend` for the standard write path.
> Selecting it for a live issue-store backend **fails closed** with the operator
> message:
>
> > issue provider `gitlab-issues` is deferred (fail-closed): no live adapter is
> > shipped in this release. Select a shipped provider (`github-issues` or `jira`),
> > or use the file-store fallback. A follow-up unit will implement the live
> > `planning_gitlab_client.py` adapter and re-add it to the shipped set
> > (PRD 057 R7 / D1; gap-039).
>
> **Follow-up unit:** a dedicated unit will implement the live GitLab Issues
> adapter at parity and re-add `gitlab-issues` to the shipped issues set.
> Until then, config that names `gitlab-issues` is *recognized* (kept in
> `ISSUES_PROVIDERS` for validation) but resolves to the
> `issues-provider-not-shipped` fallback rather than an advertised round-trip.

## Planning-store backends

| Backend | Status |
| --- | --- |
| `in-repo-public` | shipped |
| `local-synced` | shipped |
| `memory` | shipped |
| `issue-store` | shipped |
| `private-repo` | deferred |
| `encryption-at-rest` | deferred |

## Issue-store providers

| Provider | Status | Live adapter |
| --- | --- | --- |
| `github-issues` | **shipped** | `planning_github_client.py` |
| `jira` | **shipped** | `planning_jira_client.py` |
| `gitlab-issues` | **deferred / fail-closed** (PRD 057 R7 / D1, gap-039) | follow-up unit |
| `linear` | **shipped** | `planning_linear_client.py` |
| `none` | shipped (file-store fallback) | file-store fallback |

Provider adapter specs live under `core/providers/issues/`. The neutral verb
contract and per-provider degradation matrix are documented in
`core/providers/issues/CAPABILITIES.md`; the deferred GitLab adapter is noted in
`core/providers/issues/gitlab-issues.md`.
