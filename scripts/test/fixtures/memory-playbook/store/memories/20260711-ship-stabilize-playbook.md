---
category: playbook
id: 20260711-ship-stabilize-playbook
tags: [prd-064, surface:stabilize]
relatedFiles: [scripts/check-gate.py]
importance: 0.7
scope: project
links: []
title: Ship stabilize loop
description: Stabilize failing CI checks
triggerKeywords: [stabilize, sw-stabilize, ci]
prerequisites: [open PR with failing checks]
confidence: 0.8
usage_count: 6
success_count: 5
playbookStatus: active
auditTelemetryRef: scripts/test/fixtures/memory-playbook/claims-audit-pass.json
skepticVerdict: pass
createdAt: 2026-07-11T12:00:00Z
---
# Prerequisites

- open PR with failing checks

# Steps

## Step 1: Run gate
- command: `python3 scripts/check-gate.py`
- expected: JSON verdict on stdout
- fallback: inspect host checks manually

# Verification

- check-gate returns green or actionable red
