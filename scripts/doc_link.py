#!/usr/bin/env python3
"""Brainstorm↔PRD frontmatter traceability (PRD 009 A1 — R52–R55)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import planning_artifact_handle as pah

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

BRAINSTORM_KEYS = ("brainstorm", "source_brainstorm")
PRD_KEYS = ("prd",)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    block = content[3:end].strip()
    fm: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = val.strip()
    return fm, content[end + 4 :].lstrip("\n")


def join_frontmatter(fm: dict[str, str], body: str) -> str:
    lines = ["---"]
    for key in sorted(fm.keys()):
        lines.append(f"{key}: {fm[key]}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.lstrip("\n")


def parse_link_paths(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    return [raw]


def is_truthy_frozen(fm: dict[str, str]) -> bool:
    return str(fm.get("frozen", "")).lower() in ("true", "yes", "1")


def brainstorm_ref_unit_id(ref: str) -> str:
    """Derive a planning-store unit id from a brainstorm path or unit-id reference."""
    ref = ref.strip().strip("'\"")
    stem = Path(ref).stem
    if stem.startswith("brainstorm"):
        return stem
    return f"brainstorm-{stem}"


def _linked_brainstorm_unit_id(root: Path, prd_unit_id: str | None) -> str | None:
    if not prd_unit_id or not pah.issue_store_is_effective(root):
        return None
    from planning_store import get_backend

    backend = get_backend(root)
    finder = getattr(backend, "_find_linked_brainstorm", None)
    if not callable(finder):
        return None
    linked = finder(prd_unit_id)
    if linked is None:
        return None
    uid = str(getattr(linked, "unit_id", "") or "").strip()
    return uid or None


def link_target_resolves(
    root: Path,
    rel: str,
    *,
    unit_id: str | None = None,
    prd_unit_id: str | None = None,
) -> bool:
    rel = rel.strip().strip("'\"")
    if not rel or rel.startswith("http"):
        return False
    if pah.resolve_repo_file(root, rel) is not None:
        return True
    candidates: list[str | None] = [unit_id]
    if "/" not in rel and not rel.endswith(".md"):
        candidates.append(rel)
    candidates.append(brainstorm_ref_unit_id(rel))
    linked = _linked_brainstorm_unit_id(root, prd_unit_id)
    if linked:
        candidates.append(linked)
    seen: set[str | None] = set()
    for uid in candidates:
        if uid in seen:
            continue
        seen.add(uid)
        if pah.artifact_handle_resolves(root, rel, unit_id=uid):
            return True
    return pah.artifact_handle_resolves(root, rel)


def brainstorm_backref(fm: dict[str, str]) -> str | None:
    for key in BRAINSTORM_KEYS:
        if fm.get(key):
            return fm[key]
    return None


def prd_forward_refs(fm: dict[str, str]) -> list[str]:
    out: list[str] = []
    for key in PRD_KEYS:
        out.extend(parse_link_paths(fm.get(key)))
    return out


def infer_tier_from_rel(rel: str, tier: str | None) -> str:
    if tier in ("full", "standard"):
        return tier
    return "full"


def check_prd_content(
    root: Path,
    rel: str,
    text: str,
    tier: str,
    *,
    unit_id: str | None = None,
) -> dict[str, Any]:
    fm, _ = split_frontmatter(text)
    findings: list[dict[str, str]] = []
    frozen = is_truthy_frozen(fm)
    prd_unit_id = unit_id or fm.get("id") or fm.get("unit-id")

    back = brainstorm_backref(fm)
    requires_brainstorm = tier == "full" or frozen
    if requires_brainstorm:
        if not back:
            findings.append(
                {
                    "code": "missing-brainstorm-backref",
                    "message": (
                        "Full-tier or frozen PRD requires brainstorm: "
                        "(or legacy source_brainstorm:) in frontmatter"
                    ),
                }
            )
        else:
            for target in parse_link_paths(back):
                if not link_target_resolves(
                    root,
                    target,
                    unit_id=brainstorm_ref_unit_id(target),
                    prd_unit_id=prd_unit_id,
                ):
                    findings.append(
                        {
                            "code": "dangling-brainstorm-backref",
                            "message": f"brainstorm back-reference does not resolve: {target}",
                        }
                    )

    # PRD bodies use `prd: <number>` as metadata; only path-like values are links.
    for target in prd_forward_refs(fm):
        t = target.strip().strip("'\"")
        if "/" not in t and not t.endswith(".md"):
            continue
        if not link_target_resolves(root, target, prd_unit_id=prd_unit_id):
            findings.append(
                {
                    "code": "dangling-prd-forwardref",
                    "message": f"prd forward reference does not resolve: {target}",
                }
            )

    verdict = "pass" if not findings else "fail"
    return {
        "verdict": verdict,
        "artifact": "prd",
        "path": rel,
        "tier": tier,
        "frozen": frozen,
        "findings": findings,
    }


def check_brainstorm_content(
    root: Path,
    rel: str,
    text: str,
    *,
    unit_id: str | None = None,
) -> dict[str, Any]:
    fm, _ = split_frontmatter(text)
    findings: list[dict[str, str]] = []
    brainstorm_unit_id = unit_id or fm.get("id") or brainstorm_ref_unit_id(rel)

    for target in prd_forward_refs(fm):
        if not link_target_resolves(root, target, prd_unit_id=Path(target).stem):
            findings.append(
                {
                    "code": "dangling-prd-forwardref",
                    "message": f"prd forward reference does not resolve: {target}",
                }
            )

    back = brainstorm_backref(fm)
    if back and not link_target_resolves(
        root,
        back,
        unit_id=brainstorm_ref_unit_id(back),
        prd_unit_id=brainstorm_unit_id,
    ):
        findings.append(
            {
                "code": "dangling-brainstorm-selfref",
                "message": f"brainstorm self-reference does not resolve: {back}",
            }
        )

    verdict = "pass" if not findings else "fail"
    return {"verdict": verdict, "artifact": "brainstorm", "path": rel, "findings": findings}


def check_artifact(
    root: Path,
    body_path: str,
    tier: str | None = None,
    *,
    unit_id: str | None = None,
) -> dict[str, Any]:
    rel = pah.normalize_body_path(body_path)
    text, _ = pah.resolve_artifact_text(root, rel, unit_id=unit_id)
    if text is None:
        return {"verdict": "fail", "path": rel, "error": f"artifact not found: {rel}"}
    norm = rel.replace("\\", "/")
    resolved_unit_id = unit_id or pah.default_unit_id_from_body_path(rel)
    if "docs/brainstorms/" in norm:
        return check_brainstorm_content(root, rel, text, unit_id=resolved_unit_id)
    name = Path(norm).name
    if "/prd-" in name or norm.endswith("-prd.md"):
        return check_prd_content(
            root,
            rel,
            text,
            infer_tier_from_rel(rel, tier),
            unit_id=resolved_unit_id,
        )
    if "docs/prds/" in norm and "prd" in name:
        return check_prd_content(
            root,
            rel,
            text,
            infer_tier_from_rel(rel, tier),
            unit_id=resolved_unit_id,
        )
    return {"verdict": "pass", "path": rel, "note": "not a PRD/brainstorm — skipped"}


def normalize_body_ref(root: Path, ref: str) -> tuple[str, str | None]:
    ref = ref.strip()
    path = Path(ref)
    if path.is_absolute() and path.is_file():
        try:
            return str(path.resolve().relative_to(root.resolve())), None
        except ValueError:
            pass
    rel = pah.normalize_body_path(ref)
    return rel, pah.default_unit_id_from_body_path(rel)


def write_backref(
    root: Path,
    brainstorm: str,
    prd: str,
    *,
    brainstorm_unit_id: str | None = None,
    prd_unit_id: str | None = None,
) -> dict[str, Any]:
    bs_rel, bs_uid = normalize_body_ref(root, brainstorm)
    prd_rel, prd_uid = normalize_body_ref(root, prd)
    bs_uid = brainstorm_unit_id or bs_uid
    prd_uid = prd_unit_id or prd_uid
    prd_text, _ = pah.resolve_artifact_text(root, prd_rel, unit_id=prd_uid)
    if prd_text is None:
        return {"verdict": "fail", "error": f"PRD not found: {prd_rel}"}
    fm, body = split_frontmatter(prd_text)
    fm["brainstorm"] = bs_rel
    fm.pop("source_brainstorm", None)
    updated = join_frontmatter(fm, body)
    put = pah.put_artifact_text(root, prd_uid or pah.default_unit_id_from_body_path(prd_rel), prd_rel, updated)
    if put.get("verdict") != "ok":
        return {"verdict": "fail", "error": "failed to persist PRD back-reference", **put}
    return {"verdict": "pass", "action": "write-backref", "prd": prd_rel, "brainstorm": bs_rel, "backend": put.get("backend")}


def write_forwardref(
    root: Path,
    brainstorm: str,
    prd: str,
    *,
    brainstorm_unit_id: str | None = None,
    prd_unit_id: str | None = None,
) -> dict[str, Any]:
    bs_rel, bs_uid = normalize_body_ref(root, brainstorm)
    prd_rel, prd_uid = normalize_body_ref(root, prd)
    bs_uid = brainstorm_unit_id or bs_uid
    prd_uid = prd_unit_id or prd_uid
    bs_text, _ = pah.resolve_artifact_text(root, bs_rel, unit_id=bs_uid)
    if bs_text is None:
        return {"verdict": "fail", "error": f"brainstorm not found: {bs_rel}"}
    fm, body = split_frontmatter(bs_text)
    if is_truthy_frozen(fm):
        return {
            "verdict": "pass",
            "action": "write-forwardref",
            "skipped": True,
            "reason": "brainstorm frozen — PRD back-reference is authoritative",
        }
    existing = prd_forward_refs(fm)
    if prd_rel not in existing:
        existing.append(prd_rel)
    if len(existing) == 1:
        fm["prd"] = existing[0]
    else:
        fm["prd"] = "[" + ", ".join(existing) + "]"
    updated = join_frontmatter(fm, body)
    put = pah.put_artifact_text(root, bs_uid or pah.default_unit_id_from_body_path(bs_rel), bs_rel, updated)
    if put.get("verdict") != "ok":
        return {"verdict": "fail", "error": "failed to persist brainstorm forward-reference", **put}
    return {
        "verdict": "pass",
        "action": "write-forwardref",
        "brainstorm": bs_rel,
        "prd": prd_rel,
        "backend": put.get("backend"),
    }


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        emit({"verdict": "fail", "error": "usage: doc_link.py check|write-backref|write-forwardref ..."}, EXIT_ERROR)

    cmd = args[0]
    root = repo_root()

    def kv(flag: str) -> str | None:
        if flag in args:
            i = args.index(flag)
            return args[i + 1] if i + 1 < len(args) else None
        return None

    if cmd == "check":
        path_s = kv("--path")
        if not path_s:
            emit({"verdict": "fail", "error": "--path required"}, EXIT_ERROR)
        root_override = kv("--root")
        if root_override:
            root = Path(root_override).resolve()
        unit_id = kv("--unit-id")
        tier = kv("--tier")
        result = check_artifact(root, path_s, tier, unit_id=unit_id)
        code = EXIT_PASS if result.get("verdict") == "pass" else EXIT_FAIL
        emit(result, code)

    if cmd == "write-backref":
        bs = kv("--brainstorm")
        prd = kv("--prd")
        if not bs or not prd:
            emit({"verdict": "fail", "error": "--brainstorm and --prd required"}, EXIT_ERROR)
        root_override = kv("--root")
        if root_override:
            root = Path(root_override).resolve()
        emit(
            write_backref(
                root,
                bs,
                prd,
                brainstorm_unit_id=kv("--brainstorm-unit-id"),
                prd_unit_id=kv("--prd-unit-id"),
            )
        )

    if cmd == "write-forwardref":
        bs = kv("--brainstorm")
        prd = kv("--prd")
        if not bs or not prd:
            emit({"verdict": "fail", "error": "--brainstorm and --prd required"}, EXIT_ERROR)
        root_override = kv("--root")
        if root_override:
            root = Path(root_override).resolve()
        emit(
            write_forwardref(
                root,
                bs,
                prd,
                brainstorm_unit_id=kv("--brainstorm-unit-id"),
                prd_unit_id=kv("--prd-unit-id"),
            )
        )

    emit({"verdict": "fail", "error": f"unknown command: {cmd}"}, EXIT_ERROR)


if __name__ == "__main__":
    main()
