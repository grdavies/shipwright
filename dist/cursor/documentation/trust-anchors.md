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

## Fail-closed posture

- Unknown or tampered anchors halt script dispatch.
- Operator trust keys are out-of-band — never sourced from the install root alone.
- Dist trust complements (does not replace) workflow-package trust anchors used for
  signed workflow packs under `.sw/workflows/`.
