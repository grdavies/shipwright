
"""Shared safe evidence file/dir reads (plan 005 U4)."""
from __future__ import annotations
import json, os, stat
from pathlib import Path

def stat_uid(target: Path) -> int:
    return target.lstat().st_uid

def stat_perms(target: Path) -> int:
    return stat.S_IMODE(target.lstat().st_mode)

def caller_uid() -> int:
    return os.getuid()

def validate_run_dir(dir_path: Path) -> bool:
    if not dir_path.is_dir() or dir_path.is_symlink(): return False
    if stat_uid(dir_path) != caller_uid(): return False
    return stat_perms(dir_path) == 0o700

def safe_read_check(path: Path) -> bool:
    if not path.exists() or path.is_symlink(): return False
    if stat_uid(path) != caller_uid(): return False
    perms = stat_perms(path)
    if (perms // 10) % 10 & 2: return False
    if perms % 10 & 2: return False
    return True

def safe_json_load(path: Path):
    if not safe_read_check(path): raise PermissionError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))
