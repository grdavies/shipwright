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

### PRD absorbs projection (PRD 094 R1/R13/R14)

Hybrid-operator PRD bodies do **not** persist raw YAML `absorbs:` on the stored body. Absorb targets
project into the `sw-edges` payload as `{"rel":"absorbs","target":"<unit-id>"}` entries (alias-normalized,
order-insensitive on read).

| Rule | Behavior |
| --- | --- |
| Write path | New absorbs edges **merge into** the existing `edges[]` set; pre-existing `depends` / `blocks` / other rels and `native[]` links are preserved — never replaced by an absorbs-only fence |
| Read path | Parse `sw-edges` **before** marker strip; edges are authoritative over truncated discovery labels |
| Label cap | `MAX_EDGE_LABELS_PER_RELATION` may truncate label projection only — the fence remains the durable graph |
| Structural keys | `absorbs`, `depends`, `blocks`, `amends`, `extends`, `supersedes` MUST NOT appear in `sw-frontmatter-extra` on write or override edges on read |

Put→get round-trip must preserve the full absorb target set (including counts above the label cap) with
no silent drop. `record_absorb_linkage` merges through the same hybrid path; semantic `changed` compares
alias-normalized sets, not byte identity.

## Hash

`canonical_hash = sha256(canonical_form).hexdigest()` — full 64-char digest (distinct from 16-char
operational `content_hash` in store logs).

## Golden vectors

Cross-provider fixtures: `scripts/tests/fixtures/canonical/*.json` — verified by
`python3 scripts/test/run_planning_store_fixtures.py`.

## Decision evidence — `ResearchEvidence` (PRD 326)

Hash-linked research evidence records bind retrieved claims and source digests to a parent decision node
in a `DecisionGraph`. Schema: `core/sw-reference/research-evidence.schema.json`. Store root:
`.cursor/sw-decision-evidence/` — one file per parent id: `<parentDecisionId>.json`.

### Document shape

```json
{
  "apiVersion": "decision-evidence/v1",
  "kind": "ResearchEvidence",
  "metadata": {
    "parentDecisionId": "<node-id>",
    "linkedAt": "<UTC ISO-8601>",
    "sourceKind": "<provenance-kind>"
  },
  "spec": {
    "claim": "<normalized claim>",
    "sources": [
      {"uri": "<uri>", "accessedAt": "<UTC>", "digest": "<sha256-hex>", "quote": "<optional>"}
    ],
    "retrievedAt": "<UTC ISO-8601>",
    "contentHash": "<sha256-hex>",
    "linkBack": {"decisionNodeId": "<node-id>", "hashLinked": true}
  }
}
```

`additionalProperties` is **false** at every object level in the schema — no extension bags on write.

### Canonical JSON (sorted keys)

Normative serialization for hashing and byte-stable comparison:

```python
json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Apply at every nesting level (full document, `metadata`, `spec`, each `sources[]` entry, `linkBack`).

### `contentHash`

`spec.contentHash` is the lowercase hex SHA-256 digest of the canonical JSON for the **spec payload
excluding `contentHash`**:

```python
material = {k: v for k, v in spec.items() if k != "contentHash"}
content_hash = hashlib.sha256(
    json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
).hexdigest()
```

Readers verify by recomputing from stored fields; mismatch fails closed (`evidence:content-hash-mismatch`).

### Link-back

`spec.linkBack.decisionNodeId` MUST equal `metadata.parentDecisionId`. When `hashLinked` is `true`, graph
writers attach the evidence `contentHash` (and optional head metadata) onto the parent decision node's
`resolution` — same contract as prototype evidence link-back in `scripts/decision_graph/evidence.py`.

## Live document-review witness exclusion (PRD 341)

Frozen/canonical hashing **excludes** live `sw-doc-review-round` body witnesses and related review markers from
the hashed byte sequence (stripped-hash / `body-sha256/v1`). The witness must remain on the live issue body —
never strip it from the body to manufacture a hash match. Completion receipts are not freeze authority.

