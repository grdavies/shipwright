# Self-upgrade and release assets

Packaged Shipwright upgrades resolve artifacts from the **distribution origin** recorded in the
installed distribution stamp — not from a hard-coded URL. A successful `shipwright self upgrade`
requires two release assets on that origin:

| Asset | Purpose |
| --- | --- |
| `shipwright-<version>.pyz` | Versioned scripts zipapp |
| `shipwright-distribution-stamp.json` | Release version, origin, and zipapp integrity digest |

The maintainer release pipeline builds and verifies these assets before a tag is published (see the
Shipwright source repository release workflow — not part of the install-root consumer surface).

## When assets are missing

If a GitHub release (or other origin) exists but the zipapp or stamp asset has not been published
yet:

- `shipwright self check` reports the available release version but sets `assetsAvailable: false`
  and explains that upgrade is blocked until the assets appear.
- `shipwright self upgrade` refuses with status `missing-assets` and names which files are absent.
  This is expected during rollout windows before the release job finishes uploading artifacts.

## Packaged provider conformance (PRD 356)

Installed wheels ship issues-provider conformance evidence under host bundles, not only at the
package root:

```text
dist/<host>/core/sw-reference/provider-conformance/<provider>.ok.json
```

Runtime resolution (D3) searches the **active** host bundle first (`scripts/planning/packaged_conformance_roots.py`).
Sibling `dist/<host>/` trees are used only when the active-host record is **absent** — never when
present-and-fail. Staging `core/sw-reference/provider-conformance/` at the package root alone does not
satisfy packaged installs.

Live planning and issue-store gating resolve the shipped provider set on each call (root-keyed cache in
`planning_store_facade.py`) — not a one-time import from the wrong package root.

After `shipwright init` or reinstall, existing operator config under any D5 candidate
(`.shipwright/workflow.config.json`, legacy `.cursor/workflow.config.json`, or repo-root
`workflow.config.json`) is **preserved** (skip-overwrite). Greenfield repos still receive scaffold once.
See [Configuration](configuration.md#packaged-provider-conformance-and-config-preserve-prd-356).

`self check` remains **degraded** (not "up to date") when the distribution origin itself is
unreachable. Missing assets on an otherwise reachable release are a separate, explicit condition —
the check can still resolve the tag while upgrade stays blocked.

## Integrity and corruption

When assets are present, `self upgrade` downloads the zipapp and stamp, verifies the SHA-256 digest
recorded in the stamp, and refuses on mismatch. Refusal messages name **corruption in transit or on
disk** — the marker does not assert authenticity or tamper detection. See
[Getting started](getting-started.md#integrity-threat-model-same-words-the-code-reports) for the
full threat model.

## Operator recovery

1. Run `shipwright self check` and read `assetsAvailable`, `availableVersion`, and `message`.
2. If assets are missing, wait for the maintainer release job or install from a checkout using the
   contributor path in [Getting started](getting-started.md).
3. If integrity fails, delete the partial download under your install `dist/` tree and retry after
   confirming the upstream release publishes both the zipapp and distribution stamp on the
   distribution origin.
