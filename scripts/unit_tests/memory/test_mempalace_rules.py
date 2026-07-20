"""PRD 074 R19–R23 — mempalace hook rules script transport."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "core" / "providers" / "mempalace-rules.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mempalace_rules", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mempalace_rules"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mempalace_rules():
    return _load_module()


def _write_config(workspace: Path, provider: str, **mempalace: object) -> None:
    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    payload = {
        "memory": {
            "provider": provider,
            "project": "hook-test",
            "mempalace": mempalace,
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
    mempalace_rules,
) -> tuple[int, dict]:
    import contextlib
    from io import StringIO

    monkeypatch.setenv("SW_WORKSPACE_ROOT", str(workspace))
    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        code = mempalace_rules.main()
    payload = json.loads(buf.getvalue() or "{}")
    return code, payload


def test_non_applicable_for_wrong_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, "recallium", palacePath=str(tmp_path / "palace"))
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 0
    assert payload["applicable"] is False
    assert payload["rules"] == []


def test_rejects_remote_palace_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, "mempalace", palacePath="https://example.com/palace")
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 1
    assert payload["ok"] is False
    assert "local filesystem" in payload["error"]


def test_missing_palace_directory_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    palace = tmp_path / "missing-palace"
    _write_config(tmp_path, "mempalace", palacePath=str(palace))
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 1
    assert payload["ok"] is False
    assert "not found" in payload["error"]


def test_strip_control_chars(mempalace_rules) -> None:
    cleaned = mempalace_rules.strip_control_chars("line\x00one\x07two")
    assert "\x00" not in cleaned
    assert "line" in cleaned and "two" in cleaned


def test_drawers_to_rules_filters_room_and_caps(mempalace_rules) -> None:
    payload = {
        "drawers": [
            {"drawer_id": "r1", "room": "rules", "content": "alpha"},
            {"drawer_id": "r2", "room": "decision", "content": "skip"},
            {"drawer_id": "r3", "room": "rules", "content": "x" * 3000},
        ]
    }
    rules = mempalace_rules.drawers_to_rules(payload, rules_room="rules")
    assert len(rules) == 1
    assert rules[0]["id"] == "r1"
    assert rules[0]["content"] == "alpha"


def test_rule_fetch_command_rejects_shell_metacharacters(mempalace_rules) -> None:
    with pytest.raises(ValueError):
        mempalace_rules.parse_rule_fetch_command("python3 -c 'import os; os.system(\"rm\")'")


def test_rule_fetch_command_requires_exact_template(mempalace_rules) -> None:
    python = sys.executable
    good = mempalace_rules.default_fetch_argv(python)
    mempalace_rules.validate_rule_fetch_command(good, default_python=python)
    with pytest.raises(ValueError):
        mempalace_rules.validate_rule_fetch_command(
            [python, "-c", "print(1)"],
            default_python=python,
        )


def test_validate_registration_includes_mempalace(repo_root: Path) -> None:
    from memory_provider_register import validate_registration

    result = validate_registration(repo_root, "mempalace")
    assert result["providerId"] == "mempalace"
    assert result["rulesScript"].endswith("mempalace-rules.py")


def test_cache_miss_then_hit_skips_fetch(tmp_path: Path, mempalace_rules, monkeypatch: pytest.MonkeyPatch) -> None:
    palace = tmp_path / "palace"
    palace.mkdir()
    _write_config(tmp_path, "mempalace", palacePath=str(palace))

    fetch_calls = {"count": 0}

    def fake_fetch(*_args, **_kwargs):
        fetch_calls["count"] += 1
        return {
            "drawers": [{"drawer_id": "r1", "room": "rules", "content": "cached rule"}],
        }

    monkeypatch.setattr(mempalace_rules, "fetch_drawers_raw", fake_fetch)
    monkeypatch.setattr(
        mempalace_rules,
        "resolve_mempalace_python",
        lambda: sys.executable,
    )
    monkeypatch.setattr(
        mempalace_rules.subprocess,
        "run",
        lambda *args, **kwargs: type("P", (), {"returncode": 0})(),
    )

    code1, payload1 = _run_main_inprocess(tmp_path, monkeypatch, mempalace_rules)
    assert code1 == 0
    assert payload1["cache"] == "miss"
    assert fetch_calls["count"] == 1

    code2, payload2 = _run_main_inprocess(tmp_path, monkeypatch, mempalace_rules)
    assert code2 == 0
    assert payload2["cache"] == "hit"
    assert payload2["rules"][0]["content"] == "cached rule"
    assert fetch_calls["count"] == 1


def test_tampered_cache_is_miss(tmp_path: Path, mempalace_rules, monkeypatch: pytest.MonkeyPatch) -> None:
    palace = tmp_path / "palace"
    palace.mkdir()
    _write_config(tmp_path, "mempalace", palacePath=str(palace))
    rules = [{"id": "r1", "content": "alpha"}]
    mempalace_rules.write_rules_cache_atomic(
        tmp_path,
        provider="mempalace",
        palace_path=palace,
        rules=rules,
    )
    cache_path = mempalace_rules.cache_path(tmp_path)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["rules"] = [{"id": "r1", "content": "tampered"}]
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    fetch_calls = {"count": 0}

    def fake_fetch(*_args, **_kwargs):
        fetch_calls["count"] += 1
        return {"drawers": [{"drawer_id": "r2", "room": "rules", "content": "fresh"}]}

    monkeypatch.setattr(mempalace_rules, "fetch_drawers_raw", fake_fetch)
    monkeypatch.setattr(mempalace_rules, "resolve_mempalace_python", lambda: sys.executable)
    monkeypatch.setattr(
        mempalace_rules.subprocess,
        "run",
        lambda *args, **kwargs: type("P", (), {"returncode": 0})(),
    )

    code, out = _run_main_inprocess(tmp_path, monkeypatch, mempalace_rules)
    assert code == 0
    assert out["cache"] == "miss"
    assert fetch_calls["count"] == 1
    assert out["rules"][0]["id"] == "r2"


def test_foreign_cache_binding_is_miss(tmp_path: Path, mempalace_rules) -> None:
    palace = tmp_path / "palace"
    palace.mkdir()
    other = tmp_path / "other-palace"
    other.mkdir()
    mempalace_rules.write_rules_cache_atomic(
        tmp_path,
        provider="mempalace",
        palace_path=other,
        rules=[{"id": "r1", "content": "foreign"}],
    )
    assert (
        mempalace_rules.read_rules_cache(
            tmp_path,
            provider="mempalace",
            palace_path=palace,
            ttl_seconds=300,
        )
        is None
    )


def test_fail_closed_blocks_missing_palace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    palace = tmp_path / "missing"
    _write_config(tmp_path, "mempalace", palacePath=str(palace), failClosed=True)
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 1
    assert payload["ok"] is False


def test_fail_closed_break_glass_allows_missing_palace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    palace = tmp_path / "missing"
    _write_config(tmp_path, "mempalace", palacePath=str(palace), failClosed=False)
    code, payload = _run_script(tmp_path, monkeypatch)
    assert code == 0
    assert payload["ok"] is True
    assert payload.get("degraded") is True
    assert payload["rules"] == []


def test_cache_ttl_expiry_is_miss(tmp_path: Path, mempalace_rules) -> None:
    palace = tmp_path / "palace"
    palace.mkdir()
    mempalace_rules.write_rules_cache_atomic(
        tmp_path,
        provider="mempalace",
        palace_path=palace,
        rules=[{"id": "r1", "content": "alpha"}],
    )
    cache_path = mempalace_rules.cache_path(tmp_path)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["writtenAt"] = time.time() - 600
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        mempalace_rules.read_rules_cache(
            tmp_path,
            provider="mempalace",
            palace_path=palace,
            ttl_seconds=300,
        )
        is None
    )
