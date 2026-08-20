#!/usr/bin/env python3
"""Executable Recallium rule-fetcher for hooks. Emits JSON to stdout; never prints credentials."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any


def _ensure_scripts_importable() -> None:
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if entry.strip() and (Path(entry) / "memory_lib.py").is_file():
            return
    here = Path(__file__).resolve()
    for parent in here.parents:
        scripts = parent / "scripts"
        if (scripts / "memory_lib.py").is_file():
            entry = str(scripts)
            if entry not in sys.path:
                sys.path.insert(0, entry)
            return


def load_config(root: Path) -> tuple[str, str, str]:
    provider, project, base = "recallium", "", "http://localhost:8001"
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            break
        memory = data.get("memory") or {}
        provider = str(memory.get("provider") or provider)
        project = str(memory.get("project") or "")
        base = str(memory.get("connection", {}).get("restBaseUrl") or base)
    if not project:
        project = root.name
    return provider, project, base


def _fetch_rules(url: str, policy: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    from sw_recallium_url import guarded_urlopen

    with guarded_urlopen(url, policy, headers=headers, timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    _ensure_scripts_importable()
    from memory_broker import MemoryBrokerError, prepare_bound_headers
    from memory_lib import resolve_memory_credential
    from sw_recallium_url import RestFetchPolicyError, load_catalog_rest_policy, validate_rest_url

    root = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd())
    provider, project, base = load_config(root)
    if provider != "recallium":
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "unsupported provider for executable fetch",
                    "provider": provider,
                    "rules": [],
                }
            )
        )
        return 1

    try:
        policy = load_catalog_rest_policy(root, "recallium")
        validate_rest_url(base, policy)
    except RestFetchPolicyError:
        print(json.dumps({"ok": False, "error": "restBaseUrl must be localhost-only", "rules": []}))
        return 1

    credential = resolve_memory_credential(
        root,
        memory_provider="recallium",
        destination_endpoint=base,
    )
    quoted = urllib.parse.quote(project, safe="")
    url = f"{base.rstrip('/')}/api/projects/{quoted}/memories?memory_type=rule&limit=25"
    try:
        headers = prepare_bound_headers(url=url, policy=policy, credential=credential)
    except MemoryBrokerError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": exc.code,
                    "rules": [],
                }
            )
        )
        return 1

    try:
        body = _fetch_rules(url, policy, headers)
    except Exception:
        print(json.dumps({"ok": False, "error": "provider unreachable", "rules": []}))
        return 1

    rows = body.get("data") if isinstance(body, dict) else []
    rules = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        rid = row.get("id") or row.get("memory_id") or row.get("summary")
        summary = row.get("summary") or row.get("content") or ""
        rules.append({"id": rid, "summary": summary})
    if os.environ.get("SW_RULE_EFFECTIVENESS_DISABLED") != "1":
        try:
            from rule_effectiveness import emit_provider_fetch_events

            emit_provider_fetch_events(root, provider="recallium", rules=rules, ok=True)
        except Exception:
            pass
    print(json.dumps({"ok": True, "rules": rules}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
