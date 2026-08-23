"""PRD 325 phase 6 — orchestrator/primary scripts-hash divergence halt and rebind (R10)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _ROOT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sw_scripts_resolve import compute_scripts_root_hash, scripts_root_binding


def _load_wave_lifecycle():
    spec = importlib.util.spec_from_file_location(
        "wave_lifecycle_hash_binding", _ROOT / "wave_lifecycle.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wave_lifecycle_hash_binding"] = mod
    spec.loader.exec_module(mod)
    return mod


wave_lifecycle = _load_wave_lifecycle()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def _trusted_scripts(tmp_path: Path, *, suffix: str = "") -> Path:
    scripts = tmp_path / f"scripts{suffix}"
    scripts.mkdir(parents=True)
    (scripts / "check-gate.py").write_text(f"# gate {suffix}\n", encoding="utf-8")
    (scripts / "resolve-model-tier.py").write_text(
        f"# tier {suffix}\n", encoding="utf-8"
    )
    return scripts


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "branch", "-M", "main")
    scripts = _REPO_ROOT / "scripts"
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(scripts.resolve()))
    return repo


def _provision_fixture(git_repo: Path) -> tuple[Path, Path]:
    _git(git_repo, "checkout", "-qb", "feat/hash-demo")
    _git(git_repo, "commit", "--allow-empty", "-qm", "demo")
    _git(git_repo, "checkout", "-q", "main")
    orch = git_repo / ".sw-worktrees" / "hash-demo-orchestrator"
    _git(git_repo, "worktree", "add", "-q", str(orch), "feat/hash-demo")
    _git(git_repo, "checkout", "-q", "main")
    return git_repo, orch


def test_compute_scripts_root_hash_stable(tmp_path: Path) -> None:
    scripts = _trusted_scripts(tmp_path)
    first = compute_scripts_root_hash(scripts)
    second = compute_scripts_root_hash(scripts)
    assert first == second
    (scripts / "check-gate.py").write_text("# changed\n", encoding="utf-8")
    assert compute_scripts_root_hash(scripts) != first


def test_equal_hash_provision_is_noop(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, orch = _provision_fixture(git_repo)
    primary_binding = scripts_root_binding(repo)
    orchestrator_binding = scripts_root_binding(orch)
    assert primary_binding["hash"] == orchestrator_binding["hash"]

    with patch("halt_resume.enrich_fail_extra"), patch.object(
        wave_lifecycle, "assert_primary_off_target"
    ):
        with pytest.raises(SystemExit) as exc:
            wave_lifecycle.cmd_orchestrator_provision(repo, ["--target", "feat/hash-demo"])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["adopted"] is True
    assert payload["scriptsBinding"]["hash"] == primary_binding["hash"]


def test_divergent_hash_halts_with_remediation() -> None:
    primary_binding = {"root": "/a", "source": "self-repo", "hash": "a" * 64}
    divergent = {"root": "/b", "source": "env", "hash": "b" * 64}
    with patch("halt_resume.enrich_fail_extra"):
        with pytest.raises(SystemExit) as exc:
            wave_lifecycle._enforce_scripts_hash_binding(
                primary_binding=primary_binding,
                orchestrator_binding=divergent,
                stored_binding=None,
                target="feat/hash-demo",
                rebind=False,
            )
    assert exc.value.code == 20


def test_rebind_restamps_binding(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, orch = _provision_fixture(git_repo)
    primary_binding = scripts_root_binding(repo)
    divergent = {
        "root": "/tmp/other-scripts",
        "source": "env",
        "hash": "deadbeef" * 8,
    }

    with patch.object(wave_lifecycle, "assert_primary_off_target"), patch.object(
        wave_lifecycle,
        "_resolve_scripts_bindings",
        return_value=(primary_binding, divergent),
    ):
        with pytest.raises(SystemExit) as exc:
            wave_lifecycle.cmd_orchestrator_provision(
                repo, ["--target", "feat/hash-demo", "--rebind"]
            )
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rebound"] is True
    assert payload["scriptsBinding"] == divergent


def test_orchestrator_status_reports_divergence(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, orch = _provision_fixture(git_repo)
    primary_binding = scripts_root_binding(repo)
    divergent = {
        "root": "/tmp/other-scripts",
        "source": "env",
        "hash": "deadbeef" * 8,
    }
    from wave_state import load_deliver_state, save_deliver_state

    state = load_deliver_state(repo, target="feat/hash-demo")
    state["orchestratorWorktree"] = {
        "path": str(orch),
        "branch": "feat/hash-demo",
        "name": "hash-demo-orchestrator",
        "scriptsBinding": divergent,
    }
    save_deliver_state(repo, state, target="feat/hash-demo")

    with patch.object(
        wave_lifecycle,
        "_resolve_scripts_bindings",
        return_value=(primary_binding, divergent),
    ):
        with pytest.raises(SystemExit) as exc:
            wave_lifecycle.cmd_orchestrator_status(repo, [])
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scriptsHashDiverged"] is True
    assert payload["primaryScriptsBinding"]["hash"] != payload["orchestratorScriptsBinding"]["hash"]
