"""PRD 325 phase 7 / PRD 338 R31 — docs-currency consumer and profile selection."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[1]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))


def _load_docs_currency_gate():
    spec = importlib.util.spec_from_file_location(
        "docs_currency_gate",
        scripts / "docs-currency-gate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gate_argv(root: Path, state: dict, plan: dict | None = None) -> list[str]:
    state_path = root / "state.json"
    plan_path = root / "plan.json"
    state_path.write_text(json.dumps(state))
    plan_path.write_text(json.dumps(plan or {"prd_number": state.get("prd_number", "325")}))
    return [
        "docs-currency-gate.py",
        str(root),
        str(root),
        str(state_path),
        str(plan_path),
    ]


def _consumer_profile_resolution() -> dict[str, object]:
    return {
        "profile": "consumer",
        "rolloutBlocked": False,
        "consumerRepo": True,
        "runArtifactCurrency": False,
        "r24": {"ready": True, "posture": "consumer", "reason": "consumer"},
        "r28": {"ready": True, "source": "consumer-no-trusted-scripts"},
    }


def _plugin_self_profile_resolution() -> dict[str, object]:
    return {
        "profile": "plugin-self",
        "rolloutBlocked": False,
        "consumerRepo": False,
        "runArtifactCurrency": True,
        "r24": {"ready": True, "posture": "plugin-self", "reason": "sentinel-authoritative"},
        "r28": {"ready": True, "source": "self-repo-markers"},
    }


def test_consumer_skip_payload_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "consumer-fixture"},
        "phases": {"1": {"status": "green-merged"}},
    }

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=_consumer_profile_resolution()), patch(
        "wave_living_docs.living_doc_write_banned", return_value=True
    ), patch("wave_living_docs.derive_index_status", return_value="in-progress"), patch(
        "wave_living_docs.read_index_status_evidence",
        return_value={"status": "in-progress"},
    ), patch(
        "wave_living_docs.read_completion_evidence", return_value={"prd_id": "325"}
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ):
        rc = dcg.main(_gate_argv(tmp_path, state))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["verdict"] == "pass"
    assert payload["profile"] == "consumer"
    skipped = payload["skipped"]
    assert len(skipped) == 4
    assert {row["reason"] for row in skipped} == {"consumer-repo"}
    assert {row["check"] for row in skipped} == set(dcg.INTERNAL_ARTIFACT_CURRENCY_CHECKS)
    assert payload["artifactSet"]


def test_self_repo_runs_artifact_currency_fail_closed(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "shipwright"},
        "phases": {"1": {"status": "green-merged"}},
    }
    index = tmp_path / "docs" / "prds" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text("| # | Unit | Status | PRD status |\n| 325 | x | y | in-progress |\n")

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=_plugin_self_profile_resolution()), patch(
        "wave_living_docs.living_doc_write_banned", return_value=False
    ), patch("wave_living_docs.derive_index_status", return_value="in-progress"), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ), patch(
        "docs_currency_081.check_release_guide_artifacts",
        return_value=[{"kind": "guide-stale", "id": "layout"}],
    ):
        with pytest.raises(SystemExit) as exc:
            dcg.main(_gate_argv(tmp_path, state))
    assert exc.value.code == 1


def test_skip_flag_composes_on_self_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "shipwright"},
        "phases": {"1": {"status": "pending"}},
    }
    index = tmp_path / "docs" / "prds" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text("| # | Unit | Status | PRD status |\n| 325 | x | y | in-progress |\n")
    argv = _gate_argv(tmp_path, state) + ["--skip-artifact-currency"]

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=_plugin_self_profile_resolution()), patch(
        "wave_living_docs.living_doc_write_banned", return_value=False
    ), patch("wave_living_docs.derive_index_status", return_value="in-progress"), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ), patch(
        "docs_currency_081.check_release_guide_artifacts",
        side_effect=AssertionError("should be skipped"),
    ):
        rc = dcg.main(argv)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["verdict"] == "pass"
    assert payload["profile"] == "plugin-self"
    assert {row["reason"] for row in payload["skipped"]} == {"skip-artifact-currency"}


def test_consumer_store_evidence_avoids_index_missing_row(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "consumer-fixture"},
        "phases": {"1": {"status": "pending"}},
    }

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=_consumer_profile_resolution()), patch(
        "wave_living_docs.living_doc_write_banned", return_value=False
    ), patch("wave_living_docs.derive_index_status", return_value="not-started"), patch(
        "wave_living_docs.read_index_status_evidence",
        return_value={"status": "not-started"},
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ):
        rc = dcg.main(_gate_argv(tmp_path, state))

    assert rc == 0


def test_consumer_vendored_plugin_passes_without_plugin_only_docs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "338",
        "target": {"slug": "consumer-vendored-plugin"},
        "phases": {"1": {"status": "pending"}},
    }
    resolution = {
        "profile": "consumer",
        "rolloutBlocked": False,
        "consumerRepo": True,
        "runArtifactCurrency": False,
        "r24": {"ready": True, "posture": "consumer", "reason": "consumer"},
        "r28": {
            "ready": True,
            "source": "consumer-dist-trust",
            "scriptsSource": "plugin-local-dist",
            "trustDigest": "abc123",
        },
    }

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=resolution), patch(
        "wave_living_docs.living_doc_write_banned", return_value=True
    ), patch("wave_living_docs.derive_index_status", return_value="not-started"), patch(
        "wave_living_docs.read_index_status_evidence",
        return_value={"status": "not-started"},
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ), patch(
        "docs_currency_081.check_release_guide_artifacts",
        side_effect=AssertionError("consumer profile must skip plugin-only guides"),
    ), patch(
        "docs_currency_memory.check_memory_doc_currency",
        side_effect=AssertionError("consumer profile must skip plugin-only memory docs"),
    ):
        rc = dcg.main(_gate_argv(tmp_path, state))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["profile"] == "consumer"
    assert payload["skipped"]


def test_rollout_blocks_when_r24_readiness_absent(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "338",
        "target": {"slug": "ambiguous-posture"},
        "phases": {"1": {"status": "pending"}},
    }
    blocked = {
        "profile": None,
        "rolloutBlocked": True,
        "blockReason": "r24-not-ready",
        "r24": {"ready": False, "reason": "ambiguous layout"},
    }

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=blocked):
        with pytest.raises(SystemExit) as exc:
            dcg.main(_gate_argv(tmp_path, state))
    assert exc.value.code == 2


def test_rollout_blocks_when_r28_readiness_absent(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "338",
        "target": {"slug": "consumer-dist-untrusted"},
        "phases": {"1": {"status": "pending"}},
    }
    blocked = {
        "profile": None,
        "rolloutBlocked": True,
        "blockReason": "r28-not-ready",
        "r24": {"ready": True, "posture": "consumer", "reason": "consumer"},
        "r28": {"ready": False, "reason": "r28-dist-trust:operator trust store missing"},
    }

    with patch.object(dcg, "resolve_docs_currency_profile", return_value=blocked):
        with pytest.raises(SystemExit) as exc:
            dcg.main(_gate_argv(tmp_path, state))
    assert exc.value.code == 2


def test_resolve_docs_currency_profile_selects_consumer(repo_root: Path) -> None:
    dcg = _load_docs_currency_gate()
    spoof = repo_root.parent / "consumer-spoof"
    spoof.mkdir(exist_ok=True)
    resolution = dcg.resolve_docs_currency_profile(spoof)
    assert resolution["profile"] == "consumer"
    assert resolution["runArtifactCurrency"] is False


def test_resolve_docs_currency_profile_selects_plugin_self(repo_root: Path) -> None:
    dcg = _load_docs_currency_gate()
    resolution = dcg.resolve_docs_currency_profile(repo_root)
    assert resolution["profile"] == "plugin-self"
    assert resolution["runArtifactCurrency"] is True


def test_resolve_docs_currency_profile_blocks_ambiguous_sentinel(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    ambiguous = tmp_path / "ambiguous"
    ambiguous.mkdir()
    (ambiguous / ".shipwright-dev").write_text("# sentinel only\n", encoding="utf-8")
    resolution = dcg.resolve_docs_currency_profile(ambiguous)
    assert resolution["rolloutBlocked"] is True
    assert resolution["blockReason"] == "r24-not-ready"
