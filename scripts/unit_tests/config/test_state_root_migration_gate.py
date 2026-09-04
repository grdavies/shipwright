"""Race and refusal tests for state-root migration gate (PRD 342 R13, R14, R54)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doctor  # noqa: E402
import shipwright_paths  # noqa: E402
import state_root_migrate as srm  # noqa: E402
import wave_lock  # noqa: E402


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    inv_src = REPO_ROOT / srm.INVENTORY_REL
    dest = root / srm.INVENTORY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(inv_src, dest)
    (root / "version.txt").write_text("1.0.0\n", encoding="utf-8")
    legacy = root / ".cursor" / "sw-deliver-runs"
    legacy.mkdir(parents=True)
    (legacy / "marker.txt").write_text("run-state\n", encoding="utf-8")
    return root


@pytest.fixture
def plugin_matched(repo: Path, tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin-matched"
    plugin.mkdir()
    dest = plugin / srm.INVENTORY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(repo / srm.INVENTORY_REL, dest)
    (plugin / "version.txt").write_text("1.0.0\n", encoding="utf-8")
    return plugin


@pytest.fixture
def plugin_skewed(repo: Path, tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin-skewed"
    plugin.mkdir()
    dest = plugin / srm.INVENTORY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads((repo / srm.INVENTORY_REL).read_text(encoding="utf-8"))
    data["entries"] = [
        {
            "family": "configuration",
            "legacyPath": ".cursor/workflow.config.json",
            "newPath": ".shipwright/DIFFERENT-workflow.config.json",
            "accessor": "workflow_config_path",
        }
    ]
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (plugin / "version.txt").write_text("0.9.0-stale\n", encoding="utf-8")
    return plugin


def test_skew_refusal_precedes_consent_gate(repo: Path, plugin_skewed: Path) -> None:
    """R54 — installed-plugin redirect-map skew refuses before consent is offered."""
    with pytest.raises(srm.StateRootMigrateError) as excinfo:
        srm.relocate(repo, confirm=False, plugin_root=plugin_skewed)
    err = excinfo.value
    assert err.code == "plugin-version-skew"
    payload = err.as_dict()
    assert payload["repoVersion"] == "1.0.0"
    assert payload["pluginVersion"] == "0.9.0-stale"
    assert payload["matched"] is False

    out = doctor.state_root_migrate_consent(
        repo, confirm=False, plugin_root=plugin_skewed
    )
    assert out.get("consentOffered") is False
    assert out.get("error") == "plugin-version-skew"
    assert not srm.fence_held(repo)


def test_fence_blocks_lock_acquired_after_clean_probe(repo: Path) -> None:
    """R14 — locks taken after a clean probe are blocked by the quiesce fence."""
    assert srm.assert_quiesced(repo) == []

    fence = srm.acquire_quiesce_fence(repo, holder="test-fence")
    assert fence["verdict"] == "pass"
    assert srm.fence_held(repo)

    blocked = wave_lock.acquire_run_lease(repo, "deliver-after-probe")
    assert blocked["verdict"] == "fail"
    assert blocked["error"] == "quiesce-fence-blocks-acquire"

    srm.release_quiesce_fence(repo, missing_ok=True)
    assert not srm.fence_held(repo)


def test_fence_release_on_completion_rollback_and_abnormal_exit(
    repo: Path, plugin_matched: Path
) -> None:
    """R14 — fence releases on completion, rollback (decline), and abnormal exit."""
    declined = srm.relocate(repo, confirm=False, plugin_root=plugin_matched)
    assert declined["verdict"] == "confirm-required"
    assert declined["fenceReleased"]["released"] is True
    assert not srm.fence_held(repo)
    assert (repo / ".cursor" / "sw-deliver-runs" / "marker.txt").is_file()

    completed = srm.relocate(repo, confirm=True, plugin_root=plugin_matched)
    assert completed["verdict"] == "pass"
    assert completed["fenceReleased"]["released"] is True
    assert not srm.fence_held(repo)
    assert (repo / ".shipwright" / "deliver-runs" / "marker.txt").is_file()
    assert not (repo / ".cursor" / "sw-deliver-runs" / "marker.txt").exists()

    legacy = repo / ".cursor" / "sw-graph-cache"
    legacy.mkdir(parents=True)
    (legacy / "cache.bin").write_text("x", encoding="utf-8")
    srm.acquire_quiesce_fence(repo, holder="abnormal")
    assert srm.fence_held(repo)
    srm._release_held_fences_atexit()  # noqa: SLF001 - abnormal-exit simulation
    assert not srm.fence_held(repo)


def test_doctor_reports_stale_fence(repo: Path) -> None:
    """R13/R14 — doctor surfaces a stale quiesce fence left behind."""
    srm.acquire_quiesce_fence(repo, holder="stale-owner")
    srm._HELD_FENCES.clear()  # noqa: SLF001
    assert srm.fence_held(repo)

    report = doctor.legacy_layout_report(repo)
    assert report["staleFence"] is not None
    assert report["verdict"] == "warn"
    assert report["remediation"]

    diagnosed = doctor.diagnose(repo)
    assert any("stale-state-root-migrate-fence" in i for i in diagnosed.get("issues", []))

    srm.release_quiesce_fence(repo, missing_ok=True)


def test_decline_leaves_legacy_paths_functional(repo: Path, plugin_matched: Path) -> None:
    """R13 — declining consent leaves the repository functional on legacy paths."""
    out = doctor.state_root_migrate_consent(
        repo, confirm=False, plugin_root=plugin_matched
    )
    assert out["verdict"] == "confirm-required"
    assert out["consentOffered"] is True
    assert (repo / ".cursor" / "sw-deliver-runs" / "marker.txt").is_file()
    assert not (repo / ".shipwright" / "deliver-runs").exists()
    assert shipwright_paths.deliver_runs_dir(repo) == repo / ".cursor" / "sw-deliver-runs"
