#!/usr/bin/env python3
"""Two-process concurrency fixtures for file-backed planning store (PRD 082 R28 / PRD 339 R39)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planning.backends.issues import IssueStoreBackend  # noqa: E402
from planning.backends.issues_helpers import (  # noqa: E402
    ISSUE_UNIT_INDEX,
    ISSUE_UNIT_INDEX_AUDIT,
    issue_index_key,
    load_issue_unit_index,
    self_heal_issue_unit_index,
)
from planning_canonical import compose_issue_body  # noqa: E402
from planning_paths import atomic_write_text  # noqa: E402
from planning_store import (  # noqa: E402
    FILE_BACKED_STORE_TXN_ID,
    mutate_issue_unit_index,
    read_issue_unit_index_locked,
    save_issue_unit_index,
    self_heal_unit_index,
)


def _fixture_root(tmp: Path) -> Path:
    (tmp / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    return tmp


def check_concurrent_index_updates_no_lost_write() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "demo"
        errors: list[str] = []
        barrier = threading.Barrier(2)

        def worker(unit_suffix: str) -> None:
            try:
                barrier.wait(timeout=5)
                idx_key = issue_index_key(project_key, f"unit-{unit_suffix}")

                def _update(index: dict[str, str]) -> None:
                    index[idx_key] = f"issue-{unit_suffix}"

                mutate_issue_unit_index(root, _update)
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(suffix,), daemon=True) for suffix in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        if errors:
            return {"verdict": "fail", "check": "concurrent-index", "errors": errors}
        final = load_issue_unit_index(root)
        expected = {
            issue_index_key(project_key, "unit-a"): "issue-a",
            issue_index_key(project_key, "unit-b"): "issue-b",
        }
        for key, value in expected.items():
            if final.get(key) != value:
                return {"verdict": "fail", "check": "lost-update", "index": final, "missing": key}
    return {"verdict": "ok", "check": "concurrent-index"}


def check_index_reread_under_lock() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "demo"
        save_issue_unit_index(root, {issue_index_key(project_key, "seed"): "issue-seed"})
        observed: list[str] = []

        def writer() -> None:
            mutate_issue_unit_index(
                root,
                lambda index: index.__setitem__(issue_index_key(project_key, "writer"), "issue-writer"),
            )

        def reader() -> None:
            index = read_issue_unit_index_locked(root)
            observed.append(index.get(issue_index_key(project_key, "seed"), ""))

        writer_thread = threading.Thread(target=writer, daemon=True)
        reader_thread = threading.Thread(target=reader, daemon=True)
        writer_thread.start()
        reader_thread.start()
        writer_thread.join(timeout=5)
        reader_thread.join(timeout=5)
        if "issue-seed" not in observed:
            return {"verdict": "fail", "check": "index-reread", "observed": observed}
    return {"verdict": "ok", "check": "index-reread"}


def _init_issue_store_repo(tmp: Path, project_key: str = "r39-txn") -> dict:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, check=True)
    cfg = {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }
    (tmp / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def check_unit_index_concurrent_self_heal_marker_reuse() -> dict:
    """R39 — refuse cross-artifact sw-unit-id marker reuse before mutation."""
    import tempfile

    os.environ["SW_ISSUES_FIXTURE"] = "1"
    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "r39-txn"
        cfg = _init_issue_store_repo(root, project_key)
        backend = IssueStoreBackend(root, cfg)
        shared_unit = "339-prd-planning-store-correctness-provider-expansion"
        prd_body = compose_issue_body(
            project_key,
            "prd",
            shared_unit,
            (
                "---\n"
                f"id: {shared_unit}\n"
                "type: prd\n"
                "status: proposed\n"
                "---\n"
                "# PRD\n"
            ),
        )
        prd = backend._client.issue_create(
            title="PRD 339",
            body=prd_body,
            labels=["sw:prd", f"sw:unit:{shared_unit}"],
            project_key=project_key,
            artifact_type="prd",
            unit_id=shared_unit,
        )
        (root / ISSUE_UNIT_INDEX).write_text(
            json.dumps({"version": 1, "units": {issue_index_key(project_key, shared_unit): prd.id}}),
            encoding="utf-8",
        )
        tasks_content = (
            "---\n"
            f"id: {shared_unit}\n"
            "type: tasks\n"
            "status: proposed\n"
            "---\n"
            "# Tasks wrongly reusing PRD unit id\n"
        )
        try:
            backend.put(shared_unit, f"docs/prds/{shared_unit}/tasks.md", tasks_content)
        except SystemExit as exc:
            if exc.code not in (2, 20):
                return {
                    "verdict": "fail",
                    "check": "unit_index_concurrent_self_heal_marker_reuse",
                    "error": f"unexpected-exit:{exc.code}",
                }
        else:
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_marker_reuse",
                "error": "expected-unit-id-marker-reuse-refusal",
            }
    return {"verdict": "ok", "check": "unit_index_concurrent_self_heal_marker_reuse"}


def check_unit_index_concurrent_self_heal_polluted_index() -> dict:
    """R39 — heal polluted index once; emit audit before/after/cause."""
    import tempfile

    os.environ["SW_ISSUES_FIXTURE"] = "1"
    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "r39-heal"
        cfg = _init_issue_store_repo(root, project_key)
        backend = IssueStoreBackend(root, cfg)
        valid_unit = "valid-gap-unit"
        prd_body = compose_issue_body(
            project_key,
            "gap",
            valid_unit,
            "---\nid: valid-gap-unit\ntype: gap\nstatus: proposed\n---\n# Gap\n",
        )
        record = backend._client.issue_create(
            title="Gap",
            body=prd_body,
            labels=["sw:gap", f"sw:unit:{valid_unit}"],
            project_key=project_key,
            artifact_type="gap",
            unit_id=valid_unit,
        )
        ghost_id = "ghost-issue-404"
        index = {
            issue_index_key(project_key, valid_unit): record.id,
            issue_index_key(project_key, "orphan-unit"): ghost_id,
        }
        save_issue_unit_index(root, index)

        def _resolve(issue_id: str):
            if issue_id == ghost_id:
                return None
            try:
                return backend._client.issue_get(issue_id)
            except Exception:
                return None

        healed = self_heal_unit_index(root, cfg)
        if healed.get("removedCount", 0) < 1:
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_polluted_index",
                "error": "heal-removed-none",
                "result": healed,
            }
        if ghost_id in load_issue_unit_index(root).values():
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_polluted_index",
                "error": "ghost-still-indexed",
            }
        audit_path = root / ISSUE_UNIT_INDEX_AUDIT
        if not audit_path.is_file():
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_polluted_index",
                "error": "missing-audit",
            }
        audit_line = json.loads(audit_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        if not audit_line.get("before") or audit_line.get("cause") != "missing-issue":
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_polluted_index",
                "error": "audit-missing-before-or-cause",
                "audit": audit_line,
            }
        # Idempotent second heal — no duplicate removal.
        again = self_heal_issue_unit_index(
            root,
            project_key=project_key,
            resolve_record=_resolve,
            record_unit_id=lambda rec: str(getattr(rec, "unit_id", "") or ""),
            record_artifact_type=lambda rec: str(getattr(rec, "artifact_type", "") or ""),
        )
        if again.get("removedCount", 0) != 0:
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_polluted_index",
                "error": "heal-not-idempotent",
                "again": again,
            }
    return {"verdict": "ok", "check": "unit_index_concurrent_self_heal_polluted_index"}


def check_unit_index_concurrent_self_heal_winner() -> dict:
    """R39 — concurrent puts preserve one winner per unit key (no dual repoint)."""
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "demo"
        idx_key = issue_index_key(project_key, "contested-unit")
        winners: list[str] = []
        errors: list[str] = []
        barrier = threading.Barrier(2)

        def racer(suffix: str) -> None:
            try:
                barrier.wait(timeout=5)

                def _update(index: dict[str, str]) -> None:
                    index[idx_key] = f"issue-{suffix}"

                mutate_issue_unit_index(root, _update)
                winners.append(f"issue-{suffix}")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(str(exc))

        threads = [
            threading.Thread(target=racer, args=(suffix,), daemon=True) for suffix in ("first", "second")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        if errors:
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_winner",
                "errors": errors,
            }
        final = load_issue_unit_index(root).get(idx_key)
        if final not in {"issue-first", "issue-second"}:
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_winner",
                "error": "no-single-winner",
                "final": final,
            }
        if len({final}) != 1:
            return {
                "verdict": "fail",
                "check": "unit_index_concurrent_self_heal_winner",
                "error": "ambiguous-winner",
            }
    return {"verdict": "ok", "check": "unit_index_concurrent_self_heal_winner", "winner": final}


def check_file_backed_atomic_write() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        target = root / "docs" / "planning" / "unit.md"
        atomic_write_text(target, "hello\n", root=root, store_id=FILE_BACKED_STORE_TXN_ID)
        if target.read_text(encoding="utf-8") != "hello\n":
            return {"verdict": "fail", "check": "atomic-write-content"}
        lock_dir = root / ".cursor" / "hooks" / "state" / "planning-txn" / FILE_BACKED_STORE_TXN_ID
        if not (lock_dir / "store.lock").is_file():
            return {"verdict": "fail", "check": "atomic-write-lock-artifact"}
    return {"verdict": "ok", "check": "atomic-write"}


def main() -> int:
    checks = [
        check_concurrent_index_updates_no_lost_write(),
        check_index_reread_under_lock(),
        check_file_backed_atomic_write(),
        check_unit_index_concurrent_self_heal_marker_reuse(),
        check_unit_index_concurrent_self_heal_polluted_index(),
        check_unit_index_concurrent_self_heal_winner(),
    ]
    failed = [item for item in checks if item.get("verdict") != "ok"]
    print(json.dumps({"verdict": "ok" if not failed else "fail", "checks": checks}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
