#!/usr/bin/env python3
"""Executable Recallium rule-fetcher for hooks. Emits JSON to stdout; never prints credentials."""
from __future__ import annotations
import json, os, sys, urllib.parse, urllib.request
from pathlib import Path

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


def main() -> int:
    root = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd())
    hooks_dir = Path(__file__).resolve().parents[1] / "hooks"
    sys.path.insert(0, str(hooks_dir))
    from sw_recallium_url import is_allowed_recallium_base

    provider, project, base = load_config(root)
    if provider != "recallium":
        print(json.dumps({"ok": False, "error": "unsupported provider for executable fetch", "provider": provider, "rules": []}))
        return 1
    if not is_allowed_recallium_base(base):
        print(json.dumps({"ok": False, "error": "restBaseUrl must be localhost-only", "rules": []}))
        return 1
    quoted = urllib.parse.quote(project, safe="")
    url = f"{base.rstrip('/')}/api/projects/{quoted}/memories?memory_type=rule&limit=25"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8"))
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
    print(json.dumps({"ok": True, "rules": rules}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
