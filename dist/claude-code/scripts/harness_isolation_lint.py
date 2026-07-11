#!/usr/bin/env python3
"""Harness isolation lint — shared config, baseline I/O, planning-store pollution (PRD 060 R14–R15, 063 R10)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REMEDIATION = "python3 scripts/harness_isolation_lint.py --check"
OPT_OUT_PREFIX = "harness-isolation-opt-out:"
MANIFEST_REL = "core/sw-reference/harness-roots-manifest.json"
PLANNING_STORE_MARKERS = ("override-add", "capture_verify_override", "store_put_gap")
ISOLATION_MARKERS = (
    "$TMP", "$FIXTURES", "mktemp", "tempfile", "tmp_path", "monkeypatch",
    "fake_put", "harness-isolation-opt-out:", "SW_HARNESS", "OV_TMP",
)


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def has_opt_out(text: str) -> bool:
    return OPT_OUT_PREFIX in text


def mutates_shared_workflow_config(text: str) -> bool:
    if "workflow.config.json" not in text:
        return False
    if "CFG_BACKUP" in text and "restore_config" in text and "write_text" not in text:
        return False
    if "write_text" in text and "workflow.config.json" in text:
        return True
    if re.search(r"cp\s+[^\n]*workflow\.config\.json", text):
        return True
    if re.search(r">\s*[^\n]*workflow\.config\.json", text):
        return True
    return False


def baseline_io_without_isolation(text: str) -> bool:
    if "verify-baseline" not in text and "baseline.verify.json" not in text and ".shipwright/baseline" not in text:
        return False
    if any(marker in text for marker in ISOLATION_MARKERS):
        return False
    return True


def _touches_planning_store(text: str) -> bool:
    if "capture_verify_override" in text or "store_put_gap" in text:
        return True
    return re.search(r"(?<!dispatch-)override-add", text) is not None


def planning_store_without_isolation(text: str) -> bool:
    if not _touches_planning_store(text):
        return False
    return not any(marker in text for marker in ISOLATION_MARKERS)


def scan_file(root: Path, path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if has_opt_out(text):
        return None
    hit: dict[str, object] = {"file": str(path.relative_to(root))}
    flagged = False
    if mutates_shared_workflow_config(text) and baseline_io_without_isolation(text):
        hit["mutatesSharedConfig"] = True
        hit["baselineIoWithoutIsolation"] = True
        flagged = True
    if planning_store_without_isolation(text):
        hit["planningStoreWithoutIsolation"] = True
        flagged = True
    return hit if flagged else None


def iter_manifest_files(root: Path) -> list[Path]:
    manifest = root / MANIFEST_REL
    if not manifest.is_file():
        return sorted((root / "scripts/unit_tests").rglob("*.py")) if (root / "scripts/unit_tests").is_dir() else []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    roots = data.get("roots") or ["scripts/unit_tests/**"]
    files: list[Path] = []
    for pattern in roots:
        files.extend(sorted(root.glob(pattern)))
    return [p for p in files if p.is_file()]


def check(root: Path) -> dict:
    violations: list[dict] = []
    files = iter_manifest_files(root)
    for path in files:
        hit = scan_file(root, path)
        if hit:
            violations.append(hit)
    if violations:
        emit(
            {
                "verdict": "fail",
                "error": "harness-isolation",
                "violations": violations,
                "remediation": REMEDIATION,
            },
            1,
        )
    emit({"verdict": "pass", "action": "harness-isolation-lint", "filesScanned": len(files)})
    return {"verdict": "pass"}


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(__file__).resolve().parent.parent
    if args == ["--check"]:
        check(root)
    emit({"verdict": "fail", "error": "usage: harness_isolation_lint.py --check"})


if __name__ == "__main__":
    main()
