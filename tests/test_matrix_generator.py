"""PRD 349 R46–R48 / TS9 — support matrix generator from tested conformance records."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "matrix_generator.py"
FIXTURES = REPO / "tests" / "fixtures" / "conformance_records"


def _run(records_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GEN), "--records", str(records_dir), *extra],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_full_tested_records_all_four_levels(tmp_path: Path) -> None:
    src = FIXTURES / "full"
    out = tmp_path / "matrix.md"
    proc = _run(src, "--format", "markdown", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    text = out.read_text(encoding="utf-8")
    assert "controls_verified" in text
    assert "codex" in text.lower() or "Codex" in text
    assert "cli" in text.lower()
    # four distinct levels must be representable in generator vocabulary
    for level in ("generated", "loads", "passes", "controls_verified"):
        assert level in (GEN.read_text(encoding="utf-8"))


def test_generated_only_records_show_generated(tmp_path: Path) -> None:
    src = FIXTURES / "generated_only"
    out = tmp_path / "matrix.json"
    proc = _run(src, "--format", "json", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    cells = json.loads(out.read_text(encoding="utf-8"))["cells"]
    assert len(cells) == 1
    assert cells[0]["level"] == "generated"
    assert cells[0]["host"] == "opencode"


def test_missing_tested_at_rejects_nonzero() -> None:
    src = FIXTURES / "missing_tested_at"
    proc = _run(src, "--format", "json")
    assert proc.returncode != 0
    assert "tested_at" in (proc.stderr + proc.stdout).lower()


def test_cli_tested_does_not_imply_desktop(tmp_path: Path) -> None:
    """R48 — CLI surface tested must not propagate to desktop cell."""
    records = tmp_path / "records"
    records.mkdir()
    (records / "cli.json").write_text(
        json.dumps(
            {
                "host": "codex",
                "surface": "cli",
                "host_version": "0.42.0",
                "capability": "emit_hook",
                "level": "passes",
                "tested_at": "2026-09-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    out_json = tmp_path / "matrix.json"
    proc = _run(records, "--format", "json", "--out", str(out_json))
    assert proc.returncode == 0, proc.stderr
    matrix = json.loads(out_json.read_text(encoding="utf-8"))
    cells = matrix["cells"] if isinstance(matrix, dict) else matrix
    cli = [
        c
        for c in cells
        if c["host"] == "codex" and c["surface"] == "cli" and c["capability"] == "emit_hook"
    ]
    desktop = [
        c
        for c in cells
        if c["host"] == "codex" and c["surface"] == "desktop" and c["capability"] == "emit_hook"
    ]
    assert cli and cli[0]["level"] == "passes"
    assert not desktop or desktop[0].get("level") in (None, "untested", "")


def test_host_version_and_surface_required_on_rows(tmp_path: Path) -> None:
    src = FIXTURES / "full"
    out = tmp_path / "matrix.json"
    proc = _run(src, "--format", "json", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    for cell in payload["cells"]:
        assert cell.get("host_version")
        assert cell.get("surface") in {"cli", "desktop", "cloud"}
