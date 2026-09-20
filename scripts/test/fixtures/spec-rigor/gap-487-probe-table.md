---
fixture: gap-487-probe-table
source: planning#1065
unit-id: gap-487-spec-rigor-colon-and-bracket-wraps-treat-ordinar
---

# GAP-487 probe table (golden cases)

Vendored probe rows from GAP-487 (`planning#1065`). Unit tests must use exact `text` strings — paraphrase-only coverage is not success.

```json
{
  "version": 1,
  "rows": [
    {
      "id": "citation-source-not-wrapper",
      "text": "Source: approved specification.",
      "installedMatcherAmbiguity": true,
      "expectAmbiguity": false,
      "rIds": ["R1"]
    },
    {
      "id": "markdown-link-ready-https",
      "text": "[ready](https://example.com)",
      "installedMatcherAmbiguity": true,
      "expectAmbiguity": false,
      "rIds": ["R2"]
    },
    {
      "id": "slash-taxonomy-lowercase-pass",
      "text": "Todo/in progress/verifying/done/blocked/cancelled",
      "installedMatcherAmbiguity": false,
      "expectAmbiguity": false,
      "rIds": ["R3"]
    },
    {
      "id": "named-states-label-taxonomy",
      "text": "Required critical states: Todo/in progress/verifying/done/blocked/cancelled",
      "installedMatcherAmbiguity": true,
      "expectAmbiguity": false,
      "rIds": ["R3"]
    },
    {
      "id": "unfinished-authorization-fail-closed",
      "text": "TODO implement authorization.",
      "installedMatcherAmbiguity": true,
      "expectAmbiguity": true,
      "rIds": ["R4"]
    },
    {
      "id": "resolved-authorization-pass",
      "text": "Authorization is enforced on every request.",
      "installedMatcherAmbiguity": false,
      "expectAmbiguity": false,
      "rIds": ["R4"]
    }
  ]
}
```
