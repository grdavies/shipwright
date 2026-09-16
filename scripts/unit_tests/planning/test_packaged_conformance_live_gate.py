"""PRD 356 phase 2 — live gating without import-time freeze (R3, R7)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_lib
import planning_linear_client as plc
import planning_store as ps
import planning_store_facade as ps_facade


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


def _linear_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": "planning",
                "issues": {
                    "tokenEnv": "ISSUES_LINEAR_TOKEN",
                    "teamKey": "ENG",
                    "teamId": "team_ENG",
                    "authMode": "api-key",
                },
                "operatorProjection": {
                    "githubProjects": {"enabled": False},
                    "linear": {"enabled": True},
                },
            }
        },
        "host": {"provider": "github"},
    }


def test_wrong_root_lookup_empty_live_resolve_finds_linear(tmp_path: Path, repo_root: Path) -> None:
    """Packaged conformance only under D3 dist bundle — wrong-root lookup is empty (R3)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    pkg = tmp_path / "sw"
    _write_conformance(pkg / "dist/codex", "linear", repo_root)

    wrong_root_shipped = ps_facade.shipped_issues_providers(consumer)
    assert "linear" not in wrong_root_shipped

    live_shipped = ps_facade.shipped_issues_providers(
        consumer,
        package_root=pkg,
        active_host="codex",
    )
    assert "linear" in live_shipped


def test_import_time_view_does_not_bypass_live_resolve(tmp_path: Path, repo_root: Path) -> None:
    """Import-compat view cannot bypass live resolve for packaged consumer roots (R7)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    pkg = tmp_path / "sw"
    _write_conformance(pkg / "dist/codex", "linear", repo_root)

    ps_facade.clear_shipped_providers_cache()
    assert "linear" not in ps_facade.shipped_issues_providers(consumer)
    assert "linear" in ps_facade.shipped_issues_providers(
        consumer,
        package_root=pkg,
        active_host="codex",
    )


def test_linear_live_backend_not_refused_when_d3_finds_conformance(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linear proceeds when D3 finds conformance — no recognized-not-shipped refuse (R3)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    pkg = tmp_path / "sw"
    host_bundle = pkg / "dist/codex"
    _write_conformance(host_bundle, "linear", repo_root)
    monkeypatch.setenv("CODEX_PLUGIN_ROOT", str(host_bundle))

    store = issues_lib.FixtureIssuesStore(consumer / "linear-fixture.json")

    class _FakeLinear(plc.LinearIssuesClient):
        def __init__(self, root: Path, **kwargs: Any) -> None:  # noqa: ARG002
            super().__init__(root, cfg=_linear_cfg()["planning"]["store"], fixture_store=store)

    monkeypatch.setattr(plc, "LinearIssuesClient", _FakeLinear)
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)

    client = issues_lib.IssuesClient(consumer, "linear")
    backend = client._live_backend()
    assert backend is not None

    reason = ps.issue_store_fallback_reason(consumer, _linear_cfg())
    assert reason != "issues-provider-not-shipped"

    doctor = ps.doctor_issues_provider_stub(consumer, _linear_cfg())
    assert doctor["verdict"] == "pass"
    assert doctor.get("notice") != "linear-recognized-not-shipped"


def test_present_and_fail_active_host_blocks_live_selection(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """Present-and-fail active-host evidence blocks live selection — no sibling override (R7)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    pkg = tmp_path / "sw"
    _write_conformance(pkg / "dist/codex", "linear", repo_root, verdict="fail")
    _write_conformance(pkg / "dist/cursor", "linear", repo_root, verdict="ok")

    shipped = ps_facade.shipped_issues_providers(
        consumer,
        package_root=pkg,
        active_host="codex",
    )
    assert "linear" not in shipped


def test_no_active_host_consumer_without_vendored_tests_constructs_linear(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Packaged consumer tree has no unit_tests and keeps consumer credential refs (PRD 357 R4/R5)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    assert not (consumer / "scripts" / "unit_tests").exists()
    pkg = tmp_path / "sw"
    _write_conformance(pkg / "dist/cursor", "linear", repo_root)

    shipped = ps_facade.shipped_issues_providers(
        consumer,
        package_root=pkg,
        active_host=None,
    )
    assert "linear" in shipped

    monkeypatch.setattr(plc, "_plugin_source_root", lambda: pkg)
    gate = plc.prd061_facade_projection_readiness(consumer)
    assert gate.get("verdict") == "ready"
    assert gate.get("reason") == "packaged-runtime-conformance"

    store = issues_lib.FixtureIssuesStore(consumer / "linear-fixture.json")
    cfg = _linear_cfg()
    client = plc.LinearIssuesClient(consumer, cfg=cfg["planning"]["store"], fixture_store=store)
    assert client is not None
    assert cfg["planning"]["store"]["issues"]["teamKey"] == "ENG"
    assert cfg["planning"]["store"]["issues"]["tokenEnv"] == "ISSUES_LINEAR_TOKEN"
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
