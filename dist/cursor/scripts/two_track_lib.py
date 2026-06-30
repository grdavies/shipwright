#!/usr/bin/env python3
"""Two-track docs edit classifier and INDEX region hashing (PRD 035 R11/R14/R18)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402

TRACK_MECHANICAL = "mechanical"
TRACK_SUBSTANTIVE = "substantive"

UNIT_BODY_RE = re.compile(r"^docs/planning/[^/]+/.+")
PLANNING_UNIT_PREFIX_RE = re.compile(r"^docs/planning/[^/]+/")
HASH_MARKER_RE = re.compile(r"<!--\s*two-track-index-hash:\s*([a-f0-9]{64})\s*-->", re.I)
INFLIGHT_MARKER = pig.REGION_MARKERS["inFlight"][0]
DERIVED_MARKER = pig.REGION_MARKERS["derived"][0]
STRUCTURAL_MARKER = pig.REGION_MARKERS["structural"][0]


@dataclass(frozen=True)
class Classification:
    track: str
    reason: str
    paths: tuple[str, ...]


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def load_two_track_config(root: Path) -> dict[str, Any]:
    cfg = pp.load_workflow_config(root)
    docs = cfg.get("docs") if isinstance(cfg.get("docs"), dict) else {}
    two = docs.get("twoTrack") if isinstance(docs.get("twoTrack"), dict) else {}
    return {
        "mechanicalBranch": str(two.get("mechanicalBranch") or "docs/mechanical-maintenance"),
        "allowDirectTrunk": bool(two.get("allowDirectTrunk", False)),
        "protectionProbeTtlSeconds": int(two.get("protectionProbeTtlSeconds") or 300),
    }


def artifact_paths(root: Path) -> dict[str, str]:
    dirs = pp.load_planning_dirs(root)
    return {
        "index_active": pp.join_rel(dirs.planning, "INDEX.md"),
        "index_archive": pp.join_rel(dirs.prds, "INDEX-archive.md"),
        "superseded": pp.join_rel(dirs.prds, "SUPERSEDED.md"),
        "gap_index": pp.join_rel(dirs.prds, "GAP-BACKLOG.md"),
    }


def is_planning_unit_path(path: str) -> bool:
    rel = normalize_rel(path)
    return bool(PLANNING_UNIT_PREFIX_RE.match(rel))


def is_mechanical_artifact_path(root: Path, path: str) -> bool:
    rel = normalize_rel(path)
    arts = artifact_paths(root)
    return rel in {
        arts["index_active"],
        arts["index_archive"],
        arts["superseded"],
        arts["gap_index"],
    }


def classify_paths(
    root: Path,
    paths: list[str],
    *,
    index_region: str | None = None,
) -> Classification:
    rels = [normalize_rel(p) for p in paths if p.strip()]
    if not rels:
        return Classification(TRACK_SUBSTANTIVE, "empty-path-set", tuple())

    for rel in rels:
        if is_planning_unit_path(rel):
            return Classification(TRACK_SUBSTANTIVE, "planning-unit-path", tuple(rels))

    if index_region == "inFlight":
        return Classification(TRACK_SUBSTANTIVE, "inflight-region-forbidden", tuple(rels))

    arts = artifact_paths(root)
    for rel in rels:
        if rel == arts["index_active"] or rel == arts["index_archive"]:
            if index_region in (None, "structural"):
                return Classification(TRACK_SUBSTANTIVE, "index-non-derived-region", tuple(rels))
            if index_region != "derived":
                return Classification(TRACK_SUBSTANTIVE, "index-non-derived-region", tuple(rels))
        elif not is_mechanical_artifact_path(root, rel):
            return Classification(TRACK_SUBSTANTIVE, "not-on-mechanical-allowlist", tuple(rels))

    return Classification(TRACK_MECHANICAL, "mechanical-allowlist", tuple(rels))




def dual_region_index_path(root: Path) -> Path | None:
    """Resolve planning-index dual-region file (R5); tolerate legacy planningDir → prds alias."""
    worktree = pp.git_root(root)
    candidates: list[Path] = []
    canonical = worktree / pp.schema_dir_default(root, "planningDir") / "INDEX.md"
    configured = pig.index_path(root)
    for candidate in (canonical, configured):
        if candidate in candidates:
            continue
        candidates.append(candidate)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        content = candidate.read_text(encoding="utf-8")
        if pig.SCHEMA_MARKER in content:
            return candidate
    return None

def both_region_content_hash(root: Path) -> str:
    idx = dual_region_index_path(root)
    if idx is None:
        return hashlib.sha256(b"").hexdigest()
    content = idx.read_text(encoding="utf-8")
    regions = pig.parse_regions(content)
    payload = regions.derived.encode("utf-8") + b"\n---\n" + regions.inFlight.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_marker(hash_value: str) -> str:
    return f"<!-- two-track-index-hash: {hash_value} -->"


def extract_embedded_hash(text: str) -> str | None:
    match = HASH_MARKER_RE.search(text)
    return match.group(1).lower() if match else None


def diff_paths(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[6:].strip())
        elif line.startswith("--- a/"):
            p = line[6:].strip()
            if p != "/dev/null" and p not in paths:
                paths.append(p)
    return paths


def diff_touches_marker(diff_text: str, marker: str) -> bool:
    for line in diff_text.splitlines():
        if not line.startswith(("+", "-")):
            continue
        if line.startswith(("+++", "---")):
            continue
        if marker in line[1:]:
            return True
    return False


def validate_mechanical_diff(root: Path, diff_text: str) -> dict[str, Any]:
    violations: list[str] = []
    for path in diff_paths(diff_text):
        rel = normalize_rel(path)
        if is_planning_unit_path(rel):
            violations.append(f"planning-unit-path:{rel}")
        if rel.endswith("/INDEX.md") or rel.endswith("INDEX.md"):
            if diff_touches_marker(diff_text, INFLIGHT_MARKER):
                violations.append("inflight-region-edit")
            if diff_touches_marker(diff_text, STRUCTURAL_MARKER):
                violations.append("structural-region-edit")

    added = "\n".join(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    if re.search(r"docs/planning/[^/\s]+/", added):
        violations.append("unit-body-marker-in-diff")

    if violations:
        return {"verdict": "fail", "violations": violations}
    return {"verdict": "pass"}


def classify_diff(root: Path, diff_text: str) -> Classification:
    paths = diff_paths(diff_text)
    index_region = "derived"
    if diff_touches_marker(diff_text, INFLIGHT_MARKER):
        index_region = "inFlight"
    elif diff_touches_marker(diff_text, STRUCTURAL_MARKER):
        index_region = "structural"
    return classify_paths(root, paths, index_region=index_region)


def cmd_classify(root: Path, args: argparse.Namespace) -> None:
    paths = list(args.paths or [])
    if args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        result = classify_diff(root, diff_text)
    else:
        result = classify_paths(root, paths, index_region=args.index_region)
    emit(
        {
            "verdict": "pass",
            "track": result.track,
            "reason": result.reason,
            "paths": list(result.paths),
        }
    )


def cmd_content_hash(root: Path, _args: argparse.Namespace) -> None:
    emit({"verdict": "pass", "hash": both_region_content_hash(root), "marker": hash_marker(both_region_content_hash(root))})


def cmd_validate_mechanical(root: Path, args: argparse.Namespace) -> None:
    if args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8")
    elif args.diff_stdin:
        diff_text = sys.stdin.read()
    else:
        fail("diff required")
    out = validate_mechanical_diff(root, diff_text)
    emit(out, 0 if out["verdict"] == "pass" else 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Two-track docs edit classifier")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)

    classify = sub.add_parser("classify")
    classify.add_argument("--paths", nargs="*", default=[])
    classify.add_argument("--index-region", choices=["derived", "inFlight", "structural"])
    classify.add_argument("--diff-file")
    classify.set_defaults(func=cmd_classify)

    content_hash = sub.add_parser("content-hash")
    content_hash.set_defaults(func=cmd_content_hash)

    validate = sub.add_parser("validate-mechanical-diff")
    validate.add_argument("--diff-file")
    validate.add_argument("--diff-stdin", action="store_true")
    validate.set_defaults(func=cmd_validate_mechanical)

    args = parser.parse_args()
    root = pp.git_root(args.root)
    args.func(root, args)


if __name__ == "__main__":
    main()
