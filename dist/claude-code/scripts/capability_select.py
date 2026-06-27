#!/usr/bin/env python3
"""Deterministic capability selector primitive (PRD 021 TR3, R10, R14)."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from capability_index import check_freshness
from capability_precedence import effective_tier, total_order_key
from wave_json_io import read_json, write_json

SIGNAL_CONTEXT_VERSION = 1
OUTPUT_VERSION = 1
SNAPSHOT_FILENAME = "signal-context.json"

POLYSEMOUS_TOKENS = frozenset({"component", "view", "page", "form", "screen"})
UNCONFIGURED_VALUES = frozenset({"", "none", "off", "unconfigured", "null"})

FAIL_CLOSED_DEFAULTS: dict[str, Any] = {
    "version": SIGNAL_CONTEXT_VERSION,
    "tier": None,
    "doc_path": None,
    "body_snapshot": "",
    "derived_tags": [],
    "file_paths": [],
    "change_digest": None,
    "config": {},
    "phase_type": None,
    "conductor_mode": None,
    "overrides": {},
}


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def normalize_signal_context(raw: dict[str, Any] | None) -> dict[str, Any]:
    ctx: dict[str, Any] = dict(FAIL_CLOSED_DEFAULTS)
    if not isinstance(raw, dict):
        return ctx
    version = raw.get("version", SIGNAL_CONTEXT_VERSION)
    ctx["version"] = int(version) if version is not None else SIGNAL_CONTEXT_VERSION
    for key in FAIL_CLOSED_DEFAULTS:
        if key == "version":
            continue
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key in {"derived_tags", "file_paths"} and isinstance(value, list):
            ctx[key] = [str(v) for v in value if v]
        elif key == "config" and isinstance(value, dict):
            ctx[key] = value
        elif key == "overrides" and isinstance(value, dict):
            ctx[key] = value
        elif key == "change_digest" and isinstance(value, dict):
            ctx[key] = value
        elif key == "body_snapshot":
            ctx[key] = str(value)
        else:
            ctx[key] = value
    if not isinstance(ctx["derived_tags"], list):
        ctx["derived_tags"] = []
    if not isinstance(ctx["file_paths"], list):
        ctx["file_paths"] = []
    if not isinstance(ctx["config"], dict):
        ctx["config"] = {}
    if not isinstance(ctx["overrides"], dict):
        ctx["overrides"] = {}
    return ctx


def snapshot_path(run_dir: Path) -> Path:
    return run_dir / SNAPSHOT_FILENAME


def load_or_snapshot_context(
    run_dir: Path | None,
    *,
    resume: bool,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    if run_dir is None:
        return normalize_signal_context(incoming)
    path = snapshot_path(run_dir)
    if resume and path.is_file():
        stored = read_json(path)
        return normalize_signal_context(stored)
    normalized = normalize_signal_context(incoming)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(path, normalized)
    return normalized


def resolve_config_value(config: dict[str, Any], dotted_key: str) -> Any:
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_configured(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized not in UNCONFIGURED_VALUES


def whole_token_pattern(token: str, *, case_insensitive: bool) -> re.Pattern[str]:
    escaped = re.escape(token)
    flags = re.IGNORECASE if case_insensitive else 0
    if " " in token:
        return re.compile(rf"(?<!\w){escaped}(?!\w)", flags)
    return re.compile(rf"\b{escaped}\b", flags)


def text_has_token(
    text: str,
    token: str,
    *,
    match_mode: str,
    case_insensitive: bool,
    exclude_polysemous: bool,
) -> bool:
    if exclude_polysemous and token.lower() in POLYSEMOUS_TOKENS:
        return False
    if match_mode == "substring":
        hay = text.lower() if case_insensitive else text
        needle = token.lower() if case_insensitive else token
        return needle in hay
    return bool(whole_token_pattern(token, case_insensitive=case_insensitive).search(text))


def match_text_token(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    source = trigger.get("source", "body_snapshot")
    tokens = trigger.get("tokens") or []
    if not tokens:
        return False
    match_mode = trigger.get("match", "whole_token")
    case_insensitive = bool(trigger.get("case_insensitive", True))
    exclude_polysemous = bool(trigger.get("exclude_polysemous", False))
    if source == "derived_tags":
        hay = " ".join(ctx.get("derived_tags") or [])
    elif source == "change_digest":
        digest = ctx.get("change_digest") or {}
        hay = json.dumps(digest, sort_keys=True)
    else:
        hay = str(ctx.get("body_snapshot") or "")
    return any(
        text_has_token(
            hay,
            str(token),
            match_mode=match_mode,
            case_insensitive=case_insensitive,
            exclude_polysemous=exclude_polysemous,
        )
        for token in tokens
    )


def match_heading(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    headings = trigger.get("headings") or []
    if not headings:
        return False
    body = str(ctx.get("body_snapshot") or "")
    case_insensitive = bool(trigger.get("case_insensitive", True))
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading_text = re.sub(r"^#+\s*", "", stripped).strip()
        compare = heading_text.lower() if case_insensitive else heading_text
        for target in headings:
            needle = target.lower() if case_insensitive else target
            if compare == needle or needle in compare:
                return True
    return False


def match_link_pattern(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    patterns = trigger.get("patterns") or []
    if not patterns:
        return False
    body = str(ctx.get("body_snapshot") or "").lower()
    return any(str(pattern).lower() in body for pattern in patterns)


def path_candidates(ctx: dict[str, Any], source: str) -> list[str]:
    if source == "doc_path":
        doc = ctx.get("doc_path")
        return [str(doc)] if doc else []
    if source == "change_digest":
        digest = ctx.get("change_digest") or {}
        return [str(f.get("path", "")) for f in digest.get("files") or [] if f.get("path")]
    paths = list(ctx.get("file_paths") or [])
    doc = ctx.get("doc_path")
    if doc:
        paths.append(str(doc))
    return paths


def match_path_glob(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    globs = trigger.get("globs") or trigger.get("patterns") or []
    if not globs:
        return False
    source = trigger.get("source", "file_paths")
    candidates = path_candidates(ctx, source)
    for path in candidates:
        normalized = path.replace("\\", "/")
        for pattern in globs:
            pat = str(pattern)
            if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(os.path.basename(normalized), pat):
                return True
    return False


def digest_added_lines(ctx: dict[str, Any]) -> list[tuple[str, str]]:
    digest = ctx.get("change_digest") or {}
    rows: list[tuple[str, str]] = []
    for entry in digest.get("files") or []:
        path = str(entry.get("path", ""))
        for line in entry.get("added_lines") or []:
            rows.append((path, str(line)))
    return rows


def match_change_digest(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    predicate = trigger.get("predicate")
    rows = digest_added_lines(ctx)
    if predicate == "executable_lines_gte":
        threshold = int(trigger.get("threshold", 0))
        executable = sum(1 for _, line in rows if _is_executable_line(line))
        return executable >= threshold
    if predicate == "path_match":
        globs = trigger.get("globs") or []
        paths = {path for path, _ in rows}
        return any(
            fnmatch.fnmatch(path.replace("\\", "/"), pat) or fnmatch.fnmatch(os.path.basename(path), pat)
            for path in paths
            for pat in globs
        )
    if predicate == "keyword_in_added_lines":
        keywords = [str(k).lower() for k in trigger.get("keywords") or []]
        return any(any(k in line.lower() for k in keywords) for _, line in rows)
    if predicate == "added_lines_match":
        keywords = [str(k).lower() for k in trigger.get("keywords") or []]
        return any(any(k in line.lower() for k in keywords) for _, line in rows)
    return False


def _is_executable_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in {"{", "}", "(", ")", "[", "]"}:
        return False
    if re.match(r"^[{}\[\]()]+$", stripped):
        return False
    if re.match(r"^(import\s|from\s+\S+\s+import|#include|using\s|require\(|use\s)", stripped):
        return False
    if re.match(r"^(//|#(?!!)|/\*|\*|--|<!--)", stripped):
        return False
    return True


def match_config_flag(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    key = str(trigger.get("key", ""))
    if not key:
        return False
    value = resolve_config_value(ctx.get("config") or {}, key)
    if trigger.get("absent"):
        return value is None
    if "configured" in trigger:
        want = bool(trigger.get("configured"))
        return is_configured(value) == want
    if "equals" in trigger:
        if value is None:
            return False
        return str(value).strip().lower() == str(trigger["equals"]).strip().lower()
    if "notEquals" in trigger:
        if value is None:
            return True
        return str(value).strip().lower() != str(trigger["notEquals"]).strip().lower()
    return False


def match_triage_tag(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    tags = {str(t).lower() for t in trigger.get("tags") or []}
    if not tags:
        return False
    derived = {str(t).lower() for t in ctx.get("derived_tags") or []}
    if not derived:
        return False
    mode = trigger.get("match", "any")
    if mode == "all":
        return tags.issubset(derived)
    return bool(tags & derived)


def match_trigger(trigger: dict[str, Any], ctx: dict[str, Any]) -> bool:
    trigger_type = trigger.get("type")
    if trigger_type == "always_on":
        return True
    if trigger_type == "phase_default":
        command = trigger.get("command")
        phase = ctx.get("phase_type")
        return bool(command and phase and str(phase) == str(command))
    if trigger_type == "text_token":
        return match_text_token(trigger, ctx)
    if trigger_type == "heading":
        return match_heading(trigger, ctx)
    if trigger_type == "link_pattern":
        return match_link_pattern(trigger, ctx)
    if trigger_type == "path_glob":
        return match_path_glob(trigger, ctx)
    if trigger_type == "change_digest":
        return match_change_digest(trigger, ctx)
    if trigger_type == "config_flag":
        return match_config_flag(trigger, ctx)
    if trigger_type == "triage_tag":
        return match_triage_tag(trigger, ctx)
    if trigger_type == "any_of":
        children = trigger.get("triggers") or []
        return any(match_trigger(child, ctx) for child in children if isinstance(child, dict))
    if trigger_type == "all_of":
        children = trigger.get("triggers") or []
        return all(match_trigger(child, ctx) for child in children if isinstance(child, dict))
    return False


def capability_matches(entry: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, list[str]]:
    capability = entry.get("capability") or {}
    triggers = capability.get("triggers") or []
    matched: list[str] = []
    for trigger in triggers:
        if isinstance(trigger, dict) and match_trigger(trigger, ctx):
            matched.append(str(trigger.get("type", "unknown")))
    return bool(matched), matched


def apply_overrides(
    selected: list[dict[str, Any]],
    index_entries: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    overrides = ctx.get("overrides") or {}
    if overrides.get("all"):
        doc_review = [
            entry
            for entry in index_entries
            if (entry.get("capability") or {}).get("metadata", {}).get("selectionFamily") == "doc-review"
            or any(
                isinstance(t, dict) and t.get("selectionFamily") == "doc-review"
                for t in (entry.get("capability") or {}).get("triggers") or []
            )
        ]
        by_id = {row["id"]: row for row in selected}
        for entry in doc_review:
            matched, triggers = capability_matches(entry, ctx)
            if not matched and entry.get("kind") == "persona":
                matched, triggers = True, ["override:all"]
            if matched:
                by_id[entry["id"]] = {
                    "entry": entry,
                    "matched_triggers": triggers,
                    "override_tier": "override",
                }
        return sorted(by_id.values(), key=lambda row: row["entry"]["id"])
    persona_ids = overrides.get("personas")
    if isinstance(persona_ids, list) and persona_ids:
        wanted = {str(p).lower() for p in persona_ids}
        by_id = {row["entry"]["id"]: row for row in selected}
        for entry in index_entries:
            if entry.get("kind") != "persona":
                continue
            metadata = (entry.get("capability") or {}).get("metadata") or {}
            persona_id = str(metadata.get("personaId", "")).lower()
            agent_suffix = entry["id"].split(".", 1)[-1].replace("sw-", "").replace("-reviewer", "")
            if persona_id in wanted or agent_suffix in wanted or entry["id"] in wanted:
                by_id[entry["id"]] = {
                    "entry": entry,
                    "matched_triggers": ["override:personas"],
                    "override_tier": "override",
                }
        return sorted(by_id.values(), key=lambda row: row["entry"]["id"])
    return selected


def trust_fields(entry: dict[str, Any], ctx: dict[str, Any], *, eligible: bool) -> dict[str, Any]:
    executable = bool(entry.get("executable"))
    metadata = (entry.get("capability") or {}).get("metadata") or {}
    gate_ref = metadata.get("gateRef")
    if not eligible:
        return {
            "eligible": False,
            "executable": executable,
            "authorized": False,
            "gateRef": gate_ref,
            "refusalReason": "not_eligible",
        }
    if not executable:
        return {
            "eligible": True,
            "executable": False,
            "authorized": True,
            "gateRef": None,
            "refusalReason": None,
        }
    provider_keys = {
        "review.provider": metadata.get("providerFamily") == "review",
        "review.local.provider": metadata.get("providerFamily") == "review.local",
        "memory.provider": metadata.get("providerFamily") == "memory",
        "verify.provider": metadata.get("providerFamily") == "verify",
    }
    configured = True
    for key, relevant in provider_keys.items():
        if not relevant:
            continue
        value = resolve_config_value(ctx.get("config") or {}, key)
        if not is_configured(value):
            configured = False
            break
    if gate_ref and configured:
        return {
            "eligible": True,
            "executable": True,
            "authorized": True,
            "gateRef": gate_ref,
            "refusalReason": None,
        }
    reason = "unconfigured_provider" if not configured else "unknown_gate"
    return {
        "eligible": True,
        "executable": True,
        "authorized": False,
        "gateRef": gate_ref,
        "refusalReason": reason,
    }


def membership_hash(capability_ids: list[str]) -> str:
    payload = json.dumps(sorted(capability_ids), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_output_row(
    entry: dict[str, Any],
    ctx: dict[str, Any],
    *,
    matched_triggers: list[str],
    override_tier: str | None,
) -> dict[str, Any]:
    capability = entry.get("capability") or {}
    tier = override_tier or effective_tier(capability, None)
    trust = trust_fields(entry, ctx, eligible=True)
    return {
        "id": entry["id"],
        "kind": entry.get("kind"),
        "sourcePath": entry.get("sourcePath"),
        "eligible": trust["eligible"],
        "executable": trust["executable"],
        "authorized": trust["authorized"],
        "gateRef": trust["gateRef"],
        "refusalReason": trust["refusalReason"],
        "precedenceTier": tier,
        "matchedTriggers": sorted(set(matched_triggers)),
    }


def select_capabilities(index: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    entries = index.get("capabilities") or []
    selected: list[dict[str, Any]] = []
    for entry in entries:
        matched, triggers = capability_matches(entry, ctx)
        if matched:
            selected.append({"entry": entry, "matched_triggers": triggers, "override_tier": None})
    selected = apply_overrides(selected, entries, ctx)
    selected.sort(
        key=lambda row: total_order_key(
            row["entry"]["id"],
            row["entry"].get("capability") or {},
            trigger=None,
        )
    )
    rows = [
        build_output_row(
            row["entry"],
            ctx,
            matched_triggers=row["matched_triggers"],
            override_tier=row.get("override_tier"),
        )
        for row in selected
    ]
    ids = [row["id"] for row in rows]
    return {
        "version": OUTPUT_VERSION,
        "membershipHash": membership_hash(ids),
        "signalContext": ctx,
        "capabilities": rows,
        "precedenceTrace": [
            {
                "id": row["id"],
                "precedenceTier": row["precedenceTier"],
                "matchedTriggers": row["matchedTriggers"],
            }
            for row in rows
        ],
    }


def canonical_bytes(result: dict[str, Any]) -> bytes:
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_index(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Deterministic capability selector")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--context", type=Path, default=None)
    parser.add_argument("--context-json", default=None)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-freshness", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    core_root = root / "core"
    index_path = args.index or (core_root / "sw-reference" / "capability-index.json")
    if not index_path.is_file():
        fail(f"missing capability index: {index_path}", cause="capability-index:missing")

    if not args.skip_freshness:
        ok, message = check_freshness(core_root, index_path)
        if not ok:
            fail(message, exit_code=20, cause="capability-index:stale")

    if args.context_json:
        raw_context = json.loads(args.context_json)
    elif args.context and args.context.is_file():
        raw_context = json.loads(args.context.read_text(encoding="utf-8"))
    else:
        raw_context = {}

    run_dir = args.run_dir
    if run_dir is None and os.environ.get("SW_RUN_DIR"):
        run_dir = Path(os.environ["SW_RUN_DIR"])

    ctx = load_or_snapshot_context(run_dir, resume=args.resume, incoming=raw_context)
    index = load_index(index_path)
    result = select_capabilities(index, ctx)
    payload = canonical_bytes(result) + b"\n"
    sys.stdout.buffer.write(payload)


if __name__ == "__main__":
    main()
