#!/usr/bin/env python3
"""Pre-push secret scan — deny patterns single-sourced with memory_redact (R41/R50/R51)."""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from secret_patterns import DENY_PATTERNS

EXIT_PASS = 0
EXIT_DENY = 1
EXIT_ERROR = 2

ALLOWLIST_REL = Path(".cursor/sw-secret-scan-allowlist.json")


@dataclass(frozen=True)
class Finding:
    pattern: str
    line_no: int
    excerpt: str


def repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return Path(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"secret-scan: not in a git repository ({exc})") from exc


def load_allowlist(root: Path) -> dict[str, list[str]]:
    path = root / ALLOWLIST_REL
    if not path.is_file():
        return {"lines": [], "paths": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"secret-scan: corrupt allowlist {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"secret-scan: allowlist must be a JSON object: {path}")
    lines = data.get("lines", [])
    paths = data.get("paths", [])
    if not isinstance(lines, list) or not isinstance(paths, list):
        raise RuntimeError(f"secret-scan: allowlist lines/paths must be arrays: {path}")
    return {"lines": [str(x) for x in lines], "paths": [str(x) for x in paths]}


def is_allowed(*, matched: str, line: str, path: str | None, allowlist: dict[str, list[str]]) -> bool:
    for entry in allowlist.get("lines", []):
        if entry and (entry in line or entry == matched):
            return True
    if path:
        for entry in allowlist.get("paths", []):
            if entry and entry in path.replace("\\", "/"):
                return True
    return False


def scan_text(
    text: str,
    *,
    allowlist: dict[str, list[str]],
    path: str | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for deny in DENY_PATTERNS:
            for match in deny.pattern.finditer(line):
                matched = match.group(0)
                if is_allowed(matched=matched, line=line, path=path, allowlist=allowlist):
                    continue
                excerpt = line.strip()
                if len(excerpt) > 120:
                    excerpt = excerpt[:117] + "..."
                findings.append(Finding(deny.name, line_no, excerpt))
    return findings


def git_out(*args: str, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"secret-scan: git {' '.join(args)} failed: {exc.output.strip()}") from exc


def collect_pre_push_diff(root: Path) -> str:
    upstream = None
    try:
        upstream = git_out("rev-parse", "@{upstream}", cwd=root).strip()
    except RuntimeError:
        upstream = None

    if upstream:
        try:
            return git_out("diff", f"{upstream}..HEAD", cwd=root)
        except RuntimeError:
            pass

    try:
        unpushed = git_out("rev-list", "HEAD", "--not", "--remotes", cwd=root).strip()
        if unpushed:
            return git_out("log", "--format=", "-p", *unpushed.split(), cwd=root)
    except RuntimeError:
        pass

    for base in ("origin/main", "main", "origin/master", "master"):
        try:
            git_out("rev-parse", "--verify", base, cwd=root)
            diff = git_out("diff", f"{base}...HEAD", cwd=root)
            if diff.strip():
                return diff
        except RuntimeError:
            continue

    try:
        if git_out("rev-parse", "--verify", "HEAD~0", cwd=root):
            return git_out("log", "--format=", "-p", "-1", "HEAD", cwd=root)
    except RuntimeError:
        pass

    return git_out("diff", "--cached", cwd=root) + git_out("diff", cwd=root)


def iter_diff_file_chunks(diff: str) -> Iterator[tuple[str, str]]:
    """Yield (repo-relative path, chunk) per file in a unified diff for path allowlisting."""
    current_path: str | None = None
    current_lines: list[str] = []

    def flush() -> Iterator[tuple[str, str]]:
        nonlocal current_path, current_lines
        if current_path is not None and current_lines:
            yield current_path, "".join(current_lines)
        current_path = None
        current_lines = []

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            yield from flush()
            parts = line.split()
            b_path = None
            for part in reversed(parts):
                if part.startswith("b/"):
                    b_path = part[2:]
                    break
            current_path = b_path or "unknown"
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)
    yield from flush()


def scan_diff(diff: str, *, allowlist: dict[str, list[str]]) -> list[Finding]:
    if not diff.strip():
        return []
    chunks = list(iter_diff_file_chunks(diff))
    if not chunks:
        return scan_text(diff, allowlist=allowlist, path=None)
    findings: list[Finding] = []
    for path, chunk in chunks:
        findings.extend(scan_text(chunk, allowlist=allowlist, path=path))
    return findings


def report_findings(findings: list[Finding]) -> None:
    print("secret-scan: deny pattern match — push blocked", file=sys.stderr)
    for f in findings[:20]:
        print(f"  [{f.pattern}] line {f.line_no}: {f.excerpt}", file=sys.stderr)
    if len(findings) > 20:
        print(f"  ... and {len(findings) - 20} more", file=sys.stderr)
    print(
        "Remediation: remove or rotate the secret, redact from history (range-scoped only — "
        "see rules/sw-redaction-scope.mdc), or add a fixture-only allowlist entry to "
        f"{ALLOWLIST_REL} if this is an intentional test literal.",
        file=sys.stderr,
    )


def cmd_pre_push(root: Path, allowlist: dict[str, list[str]]) -> int:
    diff = collect_pre_push_diff(root)
    findings = scan_diff(diff, allowlist=allowlist)
    if findings:
        report_findings(findings)
        return EXIT_DENY
    return EXIT_PASS


def cmd_file(path: Path, allowlist: dict[str, list[str]]) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = scan_text(text, allowlist=allowlist, path=str(path))
    if findings:
        report_findings(findings)
        return EXIT_DENY
    return EXIT_PASS


def cmd_stdin(allowlist: dict[str, list[str]]) -> int:
    findings = scan_text(sys.stdin.read(), allowlist=allowlist)
    if findings:
        report_findings(findings)
        return EXIT_DENY
    return EXIT_PASS


def cmd_patterns_check() -> int:
    from memory_redact import redact  # noqa: PLC0415 — intentional coupling check

    sample = "token=ghp_" + ("x" * 40)
    redacted = redact(sample)
    if "ghp_" in redacted:
        print("secret-scan: memory_redact.py does not redact ghp_ sample", file=sys.stderr)
        return EXIT_ERROR
    if len(DENY_PATTERNS) < 10:
        print("secret-scan: deny pattern set unexpectedly small", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_PASS


def main() -> int:
    try:
        root = repo_root()
        allowlist = load_allowlist(root)
        cmd = sys.argv[1] if len(sys.argv) > 1 else "pre-push"
        if cmd == "pre-push":
            return cmd_pre_push(root, allowlist)
        if cmd == "file":
            if len(sys.argv) < 3:
                raise RuntimeError("secret-scan: file requires a path argument")
            return cmd_file(Path(sys.argv[2]), allowlist)
        if cmd == "stdin":
            return cmd_stdin(allowlist)
        if cmd == "patterns-check":
            return cmd_patterns_check()
        raise RuntimeError(f"secret-scan: unknown command {cmd!r}")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
