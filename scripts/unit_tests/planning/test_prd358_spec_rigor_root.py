"""PRD 358 R8 — installed spec-rigor consumer --root (phase 10)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

FIXTURE_NAME = "spec-rigor-consumer-root"
FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "prd358_spec_rigor_consumer_root.json"
)


def _load_fixture() -> dict:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload.get("name") == FIXTURE_NAME
    return payload


def _issue_store_config() -> dict:
    return {
        "version": 1,
        "host": {"provider": "github"},
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "fixture-spec-rigor-root",
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "grdavies",
                    "repo": "planning",
                },
            }
        },
    }


def _init_consumer_git(consumer: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=consumer, check=True)
    subprocess.run(["git", "config", "user.email", "spec-rigor-root@test"], cwd=consumer, check=True)
    subprocess.run(["git", "config", "user.name", "spec-rigor-root"], cwd=consumer, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/shipwright-fixture/consumer.git"],
        cwd=consumer,
        check=True,
    )


@pytest.fixture
def issue_store_consumer(tmp_path: Path, repo_root: Path) -> Path:
    """Hermetic consumer repo (no scripts/) with issue-store virtual handle seeded."""
    fx = _load_fixture()
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _init_consumer_git(consumer)

    cfg_path = repo_root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    prior_cfg = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else None
    cfg_path.write_text(json.dumps(_issue_store_config(), indent=2) + "\n", encoding="utf-8")

    env = {**os.environ, "PYTHONPATH": str(repo_root / "scripts"), "SW_ISSUES_FIXTURE": "1"}
    subprocess.run(
        [sys.executable, str(repo_root / "scripts/planning_store.py"), "--root", str(repo_root), "clear-issue-fixture"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    put = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/planning_store.py"),
            "--root",
            str(repo_root),
            "put",
            "--backend",
            "issue-store",
            "--unit-id",
            fx["unitId"],
            "--body-path",
            fx["bodyPath"],
            "--content",
            fx["prdBody"],
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert json.loads(put.stdout).get("verdict") == "ok"

    state_src = repo_root / ".cursor" / "hooks" / "state"
    state_dest = consumer / ".cursor" / "hooks" / "state"
    state_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(state_src, state_dest, dirs_exist_ok=True)
    (consumer / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_issue_store_config(), indent=2) + "\n",
        encoding="utf-8",
    )
    assert not (consumer / fx["bodyPath"]).is_file()

    yield consumer

    subprocess.run(
        [sys.executable, str(repo_root / "scripts/planning_store.py"), "--root", str(repo_root), "clear-issue-fixture"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if prior_cfg is None:
        cfg_path.unlink(missing_ok=True)
    else:
        cfg_path.write_text(prior_cfg, encoding="utf-8")


def _run_spec_rigor(
    repo_root: Path,
    *,
    consumer: Path,
    extra_args: list[str],
) -> subprocess.CompletedProcess[str]:
    fx = _load_fixture()
    cmd = [
        sys.executable,
        str(repo_root / "scripts/spec-rigor-check.py"),
        "--artifact",
        "prd",
        "--path",
        fx["bodyPath"],
        "--unit-id",
        fx["unitId"],
        "--tier",
        "standard",
        *extra_args,
    ]
    return subprocess.run(
        cmd,
        cwd=str(consumer),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo_root / "scripts"), "SW_ISSUES_FIXTURE": "1"},
    )


def test_spec_rigor_consumer_root_virtual_handle_resolves(
    issue_store_consumer: Path, repo_root: Path
) -> None:
    """Named fixture resolves the virtual PRD handle when --root is the consumer repo."""
    proc = _run_spec_rigor(
        repo_root,
        consumer=issue_store_consumer,
        extra_args=["--root", str(issue_store_consumer)],
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    data = json.loads(proc.stdout)
    assert data.get("verdict") == "pass"
    assert data.get("artifact") == "prd"


def test_spec_rigor_consumer_root_fails_closed_without_root(
    issue_store_consumer: Path, repo_root: Path
) -> None:
    """Omitting --root fails closed (argparse required flag)."""
    fx = _load_fixture()
    cmd = [
        sys.executable,
        str(repo_root / "scripts/spec-rigor-check.py"),
        "--artifact",
        "prd",
        "--path",
        fx["bodyPath"],
        "--unit-id",
        fx["unitId"],
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(issue_store_consumer),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(repo_root / "scripts"),
            "SW_ISSUES_FIXTURE": "1",
            "SW_HARNESS": "",
            "ROOT": "",
        },
    )
    assert proc.returncode != 0
    assert "required" in (proc.stderr + proc.stdout).lower()


def test_spec_rigor_consumer_root_fails_closed_on_package_scripts_parent(
    issue_store_consumer: Path, repo_root: Path, tmp_path: Path
) -> None:
    """Passing the package scripts/ parent as --root fails closed for consumers (R8)."""
    fake_package = tmp_path / "installed-package"
    fake_package.mkdir()
    (fake_package / "scripts").symlink_to(repo_root / "scripts")

    proc = _run_spec_rigor(
        repo_root,
        consumer=issue_store_consumer,
        extra_args=["--root", str(fake_package.resolve())],
    )
    assert proc.returncode == 20
    data = json.loads(proc.stdout)
    assert data.get("verdict") == "fail"
    assert data.get("gate") == "root"
    assert "scripts/ parent" in (data.get("error") or "")
