"""PRD 347 — packaged_init_steps authority contract (R1/R2/R4/R5)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent


def _load_sw_configure():
    path = SCRIPT_DIR / "sw-configure.py"
    spec = importlib.util.spec_from_file_location("sw_configure_packaged_init", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sw_configure():
    return _load_sw_configure()


def test_packaged_init_steps_importable(sw_configure) -> None:
    assert callable(sw_configure.packaged_init_steps)


def test_packaged_init_steps_returns_nonempty(sw_configure) -> None:
    steps = sw_configure.packaged_init_steps()
    assert isinstance(steps, list)
    assert len(steps) > 0


def test_packaged_init_steps_step_schema(sw_configure) -> None:
    steps = sw_configure.packaged_init_steps()
    for step in steps:
        assert isinstance(step, dict)
        assert isinstance(step.get("name"), str) and step["name"]
        assert isinstance(step.get("description"), str) and step["description"]
        assert isinstance(step.get("required"), bool)


def test_packaged_init_steps_order_stable(sw_configure) -> None:
    assert sw_configure.packaged_init_steps() == sw_configure.packaged_init_steps()


def test_documented_init_steps_match_code_seed(sw_configure) -> None:
    """Docs numbered steps must match packaged_init_steps descriptions (R3)."""
    steps = sw_configure.packaged_init_steps()
    docs = (REPO_ROOT / "core/documentation/getting-started.md").read_text(encoding="utf-8")
    default_section = docs.split("## Default: packaged install + single init", 1)[1].split(
        "### Self-check", 1
    )[0]
    numbered = re.findall(r"^\d+\.\s+(.+)$", default_section, flags=re.MULTILINE)
    descriptions = [s["description"] for s in steps]
    assert numbered[: len(descriptions)] == descriptions
    for step in steps:
        assert step["description"] in docs
