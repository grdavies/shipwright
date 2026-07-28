"""Reserved-prefix fixture corpora for hermetic memory-eval (PRD 082 R33)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Fixture memory ids use this prefix so real reads never retrieve or persist them.
RESERVED_PREFIX = "sw-eval-fixture-"

CORPUS_KINDS = frozenset({"relevant", "stale", "contradictory", "foreign_project"})


@dataclass(frozen=True)
class MemoryFixture:
    memory_id: str
    corpus: str
    project_id: str
    content: str
    decision_hint: str
    stale: bool = False
    contradictory: bool = False


def fixture_id(corpus: str, suffix: str) -> str:
    if corpus not in CORPUS_KINDS:
        raise ValueError(f"unknown corpus: {corpus}")
    return f"{RESERVED_PREFIX}{corpus}-{suffix}"


def is_reserved_id(memory_id: str) -> bool:
    return str(memory_id or "").startswith(RESERVED_PREFIX)


def exclude_reserved_ids(memory_ids: list[str]) -> list[str]:
    """Drop reserved-prefix ids from a real-read result set."""
    return [mid for mid in memory_ids if not is_reserved_id(mid)]


def assert_reserved_id(memory_id: str) -> None:
    if not is_reserved_id(memory_id):
        raise ValueError(f"fixture id must use reserved prefix {RESERVED_PREFIX!r}: {memory_id}")


def build_corpus(corpus: str, *, project_id: str = "eval-project") -> list[MemoryFixture]:
    if corpus not in CORPUS_KINDS:
        raise ValueError(f"unknown corpus: {corpus}")

    if corpus == "relevant":
        return [
            MemoryFixture(
                fixture_id(corpus, "decision-a"),
                corpus,
                project_id,
                "Prefer transactional writes for planning store mutations.",
                decision_hint="use-transaction-coordinator",
            ),
            MemoryFixture(
                fixture_id(corpus, "decision-b"),
                corpus,
                project_id,
                "Authority resolver must not substitute backends.",
                decision_hint="no-backend-substitution",
            ),
        ]
    if corpus == "stale":
        return [
            MemoryFixture(
                fixture_id(corpus, "old-guidance"),
                corpus,
                project_id,
                "Legacy: write directly to planning_store without a lock.",
                decision_hint="direct-write",
                stale=True,
            ),
        ]
    if corpus == "contradictory":
        return [
            MemoryFixture(
                fixture_id(corpus, "claim-a"),
                corpus,
                project_id,
                "All planning writes are read-only when authority is blocked.",
                decision_hint="read-only-when-blocked",
            ),
            MemoryFixture(
                fixture_id(corpus, "claim-b"),
                corpus,
                project_id,
                "Planning writes proceed even when authority is blocked.",
                decision_hint="write-when-blocked",
                contradictory=True,
            ),
        ]
    # foreign_project
    return [
        MemoryFixture(
            fixture_id(corpus, "foreign-secret"),
            corpus,
            "foreign-project-alpha",
            "Foreign repo secret: rotate credentials weekly.",
            decision_hint="rotate-credentials",
        ),
    ]


def all_corpora(*, project_id: str = "eval-project") -> dict[str, list[MemoryFixture]]:
    return {kind: build_corpus(kind, project_id=project_id) for kind in sorted(CORPUS_KINDS)}


def fixture_records(corpus: str, *, project_id: str = "eval-project") -> list[dict[str, Any]]:
    return [
        {
            "id": item.memory_id,
            "corpus": item.corpus,
            "projectId": item.project_id,
            "content": item.content,
            "decisionHint": item.decision_hint,
            "stale": item.stale,
            "contradictory": item.contradictory,
        }
        for item in build_corpus(corpus, project_id=project_id)
    ]
