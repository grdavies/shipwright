"""Legacy façade removal + clobber detection (PRD 078 phase 5 / R8)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from init_scripts_facade import (
    DELIVER_ENTRYPOINTS,
    FORWARDER_BODY,
    FORWARDER_SCRIPTS,
    MANIFEST_REL,
    SW_DISPATCHER,
    detect_legacy_facade,
    manifest_path,
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


def test_detect_finds_legacy_facade_files(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    plugin.mkdir()
    _write_legacy_facade(consumer, plugin)
    app_script = consumer / "scripts" / "my_app_deploy.py"
    app_script.write_text("# user app script\n", encoding="utf-8")

    payload = detect_legacy_facade(consumer)
    assert payload["verdict"] == "found"
    facade_paths = {entry["path"] for entry in payload["facadeFiles"]}
    assert MANIFEST_REL in facade_paths
    assert "scripts/sw" in facade_paths
    assert "scripts/wave_deliver.py" in facade_paths
    foreign_paths = {entry["path"] for entry in payload["foreign"]}
    assert "scripts/my_app_deploy.py" in foreign_paths


def test_remove_deletes_only_facade_files(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    plugin.mkdir()
    _write_legacy_facade(consumer, plugin)
    app_script = consumer / "scripts" / "my_app_deploy.py"
    app_script.write_text("# user app script\n", encoding="utf-8")

    dry = remove_legacy_facade(consumer, confirm=False)
    assert dry["dryRun"] is True
    assert manifest_path(consumer).is_file()

    removed = remove_legacy_facade(consumer, confirm=True)
    assert removed["verdict"] == "pass"
    assert MANIFEST_REL in removed["removed"]
    assert not manifest_path(consumer).exists()
    assert not (consumer / "scripts" / "sw").exists()
    assert app_script.is_file()
    assert app_script.read_text(encoding="utf-8") == "# user app script\n"


def test_remove_refuses_unmarked_forwarder_candidate(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    plugin.mkdir()
    _write_legacy_facade(consumer, plugin)
    hand_authored = consumer / "scripts" / "wave_deliver.py"
    hand_authored.write_text("# custom deliver helper\n", encoding="utf-8")

    payload = remove_legacy_facade(consumer, confirm=True)
    assert payload["verdict"] == "fail"
    assert payload["error"] == "refused-unmarked-facade-candidates"
    assert hand_authored.is_file()


def test_clobber_reported_for_modified_forwarder(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    plugin.mkdir()
    _write_legacy_facade(consumer, plugin)
    forwarder = consumer / "scripts" / "wave_deliver.py"
    forwarder.write_text(
        forwarder.read_text(encoding="utf-8") + "\n# operator edit\n",
        encoding="utf-8",
    )

    payload = detect_legacy_facade(consumer)
    kinds = {entry["kind"] for entry in payload["clobber"]}
    assert "modified-template" in kinds


def test_clobber_reported_from_git_history(tmp_git_repo: Path) -> None:
    consumer = tmp_git_repo
    _seed_consumer(consumer)
    plugin = consumer / "plugin"
    plugin.mkdir()
    scripts = consumer / "scripts"
    scripts.mkdir()
    original = scripts / "wave_deliver.py"
    original.write_text("# user-owned deliver script\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=consumer, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "user script"],
        cwd=consumer,
        check=True,
        capture_output=True,
    )

    _write_legacy_facade(consumer, plugin)
    subprocess.run(["git", "add", "-A"], cwd=consumer, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "legacy facade emit"],
        cwd=consumer,
        check=True,
        capture_output=True,
    )

    payload = detect_legacy_facade(consumer)
    history = [entry for entry in payload["clobber"] if entry.get("kind") == "history-overwrite"]
    assert history
    assert "no restore offered" in history[0]["note"]


def test_cli_detect_and_remove_subcommands(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    plugin = tmp_path / "plugin"
    _seed_consumer(consumer)
    plugin.mkdir()
    _write_legacy_facade(consumer, plugin)

    script = Path(__file__).resolve().parents[2] / "init_scripts_facade.py"
    detect_proc = subprocess.run(
        [sys.executable, str(script), str(consumer), "detect"],
        cwd=str(consumer),
        capture_output=True,
        text=True,
    )
    assert detect_proc.returncode == 0, detect_proc.stderr
    detect_payload = json.loads(detect_proc.stdout)
    assert detect_payload["verdict"] == "found"

    remove_proc = subprocess.run(
        [sys.executable, str(script), str(consumer), "remove", "--confirm"],
        cwd=str(consumer),
        capture_output=True,
        text=True,
    )
    assert remove_proc.returncode == 0, remove_proc.stderr
    remove_payload = json.loads(remove_proc.stdout)
    assert remove_payload["verdict"] == "pass"
    assert not manifest_path(consumer).exists()
