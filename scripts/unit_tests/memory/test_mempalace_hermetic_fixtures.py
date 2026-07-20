"""PRD 074 R28 — hermetic offline MemPalace fixture suite (no live daemon/MCP)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mempalace_interchange as mpi

FIXTURE_ROOT = SCRIPTS / "test" / "fixtures" / "mempalace"
SCENARIOS = FIXTURE_ROOT / "scenarios"
RULES_SCRIPT = SCRIPTS.parent / "core" / "providers" / "mempalace-rules.py"


def _load_rules_module():
    spec = importlib.util.spec_from_file_location("mempalace_rules", RULES_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mempalace_rules():
    return _load_rules_module()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_lists_required_scenarios() -> None:
    manifest = _read_json(FIXTURE_ROOT / "manifest.json")
    assert manifest["supportedPackage"] == "mempalace>=3.6.0,<4.0.0"
    for scenario in (
        "cache-allowlist",
        "rooms-taxonomy",
        "opt-in-transcripts",
        "rulesroom-refuse",
        "links-merge",
        "purge-orphan",
    ):
        assert scenario in manifest["scenarios"]
        assert (SCENARIOS / scenario).is_dir()


def test_compat_tool_schemas_cover_op_map_tools() -> None:
    compat = _read_json(FIXTURE_ROOT / "compat-tool-schemas.json")
    assert compat["metadata"]["supportedPackage"] == "mempalace>=3.6.0,<4.0.0"
    for tool in compat["opMapTools"]:
        assert tool in compat["tools"]
        schema = compat["tools"][tool]["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties"), dict)


def test_cache_allowlist_fixture_validates_and_rejects_tamper(
    tmp_path: Path, mempalace_rules
) -> None:
    palace = tmp_path / "palace"
    palace.mkdir()
    valid = _read_json(SCENARIOS / "cache-allowlist" / "rules-cache-valid.json")
    valid["palacePath"] = str(palace.resolve())
    valid["writtenAt"] = time.time()
    tampered = _read_json(SCENARIOS / "cache-allowlist" / "rules-cache-tampered.json")
    allowlist = _read_json(SCENARIOS / "cache-allowlist" / "allowlist-executables.json")
    list_drawers = _read_json(SCENARIOS / "cache-allowlist" / "list-drawers-response.json")

    assert mempalace_rules.validate_cache_entry(
        valid,
        provider="mempalace",
        palace_path=palace,
        ttl_seconds=300,
    )
    assert not mempalace_rules.validate_cache_entry(
        tampered,
        provider="mempalace",
        palace_path=palace,
        ttl_seconds=300,
    )

    for basename in allowlist["allowedBasenames"]:
        assert basename in mempalace_rules._ALLOWED_EXECUTABLE_BASENAMES
    for rejected in allowlist["rejectedExamples"]:
        with pytest.raises(ValueError):
            mempalace_rules.parse_rule_fetch_command(rejected)

    rules = mempalace_rules.drawers_to_rules(
        list_drawers,
        rules_room="rules",
    )
    assert [rule["id"] for rule in rules] == ["rule-guard-no-secrets"]


def test_rooms_taxonomy_fixture_matches_canonical_categories(mempalace_rules) -> None:
    taxonomy = _read_json(SCENARIOS / "rooms-taxonomy" / "taxonomy.json")
    canonical = _read_json(SCENARIOS / "rooms-taxonomy" / "canonical-rooms.json")
    drawers = _read_json(SCENARIOS / "rooms-taxonomy" / "drawers-by-room.json")["drawers"]

    assert taxonomy["rooms"]["rules"] == 1
    assert taxonomy["rooms"]["transcripts"] == 1
    assert canonical["reservedRooms"]["rulesRoom"] == "rules"
    assert "rule" in canonical["canonicalCategories"]

    excluded = mempalace_rules.resolve_search_exclude_rooms(
        {
            "rulesRoom": canonical["reservedRooms"]["rulesRoom"],
            "searchExcludeRooms": ["transcripts"],
        }
    )
    visible = mempalace_rules.filter_drawers_for_ordinary_search(
        drawers,
        exclude_rooms=excluded,
    )
    assert {row["room"] for row in visible} == {"decision", "learning"}


def test_opt_in_transcripts_fixture_emits_warning(mempalace_rules) -> None:
    scenario = _read_json(SCENARIOS / "opt-in-transcripts" / "config.json")
    drawers = _read_json(SCENARIOS / "opt-in-transcripts" / "drawers.json")
    expected = _read_json(SCENARIOS / "opt-in-transcripts" / "expected-warnings.json")

    mem_cfg = scenario["memory"]
    excluded = mempalace_rules.resolve_search_exclude_rooms(mem_cfg)
    filtered = mempalace_rules.filter_drawers_for_ordinary_search(
        drawers["drawers"],
        exclude_rooms=excluded,
    )
    assert [row["drawer_id"] for row in filtered] == ["mp-decision-001"]

    warnings = mempalace_rules.opt_in_excluded_room_warnings(
        exclude_rooms=excluded,
        explicit_room=drawers["explicitRoom"],
    )
    assert warnings == expected["warnings"]


def test_rulesroom_refuse_fixture_blocks_ordinary_store(mempalace_rules) -> None:
    scenario = _read_json(SCENARIOS / "rulesroom-refuse" / "config.json")
    rules_drawers = _read_json(SCENARIOS / "rulesroom-refuse" / "rules-drawers.json")
    rules_room = scenario["memory"]["rulesRoom"]

    excluded = mempalace_rules.resolve_search_exclude_rooms(scenario["memory"])
    filtered = mempalace_rules.filter_drawers_for_ordinary_search(
        rules_drawers["drawers"],
        exclude_rooms=excluded,
    )
    assert filtered == []

    with pytest.raises(ValueError, match="rulesRoom"):
        mempalace_rules.guard_rules_room_write(
            scenario["ordinaryStoreAttempt"]["room"],
            rules_room=rules_room,
        )
    mempalace_rules.guard_rules_room_write(
        scenario["promotionPath"]["room"],
        rules_room=rules_room,
        promotion_path=scenario["promotionPath"]["promotionPath"],
    )


def test_links_merge_fixture_remaps_conflicts_and_preserves_links(tmp_path: Path) -> None:
    palace = tmp_path / "palace"
    shutil.copytree(SCENARIOS / "links-merge" / "palace", palace)
    incoming = SCENARIOS / "links-merge" / "incoming.jsonl"

    result = mpi.import_palace(palace, "jsonl", incoming, dry_run=False, wing="fixture-repo")
    remapped = {entry["from"]: entry["to"] for entry in result["idRemaps"]}
    assert "mp-merge-a" in remapped

    links = mpi.load_kg_links(palace)
    new_a = remapped["mp-merge-a"]
    assert any(
        link["source"] == new_a and link["target"] == "mp-merge-b" for link in links
    )
    assert "mp-merge-c" in set(mpi.list_drawer_ids(palace))


def test_purge_orphan_fixture_keeps_dangling_kg_edge(tmp_path: Path, mempalace_rules) -> None:
    expected = _read_json(SCENARIOS / "purge-orphan" / "expected-orphan.json")
    palace = tmp_path / "palace"
    shutil.copytree(SCENARIOS / "purge-orphan" / "palace", palace)

    mempalace_rules.guard_hard_purge(confirmed=True)

    assert mpi.load_drawer(palace, expected["deletedDrawerId"]) is None
    assert mpi.load_drawer(palace, expected["survivingDrawerId"]) is not None
    links = mpi.load_kg_links(palace)
    assert expected["orphanEdge"] in links
