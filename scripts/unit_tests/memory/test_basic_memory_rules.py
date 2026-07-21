"""PRD 075 R22–R26 — basic-memory hook rules script transport + mode-partitioned cache."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "core" / "providers" / "basic-memory-rules.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("basic_memory_rules", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["basic_memory_rules"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bm_rules():
    return _load_module()


def _write_config(workspace: Path, provider: str, **basic_memory: object) -> None:
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    payload = {
        "memory": {
            "provider": provider,
            "project": "hook-test",
            "basicMemory": basic_memory,
        }
    }
    (cursor / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


def _run_script(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict]:
    monkeypatch.setenv("SW_WORKSPACE_ROOT", str(workspace))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout or "{}")
    return proc.returncode, payload


def _run_main_inprocess(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    bm_rules,
) -> tuple[int, dict]:
    monkeypatch.setenv("SW_WORKSPACE_ROOT", str(workspace))
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        code = bm_rules.main()
    payload = json.loads(buf.getvalue() or "{}")
    return code, payload


def _seed_local_project(workspace: Path) -> Path:
    project = workspace / "bm-project"
    rules = project / "rules"
    rules.mkdir(parents=True)
    (rules / "guard.md").write_text(
        "---\nnote_type: rule\ncategory: rule\n---\nDo not invent providers.\n",
        encoding="utf-8",
    )
    return project


def test_non_applicable_for_wrong_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, "recallium", mode="local", projectPath=str(tmp_path / "proj"))
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 0
    assert payload["applicable"] is False
    assert payload["rules"] == []
    assert payload["ok"] is True


def test_local_reads_rules_folder_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "bm-project"
    rules = project / "rules"
    memories = project / "memories" / "decision"
    rules.mkdir(parents=True)
    memories.mkdir(parents=True)
    (rules / "guard.md").write_text(
        "---\nnote_type: rule\ncategory: rule\n---\nDo not invent providers.\n",
        encoding="utf-8",
    )
    (memories / "dec.md").write_text(
        "---\nnote_type: decision\n---\nShould not load as rule.\n",
        encoding="utf-8",
    )
    _write_config(
        tmp_path,
        "basic-memory",
        mode="local",
        projectPath=str(project),
        rulesDirectory="rules",
    )
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 0
    assert payload["ok"] is True
    assert payload["applicable"] is True
    assert payload["mode"] == "local"
    assert payload["cache"] == "miss"
    assert len(payload["rules"]) == 1
    assert payload["rules"][0]["id"] == "guard"
    assert "invent" in payload["rules"][0]["summary"]


def test_local_rejects_cloud_api_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    (project / "rules").mkdir(parents=True)
    _write_config(
        tmp_path,
        "basic-memory",
        mode="local",
        projectPath=str(project),
        apiBase="https://cloud.basicmemory.com",
    )
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 1
    assert payload["ok"] is False
    assert "must not open cloud" in payload["error"]


def test_local_rejects_remote_project_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        "basic-memory",
        mode="local",
        projectPath="https://evil.example/project",
    )
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 1
    assert payload["ok"] is False
    assert "filesystem" in payload["error"]


def test_cloud_missing_token_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BASIC_MEMORY_API_KEY", raising=False)
    _write_config(tmp_path, "basic-memory", mode="cloud")
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 1
    assert payload["ok"] is False
    assert "BASIC_MEMORY_API_KEY" in payload["error"]


def test_cloud_rejects_non_allowlisted_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bm_rules
) -> None:
    with pytest.raises(ValueError, match="allowlisted"):
        bm_rules.resolve_api_base({"apiBase": "https://evil.example"})


def test_strip_control_chars(bm_rules) -> None:
    cleaned = bm_rules.strip_control_chars("line\x00one\x07two")
    assert "\x00" not in cleaned
    assert "line" in cleaned and "two" in cleaned


def test_rule_fetch_command_rejects_shell_metacharacters(bm_rules) -> None:
    with pytest.raises(ValueError, match="shell metacharacters"):
        bm_rules.parse_rule_fetch_command("python3 -c 'print(1)' ; rm -rf /")


def test_rule_fetch_command_requires_exact_template(bm_rules) -> None:
    with pytest.raises(ValueError, match="fixed basic-memory"):
        bm_rules.validate_rule_fetch_command(
            ["python3", "-c", "print('nope')"],
            default_python="python3",
        )


def test_rules_from_cloud_payload_filters_and_caps(bm_rules) -> None:
    payload = {
        "notes": [
            {"id": "r1", "note_type": "rule", "content": "alpha"},
            {"id": "d1", "note_type": "decision", "content": "skip"},
            {"id": "r2", "directory": "rules/extra", "content": "beta"},
            {"id": "r3", "note_type": "rule", "content": "x" * 3000},
        ]
    }
    rules = bm_rules.rules_from_cloud_payload(payload)
    assert [r["id"] for r in rules] == ["r1", "r2", "r3"]
    assert rules[2]["summary"] == "x" * bm_rules.MAX_RULE_CHARS


def test_cache_miss_then_hit_skips_fetch(
    tmp_path: Path, bm_rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _seed_local_project(tmp_path)
    _write_config(
        tmp_path,
        "basic-memory",
        mode="local",
        projectPath=str(project),
        ruleCacheTtlSec=300,
    )

    fetch_calls = {"count": 0}
    real_fetch = bm_rules.fetch_local_rules

    def counting_fetch(cfg, workspace):
        fetch_calls["count"] += 1
        return real_fetch(cfg, workspace)

    monkeypatch.setattr(bm_rules, "fetch_local_rules", counting_fetch)

    code1, payload1 = _run_main_inprocess(tmp_path, monkeypatch, bm_rules)
    assert code1 == 0
    assert payload1["cache"] == "miss"
    assert fetch_calls["count"] == 1

    code2, payload2 = _run_main_inprocess(tmp_path, monkeypatch, bm_rules)
    assert code2 == 0
    assert payload2["cache"] == "hit"
    assert payload2["rules"][0]["id"] == "guard"
    assert fetch_calls["count"] == 1


def test_tampered_cache_is_miss(
    tmp_path: Path, bm_rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _seed_local_project(tmp_path)
    identity = str(project.resolve())
    _write_config(
        tmp_path,
        "basic-memory",
        mode="local",
        projectPath=str(project),
    )
    bm_rules.write_rules_cache_atomic(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        rules=[{"id": "r1", "summary": "alpha"}],
    )
    cache_file = bm_rules.cache_path(tmp_path)
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["rules"] = [{"id": "r1", "summary": "tampered"}]
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    code, out = _run_main_inprocess(tmp_path, monkeypatch, bm_rules)
    assert code == 0
    assert out["cache"] == "miss"
    assert out["rules"][0]["id"] == "guard"


def test_mode_partition_local_cloud_do_not_bleed(tmp_path: Path, bm_rules) -> None:
    project = _seed_local_project(tmp_path)
    local_identity = str(project.resolve())
    bm_rules.write_rules_cache_atomic(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=local_identity,
        rules=[{"id": "local-only", "summary": "local rule"}],
    )
    cloud_identity = "https://cloud.basicmemory.com|proj-1"
    assert (
        bm_rules.read_rules_cache(
            tmp_path,
            provider="basic-memory",
            mode="cloud",
            project_identity=cloud_identity,
            ttl_seconds=300,
        )
        is None
    )
    hit = bm_rules.read_rules_cache(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=local_identity,
        ttl_seconds=300,
    )
    assert hit is not None
    assert hit[0]["id"] == "local-only"


def test_foreign_project_cache_binding_is_miss(tmp_path: Path, bm_rules) -> None:
    project = tmp_path / "proj-a"
    other = tmp_path / "proj-b"
    project.mkdir()
    other.mkdir()
    bm_rules.write_rules_cache_atomic(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=str(other.resolve()),
        rules=[{"id": "r1", "summary": "foreign"}],
    )
    assert (
        bm_rules.read_rules_cache(
            tmp_path,
            provider="basic-memory",
            mode="local",
            project_identity=str(project.resolve()),
            ttl_seconds=300,
        )
        is None
    )


def test_cache_ttl_expiry_is_miss(tmp_path: Path, bm_rules) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    identity = str(project.resolve())
    bm_rules.write_rules_cache_atomic(
        tmp_path,
        provider="basic-memory",
        mode="local",
        project_identity=identity,
        rules=[{"id": "r1", "summary": "alpha"}],
    )
    cache_file = bm_rules.cache_path(tmp_path)
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["writtenAt"] = time.time() - 600
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        bm_rules.read_rules_cache(
            tmp_path,
            provider="basic-memory",
            mode="local",
            project_identity=identity,
            ttl_seconds=300,
        )
        is None
    )


def test_fail_closed_default_true(bm_rules) -> None:
    assert bm_rules.fail_closed_default({}) is True
    assert bm_rules.fail_closed_default({"failClosed": False}) is False
