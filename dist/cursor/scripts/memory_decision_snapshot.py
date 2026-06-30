#!/usr/bin/env python3
"""Write/refresh a redacted committed decision snapshot with SoT frontmatter (PRD 015 R4–R6)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent


def plugin_scripts(root: Path) -> Path:
    """Harness scripts live at plugin root; fall back when repo root lacks scripts/."""
    candidate = root / "scripts"
    if (candidate / "memory-sot.py").is_file():
        return candidate
    return PLUGIN_ROOT / "scripts"


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def git_root(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def resolve_sot(root: Path) -> dict:
    scripts = plugin_scripts(root)
    proc = subprocess.run(
        ["bash", str(scripts / "memory-sot.py"), "resolve", "--class", "decision", "--json"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("memory-sot resolve failed", stderr=proc.stderr.strip())
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("memory-sot returned invalid JSON")
    if data.get("verdict") != "pass":
        fail("memory-sot resolve did not pass", detail=data)
    return data


def redact_text(root: Path, text: str) -> str:
    scripts = plugin_scripts(root)
    proc = subprocess.run(
        ["bash", str(scripts / "memory-redact.py")],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("memory-redact failed", stderr=proc.stderr.strip())
    return proc.stdout


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    block = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip()
    return meta, body


def render_frontmatter(meta: dict[str, str]) -> str:
    lines = ["---"]
    for key, val in meta.items():
        lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def stamp_snapshot(meta: dict[str, str], effective: str, memory_pointer: str | None) -> dict[str, str]:
    out = dict(meta)
    out["authoritative"] = effective
    if effective == "memory":
        out["snapshotRole"] = "pointer"
        if memory_pointer:
            out["memoryPointer"] = memory_pointer
    else:
        out["snapshotRole"] = "authoritative"
        out.pop("memoryPointer", None)
    return out


def append_audit_breadcrumb(root: Path, path: Path, effective: str, provider_ok: bool, note: str) -> None:
    log_path = root / "docs/decisions/.memory-freeze-audit.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{date.today().isoformat()}\t{path.as_posix()}\tauthoritative={effective}\t"
        f"providerWrite={'ok' if provider_ok else 'skipped'}\t{note}\n"
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def cmd_write(root: Path, rel_path: str, memory_pointer: str | None, dry_run: bool) -> None:
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        fail("path escapes repository root")
    if not target.is_file():
        fail(f"decision record not found: {rel_path}")
    if not rel_path.startswith("docs/decisions/") or rel_path.endswith("INDEX.md"):
        fail("path must be a decision record under docs/decisions/")

    sot = resolve_sot(root)
    effective = str(sot.get("effective", "repo"))
    if effective not in ("repo", "memory"):
        fail(f"unexpected effective SoT for decision: {effective!r}")

    raw = target.read_text(encoding="utf-8")
    meta, body = split_frontmatter(raw)
    unit_visibility = str(meta.get("visibility", "")).strip().lower()
    # PRD 034 R12: decision snapshots are always committed regardless of unit visibility.
    always_committed = True
    redacted_body = redact_text(root, body)
    stamped = stamp_snapshot(meta, effective, memory_pointer)
    output = render_frontmatter(stamped) + redacted_body.lstrip("\n")

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "snapshot-write",
                "dryRun": True,
                "path": rel_path,
                "authoritative": effective,
                "snapshotRole": stamped.get("snapshotRole"),
                "alwaysCommitted": always_committed,
                "unitVisibility": unit_visibility or None,
            }
        )

    target.write_text(output, encoding="utf-8")
    append_audit_breadcrumb(
        root,
        Path(rel_path),
        effective,
        provider_ok=False,
        note="provider write best-effort deferred to memory-preflight (offline-safe freeze)",
    )
    emit(
        {
            "verdict": "pass",
            "action": "snapshot-write",
            "path": rel_path,
            "authoritative": effective,
            "snapshotRole": stamped.get("snapshotRole"),
            "providerWrite": "deferred-best-effort",
            "alwaysCommitted": always_committed,
            "unitVisibility": unit_visibility or None,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision snapshot writer for freeze path")
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write", help="Redact and stamp a decision record snapshot")
    write.add_argument("--path", required=True, help="Repo-relative path to docs/decisions/<n>-<slug>.md")
    write.add_argument("--memory-pointer", default=None, help="Provider record id when memory-SoT")
    write.add_argument("--dry-run", action="store_true")
    write.add_argument("--root", type=Path, default=None)

    args = parser.parse_args()
    start = args.root or Path.cwd()
    root = git_root(start)

    if args.command == "write":
        cmd_write(root, args.path, args.memory_pointer, args.dry_run)


if __name__ == "__main__":
    main()
