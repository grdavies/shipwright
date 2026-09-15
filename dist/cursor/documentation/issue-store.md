# Issue-store planning backend

When `planning.store.backend` is `issue-store`, planning artifacts and (on GitHub) document-review rounds
live on issues rather than local `docs/prds/` files as authority.

## Document-review transport

- **Facade only** — workflows call the five `*_review_*` facade ops; never public `issue-comment` for persona findings.
- **post-then-open / complete** for new rounds; bootstrap in-flight rounds may still open-then-post/`close`.
- **Stripped-hash exclusion** — freeze/canonical hash omit the live review witness; do not strip the witness from the body.
- **Cache-only** — `.cursor/doc-review-runs/` cannot authorize open or complete.
- **Isolation** — `/sw-deliver` must not open/complete review rounds or treat doc-review cache as store truth.

## Packaged shipped providers (PRD 356)

When `planning.store.backend` is `issue-store`, live selection consults shipped issues-provider
conformance under the installed wheel layout (D3 host-bundle search). Packaged installs load evidence from
`dist/<host>/core/sw-reference/provider-conformance/`; package-root-only staging is insufficient.

Resolution and gating share `shipped_issues_providers()` in `planning_store_facade.py` (live, root-keyed cache).
Fail-closed rules for corrupt/missing **active-host** evidence still apply — siblings cannot override
present-and-fail.

Provider conformance suite: `scripts/planning/provider_conformance.py` → `run_doc_review_conformance_suite`.
Packaged multi-root helpers: `scripts/planning/packaged_conformance_roots.py`.
