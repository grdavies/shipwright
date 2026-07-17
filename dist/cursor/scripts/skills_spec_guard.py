"""Agent Skills spec conformance guard for Shipwright skill trees (PRD 064 R17)."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yaml_structured import safe_load

SKILL_TREE_PREFIXES = (
    "core/skills",
    "dist/cursor/skills",
    "dist/claude-code/skills",
)

ALLOWED_TOP_LEVEL = frozenset(
    {
        "name",
        "description",
        "license",
        "allowed-tools",
        "metadata",
        "compatibility",
    }
)

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
ADVISORY_SKILL_LINES = 450
MAX_SKILL_LINES = 500
MAX_COMPATIBILITY_LEN = 500

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
BACKTICK_PATH_RE = re.compile(
    r"`((?:\./)?(?:references|scripts|assets|skills|core|docs|providers|commands|rules|agents|\.cursor|\.sw)[^`\s]+\.[a-zA-Z0-9]+)`"
)

FILE_SUFFIXES = (".md", ".mdc", ".py", ".json", ".yaml", ".yml")


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    severity: str = "fail"

    def as_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "path": self.path, "message": self.message}
        if self.severity != "fail":
            payload["severity"] = self.severity
        return payload


def _load_frontmatter_keys(text: str) -> tuple[dict[str, Any], list[str]]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, ["missing-frontmatter"]
    parsed = safe_load(match.group(1))
    if not isinstance(parsed, dict):
        return {}, ["invalid-frontmatter"]
    return parsed, []


def _description_shape_ok(description: str) -> bool:
    if not description or not description.strip():
        return False
    if len(description) > MAX_DESCRIPTION_LEN:
        return False
    return "use when" in description.lower()


def _reference_depth_violation(target: str) -> str | None:
    normalized = target.split("#", 1)[0].strip()
    if not normalized or normalized.startswith(("http://", "https://", "mailto:")):
        return None
    if normalized.startswith("references/"):
        remainder = normalized.removeprefix("references/")
        if "/" in remainder.rstrip("/"):
            return "reference path deeper than one level from skill root"
    return None


def _is_template_path(target: str) -> bool:
    normalized = target.split("#", 1)[0].strip()
    if any(ch in normalized for ch in "<>*"):
        return True
    if "YYYY" in normalized or "..." in normalized:
        return True
    if normalized.startswith(".cursor/"):
        return True
    return False


def _resolve_target(
    repo_root: Path,
    skill_root: Path,
    target: str,
    tree_prefix: str,
) -> Path | None:
    normalized = target.split("#", 1)[0].strip()
    if not normalized or normalized.startswith(("http://", "https://", "mailto:")):
        return None
    if normalized.startswith("skills/"):
        return repo_root / tree_prefix / normalized.removeprefix("skills/")
    if normalized.startswith(("core/", "dist/", "docs/", "scripts/", ".cursor/", ".sw/")):
        return repo_root / normalized
    if normalized.startswith("references/") or normalized.startswith("./references/"):
        return skill_root / normalized.removeprefix("./")
    if normalized.startswith(("./", "../")):
        return (skill_root / normalized).resolve()
    if "/" not in normalized:
        candidate = skill_root / normalized
        if candidate.is_file():
            return candidate
        scripts_candidate = repo_root / "scripts" / normalized
        if scripts_candidate.is_file():
            return scripts_candidate
        return None
    return repo_root / normalized


def _should_check_existence(target: str) -> bool:
    normalized = target.split("#", 1)[0].strip()
    if not normalized or normalized.startswith(("http://", "https://", "mailto:")):
        return False
    if _is_template_path(normalized):
        return False
    if normalized.startswith("references/"):
        return True
    if normalized.startswith("skills/") and normalized.endswith("/SKILL.md"):
        return True
    if normalized.endswith("CAPABILITIES.md"):
        return True
    return False


def _collect_path_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        refs.append(match.group(1).strip())
    for match in BACKTICK_PATH_RE.finditer(text):
        refs.append(match.group(1).strip())
    return refs


def _scan_skill_md(repo_root: Path, skill_md: Path, tree_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    rel = skill_md.relative_to(repo_root).as_posix()
    is_skill_entry = skill_md.name == "SKILL.md"
    skill_root = skill_md.parent
    skill_dir = skill_root.name
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("read-error", rel, str(exc))]

    if skill_md.name == "SKILL.md":
        lines = text.splitlines()
        line_count = len(lines)
        if line_count > MAX_SKILL_LINES:
            findings.append(
                Finding(
                    "skill-line-budget",
                    rel,
                    f"SKILL.md has {line_count} lines (max {MAX_SKILL_LINES})",
                )
            )
        elif line_count >= ADVISORY_SKILL_LINES:
            findings.append(
                Finding(
                    "skill-line-budget-advisory",
                    rel,
                    (
                        f"SKILL.md has {line_count} lines "
                        f"(advisory at >={ADVISORY_SKILL_LINES}; hard fail above {MAX_SKILL_LINES})"
                    ),
                    severity="advisory",
                )
            )

    frontmatter, fm_errors = _load_frontmatter_keys(text)
    if is_skill_entry:
        for err in fm_errors:
            findings.append(Finding("frontmatter", rel, err))

    extra_keys = sorted(set(frontmatter) - ALLOWED_TOP_LEVEL) if is_skill_entry else []
    for key in extra_keys:
        findings.append(
            Finding(
                "closed-field-set",
                rel,
                f"disallowed top-level field {key!r}",
            )
        )

    if not is_skill_entry:
        body = FRONTMATTER_RE.sub("", text, count=1)
        is_reference_file = True
        for ref in _collect_path_refs(body):
            depth_issue = _reference_depth_violation(ref)
            if depth_issue:
                findings.append(Finding("reference-depth", rel, f"{ref}: {depth_issue}"))
            if ref.startswith("references/"):
                findings.append(
                    Finding(
                        "reference-nested-tier",
                        rel,
                        f"reference file links to nested reference tier {ref!r}",
                    )
                )
        return findings

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        findings.append(Finding("name-missing", rel, "missing or empty name"))
    else:
        if len(name) > MAX_NAME_LEN:
            findings.append(Finding("name-length", rel, f"name exceeds {MAX_NAME_LEN} characters"))
        if not NAME_RE.fullmatch(name) or "--" in name:
            findings.append(Finding("name-regex", rel, f"name {name!r} fails Agent Skills name regex"))
        if name != skill_dir:
            findings.append(
                Finding(
                    "name-dir-mismatch",
                    rel,
                    f"name {name!r} does not match directory {skill_dir!r}",
                )
            )

    description = frontmatter.get("description")
    if not isinstance(description, str):
        findings.append(Finding("description-missing", rel, "missing description"))
    else:
        if len(description) > MAX_DESCRIPTION_LEN:
            findings.append(
                Finding(
                    "description-length",
                    rel,
                    f"description length {len(description)} exceeds {MAX_DESCRIPTION_LEN}",
                )
            )
        if not _description_shape_ok(description):
            findings.append(
                Finding(
                    "description-shape",
                    rel,
                    'description must include what+when shape with explicit "Use when" trigger',
                )
            )

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility.strip():
            findings.append(Finding("compatibility", rel, "compatibility must be a non-empty string"))
        elif len(compatibility) > MAX_COMPATIBILITY_LEN:
            findings.append(
                Finding(
                    "compatibility-length",
                    rel,
                    f"compatibility exceeds {MAX_COMPATIBILITY_LEN} characters",
                )
            )

    body = FRONTMATTER_RE.sub("", text, count=1)
    is_reference_file = skill_md.name != "SKILL.md" and "references" in skill_md.parts

    for ref in _collect_path_refs(body):
        depth_issue = _reference_depth_violation(ref)
        if depth_issue:
            findings.append(Finding("reference-depth", rel, f"{ref}: {depth_issue}"))
        if is_reference_file and ref.startswith("references/"):
            findings.append(
                Finding(
                    "reference-nested-tier",
                    rel,
                    f"reference file links to nested reference tier {ref!r}",
                )
            )
        if not _should_check_existence(ref):
            continue
        resolved = _resolve_target(repo_root, skill_root, ref, tree_prefix)
        if resolved is None or resolved.is_file():
            continue
        findings.append(
            Finding(
                "missing-reference",
                rel,
                f"referenced path does not exist: {ref}",
            )
        )

    return findings


def iter_skill_files(repo_root: Path, tree_prefix: str) -> list[Path]:
    base = repo_root / tree_prefix
    if not base.is_dir():
        return []
    return sorted(base.glob("*/SKILL.md"))


def iter_reference_files(repo_root: Path, tree_prefix: str) -> list[Path]:
    base = repo_root / tree_prefix
    if not base.is_dir():
        return []
    return sorted(base.glob("*/references/*.md"))


def scan_tree(repo_root: Path, tree_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    for skill_md in iter_skill_files(repo_root, tree_prefix):
        findings.extend(_scan_skill_md(repo_root, skill_md, tree_prefix))
    for ref_md in iter_reference_files(repo_root, tree_prefix):
        findings.extend(_scan_skill_md(repo_root, ref_md, tree_prefix))
    return findings


def scan_repo(repo_root: Path, tree_prefixes: tuple[str, ...] | None = None) -> list[Finding]:
    prefixes = tree_prefixes or SKILL_TREE_PREFIXES
    findings: list[Finding] = []
    for prefix in prefixes:
        findings.extend(scan_tree(repo_root, prefix))
    return findings


def advisory_skills_ref(repo_root: Path, tree_prefix: str) -> list[Finding]:
    if shutil.which("skills-ref") is None:
        return []
    target = repo_root / tree_prefix
    if not target.is_dir():
        return []
    proc = subprocess.run(
        ["skills-ref", "validate", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return []
    detail = (proc.stderr or proc.stdout or "skills-ref validate failed").strip()
    return [Finding("skills-ref-advisory", tree_prefix, detail[:500])]


def partition_findings(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    hard = [finding for finding in findings if finding.severity != "advisory"]
    advisory = [finding for finding in findings if finding.severity == "advisory"]
    return hard, advisory


def check_repo(
    repo_root: Path,
    *,
    tree_prefixes: tuple[str, ...] | None = None,
    include_skills_ref: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    findings = scan_repo(repo_root, tree_prefixes)
    if include_skills_ref:
        for prefix in tree_prefixes or SKILL_TREE_PREFIXES:
            findings.extend(advisory_skills_ref(repo_root, prefix))
    hard_findings, advisory_findings = partition_findings(findings)
    payload: dict[str, Any] = {
        "verdict": "pass" if not hard_findings else "fail",
        "findingCount": len(hard_findings),
        "findings": [f.as_dict() for f in hard_findings],
        "advisoryCount": len(advisory_findings),
        "advisories": [f.as_dict() for f in advisory_findings],
    }
    if hard_findings:
        payload["halt"] = "skills-spec-guard"
    return payload
