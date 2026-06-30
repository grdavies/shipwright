---
capability:
  version: 1
  triggers:
    - type: any_of
      selectionFamily: code-review
      triggers:
        - type: change_digest
          predicate: path_match
          globs:
            - "commands/**"
            - "core/commands/**"
            - "skills/**"
            - "core/skills/**"
            - "rules/**"
            - "providers/**"
        - type: change_digest
          predicate: regex_in_added_lines
          patterns:
            - "\\b(openai|anthropic|llm|chat\\.completions|untrusted)\\b"
            - "\\b(prompt|agent|subagent|skill)\\b"
  metadata:
    specialistId: ai-native
    selectionFamily: code-review
---

# Code-review specialist — ai-native

Signal-gated native panel specialist (parity with `code-review-select.py`).
