"""PRD 349 TS10 — platform portability suite ordering in check-gate."""

from __future__ import annotations

from pathlib import Path

from check_gate_lib import platform_portability_suite_steps


def test_platform_portability_suite_order() -> None:
    root = Path(__file__).resolve().parents[2]
    names = [name for name, _argv in platform_portability_suite_steps(root)]
    assert names == [
        "validate_bundle_self_test",
        "phase1_native_conformance",
        "phase3_portability_traps",
        "phase4_continuation_smoke",
        "phase4_concurrent_resume_guard",
        "phase4_mcp_integration",
        "support_matrix_generator",
    ]


def test_support_matrix_step_points_at_conformance_records() -> None:
    root = Path(__file__).resolve().parents[2]
    steps = dict(platform_portability_suite_steps(root))
    argv = steps["support_matrix_generator"]
    assert "matrix_generator.py" in argv[1]
    assert "--records" in argv
    records = argv[argv.index("--records") + 1]
    assert records.endswith("core/schemas/capabilities/conformance")
