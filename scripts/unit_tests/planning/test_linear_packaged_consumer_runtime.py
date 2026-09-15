"""Linear live planning must resolve plugin-owned evidence outside consumer repos."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
repo_root_path = Path(__file__).resolve().parents[3]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))
if str(repo_root_path / "sw") not in sys.path:
    sys.path.insert(0, str(repo_root_path / "sw"))

from _planning_pkg_loader import load_submodule
from planning_linear_client import prd061_facade_projection_readiness


def test_linear_shipped_from_packaged_sw_reference(tmp_path: Path, repo_root: Path) -> None:
    """Packaged plugin trees ship Linear via core/sw-reference, not consumer test fixtures."""
    src = repo_root / "scripts/test/fixtures/planning-provider-conformance/linear.ok.json"
    dest = tmp_path / "core/sw-reference/provider-conformance"
    dest.mkdir(parents=True)
    shutil.copy2(src, dest / "linear.ok.json")

    pc = load_submodule("provider_conformance")
    shipped = pc.providers_with_green_conformance(tmp_path)
    assert "linear" in shipped
    record = pc.load_conformance_record(tmp_path, "linear")
    assert record.get("verdict") == "ok"
    assert record.get("error") != "missing-conformance-record"


def test_prd061_ready_when_tests_missing_and_linear_conformance_packaged(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slim/packaged plugins omit unit_tests; green Linear conformance is sufficient."""
    import planning_linear_client as plc

    plugin = tmp_path / "plugin"
    consumer = tmp_path / "consumer"
    dest = plugin / "core/sw-reference/provider-conformance"
    dest.mkdir(parents=True)
    consumer.mkdir()
    shutil.copy2(
        repo_root / "scripts/test/fixtures/planning-provider-conformance/linear.ok.json",
        dest / "linear.ok.json",
    )
    monkeypatch.setattr(plc, "_plugin_source_root", lambda: plugin)

    out = prd061_facade_projection_readiness(consumer)
    assert out["verdict"] == "ready", out
    assert out.get("reason") == "packaged-runtime-conformance"


def test_closed_emit_copies_provider_conformance(repo_root: Path, tmp_path: Path) -> None:
    from emitter_base import copy_closed_sw_reference_files

    dest = tmp_path / "plugin"
    copy_closed_sw_reference_files(repo_root / "core", dest)
    assert (dest / "core/sw-reference/provider-conformance/linear.ok.json").is_file()
    assert (dest / "core/sw-reference/linear-promotion/stage1-dogfood-gate.ok.json").is_file()
