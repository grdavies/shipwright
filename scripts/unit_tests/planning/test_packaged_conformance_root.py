"""PRD 356 phase 1 — D3 packaged conformance root resolution (R1, R2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
repo_root_path = Path(__file__).resolve().parents[3]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from _planning_pkg_loader import load_submodule
from planning_store_facade import resolve_shipped_issues_providers


def _fixture_src(repo_root: Path, slug: str) -> Path:
    return repo_root / "scripts/test/fixtures/planning-provider-conformance" / f"{slug}.ok.json"


def _write_conformance(bundle: Path, slug: str, repo_root: Path, *, verdict: str = "ok") -> None:
    dest_dir = bundle / "core/sw-reference/provider-conformance"
    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(_fixture_src(repo_root, slug).read_text(encoding="utf-8"))
    payload["verdict"] = verdict
    if verdict != "ok":
        payload["dimensions"] = {
            key: {"verdict": "fail", "dimension": key}
            for key in payload.get("dimensions", {})
        }
    (dest_dir / f"{slug}.ok.json").write_text(json.dumps(payload), encoding="utf-8")


def _stage_wheel_layout(tmp_path: Path, repo_root: Path) -> Path:
    return tmp_path / "sw"


def test_active_host_dist_bundle_hit(tmp_path: Path, repo_root: Path) -> None:
    """Active-host dist/<host>/ bundle resolves green conformance (R1)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    _write_conformance(pkg / "dist/codex", "linear", repo_root)

    pc = load_submodule("provider_conformance")
    record = pc.load_conformance_record(
        tmp_path / "consumer",
        "linear",
        package_root=pkg,
        active_host="codex",
    )
    assert record.get("verdict") == "ok"
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )
    assert "linear" in shipped
    assert "linear" in resolve_shipped_issues_providers(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )


def test_sibling_used_only_when_active_absent(tmp_path: Path, repo_root: Path) -> None:
    """Sibling host bundle is consulted only when active-host record is absent (D3)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    (pkg / "dist/codex/core/sw-reference/provider-conformance").mkdir(parents=True)
    _write_conformance(pkg / "dist/cursor", "linear", repo_root)

    pc = load_submodule("provider_conformance")
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )
    assert "linear" in shipped


def test_unknown_host_fail_closed_no_sibling_walk(tmp_path: Path, repo_root: Path) -> None:
    """Undetermined active host fails closed — no silent sibling walk (D3)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    _write_conformance(pkg / "dist/cursor", "linear", repo_root)
    _write_conformance(pkg / "dist/codex", "linear", repo_root)

    pc = load_submodule("provider_conformance")
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host=None,
    )
    assert shipped == frozenset()


def test_package_root_only_layout_yields_empty_shipped_set(tmp_path: Path, repo_root: Path) -> None:
    """core/sw-reference at package root without dist/<host>/ is insufficient (D4 negative)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    _write_conformance(pkg, "linear", repo_root)

    pc = load_submodule("provider_conformance")
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )
    assert shipped == frozenset()
    assert resolve_shipped_issues_providers(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    ) == frozenset()
