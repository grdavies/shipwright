#!/usr/bin/env python3
"""Python test runner for scripts/test harnesses (R27).

Replaces bash orchestration for fixture suites, .test files, and verify.test integration.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
from _fixture_lib import invoke_suite_main, repo_root


def coverage_enabled(*, flag: bool = False) -> bool:
    if flag:
        return True
    return os.environ.get("SW_COVERAGE", "").strip().lower() in ("1", "true", "yes")


def resolve_coverdir(root: Path, run_id: str | None = None) -> Path:
    rid = run_id or uuid.uuid4().hex[:12]
    coverdir = root / ".cursor" / "sw-coverage" / rid
    coverdir.mkdir(parents=True, exist_ok=True)
    return coverdir


def trace_command(path: Path, *, coverdir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "trace",
        "--count",
        f"--coverdir={coverdir}",
        str(path),
    ]


def run_traced_subprocess(path: Path, *, root: Path, coverdir: Path, env: dict[str, str]) -> int:
    completed = subprocess.run(
        trace_command(path, coverdir=coverdir),
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


def emit_coverage_report(coverdir: Path, *, root: Path) -> None:
    report = root / "scripts" / "coverage_report.py"
    if not report.is_file():
        return
    subprocess.run(
        [sys.executable, str(report), "--coverdir", str(coverdir), "--scripts-root", str(root / "scripts")],
        cwd=str(root),
        check=False,
    )


def discover_tests(root: Path) -> list[Path]:
    return sorted(root.glob("*.test"))


def discover_suites(root: Path) -> list[Path]:
    py = sorted(root.glob("run_*_fixtures.py"))
    sh = sorted(root.glob("run-*-fixtures.sh"))
    return py + sh




def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _suite_env(root: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = (base_env or os.environ).copy()
    env["ROOT"] = str(root)
    env["SW_REPO_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
    if _truthy_env("SW_DELIVER_VERIFY"):
        from _fixture_lib import prepare_ephemeral_fixtures

        ephemeral = prepare_ephemeral_fixtures(root)
        env["SW_FIXTURES_EPHEMERAL_ROOT"] = str(ephemeral / "fixtures")
        env["_SW_FIXTURES_EPHEMERAL_DIR"] = str(ephemeral)
    return env


def run_test_file(
    path: Path,
    *,
    root: Path | None = None,
    coverage: bool = False,
    coverdir: Path | None = None,
) -> int:
    root = root or repo_root(path)
    env = _suite_env(root)
    use_coverage = coverage_enabled(flag=coverage)
    active_coverdir = coverdir or (resolve_coverdir(root) if use_coverage else None)

    if use_coverage and active_coverdir is not None:
        return run_traced_subprocess(path, root=root, coverdir=active_coverdir, env=env)

    if path.suffix == ".test" and path.read_text(encoding="utf-8", errors="replace").startswith(
        "#!/usr/bin/env python"
    ):
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(root),
            env=env,
            shell=False,
        )
        return completed.returncode
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("#!/usr/bin/env bash"):
        body = text
        body = body.replace("#!/usr/bin/env bash", "")
        body = body.replace("set -euo pipefail", "")
        for marker in ('ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"',):
            body = body.replace(marker, f'ROOT="{root}"')
        body = re.sub(
            r'ROOT="[^"]*worktrees/[^"]*"',
            f'ROOT="{root}"',
            body,
        )
        body = body.replace('bash "', f"{sys.executable} ").replace('.test"', '.test"')
        body = body.replace('bash "$ROOT/', f'{sys.executable} "$ROOT/')
        body = body.replace('.sh"', '.py"')
        completed = subprocess.run(
            ["/bin/bash", "-c", body],
            cwd=str(root),
            env=env,
            shell=False,
        )
        return completed.returncode
    completed = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


def run_suite_module(
    path: Path,
    *,
    root: Path | None = None,
    coverage: bool = False,
    coverdir: Path | None = None,
) -> int:
    root = root or repo_root(path)
    use_coverage = coverage_enabled(flag=coverage)
    active_coverdir = coverdir or (resolve_coverdir(root) if use_coverage else None)

    if use_coverage and active_coverdir is not None and path.suffix == ".py":
        env = _suite_env(root)
        return run_traced_subprocess(path, root=root, coverdir=active_coverdir, env=env)

    if path.suffix == ".py":
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            print(f"FAIL cannot load suite {path}", file=sys.stderr)
            return 1
        mod = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = mod
        spec.loader.exec_module(mod)
        if hasattr(mod, "main"):
            return invoke_suite_main(mod)
        print(f"FAIL suite {path} missing main()", file=sys.stderr)
        return 1
    env = _suite_env(root)
    completed = subprocess.run(["/bin/bash", str(path)], cwd=str(root), env=env, shell=False)
    return completed.returncode


def load_manifest(root: Path) -> list[dict]:
    manifest = root / "core/sw-reference/pr-test-plan.manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return list(data.get("fixtures") or [])


def run_manifest(root: Path, *, coverage: bool = False, coverdir: Path | None = None) -> int:
    use_coverage = coverage_enabled(flag=coverage)
    active_coverdir = coverdir or (resolve_coverdir(root) if use_coverage else None)
    failures = 0
    for entry in load_manifest(root):
        script = entry.get("script", "")
        rel = script.replace(".sh", ".py")
        path = root / rel
        if not path.is_file() and (root / script).is_file():
            path = root / script
        if not path.is_file():
            print(f"FAIL manifest/{entry.get('id')}: missing {rel}")
            failures += 1
            continue
        print(f"==> pr-test-plan/{entry['id']}: {path.relative_to(root)}")
        ec = run_suite_module(path, root=root, coverage=use_coverage, coverdir=active_coverdir)
        if ec != 0:
            failures += 1
    if use_coverage and active_coverdir is not None:
        emit_coverage_report(active_coverdir, root=root)
    if failures:
        print(f"FAIL pr-test-plan-manifest: {failures} suite(s) failed")
        return 1
    print(f"OK  pr-test-plan-manifest: all {len(load_manifest(root))} fixtures passed")
    return 0


def run_verify(root: Path, *, coverage: bool = False, coverdir: Path | None = None) -> int:
    """Run the shipwright plugin verify.test bundle."""
    use_coverage = coverage_enabled(flag=coverage)
    active_coverdir = coverdir or (resolve_coverdir(root) if use_coverage else None)
    ec = run_suite_module(SCRIPT_DIR / "run_verify_bundle.py", root=root, coverage=use_coverage, coverdir=active_coverdir)
    if ec != 0:
        if use_coverage and active_coverdir is not None:
            emit_coverage_report(active_coverdir, root=root)
        return ec
    result = run_manifest(root, coverage=use_coverage, coverdir=active_coverdir)
    if use_coverage and active_coverdir is not None:
        emit_coverage_report(active_coverdir, root=root)
    return result


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root or REPO_ROOT)
    tests = discover_tests(SCRIPT_DIR)
    suites = [p for p in discover_suites(SCRIPT_DIR) if p.suffix == ".py"]
    print(json.dumps({"tests": [p.name for p in tests], "suites": [p.name for p in suites]}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="test-runner",
        description="Python test harness runner (R27). Coverage mode is opt-in via --coverage or SW_COVERAGE=1; informational baseline only — no CI threshold gate.",
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run subprocess suites via python -m trace --count (informational baseline; no CI gate)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_test = sub.add_parser("run-test", help="Run one .test file")
    p_test.add_argument("path")

    p_suite = sub.add_parser("run-suite", help="Run one fixture suite module")
    p_suite.add_argument("path")

    sub.add_parser("run-manifest", help="Run pr-test-plan manifest fixtures")
    sub.add_parser("verify", help="Run verify.test bundle")
    sub.add_parser("list", help="List discoverable tests")

    sub.add_parser("run-all-tests", help="Run all .test files")

    p_report = sub.add_parser("coverage-report", help="Print coverage summary from a trace coverdir")
    p_report.add_argument("--coverdir", required=True)

    args = parser.parse_args(argv)
    root = Path(args.root)
    coverage = coverage_enabled(flag=getattr(args, "coverage", False))

    if args.cmd == "run-test":
        return run_test_file(Path(args.path), root=root, coverage=coverage)
    if args.cmd == "run-suite":
        return run_suite_module(Path(args.path), root=root, coverage=coverage)
    if args.cmd == "run-manifest":
        return run_manifest(root, coverage=coverage)
    if args.cmd == "verify":
        return run_verify(root, coverage=coverage)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "run-all-tests":
        failures = 0
        for test in discover_tests(SCRIPT_DIR):
            if run_test_file(test, root=root, coverage=coverage) != 0:
                failures += 1
        return 1 if failures else 0
    if args.cmd == "coverage-report":
        print_report(Path(args.coverdir), scripts_root=(root / "scripts").resolve())
        return 0
    return 2


if __name__ == "__main__":
    run_module_main(main)
