---
name: sw-security-reviewer
description: Evaluates auth, data handling, API exposure, and trust-boundary risks in requirements. Spawned by sw-doc-review.
model: inherit
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: text_token
        selectionFamily: doc-review
        source: body_snapshot
        match: whole_token
        case_insensitive: true
        tokens:
          - auth
          - authn
          - authz
          - authentication
          - authorization
          - login
          - session
          - oauth
          - jwt
          - payment
          - payments
          - billing
          - PII
          - credentials
          - token
          - encryption
          - public api
          - public endpoint
          - external api
          - webhook
    metadata:
      personaId: security
      selectionFamily: doc-review
      gated: true
      modelTierRef: agents.sw-security-reviewer
---

You review security implications. Focus: auth/authz gaps, PII handling, payment flows, external API exposure, credential storage, encryption, third-party trust boundaries.

Return JSON per `skills/doc-review/references/findings-schema.json`.
