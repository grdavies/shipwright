"""Non-schema draft key refusal tests (PRD 324 phase 12 / R11, R14)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_sw_configure():
    spec = importlib.util.spec_from_file_location(
        "sw_configure",
        SCRIPT_DIR / "sw-configure.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_side_channel_keys_stripped_before_persist() -> None:
    mod = _load_sw_configure()
    draft = {
        "doc": {"afterTasks": "confirm"},
        "verifyGaps": ["verify.lint"],
        "projectTypeDetection": {"matches": ["python"], "ambiguous": False},
        "review": {"provider": "none"},
    }
    persistable = mod._strip_draft_side_channel(draft)
    assert "verifyGaps" not in persistable
    assert "projectTypeDetection" not in persistable
    assert persistable["doc"]["afterTasks"] == "confirm"
    assert mod.DRAFT_SIDE_CHANNEL_KEYS == frozenset({"verifyGaps", "projectTypeDetection"})


def test_written_config_validates_under_additional_properties_false(repo_root: Path) -> None:
    mod = _load_sw_configure()
    out = subprocess.check_output(
        [
            sys.executable,
            str(repo_root / "scripts/sw-configure.py"),
            "write-draft",
            "--accept-defaults",
            "--config",
            "/tmp/sw-init-draft-schema-fidelity.json",
        ],
        cwd=str(repo_root),
        text=True,
    )
    payload = json.loads(out)
    assert payload["verdict"] == "pass"
    draft_path = Path(payload["path"])
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    for key in mod.DRAFT_SIDE_CHANNEL_KEYS:
        assert key not in draft
    errors = mod._validate_config_document(repo_root, draft)
    assert errors == []


def test_detected_verify_gaps_produce_write_verify_routing(repo_root: Path) -> None:
    out = subprocess.check_output(
        [
            sys.executable,
            str(repo_root / "scripts/sw-configure.py"),
            "write-draft",
            "--accept-defaults",
            "--config",
            "/tmp/sw-init-draft-routing.json",
        ],
        cwd=str(repo_root),
        text=True,
    )
    payload = json.loads(out)
    side = payload.get("sideChannel") or {}
    if side.get("verifyGaps"):
        assert payload.get("writeVerifyRouting")
        assert "--write-verify" in payload["writeVerifyRouting"]
    assert "verifyGaps" not in json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
