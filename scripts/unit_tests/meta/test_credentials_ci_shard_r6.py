"""R6: credentials unit-test tree must appear in a required PR CI shard."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "core" / "sw-reference" / "pr-test-plan.manifest.json"
CREDENTIALS_PATH = "scripts/unit_tests/credentials"


def _required_fixtures_covering_credentials(manifest: dict) -> list[dict]:
    hits: list[dict] = []
    for fixture in manifest.get("fixtures") or []:
        if fixture.get("classification") != "required":
            continue
        args = fixture.get("args") or []
        if any(
            isinstance(a, str)
            and (a == CREDENTIALS_PATH or a.startswith(CREDENTIALS_PATH + "/"))
            for a in args
        ):
            hits.append(fixture)
    return hits


def test_credentials_tree_listed_under_exactly_one_required_shard() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    hits = _required_fixtures_covering_credentials(manifest)
    assert hits, (
        f"{CREDENTIALS_PATH} must be listed under a required-classification "
        "fixture in pr-test-plan.manifest.json (PRD 083 R6)"
    )
    shards = {h.get("ciShard") for h in hits}
    assert None not in shards, f"credentials fixtures missing ciShard: {hits}"
    assert len(shards) == 1, f"credentials must map to exactly one required shard, got {shards}"


def test_generated_workflow_invokes_credentials_pytest_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pr-test-plan-ci.yml").read_text(
        encoding="utf-8"
    )
    assert CREDENTIALS_PATH in workflow, (
        f"generated pr-test-plan-ci.yml must invoke {CREDENTIALS_PATH} "
        "(regenerate after manifest edit)"
    )
