#!/usr/bin/env python3
"""Executable in-repo rule-fetcher for hooks. Emits JSON to stdout."""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

MAX_RULE_CHARS = 2000


def load_config(root: Path) -> tuple[str, str]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return "in-repo", ".cursor/sw-memory"
            memory = data.get("memory") or {}
            provider = str(memory.get("provider") or "in-repo")
            store = str(memory.get("inRepo", {}).get("storeDir") or ".cursor/sw-memory")
            return provider, store
    return "in-repo", ".cursor/sw-memory"


def parse_frontmatter_category(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    for line in block.splitlines():
        if line.startswith("category:"):
            return line.split(":", 1)[1].strip()
    return None


def body_after_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2].lstrip("\n") if len(parts) >= 3 else ""


def main() -> int:
    root = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd())
    provider, store_dir = load_config(root)
    if provider != "in-repo":
        print(json.dumps({"ok": False, "error": "unsupported provider for in-repo rules adapter", "provider": provider, "rules": []}))
        return 1
    rules_dir = (root / store_dir / "rules").resolve()
    try:
        rules_dir.relative_to(root.resolve())
    except ValueError:
        print(json.dumps({"ok": False, "error": "storeDir escapes workspace", "rules": []}))
        return 1
    if not rules_dir.is_dir():
        print(json.dumps({"ok": True, "rules": []}))
        return 0
    rules = []
    for path in sorted(rules_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if parse_frontmatter_category(text) != "rule":
            continue
        body = body_after_frontmatter(text)
        if len(body) > MAX_RULE_CHARS:
            continue
        summary = re.sub(r"[\000-\010\013\014\016-\037]", "", body)
        if not summary.strip():
            continue
        rules.append({"id": path.stem, "summary": summary})
    print(json.dumps({"ok": True, "rules": rules}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
