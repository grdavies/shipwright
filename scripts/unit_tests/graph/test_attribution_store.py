"""Attribution store tests — PRD 351 phase 1 (TS1, TS9, TS11)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from graph.attribution_store import (
    ATTRIBUTION_SCHEMA_VERSION,
    AttributionWriteError,
    NULLABLE_DIMENSION_FIELDS,
    build_attribution_record,
    mark_legacy_if_unversioned,
    write_attribution_record,
)

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
RAW_PROMPT_FIXTURE = "SYSTEM PROMPT: you are a helpful assistant with secret key sk-test"


@pytest.mark.parametrize("field", list(NULLABLE_DIMENSION_FIELDS))
def test_null_field_preservation(field: str) -> None:
    """TS1 — each nullable field can be null without sentinel substitution."""
    kwargs = {field: None, "attempt_count": 1}
    record = build_attribution_record(**kwargs)
    assert record[field] is None  # type: ignore[literal-required]
    assert record[field] not in {"python", "build", "medium"}  # type: ignore[literal-required]


def test_post_merge_defects_always_null() -> None:
    record = build_attribution_record(attempt_count=1)
    assert record["post_merge_defects"] is None


def test_schema_version_present_on_new_records() -> None:
    record = build_attribution_record(
        attempt_count=1,
        attribution_schema_version=ATTRIBUTION_SCHEMA_VERSION,
    )
    assert record["attribution_schema_version"] == "1.0.0"
    assert record["legacy"] is False


def test_attempt_count_rejects_zero() -> None:
    with pytest.raises(ValueError):
        build_attribution_record(attempt_count=0)


def test_write_atomic_and_task_record_id_unique(tmp_path: Path) -> None:
    a = build_attribution_record(attempt_count=1, requested_model="a")
    b = build_attribution_record(attempt_count=1, requested_model="b")
    assert a["task_record_id"] != b["task_record_id"]
    write_attribution_record(a, tmp_path)
    write_attribution_record(b, tmp_path)
    paths = list((tmp_path / "attribution").glob("*.json"))
    assert len(paths) == 2
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["post_merge_defects"] is None
        assert payload["attribution_schema_version"] == ATTRIBUTION_SCHEMA_VERSION


def test_missing_schema_version_marked_legacy() -> None:
    """TS9 — records lacking attribution_schema_version are legacy."""
    record: dict = {"task_record_id": "legacy-1"}
    mark_legacy_if_unversioned(record)
    assert record["legacy"] is True


def test_write_requires_task_record_id(tmp_path: Path) -> None:
    with pytest.raises(AttributionWriteError):
        write_attribution_record({}, tmp_path)  # type: ignore[arg-type]


def test_sc_m8_no_raw_prompt_and_lineage_hash_format(tmp_path: Path) -> None:
    """TS11 / SC-M8 — no raw fixture prompt text; lineage hashes are SHA-256 hex."""
    record = build_attribution_record(
        attempt_count=1,
        task_type="implement",
        attribution_schema_version=ATTRIBUTION_SCHEMA_VERSION,
    )
    # Optional lineage hashes when present must be SHA-256 hex.
    lineage = hashlib.sha256(b"context").hexdigest()
    enriched = dict(record)
    enriched["author_lineage_hash"] = lineage
    enriched["reviewer_lineage_hash"] = lineage
    write_attribution_record(enriched, tmp_path)  # type: ignore[arg-type]
    stored = json.loads(
        (tmp_path / "attribution" / f"{record['task_record_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    blob = json.dumps(stored)
    assert RAW_PROMPT_FIXTURE not in blob
    assert "sk-test" not in blob
    assert SHA256_HEX.match(stored["author_lineage_hash"])
    assert SHA256_HEX.match(stored["reviewer_lineage_hash"])
