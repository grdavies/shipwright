# Issue-store planning backend

When `planning.store.backend` is `issue-store`, planning artifacts live on issues rather than local
`docs/prds/` files as authority. Document-review rounds use the issue-store facade on **GitHub** and
**Linear** when `docReviewComments` preflight passes. **Jira** and **Notion** are documented in the
provider matrix as fixture-enabled-not-dogfooded — not operator-live until promotion.

## Document-review transport

- **Facade only** — workflows call the five `*_review_*` facade ops; never public `issue-comment` for persona findings.
- **post-then-open / complete** for new rounds; bootstrap in-flight rounds may still open-then-post/`close`.
- **Stripped-hash exclusion** — freeze/canonical hash omit the live review witness; do not strip the witness from the body.
- **Cache-only** — `.cursor/doc-review-runs/` cannot authorize open or complete.
- **Isolation** — `/sw-deliver` must not open/complete review rounds or treat doc-review cache as store truth.

## Packaged shipped providers (dual-root)

When `planning.store.backend` is `issue-store`, live selection consults shipped issues-provider
conformance across **both**:

- Source / dev checkout: `core/sw-reference/provider-conformance/`
- Packaged host bundles: `dist/<host>/core/sw-reference/provider-conformance/` for each built host in
  `PACKAGED_DIST_IDS` (`cursor`, `claude-code`, `codex`, `opencode`)

Package-root-only staging (records only at the wheel root without `dist/<host>/…`) yields an empty shipped
set — Linear may appear **recognized-but-not-shipped** even when credentials succeed.

Resolution and gating share `shipped_issues_providers()` in `planning_store_facade.py` (live, root-keyed cache).
**Active-host** evidence is consulted first; sibling `dist/<host>/` bundles apply only when the active-host
record is **absent** — never when present-and-fail. With **no active host**, resolution walks present
`dist/<host>/` bundles in `PACKAGED_DIST_IDS` order (first present record wins, including present-and-fail).
Operator recovery copy: `PACKAGED_CONFORMANCE_RECOVERY` in `scripts/planning/packaged_conformance_roots.py`.
Named search roots for diagnostics: `packaged_conformance_search_roots()`.

Provider conformance suite: `scripts/planning/provider_conformance.py` → `run_doc_review_conformance_suite`.
Packaged multi-root helpers: `scripts/planning/packaged_conformance_roots.py`. See also
`core/documentation/configuration.md` and `core/documentation/self-upgrade.md`.
