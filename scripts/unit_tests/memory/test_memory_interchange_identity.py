"""PRD 082 R31 — interchange identity, two-pass import, key collision fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import basic_memory_interchange as bmi
import memory_import_resolve as mir
import memory_key_collision as mkc


def _record(
    record_id: str,
    *,
    title: str | None = None,
    body: str = "body",
    supersedes: list[str] | None = None,
) -> dict:
    fields: dict = {"permalink": record_id}
    if title:
        fields["title"] = title
    if supersedes:
        fields["supersedes"] = supersedes
    out: dict = {
        "id": record_id,
        "category": "learning",
        "body": body,
        "fields": fields,
    }
    if supersedes:
        out["supersedes"] = supersedes
    return out


def test_out_of_order_supersedes_resolves() -> None:
    records = [
        _record("mem-v2", body="v2 body", supersedes=["mem-v1"]),
        _record("mem-v1", body="v1 body"),
    ]
    resolved, registry = mir.two_pass_import_resolve(records)
    assert registry.resolve("mem-v1") == "mem-v1"
    assert registry.resolve("mem-v2") == "mem-v2"
    by_id = {r["id"]: r for r in resolved}
    assert by_id["mem-v2"]["supersedes"] == ["mem-v1"]


def test_unresolvable_supersedes_target_errors() -> None:
    records = [_record("mem-new", supersedes=["missing-parent"])]
    with pytest.raises(mir.ImportResolveError) as exc:
        mir.two_pass_import_resolve(records)
    assert exc.value.cause == "unresolvable-supersedes"


def test_alias_collision_write_refused() -> None:
    index: dict[str, str] = {"shared-alias": "identity-a"}
    incoming = _record("identity-b", title="shared-alias")
    with pytest.raises(mkc.KeyCollisionError) as exc:
        mkc.assert_no_alias_collision(index, incoming, canonical_id="identity-b")
    assert exc.value.cause == "alias-collision"


def test_repeated_imports_produce_no_suffix_families(tmp_path: Path) -> None:
    project = tmp_path / "bm"
    source = tmp_path / "batch.jsonl"
    rows = [
        {"id": "mem-alpha", "content": "alpha body", "category": "learning", "title": "Alpha"},
        {"id": "mem-beta", "content": "beta body", "category": "decision", "title": "Beta"},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    first = bmi.import_project(project, "jsonl", source, dry_run=False)
    second = bmi.import_project(project, "jsonl", source, dry_run=False)

    assert first["idRemaps"] == []
    assert second["idRemaps"] == []
    ids = set(bmi.list_permalinks(project))
    assert ids == {"mem-alpha", "mem-beta"}
    assert not any("-sw-" in note_id for note_id in ids)


def test_identity_keyed_disk_path_differs_from_permalink_alias(tmp_path: Path) -> None:
    record = _record("stable-id-001", title="permalink-alias")
    record["fields"]["permalink"] = "permalink-alias"
    assert mkc.identity_key(record) == "stable-id-001"
    identity_rel = mkc.identity_disk_relpath("learning", "stable-id-001")
    permalink_rel = mkc.permalink_disk_relpath("learning", "permalink-alias")
    assert identity_rel != permalink_rel


def test_semantic_drift_without_supersedes_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "bm"
    bmi.ensure_project(project)
    bmi.write_note(
        project,
        bmi.record_to_note(_record("mem-drift", body="original")),
    )
    source = tmp_path / "drift.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": "mem-drift",
                "content": "changed semantic body",
                "category": "learning",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(bmi.InterchangeError) as exc:
        bmi.import_project(project, "jsonl", source, dry_run=False)
    assert exc.value.cause == "alias-collision"
