"""PRD 330 R6/R14 — ProjectBaseline@v1 brownfield synthesis fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import project_baseline as pb  # noqa: E402

BASELINE_SCHEMA_REL = Path("core/sw-reference/project-baseline.schema.json")
COMMANDS_DIRS = (
    Path("core/commands"),
    Path("commands"),
    Path("dist/cursor/commands"),
    Path("dist/claude-code/commands"),
)


def _obs(
    key: str,
    claim: str,
    uri: str,
    *,
    confidence: str = "high",
) -> dict:
    return {
        "key": key,
        "claim": claim,
        "confidence": confidence,
        "sourceEvidence": {"uri": uri},
    }


def _maybe_validate_jsonschema(document: dict, schema: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema", reason="optional schema engine")
    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)


@pytest.fixture
def baseline_schema(repo_root: Path) -> dict:
    path = repo_root / BASELINE_SCHEMA_REL
    assert path.is_file()
    return json.loads(path.read_text(encoding="utf-8"))


def test_zero_sources_yields_empty_draft(baseline_schema: dict) -> None:
    doc = pb.synthesize_baseline(
        [],
        created_at="2026-08-25T00:00:00Z",
    )
    assert doc["status"] == "draft"
    assert doc["version"] == "ProjectBaseline@v1"
    assert doc["facts"] == []
    assert "conflicts" not in doc or doc["conflicts"] == []
    assert doc["confidence"] == "unknown"
    assert pb.validate_baseline(doc) == []
    assert baseline_schema["title"] == "ProjectBaseline@v1"


def test_one_source_retains_evidence_and_confidence() -> None:
    doc = pb.synthesize_baseline(
        [
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/pyproject.toml",
                confidence="high",
            )
        ],
        created_at="2026-08-25T00:00:00Z",
    )
    assert doc["status"] == "draft"
    assert len(doc["facts"]) == 1
    fact = doc["facts"][0]
    assert fact["claim"] == "Primary runtime appears to be Python."
    assert fact["sourceEvidence"]["uri"] == "file://repo/pyproject.toml"
    assert fact["confidence"] == "high"
    assert "conflicts" not in doc
    assert pb.validate_baseline(doc) == []


def test_many_sources_agreeing_collapse_to_facts() -> None:
    doc = pb.synthesize_baseline(
        [
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/pyproject.toml",
                confidence="high",
            ),
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/setup.py",
                confidence="medium",
            ),
            _obs(
                "docs.readme",
                "Repository includes a README.md.",
                "file://repo/README.md",
                confidence="medium",
            ),
        ],
        created_at="2026-08-25T00:00:00Z",
    )
    assert doc["status"] == "draft"
    assert len(doc["facts"]) == 2
    assert "conflicts" not in doc
    uris = {f["sourceEvidence"]["uri"] for f in doc["facts"]}
    assert "file://repo/pyproject.toml" in uris or "file://repo/setup.py" in uris
    assert "file://repo/README.md" in uris
    assert pb.validate_baseline(doc) == []


def test_conflicts_preserved_for_contradictory_observations() -> None:
    doc = pb.synthesize_baseline(
        [
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/pyproject.toml",
                confidence="high",
            ),
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Node.js.",
                "file://repo/package.json",
                confidence="high",
            ),
        ],
        created_at="2026-08-25T00:00:00Z",
    )
    assert doc["status"] == "draft"
    assert doc["facts"] == []
    assert len(doc["conflicts"]) == 1
    conflict = doc["conflicts"][0]
    assert conflict["status"] == "open"
    claims = {obs["claim"] for obs in conflict["observations"]}
    assert "Primary runtime appears to be Python." in claims
    assert "Primary runtime appears to be Node.js." in claims
    assert all(obs["sourceEvidence"]["uri"] for obs in conflict["observations"])
    assert doc["confidence"] == "low"
    assert pb.validate_baseline(doc) == []


def test_discover_and_synthesize_from_tmp_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    observations = pb.discover_observations(tmp_path, accessed_at="2026-08-25T00:00:00Z")
    assert len(observations) >= 2
    doc = pb.synthesize_from_root(tmp_path, created_at="2026-08-25T00:00:00Z")
    assert doc["status"] == "draft"
    assert doc["facts"]
    assert pb.validate_baseline(doc) == []


def test_write_draft_does_not_promote(tmp_path: Path) -> None:
    doc = pb.synthesize_baseline(
        [_obs("docs.readme", "Repository includes a README.md.", "file://repo/README.md")],
        created_at="2026-08-25T00:00:00Z",
    )
    result = pb.write_draft(tmp_path, doc)
    assert result["verdict"] == "pass"
    assert result["promoted"] is False
    assert result["status"] == "draft"
    draft = tmp_path / pb.DEFAULT_DRAFT_REL
    assert draft.is_file()
    written = json.loads(draft.read_text(encoding="utf-8"))
    assert written["status"] == "draft"
    doctrine = tmp_path / pb.DEFAULT_DOCTRINE_REL
    assert not doctrine.exists()


def test_refuse_promote_even_with_confirm() -> None:
    result = pb.refuse_promote(confirm=True)
    assert result["verdict"] == "fail"
    assert result["error"] == "auto-promote-refused"
    assert result["promoted"] is False
    assert result["confirm"] is True


def test_cli_promote_refuses(repo_root: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/project_baseline.py"), "promote", "--confirm"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert payload["promoted"] is False
    assert payload["error"] == "auto-promote-refused"


def test_cli_synthesize_zero_and_schema_valid(repo_root: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    out = tmp_path / "baseline.json"
    obs_file = tmp_path / "obs.json"
    obs_file.write_text("[]\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/project_baseline.py"),
            "--root",
            str(empty),
            "synthesize",
            "--observations",
            str(obs_file),
            "--out",
            str(out),
            "--created-at",
            "2026-08-25T00:00:00Z",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["status"] == "draft"
    assert payload["promoted"] is False
    assert payload["registersCommands"] == []
    assert payload["baseline"]["facts"] == []
    assert out.is_file()


def test_interface_contract_stable_and_forbids_explore() -> None:
    contract = pb.interface_contract()
    assert contract["interface"] == pb.SYNTHESIS_INTERFACE_VERSION
    assert contract["autoPromote"] is False
    assert contract["registersCommands"] == []
    assert "/sw-explore" in contract["forbidsCommands"]
    assert "synthesize_baseline" in contract["callable"]


def test_no_sw_explore_command_registered(repo_root: Path) -> None:
    names = {
        "sw-explore.md",
        "sw-explore",
        "explore.md",
    }
    found: list[str] = []
    for directory in COMMANDS_DIRS:
        root = repo_root / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.name in names or path.stem == "sw-explore":
                found.append(str(path.relative_to(repo_root)))
    assert found == [], f"unexpected /sw-explore registration: {found}"


def test_repeated_synthesis_remains_draft(baseline_schema: dict) -> None:
    observations = [
        _obs(
            "runtime.primary",
            "Primary runtime appears to be Python.",
            "file://repo/pyproject.toml",
        )
    ]
    first = pb.synthesize_baseline(observations, created_at="2026-08-25T00:00:00Z")
    second = pb.synthesize_baseline(observations, created_at="2026-08-25T01:00:00Z")
    assert first["status"] == "draft"
    assert second["status"] == "draft"
    assert first["version"] == second["version"] == "ProjectBaseline@v1"
    assert pb.validate_baseline(first) == []
    assert pb.validate_baseline(second) == []
    # Optional engine — must not gate core draft assertions above.
    try:
        _maybe_validate_jsonschema(first, baseline_schema)
        _maybe_validate_jsonschema(second, baseline_schema)
    except pytest.skip.Exception:
        pass


def test_optional_jsonschema_engine_when_present(baseline_schema: dict) -> None:
    doc = pb.synthesize_baseline(
        [
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/pyproject.toml",
            )
        ],
        created_at="2026-08-25T00:00:00Z",
    )
    _maybe_validate_jsonschema(doc, baseline_schema)
