#!/usr/bin/env python3
"""Pre-push secret scan — deny patterns single-sourced with memory_redact (R41/R50/R51)."""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from secret_patterns import DENY_PATTERNS, email_match_is_schema_version_token

EXIT_PASS = 0
EXIT_DENY = 1
EXIT_ERROR = 2

ALLOWLIST_REL = Path(".cursor/sw-secret-scan-allowlist.json")
_PUBLIC_GLOB_CONTACT = "i" + "@izs.me"
_PUBLIC_GLOB_DEPRECATION = (
    "deprecated: Old versions of glob are not supported, and contain widely "
    "publicized security vulnerabilities, which have been fixed in the current "
    "version. Please update. Support for old versions may be purchased "
    "(at exorbitant rates) by contacting " + _PUBLIC_GLOB_CONTACT
)


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
                if deny.name == "EMAIL" and email_match_is_schema_version_token(
                    matched, line=line, match_start=match.start()
                ):
                    continue
                if (
                    deny.name == "EMAIL"
                    and path == "pnpm-lock.yaml"
                    and matched == _PUBLIC_GLOB_CONTACT
                    and line.strip() == _PUBLIC_GLOB_DEPRECATION
                ):
                    continue
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


@dataclass(frozen=True)
class _PrePushSelection:
    """Baseline patch and its pinned endpoints; never evidence of source approval.

    Root and merge-log selections have no single base; kind distinguishes them.
    A merge log is not first-parent patch provenance. Uncommitted fallback has
    neither endpoint and cannot supply committed source context.
    """

    diff: str
    kind: str
    base_oid: str | None
    target_oid: str | None


def _resolve_commit(root: Path, revision: str) -> str:
    oid = git_out("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}", cwd=root).strip()
    if len(oid) not in (40, 64) or any(c not in "0123456789abcdef" for c in oid):
        raise RuntimeError("secret-scan: invalid resolved commit identity")
    return oid


def _collect_pre_push_selection(root: Path) -> _PrePushSelection:
    """Select once, then acquire using object IDs instead of moving refs.

    Unavailable selection probes retain the legacy fallback order. Once selected,
    patch acquisition errors propagate: a smaller range cannot stand in for a
    failed baseline scan. Resolver output proposes a range, never source trust.
    """
    try:
        head = _resolve_commit(root, "HEAD")
    except RuntimeError:
        head = None

    def resolve(revision: str) -> str:
        revision = revision or "HEAD"
        for alias in ("HEAD", "@"):
            if head and revision == alias:
                return head
            if head and revision.startswith((alias + "~", alias + "^")):
                revision = head + revision[len(alias):]
                break
        return _resolve_commit(root, revision)

    def between(kind: str, base: str, target: str) -> _PrePushSelection:
        return _PrePushSelection(git_out("diff", f"{base}..{target}", cwd=root), kind, base, target)

    if head:
        try:
            upstream = resolve("@{upstream}")
            base = git_out("merge-base", upstream, head, cwd=root).strip()
        except RuntimeError:
            pass
        else:
            return between("upstream", base, head)

    resolver = root / "scripts" / "resolve_base_branch.py"
    if resolver.is_file():
        resolved = None
        try:
            proc = subprocess.run(
                [sys.executable, str(resolver), "diff-base"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                range_spec = data.get("range", "") if isinstance(data, dict) else ""
                if isinstance(range_spec, str) and ".." in range_spec:
                    if "..." in range_spec:
                        base_ref, target_ref = range_spec.split("...", 1)
                        base, target = resolve(base_ref), resolve(target_ref)
                        base = git_out("merge-base", base, target, cwd=root).strip()
                    else:
                        base_ref, target_ref = range_spec.split("..", 1)
                        base, target = resolve(base_ref), resolve(target_ref)
                    resolved = (base, target)
        except (RuntimeError, json.JSONDecodeError, subprocess.SubprocessError):
            pass
        if resolved is not None:
            return between("resolver", *resolved)

    if head:
        parent = None
        try:
            unpushed = git_out("rev-list", head, "--not", "--remotes", cwd=root).split()
            if unpushed:
                parent = resolve(f"{unpushed[-1]}^")
        except RuntimeError:
            pass
        if parent is not None:
            return between("unpushed", parent, head)

        for candidate in ("origin/main", "main", "origin/master", "master"):
            try:
                base = resolve(candidate)
                base = git_out("merge-base", base, head, cwd=root).strip()
            except RuntimeError:
                continue
            selected = between("triple-dot", base, head)
            if selected.diff.strip():
                return selected

        parents = git_out("rev-list", "--parents", "-n", "1", head, cwd=root).split()[1:]
        # Keep log's legacy merge/root patch semantics rather than substituting
        # a first-parent diff, which can change the selected additions.
        diff = git_out("log", "--format=", "-p", "-1", head, cwd=root)
        if len(parents) > 1:
            return _PrePushSelection(diff, "merge-commit", None, head)
        return _PrePushSelection(diff, "last-commit" if parents else "root", parents[0] if parents else None, head)

    diff = git_out("diff", "--cached", cwd=root) + git_out("diff", cwd=root)
    return _PrePushSelection(diff, "uncommitted", None, None)


def collect_pre_push_diff(root: Path) -> str:
    return _collect_pre_push_selection(root).diff


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


def diff_added_lines_only(chunk: str) -> str:
    """Return only lines introduced in a unified diff hunk (pre-push scope)."""
    added: list[str] = []
    for line in chunk.splitlines():
        if line.startswith(("+++", "---", "@@", "diff ")):
            continue
        if line.startswith("+"):
            added.append(line[1:])
    return "\n".join(added)


def scan_diff(diff: str, *, allowlist: dict[str, list[str]]) -> list[Finding]:
    if not diff.strip():
        return []
    chunks = list(iter_diff_file_chunks(diff))
    if not chunks:
        return scan_text(diff, allowlist=allowlist, path=None)
    findings: list[Finding] = []
    for path, chunk in chunks:
        if "Binary files " in chunk:
            continue
        added = diff_added_lines_only(chunk)
        if not added.strip():
            continue
        findings.extend(scan_text(added, allowlist=allowlist, path=path))
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
    selection = _collect_pre_push_selection(root)
    findings = scan_diff(selection.diff, allowlist=allowlist)
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
    from planning_visibility import resolve_emission_destination

    sample = "token=ghp_" + ("x" * 40)
    destination = resolve_emission_destination("dispatch-context")
    redacted = redact(sample, destination=destination)
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
