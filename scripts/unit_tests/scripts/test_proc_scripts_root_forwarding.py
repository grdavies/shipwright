"""Internal child dispatch keeps only the validated Shipwright scripts binding."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from _sw.proc import HookVerifyEnv, materialize_child_env, run


def trusted_scripts(tmp_path: Path) -> Path:
    scripts = tmp_path / "trusted scripts"
    scripts.mkdir()
    (scripts / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (scripts / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")
    return scripts


def test_default_dispatch_forwards_only_validated_scripts_root(tmp_path: Path, monkeypatch) -> None:
    scripts = trusted_scripts(tmp_path)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(scripts))
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS_TOKEN", "do-not-forward")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-forward")
    monkeypatch.setenv("SW_PHASE_SLUG", "phase-three")
    child = run(
        [sys.executable, "-c", "import json, os; print(json.dumps({k: os.getenv(k) for k in ('SHIPWRIGHT_SCRIPTS', 'SHIPWRIGHT_SCRIPTS_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'SW_PHASE_SLUG')}))"]
    )
    assert child.returncode == 0
    observed = json.loads(child.stdout)
    assert observed == {
        "SHIPWRIGHT_SCRIPTS": str(scripts.resolve()),
        "SHIPWRIGHT_SCRIPTS_TOKEN": None,
        "AWS_SECRET_ACCESS_KEY": None,
        "SW_PHASE_SLUG": "phase-three",
    }


@pytest.mark.parametrize("invalid", ["relative/scripts", "/definitely/missing/shipwright/scripts"])
def test_default_dispatch_rejects_untrusted_binding(invalid: str) -> None:
    with pytest.raises(ValueError, match="SHIPWRIGHT_SCRIPTS"):
        materialize_child_env(None, parent={"PATH": "/usr/bin", "SHIPWRIGHT_SCRIPTS": invalid})


def test_explicit_hook_environment_does_not_gain_scripts_binding(tmp_path: Path) -> None:
    scripts = trusted_scripts(tmp_path)
    parent = {"PATH": "/usr/bin", "SHIPWRIGHT_SCRIPTS": str(scripts), "SW_PHASE_SLUG": "p3"}
    child = materialize_child_env(HookVerifyEnv(declared_context_keys=("SW_PHASE_SLUG",)), parent=parent)
    assert child.get("SW_PHASE_SLUG") == "p3"
    assert "SHIPWRIGHT_SCRIPTS" not in child
