"""Migration + pollution regression integration smoke (PRD 078 phase 10 / TR4, R6, R8)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from init_scripts_facade import (
    DELIVER_ENTRYPOINTS,
    FORWARDER_BODY,
    FORWARDER_SCRIPTS,
    SW_DISPATCHER,
    detect_legacy_facade,
    manifest_path,
    probe_deliver_entrypoints,
    remove_legacy_facade,
    shipwright_version,
)


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


def test_migration_smoke_removes_only_facade_preserves_foreign_scripts(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    _write_legacy_facade(consumer, plugin)
    foreign = consumer / "scripts" / "my_app_deploy.py"
    foreign.write_text("# user-owned deploy script\n", encoding="utf-8")

    detect = detect_legacy_facade(consumer)
    assert detect["verdict"] == "found"
    assert any(entry["path"] == "scripts/my_app_deploy.py" for entry in detect["foreign"])

    removed = remove_legacy_facade(consumer, confirm=True)
    assert removed["verdict"] == "pass"
    assert not manifest_path(consumer).exists()
    assert not (consumer / "scripts" / "sw").exists()
    assert foreign.is_file()
    assert foreign.read_text(encoding="utf-8") == "# user-owned deploy script\n"

    probe = probe_deliver_entrypoints(consumer, env={"SHIPWRIGHT_SCRIPTS": str(plugin.resolve())})
    assert probe["verdict"] == "pass"
    assert probe["mode"] == "zero-footprint"


def test_migration_smoke_cli_detect_remove_end_to_end(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    _write_legacy_facade(consumer, plugin)
    foreign = consumer / "scripts" / "ci_runner.py"
    foreign.write_text("# foreign ci runner\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "init_scripts_facade.py"

    detect_proc = subprocess.run(
        [sys.executable, str(script), str(consumer), "detect"],
        cwd=str(consumer),
        capture_output=True,
        text=True,
    )
    assert detect_proc.returncode == 0, detect_proc.stderr
    assert json.loads(detect_proc.stdout)["verdict"] == "found"

    remove_proc = subprocess.run(
        [sys.executable, str(script), str(consumer), "remove", "--confirm"],
        cwd=str(consumer),
        capture_output=True,
        text=True,
    )
    assert remove_proc.returncode == 0, remove_proc.stderr
    remove_payload = json.loads(remove_proc.stdout)
    assert remove_payload["verdict"] == "pass"
    assert foreign.is_file()


def test_migration_smoke_hand_forwarder_fails_guards(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    _seed_trusted_plugin(plugin)
    scripts = consumer / "scripts"
    scripts.mkdir(parents=True)
    hand_authored = scripts / "wave_deliver.py"
    hand_authored.write_text("# custom deliver helper\n", encoding="utf-8")
    foreign = scripts / "my_app_deploy.py"
    foreign.write_text("# user app script\n", encoding="utf-8")
    env = {"SHIPWRIGHT_SCRIPTS": str(plugin.resolve())}

    probe = probe_deliver_entrypoints(consumer, env=env)
    assert probe["verdict"] == "fail"
    assert "hand-forwarder-pollution" in probe["errors"]
    assert hand_authored.is_file()
    assert foreign.is_file()

    remove_payload = remove_legacy_facade(consumer, confirm=True)
    assert remove_payload["verdict"] == "fail"
    assert remove_payload["error"] == "refused-unmarked-facade-candidates"
