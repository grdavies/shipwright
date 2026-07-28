"""Load scripts/planning submodules without colliding with unit_tests/planning."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT_DIR = Path(__file__).resolve().parent
_PKG_DIR = _SCRIPT_DIR / "planning"
_CACHE: dict[str, ModuleType] = {}


def load_submodule(name: str) -> ModuleType:
  cached = _CACHE.get(name)
  if cached is not None:
    return cached
  path = _PKG_DIR / f"{name}.py"
  module_name = f"sw_planning.{name}"
  spec = importlib.util.spec_from_file_location(module_name, path)
  if spec is None or spec.loader is None:
    raise ImportError(f"cannot load planning submodule: {name}")
  module = importlib.util.module_from_spec(spec)
  sys.modules[module_name] = module
  spec.loader.exec_module(module)
  _CACHE[name] = module
  return module


def load_package() -> ModuleType:
  cached = _CACHE.get("__package__")
  if cached is not None:
    return cached
  init_path = _PKG_DIR / "__init__.py"
  module_name = "sw_planning"
  spec = importlib.util.spec_from_file_location(
    module_name,
    init_path,
    submodule_search_locations=[str(_PKG_DIR)],
  )
  if spec is None or spec.loader is None:
    raise ImportError("cannot load planning package")
  module = importlib.util.module_from_spec(spec)
  sys.modules[module_name] = module
  spec.loader.exec_module(module)
  _CACHE["__package__"] = module
  return module
