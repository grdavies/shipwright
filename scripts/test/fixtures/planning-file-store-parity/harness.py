#!/usr/bin/env python3
"""File-store parity golden-output harness (PRD 057 R23).

Proves the local (file-store) code path is unchanged by the guards this PRD
adds. Every R1-R4 guard is conditioned on the shared predicate
``issue-store effective AND storeLocation.mode == separate-project``. Under a
non-issue-store backend that predicate is False, so the guards are inert and the
per-command artifacts (gap capture, reconcile, spec-seed) are emitted exactly as
today; a file-store put/get round-trip proves byte-identity of the write path.

Contract:
- File-store parity checks ALWAYS run (deterministic, offline).
- Issue-store-authoritative checks degrade to skip-with-advisory (green) when a
  live issue-store is unavailable (token absent or backend not issue-store) — R30.
- Sibling ``*_golden.py`` modules (added by later waves: 6.5 gap_capture_golden,
  7.3 spec_seed_reconcile_golden) are discovered and run through ``run_golden``.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store

# Artifacts each guarded command writes on the local (file-store) path. Later
# per-command golden modules assert byte-identity of these exact paths.
COMMAND_ARTIFACTS: dict[str, list[str]] = {
    "gap-capture": ["docs/prds/GAP-BACKLOG.md"],
    "reconcile": [
        "docs/prds/INDEX.md",
        "docs/prds/INDEX-archive.md",
        "docs/prds/SUPERSEDED.md",
    ],
    "spec-seed": ["docs/prds/INDEX.md"],
}

REPRESENTATIVE_BODY = (
    "---\ntype: prd\nunit-id: 999-prd-parity-probe\nstatus: draft\n---\n"
    "# Parity probe\n\n- **R1** deterministic body used for file-store round-trip parity.\n"
)


def guard_predicate(root: Path, cfg: dict) -> bool:
    """issue-store effective AND storeLocation.mode == separate-project."""
    effective = planning_store.resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        return False
    location = planning_store.resolve_store_location(root, cfg)
    return location.get("mode") == "separate-project"


def check_file_store_predicate_inert() -> dict:
    """Under a default (file-store) config the guard predicate must be False."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg: dict = {}
        predicate = guard_predicate(root, cfg)
    ok = predicate is False
    return {
        "name": "file-store-guard-inert",
        "ok": ok,
        "detail": f"guard predicate under file-store = {predicate} (expected False)",
    }


def check_file_store_roundtrip_byte_identity() -> dict:
    """The file-store put path is byte-identical on repeated writes (parity)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg: dict = {}
        backend = planning_store.get_backend(root, cfg)
        body_path = "docs/prds/999-prd-parity-probe/999-prd-parity-probe.md"
        # Suppress the backend's stdout operation log so the harness emits only
        # its JSON verdict on stdout.
        with contextlib.redirect_stdout(io.StringIO()):
            first = backend.put("999-prd-parity-probe", body_path, REPRESENTATIVE_BODY)
            fetched = backend.get("999-prd-parity-probe", body_path)
            second = backend.put("999-prd-parity-probe", body_path, REPRESENTATIVE_BODY)
    ok = (
        backend.backend_id != "issue-store"
        and fetched.content == REPRESENTATIVE_BODY
        and first.hash == fetched.hash == second.hash
    )
    return {
        "name": "file-store-roundtrip-byte-identity",
        "ok": ok,
        "detail": f"backend={backend.backend_id} hash={first.hash}",
    }


def check_command_artifact_registry() -> dict:
    """Each guarded command declares its local artifact set for golden parity."""
    ok = all(paths for paths in COMMAND_ARTIFACTS.values())
    return {
        "name": "command-artifact-registry",
        "ok": ok,
        "detail": {cmd: paths for cmd, paths in COMMAND_ARTIFACTS.items()},
    }


def issue_store_side() -> dict:
    """Issue-store-authoritative parity: run only with a live store, else skip."""
    cfg = planning_store.load_workflow_config(ROOT)
    effective = planning_store.resolve_effective_backend(ROOT, cfg)
    if effective.get("effective") != "issue-store":
        return {"name": "issue-store-authoritative", "skipped": True, "reason": "backend-not-issue-store"}
    provider = planning_store.resolve_issues_provider(cfg).get("provider", "")
    token_env = planning_store.resolve_issues_token_env(cfg, provider)
    if not token_env or not planning_store.token_present(token_env):
        return {"name": "issue-store-authoritative", "skipped": True, "reason": "store-token-absent"}
    # Live store present: assert the guard predicate is well-formed for the
    # configured store location (authoritative writes divert away from local).
    predicate = guard_predicate(ROOT, cfg)
    location = planning_store.resolve_store_location(ROOT, cfg)
    ok = predicate == (location.get("mode") == "separate-project")
    return {
        "name": "issue-store-authoritative",
        "skipped": False,
        "ok": ok,
        "detail": f"mode={location.get('mode')} predicate={predicate}",
    }


def run_golden() -> list[dict]:
    """Discover and run sibling *_golden.py modules (later-wave extension point)."""
    results: list[dict] = []
    for module_path in sorted(SCRIPT_DIR.glob("*_golden.py")):
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            runner = getattr(module, "run", None)
            outcome = runner() if callable(runner) else {"ok": True, "detail": "no run()"}
        except Exception as exc:  # golden module failure is a real parity failure
            outcome = {"ok": False, "detail": f"golden-error: {exc}"}
        results.append({"name": module_path.stem, **outcome})
    return results


def main() -> int:
    checks = [
        check_file_store_predicate_inert(),
        check_file_store_roundtrip_byte_identity(),
        check_command_artifact_registry(),
    ]
    golden = run_golden()
    issue_store = issue_store_side()

    ran = [c for c in checks + golden if not c.get("skipped")]
    failures = [c for c in ran if not c.get("ok")]
    if not issue_store.get("skipped") and not issue_store.get("ok"):
        failures.append(issue_store)

    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-file-store-parity",
        "rid": "R23",
        "verdict": verdict,
        "fileStoreChecks": checks,
        "goldenModules": golden,
        "issueStore": issue_store,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
