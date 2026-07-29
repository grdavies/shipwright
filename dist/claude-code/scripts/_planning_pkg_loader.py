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
  if name.startswith("backends."):
    rel = name.split(".", 1)[1]
    path = _PKG_DIR / "backends" / f"{rel.replace('.', '/')}.py"
  elif name.startswith("providers."):
    rel = name.split(".", 1)[1]
    path = _PKG_DIR / "providers" / f"{rel.replace('.', '/')}.py"
  else:
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


def load_providers_package() -> ModuleType:
  """Load scripts/planning/providers without colliding with unit_tests/planning."""
  cached = _CACHE.get("__providers__")
  if cached is not None:
    return cached
  parent = load_package()
  providers_dir = _PKG_DIR / "providers"
  init_path = providers_dir / "__init__.py"
  module_name = "sw_planning.providers"
  spec = importlib.util.spec_from_file_location(
    module_name,
    init_path,
    submodule_search_locations=[str(providers_dir)],
  )
  if spec is None or spec.loader is None:
    raise ImportError("cannot load planning.providers package")
  module = importlib.util.module_from_spec(spec)
  module.__package__ = module_name
  module.__path__ = [str(providers_dir)]  # type: ignore[attr-defined]
  sys.modules[module_name] = module
  setattr(parent, "providers", module)
  spec.loader.exec_module(module)
  _CACHE["__providers__"] = module
  return module


def load_backends_package() -> ModuleType:
  """Load scripts/planning/backends without colliding with unit_tests/planning."""
  cached = _CACHE.get("__backends__")
  if cached is not None:
    return cached
  parent = load_package()
  backends_dir = _PKG_DIR / "backends"
  init_path = backends_dir / "__init__.py"
  module_name = "sw_planning.backends"
  spec = importlib.util.spec_from_file_location(
    module_name,
    init_path,
    submodule_search_locations=[str(backends_dir)],
  )
  if spec is None or spec.loader is None:
    raise ImportError("cannot load planning.backends package")
  module = importlib.util.module_from_spec(spec)
  module.__package__ = module_name
  module.__path__ = [str(backends_dir)]  # type: ignore[attr-defined]
  sys.modules[module_name] = module
  setattr(parent, "backends", module)
  spec.loader.exec_module(module)
  _CACHE["__backends__"] = module
  return module
