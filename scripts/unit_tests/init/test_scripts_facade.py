"""Emit-forbidden fixtures for retired consumer façade (PRD 078 phase 4 / R1, R2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from init_scripts_facade import (
    FORWARDER_SCRIPTS,
    emit_facade,
    manifest_path,
    should_emit_facade,
)


def _seed_consumer(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cursor").mkdir(exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "memory": {"provider": "in-repo"}}) + "\n",
        encoding="utf-8",
    )


def _seed_plugin_scripts(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in FORWARDER_SCRIPTS:
        (path / name).write_text(f"# stub {name}\nif __name__ == '__main__': pass\n", encoding="utf-8")


def test_should_not_emit_in_shipwright_self_repo(repo_root: Path) -> None:
    assert not should_emit_facade(repo_root)
    payload = emit_facade(repo_root)
    assert payload["verdict"] == "skip"
    assert payload["reason"] == "shipwright-self-repo"


def test_should_not_emit_for_consumer(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    _seed_consumer(consumer)
    assert not should_emit_facade(consumer)


def test_consumer_emit_forbidden_writes_nothing(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_plugin_scripts(plugin)
    scripts = consumer / "scripts"
    scripts.mkdir(parents=True)
    app_script = scripts / "my_app_deploy.py"
    app_script.write_text("# user app script\n", encoding="utf-8")

    payload = emit_facade(consumer, plugin_scripts=plugin)
    assert payload["verdict"] == "skip"
    assert payload["reason"] == "emit-retired"

    assert not (scripts / "sw").exists()
    assert not manifest_path(consumer).exists()
    for name in FORWARDER_SCRIPTS:
        assert not (scripts / name).exists()
    assert app_script.read_text(encoding="utf-8") == "# user app script\n"


def test_cli_emit_subcommand_forbidden(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_plugin_scripts(plugin)

    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "init_scripts_facade.py"), str(consumer), "emit"],
        cwd=str(consumer),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "skip"
    assert payload["reason"] == "emit-retired"
    assert not (consumer / "scripts" / "sw").exists()
