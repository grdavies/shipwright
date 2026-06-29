# Planning privacy notice (PRD 034 R3)

Your repository origin remote is **public**. Shipwright defaults to the `all-private` visibility
profile so advisory planning bodies stay out of the tracked git index until you choose otherwise.

Before your first tracked spec commit:

1. Review `planning.visibilityProfile` and per-unit `visibility` in `.cursor/workflow.config.json`.
2. Confirm you understand which bodies may appear in PR diffs under your profile.
3. Acknowledge by setting `planning.privacyAck.ackedAt` to an ISO-8601 timestamp after review.

Spec-class units (`prd`, `tasks`, `amendment`) may still be public under `specs-public`; under
`all-private` every unit defaults private until explicitly marked `public`.
