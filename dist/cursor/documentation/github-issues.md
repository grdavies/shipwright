# GitHub Issues (planning / doc-review)

Shipwright's GitHub issues provider backs `planning.store.backend: issue-store` for planning units and
document-review transport.

## Document review

| Topic | Rule |
| --- | --- |
| Enablement | **GitHub** issue-store live today after `docReviewComments` preflight; Linear/Jira/Notion issue-store doc-review remain unsupported until those providers ship the same `docReviewComments` floor |
| Public API | Five facade ops: `post_review_finding`, `open_review_manifest`, `read_review_manifest`, `verify_review_manifest`, `complete_review_round` |
| Sequence (new rounds) | **post-then-open** → verify → synthesize → **complete** |
| `issue-comment` | Adapter-internal only — not a public review verb |
| Stripped-hash | Live `sw-doc-review-round` witness stays on the body; excluded from `body-sha256/v1` / frozen hash |
| Cache | `.cursor/doc-review-runs/` is gitignored cache-only (non-authoritative) |

Non-GitHub issues providers (Linear, Jira, Notion, …) return `doc-review-provider-unsupported` on the
doc-review facade until their `docReviewComments` floor ships — planning/issue LCD may still work. See
`core/documentation/issue-store.md`, `skills/doc-review/SKILL.md`, and `core/providers/issues/CAPABILITIES.md`.
