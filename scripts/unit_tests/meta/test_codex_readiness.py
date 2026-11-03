"""Regression checks for existing-project readiness in a linked Codex checkout."""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_fixture_child_keeps_context_without_inheriting_credentials(tmp_path: Path) -> None:
    from unit_tests._harness_runtime import FixtureContext

    script = tmp_path / "child_probe.py"
    script.write_text(
        "import os,json\nprint(json.dumps({"
        "'planning': 'SW_PLANNING_ISSUES_TOKEN' in os.environ,"
        "'host': 'GH_TOKEN' in os.environ,"
        "'context': os.environ.get('SW_FIXTURE_CONTEXT')}))\n"
    )
    fixture = FixtureContext(__file__)
    fixture.env.update(SW_PLANNING_ISSUES_TOKEN="fixture-value",
                       GH_TOKEN="fixture-host-secret", SW_FIXTURE_CONTEXT="fixture")
    result = fixture.run_py(str(script), check=True)
    assert json.loads(result.stdout) == {"planning": False, "host": False, "context": "fixture"}


def test_source_fixture_owns_config_and_git_state(tmp_path: Path) -> None:
    from unit_tests._harness_runtime import isolated_source_fixture

    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "scripts/example.py").write_text("# fixture source\n")
    (source / "scripts/check-gate.py").write_text("# fixture marker\n")
    (source / "core/sw-reference").mkdir(parents=True)
    (source / "core/sw-reference/marker.json").write_text("{}")
    (source / "version.txt").write_text("0.0.0")
    (source / ".shipwright-dev").write_text("# development sentinel\n")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "scripts", "core", "version.txt", ".shipwright-dev"], check=True)
    (source / "scripts/ignored-output").write_text("not a source input")
    (source / ".cursor").mkdir()
    operator_config = source / ".cursor/workflow.config.json"
    execution = {
        "models": {"tiers": {"build": "gpt-6.1-sol"},
                   "reasoningEffortByTier": {"build": "high"}},
        "review": {"local": {"enabled": True, "gate": {"haltOn": ["P0", "P1"]}}},
        "communication": {"defaultIntensity": "lite"},
        "dispatch": {"unregisteredParentModelTier": "mid"},
    }
    operator_config.write_text(json.dumps({"projectId": "operator-owned", **execution,
        "planning": {"store": {"backend": "issue-store", "issues": {"credentialRef": "fixture-ref"}}}}))
    before = operator_config.read_bytes()
    with isolated_source_fixture(source) as fixture:
        assert fixture != source
        assert (fixture / "scripts/example.py").is_file()
        assert not (fixture / "scripts/ignored-output").exists()
        from repository_context import is_plugin_self_repository
        assert is_plugin_self_repository(fixture)
        config = json.loads((fixture / ".cursor/workflow.config.json").read_text())
        assert config["projectId"] != "operator-owned"
        assert config["planning"]["store"]["backend"] == "in-repo-public"
        assert config["models"] == execution["models"]
        assert config["review"] == execution["review"]
        assert config["communication"] == execution["communication"]
        assert config["dispatch"] == execution["dispatch"]
        assert "credentialRef" not in json.dumps(config)
        common = subprocess.check_output(
            ["git", "-C", str(fixture), "rev-parse", "--git-common-dir"], text=True).strip()
        assert (fixture / common).resolve() == fixture / ".git"
    assert not fixture.exists()
    assert operator_config.read_bytes() == before


def test_source_fixture_ignores_caller_git_selectors(tmp_path: Path, monkeypatch) -> None:
    from unit_tests._harness_runtime import isolated_source_fixture

    caller = tmp_path / "caller"
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "init", "-q", str(caller)], check=True)
    (caller / "sentinel").write_text("caller-owned\n")
    subprocess.run(["git", "-C", str(caller), "add", "sentinel"], check=True)
    subprocess.run(["git", "-C", str(caller), "-c", "user.name=Fixture",
                    "-c", "user.email=t@t.com", "commit", "-q", "-m", "caller"], check=True)
    before_head = (caller / ".git/logs/HEAD").read_bytes()
    before_index = (caller / ".git/index").read_bytes()
    monkeypatch.setenv("GIT_DIR", str(caller / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(caller))
    monkeypatch.setenv("GIT_INDEX_FILE", str(caller / ".git/index"))
    with isolated_source_fixture(source) as fixture:
        assert (fixture / ".git").is_dir()
    assert (caller / ".git/logs/HEAD").read_bytes() == before_head
    assert (caller / ".git/index").read_bytes() == before_index


def test_approved_build_model_keeps_exact_id(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"models": {
        "tiers": {"build": "gpt-6.1-sol"},
        "reasoningEffortByTier": {"build": "high"},
    }}))
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/resolve-model-tier.py"),
         "--tier", "build", "--config", str(config)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["modelId"] == "gpt-6.1-sol"
    assert payload["reasoningEffort"] == "high"
    assert "aliasFrom" not in payload


def test_doctor_accepts_successful_interpreter_probe(tmp_path: Path, monkeypatch) -> None:
    import doctor
    from _sw.interpreter import InterpreterResult

    monkeypatch.setattr(doctor, "probe", lambda: InterpreterResult(
        [sys.executable], (3, 14, 5), "3.14.5"))
    result = doctor.diagnose(tmp_path)
    assert not any(issue.startswith("python-floor:") for issue in result["issues"])
    assert result["python"] == "3.14.5"


def test_linked_worktree_guard_never_rewrites_primary(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "-q", str(primary)], check=True)
    subprocess.run(["git", "-C", str(primary), "-c", "user.name=Fixture",
                    "-c", "user.email=t@t.com", "commit", "-q",
                    "--allow-empty", "-m", "fixture"], check=True)
    subprocess.run(["git", "-C", str(primary), "worktree", "add", "-q",
                    "--detach", str(linked)], check=True)
    for root, content in [(primary, "primary-owned"), (linked, "worktree-owned")]:
        (root / ".cursor").mkdir()
        (root / ".cursor/state.json").write_text(content)
    protected = primary / ".cursor/state.json"
    protected.chmod(0o640)
    before = protected.stat().st_mtime_ns
    before_mode = protected.stat().st_mode
    spec = importlib.util.spec_from_file_location(
        "readiness_conftest", ROOT / "scripts/unit_tests/conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    guard = module._guard_cursor_worktree_artifacts.__wrapped__(linked)
    next(guard)
    (linked / ".cursor/state.json").write_text("test-mutated")
    (linked / ".cursor/ephemeral.json").write_text("test-created")
    next(guard, None)
    assert protected.read_text() == "primary-owned"
    assert protected.stat().st_mtime_ns == before
    assert protected.stat().st_mode == before_mode
    assert (linked / ".cursor/state.json").read_text() == "worktree-owned"
    assert not (linked / ".cursor/ephemeral.json").exists()


def test_chunk_doctor_hydrates_summary_comments(tmp_path: Path, monkeypatch) -> None:
    import planning_store as ps
    import planning_migrate_issue_store as migrate

    doctor = importlib.import_module("planning-doctor")
    body = '<!-- sw-chunk-manifest: {"chunks":[{"commentId":"123"}]} -->'
    summary = SimpleNamespace(id="42", unit_id="unit-a", body=body, comments=[])
    ordinary = SimpleNamespace(id="43", unit_id="ordinary", body="plain body", comments=[])
    complete = SimpleNamespace(id="42", unit_id="unit-a", body=body,
                               comments=[SimpleNamespace(id="123")])
    reads = []

    def get(issue_id):
        reads.append(issue_id)
        return complete

    monkeypatch.setattr(ps, "load_workflow_config", lambda root: {})
    monkeypatch.setattr(ps, "validate_project_key", lambda root, cfg: {"verdict": "ok", "projectKey": "fixture"})
    monkeypatch.setattr(migrate, "issue_store_effective", lambda root, cfg: True)
    monkeypatch.setattr(migrate, "cfg_issues_client", lambda root: SimpleNamespace(
        issue_search=lambda **kwargs: [ordinary, summary], issue_get=get))
    assert doctor.chunk_cardinality_finding(tmp_path) is None
    assert reads == ["42"]
    complete.comments = []
    finding = doctor.chunk_cardinality_finding(tmp_path)
    assert finding["check"] == "chunk-cardinality-mismatch"
    assert finding["units"][0]["missingCommentIds"] == ["123"]
    complete.body = '<!-- sw-chunk-manifest: {"chunks":[{"commentId":"456"}]} -->'
    complete.comments = [SimpleNamespace(id="456")]
    assert doctor.chunk_cardinality_finding(tmp_path) is None

    def denied(issue_id):
        raise PermissionError("fixture read denied")

    monkeypatch.setattr(migrate, "cfg_issues_client", lambda root: SimpleNamespace(
        issue_search=lambda **kwargs: [summary], issue_get=denied))
    finding = doctor.chunk_cardinality_finding(tmp_path)
    assert finding["check"] == "chunk-cardinality-inconclusive"
    assert finding["issueIds"] == ["42"]


def test_credential_probe_uses_broker_without_ambient_env(tmp_path: Path, monkeypatch) -> None:
    import planning_store as ps
    from credentials.model import CredentialRef, Resolution, ResolvedToken, Secret
    from _planning_pkg_loader import load_providers_package

    providers = load_providers_package()
    resolution = Resolution.resolved(CredentialRef("planning-fixture"),
                                     ResolvedToken(Secret("fixture-only")))
    monkeypatch.setattr(ps, "resolve_issues_provider", lambda cfg: {"provider": "github-issues", "supported": True})
    monkeypatch.setattr(ps, "shipped_issues_providers", lambda root: {"github-issues"})
    monkeypatch.setattr(ps, "resolve_issues_token_env", lambda cfg, provider: "")
    monkeypatch.setattr(ps, "resolve_issues_credential", lambda *args, **kwargs: resolution)
    seen = []

    def probe(provider, token, cfg, root):
        seen.append((provider, token))
        return {"verdict": "ok"}

    monkeypatch.setattr(providers, "scope_probe", probe)
    monkeypatch.setattr(providers, "attach_native_links_capable", lambda *args: None)
    result = providers.probe_issues_token(tmp_path, {})
    assert result["verdict"] == "ok"
    assert result["credentialRef"] == "planning-fixture"
    assert result["credentialState"] == "resolved"
    assert seen == [("github-issues", "fixture-only")]
    assert "fixture-only" not in json.dumps(result)
    monkeypatch.setattr(ps, "resolve_issues_credential", lambda *args, **kwargs:
                        Resolution.unresolved(CredentialRef("planning-fixture")))
    result = providers.probe_issues_token(tmp_path, {})
    assert result["verdict"] == "fail"
    assert result["credentialState"] == "unresolved"
    assert seen == [("github-issues", "fixture-only")]


@pytest.mark.parametrize("family", ["default", "legacy", "preferred", "both"])
def test_prework_audit_is_local_to_linked_checkout(tmp_path: Path, capsys, family: str) -> None:
    import wave_memory_prework as prework
    from shipwright_paths import deliver_runs_dir
    from unit_tests._harness_runtime import isolated_git_environment

    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    env = isolated_git_environment({key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ})
    subprocess.run(["git", "init", "-q", "-b", "main", str(primary)], check=True, env=env)
    subprocess.run(["git", "-C", str(primary), "-c", "user.name=Fixture",
                    "-c", "user.email=t@t.com", "-c", "commit.gpgsign=false",
                    "commit", "-q", "--allow-empty", "-m", "fixture"], check=True, env=env)
    subprocess.run(["git", "-C", str(primary), "worktree", "add", "-q", "-b", "codex/prework",
                    str(linked)], check=True, env=env)
    protected = [primary / ".cursor/sw-deliver-runs/run.legacy.log",
                 primary / ".shipwright/deliver-runs/run.legacy.log"]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("primary-owned\n")
        path.chmod(0o640)
    before = [(p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in protected]
    cursor = linked / ".cursor"
    cursor.mkdir()
    (cursor / "workflow.config.json").write_text(json.dumps({"memory": {"provider": "in-repo"}}))
    (cursor / "sw-memory.provider").write_text("in-repo")
    if family in ("legacy", "both"):
        (cursor / "sw-deliver-runs").mkdir()
    if family in ("preferred", "both"):
        (linked / ".shipwright/deliver-runs").mkdir(parents=True)
    expected = linked / (".cursor/sw-deliver-runs" if family == "legacy" else ".shipwright/deliver-runs")
    assert deliver_runs_dir(linked) == expected
    with pytest.raises(SystemExit) as stop:
        prework.cmd_record(linked, ["--surface", "sw-review", "--scope", "fixture", "--offline"])
    assert stop.value.code == 0
    response = json.loads(capsys.readouterr().out)
    record = json.loads((linked / prework.RECORD_PATH).read_text())
    audit = expected / "run.legacy.log"
    assert audit.is_file()
    entry = json.loads(audit.read_text().splitlines()[-1])
    assert response["verdict"] == "pass"
    assert entry["event"] == "memory-prework-search"
    assert entry["nonce"] == record["nonce"] == response["nonce"]
    assert [(p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in protected] == before
