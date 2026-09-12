"""PRD 348 R5/R6 — layout dual-home byte-identity fixtures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from layout_sync_check import (  # noqa: E402
    EXIT_FAIL,
    EXIT_PASS,
    check_layout_sync,
)

IDENTICAL_BODY = b"# Shipwright artifact layout\n\nboth homes share these bytes.\n"
DIVERGENT_CORE = b"# Shipwright artifact layout\n\ncore mirror drifted.\n"


def _write_pair(root: Path, *, legacy: bytes | None, core: bytes | None) -> None:
    if legacy is not None:
        path = root / ".sw" / "layout.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(legacy)
    if core is not None:
        path = root / "core" / "sw-reference" / "layout.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(core)


def test_byte_identical_pair_passes(tmp_path: Path) -> None:
    _write_pair(tmp_path, legacy=IDENTICAL_BODY, core=IDENTICAL_BODY)
    result = check_layout_sync(tmp_path)
    assert result.verdict == "pass"
    assert result.reason == "byte-identical"
    assert result.checked == [".sw/layout.md", "core/sw-reference/layout.md"]
    assert result.missing == []
    assert result.diagnostic is None


def test_byte_divergent_pair_fails_with_both_paths(tmp_path: Path) -> None:
    _write_pair(tmp_path, legacy=IDENTICAL_BODY, core=DIVERGENT_CORE)
    result = check_layout_sync(tmp_path)
    assert result.verdict == "fail"
    assert result.reason == "byte-divergent"
    assert result.checked == [".sw/layout.md", "core/sw-reference/layout.md"]
    assert result.diagnostic is not None
    assert ".sw/layout.md" in result.diagnostic
    assert "core/sw-reference/layout.md" in result.diagnostic


def test_neither_present_skips_pass(tmp_path: Path) -> None:
    result = check_layout_sync(tmp_path)
    assert result.verdict == "pass"
    assert result.reason == "neither-layout-present"
    assert result.checked == []
    assert ".sw/layout.md" in result.missing
    assert "core/sw-reference/layout.md" in result.missing


def test_one_sided_pair_fails(tmp_path: Path) -> None:
    _write_pair(tmp_path, legacy=IDENTICAL_BODY, core=None)
    result = check_layout_sync(tmp_path)
    assert result.verdict == "fail"
    assert result.reason == "one-sided-layout-pair"
    assert result.checked == [".sw/layout.md"]
    assert result.missing == ["core/sw-reference/layout.md"]
    assert result.diagnostic is not None
    assert ".sw/layout.md" in result.diagnostic
    assert "core/sw-reference/layout.md" in result.diagnostic


def test_cli_pass_and_fail_exit_codes(tmp_path: Path) -> None:
    script = SCRIPT_DIR / "layout_sync_check.py"
    _write_pair(tmp_path, legacy=IDENTICAL_BODY, core=IDENTICAL_BODY)
    ok = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == EXIT_PASS
    assert "byte-identical" in ok.stdout or "ok" in ok.stdout

    _write_pair(tmp_path, legacy=IDENTICAL_BODY, core=DIVERGENT_CORE)
    bad = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == EXIT_FAIL
    assert ".sw/layout.md" in bad.stderr
    assert "core/sw-reference/layout.md" in bad.stderr


@pytest.mark.parametrize(
    ("legacy", "core"),
    [
        (IDENTICAL_BODY, IDENTICAL_BODY + b"\n"),
        (b"", IDENTICAL_BODY),
        (IDENTICAL_BODY, b""),
    ],
)
def test_any_byte_difference_fails(
    tmp_path: Path, legacy: bytes, core: bytes
) -> None:
    _write_pair(tmp_path, legacy=legacy, core=core)
    result = check_layout_sync(tmp_path)
    assert result.verdict == "fail"
    assert result.reason == "byte-divergent"
