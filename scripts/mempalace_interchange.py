#!/usr/bin/env python3
"""Hermetic MemPalace JSONL/OKF interchange adapter (PRD 074 R26/R27).

Uses a file-backed palace layout under ``palacePath`` so CI can round-trip without a live
MemPalace daemon. Layout mirrors synthesized export/import semantics from
``core/providers/mempalace.md`` (drawers + KG ``links[]``).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "shipwright-palace.json"
DRAWERS_DIR = "drawers"
KG_FILE = "kg.json"
DEFAULT_WING = "__global__"
RULES_ROOM = "rules"


class InterchangeError(Exception):
    def __init__(self, message: str, *, cause: str = "error") -> None:
        super().__init__(message)
        self.cause = cause


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_in_repo_search():
    path = Path(__file__).resolve().parent / "in-repo-memory-search.py"
    spec = importlib.util.spec_from_file_location("in_repo_memory_search", path)
    if spec is None or spec.loader is None:
        raise InterchangeError("in-repo-memory-search.py not found", cause="missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _palace_root(palace_path: Path) -> Path:
    return palace_path.expanduser().resolve()


def _drawers_dir(palace_path: Path) -> Path:
    return _palace_root(palace_path) / DRAWERS_DIR


def _kg_path(palace_path: Path) -> Path:
    return _palace_root(palace_path) / KG_FILE


def _manifest_path(palace_path: Path) -> Path:
    return _palace_root(palace_path) / MANIFEST_NAME


def ensure_palace(palace_path: Path) -> Path:
    root = _palace_root(palace_path)
    root.mkdir(parents=True, exist_ok=True)
    drawers = _drawers_dir(palace_path)
    drawers.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_path(palace_path)
    if not manifest.is_file():
        manifest.write_text(
            json.dumps({"version": 1, "createdAt": _utc_now(), "adapter": "shipwright-mempalace-interchange"}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    kg = _kg_path(palace_path)
    if not kg.is_file():
        kg.write_text(json.dumps({"links": []}, indent=2) + "\n", encoding="utf-8")
    return root


def _drawer_path(palace_path: Path, drawer_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", drawer_id)
    return _drawers_dir(palace_path) / f"{safe}.json"


def load_drawer(palace_path: Path, drawer_id: str) -> dict[str, Any] | None:
    path = _drawer_path(palace_path, drawer_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def list_drawer_ids(palace_path: Path) -> list[str]:
    drawers = _drawers_dir(palace_path)
    if not drawers.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(drawers.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            ids.append(str(data["id"]))
    return ids


def load_kg_links(palace_path: Path) -> list[dict[str, str]]:
    path = _kg_path(palace_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    links = data.get("links") if isinstance(data, dict) else []
    if not isinstance(links, list):
        return []
    out: list[dict[str, str]] = []
    for entry in links:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source") or entry.get("from") or "").strip()
        target = str(entry.get("target") or entry.get("to") or "").strip()
        edge = str(entry.get("edge") or entry.get("type") or "relates-to")
        if source and target:
            out.append({"source": source, "target": target, "edge": edge})
    return out


def save_kg_links(palace_path: Path, links: list[dict[str, str]]) -> None:
    ensure_palace(palace_path)
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for link in links:
        key = (link["source"], link["target"], link["edge"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    _kg_path(palace_path).write_text(json.dumps({"links": deduped}, indent=2) + "\n", encoding="utf-8")


def write_drawer(palace_path: Path, drawer: dict[str, Any]) -> Path:
    ensure_palace(palace_path)
    drawer_id = str(drawer["id"])
    path = _drawer_path(palace_path, drawer_id)
    path.write_text(json.dumps(drawer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def drawer_fingerprint(drawer: dict[str, Any]) -> str:
    payload = {
        "id": drawer.get("id"),
        "wing": drawer.get("wing"),
        "room": drawer.get("room"),
        "content": drawer.get("content"),
        "fields": drawer.get("fields"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def remap_id_for_merge_with_palace(
    palace_path: Path,
    existing_ids: set[str],
    imported_id: str,
    incoming: dict[str, Any],
) -> tuple[str, bool]:
    if imported_id not in existing_ids:
        return imported_id, False
    current = load_drawer(palace_path, imported_id)
    if current and drawer_fingerprint(current) == drawer_fingerprint(incoming):
        return imported_id, False
    suffix = hashlib.sha256(imported_id.encode("utf-8")).hexdigest()[:8]
    candidate = f"{imported_id}-sw-{suffix}"
    counter = 1
    while candidate in existing_ids:
        candidate = f"{imported_id}-sw-{suffix}-{counter}"
        counter += 1
    return candidate, True


def record_to_drawer(record: dict[str, Any], *, wing: str) -> dict[str, Any]:
    category = str(record.get("category") or "learning")
    fields = dict(record.get("fields") or {})
    fields.pop("category", None)
    room = str(fields.pop("room", None) or category)
    if room == "rule":
        room = RULES_ROOM
    scope = str(fields.get("scope") or "project")
    resolved_wing = DEFAULT_WING if scope == "global" else wing
    return {
        "id": str(record["id"]),
        "wing": resolved_wing,
        "room": room,
        "content": str(record.get("body") or ""),
        "fields": fields,
        "updatedAt": _utc_now(),
    }


def drawer_to_record(drawer: dict[str, Any]) -> dict[str, Any]:
    fields = dict(drawer.get("fields") or {})
    room = str(drawer.get("room") or "learning")
    category = "rule" if room == RULES_ROOM else room
    fields["category"] = category
    fields["id"] = str(drawer["id"])
    scope = "global" if str(drawer.get("wing") or "") == DEFAULT_WING else "project"
    if "scope" not in fields:
        fields["scope"] = scope
    return {
        "id": str(drawer["id"]),
        "category": category,
        "fields": fields,
        "body": str(drawer.get("content") or ""),
    }


def extract_record_links(record: dict[str, Any]) -> list[dict[str, str]]:
    search = _load_in_repo_search()
    fields = dict(record.get("fields") or {})
    source = str(record["id"])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_link(target: str, edge: str) -> None:
        key = (target, edge)
        if key in seen:
            return
        seen.add(key)
        out.append({"source": source, "target": target, "edge": edge})

    links_raw = fields.get("links")
    if links_raw is None and "links" in record:
        links_raw = record.get("links")
    for entry in _normalize_link_entries(links_raw):
        parsed = search.parse_link_entry(entry)
        if parsed:
            add_link(parsed[0], parsed[1])

    body = str(record.get("body") or fields.get("content") or record.get("content") or "")
    for target, edge in search.extract_inline_links(body):
        add_link(target, edge)
    return out


def _normalize_link_entries(links_raw: Any) -> list[Any]:
    if not links_raw:
        return []
    if isinstance(links_raw, list):
        if links_raw and all(isinstance(item, str) for item in links_raw):
            joined = ", ".join(links_raw)
            if joined.startswith("{") or joined.startswith("["):
                try:
                    parsed = json.loads(joined)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return [parsed]
                if isinstance(parsed, list):
                    return parsed
        return links_raw
    if isinstance(links_raw, str):
        text = links_raw.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return [links_raw]
            if isinstance(parsed, dict):
                return [parsed]
            if isinstance(parsed, list):
                return parsed
        return [links_raw]
    return [links_raw]


def parse_interchange_records(fmt: str, source: Path) -> list[dict[str, Any]]:
    search = _load_in_repo_search()
    imported: list[dict[str, Any]] = []
    if fmt == "jsonl":
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InterchangeError(f"jsonl line {line_no}: {exc}", cause="malformed") from exc
            if not isinstance(obj, dict):
                raise InterchangeError(f"jsonl line {line_no}: expected object", cause="malformed")
            imported.append(search.jsonl_to_record(obj))
        return imported
    if fmt == "okf":
        for path in sorted(source.rglob("*.md")):
            if path.name in search.RESERVED_OKF_NAMES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            fm, body = search.parse_frontmatter(text)
            if not fm.get("type"):
                continue
            imported.append(search.okf_fields_to_record(fm, body))
        return imported
    raise InterchangeError(f"unsupported format: {fmt}", cause="unsupported")


def export_palace(palace_path: Path, fmt: str, out: Path, *, wing: str | None = None) -> dict[str, Any]:
    ensure_palace(palace_path)
    records = [drawer_to_record(load_drawer(palace_path, drawer_id) or {"id": drawer_id}) for drawer_id in list_drawer_ids(palace_path)]
    records = [r for r in records if r.get("id")]
    kg_links = load_kg_links(palace_path)
    link_by_source: dict[str, list[dict[str, str]]] = {}
    for link in kg_links:
        link_by_source.setdefault(link["source"], []).append({"to": link["target"], "edge": link["edge"]})
    for record in records:
        fields = record.setdefault("fields", {})
        merged = list(fields.get("links") or [])
        for link in link_by_source.get(record["id"], []):
            if link not in merged:
                merged.append(link)
        if merged:
            fields["links"] = merged

    search = _load_in_repo_search()
    if fmt == "jsonl":
        lines = [json.dumps(search.record_to_jsonl(record), sort_keys=True) for record in records]
        payload = "\n".join(lines) + ("\n" if lines else "")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        return {"provider": "mempalace", "format": "jsonl", "out": str(out), "count": len(records)}
    if fmt == "okf":
        out.mkdir(parents=True, exist_ok=True)
        for record in records:
            category = record["category"]
            category_dir = out / category
            category_dir.mkdir(parents=True, exist_ok=True)
            fields = search.record_to_okf_fields(record)
            body = search.redact_text(record["body"])
            target = category_dir / f"{record['id']}.md"
            target.write_text(search.render_memory_file(fields, body), encoding="utf-8")
        (out / "index.md").write_text(search.render_store_index(records, okf_bundle_root=True), encoding="utf-8")
        (out / "log.md").write_text(search.render_store_log(records), encoding="utf-8")
        return {"provider": "mempalace", "format": "okf", "out": str(out), "count": len(records)}
    raise InterchangeError(f"unsupported export format: {fmt}", cause="unsupported")


def import_palace(
    palace_path: Path,
    fmt: str,
    source: Path,
    *,
    dry_run: bool,
    wing: str,
) -> dict[str, Any]:
    records = parse_interchange_records(fmt, source)
    ensure_palace(palace_path)
    existing_ids = set(list_drawer_ids(palace_path))
    id_map: dict[str, str] = {}
    remapped: list[dict[str, str]] = []
    incoming_links: list[dict[str, str]] = []

    for record in records:
        drawer = record_to_drawer(record, wing=wing)
        original_id = str(record["id"])
        final_id, was_remapped = remap_id_for_merge_with_palace(
            palace_path, existing_ids | set(id_map.values()), original_id, drawer
        )
        if was_remapped:
            remapped.append({"from": original_id, "to": final_id})
        id_map[original_id] = final_id
        drawer["id"] = final_id
        if not dry_run:
            write_drawer(palace_path, drawer)
        existing_ids.add(final_id)
        for link in extract_record_links({**record, "id": original_id}):
            incoming_links.append(
                {
                    "source": id_map.get(link["source"], link["source"]),
                    "target": id_map.get(link["target"], link["target"]),
                    "edge": link["edge"],
                }
            )

    if not dry_run and incoming_links:
        merged = load_kg_links(palace_path) + incoming_links
        save_kg_links(palace_path, merged)

    return {
        "verdict": "pass",
        "dryRun": dry_run,
        "format": fmt,
        "imported": len(records),
        "plannedImport": len(records),
        "source": str(source),
        "palacePath": str(_palace_root(palace_path)),
        "idRemaps": remapped,
        "linksImported": len(incoming_links),
    }
