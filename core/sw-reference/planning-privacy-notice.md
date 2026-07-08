# Planning privacy notice (PRD 034 R3, PRD 057 R13/R15)

Your repository origin remote is **public** — or your configured planning store host is
public (PRD 057 R14) — so Shipwright defaults the visibility (redaction) tier to
`all-private` so advisory planning bodies stay out of the tracked git index (or a shared
issue-store host) until you choose otherwise.

Visibility configuration models three orthogonal axes (PRD 057 R13): the visibility
(redaction) **tier**, `storeLocation` (same-repo vs. separate-project), and store-host
privacy (whether the configured issue-store host is private). Each is resolved and
recorded independently; `probe_remote_visibility` is one input, not the sole gate.

Before your first tracked spec commit:

1. Review `planning.visibilityTier` (tier-first rename; the deprecated `visibilityProfile`
   key remains a one-release back-compat alias — new key wins, and a mixed old/new config
   never resolves to a *less private* tier) and per-unit `visibility` in
   `.cursor/workflow.config.json`.
2. Confirm you understand which bodies may appear in PR diffs, or in the configured issue
   store, under your resolved tier.
3. Acknowledge by recording `planning.privacyAck.recordedAt` — run
   `python3 scripts/planning_visibility.py --root . record-privacy-ack` (the exact
   remediation `planning-doctor.py` names for its `privacy-ack-required` finding) to set
   it to the current UTC timestamp.

Spec-class units (`prd`, `tasks`, `amendment`) may still be public under `specs-public`;
under `all-private` every unit defaults private until explicitly marked `public`.

## `privacyAck` keys

| Key | Meaning |
| --- | --- |
| `required` | `true` when a public-origin remote or public store host requires acknowledgement before first tracked/store write. |
| `recordedAt` | ISO-8601 UTC timestamp the operator acknowledged the notice, or `null` if not yet recorded. This is the key `planning_visibility.py` actually writes — an older revision of this notice referred to a since-renamed `ackedAt` key; `recordedAt` is authoritative. |
| `reason` | Why `required` is `true` (for example `public-origin-remote`, `public-store-host`, or both). |

`planning-doctor.py` flags a live config with `privacyAck.required: true` and
`privacyAck.recordedAt: null` as an `action-required` finding naming the exact
remediation command above.
