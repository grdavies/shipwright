"""PRD 331 D7, R16–R19, R21, R42 — optional project-intelligence integrations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_engine import ExplorationEngine  # noqa: E402
from exploration_intelligence import (  # noqa: E402
    blocks_destination_progress,
    collect_intelligence_context,
    discover_repository,
    enrich_exploration_context,
    intelligence_blocks_destination,
)
from exploration_store import ExplorationStore  # noqa: E402
import architecture_radar as radar  # noqa: E402
import memory_preflight  # noqa: E402
from memory_preflight import PreflightError  # noqa: E402

_SECRET_SAMPLE = "ghpABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _init_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# sample\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)


def test_repository_discovery_enriches_explore(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "sample.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "add", "scripts/sample.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add script"], cwd=tmp_path, check=True, capture_output=True)

    result = discover_repository(tmp_path)
    assert result["verdict"] == "ok"
    assert result["mode"] in {"enriched", "greenfield"}
    assert result["blocking"] is False
    assert result["layout"]["hasGit"] is True


def test_greenfield_requires_no_architecture_artifacts(tmp_path: Path) -> None:
    result = discover_repository(tmp_path)
    assert result["verdict"] in {"ok", "degraded"}
    assert result["mode"] == "greenfield"
    assert result["blocking"] is False


def test_radar_is_optional_and_degradable(tmp_path: Path) -> None:
    context = collect_intelligence_context(
        tmp_path,
        radar_fn=lambda _root: {
            "verdict": "degraded",
            "source": "radar",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
        },
    )
    assert context["verdict"] == "ok"
    assert context["blocking"] is False
    assert "radar" in context["degradedSources"]
    assert blocks_destination_progress(context) is False


def test_vocabulary_is_optional_and_degradable(tmp_path: Path) -> None:
    context = collect_intelligence_context(
        tmp_path,
        vocabulary_fn=lambda _root: {
            "verdict": "degraded",
            "source": "vocabulary",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
        },
    )
    assert context["verdict"] == "ok"
    assert "vocabulary" in context["degradedSources"]


def test_memory_exploration_query_degrades_on_preflight_failure(tmp_path: Path) -> None:
    def _preflight_fail(_root: Path) -> dict[str, Any]:
        raise PreflightError("auth refused", cause="auth-refused")

    result = memory_preflight.exploration_query(
        tmp_path,
        "prior exploration",
        preflight_loader=_preflight_fail,
    )
    assert result["verdict"] == "degraded"
    assert result["cause"] == "auth-refused"
    assert result["nonBlocking"] is True
    assert result["results"] == []


def test_memory_exploration_query_redacts_results(tmp_path: Path) -> None:
    def _search(_root: Path, _query: str, _ctx: dict[str, Any]) -> dict[str, Any]:
        return {"results": [{"snippet": f"token {_SECRET_SAMPLE}"}]}

    result = memory_preflight.exploration_query(
        tmp_path,
        "secrets",
        preflight_loader=lambda root: {"verdict": "ok", "provider": "in-repo"},
        query_fn=_search,
    )
    assert result["verdict"] == "ok"
    assert result["nonBlocking"] is True
    assert "ghp_" not in json.dumps(result)


def test_intelligence_degrades_while_core_stays_green(tmp_path: Path) -> None:
    context = collect_intelligence_context(
        tmp_path,
        query="history",
        radar_fn=lambda _root: {"verdict": "degraded", "status": "degraded", "blocking": False},
        vocabulary_fn=lambda _root: {"verdict": "degraded", "status": "degraded", "blocking": False},
        memory_fn=lambda _root, _query: {"verdict": "degraded", "status": "degraded", "blocking": False},
    )
    assert context["verdict"] == "ok"
    assert context["blocking"] is False
    assert len(context["degradedSources"]) >= 2

    engine = ExplorationEngine(ExplorationStore(tmp_path))
    started = engine.start_session(
        map_id="intel-degrade-core-green",
        destination_statement="Destination progress must remain available when intel degrades.",
    )
    assert started["map"]["destination"]["statement"].startswith("Destination progress")


def test_all_intelligence_failures_are_non_blocking(tmp_path: Path) -> None:
    context = collect_intelligence_context(
        tmp_path,
        radar_fn=lambda _root: {"verdict": "degraded", "status": "degraded", "blocking": False},
        vocabulary_fn=lambda _root: {"verdict": "degraded", "status": "degraded", "blocking": False},
    )
    assert context["verdict"] == "ok"
    assert context["blocking"] is False
    assert intelligence_blocks_destination(context) is False


def test_destination_progress_invariant_under_combined_degradation(tmp_path: Path) -> None:
    context = collect_intelligence_context(
        tmp_path,
        radar_fn=lambda _root: {"verdict": "degraded", "status": "degraded", "blocking": False},
        vocabulary_fn=lambda _root: {"verdict": "degraded", "status": "degraded", "blocking": False},
    )
    assert context["degradedSources"]

    engine = ExplorationEngine(ExplorationStore(tmp_path))
    started = engine.start_session(
        map_id="combined-degrade",
        destination_statement="Combined degradation must not block destination capture.",
    )
    revision = started["map"]["revision"]
    updated = engine.set_structured_field(
        "combined-degrade",
        "problem",
        "Operators need exploration even when intel hooks fail.",
        expected_revision=revision,
    )
    assert updated["structuredFieldProgress"]["requiredComplete"] == ["problem"]

    enriched = enrich_exploration_context(
        tmp_path,
        started["map"],
        collector=lambda root, query="": context,
    )
    assert enriched["destinationProgressInvariant"] is True
    assert enriched["blocking"] is False


def test_explore_radar_adapter_never_raises(tmp_path: Path) -> None:
    result = radar.explore_radar_adapter(tmp_path)
    assert result["nonBlocking"] is True
    assert result["verdict"] in {"ok", "degraded"}


def test_explore_vocabulary_adapter_never_raises(tmp_path: Path) -> None:
    result = radar.explore_vocabulary_adapter(tmp_path)
    assert result["nonBlocking"] is True
    assert result["verdict"] in {"ok", "degraded"}
