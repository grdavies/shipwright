"""PRD 277 R3 — work-start loads rules via preflight rules-load, not search/store."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import (
    RulesLoadRequiredError,
    preflight,
    search_cannot_load_rules,
    store_cannot_load_rules,
)

REPO = SCRIPTS.parent


def _loader(root: Path, provider: str) -> dict:
    del root
    return {
        "ok": True,
        "provider": provider,
        "rules": [
            {"id": "mock-realism", "body": "Mocks must match production contracts."},
            {"id": "not-allowlisted", "body": "should be dropped"},
        ],
    }


def test_work_start_loads_via_preflight_rules_load() -> None:
    result = preflight(REPO, loader=_loader)
    assert result["verdict"] == "ok"
    assert result["rulesLoad"]["op"] == "rules-load"
    assert result["rulesLoad"]["source"] == "rules-load"
    ids = {_rule_id(entry) for entry in result["rulesLoad"]["rules"]}
    assert "mock-realism" in ids
    assert "not-allowlisted" not in ids


def test_rules_load_not_substitutable_by_search_store() -> None:
    with pytest.raises(RulesLoadRequiredError) as search_exc:
        search_cannot_load_rules()
    assert search_exc.value.op == "search"
    with pytest.raises(RulesLoadRequiredError) as store_exc:
        store_cannot_load_rules()
    assert store_exc.value.op == "store"


def _rule_id(entry: object) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id") or "")
    return str(entry)
