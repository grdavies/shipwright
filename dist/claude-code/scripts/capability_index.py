"""Emitter-generated capability index from per-capability frontmatter (PRD 021 TR2)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from yaml_structured import safe_load

INDEX_VERSION = 1
CAPABILITY_ROOTS = (
    ("skills", "skill"),
    ("agents", "persona"),
    ("rules", "rule"),
    ("providers", "provider"),
    ("hooks", "hook"),
)
EXECUTABLE_KINDS = frozenset({"provider", "hook"})
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def derive_kind(source_path: str) -> str:
    rel = source_path.removeprefix("core/")
    for prefix, kind in CAPABILITY_ROOTS:
        if rel.startswith(f"{prefix}/"):
            return kind
    raise ValueError(f"cannot derive kind for {source_path}")


def capability_id(source_path: str, kind: str) -> str:
    rel = Path(source_path.removeprefix("core/"))
    if kind == "skill":
        return f"skill.{rel.parent.name}"
    if kind in {"persona", "rule", "hook"}:
        return f"{kind}.{rel.stem}"
    parts = rel.parts
    if len(parts) == 1:
        return f"provider.{rel.stem}"
    return f"provider.{'.'.join(parts[:-1])}.{rel.stem}"


def parse_frontmatter(text: str) -> dict[str, Any]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    parsed = safe_load(match.group(1))
    return parsed if isinstance(parsed, dict) else {}


def collect_capability_files(core_root: Path) -> list[Path]:
    files: list[Path] = []
    for dirname, _kind in CAPABILITY_ROOTS:
        root = core_root / dirname
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in {".md", ".mdc"}:
                continue
            if path.name == "CAPABILITIES.md":
                files.append(path)
                continue
            if dirname == "skills" and path.name != "SKILL.md":
                continue
            if dirname == "providers" and path.suffix != ".md":
                continue
            files.append(path)
    return files


def build_entry(core_root: Path, path: Path) -> dict[str, Any] | None:
    rel = path.relative_to(core_root)
    source_path = f"core/{rel.as_posix()}"
    text = path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(text)
    capability = frontmatter.get("capability")
    if not isinstance(capability, dict):
        return None
    kind = derive_kind(source_path)
    return {
        "id": capability_id(source_path, kind),
        "kind": kind,
        "sourcePath": source_path,
        "executable": kind in EXECUTABLE_KINDS,
        "capability": capability,
    }


def build_index(core_root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in collect_capability_files(core_root):
        entry = build_entry(core_root, path)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda row: row["id"])
    return {"version": INDEX_VERSION, "capabilities": entries}


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_index(core_root: Path, index: dict[str, Any] | None = None) -> Path:
    if index is None:
        index = build_index(core_root)
    out = core_root / "sw-reference" / "capability-index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def check_freshness(core_root: Path, index_path: Path | None = None) -> tuple[bool, str]:
    path = index_path or (core_root / "sw-reference" / "capability-index.json")
    if not path.is_file():
        return False, f"missing committed index: {path}"
    try:
        committed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid index JSON: {exc}"
    expected = build_index(core_root)
    if canonical_json(committed) != canonical_json(expected):
        return False, "capability-index.json does not match frontmatter aggregate"
    return True, "fresh"
