#!/usr/bin/env python3
"""Deterministic in-repo memory search, export/import, traversal, and derived index/log maintenance."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

OKF_VERSION = "0.1"
CANONICAL_CATEGORIES = (
    "decision",
    "learning",
    "debug",
    "design",
    "code-context",
    "playbook",
    "research",
    "discussion",
    "progress",
    "rule",
)
RESERVED_OKF_NAMES = frozenset({"index.md", "log.md"})
INLINE_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
MEMORY_PATH_RE = re.compile(r"^(?:memories|rules|global/memories)/([^/]+)\.md$")
KNOWN_EDGES = frozenset({"supersedes", "relates-to", "file-linked"})
EXCLUDED_STATUSES = frozenset({"superseded", "resolved", "tombstone"})
COMPILED_TRUTH_HEADING = "## Compiled truth"
TIMELINE_HEADING = "## Timeline"
TIMELINE_ENTRY_RE = re.compile(
    r"^- `([a-z0-9-]+)` @ (\S+) — (.+)$",
    re.IGNORECASE,
)
TIMELINE_KINDS = frozenset({
    "created",
    "truth-updated",
    "inactivated",
    "reactivated",
    "imported",
    "modified",
})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_rule_record(record: dict[str, Any]) -> bool:
    return str(record.get("category") or record.get("fields", {}).get("category") or "") == "rule"


def parse_timeline_entries(block: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in block.splitlines():
        match = TIMELINE_ENTRY_RE.match(line.strip())
        if not match:
            continue
        entries.append({
            "kind": match.group(1).lower(),
            "at": match.group(2),
            "summary": match.group(3).strip(),
        })
    return entries


def render_timeline_entries(entries: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for entry in entries:
        kind = str(entry.get("kind") or "modified")
        at = str(entry.get("at") or utc_now_iso())
        summary = str(entry.get("summary") or "").replace("\n", " ").strip() or "(no summary)"
        lines.append(f"- `{kind}` @ {at} — {summary}")
    return "\n".join(lines)


def parse_body_sections(body: str) -> dict[str, Any]:
    """Split a memory body into compiled truth, timeline, and remaining sections.

    Legacy bodies without headings treat the full body as compiled truth.
    """
    text = body or ""
    truth_idx = text.find(COMPILED_TRUTH_HEADING)
    timeline_idx = text.find(TIMELINE_HEADING)
    if truth_idx < 0 and timeline_idx < 0:
        return {
            "compiled_truth": text.strip(),
            "timeline": [],
            "rest": "",
            "legacy": True,
        }

    truth = ""
    timeline: list[dict[str, str]] = []
    rest_parts: list[str] = []

    if truth_idx >= 0:
        after_truth = text[truth_idx + len(COMPILED_TRUTH_HEADING):]
        next_heading = after_truth.find("\n## ")
        if next_heading >= 0:
            truth = after_truth[:next_heading].strip()
            remainder = after_truth[next_heading + 1:]
        else:
            truth = after_truth.strip()
            remainder = ""
    else:
        remainder = text
        # No compiled-truth heading: body before timeline is truth.
        if timeline_idx >= 0:
            truth = text[:timeline_idx].strip()
            remainder = text[timeline_idx:]

    if TIMELINE_HEADING in remainder or remainder.startswith("## Timeline"):
        if not remainder.startswith("## Timeline"):
            tpos = remainder.find(TIMELINE_HEADING)
            if tpos > 0:
                rest_parts.append(remainder[:tpos].strip())
            remainder = remainder[tpos:] if tpos >= 0 else remainder
        after_tl = remainder[len(TIMELINE_HEADING):] if remainder.startswith(TIMELINE_HEADING) else remainder
        # Strip leading newline
        if after_tl.startswith("\n"):
            after_tl = after_tl[1:]
        next_heading = after_tl.find("\n## ")
        citations = after_tl.find("\n# ")
        cut = -1
        for candidate in (next_heading, citations):
            if candidate >= 0 and (cut < 0 or candidate < cut):
                cut = candidate
        if cut >= 0:
            timeline_block = after_tl[:cut]
            rest_parts.append(after_tl[cut + 1:].strip())
        else:
            timeline_block = after_tl
        timeline = parse_timeline_entries(timeline_block)
    elif remainder.strip():
        rest_parts.append(remainder.strip())

    return {
        "compiled_truth": truth,
        "timeline": timeline,
        "rest": "\n\n".join(part for part in rest_parts if part),
        "legacy": False,
    }


def render_body_sections(
    compiled_truth: str,
    timeline: list[dict[str, str]],
    rest: str = "",
) -> str:
    parts = [
        COMPILED_TRUTH_HEADING,
        "",
        compiled_truth.strip() or "(empty)",
        "",
        TIMELINE_HEADING,
        "",
        render_timeline_entries(timeline) or "- `created` @ " + utc_now_iso() + " — (empty timeline)",
    ]
    rest = (rest or "").strip()
    if rest:
        parts.extend(["", rest])
    return "\n".join(parts).rstrip() + "\n"


def compiled_truth_of(record: dict[str, Any]) -> str:
    sections = parse_body_sections(str(record.get("body") or ""))
    truth = str(sections.get("compiled_truth") or "").strip()
    if truth:
        return truth
    return str(record.get("body") or "").strip()


def timeline_of(record: dict[str, Any]) -> list[dict[str, str]]:
    sections = parse_body_sections(str(record.get("body") or ""))
    return list(sections.get("timeline") or [])


def ensure_truth_timeline_body(
    body: str,
    *,
    category: str,
    initial_kind: str = "created",
    initial_summary: str = "Initial memory created",
) -> str:
    """Ensure non-rule bodies carry compiled truth + timeline sections."""
    if category == "rule":
        return body
    sections = parse_body_sections(body)
    truth = str(sections.get("compiled_truth") or body).strip()
    timeline = list(sections.get("timeline") or [])
    if not timeline:
        timeline = [{
            "kind": initial_kind,
            "at": utc_now_iso(),
            "summary": initial_summary,
        }]
    return render_body_sections(truth, timeline, str(sections.get("rest") or ""))


def append_timeline_entry(
    body: str,
    *,
    kind: str,
    summary: str,
    at: str | None = None,
    category: str = "learning",
) -> str:
    if category == "rule":
        return body
    sections = parse_body_sections(body)
    truth = str(sections.get("compiled_truth") or body).strip()
    timeline = list(sections.get("timeline") or [])
    timeline.append({
        "kind": kind if kind in TIMELINE_KINDS else "modified",
        "at": at or utc_now_iso(),
        "summary": summary,
    })
    return render_body_sections(truth, timeline, str(sections.get("rest") or ""))


def atomic_write_text(path: Path, content: str) -> None:
    """Write via temp file + os.replace so readers never see partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if raw in {"null", "Null", "None"}:
        return None
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in re.split(r",\s*", inner) if item.strip()]
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = parse_scalar(value)
    body = parts[2].lstrip("\n")
    return fm, body


def format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        if value and all(isinstance(item, dict) for item in value):
            return json.dumps(value)
        items = ", ".join(json.dumps(str(item)) for item in value)
        return f"[{items}]"
    if value is None:
        return '""'
    return json.dumps(str(value))


def render_frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key in sorted(fields):
        lines.append(f"{key}: {format_scalar(fields[key])}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def render_memory_file(fields: dict[str, Any], body: str) -> str:
    return render_frontmatter(fields) + body.rstrip() + "\n"


def memory_id_from_path(path: Path) -> str:
    return path.stem


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def display_title(fields: dict[str, Any], body: str) -> str:
    title = fields.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    sections = parse_body_sections(body)
    truth = str(sections.get("compiled_truth") or "").strip()
    line = first_body_line(truth if truth else body)
    if line:
        return line[:120]
    mid = fields.get("id")
    if isinstance(mid, str) and mid:
        return mid
    return "untitled"


def iter_memory_files(store: Path) -> list[Path]:
    paths: list[Path] = []
    for sub in ("memories", "rules", "global/memories"):
        base = store / sub
        if not base.is_dir():
            continue
        paths.extend(sorted(base.rglob("*.md")))
    return paths


def read_memory_record(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    category = str(fm.get("category") or ("rule" if "rules" in path.parts else "learning"))
    record_id = str(fm.get("id") or memory_id_from_path(path))
    fm["id"] = record_id
    fm["category"] = category
    return {
        "id": record_id,
        "category": category,
        "fields": fm,
        "body": body,
        "path": path,
    }


def load_store_records(store: Path) -> list[dict[str, Any]]:
    return [read_memory_record(path) for path in iter_memory_files(store)]

def is_excluded_record(fields: dict[str, Any]) -> bool:
    if fields.get("inactive") is True:
        return True
    status = str(fields.get("status") or "").lower()
    return status in EXCLUDED_STATUSES


def normalize_link_target(raw: str) -> str | None:
    target = raw.strip()
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    path_match = MEMORY_PATH_RE.match(target)
    if path_match:
        return path_match.group(1)
    if target.endswith(".md"):
        return Path(target).stem
    if "/" not in target and " " not in target:
        return target
    return None


def parse_link_entry(entry: Any) -> tuple[str, str] | None:
    if isinstance(entry, str):
        tid = normalize_link_target(entry)
        return (tid, "relates-to") if tid else None
    if isinstance(entry, dict):
        raw_target = entry.get("to") or entry.get("target") or entry.get("id")
        if not raw_target:
            return None
        tid = normalize_link_target(str(raw_target))
        if not tid:
            return None
        edge = str(entry.get("edge") or entry.get("type") or "relates-to")
        return tid, edge
    return None


def extract_frontmatter_links(fields: dict[str, Any]) -> list[tuple[str, str]]:
    links_raw = fields.get("links")
    if not links_raw:
        return []
    entries = links_raw if isinstance(links_raw, list) else [links_raw]
    out: list[tuple[str, str]] = []
    for entry in entries:
        parsed = parse_link_entry(entry)
        if parsed:
            out.append(parsed)
    return out


def extract_inline_links(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _text, target in INLINE_MD_LINK_RE.findall(body):
        tid = normalize_link_target(target)
        if tid:
            out.append((tid, "relates-to"))
    return out


def build_edge_map(
    records: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    forward: dict[str, list[dict[str, str]]] = {}
    backlinks: dict[str, list[dict[str, str]]] = {}
    known_ids = {record["id"] for record in records}

    def add_edge(source: str, target: str, edge: str, *, kind: str) -> None:
        edge_entry = {
            "target": target,
            "edge": edge,
            "kind": kind,
            "dangling": target not in known_ids,
        }
        forward.setdefault(source, []).append(edge_entry)
        backlinks.setdefault(target, []).append({"source": source, "edge": edge, "kind": kind})

    for record in records:
        source = record["id"]
        for target, edge in extract_frontmatter_links(record["fields"]):
            add_edge(source, target, edge, kind="frontmatter")
        for target, edge in extract_inline_links(record["body"]):
            add_edge(source, target, edge, kind="inline")
    return forward, backlinks


def store_title_description(content: str, *, title: str = "", description: str = "") -> tuple[str, str]:
    body = content.strip()
    first = first_body_line(body)
    resolved_title = title.strip() or (first[:120] if first else "untitled")
    resolved_desc = description.strip() or (first[:240] if first else resolved_title)
    return resolved_title, resolved_desc


def reconcile_supersede_entries(
    store: Path, entries: list[tuple[str, str, str]]
) -> dict[str, Any]:
    records = load_store_records(store)
    if not records:
        return {"reconciled": 0, "actions": []}

    forward, _backlinks = build_edge_map(records)
    actions: list[dict[str, str]] = []
    reconciled = 0

    for _date, old_path, new_path in entries:
        old_path = old_path.strip()
        new_path = new_path.strip()
        if not old_path or not new_path:
            continue

        for record in records:
            if is_excluded_record(record["fields"]):
                continue
            fields = dict(record["fields"])
            related = fields.get("relatedFiles")
            related_list = related if isinstance(related, list) else []
            if not related_list:
                continue
            updated = False
            new_related: list[Any] = []
            for item in related_list:
                item_str = str(item)
                if item_str == old_path or item_str.endswith("/" + old_path.lstrip("/")):
                    new_related.append(new_path)
                    updated = True
                    actions.append({
                        "action": "repoint-relatedFiles",
                        "id": record["id"],
                        "from": old_path,
                        "to": new_path,
                    })
                else:
                    new_related.append(item)
            if updated:
                fields["relatedFiles"] = new_related
                write_memory_record(store, {**record, "fields": fields})
                reconciled += 1

        for record in records:
            if is_excluded_record(record["fields"]):
                continue
            for edge in forward.get(record["id"], []):
                if edge.get("edge") != "supersedes":
                    continue
                target = str(edge.get("target") or "")
                if target not in {Path(old_path).stem, old_path}:
                    continue
                fields = dict(record["fields"])
                fields["status"] = "superseded"
                write_memory_record(store, {**record, "fields": fields})
                actions.append({"action": "mark-superseded", "id": record["id"], "target": target})
                reconciled += 1

    if reconciled:
        maintain_derived(store)
    return {"reconciled": reconciled, "actions": actions}


def redact_text(text: str) -> str:
    try:
        from memory_redact import redact
    except ImportError:
        return text
    return redact(text)


def record_to_jsonl(record: dict[str, Any]) -> dict[str, Any]:
    fields = dict(record["fields"])
    fields.pop("id", None)
    sections = parse_body_sections(str(record.get("body") or ""))
    payload = {
        "id": record["id"],
        "content": record["body"].strip(),
        "category": record["category"],
        "compiledTruth": sections.get("compiled_truth") or "",
        "timeline": sections.get("timeline") or [],
    }
    for key, value in fields.items():
        if key == "category":
            continue
        payload[key] = value
    return payload


def jsonl_to_record(obj: dict[str, Any]) -> dict[str, Any]:
    category = str(obj.get("category") or "learning")
    record_id = str(obj.get("id") or "imported-memory")
    fields = {
        k: v
        for k, v in obj.items()
        if k not in {"content", "category", "id", "compiledTruth", "timeline"}
    }
    fields["category"] = category
    fields["id"] = record_id
    if "createdAt" not in fields:
        fields["createdAt"] = utc_now_iso()
    body = str(obj.get("content") or "")
    compiled = obj.get("compiledTruth")
    timeline = obj.get("timeline")
    if category != "rule":
        if isinstance(compiled, str) and compiled.strip():
            entries = timeline if isinstance(timeline, list) else []
            norm_entries: list[dict[str, str]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                norm_entries.append({
                    "kind": str(entry.get("kind") or "imported"),
                    "at": str(entry.get("at") or utc_now_iso()),
                    "summary": str(entry.get("summary") or "imported"),
                })
            if not norm_entries:
                norm_entries = [{
                    "kind": "imported",
                    "at": utc_now_iso(),
                    "summary": "Imported from legacy interchange",
                }]
            body = render_body_sections(compiled, norm_entries)
        else:
            body = ensure_truth_timeline_body(
                body,
                category=category,
                initial_kind="imported",
                initial_summary="Imported from legacy interchange",
            )
    title, description = store_title_description(
        compiled_truth_of({"body": body, "fields": fields}),
        title=str(fields.get("title") or ""),
        description=str(fields.get("description") or ""),
    )
    if "title" not in fields:
        fields["title"] = title
    if "description" not in fields:
        fields["description"] = description
    return {
        "id": record_id,
        "category": category,
        "fields": fields,
        "body": body,
    }


def target_path_for_record(store: Path, record: dict[str, Any]) -> Path:
    category = record["category"]
    if category == "rule":
        return store / "rules" / f"{record['id']}.md"
    scope = str(record["fields"].get("scope") or "project")
    if scope == "global":
        return store / "global" / "memories" / f"{record['id']}.md"
    return store / "memories" / f"{record['id']}.md"


def relative_memory_path(record: dict[str, Any]) -> str:
    category = record["category"]
    if category == "rule":
        return f"rules/{record['id']}.md"
    scope = str(record["fields"].get("scope") or "project")
    if scope == "global":
        return f"global/memories/{record['id']}.md"
    return f"memories/{record['id']}.md"


def write_memory_record(store: Path, record: dict[str, Any]) -> Path:
    path = target_path_for_record(store, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    category = str(record.get("category") or record.get("fields", {}).get("category") or "learning")
    body = ensure_truth_timeline_body(str(record.get("body") or ""), category=category)
    redacted_body = redact_text(body)
    # Timeline must not be silently stripped by redaction; preserve structure after redact.
    if category != "rule":
        redacted_body = ensure_truth_timeline_body(redacted_body, category=category)
    fields = dict(record["fields"])
    fields["id"] = record["id"]
    fields["category"] = record["category"]
    truth = compiled_truth_of({"body": redacted_body, "fields": fields})
    title, description = store_title_description(
        truth,
        title=str(fields.get("title") or ""),
        description=str(fields.get("description") or ""),
    )
    if not fields.get("title"):
        fields["title"] = title
    if not fields.get("description"):
        fields["description"] = description
    content = render_memory_file(fields, redacted_body)
    atomic_write_text(path, content)
    return path


def record_to_okf_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = dict(record["fields"])
    category = record["category"]
    fields.pop("category", None)
    fields["type"] = category
    fields["id"] = record["id"]
    if "timestamp" not in fields and "createdAt" in fields:
        fields["timestamp"] = fields["createdAt"]
    title = display_title(record["fields"], record["body"])
    if "title" not in fields:
        fields["title"] = title
    if "description" not in fields:
        fields["description"] = title
    return fields


def okf_fields_to_record(fields: dict[str, Any], body: str) -> dict[str, Any]:
    record_fields = dict(fields)
    type_value = str(record_fields.pop("type", record_fields.pop("category", "learning")))
    record_id = str(record_fields.pop("id", "imported-memory"))
    category = type_value
    record_fields["category"] = category
    record_fields["id"] = record_id
    if "timestamp" in record_fields and "createdAt" not in record_fields:
        record_fields["createdAt"] = record_fields["timestamp"]
    return {
        "id": record_id,
        "category": category,
        "fields": record_fields,
        "body": body,
    }


def render_store_index(records: list[dict[str, Any]], *, okf_bundle_root: bool = False) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {cat: [] for cat in CANONICAL_CATEGORIES}
    for record in records:
        grouped.setdefault(record["category"], []).append(record)

    lines: list[str] = []
    if okf_bundle_root:
        lines.extend(["---", f'okf_version: "{OKF_VERSION}"', "---", ""])

    for category in CANONICAL_CATEGORIES:
        items = grouped.get(category) or []
        if not items:
            continue
        lines.append(f"# {category}")
        lines.append("")
        for record in sorted(items, key=lambda r: r["id"]):
            title = display_title(record["fields"], record["body"])
            if okf_bundle_root:
                rel = f"{category}/{record['id']}.md"
            else:
                rel = relative_memory_path(record)
            lines.append(f"* [{title}]({rel}) — `{record['id']}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_store_log(records: list[dict[str, Any]]) -> str:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        created = str(record["fields"].get("createdAt") or record["fields"].get("timestamp") or "")
        date_key = created[:10] if len(created) >= 10 else "unknown"
        by_date.setdefault(date_key, []).append(record)

    lines = ["# Memory Update Log", ""]
    for date_key in sorted(by_date, reverse=True):
        lines.append(f"## {date_key}")
        items = sorted(by_date[date_key], key=lambda r: r["id"])
        for record in items:
            title = display_title(record["fields"], record["body"])
            rel = relative_memory_path(record)
            lines.append(f"* **Creation**: [{title}]({rel}) — `{record['id']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def maintain_derived(store: Path) -> dict[str, str]:
    records = load_store_records(store)
    index_path = store / "index.md"
    log_path = store / "log.md"
    index_path.write_text(render_store_index(records), encoding="utf-8")
    log_path.write_text(render_store_log(records), encoding="utf-8")
    return {"index": str(index_path), "log": str(log_path), "count": str(len(records))}


def cmd_search(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    results = []
    query = ns.query or ""
    for path in iter_memory_files(store):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(text)
        if is_excluded_record(fm) and not ns.include_excluded:
            continue
        if ns.file_glob:
            related = fm.get("relatedFiles")
            related_text = related if isinstance(related, str) else json.dumps(related or [])
            if ns.file_glob not in related_text:
                continue
        category = str(fm.get("category") or "")
        tags = fm.get("tags")
        tag_text = tags if isinstance(tags, str) else json.dumps(tags or [])
        if ns.category and ns.category not in category:
            continue
        if ns.tag and ns.tag not in tag_text:
            continue
        if query and query.lower() not in text.lower():
            continue
        mid = str(fm.get("id") or memory_id_from_path(path))
        truth = compiled_truth_of({"body": body, "fields": fm})
        summary = first_body_line(truth if truth else body)[:200]
        results.append({"id": mid, "summary": summary})
    print(json.dumps({"results": results}, indent=2))
    return 0


def cmd_export(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    records = load_store_records(store)
    fmt = ns.format
    if fmt == "jsonl":
        out_path = Path(ns.out)
        lines = [json.dumps(record_to_jsonl(record), sort_keys=True) for record in records]
        payload = "\n".join(lines) + ("\n" if lines else "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(json.dumps({"format": "jsonl", "count": len(records), "out": str(out_path)}))
        return 0

    if fmt == "okf":
        out_dir = Path(ns.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for record in records:
            category = record["category"]
            category_dir = out_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            fields = record_to_okf_fields(record)
            body = redact_text(record["body"])
            target = category_dir / f"{record['id']}.md"
            target.write_text(render_memory_file(fields, body), encoding="utf-8")
        (out_dir / "index.md").write_text(
            render_store_index(records, okf_bundle_root=True), encoding="utf-8"
        )
        (out_dir / "log.md").write_text(render_store_log(records), encoding="utf-8")
        print(json.dumps({"format": "okf", "count": len(records), "out": str(out_dir)}))
        return 0

    print(json.dumps({"error": f"unsupported export format: {fmt}"}), file=sys.stderr)
    return 1


def cmd_import(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    fmt = ns.format
    imported: list[dict[str, Any]] = []

    if fmt == "jsonl":
        source = Path(ns.source)
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(json.dumps({"error": f"jsonl line {line_no}: {exc}"}), file=sys.stderr)
                return 1
            if not isinstance(obj, dict):
                print(json.dumps({"error": f"jsonl line {line_no}: expected object"}), file=sys.stderr)
                return 1
            imported.append(jsonl_to_record(obj))

    elif fmt == "okf":
        source = Path(ns.source)
        for path in sorted(source.rglob("*.md")):
            if path.name in RESERVED_OKF_NAMES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_frontmatter(text)
            if not fm.get("type"):
                continue
            record = okf_fields_to_record(fm, body)
            # Legacy OKF bodies (no truth/timeline headings) upgrade with kind: imported.
            if record["category"] != "rule":
                sections = parse_body_sections(str(record.get("body") or ""))
                if sections.get("legacy") or not sections.get("timeline"):
                    record["body"] = ensure_truth_timeline_body(
                        str(record.get("body") or ""),
                        category=record["category"],
                        initial_kind="imported",
                        initial_summary="Imported from legacy interchange",
                    )
            imported.append(record)
    else:
        print(json.dumps({"error": f"unsupported import format: {fmt}"}), file=sys.stderr)
        return 1

    for record in imported:
        write_memory_record(store, record)
    derived = maintain_derived(store)
    print(json.dumps({"format": fmt, "imported": len(imported), **derived}))
    return 0


def cmd_maintain_derived(ns: argparse.Namespace) -> int:
    result = maintain_derived(Path(ns.store))
    print(json.dumps(result))
    return 0


def cmd_traverse(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    records = load_store_records(store)
    forward, backlinks = build_edge_map(records)
    record_by_id = {record["id"]: record for record in records}
    start_ids = [part.strip() for part in ns.from_id.split(",") if part.strip()]
    edge_filter = ns.edge or ""
    max_depth = int(ns.depth)
    direction = ns.direction

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(sid, 0) for sid in start_ids]
    nodes: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []

    while queue:
        current, depth = queue.pop(0)
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        record = record_by_id.get(current)
        nodes.append({
            "id": current,
            "found": record is not None,
            "excluded": is_excluded_record(record["fields"]) if record else False,
            "depth": depth,
        })
        if depth >= max_depth:
            continue
        if direction in {"out", "both"}:
            for edge in forward.get(current, []):
                if edge_filter and edge.get("edge") != edge_filter:
                    continue
                edges_out.append({"source": current, **edge})
                target = str(edge.get("target") or "")
                if target and target not in visited:
                    queue.append((target, depth + 1))
        if direction in {"in", "both"}:
            for edge in backlinks.get(current, []):
                if edge_filter and edge.get("edge") != edge_filter:
                    continue
                source = str(edge.get("source") or "")
                edges_out.append({"target": current, **edge, "dangling": source not in record_by_id})
                if source and source not in visited:
                    queue.append((source, depth + 1))

    dangling = sorted({e["target"] for e in edges_out if e.get("dangling")})
    print(json.dumps({
        "from": start_ids,
        "direction": direction,
        "edge": edge_filter or None,
        "depth": max_depth,
        "nodes": nodes,
        "edges": edges_out,
        "dangling": dangling,
    }, indent=2))
    return 0


def cmd_expand(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    records = load_store_records(store)
    record_by_id = {record["id"]: record for record in records}
    _, backlinks = build_edge_map(records)
    ids = [part.strip() for part in ns.ids.split(",") if part.strip()]
    expanded: list[dict[str, Any]] = []

    for mid in ids:
        record = record_by_id.get(mid)
        if not record:
            expanded.append({"id": mid, "found": False, "backlinks": backlinks.get(mid, [])})
            continue
        sections = parse_body_sections(record["body"])
        expanded.append({
            "id": mid,
            "found": True,
            "category": record["category"],
            "fields": record["fields"],
            "body": record["body"].strip(),
            "compiledTruth": sections.get("compiled_truth") or "",
            "timeline": sections.get("timeline") or [],
            "rest": sections.get("rest") or "",
            "backlinks": backlinks.get(mid, []),
            "excluded": is_excluded_record(record["fields"]),
        })
    print(json.dumps({"expanded": expanded}, indent=2))
    return 0


def _find_record(store: Path, memory_id: str) -> dict[str, Any] | None:
    for record in load_store_records(store):
        if record["id"] == memory_id:
            return record
    return None


def cmd_store(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    memory_id = ns.id.strip()
    category = (ns.category or "learning").strip()
    content = ns.content
    if content == "-":
        content = sys.stdin.read()
    body = ensure_truth_timeline_body(
        content,
        category=category,
        initial_kind="created",
        initial_summary=ns.summary or "Initial memory created",
    )
    fields: dict[str, Any] = {
        "category": category,
        "id": memory_id,
        "createdAt": utc_now_iso(),
        "scope": ns.scope or "project",
    }
    if ns.tags:
        fields["tags"] = [t.strip() for t in ns.tags.split(",") if t.strip()]
    record = {
        "id": memory_id,
        "category": category,
        "fields": fields,
        "body": body,
    }
    path = write_memory_record(store, record)
    maintain_derived(store)
    written = read_memory_record(path)
    print(json.dumps({
        "verdict": "ok",
        "action": "store",
        "id": memory_id,
        "path": str(path),
        "compiledTruth": compiled_truth_of(written),
        "timeline": timeline_of(written),
    }, indent=2))
    return 0


def cmd_update_truth(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    memory_id = ns.id.strip()
    record = _find_record(store, memory_id)
    if record is None:
        print(json.dumps({"verdict": "fail", "error": "not-found", "id": memory_id}), file=sys.stderr)
        return 20
    if record["category"] == "rule":
        print(json.dumps({
            "verdict": "fail",
            "error": "rules-do-not-use-timeline",
            "id": memory_id,
        }), file=sys.stderr)
        return 20

    new_truth = ns.truth
    if new_truth == "-":
        new_truth = sys.stdin.read()
    new_truth = redact_text(new_truth).strip()
    summary = (ns.summary or "Truth updated").strip()
    sections = parse_body_sections(record["body"])
    prior_timeline = list(sections.get("timeline") or [])
    # Append-only: refuse if caller tried to pass a shorter timeline via body rewrite.
    prior_timeline.append({
        "kind": "truth-updated",
        "at": utc_now_iso(),
        "summary": summary,
    })
    body = render_body_sections(new_truth, prior_timeline, str(sections.get("rest") or ""))
    updated = {**record, "body": body}
    path = write_memory_record(store, updated)
    written = read_memory_record(path)
    written_timeline = timeline_of(written)
    if len(written_timeline) < len(prior_timeline):
        print(json.dumps({
            "verdict": "fail",
            "error": "timeline-append-failed",
            "id": memory_id,
        }), file=sys.stderr)
        return 20
    maintain_derived(store)
    print(json.dumps({
        "verdict": "ok",
        "action": "update-truth",
        "id": memory_id,
        "path": str(path),
        "compiledTruth": compiled_truth_of(written),
        "timeline": written_timeline,
    }, indent=2))
    return 0


def cmd_modify(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    memory_id = ns.id.strip()
    record = _find_record(store, memory_id)
    if record is None:
        print(json.dumps({"verdict": "fail", "error": "not-found", "id": memory_id}), file=sys.stderr)
        return 20

    fields = dict(record["fields"])
    body = str(record["body"] or "")
    category = record["category"]
    summary = (ns.summary or "").strip()

    if ns.inactive is not None:
        inactive = ns.inactive.lower() in {"1", "true", "yes"}
        was_inactive = fields.get("inactive") is True
        fields["inactive"] = inactive
        kind = "inactivated" if inactive else "reactivated"
        if category != "rule":
            body = append_timeline_entry(
                body,
                kind=kind,
                summary=summary or ("Inactivated" if inactive else "Reactivated"),
                category=category,
            )
        elif was_inactive == inactive and not ns.content:
            pass

    if ns.content is not None:
        content = ns.content
        if content == "-":
            content = sys.stdin.read()
        content = redact_text(content)
        if category == "rule":
            body = content
        else:
            # Truth-bearing modify must leave timeline evidence (R10).
            sections = parse_body_sections(body)
            timeline = list(sections.get("timeline") or [])
            timeline.append({
                "kind": "modified",
                "at": utc_now_iso(),
                "summary": summary or "Body modified",
            })
            # Treat content as new compiled truth (not a freehand full-body overwrite).
            body = render_body_sections(content.strip(), timeline, str(sections.get("rest") or ""))

    updated = {**record, "fields": fields, "body": body}
    path = write_memory_record(store, updated)
    written = read_memory_record(path)
    maintain_derived(store)
    print(json.dumps({
        "verdict": "ok",
        "action": "modify",
        "id": memory_id,
        "path": str(path),
        "compiledTruth": compiled_truth_of(written),
        "timeline": timeline_of(written),
        "inactive": written["fields"].get("inactive") is True,
    }, indent=2))
    return 0


def cmd_reconcile_supersede(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    log_path = Path(ns.log)
    if not log_path.is_file():
        print(json.dumps({"reconciled": 0, "actions": [], "entries": 0}))
        return 0
    entries: list[tuple[str, str, str]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            entries.append((parts[0], parts[1], parts[2]))
    result = reconcile_supersede_entries(store, entries)
    result["entries"] = len(entries)
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="In-repo memory search and interchange")
    sub = parser.add_subparsers(dest="command")

    search = sub.add_parser("search", help="keyword + frontmatter search")
    search.add_argument("--store", required=True)
    search.add_argument("--query", default="")
    search.add_argument("--category", default="")
    search.add_argument("--tag", default="")
    search.add_argument("--file-glob", default="")
    search.add_argument("--include-excluded", action="store_true")

    traverse = sub.add_parser("traverse", help="walk link graph from seed ids")
    traverse.add_argument("--store", required=True)
    traverse.add_argument("--from", dest="from_id", required=True)
    traverse.add_argument("--edge", default="")
    traverse.add_argument("--depth", default="8")
    traverse.add_argument("--direction", choices=("out", "in", "both"), default="both")

    expand = sub.add_parser("expand", help="expand ids with full body and backlinks")
    expand.add_argument("--store", required=True)
    expand.add_argument("--ids", required=True)

    reconcile = sub.add_parser("reconcile-supersede", help="reconcile SUPERSEDED.log against store")
    reconcile.add_argument("--store", required=True)
    reconcile.add_argument("--log", required=True)

    export = sub.add_parser("export", help="export store to jsonl or okf bundle")
    export.add_argument("--store", required=True)
    export.add_argument("--format", choices=("jsonl", "okf"), required=True)
    export.add_argument("--out", required=True)

    imp = sub.add_parser("import", help="import jsonl or okf bundle into store")
    imp.add_argument("--store", required=True)
    imp.add_argument("--format", choices=("jsonl", "okf"), required=True)
    imp.add_argument("--source", required=True)

    maintain = sub.add_parser("maintain-derived", help="regenerate index.md and log.md")
    maintain.add_argument("--store", required=True)

    store_cmd = sub.add_parser("store", help="create a memory with compiled truth + timeline")
    store_cmd.add_argument("--store", required=True)
    store_cmd.add_argument("--id", required=True)
    store_cmd.add_argument("--category", default="learning")
    store_cmd.add_argument("--content", required=True, help="distilled body, or '-' for stdin")
    store_cmd.add_argument("--summary", default="")
    store_cmd.add_argument("--tags", default="")
    store_cmd.add_argument("--scope", default="project")

    update_truth = sub.add_parser(
        "update-truth",
        help="atomically rewrite compiled truth and append one timeline entry",
    )
    update_truth.add_argument("--store", required=True)
    update_truth.add_argument("--id", required=True)
    update_truth.add_argument("--truth", required=True, help="new compiled truth, or '-' for stdin")
    update_truth.add_argument("--summary", default="Truth updated")

    modify = sub.add_parser("modify", help="modify a memory, leaving timeline evidence")
    modify.add_argument("--store", required=True)
    modify.add_argument("--id", required=True)
    modify.add_argument("--content", default=None, help="new compiled truth, or '-' for stdin")
    modify.add_argument("--summary", default="")
    modify.add_argument(
        "--inactive",
        default=None,
        help="true/false to inactivate or reactivate (appends timeline evidence)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    known = {
        "search", "export", "import", "maintain-derived",
        "traverse", "expand", "reconcile-supersede",
        "store", "update-truth", "modify",
        "-h", "--help",
    }
    if raw_argv and raw_argv[0] not in known:
        if "--store" in raw_argv:
            legacy = parser.parse_args(["search", *raw_argv])
            return cmd_search(legacy)

    ns = parser.parse_args(raw_argv)
    if ns.command == "search":
        return cmd_search(ns)
    if ns.command == "export":
        return cmd_export(ns)
    if ns.command == "import":
        return cmd_import(ns)
    if ns.command == "traverse":
        return cmd_traverse(ns)
    if ns.command == "expand":
        return cmd_expand(ns)
    if ns.command == "reconcile-supersede":
        return cmd_reconcile_supersede(ns)
    if ns.command == "maintain-derived":
        return cmd_maintain_derived(ns)
    if ns.command == "store":
        return cmd_store(ns)
    if ns.command == "update-truth":
        return cmd_update_truth(ns)
    if ns.command == "modify":
        return cmd_modify(ns)
    parser.print_help()
    return 2


if __name__ == "__main__":
    run_module_main(main)
