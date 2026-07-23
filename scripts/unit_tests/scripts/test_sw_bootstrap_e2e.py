"""End-to-end bootstrap argv integration smoke (PRD 078 phase 10 / TR2, R13)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from init_scripts_facade import DELIVER_ENTRYPOINTS, probe_deliver_entrypoints


def _seed_consumer(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cursor").mkdir(exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "memory": {"provider": "in-repo"}}) + "\n",
        encoding="utf-8",
    )


def _seed_trusted_plugin(path: Path, *, include_facade_helper: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (path / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")
    for name in DELIVER_ENTRYPOINTS:
        (path / name).write_text(
            "import sys\n"
            f"if __name__ == '__main__': print('{name}:ok')\n",
            encoding="utf-8",
        )
    if include_facade_helper:
        repo_script = Path(__file__).resolve().parents[2] / "init_scripts_facade.py"
        (path / "init_scripts_facade.py").write_text(
            repo_script.read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def test_documented_bootstrap_print_argv_resolves_deliver_entrypoint(tmp_path: Path) -> None:
    """Guides document: python3 scripts/sw_bootstrap.py --print wave_deliver.py"""
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    env = {**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

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
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str((plugin / "wave_deliver.py").resolve())

    probe = probe_deliver_entrypoints(consumer, env={"SHIPWRIGHT_SCRIPTS": str(plugin.resolve())})
    assert probe["verdict"] == "pass"
    assert probe["resolvedSources"]["wave_deliver.py"] == "env"


def test_documented_bootstrap_exec_argv_runs_deliver_entrypoint(tmp_path: Path) -> None:
    """Guides document: python3 scripts/sw_bootstrap.py wave_deliver.py -- --help"""
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    env = {**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "wave_deliver.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "wave_deliver.py:ok"


def test_bootstrap_init_scripts_facade_probe_argv(tmp_path: Path) -> None:
    """Configuration guide: sw_bootstrap.py init_scripts_facade.py -- . probe"""
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin, include_facade_helper=True)
    env = {**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "sw_bootstrap.py"),
            "--root",
            str(consumer),
            "init_scripts_facade.py",
            "--",
            str(consumer),
            "probe",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["mode"] == "zero-footprint"
