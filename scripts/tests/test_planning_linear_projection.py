"""PRD 066 — Linear projection suites (task path alias).

Canonical suites:
- scripts/unit_tests/planning/test_prd066_linear_projection_schema.py (phase 5 / R6–R8, R29)
- scripts/unit_tests/planning/test_prd066_dual_write_body.py (phase 6 / R26)
- scripts/unit_tests/planning/test_prd066_projects_parity.py (phase 9 / R18–R19)
"""

from __future__ import annotations

from unit_tests.planning.test_prd066_dual_write_body import (  # noqa: F401
    test_r26_document_backed_body_is_freeze_hash_sot,
    test_r26_facade_exports_and_schema_policy_surface,
    test_r26_fail_closed_projection_prefer_split_brain,
    test_r26_fail_closed_unresolved_canonical_body,
    test_r26_lcd_issue_body_is_freeze_hash_sot,
    test_r26_typed_drift_when_projection_body_diverges,
)
from unit_tests.planning.test_prd066_linear_projection_schema import (  # noqa: F401
    test_linear_projection_schema_contract_surface,
    test_r29_endpoint_typed_edge_encoding,
    test_r6_entity_mapping_prd_document_gap_milestone_issue,
    test_r7_initiative_probe_and_substitute_views,
    test_r8_cycles_orthogonal_to_milestones_and_share_notice,
)
from unit_tests.planning.test_prd066_projects_parity import (  # noqa: F401
    test_r18_assert_helper_fails_without_discriminator,
    test_r18_initiative_cycle_degradations_documented,
    test_r18_program_field_discriminator_makes_r1_green,
    test_r18_project_per_program_discriminator,
    test_r18_status_only_is_not_r1_4_complete,
    test_r19_issues_remain_body_store,
)
