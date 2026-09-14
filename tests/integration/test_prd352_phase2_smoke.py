"""PRD 352 R27 — phase-2 packaging smoke (zipapp handoff self-test)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_prd352_phase2_packaged_handoff_self_test() -> None:
    """Build zipapp and run handoff_bundle --self-test from a copied dist tree (R1/R2/R27)."""
    build = REPO / "scripts" / "build_zipapp.py"
    assert build.is_file(), "scripts/build_zipapp.py missing"

    with tempfile.TemporaryDirectory(prefix="prd352-phase2-") as tmp:
        out_dir = Path(tmp) / "dist"
        out_dir.mkdir()
        proc = subprocess.run(
            [sys.executable, str(build), "build", "--dest", str(out_dir)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            "zipapp build failed:\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )

        stage = Path(tmp) / "stage"
        stage.mkdir()
        for pattern in ("shipwright*.pyz", "shipwright*.manifest.json", "shipwright-distribution-stamp.json"):
            for src in out_dir.glob(pattern):
                (stage / src.name).write_bytes(src.read_bytes())

        pyz = stage / "shipwright.pyz"
        if not pyz.exists():
            candidates = sorted(stage.glob("shipwright-*.pyz"))
            assert candidates, f"no shipwright zipapp under {stage}"
            pyz = candidates[0]

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        self_test = subprocess.run(
            [sys.executable, str(pyz), "handoff_bundle", "--self-test"],
            cwd=str(stage),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert self_test.returncode == 0, (
            "packaged handoff_bundle --self-test failed (PRD 352 R1/R2/R27):\n"
            f"stdout:\n{self_test.stdout[-2000:]}\nstderr:\n{self_test.stderr[-2000:]}"
        )


def test_prd352_phase2_descriptor_modes_validate() -> None:
    """Codex/OpenCode descriptors must validate after R6 schema extension."""
    validate = REPO / "scripts" / "validate_descriptor.py"
    for platform in ("codex", "opencode"):
        desc = REPO / "platforms" / platform / "descriptor.json"
        proc = subprocess.run(
            [sys.executable, str(validate), str(desc)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"{platform} descriptor failed validation:\n{proc.stdout}\n{proc.stderr}"
        )


def test_prd352_phase2_emit_ships_skill_bodies(tmp_path: Path) -> None:
    """Generators must ship SKILL.md bodies (R4) and lifecycle stdin wiring (R5)."""
    sys.path.insert(0, str(REPO / "platforms" / "codex"))
    import generator as codex_gen  # noqa: E402

    out = codex_gen.generate(tmp_path / "codex", repo_root=REPO, core_root=REPO / "core")
    assert list(out.rglob("SKILL.md")), "Codex emit missing skill bodies"
    hook = (out / "hooks" / "codex-hook.py").read_text(encoding="utf-8")
    assert "lifecycle" in hook
    assert (out / "hooks" / "lifecycle.py").is_file()


def test_prd352_phase2_handoff_schema_on_closed_emit_list() -> None:
    """R2: handoff-bundle.schema.json must be on SW_REFERENCE_CLOSED_EMIT."""
    text = (REPO / "sw" / "emitter_base.py").read_text(encoding="utf-8")
    assert "handoff-bundle.schema.json" in text
    assert (REPO / "core" / "sw-reference" / "handoff-bundle.schema.json").is_file()
