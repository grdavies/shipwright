"""PRD 060 R14–R15 harness isolation tests."""

from __future__ import annotations

from pathlib import Path

import harness_isolation_lint as hil
from unit_tests._harness_runtime import FixtureContext


def test_baseline_path_for_is_per_run() -> None:
    ctx = FixtureContext(__file__)
    try:
        p1 = ctx.baseline_path_for("phase-a")
        p2 = ctx.baseline_path_for("phase-b")
        assert p1 != p2
        assert p1.name == "baseline.verify.json"
    finally:
        ctx.cleanup()


def test_shared_config_plus_root_baseline_fails(tmp_path: Path) -> None:
    harness = tmp_path / "scripts/unit_tests/bad.py"
    harness.parent.mkdir(parents=True)
    harness.write_text(
        """
(path / ".cursor/workflow.config.json").write_text("{}")
python3 scripts/verify-baseline.py capture --to .shipwright/baseline.verify.json
""",
        encoding="utf-8",
    )
    hit = hil.scan_file(tmp_path, harness)
    assert hit is not None


def test_read_only_config_backup_passes(tmp_path: Path) -> None:
    harness = tmp_path / "scripts/unit_tests/ok.py"
    harness.parent.mkdir(parents=True)
    harness.write_text(
        """
CFG_BACKUP="$TMP/workflow.config.json.bak"
cp "$ROOT/.cursor/workflow.config.json" "$CFG_BACKUP"
""",
        encoding="utf-8",
    )
    assert hil.scan_file(tmp_path, harness) is None
