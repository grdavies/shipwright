"""Import-parity fixtures over the planning package inventory (PRD 082 phase 11 / R27)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_store  # noqa: E402
from _planning_pkg_loader import load_package  # noqa: E402

planning = load_package()
from planning_import_inventory import build_inventory  # noqa: E402
from planning_shim_gen import inventoried_symbol_names  # noqa: E402


PACKAGE_SYMBOLS = tuple(planning.__all__)


@pytest.mark.parametrize("name", PACKAGE_SYMBOLS)
def test_package_symbol_matches_planning_store(name: str) -> None:
    store_obj = getattr(planning_store, name)
    package_obj = getattr(planning, name)
    assert store_obj is package_obj, f"{name}: planning_store and planning disagree"


def test_inventoried_package_symbols_match_store() -> None:
    inventory = build_inventory(REPO_ROOT)
    names = inventoried_symbol_names(inventory)
    for name in names:
        if name not in PACKAGE_SYMBOLS:
            continue
        assert getattr(planning_store, name) is getattr(planning, name)


def test_planning_index_gen_uses_canonical_planning_unit() -> None:
    import planning_index_gen as pig

    assert pig.PlanningUnit is planning.PlanningUnit


def test_repository_contract_has_no_duplicate_open_guard() -> None:
    assert not hasattr(planning.PlanningStoreBackend, "_guard_duplicate_open_tasks_mint")


def test_model_has_no_provider_fields() -> None:
    fields = {f.name for f in planning.PlanningUnit.__dataclass_fields__.values()}
    forbidden = {"labels", "etag", "comments", "chunk_manifest", "chunk_manifests"}
    assert forbidden.isdisjoint(fields)
