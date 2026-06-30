"""PR list/view field parity shapes (PRD 042 R19)."""

from __future__ import annotations

from typing import Any

PR_VIEW_FIELDS: tuple[str, ...] = (
    "number",
    "url",
    "headRefName",
    "headRefOid",
    "baseRefName",
    "state",
    "isDraft",
    "mergeable",
    "mergeStateStatus",
    "title",
    "body",
    "mergedAt",
    "mergeCommit",
)


def _github_state(pr: dict[str, Any]) -> str:
    if pr.get("merged") or pr.get("merged_at"):
        return "MERGED"
    return str(pr.get("state") or "").upper()


def _github_mergeable(pr: dict[str, Any]) -> str:
    mergeable = pr.get("mergeable")
    if mergeable is False:
        return "CONFLICTING"
    if mergeable is True:
        return "MERGEABLE"
    return "UNKNOWN"


def github_pr_to_view(pr: dict[str, Any]) -> dict[str, Any]:
    """Map a GitHub REST pull object to the canonical pr-view shape."""
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    merge_sha = pr.get("merge_commit_sha")
    merge_state = pr.get("mergeable_state")
    return {
        "number": pr.get("number"),
        "url": pr.get("html_url"),
        "headRefName": head.get("ref"),
        "headRefOid": head.get("sha"),
        "baseRefName": base.get("ref"),
        "state": _github_state(pr),
        "isDraft": bool(pr.get("draft", False)),
        "mergeable": _github_mergeable(pr),
        "mergeStateStatus": str(merge_state or "UNKNOWN").upper() if merge_state else "UNKNOWN",
        "title": pr.get("title"),
        "body": pr.get("body"),
        "mergedAt": pr.get("merged_at"),
        "mergeCommit": {"oid": merge_sha} if merge_sha else None,
    }


def github_pr_to_list_entry(pr: dict[str, Any]) -> dict[str, Any]:
    """pr-list entries use the full pr-view field set (R19)."""
    return github_pr_to_view(pr)


def gitlab_mr_to_view(mr: dict[str, Any]) -> dict[str, Any]:
    """Map a GitLab merge request to the canonical pr-view shape."""
    state = str(mr.get("state") or "").lower()
    if mr.get("merged_at"):
        state = "merged"
    merge_status = str(mr.get("merge_status") or "unknown").lower()
    if merge_status == "can_be_merged":
        mergeable = "MERGEABLE"
    elif merge_status == "cannot_be_merged":
        mergeable = "CONFLICTING"
    else:
        mergeable = "UNKNOWN"
    diff_refs = mr.get("diff_refs") or {}
    merge_sha = mr.get("merge_commit_sha")
    return {
        "number": mr.get("iid") or mr.get("id"),
        "url": mr.get("web_url"),
        "headRefName": mr.get("source_branch"),
        "headRefOid": mr.get("sha") or diff_refs.get("head_sha"),
        "baseRefName": mr.get("target_branch"),
        "state": state.upper(),
        "isDraft": bool(mr.get("draft") or mr.get("work_in_progress")),
        "mergeable": mergeable,
        "mergeStateStatus": merge_status.upper(),
        "title": mr.get("title"),
        "body": mr.get("description"),
        "mergedAt": mr.get("merged_at"),
        "mergeCommit": {"oid": merge_sha} if merge_sha else None,
    }


def gitlab_mr_to_list_entry(mr: dict[str, Any]) -> dict[str, Any]:
    return gitlab_mr_to_view(mr)


def bitbucket_pr_to_view(pr: dict[str, Any]) -> dict[str, Any]:
    """Map a Bitbucket pull request to the canonical pr-view shape."""
    state = str(pr.get("state") or "").upper()
    src = pr.get("source") or {}
    dst = pr.get("destination") or {}
    src_branch = (src.get("branch") or {}).get("name")
    dst_branch = (dst.get("branch") or {}).get("name")
    head_sha = (src.get("commit") or {}).get("hash")
    url = ((pr.get("links") or {}).get("html") or {}).get("href")
    return {
        "number": pr.get("id"),
        "url": url,
        "headRefName": src_branch,
        "headRefOid": head_sha,
        "baseRefName": dst_branch,
        "state": state,
        "isDraft": False,
        "mergeable": "UNKNOWN",
        "mergeStateStatus": "UNKNOWN",
        "title": pr.get("title"),
        "body": pr.get("description"),
        "mergedAt": pr.get("closed_on") if state == "MERGED" else None,
        "mergeCommit": None,
    }


def bitbucket_pr_to_list_entry(pr: dict[str, Any]) -> dict[str, Any]:
    return bitbucket_pr_to_view(pr)


def list_entry_matches_view_fields(entry: dict[str, Any]) -> bool:
    """Return True when *entry* contains every canonical pr-view field."""
    return all(key in entry for key in PR_VIEW_FIELDS)


def parity_keys(list_item: dict[str, Any], view_item: dict[str, Any]) -> list[str]:
    """Return field names present in view but missing from a list item."""
    return [key for key in PR_VIEW_FIELDS if key not in list_item]
