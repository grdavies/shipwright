"""PRD 352 R27 — phase-1 pin tests must be discoverable."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_prd352_phase1_pins_are_discoverable() -> None:
    required = [
        REPO / ".github/workflows/packaged-install.yml",
        REPO / "scripts/unit_tests/install/test_prd349_unified_installer.py",
        REPO / "tests/unit/test_wave_journal_capture.py",
        REPO / "tests/unit/test_prd352_guardrail_matrix_goldens.py",
        REPO / "tests/integration/test_model_policy_advisory.py",
        REPO / "tests/fixtures/guardrail-matrix/session-start.claude.expected.json",
    ]
    missing = [str(p.relative_to(REPO)) for p in required if not p.is_file()]
    assert not missing, f"phase-1 pin artifacts missing: {missing}"

    wf = (REPO / ".github/workflows/packaged-install.yml").read_text(encoding="utf-8")
    assert "PRD 352 R3" in wf

    inst = (REPO / "scripts/unit_tests/install/test_prd349_unified_installer.py").read_text(encoding="utf-8")
    assert "prd352_r9" in inst

    j = (REPO / "tests/unit/test_wave_journal_capture.py").read_text(encoding="utf-8")
    assert "prd352_r13" in j

    adv = (REPO / "tests/integration/test_model_policy_advisory.py").read_text(encoding="utf-8")
    assert "prd352_r26" in adv
