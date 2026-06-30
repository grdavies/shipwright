#!/usr/bin/env python3
"""One-shot Phase 5 bulk port helper — exec wrappers and heredoc extraction (PRD 042)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
LEDGER = ROOT / "core/sw-reference/script-port-ledger.json"

ENTRYPOINT_HEADER = '''#!/usr/bin/env python3
"""{doc}"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def git_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return SCRIPT_DIR.parent


def repo_root() -> Path:
    return git_root()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
{body}
    return 0


if __name__ == "__main__":
    run_module_main(main)
'''


def sh_doc(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("#") and not line.startswith("#!"):
            lines.append(line.lstrip("# ").strip())
        elif line.strip() and not line.startswith("#"):
            break
    return " ".join(lines[:2]) or "Shipwright script entrypoint."


def extract_heredoc_py(text: str) -> str | None:
    m = re.search(r"python3[^<]*<<'PY'\n(.*)\nPY", text, re.DOTALL)
    return m.group(1) if m else None


def resolve_exec_target(text: str) -> tuple[str, list[str]] | None:
    """Return (module_path_relative_to_scripts, prefix_args)."""
    m = re.search(r'exec python3\s+(?:\$[A-Z_]+\s+)?["\']?([^"\'\s]+)', text)
    if not m:
        return None
    raw = m.group(1)
    raw = raw.replace("${ROOT}/scripts/", "").replace("$ROOT/scripts/", "")
    raw = raw.replace("${PLUGIN_ROOT}/scripts/", "").replace("$PLUGIN_ROOT/scripts/", "")
    raw = raw.replace("$SCRIPT_DIR/", "").replace("${SCRIPT_DIR}/", "")
    raw = raw.replace("${ROOT}/", "").replace("$ROOT/", "")
    prefix: list[str] = []
    if '"$REPO_ROOT"' in text or '"$REPO_ROOT" "$@"' in text:
        prefix = ["$REPO_ROOT"]
    elif '"$ROOT"' in text and '"$ROOT" "$@"' in text:
        prefix = ["$ROOT"]
    elif '"$PWD"' in text:
        prefix = ["$PWD"]
    elif '"$GIT_ROOT"' in text:
        prefix = ["$GIT_ROOT"]
    return raw, prefix


def module_import_name(path: str) -> str:
    name = Path(path).stem.replace("-", "_")
    return name


def gen_exec_wrapper(sh_path: Path, target_py: str, prefix: list[str], doc: str) -> str:
    mod = module_import_name(target_py)
    body_lines = [f"    root = repo_root()"]
    if prefix == ["$REPO_ROOT"]:
        body_lines = ["    root = repo_root()"]
    elif prefix == ["$ROOT"]:
        body_lines = ["    root = SCRIPT_DIR.parent"]
    elif prefix == ["$PWD"]:
        body_lines = ["    root = Path.cwd()"]
    elif prefix == ["$GIT_ROOT"]:
        body_lines = ["    root = git_root()"]

    # special secret-scan inflight-tuple
    if sh_path.name == "secret-scan.py":
        body_lines = [
            "    root = git_root()",
            "    if args and args[0] == 'inflight-tuple':",
            "        import inflight_signal",
            "        inflight_signal.main([str(root), 'validate', *args[1:]])",
            "        return 0",
            "    import secret_scan",
            "    secret_scan.main(args)",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "cleanup.py":
        body_lines = [
            "    root = git_root()",
            "    import cleanup_lib",
            "    cleanup_lib.main([str(root), *args])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "planning_paths.py":
        body_lines = [
            "    root = SCRIPT_DIR.parent",
            "    import planning_paths",
            "    planning_paths.main([str(root), *args])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "visibility-callsite-lint.py":
        body_lines = [
            "    root = SCRIPT_DIR.parent",
            "    map_path = args[0] if args else 'docs/prds/034-visibility-and-planning-store/call-site-map.md'",
            "    rest = args[1:] if args else []",
            "    import visibility_callsite_lint",
            "    visibility_callsite_lint.main(['--root', str(root), '--map', map_path, *rest])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "authoring-guard.py":
        body_lines = [
            "    root = repo_root()",
            "    import authoring_guard",
            "    authoring_guard.main([str(root), *args])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "ship-phase-steps.py":
        body_lines = [
            "    root = SCRIPT_DIR.parent",
            "    import ship_phase_steps",
            "    ship_phase_steps.main([str(root), *args])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "host-detect.py":
        body_lines = [
            "    root = SCRIPT_DIR.parent",
            "    import host_lib",
            "    host_lib.main(['--root', str(root), 'resolve'])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "doc-link-check.py":
        body_lines = [
            "    import doc_link",
            "    doc_link.main(['check', *args])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if sh_path.name == "capability-manifest-lint.py" or sh_path.name == "capability-select.py":
        flag = "--root"
        body_lines = [
            "    root = SCRIPT_DIR.parent",
            f"    import {mod}",
            f"    {mod}.main([{flag!r}, str(root), *args])",
            "    return 0",
        ]
        return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))

    if prefix == ["$ROOT"]:
        call_args = "[str(root), *args]"
    elif prefix == ["$REPO_ROOT"]:
        call_args = "[str(root), *args]"
    elif prefix == ["$PWD"]:
        call_args = "[str(root), *args]"
    else:
        call_args = "args"

    body_lines.extend(
        [
            f"    import {mod}",
            f"    {mod}.main({call_args})",
            "    return 0",
        ]
    )
    return ENTRYPOINT_HEADER.format(doc=doc, body="\n".join(body_lines))


def gen_heredoc_module(sh_path: Path, py_body: str, doc: str) -> str:
    header = f'#!/usr/bin/env python3\n"""{doc}"""\nfrom __future__ import annotations\n\n'
    if "def main(" not in py_body:
        indented = "\n".join("    " + line if line.strip() else line for line in py_body.splitlines())
        return (
            header
            + "import sys\n\nfrom _sw.cli import run_module_main\n\n\n"
            + f"def main(argv: list[str] | None = None) -> int:\n{indented}\n    return 0\n\n\n"
            + 'if __name__ == "__main__":\n    run_module_main(main)\n'
        )
    return header + py_body + "\n"


def load_pending() -> list[dict]:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    return [
        e
        for e in ledger["entries"]
        if e.get("phase") == 5
        and e.get("status") == "pending"
        and e["path"].startswith("scripts/")
        and not e["path"].startswith("scripts/test/")
    ]


def port_entry(sh_rel: str, target_rel: str, text: str) -> bool:
    sh_path = ROOT / sh_rel
    target = ROOT / target_rel
    doc = sh_doc(text)
    heredoc = extract_heredoc_py(text)
    if heredoc and "exec python3" in text and "<<" in text:
        target.write_text(gen_heredoc_module(sh_path, heredoc, doc), encoding="utf-8")
        target.chmod(0o755)
        return True
    exec_info = resolve_exec_target(text)
    if exec_info:
        mod_path, prefix = exec_info
        if not (ROOT / "scripts" / mod_path).is_file() and not mod_path.startswith("/"):
            alt = mod_path.replace("-", "_")
            if (ROOT / "scripts" / alt).is_file():
                mod_path = alt
        target.write_text(gen_exec_wrapper(sh_path, mod_path, prefix, doc), encoding="utf-8")
        target.chmod(0o755)
        return True
    return False


def main() -> int:
    ported = 0
    skipped: list[str] = []
    for entry in load_pending():
        sh_rel = entry["path"]
        target_rel = entry["target"]
        sh_path = ROOT / sh_rel
        if not sh_path.is_file():
            skipped.append(sh_rel)
            continue
        if (ROOT / target_rel).is_file():
            continue
        text = sh_path.read_text(encoding="utf-8")
        if port_entry(sh_rel, target_rel, text):
            ported += 1
            print(f"ported wrapper/heredoc: {target_rel}")
        else:
            skipped.append(sh_rel)
    print(f"wrapper/heredoc ported: {ported}, need manual: {len(skipped)}")
    for s in skipped:
        print(f"  manual: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
