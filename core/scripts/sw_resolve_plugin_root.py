from pathlib import Path

def resolve_plugin_root(script_dir: Path) -> Path:
    parent = script_dir.parent.resolve()
    if (parent/"providers").is_dir() or (parent/"commands").is_dir():
        return parent
    if (parent/"core"/"providers").is_dir():
        return parent/"core"
    return parent
