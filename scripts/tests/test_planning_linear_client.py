"""PRD 066 phase 3 — linear client tests (task path alias).

Canonical suite: scripts/unit_tests/planning/test_prd066_linear_client_auth_budget.py
"""

from __future__ import annotations

from unit_tests.planning.test_prd066_linear_client_auth_budget import (  # noqa: F401
    test_r9_live_client_present_before_issues_providers_recognition,
    test_r11_missing_both_team_keys_fails_closed,
    test_r11_team_probe_mismatch_fails,
    test_r11_team_probe_success,
    test_r13_dual_budget_tracks_count_and_complexity,
    test_r13_ratelimited_graphql_extension_handled,
    test_r13_complexity_aware_query_planner_splits,
    test_r14_bare_issues_array_batch_footgun_blocked,
    test_r23_oauth_auth_mode_header_only,
    test_r23_doctor_refuses_shared_ci_oauth_without_exception,
)
