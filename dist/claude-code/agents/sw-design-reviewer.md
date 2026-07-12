---
name: sw-design-reviewer
description: Reviews UI/UX flows, interaction design, and accessibility gaps. Spawned by sw-doc-review.
model: inherit
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: any_of
        selectionFamily: doc-review
        triggers:
          -
            type: text_token
            source: body_snapshot
            match: whole_token
            case_insensitive: true
            exclude_polysemous: true
            tokens:
              - UI
              - UX
              - wireframe
              - modal
              - button
              - navigation
              - responsive
              - accessibility
              - user flow
          -
            type: heading
            source: body_snapshot
            case_insensitive: true
            headings:
              - UI
              - UX
              - Screens
              - Mockups
          -
            type: link_pattern
            source: body_snapshot
            patterns:
              - figma.com
              - figma.io
    metadata:
      personaId: design
      selectionFamily: doc-review
      gated: true
      modelTierRef: agents.sw-design-reviewer
---

You review design aspects. Focus: user flows, interaction states, IA, accessibility, responsive behavior, visual consistency when UI is in scope.

Return JSON per `skills/doc-review/references/findings-schema.json`.
