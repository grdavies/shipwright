"""PRD 342 R35 — bundle assets survive freeze/reconcile byte-identically on both backends."""
from __future__ import annotations

import json
import os
import subprocess
import warnings
from pathlib import Path

import pytest

import planning_bundle as pb
import planning_index_gen as pig
import planning_paths as pp
from planning_store import InRepoPublicBackend, IssueStoreBackend
from planning_linear_projection import freeze_from_canonical_body


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_unit(repo: Path, unit_id: str = "342-prd-bundle-r35") -> tuple[Path, str, dict[str, tuple[str, str]]]:
    unit_rel = f"docs/prds/{unit_id}"
    unit = repo / unit_rel
    body_rel = f"{unit_rel}/{unit_id}.md"
    body = (
        "---\n"
        f"id: {unit_id}\n"
        "type: prd\n"
        "status: planned\n"
        "title: Bundle R35\n"
        "visibility: public\n"
        "bundle: true\n"
        "---\n\n"
        "# Bundle R35\n"
    )
    _write(repo / body_rel, body)
    assets: dict[str, tuple[str, str]] = {}
    for role in pp.BUNDLE_ASSET_ROLES:
        rel = f"{unit_rel}/{pp.BUNDLE_ASSET_FILENAMES[role]}"
        text = f"# {role}\nUNIQUE-{role}-BYTES\n"
        _write(repo / rel, text)
        assets[role] = (rel, text)
    return unit, body_rel, assets


def _assert_canonical_stable(unit: Path, body_rel: str) -> None:
    selected = pig.body_file_for_unit_dir(unit)
    assert selected is not None
    assert selected.name == Path(body_rel).name
    assert pb.canonical_body_path(unit) == selected


@pytest.mark.parametrize("backend_name", ["in-repo-public", "issue-store"])
def test_bundle_assets_freeze_reconcile_lossless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend_name: str
) -> None:
    """R35 — put → freeze → get round-trip is byte-identical; canonical body unchanged."""
    repo = tmp_path / backend_name
    repo.mkdir()
    _git_init(repo)
    unit, body_rel, assets = _seed_unit(repo)
    unit_id = "342-prd-bundle-r35"
    _assert_canonical_stable(unit, body_rel)

    if backend_name == "issue-store":
        monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
        cfg = {
            "version": 1,
            "planning": {
                "store": {
                    "backend": "issue-store",
                    "issuesProvider": "github-issues",
                    "projectKey": "bundle-r35",
                }
            },
            "host": {"provider": "github"},
        }
        (repo / ".cursor" / "hooks" / "state").mkdir(parents=True)
        (repo / ".cursor" / "workflow.config.json").write_text(
            json.dumps(cfg), encoding="utf-8"
        )
        backend = IssueStoreBackend(repo, cfg)
    else:
        cfg = {"version": 1, "planning": {"store": {"backend": "in-repo-public"}}}
        (repo / ".cursor").mkdir(parents=True, exist_ok=True)
        (repo / ".cursor" / "workflow.config.json").write_text(
            json.dumps(cfg), encoding="utf-8"
        )
        backend = InRepoPublicBackend(repo, cfg)

    body_text = (repo / body_rel).read_text(encoding="utf-8")
    assert backend.put(unit_id, body_rel, body_text).verdict == "ok"
    for role, (rel, text) in assets.items():
        assert backend.put(unit_id, rel, text).verdict == "ok", role

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if backend_name == "issue-store":
            frozen = backend.freeze(unit_id, body_rel, distill=False)
            assert frozen.get("verdict") == "ok"
            assert frozen.get("locked") is True
        else:
            frozen = freeze_from_canonical_body(
                unit_id=unit_id, body_path=body_rel, body=body_text
            )
            assert frozen.get("verdict") == "pass"
            assert frozen.get("frozen") is True

        for role, (rel, text) in assets.items():
            got = backend.get(unit_id, rel)
            assert got.verdict == "ok", role
            assert got.content == text, role

        # Reconcile / re-select: selection and disposition remain stable.
        _assert_canonical_stable(unit, body_rel)
        result = pb.validate_unit_bundle(repo, unit)
        assert result["disposition"] == pb.DISPOSITION_COMPLETE
        assert result["bodyPath"] == body_rel.replace("\\", "/")

    assert not caught, f"unexpected warnings during freeze/reconcile: {caught}"
