"""PRD 356 phase 3 — packaged consumer fixture and CI test (R3, R4)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
repo_root_path = Path(__file__).resolve().parents[3]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_lib
import planning_linear_client as plc
import planning_store as ps
import planning_store_facade as ps_facade


def _fixture_root(repo_root: Path) -> Path:
    return repo_root / "scripts/test/fixtures/packaged-provider-conformance"


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


def _stage_wheel_tree(tmp_path: Path, repo_root: Path, *, layout: str) -> tuple[Path, Path]:
    """Stage site-packages/sw layout; return (scripts_dir, package_root)."""
    pkg = tmp_path / "site-packages" / "sw"
    scripts_dir = pkg / "scripts"
    shutil.copytree(repo_root / "scripts", scripts_dir)
    if layout == "d4":
        shutil.copytree(_fixture_root(repo_root) / "dist", pkg / "dist")
    else:
        shutil.copytree(_fixture_root(repo_root) / "wrong-root-only", pkg, dirs_exist_ok=True)
    return scripts_dir, pkg


def _packaged_subprocess_env(
    *,
    staged_scripts: Path,
    consumer: Path,
    host_bundle: Path,
    repo_root: Path,
) -> dict[str, str]:
    pythonpath_parts = [str(staged_scripts.resolve())]
    repo_scripts = str((repo_root / "scripts").resolve())
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "PYTHONPATH" or repo_scripts not in value
    }
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env["CODEX_PLUGIN_ROOT"] = str(host_bundle.resolve())
    env.pop("SW_ISSUES_FIXTURE", None)
    return env


def _run_packaged_probe(
    consumer: Path,
    pkg: Path,
    staged_scripts: Path,
    repo_root: Path,
    *,
    active_host: str = "codex",
) -> dict[str, Any]:
    code = textwrap.dedent(
        f"""
        import json
        from pathlib import Path
        import planning_store_facade as psf
        consumer = Path({json.dumps(str(consumer))})
        pkg = Path({json.dumps(str(pkg))})
        shipped = psf.shipped_issues_providers(
            consumer,
            package_root=pkg,
            active_host={json.dumps(active_host)},
        )
        print(json.dumps({{"shipped": sorted(shipped)}}))
        """
    )
    env = _packaged_subprocess_env(
        staged_scripts=staged_scripts,
        consumer=consumer,
        host_bundle=pkg / "dist" / active_host,
        repo_root=repo_root,
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(consumer),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout.strip())


def test_wrong_root_only_layout_empty_shipped_set(tmp_path: Path, repo_root: Path) -> None:
    """Package-root-only conformance layout is insufficient — shipped set stays empty (D4 negative)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    staged_scripts, pkg = _stage_wheel_tree(tmp_path, repo_root, layout="wrong-root-only")

    payload = _run_packaged_probe(consumer, pkg, staged_scripts, repo_root, active_host="codex")
    assert payload["shipped"] == []


def test_packaged_consumer_linear_in_shipped_set_subprocess(
    tmp_path: Path, repo_root: Path
) -> None:
    """Packaged D4 layout resolves Linear without Shipwright source tree on PYTHONPATH (R4)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    staged_scripts, pkg = _stage_wheel_tree(tmp_path, repo_root, layout="d4")

    payload = _run_packaged_probe(consumer, pkg, staged_scripts, repo_root)
    assert "linear" in payload["shipped"]


def test_packaged_consumer_planning_discovery_path(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planning discovery proceeds when D4 packaged conformance finds Linear (R4)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _, pkg = _stage_wheel_tree(tmp_path, repo_root, layout="d4")
    host_bundle = pkg / "dist/codex"
    monkeypatch.setenv("CODEX_PLUGIN_ROOT", str(host_bundle.resolve()))

    store = issues_lib.FixtureIssuesStore(consumer / "linear-fixture.json")

    class _FakeLinear(plc.LinearIssuesClient):
        def __init__(self, root: Path, **kwargs: Any) -> None:  # noqa: ARG002
            super().__init__(root, cfg=_linear_cfg()["planning"]["store"], fixture_store=store)

    monkeypatch.setattr(plc, "LinearIssuesClient", _FakeLinear)
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
    ps_facade.clear_shipped_providers_cache()

    client = issues_lib.IssuesClient(consumer, "linear")
    backend = client._live_backend()
    assert backend is not None

    reason = ps.issue_store_fallback_reason(consumer, _linear_cfg())
    assert reason != "issues-provider-not-shipped"

    doctor = ps.doctor_issues_provider_stub(consumer, _linear_cfg())
    assert doctor["verdict"] == "pass"
    assert doctor.get("notice") != "linear-recognized-not-shipped"


def test_gitignore_generate_write_with_packaged_linear(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gitignore-generate --write shares live-backend gating under packaged resolution (R3, R4)."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=consumer, check=True)
    cursor = consumer / ".cursor"
    cursor.mkdir()
    (cursor / "workflow.config.json").write_text(
        json.dumps(_linear_cfg()) + "\n",
        encoding="utf-8",
    )

    staged_scripts, pkg = _stage_wheel_tree(tmp_path, repo_root, layout="d4")
    host_bundle = pkg / "dist/codex"
    fixture_store = consumer / "linear-fixture.json"
    fixture_store.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "id": "planning-001",
                        "title": "Packaged consumer fixture",
                        "body": "---\nunitId: planning-001\n---\n",
                        "labels": ["sw:artifact-type:gap"],
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    env = _packaged_subprocess_env(
        staged_scripts=staged_scripts,
        consumer=consumer,
        host_bundle=host_bundle,
        repo_root=repo_root,
    )
    env["SW_ISSUES_FIXTURE"] = "1"
    env["SW_ISSUES_FIXTURE_PATH"] = str(fixture_store.resolve())

    proc = subprocess.run(
        [
            sys.executable,
            str(staged_scripts / "gitignore_generate.py"),
            "--root",
            str(consumer),
            "generate",
            "--write",
        ],
        cwd=str(consumer),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout.strip())
    assert payload["verdict"] == "pass"
    assert payload["action"] == "generate"
    assert (consumer / ".gitignore").is_file()

    gate_code = textwrap.dedent(
        f"""
        import json
        from pathlib import Path
        import planning_store_facade as psf
        import planning_store as ps
        consumer = Path({json.dumps(str(consumer))})
        pkg = Path({json.dumps(str(pkg))})
        cfg = json.loads({json.dumps(json.dumps(_linear_cfg()))})
        shipped = psf.shipped_issues_providers(consumer, package_root=pkg, active_host="codex")
        reason = ps.issue_store_fallback_reason(consumer, cfg)
        print(json.dumps({{
            "linearShipped": "linear" in shipped,
            "fallbackReason": reason,
        }}))
        """
    )
    gate_proc = subprocess.run(
        [sys.executable, "-c", gate_code],
        cwd=str(consumer),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert gate_proc.returncode == 0, gate_proc.stderr or gate_proc.stdout
    gate_payload = json.loads(gate_proc.stdout.strip())
    assert gate_payload["linearShipped"] is True
    assert gate_payload["fallbackReason"] != "issues-provider-not-shipped"
