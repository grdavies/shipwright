# GitHub Issues (planning / doc-review)

Shipwright's GitHub issues provider backs `planning.store.backend: issue-store` for planning units and
(PRD 341) document-review transport.

## Document review (PRD 341)

| Topic | Rule |
| --- | --- |
| Enablement | GitHub issue-store only after `docReviewComments` preflight |
| Public API | Five facade ops: `post_review_finding`, `open_review_manifest`, `read_review_manifest`, `verify_review_manifest`, `complete_review_round` |
| Sequence (new rounds) | **post-then-open** → verify → synthesize → **complete** |
| `issue-comment` | Adapter-internal only — not a public review verb |
| Stripped-hash | Live `sw-doc-review-round` witness stays on the body; excluded from `body-sha256/v1` / frozen hash |
| Cache | `.cursor/doc-review-runs/` is gitignored cache-only (non-authoritative) |

Non-GitHub issues providers return `doc-review-provider-unsupported`. See `docs/guides/issue-store.md` and
`skills/doc-review/SKILL.md`.
