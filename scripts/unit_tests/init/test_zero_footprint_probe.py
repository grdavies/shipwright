"""Zero-footprint probe fixtures (PRD 078 phase 6 / TR5, R6, R9)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from init_scripts_facade import (
    DELIVER_ENTRYPOINTS,
    FORWARDER_BODY,
    FORWARDER_SCRIPTS,
    SW_DISPATCHER,
    detect_legacy_facade,
    manifest_path,
    probe_deliver_entrypoints,
    shipwright_version,
)
from sw_scripts_resolve import resolve_script


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
        (path / name).write_text(f"# stub {name}\nif __name__ == '__main__': pass\n", encoding="utf-8")


def _write_legacy_facade(root: Path, plugin: Path) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "generatedBy": "init_scripts_facade",
        "pluginScripts": str(plugin.resolve()),
        "shipwrightVersion": shipwright_version(root),
        "deliverEntrypoints": list(DELIVER_ENTRYPOINTS),
        "forwarders": list(FORWARDER_SCRIPTS),
    }
    manifest_path(root).parent.mkdir(parents=True, exist_ok=True)
    manifest_path(root).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (scripts / "sw").write_text(SW_DISPATCHER, encoding="utf-8")
    for name in FORWARDER_SCRIPTS:
        (scripts / name).write_text(FORWARDER_BODY, encoding="utf-8")


def test_probe_passes_empty_consumer_with_plugin(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    env = {"SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

    payload = probe_deliver_entrypoints(consumer, env=env)
    assert payload["verdict"] == "pass"
    assert payload["mode"] == "zero-footprint"
    assert payload["errors"] == []
    assert payload["resolveErrors"] == []
    assert set(payload["resolvedSources"]) == set(DELIVER_ENTRYPOINTS)
    assert payload["scriptsRootSource"] == "env"

    for name in DELIVER_ENTRYPOINTS:
        resolved = resolve_script(consumer, name, env=env)
        assert resolved.parent.resolve() == plugin.resolve()


def test_probe_fails_residual_facade(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    _write_legacy_facade(consumer, plugin)

    payload = probe_deliver_entrypoints(consumer)
    assert payload["verdict"] == "fail"
    assert "residual-facade-files" in payload["errors"]
    assert payload["facadeFiles"]


def test_probe_fails_missing_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = tmp_path / "consumer"
    _seed_consumer(consumer)
    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", tmp_path / "missing-local")
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "missing-cache")

    payload = probe_deliver_entrypoints(consumer)
    assert payload["verdict"] == "fail"
    assert payload["resolveErrors"]
    assert any("plugin not installed" in err for err in payload["resolveErrors"])


def test_probe_fails_hand_forwarder_pollution(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    scripts = consumer / "scripts"
    scripts.mkdir(parents=True)
    hand_authored = scripts / "wave_deliver.py"
    hand_authored.write_text("# custom deliver helper\n", encoding="utf-8")
    app_script = scripts / "my_app_deploy.py"
    app_script.write_text("# user app script\n", encoding="utf-8")
    env = {"SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

    detection = detect_legacy_facade(consumer)
    assert any(entry.get("identity") == "refused" for entry in detection["refused"])

    payload = probe_deliver_entrypoints(consumer, env=env)
    assert payload["verdict"] == "fail"
    assert "hand-forwarder-pollution" in payload["errors"]
    assert hand_authored.is_file()
    assert app_script.is_file()


def test_probe_skips_shipwright_self_repo(repo_root: Path) -> None:
    payload = probe_deliver_entrypoints(repo_root)
    assert payload["verdict"] == "skip"
    assert payload["reason"] == "shipwright-self-repo"


def test_cli_probe_subcommand_passes(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "init_scripts_facade.py"),
            str(consumer),
            "probe",
        ],
        cwd=str(consumer),
        capture_output=True,
        text=True,
        env={**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin.resolve())},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["mode"] == "zero-footprint"


def test_cli_probe_subcommand_fails_on_facade(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    _write_legacy_facade(consumer, plugin)

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "init_scripts_facade.py"),
            str(consumer),
            "probe",
        ],
        cwd=str(consumer),
        capture_output=True,
        text=True,
        env={**os.environ, "SHIPWRIGHT_SCRIPTS": str(plugin.resolve())},
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert "residual-facade-files" in payload["errors"]
