"""OpenCode platform emitter — delegates to generator (PRD 349)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_generator():
    gen_path = Path(__file__).resolve().parent / "generator.py"
    name = "sw_platform_opencode_generator"
    sys.modules.pop(name, None)
    for shared in ("generator", "hook_registry", "plugin_manifest"):
        sys.modules.pop(shared, None)
    spec = importlib.util.spec_from_file_location(name, gen_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load generator at {gen_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(gen_path.parent))
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def emit(core_root: Path, repo_root: Path, dest: Path) -> None:
    _load_generator().emit(core_root, repo_root, dest)
