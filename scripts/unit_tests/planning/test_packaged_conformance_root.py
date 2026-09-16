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


def test_no_active_host_dist_bundle_constructs_linear_client(tmp_path: Path, repo_root: Path) -> None:
    """No-active-host wheel with green evidence only under dist/<host>/ (PRD 357 R2)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    _write_conformance(pkg / "dist/cursor", "linear", repo_root)

    pc = load_submodule("provider_conformance")
    record = pc.load_conformance_record(
        tmp_path / "consumer",
        "linear",
        package_root=pkg,
        active_host=None,
    )
    assert record.get("verdict") == "ok"
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host=None,
    )
    assert "linear" in shipped
    assert "linear" in resolve_shipped_issues_providers(
        tmp_path / "consumer",
        package_root=pkg,
        active_host=None,
    )


def test_no_active_host_present_fail_blocks_later_host_green(tmp_path: Path, repo_root: Path) -> None:
    """Host A present-and-fail must not fall through to host B green (PRD 357 R3)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    _write_conformance(pkg / "dist/cursor", "linear", repo_root, verdict="fail")
    _write_conformance(pkg / "dist/claude-code", "linear", repo_root, verdict="ok")

    pc = load_submodule("provider_conformance")
    record = pc.load_conformance_record(
        tmp_path / "consumer",
        "linear",
        package_root=pkg,
        active_host=None,
    )
    assert record.get("verdict") == "fail"
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host=None,
    )
    assert "linear" not in shipped


def test_missing_record_names_searched_roots_and_recovery(tmp_path: Path, repo_root: Path) -> None:
    """Missing evidence names searched roots and the recovery action (PRD 357 R3)."""
    pkg = _stage_wheel_layout(tmp_path, repo_root)
    (pkg / "dist/cursor").mkdir(parents=True)

    pc = load_submodule("provider_conformance")
    record = pc.load_conformance_record(
        tmp_path / "consumer",
        "linear",
        package_root=pkg,
        active_host=None,
    )
    assert record.get("verdict") == "fail"
    assert record.get("error") == "missing-conformance-record"
    roots = record.get("searchedRoots") or []
    assert any("dist/cursor" in str(item) for item in roots)
    assert "Upgrade or rebuild Shipwright" in str(record.get("recoveryAction") or "")
    assert "Do not copy Shipwright tests" in str(record.get("recoveryAction") or "")
    jira = pc.load_conformance_record(
        tmp_path / "consumer",
        "jira",
        package_root=pkg,
        active_host=None,
    )
    assert jira.get("error") == "missing-conformance-record"
    assert "Linear" not in str(jira.get("recoveryAction") or "")
    assert "retarget" not in str(jira.get("recoveryAction") or "").lower()


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
