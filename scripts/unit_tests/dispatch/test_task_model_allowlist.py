"""Task model allowlist enforcement fixtures (PRD 073 phase 4 / R6/R7)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from task_model_allowlist_lib import (
    CAUSE_NOT_ALLOWLISTED,
    canonicalize_task_model_id,
    enforce_task_model_allowlist,
    load_task_model_allowlist,
)


def _run_resolve(repo_root: Path, *, tier: str, config: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "resolve-model-tier.py"),
            "--tier",
            tier,
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(repo_root / "scripts")},
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    return proc.returncode, payload


def _run_dispatch(
    repo_root: Path,
    *,
    agent: str,
    parent_model: str,
    config: Path,
) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "dispatch-check.py"),
            "--agent",
            agent,
            "--parent-model",
            parent_model,
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(repo_root / "scripts")},
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    return proc.returncode, payload


def test_allowlist_loads(repo_root: Path) -> None:
    doc = load_task_model_allowlist(repo_root)
    assert "composer-2.5" in doc.allowed
    assert doc.aliases.get("gpt-5.5-medium") == "gpt-5.6-terra-medium"


def test_canonicalize_pass_alias_and_fail(repo_root: Path) -> None:
    doc = load_task_model_allowlist(repo_root)
    canonical, alias_from = canonicalize_task_model_id("composer-2.5", doc)
    assert canonical == "composer-2.5"
    assert alias_from is None

    canonical, alias_from = canonicalize_task_model_id("gpt-5.5-medium", doc)
    assert canonical == "gpt-5.6-terra-medium"
    assert alias_from == "gpt-5.5-medium"

    canonical, alias_from = canonicalize_task_model_id("totally-unknown-model", doc)
    assert canonical is None
    assert alias_from is None


def test_enforce_fail_closed(repo_root: Path) -> None:
    result = enforce_task_model_allowlist("not-a-real-model", root=repo_root)
    assert result["verdict"] == "fail"
    assert result["cause"] == CAUSE_NOT_ALLOWLISTED


def test_resolve_model_tier_maps_alias(tmp_path: Path, repo_root: Path) -> None:
    cfg = tmp_path / "workflow.config.json"
    cfg.write_text(
        json.dumps(
            {
                "models": {
                    "tiers": {
                        "cheap": "composer-2.5-fast",
                        "build": "composer-2.5",
                        "mid": "gpt-5.5-medium",
                        "deep": "claude-opus-4-8-thinking-high",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    ec, payload = _run_resolve(repo_root, tier="mid", config=cfg)
    assert ec == 0
    assert payload["modelId"] == "gpt-5.6-terra-medium"
    assert payload.get("aliasFrom") == "gpt-5.5-medium"


def test_resolve_model_tier_rejects_unknown(tmp_path: Path, repo_root: Path) -> None:
    cfg = tmp_path / "workflow.config.json"
    cfg.write_text(
        json.dumps({"models": {"tiers": {"build": "definitely-not-allowlisted"}}}),
        encoding="utf-8",
    )
    ec, payload = _run_resolve(repo_root, tier="build", config=cfg)
    assert ec == 20
    assert payload.get("cause") == CAUSE_NOT_ALLOWLISTED


def test_dispatch_check_rejects_non_allowlisted_config(tmp_path: Path, repo_root: Path) -> None:
    cfg = tmp_path / "workflow.config.json"
    cfg.write_text(
        json.dumps(
            {
                "models": {
                    "tiers": {
                        "cheap": "composer-2.5-fast",
                        "build": "composer-2.5",
                        "mid": "gpt-5.6-terra-medium",
                        "deep": "claude-opus-4-8-thinking-high",
                    },
                    "roles": {"builder": "build", "reviewer": "deep"},
                    "routing": {"agents": {"sw-coherence-reviewer": "build"}},
                },
                "communication": {"defaultIntensity": "lite"},
            }
        ),
        encoding="utf-8",
    )
    bad = dict(json.loads(cfg.read_text(encoding="utf-8")))
    bad["models"]["routing"]["agents"]["sw-coherence-reviewer"] = "build"
    bad["models"]["tiers"]["build"] = "legacy-unlisted-model"
    bad_cfg = tmp_path / "bad.json"
    bad_cfg.write_text(json.dumps(bad), encoding="utf-8")

    ec, payload = _run_dispatch(
        repo_root,
        agent="sw-coherence-reviewer",
        parent_model="claude-opus-4-8-thinking-high",
        config=bad_cfg,
    )
    assert ec == 20
    assert payload.get("cause") == CAUSE_NOT_ALLOWLISTED


def test_dispatch_check_passes_allowlisted_agent(tmp_path: Path, repo_root: Path) -> None:
    cfg = tmp_path / "workflow.config.json"
    cfg.write_text(
        json.dumps(
            {
                "models": {
                    "tiers": {
                        "cheap": "composer-2.5-fast",
                        "build": "composer-2.5",
                        "mid": "gpt-5.6-terra-medium",
                        "deep": "claude-opus-4-8-thinking-high",
                    },
                    "roles": {"builder": "build", "reviewer": "deep"},
                    "routing": {"agents": {"sw-coherence-reviewer": "build"}},
                },
                "communication": {"defaultIntensity": "lite"},
            }
        ),
        encoding="utf-8",
    )
    ec, payload = _run_dispatch(
        repo_root,
        agent="sw-coherence-reviewer",
        parent_model="claude-opus-4-8-thinking-high",
        config=cfg,
    )
    assert ec == 0
    assert payload.get("verdict") == "pass"
    assert payload.get("modelId") == "composer-2.5"


def test_models_tiering_doc_mentions_allowlist_maintenance(repo_root: Path) -> None:
    text = (repo_root / "core/sw-reference/models-tiering.md").read_text(encoding="utf-8")
    assert "task-model-allowlist.json" in text
    assert "maintenance cadence" in text.lower()
