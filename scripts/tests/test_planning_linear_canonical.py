"""PRD 066 phase 7 — linear canonical Public Markdown tests (task path alias).

Canonical suite: scripts/unit_tests/planning/test_prd066_linear_canonical.py
"""

from __future__ import annotations

from unit_tests.planning.test_prd066_linear_canonical import (  # noqa: F401
    test_r15_cli_normalize_fixture,
    test_r15_cli_rejects_internal_contract,
    test_r15_collapsible_whitespace_normalized,
    test_r15_content_data_not_adapter_complete,
    test_r15_content_state_not_adapter_complete,
    test_r15_golden_public_markdown_round_trip,
    test_r15_html_details_rejected,
    test_r15_mention_link_normalizes_to_bare_url,
)
