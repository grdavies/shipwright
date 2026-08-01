"""PRD 085 R17 — deferred-placeholder lint fixtures."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "deferred_placeholder_lint",
    _SCRIPTS / "deferred-placeholder-lint.py",
)
dpl = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(dpl)


def _run_lint(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/deferred-placeholder-lint.py"), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_tracked_deferral_in_planning_store_facade_passes(repo_root: Path) -> None:
    """planning_store_facade DEFERRED_ISSUES_PROVIDERS block carries PRD + gap reference."""
    path = repo_root / "scripts/planning_store_facade.py"
    violations = dpl.scan_file(repo_root, path, window=3)
    assert violations == []


def test_untracked_deferral_marker_fails(repo_root: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad_module.py"
    bad.write_text(
        """
# credential backends adapter surface — not yet implemented
""",
        encoding="utf-8",
    )
    violations = dpl.scan_text("bad_module.py", bad.read_text(encoding="utf-8"), window=3)
    assert len(violations) == 1
    ec, _ = _run_lint(repo_root, "--check", "--file", str(bad))
    assert ec != 0


def test_tracked_marker_in_fixture_passes(repo_root: Path, tmp_path: Path) -> None:
    good = tmp_path / "good_module.py"
    good.write_text(
        """
# skeleton stage for credential backends — tracked in gap-039 (PRD 057 R7)
""",
        encoding="utf-8",
    )
    violations = dpl.scan_text("good_module.py", good.read_text(encoding="utf-8"), window=3)
    assert violations == []
    ec, _ = _run_lint(repo_root, "--check", "--file", str(good))
    assert ec == 0


def test_repo_scan_passes(repo_root: Path) -> None:
    result = dpl.check(repo_root)
    assert result.get("verdict") == "pass"


def test_window_boundary_tracked_reference(repo_root: Path, tmp_path: Path) -> None:
    """Reference just inside the configured window passes; outside fails."""
    inside = tmp_path / "inside.py"
    inside.write_text(
        "\n".join(
            [
                "# not yet implemented",
                "# gap-039",
            ]
        ),
        encoding="utf-8",
    )
    assert dpl.scan_text("inside.py", inside.read_text(encoding="utf-8"), window=1) == []

    outside = tmp_path / "outside.py"
    outside.write_text(
        "\n".join(
            [
                "# not yet implemented",
                "",
                "",
                "# gap-039",
            ]
        ),
        encoding="utf-8",
    )
    assert len(dpl.scan_text("outside.py", outside.read_text(encoding="utf-8"), window=1)) == 1
