"""PRD 338 R30 — curated seed docs parity and invalid top-level draft key rejection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from init_profile_report import (  # noqa: E402
    CURATED_DOCUMENTATION_PATHS,
    INVALID_TOP_LEVEL_DRAFT_KEY_FIXTURES,
    SCHEMA_REL,
    curated_seed_documentation_snippets,
    curated_writable_leaf_keys,
    extract_markdown_json_fragments,
    greenfield_curated_patch,
    invalid_top_level_keys,
    leaf_get,
    load_json,
    strip_invalid_top_level_keys,
)


def test_curated_seed_docs_parity(repo_root: Path) -> None:
    """curated_seed_docs_parity — command/docs examples match write-draft seeds."""
    patch = greenfield_curated_patch()
    snippets = curated_seed_documentation_snippets()

    for path, expected in curated_writable_leaf_keys():
        assert leaf_get(patch, path) == expected

    sw_init = (repo_root / "core/commands/sw-init.md").read_text(encoding="utf-8")
    config_doc = (repo_root / "core/documentation/configuration.md").read_text(encoding="utf-8")

    for rel in CURATED_DOCUMENTATION_PATHS:
        assert (repo_root / rel).is_file()

    init_fragments = extract_markdown_json_fragments(sw_init)
    assert any(fragment.get("delegation", {}).get("mode") == patch["delegation"]["mode"] for fragment in init_fragments)
    assert any(
        fragment.get("orchestration", {}).get("planPolicy") == patch["orchestration"]["planPolicy"]
        for fragment in init_fragments
    )
    assert any(
        fragment.get("memory", {}).get("guardrails") == patch["memory"]["guardrails"]
        for fragment in init_fragments
    )
    assert patch["delegation"]["mode"] in sw_init
    assert patch["orchestration"]["planPolicy"] in sw_init
    assert '"enforceBeforeSubmit": true' in sw_init
    assert '"requireRuleClass": false' in sw_init
    assert "bind-only" not in sw_init or "Tighten to" in config_doc
    assert "Greenfield init posture" in config_doc
    assert patch["delegation"]["mode"] in config_doc
    assert patch["orchestration"]["planPolicy"] in config_doc


def test_invalid_top_level_draft_keys_rejected(repo_root: Path) -> None:
    """Every invalid top-level draft key is stripped before persistence."""
    schema = load_json(repo_root / SCHEMA_REL)
    patch = greenfield_curated_patch()

    for bad_key in INVALID_TOP_LEVEL_DRAFT_KEY_FIXTURES:
        polluted = dict(patch)
        polluted[bad_key] = {"enforceBeforeSubmit": True, "requireRuleClass": False}
        assert bad_key in invalid_top_level_keys(polluted, schema)
        cleaned, rejected = strip_invalid_top_level_keys(polluted, schema)
        assert bad_key in rejected
        assert bad_key not in cleaned
        assert cleaned["memory"]["guardrails"]["enforceBeforeSubmit"] is True


def test_write_draft_emits_only_schema_valid_curated_keys(repo_root: Path) -> None:
    out = subprocess.check_output(
        [
            sys.executable,
            str(repo_root / "scripts/sw-configure.py"),
            "write-draft",
            "--accept-defaults",
            "--config",
            "/tmp/sw-init-prd338-profile-seeds.json",
        ],
        cwd=str(repo_root),
        text=True,
    )
    payload = json.loads(out)
    assert payload["verdict"] == "pass"
    draft = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    schema = load_json(repo_root / SCHEMA_REL)

    assert invalid_top_level_keys(draft, schema) == []
    for bad_key in INVALID_TOP_LEVEL_DRAFT_KEY_FIXTURES:
        assert bad_key not in draft

    for path, expected in curated_writable_leaf_keys():
        assert leaf_get(draft, path) == expected

    jsonschema = pytest.importorskip("jsonschema", reason="optional schema engine")
    jsonschema.validate(draft, schema, cls=jsonschema.Draft7Validator)
