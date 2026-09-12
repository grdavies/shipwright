"""Planning store backend adapters (PRD 082 phase 12 / R27)."""
from __future__ import annotations

from .in_repo import InRepoPublicBackend
from .issues import IssueStoreBackend
from .issues_helpers import (
    ISSUE_STORE_TXN_ID,
    ISSUE_UNIT_INDEX,
    ISSUE_UNIT_INDEX_AUDIT,
    PUT_JOURNAL_PATH,
    append_unit_index_audit,
    issue_index_key,
    load_issue_unit_index,
    load_put_journal,
    mutate_issue_unit_index,
    mutate_put_journal,
    read_issue_unit_index_locked,
    read_put_journal_locked,
    save_issue_unit_index,
    save_put_journal,
    self_heal_issue_unit_index,
)
from .gitlab import (
    BACKEND_ID as GITLAB_PLANNING_STORE_BACKEND_ID,
    GitlabPlanningStoreStubBackend,
    conformance_metadata_only as gitlab_planning_store_conformance_metadata,
    gitlab_planning_store_parity_gate,
    register_gitlab_planning_store_stub,
)
from .local_synced import LocalSyncedBackend
from .memory_cache import ReplicatedPlanningCacheBackend

__all__ = [
    "ISSUE_STORE_TXN_ID",
    "ISSUE_UNIT_INDEX",
    "ISSUE_UNIT_INDEX_AUDIT",
    "append_unit_index_audit",
    "GITLAB_PLANNING_STORE_BACKEND_ID",
    "GitlabPlanningStoreStubBackend",
    "InRepoPublicBackend",
    "IssueStoreBackend",
    "LocalSyncedBackend",
    "gitlab_planning_store_conformance_metadata",
    "gitlab_planning_store_parity_gate",
    "register_gitlab_planning_store_stub",
    "ReplicatedPlanningCacheBackend",
    "PUT_JOURNAL_PATH",
    "issue_index_key",
    "load_issue_unit_index",
    "load_put_journal",
    "mutate_issue_unit_index",
    "mutate_put_journal",
    "read_issue_unit_index_locked",
    "read_put_journal_locked",
    "save_issue_unit_index",
    "save_put_journal",
    "self_heal_issue_unit_index",
]
