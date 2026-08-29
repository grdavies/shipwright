"""Generated planning_store shim parity harness (PRD 082 phase 10 / R27)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_import_inventory import CANONICAL_REL, CLI_MODULE_REL, build_inventory
from planning_shim_gen import SHIM_TARGETS, generate_all, render_shim


def _write_minimal_facade_and_cli(root: Path) -> None:
    facade_path = root / CANONICAL_REL
    facade_path.parent.mkdir(parents=True, exist_ok=True)
    facade_path.write_text(
        '''\
def greet(name: str) -> str:
    return f"hello:{name}"


def main() -> None:
    from planning.cli import main as cli_main
    cli_main()
''',
        encoding="utf-8",
    )
    cli_path = root / CLI_MODULE_REL
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text(
        '''\
import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_store_facade import greet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("greet",):
        sub.add_parser(name)
    args, rest = parser.parse_known_args()
    if args.command == "greet":
        target = rest[0] if rest else "world"
        print(greet(target))
        raise SystemExit(0)
    print("unknown", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run_module(path: Path, argv: list[str], *, repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path), *argv],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def test_generated_shim_cli_parity(tmp_path: Path) -> None:
    _write_minimal_facade_and_cli(tmp_path)
    inventory = build_inventory(tmp_path)
    generate_all(tmp_path, inventory)
    cli = tmp_path / CLI_MODULE_REL
    shim = tmp_path / SHIM_TARGETS[0][0]
    argv = ["greet", "shipwright"]
    cli_run = _run_module(cli, argv, repo_root=tmp_path)
    shim_run = _run_module(shim, argv, repo_root=tmp_path)
    assert cli_run.returncode == shim_run.returncode
    assert cli_run.stdout == shim_run.stdout
    assert cli_run.stderr == shim_run.stderr


def test_monkeypatched_function_visible_through_shim(tmp_path: Path) -> None:
    _write_minimal_facade_and_cli(tmp_path)
    inventory = build_inventory(tmp_path)
    content = render_shim(repo_depth=2, symbol_names=["greet"])
    shim_path = tmp_path / "core" / "scripts" / "planning_store.py"
    shim_path.parent.mkdir(parents=True, exist_ok=True)
    shim_path.write_text(content, encoding="utf-8")

    shim = _load_module(shim_path, "planning_store_shim_under_test")

    def patched(name: str) -> str:
        return f"patched:{name}"

    shim.greet = patched
    assert shim.greet("x") == "patched:x"

    canonical = shim._load_canonical()
    assert canonical.greet("x") == "hello:x"

    # Isolated shim loads a stub facade into sys.modules; drop it so later shard tests
    # import the real scripts/planning_store_facade (not the tmp_path minimal stub).
    sys.modules.pop("planning_store_facade", None)
    sys.modules.pop("planning_store_shim_under_test", None)
    planning_store = sys.modules.get("planning_store")
    if planning_store is not None and hasattr(planning_store, "_cached"):
        planning_store._cached = None


def test_inventory_records_cli_surface() -> None:
    inventory = build_inventory(REPO_ROOT)
    cli = inventory["cli"]
    assert "list-backends" in cli["subcommands"]
    assert "--root" in cli["flags"]
    assert inventory["symbolCount"] > 0


def test_compat_removal_probe_blocked_with_live_imports() -> None:
    from planning_import_inventory import evaluate_compat_removal

    inventory = build_inventory(REPO_ROOT)
    probe = evaluate_compat_removal(inventory)
    assert probe["verdict"] == "blocked"
    assert probe["importSiteCount"] > 0
    assert probe["removable"] is False
