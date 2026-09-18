# GitHub Issues (planning / doc-review)

Shipwright's GitHub issues provider backs `planning.store.backend: issue-store` for planning units and
document-review transport.

## Document review

| Topic | Rule |
| --- | --- |
| Enablement | **GitHub** and **Linear** issue-store live after `docReviewComments` preflight; Jira/Notion are fixture-enabled-not-dogfooded (not operator-live) |
| Public API | Five facade ops: `post_review_finding`, `open_review_manifest`, `read_review_manifest`, `verify_review_manifest`, `complete_review_round` |
| Sequence (new rounds) | **post-then-open** → verify → synthesize → **complete** |
| `issue-comment` | Adapter-internal only — not a public review verb |
| Stripped-hash | Live `sw-doc-review-round` witness stays on the body; excluded from `body-sha256/v1` / frozen hash |
| Cache | `.cursor/doc-review-runs/` is gitignored cache-only (non-authoritative) |

Providers without a complete `docReviewComments` floor return `doc-review-provider-unsupported` on the
doc-review facade — planning/issue LCD may still work for Jira/Notion. See
`core/documentation/issue-store.md`, `skills/doc-review/SKILL.md`, and `core/providers/issues/CAPABILITIES.md`.
