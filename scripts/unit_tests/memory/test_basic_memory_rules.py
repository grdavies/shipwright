"""PRD 075 R22–R25 — basic-memory hook rules script transport."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
