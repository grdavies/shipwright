"""Doc-review provider conformance suite (fixture + GitHub enablement)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from issues_lib import FixtureIssuesStore, IssuesClient, get_fixture_store, use_fixture_mode


def _dimension_ok(dimension: str, **extra):
    payload = {"verdict": "ok", "dimension": dimension}
    payload.update(extra)
    return payload


def _dimension_fail(dimension: str, error: str, **extra):
    payload = {"verdict": "fail", "dimension": dimension, "error": error}
    payload.update(extra)
    return payload

DOC_REVIEW_CONFORMANCE_DIMENSIONS: tuple[str, ...] = (
    "post-then-open",
    "drift",
    "body-drift",
    "occ",
    "completion-receipt",
    "hash-isolation",
)

DOC_REVIEW_ENABLED_PROVIDERS: frozenset[str] = frozenset({"github-issues"})


def _doc_review_cfg(provider: str = "github-issues") -> dict[str, Any]:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": provider,
                "projectKey": "doc-review-conf",
            }
        },
        "host": {"provider": "github"},
    }


def _doc_review_sample_payload(persona: str = "coherence") -> dict[str, Any]:
    return {
        "reviewer": persona,
        "findings": [
            {
                "title": "Example finding",
                "severity": "P2",
                "section": "Requirements",
                "why_it_matters": "Clarity",
                "finding_type": "omission",
                "autofix_class": "manual",
                "suggested_fix": "Clarify requirement",
                "confidence": 75,
                "evidence": ["ambiguous wording"],
            }
        ],
        "residual_risks": [],
        "deferred_questions": [],
    }


def _seed_doc_review_issue(store: FixtureIssuesStore, *, unit_id: str, issue_id: str = "887") -> None:
    record = store.create(
        title=f"PRD {unit_id}",
        body=f"<!-- sw-unit-id: {unit_id} -->\n# PRD\n",
        labels=["sw:prd", "sw:project:doc-review-conf"],
        project_key="doc-review-conf",
        artifact_type="prd",
        unit_id=unit_id,
    )
    store._issues[str(issue_id)] = record
    store._persist()


def run_doc_review_conformance_suite(provider: str, root: Path) -> dict[str, Any]:
    """Fixture/GitHub doc-review open/verify/complete suite (PRD 341 R30)."""
    if provider not in DOC_REVIEW_ENABLED_PROVIDERS:
        dims = {
            name: _dimension_ok(name, posture="disabled", reason="doc-review-provider-unsupported")
            for name in DOC_REVIEW_CONFORMANCE_DIMENSIONS
        }
        return {
            "verdict": "ok",
            "provider": provider,
            "action": "doc-review-conformance-suite",
            "posture": "disabled",
            "dimensions": dims,
            "failedDimensions": [],
        }
    if not use_fixture_mode():
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "fixture-mode-required",
            "message": "SW_ISSUES_FIXTURE=1 required for hermetic doc-review conformance",
        }

    from credentials.model import CredentialRef, Principal, Resolution, ResolvedToken, Secret
    from planning_doc_review_transport import (
        parse_review_round_block,
        strip_review_round_blocks,
        stripped_artifact_hash,
    )
    from planning_store_facade import (
        complete_review_round,
        open_review_manifest,
        post_review_finding,
        read_review_manifest,
        resolve_issues_credential,
        verify_review_manifest,
    )
    import planning_store_facade as psf

    store = get_fixture_store(root)
    store.clear()
    unit_id = "341-prd-doc-review-conformance"
    issue_id = "887"
    _seed_doc_review_issue(store, unit_id=unit_id, issue_id=issue_id)
    cfg = _doc_review_cfg(provider)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(cfg), encoding="utf-8"
    )

    resolved = Resolution.resolved(
        CredentialRef("fixture-doc-review"),
        ResolvedToken(Secret("fixture-token"), Principal(profile="fixture", account="fixture-bot")),
    )
    original = getattr(psf, "resolve_issues_credential", None)
    psf.resolve_issues_credential = lambda *a, **k: resolved  # type: ignore[assignment]

    results: dict[str, Any] = {}
    try:
        # post-then-open
        posted = post_review_finding(
            root,
            cfg,
            issue_id=issue_id,
            unit_id=unit_id,
            round_id="conf-round-1",
            persona="coherence",
            payload=_doc_review_sample_payload("coherence"),
        )
        if posted.get("verdict") != "ok":
            results["post-then-open"] = _dimension_fail("post-then-open", "post-failed", detail=posted)
        else:
            opened = open_review_manifest(
                root,
                cfg,
                issue_id=issue_id,
                unit_id=unit_id,
                round_id="conf-round-1",
                ordered_comment_ids=[str(posted["commentId"])],
            )
            if opened.get("verdict") != "ok" or opened.get("status") != "open":
                results["post-then-open"] = _dimension_fail("post-then-open", "open-failed", detail=opened)
            else:
                results["post-then-open"] = _dimension_ok(
                    "post-then-open", pins=len(opened.get("pins") or [])
                )

        # hash-isolation / body-drift baseline from open body
        record = get_fixture_store(root).get(issue_id)
        body = record.body if record else ""
        hashed = stripped_artifact_hash(body)
        stripped = strip_review_round_blocks(body)
        if "sw-doc-review-round" not in body or "sw-doc-review-round" in stripped:
            results["hash-isolation"] = _dimension_fail(
                "hash-isolation", "witness-strip-contract-broken"
            )
        elif not str(hashed).startswith("body-sha256/v1:"):
            results["hash-isolation"] = _dimension_fail("hash-isolation", "hash-prefix")
        else:
            results["hash-isolation"] = _dimension_ok("hash-isolation", artifactHash=hashed)

        # OCC — stale if_match must refuse on issue update
        from issues_lib import IssueRevisionConflict

        rec = get_fixture_store(root).get(issue_id)
        try:
            client = IssuesClient(root, provider)
            client.issue_update(
                issue_id,
                body=(rec.body if rec else "") + "\n",
                if_match="stale-etag-conf",
            )
            results["occ"] = _dimension_fail("occ", "stale-etag-accepted")
        except IssueRevisionConflict:
            results["occ"] = _dimension_ok("occ")
        except Exception as exc:  # noqa: BLE001
            if "revision" in type(exc).__name__.lower() or "conflict" in str(exc).lower():
                results["occ"] = _dimension_ok("occ", observed=type(exc).__name__)
            else:
                results["occ"] = _dimension_fail("occ", type(exc).__name__, message=str(exc))

        # drift — mutate pinned comment payload then verify
        read = read_review_manifest(
            root, cfg, issue_id=issue_id, unit_id=unit_id, round_id="conf-round-1"
        )
        if read.get("verdict") != "ok":
            results["drift"] = _dimension_fail("drift", "read-failed", detail=read)
        else:
            comment_id = str(posted.get("commentId") or "")
            store_live = get_fixture_store(root)
            rec = store_live.get(issue_id)
            if rec and comment_id:
                for c in rec.comments:
                    if str(getattr(c, "id", "")) == comment_id:
                        c.body = (c.body or "") + "\n<!-- tamper -->\n"
                        break
                store_live._issues[str(issue_id)] = rec
                store_live._persist()
            verified = verify_review_manifest(
                root, cfg, issue_id=issue_id, unit_id=unit_id, round_id="conf-round-1"
            )
            if verified.get("verdict") == "ok":
                results["drift"] = _dimension_fail("drift", "tamper-not-detected", detail=verified)
            else:
                results["drift"] = _dimension_ok(
                    "drift", refuse=verified.get("error") or verified.get("halt")
                )

        # body-drift — change stripped body bytes under open round
        store_live = get_fixture_store(root)
        store_live.clear()
        _seed_doc_review_issue(store_live, unit_id=unit_id, issue_id=issue_id)
        p2 = post_review_finding(
            root,
            cfg,
            issue_id=issue_id,
            unit_id=unit_id,
            round_id="conf-round-2",
            persona="coherence",
            payload=_doc_review_sample_payload("coherence"),
        )
        if p2.get("verdict") != "ok" or not p2.get("commentId"):
            results["body-drift"] = _dimension_fail("body-drift", "reseed-post-failed", detail=p2)
        else:
            open_review_manifest(
                root,
                cfg,
                issue_id=issue_id,
                unit_id=unit_id,
                round_id="conf-round-2",
                ordered_comment_ids=[str(p2["commentId"])],
            )
            store_live = get_fixture_store(root)
            live = store_live.get(issue_id)
            if live is None:
                results["body-drift"] = _dimension_fail("body-drift", "missing-issue")
            else:
                live.body = (live.body or "") + "\n\n## unexpected body drift\n"
                live.etag = (live.etag or "e") + "-drift"
                store_live._issues[str(issue_id)] = live
                store_live._persist()
                v2 = verify_review_manifest(
                    root, cfg, issue_id=issue_id, unit_id=unit_id, round_id="conf-round-2"
                )
                if v2.get("verdict") == "ok":
                    results["body-drift"] = _dimension_fail(
                        "body-drift", "drift-not-detected", detail=v2
                    )
                else:
                    results["body-drift"] = _dimension_ok(
                        "body-drift", refuse=v2.get("error") or v2.get("halt")
                    )

        # completion-receipt — fresh round then complete
        store_live = get_fixture_store(root)
        store_live.clear()
        _seed_doc_review_issue(store_live, unit_id=unit_id, issue_id=issue_id)
        p3 = post_review_finding(
            root,
            cfg,
            issue_id=issue_id,
            unit_id=unit_id,
            round_id="conf-round-3",
            persona="coherence",
            payload=_doc_review_sample_payload("coherence"),
        )
        if p3.get("verdict") != "ok" or not p3.get("commentId"):
            results["completion-receipt"] = _dimension_fail(
                "completion-receipt", "reseed-post-failed", detail=p3
            )
        else:
            open_review_manifest(
                root,
                cfg,
                issue_id=issue_id,
                unit_id=unit_id,
                round_id="conf-round-3",
                ordered_comment_ids=[str(p3["commentId"])],
            )
            done = complete_review_round(
                root, cfg, issue_id=issue_id, unit_id=unit_id, round_id="conf-round-3"
            )
            if done.get("verdict") != "ok":
                results["completion-receipt"] = _dimension_fail(
                    "completion-receipt", "complete-failed", detail=done
                )
            else:
                receipt = done.get("receipt") or done.get("completionReceipt") or done
                results["completion-receipt"] = _dimension_ok(
                    "completion-receipt",
                    status=done.get("status"),
                    hasReceipt=bool(receipt),
                )
    finally:
        if original is not None:
            psf.resolve_issues_credential = original  # type: ignore[assignment]

    # Ensure all dims present
    for name in DOC_REVIEW_CONFORMANCE_DIMENSIONS:
        results.setdefault(name, _dimension_fail(name, "not-executed"))

    failures = [n for n, e in results.items() if e.get("verdict") != "ok"]
    return {
        "verdict": "ok" if not failures else "fail",
        "provider": provider,
        "action": "doc-review-conformance-suite",
        "posture": "enabled",
        "dimensions": results,
        "failedDimensions": failures,
    }
