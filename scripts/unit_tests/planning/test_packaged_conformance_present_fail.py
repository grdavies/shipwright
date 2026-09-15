"""PRD 356 phase 1 — present-and-fail active-host conformance (R7)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


def test_present_and_fail_active_host_blocks_sibling_green(tmp_path: Path, repo_root: Path) -> None:
    """Present-and-fail on active host must not fall through to sibling green (R7)."""
    pkg = tmp_path / "sw"
    _write_conformance(pkg / "dist/codex", "linear", repo_root, verdict="fail")
    _write_conformance(pkg / "dist/cursor", "linear", repo_root, verdict="ok")

    pc = load_submodule("provider_conformance")
    record = pc.load_conformance_record(
        tmp_path / "consumer",
        "linear",
        package_root=pkg,
        active_host="codex",
    )
    assert record.get("verdict") == "fail"
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )
    assert "linear" not in shipped
    assert "linear" not in resolve_shipped_issues_providers(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )


def test_corrupt_active_host_record_stays_fail_closed(tmp_path: Path, repo_root: Path) -> None:
    """Corrupt active-host evidence remains fail-closed without sibling override (R7)."""
    pkg = tmp_path / "sw"
    corrupt_dir = pkg / "dist/codex/core/sw-reference/provider-conformance"
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "linear.ok.json").write_text("{not-json", encoding="utf-8")
    _write_conformance(pkg / "dist/cursor", "linear", repo_root, verdict="ok")

    pc = load_submodule("provider_conformance")
    record = pc.load_conformance_record(
        tmp_path / "consumer",
        "linear",
        package_root=pkg,
        active_host="codex",
    )
    assert record.get("verdict") == "fail"
    assert record.get("error") == "invalid-conformance-record"
    shipped = pc.providers_with_green_conformance(
        tmp_path / "consumer",
        package_root=pkg,
        active_host="codex",
    )
    assert "linear" not in shipped
