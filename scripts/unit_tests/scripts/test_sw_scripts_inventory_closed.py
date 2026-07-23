"""Closed inventory gate after skills/hooks migration (PRD 078 phase 8 / TR9, R7, R9)."""
from __future__ import annotations

from pathlib import Path

from check_scripts_inventory import run_check
from sw_scripts_inventory import find_unclassified, load_inventory
from sw_scripts_rewrite import consumer_capable_literals_remain


def test_full_tree_inventory_guard_passes() -> None:
    root = Path(__file__).resolve().parents[3]
    exit_code, payload = run_check(root)
    assert exit_code == 0
    assert payload["verdict"] == "pass"
    assert payload["reason"] == "scripts-inventory-closed"
    assert int(payload.get("entryCount") or 0) > 0


def test_no_unclassified_literals_in_scanned_trees() -> None:
    root = Path(__file__).resolve().parents[3]
    inventory = load_inventory(root)
    assert find_unclassified(root, inventory) == []


def test_no_consumer_capable_direct_literals_in_skills_hooks() -> None:
    root = Path(__file__).resolve().parents[3]
    trees = ("core/skills", "core/hooks", "dist/cursor/skills", "dist/claude-code/skills")
    remaining = consumer_capable_literals_remain(root, trees)
    assert remaining == []
