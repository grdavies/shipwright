# Memory envelope field lossiness matrix (PRD 082 R29)

Canonical v2 envelope fields are defined in `scripts/memory_envelope_v2.py`. This matrix records how each
memory provider adapter carries, side-channels, or loses fields during round-trip. **Planning bodies** (Recallium
`planning-bodies/<unitId>` and local planning-store bodies) are **outside** the v2 envelope record domain — they
require no envelope wrapper.

Legend:

| Class | Meaning |
| --- | --- |
| **native** | Stored in the provider's primary record and round-trips without loss |
| **side-channel** | Persisted in adapter metadata, tags, or a companion file — not the primary note body |
| **lossy** | Dropped or approximated on write; may be reconstructed heuristically on read |
| **n/a** | Not applicable — provider does not persist distilled memory records in this shape |

## Field reference

| Field | Role |
| --- | --- |
| `stableId` | Durable identity for supersession and alias merge |
| `projectId` | Owning project / palace / vault scope |
| `category` | Memory taxonomy (decision, learning, rule, …) |
| `status` | `active` or `superseded` |
| `scope` | Repo/path/tag scope object |
| `evidenceRefs` | Pointers to decision records, files, or external evidence |
| `confidence` | 0.0–1.0 operator/model confidence |
| `observedAt` | First observation timestamp (ISO-8601) |
| `lastValidatedAt` | Last human or gate validation timestamp |
| `validUntil` | Optional expiry for time-bounded memories |
| `supersedes` | Prior `stableId` values replaced by this record |
| `contentHash` | SHA-256 over canonical envelope semantic content |
| `schemaVersion` | Envelope codec version (currently `2`) |
| `sensitivity` | Redaction tier (`public` … `secret`) |
| `appliedRedaction` | Provenance for redaction chokepoint application |

## Per-adapter matrix

### `in-repo`

| Field | Class | Notes |
| --- | --- | --- |
| `stableId` | native | OKF frontmatter `id` / permalink |
| `projectId` | side-channel | Implicit repo root; stored in export metadata |
| `category` | native | Frontmatter `category` |
| `status` | native | Frontmatter `status` |
| `scope` | side-channel | Derived from `related_files` + tags in compiled truth |
| `evidenceRefs` | native | `related_files` list |
| `confidence` | lossy | Not in legacy OKF; defaults on import |
| `observedAt` | native | Timeline `created` entry |
| `lastValidatedAt` | side-channel | Timeline `truth-updated` |
| `validUntil` | side-channel | Optional frontmatter extension |
| `supersedes` | native | Typed `supersedes` edge in index |
| `contentHash` | side-channel | Stored in interchange export manifest |
| `schemaVersion` | native | Interchange manifest |
| `sensitivity` | native | `visibility` axis maps to sensitivity tier |
| `appliedRedaction` | side-channel | Export manifest redaction block |

### `recallium`

| Field | Class | Notes |
| --- | --- | --- |
| `stableId` | native | Recallium memory id / permalink |
| `projectId` | native | `project_name` |
| `category` | native | Memory type / category |
| `status` | side-channel | Inactive flag + tags (`superseded`) |
| `scope` | lossy | Partial via `related_files` only |
| `evidenceRefs` | native | `related_files` |
| `confidence` | native | `importance_score` maps 1:1 |
| `observedAt` | native | `created_at` |
| `lastValidatedAt` | lossy | No first-class field; may use `updated_at` |
| `validUntil` | lossy | Not native; tag side-channel if needed |
| `supersedes` | side-channel | `related_memory_ids` + traverse `supersedes` edge |
| `contentHash` | side-channel | Adapter-computed on export |
| `schemaVersion` | side-channel | Tag `sw:envelope:v2` |
| `sensitivity` | lossy | Project visibility; redaction at REST boundary |
| `appliedRedaction` | side-channel | Adapter audit on PUT |

**Planning bodies:** Recallium `planning-bodies/<unitId>` payloads stay outside this matrix (no envelope).

### `mempalace`

| Field | Class | Notes |
| --- | --- | --- |
| `stableId` | native | Palace node id |
| `projectId` | native | Palace path scope |
| `category` | native | Node type |
| `status` | side-channel | Tombstone / inactive node |
| `scope` | lossy | Tags only |
| `evidenceRefs` | side-channel | Linked node ids |
| `confidence` | lossy | Not native |
| `observedAt` | native | Node created timestamp |
| `lastValidatedAt` | lossy | Not native |
| `validUntil` | lossy | Not native |
| `supersedes` | native | Typed `supersedes` edge |
| `contentHash` | side-channel | Synthesized export |
| `schemaVersion` | side-channel | Export manifest |
| `sensitivity` | lossy | Operator vault policy only |
| `appliedRedaction` | side-channel | Pre-MCP redaction chokepoint |

### `basic-memory`

| Field | Class | Notes |
| --- | --- | --- |
| `stableId` | native | Note permalink |
| `projectId` | native | BM project id |
| `category` | native | `note_type` folder |
| `status` | side-channel | Soft-delete + tags |
| `scope` | lossy | Tags / relations partial |
| `evidenceRefs` | side-channel | `links[]` targets |
| `confidence` | lossy | Not native |
| `observedAt` | native | Note metadata timestamp |
| `lastValidatedAt` | lossy | Not native |
| `validUntil` | lossy | Not native |
| `supersedes` | side-channel | `links` with `supersedes` edge |
| `contentHash` | side-channel | Interchange manifest |
| `schemaVersion` | side-channel | Interchange manifest |
| `sensitivity` | lossy | Cloud/local policy |
| `appliedRedaction` | side-channel | Export pipeline |

### `obsidian`

| Field | Class | Notes |
| --- | --- | --- |
| `stableId` | native | File path / note id |
| `projectId` | native | Vault path |
| `category` | side-channel | Folder + frontmatter type |
| `status` | side-channel | Frontmatter `status` |
| `scope` | native | Wikilinks + frontmatter paths |
| `evidenceRefs` | native | Wikilink targets |
| `confidence` | lossy | Not native |
| `observedAt` | native | File ctime / frontmatter |
| `lastValidatedAt` | lossy | Not native |
| `validUntil` | lossy | Not native |
| `supersedes` | side-channel | Manual `supersedes` link convention |
| `contentHash` | side-channel | Export manifest |
| `schemaVersion` | side-channel | Export manifest |
| `sensitivity` | lossy | Vault operator policy |
| `appliedRedaction` | side-channel | REST read redaction |

## Upgrade path

v1 envelopes upgrade through `scripts/memory_envelope_upgrade.py` before any adapter change. Unknown v1 keys are
preserved under `v1Preserved` on the v2 record. Stable-id merges are recorded in
`.cursor/sw-memory-envelope-aliases/<scope>.json`.
