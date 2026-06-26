#!/usr/bin/env python3
"""CHANGELOG.md and version.txt bookkeeping for /sw-deliver phase merges (R58–R60)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MARKER_PREFIX = "sw-deliver:"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_release_sections(root: Path) -> dict[str, str]:
    cfg_path = root / "release-please-config.json"
    if not cfg_path.is_file():
        return {
            "feat": "Features",
            "fix": "Bug Fixes",
            "perf": "Performance",
            "revert": "Reverts",
            "docs": "Documentation",
        }
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    sections: dict[str, str] = {}
    for pkg in (cfg.get("packages") or {}).values():
        for item in pkg.get("changelog-sections") or []:
            if item.get("hidden"):
                continue
            sections[item["type"]] = item["section"]
    return sections


def parse_semver(text: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", text.strip())
    if not m:
        fail(f"invalid semver in version.txt: {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_semver(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def projected_version(base: tuple[int, int, int], commit_types: list[str]) -> str:
    major, minor, patch = base
    normalized = [t.split("!", 1)[0].lower() for t in commit_types]
    if any("!" in t or t.endswith("!") for t in commit_types):
        return format_semver(major + 1, 0, 0)
    if "feat" in normalized:
        return format_semver(major, minor + 1, 0)
    if any(t in ("fix", "perf", "revert") for t in normalized):
        return format_semver(major, minor, patch + 1)
    return format_semver(major, minor, patch)


def base_version_from_file(version_path: Path) -> tuple[int, int, int]:
    if not version_path.is_file():
        return 0, 1, 0
    return parse_semver(version_path.read_text(encoding="utf-8"))


def released_version_from_changelog(content: str) -> tuple[int, int, int] | None:
    versions: list[tuple[int, int, int]] = []
    for match in re.finditer(r"^## \[(\d+\.\d+\.\d+)\]", content, re.MULTILINE):
        versions.append(parse_semver(match.group(1)))
    if not versions:
        return None
    return max(versions)


def resolve_base_version(changelog_path: Path, version_path: Path) -> tuple[int, int, int]:
    if changelog_path.is_file():
        released = released_version_from_changelog(changelog_path.read_text(encoding="utf-8"))
        if released:
            return released
    return base_version_from_file(version_path)


def merged_commit_types(state: dict[str, Any], exclude_slug: str | None = None) -> list[str]:
    types: list[str] = []
    for record in state.get("mergedPhases") or []:
        if record.get("reverted") or record.get("bookkeepingReverted"):
            continue
        if exclude_slug and record.get("phaseSlug") == exclude_slug:
            continue
        t = record.get("commitType")
        if t:
            types.append(str(t))
    return types


def entry_marker(phase_slug: str) -> str:
    return f"<!-- {MARKER_PREFIX}{phase_slug} -->"


def ensure_unreleased_block(content: str) -> str:
    if re.search(r"^## \[Unreleased\]\s*$", content, re.MULTILINE):
        return content
    if content.startswith("# Changelog"):
        parts = content.split("\n", 1)
        head = parts[0]
        rest = parts[1] if len(parts) > 1 else "\n"
        return f"{head}\n\n## [Unreleased]\n{rest}"
    return f"# Changelog\n\n## [Unreleased]\n\n{content}"


def insert_changelog_entry(
    content: str, section: str, line: str
) -> str:
    content = ensure_unreleased_block(content)
    unreleased_match = re.search(
        r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not unreleased_match:
        fail("could not locate ## [Unreleased] section")

    unreleased_body = unreleased_match.group(1)
    section_header = f"### {section}"
    section_pattern = re.compile(
        rf"^### {re.escape(section)}\s*\n(.*?)(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    section_match = section_pattern.search(unreleased_body)
    if section_match:
        existing = section_match.group(1).rstrip("\n")
        new_body = existing + "\n" + line + "\n"
        new_section = f"{section_header}\n{new_body}"
        new_unreleased = (
            unreleased_body[: section_match.start()]
            + new_section
            + unreleased_body[section_match.end() :]
        )
    else:
        addition = f"\n{section_header}\n\n{line}\n"
        new_unreleased = unreleased_body.rstrip("\n") + addition + "\n"

    start = unreleased_match.start(1)
    end = unreleased_match.end(1)
    return content[:start] + new_unreleased + content[end:]


def remove_changelog_entry(content: str, phase_slug: str) -> tuple[str, bool]:
    marker = entry_marker(phase_slug)
    lines = content.splitlines(keepends=True)
    new_lines = [ln for ln in lines if marker not in ln]
    removed = len(new_lines) != len(lines)
    return "".join(new_lines), removed


def resolve_worktree(root: Path, args: list[str]) -> Path:
    explicit = parse_kv(args, "--worktree")
    if explicit:
        return Path(explicit).resolve()
    from wave_state import load_deliver_state

    state = load_deliver_state(root)
    orch = state.get("orchestratorWorktree") or {}
    path = orch.get("path")
    if path:
        return Path(path).resolve()
    return root.resolve()


def git_commit_bookkeeping(worktree: Path, phase_slug: str, dry_run: bool) -> str | None:
    if dry_run:
        return None
    git_run = lambda cmd: subprocess.run(
        ["git"] + cmd, cwd=str(worktree), text=True, capture_output=True, check=False
    )
    git_run(["add", "CHANGELOG.md", "version.txt"])
    msg = f"chore: deliver bookkeeping for phase {phase_slug}"
    proc = git_run(["commit", "-m", msg])
    if proc.returncode != 0:
        if "nothing to commit" in (proc.stdout + proc.stderr):
            return None
        fail(proc.stderr.strip() or proc.stdout.strip() or "bookkeeping commit failed")
    sha = git_run(["rev-parse", "HEAD"]).stdout.strip()
    return sha


def cmd_record(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    message = parse_kv(args, "--message")
    commit_type = parse_kv(args, "--type", "feat") or "feat"
    merge_commit = parse_kv(args, "--merge-commit", "")
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")

    if not phase_slug or not message:
        fail("--phase-slug and --message required")

    worktree = resolve_worktree(root, args)
    changelog_path = worktree / "CHANGELOG.md"
    version_path = worktree / "version.txt"

    sections = load_release_sections(root)
    section = sections.get(commit_type.split("!")[0].lower())
    if not section:
        fail(f"commit type {commit_type!r} has no visible changelog section")

    from wave_state import load_deliver_state, resolve_state_path

    state_path = resolve_state_path(root)
    state = load_deliver_state(root)
    if changelog_path.is_file():
        changelog = changelog_path.read_text(encoding="utf-8")
    else:
        changelog = "# Changelog\n\n"
    base = resolve_base_version(changelog_path, version_path)
    types = merged_commit_types(state) + [commit_type]
    new_version = projected_version(base, types)

    marker = entry_marker(phase_slug)
    line = f"* {message} {marker}"
    if merge_commit:
        short = merge_commit[:7]
        line = f"* {message} ({short}) {marker}"

    new_changelog = insert_changelog_entry(changelog, section, line)

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "bookkeeping-record",
                "dry_run": True,
                "phase": phase_slug,
                "section": section,
                "projectedVersion": new_version,
                "line": line.strip(),
            }
        )

    changelog_path.write_text(new_changelog, encoding="utf-8")
    version_path.write_text(new_version + "\n", encoding="utf-8")

    bookkeeping_sha = None
    if do_commit:
        bookkeeping_sha = git_commit_bookkeeping(worktree, phase_slug, dry_run=False)

    if state_path.is_file():
        state = read_json(state_path)
        for record in state.get("mergedPhases") or []:
            if record.get("phaseSlug") == phase_slug:
                record["commitType"] = commit_type
                record["bookkeepingVersion"] = new_version
                if bookkeeping_sha:
                    record["bookkeepingCommit"] = bookkeeping_sha
                break
        state["projectedVersion"] = new_version
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    emit(
        {
            "verdict": "pass",
            "action": "bookkeeping-record",
            "phase": phase_slug,
            "section": section,
            "projectedVersion": new_version,
            "bookkeepingCommit": bookkeeping_sha,
        }
    )


def cmd_revert(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")

    worktree = resolve_worktree(root, args)
    changelog_path = worktree / "CHANGELOG.md"
    version_path = worktree / "version.txt"
    if not changelog_path.is_file():
        fail(f"CHANGELOG.md not found in {worktree}")

    from wave_state import load_deliver_state, resolve_state_path

    state_path = resolve_state_path(root)
    state = load_deliver_state(root)

    if changelog_path.is_file():
        changelog = changelog_path.read_text(encoding="utf-8")
    else:
        changelog = "# Changelog\n\n"
    new_changelog, removed = remove_changelog_entry(changelog, phase_slug)
    if not removed:
        fail(f"no changelog entry found for phase {phase_slug!r}", exit_code=20)

    base = resolve_base_version(changelog_path, version_path)
    types = merged_commit_types(state, exclude_slug=phase_slug)
    new_version = projected_version(base, types)

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "bookkeeping-revert",
                "dry_run": True,
                "phase": phase_slug,
                "projectedVersion": new_version,
            }
        )

    changelog_path.write_text(new_changelog, encoding="utf-8")
    version_path.write_text(new_version + "\n", encoding="utf-8")

    bookkeeping_sha = None
    if do_commit:
        bookkeeping_sha = git_commit_bookkeeping(
            worktree, f"revert-{phase_slug}", dry_run=False
        )

    if state_path.is_file():
        state = read_json(state_path)
        merged = []
        for record in state.get("mergedPhases") or []:
            if record.get("phaseSlug") == phase_slug:
                record = {**record, "reverted": True, "bookkeepingReverted": True}
            merged.append(record)
        state["mergedPhases"] = merged
        state["projectedVersion"] = new_version
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    emit(
        {
            "verdict": "pass",
            "action": "bookkeeping-revert",
            "phase": phase_slug,
            "projectedVersion": new_version,
            "bookkeepingCommit": bookkeeping_sha,
        }
    )


def cmd_projected(root: Path, args: list[str]) -> None:
    types_raw = parse_kv(args, "--types", "feat") or "feat"
    types = [t.strip() for t in types_raw.split(",") if t.strip()]
    worktree = resolve_worktree(root, args)
    base = base_version_from_file(worktree / "version.txt")
    emit(
        {
            "verdict": "pass",
            "action": "bookkeeping-projected",
            "base": format_semver(*base),
            "projectedVersion": projected_version(base, types),
            "types": types,
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_bookkeeping.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]

    if cmd == "record":
        cmd_record(root, args)
    elif cmd == "revert":
        cmd_revert(root, args)
    elif cmd == "projected":
        cmd_projected(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
