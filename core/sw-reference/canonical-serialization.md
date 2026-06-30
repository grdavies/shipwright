---
title: Canonical serialization (issue-store)
visibility: public
---

# Canonical serialization (PRD 043 R35)

Normative provider-render-independent form for issue-backed planning artifacts. The content-hash is
SHA-256 over the canonical JSON payload below.

## Version marker

Every artifact body includes `<!-- sw-canonical-version: 1 -->`. The canonical payload carries
`sw-canonical-version: "1"`.

## Body markers (authoritative for isolation — R42)

| Marker | Purpose |
| --- | --- |
| `sw-project-key` | Project scoping (`planning.store.projectKey`) |
| `sw-artifact-type` | `prd` \| `gap` \| `tasks` \| `brainstorm` |
| `sw-unit-id` | Stable unit id |
| `sw-canonical-version` | Serialization version |

Title prefix `[<projectKey>]` and labels (`sw:project:<key>`, `sw:<type>`) are portable identification;
**body marker is authoritative** on read for project isolation (R12).

## Canonical payload

```json
{
  "sw-canonical-version": "1",
  "title": "<normalized title>",
  "body": "<normalized body after chunk reassembly>",
  "state": "open|closed",
  "labels": ["sorted", "labels"],
  "comments": [{"id": "...", "body": "..."}]
}
```

Normalization: CRLF→LF, trim trailing spaces per line, strip leading/trailing blank lines.

## Excluded comments

Comments tagged `sw-freeze-record` or `sw-chunk-overflow` are excluded from canonicalization (R37/R46).

## Chunk overflow (R9)

When UTF-8 body exceeds the adapter limit, overflow is stored in ordered comments with a body manifest:

`<!-- sw-chunk-manifest: {"version":1,"chunks":[{"index":0,"commentId":"..."}]} -->`

Reassembly concatenates chunk bodies in manifest order.

## sw-edges block (R29/R47)

Portable edges live in a fenced block:

````markdown
```sw-edges
{"version":1,"edges":[...],"native":[...]}
```
````

The body block is **authoritative on conflict**; native links/sub-issues are reconciled on read.
Divergence beyond tolerance fails closed (`edge-divergence`).

## Hash

`canonical_hash = sha256(canonical_form).hexdigest()` — full 64-char digest (distinct from 16-char
operational `content_hash` in store logs).

## Golden vectors

Cross-provider fixtures: `scripts/tests/fixtures/canonical/*.json` — verified by
`python3 scripts/test/run_planning_store_fixtures.py`.
