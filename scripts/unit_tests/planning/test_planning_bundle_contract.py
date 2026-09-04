"""PRD 342 phase 9 — planning-unit bundle contract (R30, R32)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_bundle as pb
import planning_paths as pp


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


def _canonical_body(*, declare_bundle: bool, unit_id: str = "prd-fixture") -> str:
    lines = [
        "---",
        f"id: {unit_id}",
        "type: prd",
        "status: planned",
        "title: Fixture PRD",
        "visibility: public",
    ]
    if declare_bundle:
        lines.append("bundle: true")
    lines.extend(["---", "", "# Fixture", ""])
    return "\n".join(lines)


def _asset(body: str = "# asset\n") -> str:
    return body


def _unit_dir(repo: Path, name: str = "docs/prds/999-fixture") -> Path:
    return repo / name


def _seed_assets(unit: Path, roles: list[str] | None = None, *, with_id: bool = False) -> None:
    roles = list(roles) if roles is not None else list(pp.BUNDLE_ASSET_ROLES)
    for role in roles:
        text = (
            "---\nid: stolen-body\ntype: prd\nstatus: planned\ntitle: bad\nvisibility: public\n---\n\n# bad\n"
            if with_id
            else _asset(f"# {role}\n")
        )
        _write(unit / pp.BUNDLE_ASSET_FILENAMES[role], text)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git_init(root)
    schema_src = (
        Path(__file__).resolve().parents[3]
        / "core"
        / "sw-reference"
        / "planning-bundle.schema.json"
    )
    dest = root / "core" / "sw-reference" / "planning-bundle.schema.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if schema_src.is_file():
        dest.write_text(schema_src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dest.write_text("{}", encoding="utf-8")
    return root


def test_schema_requires_five_roles_and_declaration_signal(repo: Path) -> None:
    """R30 — schema encodes five required roles + declaration (not inference)."""
    schema_path = repo / "core" / "sw-reference" / "planning-bundle.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    roles = schema["properties"]["requiredRoles"]["items"]["enum"]
    assert roles == [
        "plan",
        "data-model",
        "contracts",
        "quickstart",
        "checklist",
    ]
    declaration = schema["properties"]["declaration"]["properties"]
    assert declaration["frontmatterKey"]["const"] == "bundle"
    contract = pb.load_bundle_contract(repo)
    assert contract["requiredRoles"] == list(pp.BUNDLE_ASSET_ROLES)
    assert contract["declaration"]["frontmatterKey"] == "bundle"


def test_asset_roles_resolve_by_fixed_naming() -> None:
    """R31 — each role maps to a fixed filename co-located with the unit folder."""
    unit = "docs/prds/342-spec-kit-learnings"
    paths = pp.bundle_asset_paths_rel(unit)
    assert paths == {
        "plan": "docs/prds/342-spec-kit-learnings/plan.md",
        "data-model": "docs/prds/342-spec-kit-learnings/data-model.md",
        "contracts": "docs/prds/342-spec-kit-learnings/contracts.md",
        "quickstart": "docs/prds/342-spec-kit-learnings/quickstart.md",
        "checklist": "docs/prds/342-spec-kit-learnings/checklist.md",
    }
    # separate-project virtual body paths use the same fixed naming
    assert (
        pp.bundle_asset_virtual_body_path(unit, "plan")
        == "docs/prds/342-spec-kit-learnings/plan.md"
    )


def test_declared_complete_bundle(repo: Path) -> None:
    """R30 — declared + all five assets → complete."""
    unit = _unit_dir(repo)
    _write(unit / "999-prd-fixture.md", _canonical_body(declare_bundle=True))
    _seed_assets(unit)
    result = pb.validate_unit_bundle(repo, unit)
    assert result["disposition"] == pb.DISPOSITION_COMPLETE
    assert result["verdict"] == "pass"
    assert result["declared"] is True
    assert result["missing"] == []
    assert set(result["present"]) == set(pp.BUNDLE_ASSET_ROLES)


def test_declared_incomplete_bundle(repo: Path) -> None:
    """R30 — declared but missing assets → incomplete (named missing roles)."""
    unit = _unit_dir(repo)
    _write(unit / "999-prd-fixture.md", _canonical_body(declare_bundle=True))
    _seed_assets(unit, roles=["plan", "contracts", "checklist"])
    result = pb.validate_unit_bundle(repo, unit)
    assert result["disposition"] == pb.DISPOSITION_INCOMPLETE
    assert result["verdict"] == "fail"
    assert result["incomplete"] is True
    assert set(result["missing"]) == {"data-model", "quickstart"}


def test_undeclared_never_incomplete_even_with_assets(repo: Path) -> None:
    """R30 — no declaration ⇒ undeclared, never incomplete (even if assets exist)."""
    unit = _unit_dir(repo)
    _write(unit / "999-prd-fixture.md", _canonical_body(declare_bundle=False))
    _seed_assets(unit, roles=["plan", "data-model"])
    result = pb.validate_unit_bundle(repo, unit)
    assert result["disposition"] == pb.DISPOSITION_UNDECLARED
    assert result["verdict"] == "pass"
    assert result["incomplete"] is False
    assert result["missing"] == []
    assert result["declared"] is False


def test_undeclared_without_assets(repo: Path) -> None:
    """R30 — undeclared empty unit is not incomplete."""
    unit = _unit_dir(repo)
    _write(unit / "999-prd-fixture.md", _canonical_body(declare_bundle=False))
    result = pb.validate_unit_bundle(repo, unit)
    assert result["disposition"] == pb.DISPOSITION_UNDECLARED
    assert result["missing"] == []
    assert result["incomplete"] is False


def test_asset_with_id_key_rejected(repo: Path) -> None:
    """R32 — asset carrying an id: key is rejected."""
    unit = _unit_dir(repo)
    _write(unit / "999-prd-fixture.md", _canonical_body(declare_bundle=True))
    _seed_assets(unit, roles=["plan"], with_id=True)
    for role in ("data-model", "contracts", "quickstart", "checklist"):
        _write(unit / pp.BUNDLE_ASSET_FILENAMES[role], _asset())
    result = pb.validate_unit_bundle(repo, unit)
    assert result["disposition"] == pb.DISPOSITION_REJECTED
    assert result["verdict"] == "fail"
    assert result["error"] == "asset-carries-id-key"


def test_asset_with_planning_unit_frontmatter_rejected() -> None:
    """R32 — planning-unit-shaped frontmatter on an asset is rejected."""
    text = (
        "---\n"
        "type: amendment\n"
        "status: proposed\n"
        "title: sneak\n"
        "visibility: public\n"
        "---\n\n"
        "# no\n"
    )
    result = pb.validate_asset_text(text, role="plan")
    assert result["verdict"] == "fail"
    assert result["disposition"] == pb.DISPOSITION_REJECTED
    assert result["error"] == "asset-carries-planning-unit-frontmatter"


def test_plain_asset_frontmatter_allowed() -> None:
    """R32 — non-planning-unit frontmatter without id: is allowed."""
    text = "---\ntitle: Implementation plan\n---\n\n# Plan\n"
    result = pb.validate_asset_text(text, role="plan")
    assert result["verdict"] == "pass"
