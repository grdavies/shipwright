"""Inventory generator + guard fixtures (PRD 078 phase 1 / R7, R9)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from check_scripts_inventory import run_check
from sw_scripts_inventory import (
    CLASS_CONSUMER_CAPABLE,
    CLASS_SELF_REPO_ONLY,
    INVENTORY_REL,
    build_inventory,
    classify_script,
    extract_literals,
    find_dist_mismatches,
    find_unclassified,
    scan_tree,
    write_inventory,
)


def test_empty_tree_has_no_call_sites(tmp_path: Path) -> None:
    (tmp_path / "core" / "commands").mkdir(parents=True)
    assert scan_tree(tmp_path, "core/commands") == []


def test_classify_consumer_capable_helpers() -> None:
    assert classify_script("host.py") == CLASS_CONSUMER_CAPABLE
    assert classify_script("wave.py") == CLASS_SELF_REPO_ONLY


def test_labeled_self_repo_only_retained(tmp_path: Path) -> None:
    cmd = tmp_path / "core" / "commands" / "sw-ship.md"
    cmd.parent.mkdir(parents=True)
    cmd.write_text("Run `python3 scripts/wave.py ship-loop drive`\n", encoding="utf-8")
    inventory = build_inventory(tmp_path)
    write_inventory(tmp_path, inventory)
    assert find_unclassified(tmp_path) == []
    exit_code, payload = run_check(tmp_path)
    assert exit_code == 0
    assert payload["verdict"] == "pass"


def test_unclassified_consumer_literal_fails(tmp_path: Path) -> None:
    cmd = tmp_path / "core" / "commands" / "sw-init.md"
    cmd.parent.mkdir(parents=True)
    cmd.write_text("Run python3 scripts/mystery-helper.py\n", encoding="utf-8")
    inventory = {
        "version": 1,
        "schema": "scripts-call-site-inventory/v1",
        "entries": [],
    }
    write_inventory(tmp_path, inventory)
    violations = find_unclassified(tmp_path, inventory)
    assert len(violations) == 1
    assert violations[0]["code"] == "unclassified-literal"
    exit_code, payload = run_check(tmp_path)
    assert exit_code == 20
    assert payload["verdict"] == "fail"


def test_dist_mismatch_fails(tmp_path: Path) -> None:
    core = tmp_path / "core" / "commands" / "sw-init.md"
    dist = tmp_path / "dist" / "cursor" / "commands" / "sw-init.md"
    core.parent.mkdir(parents=True)
    dist.parent.mkdir(parents=True)
    core.write_text("alpha python3 scripts/host.py beta\n", encoding="utf-8")
    dist.write_text("alpha python3 scripts/doctor.py beta\n", encoding="utf-8")
    mismatches = find_dist_mismatches(tmp_path)
    assert len(mismatches) == 1
    assert mismatches[0]["code"] == "dist-mismatch"


def test_extract_literals_normalizes_script_names() -> None:
    hits = extract_literals("Use python3 scripts/host and PYTHONPATH=scripts python3 scripts/doctor.py\n")
    scripts = {script for *_rest, script in hits}
    assert scripts == {"host.py", "doctor.py"}


def test_inventory_round_trip_entry_ids(tmp_path: Path) -> None:
    cmd = tmp_path / "core" / "commands" / "sw-init.md"
    cmd.parent.mkdir(parents=True)
    cmd.write_text("python3 scripts/host.py\n", encoding="utf-8")
    inventory = build_inventory(tmp_path)
    write_inventory(tmp_path, inventory)
    loaded = json.loads((tmp_path / INVENTORY_REL).read_text(encoding="utf-8"))
    assert loaded["entries"][0]["classification"] in {CLASS_SELF_REPO_ONLY, CLASS_CONSUMER_CAPABLE}
