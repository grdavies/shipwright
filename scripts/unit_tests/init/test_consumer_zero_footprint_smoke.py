"""Greenfield consumer integration smoke (PRD 078 phase 10 / TR4, R1, R4, R13)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from init_scripts_facade import DELIVER_ENTRYPOINTS, FORWARDER_SCRIPTS, emit_facade, manifest_path, probe_deliver_entrypoints
from sw_bootstrap import resolve_helper


def _seed_consumer(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cursor").mkdir(exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "memory": {"provider": "in-repo"}}) + "\n",
        encoding="utf-8",
    )


def _seed_trusted_plugin(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (path / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")
    for name in DELIVER_ENTRYPOINTS:
        if name == "wave_deliver.py":
            (path / name).write_text(
                "print('wave-from-plugin')\nif __name__ == '__main__': pass\n",
                encoding="utf-8",
            )
        else:
            (path / name).write_text(f"# stub {name}\nif __name__ == '__main__': pass\n", encoding="utf-8")


def _snapshot_tree(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_greenfield_init_emit_writes_no_shipwright_files(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    app_script = consumer / "scripts" / "deploy_app.py"
    app_script.parent.mkdir(parents=True)
    app_script.write_text("# pre-existing app script\n", encoding="utf-8")
    before = _snapshot_tree(consumer)

    payload = emit_facade(consumer, plugin_scripts=plugin)
    assert payload["verdict"] == "skip"
    assert payload["reason"] == "emit-retired"

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "init_scripts_facade.py"),
            str(consumer),
            "emit",
        ],
        cwd=str(consumer),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    cli_payload = json.loads(proc.stdout)
    assert cli_payload["verdict"] == "skip"
    assert cli_payload["reason"] == "emit-retired"

    after = _snapshot_tree(consumer)
    assert before == after
    assert not manifest_path(consumer).exists()
    assert not (consumer / "scripts" / "sw").exists()
    for name in FORWARDER_SCRIPTS:
        assert not (consumer / "scripts" / name).exists()
    assert app_script.read_text(encoding="utf-8") == "# pre-existing app script\n"


def test_greenfield_bootstrap_resolves_wave_helper_to_plugin(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    app_script = consumer / "scripts" / "deploy_app.py"
    app_script.parent.mkdir(parents=True)
    app_script.write_text("# pre-existing app script\n", encoding="utf-8")
    env = {"SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

    resolved = resolve_helper(consumer, "wave_deliver.py", env=env)
    assert resolved == (plugin / "wave_deliver.py").resolve()

    probe = probe_deliver_entrypoints(consumer, env=env)
    assert probe["verdict"] == "pass"
    assert probe["mode"] == "zero-footprint"
    assert probe["resolvedSources"]["wave_deliver.py"] == "env"


def test_greenfield_bootstrap_exec_smoke(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    app_script = consumer / "scripts" / "deploy_app.py"
    app_script.parent.mkdir(parents=True)
    app_script.write_text("# pre-existing app script\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "--print",
            "wave_deliver.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin.resolve())},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str((plugin / "wave_deliver.py").resolve())
