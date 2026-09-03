"""State-root inventory and coupling-hygiene assertions (PRD 342 R2, R9)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT / "sw") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "sw"))

import shipwright_paths  # noqa: E402
from emitter_base import (  # noqa: E402
    HostConventionWriteForbidden,
    refuse_workflow_write_to_host_convention,
)

INVENTORY_REL = Path("core/sw-reference/state-root-inventory.json")
HOST_BRAND_RE = re.compile(r"(cursor|claude)", re.IGNORECASE)


def _load_inventory(repo_root: Path) -> list[dict]:
    path = repo_root / INVENTORY_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    assert isinstance(entries, list), "inventory entries must be a list"
    return entries


def test_inventory_entries_resolve_through_path_module(repo_root: Path) -> None:
    entries = _load_inventory(repo_root)
    assert entries, "inventory must enumerate at least one relocated family"

    for entry in entries:
        accessor_name = entry.get("accessor")
        assert isinstance(accessor_name, str) and accessor_name
        accessor = shipwright_paths.inventory_accessor(accessor_name)
        resolved = accessor(repo_root)
        assert shipwright_paths.path_matches_inventory_entry(resolved, repo_root, entry), (
            f"{accessor_name} resolved {resolved} does not match inventory entry {entry}"
        )


def test_new_paths_avoid_host_brand_names(repo_root: Path) -> None:
    entries = _load_inventory(repo_root)
    for entry in entries:
        new_path = str(entry.get("newPath") or "")
        family = str(entry.get("family") or "")
        accessor = str(entry.get("accessor") or "")
        assert not HOST_BRAND_RE.search(new_path), f"newPath carries host brand: {new_path}"
        assert not HOST_BRAND_RE.search(family), f"family carries host brand: {family}"
        assert not HOST_BRAND_RE.search(accessor), f"accessor carries host brand: {accessor}"


def test_shipwright_paths_constants_avoid_host_brand_names() -> None:
    assert shipwright_paths.STATE_ROOT_PRIMARY == ".shipwright"
    assert not HOST_BRAND_RE.search(shipwright_paths.WORKFLOW_CONFIG_PREFERRED_REL)
    for name in shipwright_paths.INVENTORY_ACCESSORS:
        assert not HOST_BRAND_RE.search(name), f"accessor name carries host brand: {name}"


def test_workflow_config_candidates_prefer_shipwright_root(tmp_path: Path) -> None:
    legacy = tmp_path / ".cursor" / "workflow.config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"defaultBaseBranch":"legacy"}', encoding="utf-8")
    preferred = tmp_path / ".shipwright" / "workflow.config.json"
    preferred.parent.mkdir(parents=True)
    preferred.write_text('{"defaultBaseBranch":"preferred"}', encoding="utf-8")

    assert shipwright_paths.workflow_config_path(tmp_path) == preferred
    assert shipwright_paths.load_workflow_config(tmp_path)["defaultBaseBranch"] == "preferred"


def test_emitter_refuses_workflow_writes_to_host_convention(tmp_path: Path) -> None:
    target = tmp_path / ".cursor" / "rules" / "example.mdc"
    with pytest.raises(HostConventionWriteForbidden):
        refuse_workflow_write_to_host_convention(target, tmp_path)
