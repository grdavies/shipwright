"""PRD 073 phase-provision stdout JSON parse (R10, R11, R18)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_wave_lifecycle():
    spec = importlib.util.spec_from_file_location("wave_lifecycle_stdout_json", _ROOT / "wave_lifecycle.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ProvisionFail(Exception):
    def __init__(self, exit_code: int, **payload: object) -> None:
        super().__init__(payload.get("error"))
        self.exit_code = exit_code
        self.payload = payload


@pytest.fixture(scope="module")
def wave_lifecycle():
    return _load_wave_lifecycle()


@pytest.fixture(autouse=True)
def _stub_fail(wave_lifecycle, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fail(error: str, exit_code: int = 2, **extra: object) -> None:
        raise ProvisionFail(exit_code, error=error, **extra)

    monkeypatch.setattr(wave_lifecycle, "fail", fake_fail)


def test_parse_last_json_object_success_with_noise(wave_lifecycle) -> None:
    stdout = (
        "Preparing worktree (new branch 'feat/demo-phase-alpha')\n"
        "HEAD is now at abc1234\n"
        '{"verdict":"provisioned","path":"/tmp/demo-phase","branch":"feat/demo-phase-alpha"}'
    )
    payload = wave_lifecycle.parse_last_json_object(stdout)
    assert payload["verdict"] == "provisioned"
    assert payload["path"] == "/tmp/demo-phase"


def test_parse_last_json_object_braces_in_strings(wave_lifecycle) -> None:
    stdout = (
        "noise line\n"
        '{"verdict":"provisioned","path":"/tmp/wt/{braces}/ok","name":"demo-phase"}'
    )
    payload = wave_lifecycle.parse_last_json_object(stdout)
    assert payload["path"] == "/tmp/wt/{braces}/ok"
    assert payload["name"] == "demo-phase"


def test_parse_last_json_object_trailing_schema_invalid_object(wave_lifecycle) -> None:
    stdout = (
        '{"verdict":"provisioned","path":"/tmp/wt","name":"demo-phase"}\n'
        '{"verdict":"ok"}'
    )
    payload = wave_lifecycle.parse_last_json_object(stdout)
    assert payload == {"verdict": "ok"}


def test_provision_payload_from_stdout_success_with_noise(wave_lifecycle) -> None:
    stdout = (
        "Preparing worktree\n"
        '{"verdict":"provisioned","path":"/tmp/demo-phase","branch":"feat/demo-phase-alpha"}'
    )
    payload = wave_lifecycle.provision_payload_from_stdout(stdout, worktree_name="parent-phase-demo")
    assert payload["path"] == "/tmp/demo-phase"
    assert payload["name"] == "parent-phase-demo"
    assert payload["worktreeName"] == "parent-phase-demo"


def test_provision_payload_from_stdout_rejects_trailing_invalid_schema(wave_lifecycle) -> None:
    stdout = (
        '{"verdict":"provisioned","path":"/tmp/wt","name":"demo-phase"}\n'
        '{"verdict":"ok"}'
    )
    with pytest.raises(ProvisionFail) as exc:
        wave_lifecycle.provision_payload_from_stdout(stdout, worktree_name="demo-phase")
    assert exc.value.exit_code == 20
    assert exc.value.payload.get("cause") == "phase-provision:invalid-payload"


def test_provision_payload_from_stdout_rejects_missing_json(wave_lifecycle) -> None:
    with pytest.raises(ProvisionFail) as exc:
        wave_lifecycle.provision_payload_from_stdout(
            "Preparing worktree only\n",
            worktree_name="demo-phase",
        )
    assert exc.value.exit_code == 20
    assert exc.value.payload.get("cause") == "phase-provision:invalid-stdout"
