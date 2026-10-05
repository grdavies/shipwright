# Trust anchors (install root)

Shipwright pure installs ship workflow scripts inside a versioned zipapp. Dist-only
install roots expose only `scripts/sw-run.py` as a thin shim — not the legacy
`check-gate.py` / `resolve-model-tier.py` marker files. Script dispatch therefore
validates **dist trust anchors** that bind the install manifest and zipapp digests.

## Install-root sidecar

Each install root carries `shipwright-scripts-trust-anchors.json`:

| Field | Purpose |
| --- | --- |
| `schemaVersion` | Document schema (currently `1`) |
| `anchors.<id>.manifestSha256` | SHA-256 of `shipwright.manifest.json` |
| `anchors.<id>.zipappSha256` | SHA-256 of `shipwright.pyz` |
| `anchors.<id>.signerKeyId` | Active operator trust key id |
| `anchors.<id>.signature` | HMAC-SHA256 over `{anchorId, manifestSha256, zipappSha256}` |
| `anchors.<id>.status` | `active`, `expired`, or `revoked` |
| `anchors.<id>.notBefore` / `notAfter` | Rotation overlap window (ISO-8601 UTC) |

Anchors are verified against operator-configured signing keys in
`.cursor/sw-package-trust-anchors.json`. Keys are never embedded in the install
root documentation or committed operator guides.

## Rotation overlap

Release rotation keeps **multiple active anchors** during an overlap window:

1. Ship the new zipapp + manifest with a new anchor entry (`notBefore` ≤ now).
2. Keep the previous anchor entry active until consumers finish upgrading.
3. Mark the retired anchor `expired` or remove it after the overlap ends.

Consumers fail closed when no active anchor matches the on-disk manifest and zipapp
digests, when the signer key is unknown/revoked, or when the signature does not
verify.

## Verification and recovery

`sw_scripts_resolve` accepts a dist-only plugin install only after
`resolve_dist_trust_verdict` returns `ok`. Tampered zipapps or manifests, unknown
signer keys, and expired rotation windows all refuse dispatch — there is no fallback
to workspace `scripts/` or unmarked plugin trees.

Recovery steps:

1. Confirm the install root still contains `shipwright.manifest.json`, `shipwright.pyz`,
   and `shipwright-scripts-trust-anchors.json`.
2. Reinstall from a trusted release channel when digests no longer match any active
   anchor.
3. Update operator signing keys in `.cursor/sw-package-trust-anchors.json` when
   rotation introduces a new `signerKeyId` (never store secrets in consumer repos).

### Scanner exact occurrence enrollment

Signed package dispatch trust permits an installed runtime to run; it does not approve
source occurrences. Scanner enrollment separately pins a reviewed release to one
repository instance. An empty catalog approves no occurrence; occurrence reviews remain
independently authorized, and a populated release needs independent security review of
its actual bytes before enrollment. Building or updating a package never enrolls it.
For real credentials, remove and rotate them; for public or synthetic examples, request
exact review. Follow the [pre-push denial decisions](troubleshooting.md#pre-push-secret-scan-denial)
for changed source requiring fresh review, trusted-install recovery, or retained denial
when approval is unavailable.

Run these commands from the repository being scanned. `SOURCE` names the trusted
Shipwright source checkout, `INSTALL` the trusted install root, and `ARCHIVE` the
absolute regular versioned archive, such as the installed `shipwright-<version>.pyz`
file. Use the actual versioned file when enrolling, not its stable symlink.

```sh
python3 "$SOURCE/scripts/secret_scan.py" pre-push
python3 "$ARCHIVE" secret_scan.py pre-push
python3 "$INSTALL/scripts/sw-run.py" secret_scan.py pre-push
```

`pre-push` is also the default with no command. `file`, `stdin` and `patterns-check`
retain their ordinary behavior; file/stdin scans and uncommitted fallbacks gain no
exact-occurrence exceptions. Scans never create, replace or repair the marker or trust
file. There is no `scan` subcommand or `--pre-push` flag. Both archive and shim pass the
scanner arguments directly, with no `--` separator after `secret_scan.py`.

Enrollment requires a separately authorized operator. Obtain approval through a trusted
channel independent of the installed artifact: the expected archive and catalog digests,
release identifier and repository identity must come from that review, not from treating
whatever is installed as approved. A local digest calculation can compare bytes with
those approved values; it cannot establish approval. Set `RELEASE_ID` to the approved opaque identifier, `ARCHIVE_SHA256` and `CATALOG_SHA256` to the reviewed SHA-256 digests,
`COMMON_DIR` to the canonical absolute repository Git common directory, and `ORIGIN` to
the normalized `github.com/owner/repository` identity. Linked worktrees use their shared
common directory, not their individual Git directory. Equivalent supported HTTPS/SSH
origins normalize to that same identity.

Choose **one** matching entry below only after approval covers these exact inputs and
the fixed marker write. These examples describe the operator action; they do not grant
permission to enroll.

```sh
python3 "$SOURCE/scripts/secret_scan.py" enroll-exact \
  --archive-path "$ARCHIVE" --release-id "$RELEASE_ID" \
  --expected-archive-sha256 "$ARCHIVE_SHA256" \
  --expected-catalog-sha256 "$CATALOG_SHA256" \
  --expected-common-dir "$COMMON_DIR" --expected-origin "$ORIGIN" \
  --authorize-marker-write

python3 "$ARCHIVE" secret_scan.py enroll-exact \
  --archive-path "$ARCHIVE" --release-id "$RELEASE_ID" \
  --expected-archive-sha256 "$ARCHIVE_SHA256" \
  --expected-catalog-sha256 "$CATALOG_SHA256" \
  --expected-common-dir "$COMMON_DIR" --expected-origin "$ORIGIN" \
  --authorize-marker-write

python3 "$INSTALL/scripts/sw-run.py" secret_scan.py enroll-exact \
  --archive-path "$ARCHIVE" --release-id "$RELEASE_ID" \
  --expected-archive-sha256 "$ARCHIVE_SHA256" \
  --expected-catalog-sha256 "$CATALOG_SHA256" \
  --expected-common-dir "$COMMON_DIR" --expected-origin "$ORIGIN" \
  --authorize-marker-write
```

Scanner trust lives at `~/.config/shipwright/secret-scan/trust-v1.json`, using the
operating-system account home, with no consumer configuration or environment override.
The sole repository marker is
`<canonical-common-dir>/shipwright-secret-scan-instance-v1.json`. Its strict JSON schema
contains only `schemaVersion` (`1`) and `instanceNonce`, a random 256-bit nonce also
pinned in the trust record's `repository` alongside `commonDir` and normalized `origin`.
The trust record additionally pins `archivePath`, `releaseId`, `archiveSha256` and
`catalogSha256`. A marker alone never approves a release or occurrence.

The scanner's `secret_scan_exact.py` enforces this through `enroll_exact`,
`read_pending_release_trust`, `read_verified_release` and `_CheckedTrustPaths`.
Enrollment validates the inputs before publication. Checked directory-relative,
no-follow operations create exclusive 0600 temporary files, perform file fsync,
atomic publication and directory fsync for each marker/trust write. Temporary files
are cleaned up; interrupted partial states grant zero exceptions and scans never
finish enrollment. A valid existing marker can be reused. Add `--replace-marker` only
for an explicit replacement authorization; replacement generates a fresh nonce.

Trust directories must be 0700 and trust/marker files 0600, with secure owner, type,
ACL and ancestor checks, including the archive and repository common directory.
Symlinks, unsafe writable ancestors and unvalidated path changes are refused.
The current secure ACL implementation supports Darwin; unsupported platforms or
unavailable secure primitives deny exceptions and refuse enrollment. A shared-volume
location must already satisfy these checks as a separate prerequisite: there is no automatic repair, permission relaxation or scan-time chmod. Restore a trusted install
for integrity failures; do not alter shared-volume security to force acceptance.

Verified source execution requires scanner, helper and detector module bytes to match
the pinned archive members. The complete archive digest and separate catalog digest
must match, and bounded archive validation rejects missing, duplicate, traversing or
tampered members. The catalog is read directly without extraction. Package signatures,
a copied catalog or a consumer setting cannot substitute for these checks.

A missing marker after a fresh clone or ordinary clear/reclone requires explicit reenrollment, even if the directory itself survived. Every new release needs fresh
actual-digest authorization; retaining a valid nonce does not carry release approval
forward. Worktrees sharing the enrolled common directory may qualify, and routine Git
metadata writes need not change eligibility. A deliberate copy or restoration of all checked identity and nonce state by the trusted operator may be a legitimate copy;
this is outside the ordinary clone/reset guarantee, not absolute reset detection.
Changed repository/common-directory, origin, release, archive or catalog identity must
deny exceptions under the old enrollment. Full committed-file and exact-occurrence
checks still apply, so copying a path, editing any source byte or moving a match does
not inherit occurrence approval.

## Fail-closed posture

- Unknown or tampered anchors halt script dispatch.
- Operator trust keys are out-of-band — never sourced from the install root alone.
- Dist trust complements (does not replace) workflow-package trust anchors used for
  signed workflow packs under `.sw/workflows/`.
