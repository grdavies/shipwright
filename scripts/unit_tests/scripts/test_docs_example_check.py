"""Unit tests for docs_example_check (PRD 345 R18–R20)."""
from __future__ import annotations

from pathlib import Path

import docs_example_check


def test_passes_clean_sw_run_examples(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text(
        '```bash\n'
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" wave_deliver.py -- --help\n'
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" wave_deliver.py list\n'
        "```\n",
        encoding="utf-8",
    )
    result = docs_example_check.run_check(root=tmp_path)
    assert result["verdict"] == "pass"
    assert result["findings"] == []


def test_detects_dot_concatenation(tmp_path: Path) -> None:
    doc = tmp_path / "core" / "documentation" / "commands.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        '```bash\n'
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" wave_deliver.py. list\n'
        "```\n",
        encoding="utf-8",
    )
    result = docs_example_check.run_check(root=tmp_path)
    assert result["verdict"] == "malformed-examples"
    assert any("concatenated helper name" in f["reason"] for f in result["findings"])


def test_detects_angle_placeholder_concatenation(tmp_path: Path) -> None:
    doc = tmp_path / "core" / "documentation" / "commands.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        '```bash\n'
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" wave_deliver.py<repo> explain-plan\n'
        "```\n",
        encoding="utf-8",
    )
    result = docs_example_check.run_check(root=tmp_path)
    assert result["verdict"] == "malformed-examples"
    assert any("placeholder" in f["reason"] for f in result["findings"])


def test_detects_invalid_wave_deliver_help(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text(
        '```bash\n'
        'python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" wave_deliver.py --help\n'
        "```\n",
        encoding="utf-8",
    )
    result = docs_example_check.run_check(root=tmp_path)
    assert result["verdict"] == "malformed-examples"
    assert any("passthrough" in f["reason"] for f in result["findings"])
