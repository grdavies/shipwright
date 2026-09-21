"""PRD 366 phase 9 — full fixture on the wheel-installed runtime (R8, R12)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning.backends import issues_helpers as ih
from prd366_fixture_lib import (
    PRD366_PRIVATE_PILOT_DIR,
    WitnessUnavailableError,
    load_committed_family_map,
    load_json,
    load_preserved_full_fixture_pair,
    private_pilot_tree_gitignored,
    require_witness_source,
    validate_redacted_families,
)
from runtime_requirements import sync_runtime_bundle
from secret_scan import load_allowlist, scan_text

FIXTURE_LINEAR = scripts / "test" / "fixtures" / "linear"
REDACTED_FAMILIES = FIXTURE_LINEAR / "prd366-redacted-comparison-families.json"


def _built_wheels(wheel_dir: Path) -> list[Path]:
    return sorted(wheel_dir.glob("shipwright*.whl"))


def _wheel_scripts_dir(tmp_path: Path, repo_root: Path) -> Path:
    sync_runtime_bundle(repo_root)
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheel_dir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    wheels = _built_wheels(wheel_dir)
    assert wheels, "expected shipwright*.whl"
    target = tmp_path / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheels[0]),
        ],
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, install.stderr or install.stdout
    staged = target / "sw" / "scripts"
    assert staged.is_dir(), f"missing wheel scripts tree: {staged}"
    return staged


def _run_wheel_predicate_probe(
    staged_scripts: Path,
    *,
    submitted: str,
    refetched: str,
) -> dict[str, Any]:
    payload = {"submitted": submitted, "refetched": refetched}
    code = textwrap.dedent(
        f"""
        import json
        import sys
        from pathlib import Path

        staged = Path({json.dumps(str(staged_scripts))})
        sys.path.insert(0, str(staged))
        from planning.backends.issues_helpers import (
            reconstruct_bodies_equivalent,
            verify_reconstruct_before_ok,
        )
        from planning_linear_canonical import linear_public_markdown_equivalent

        pair = json.loads({json.dumps(json.dumps(payload))})
        submitted = pair["submitted"]
        refetched = pair["refetched"]

        class _Ps:
            @staticmethod
            def strip_markers_and_edges(text: str) -> str:
                return text

            @staticmethod
            def reassemble_body(body: str, comments: list[object], *, linear_bind: bool = False) -> str:
                return body

            @staticmethod
            def fail(message: str, **_kwargs: object) -> None:
                raise AssertionError(message)

        class _Record:
            id = "tie-8-witness"
            body = refetched
            comments: list[object] = []
            comments_complete = True

        class _Client:
            def issue_get(self, _issue_id: str) -> _Record:
                return _Record()

        equiv = linear_public_markdown_equivalent(submitted, refetched)
        reconstruct = reconstruct_bodies_equivalent(
            submitted, refetched, issues_provider="linear", ps_mod=_Ps
        )
        verify_reconstruct_before_ok(
            _Client(),
            _Record(),
            pre_chunk_body=submitted,
            issues_provider="linear",
            ps_mod=_Ps,
        )
        print(
            json.dumps(
                {{
                    "linearPublicMarkdownEquivalent": equiv,
                    "reconstructBodiesEquivalent": reconstruct,
                    "wheelScriptsRoot": str(staged),
                }}
            )
        )
        """
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONPATH"] = str(staged_scripts.resolve())
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(staged_scripts.parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout.strip())


class TestPrd366Phase9FixtureHygiene:
    def test_redacted_linear_fixtures_are_family_minimal(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        assert validate_redacted_families(data) == []
        family_map = load_committed_family_map(REPO_ROOT)
        from prd366_fixture_lib import family_map_covers_redacted_pairs

        assert family_map_covers_redacted_pairs(family_map, data) == []

    def test_private_pilot_bytes_stay_gitignored(self) -> None:
        if not PRD366_PRIVATE_PILOT_DIR.exists():
            pytest.skip("private pilot tree absent in checkout")
        assert private_pilot_tree_gitignored(REPO_ROOT)

    def test_committed_linear_fixture_tree_secret_scan_clean(self) -> None:
        allowlist = load_allowlist(REPO_ROOT)
        for path in sorted(FIXTURE_LINEAR.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in {".json", ".md", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8")
            findings = scan_text(
                text, allowlist=allowlist, path=str(path.relative_to(REPO_ROOT))
            )
            assert findings == [], f"secret scan findings in {path}: {findings}"


class TestPrd366Phase9FullFixtureWheelInstalledRuntime:
    def test_full_preserved_fixture_both_predicates_on_wheel(
        self, tmp_path: Path, repo_root: Path
    ) -> None:
        try:
            pair = load_preserved_full_fixture_pair(repo_root)
        except (WitnessUnavailableError, FileNotFoundError) as exc:
            pytest.skip(str(exc))
        assert pair.submitted != pair.refetched or pair.submitted.strip()
        staged = _wheel_scripts_dir(tmp_path, repo_root)
        repo_scripts = str((repo_root / "scripts").resolve())
        assert repo_scripts not in os.environ.get("PYTHONPATH", "")
        out = _run_wheel_predicate_probe(
            staged,
            submitted=pair.submitted,
            refetched=pair.refetched,
        )
        assert out["linearPublicMarkdownEquivalent"] is True
        assert out["reconstructBodiesEquivalent"] is True
        assert out["wheelScriptsRoot"].endswith("/sw/scripts")

    def test_isolated_redacted_family_is_not_r8_witness(self) -> None:
        """R8 witness is the full preserved pair — not a single redacted family row."""
        data = load_json(REDACTED_FAMILIES)
        row = data["pairs"][0]
        excerpt = row["submitted"]
        assert len(excerpt) < 500
        assert "acceptance criteria" not in excerpt.lower() or len(excerpt) < 120

    def test_witness_resolution_matches_require(self, repo_root: Path) -> None:
        try:
            require_witness_source(repo_root)
        except WitnessUnavailableError:
            pytest.skip("no witness source in this environment")
