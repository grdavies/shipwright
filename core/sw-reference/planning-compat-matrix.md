# Planning compatibility matrix (PRD 082 phase 15 / R27)

Published matrix of `planning_store` shim symbols and package CLI surface by
implementation phase. Rows are validated against
`core/sw-reference/planning-import-inventory.json` via
`python3 scripts/planning_boundary_lint.py --validate-matrix --check`.

## Compat-removal condition

Shim removal is permitted only when **all** of the following hold for one full
release after the last supported-through version:

1. `planning_import_inventory.py compat-removal-probe` reports `removable: true`
   (zero inventoried imports across enforced trees).
2. Regenerated distributions (`dist/cursor`, `dist/claude-code`) contain no
   stale shim mirrors.
3. Recorded shim module-size exemptions expire with this milestone.

Inventory snapshot: 2026-07-29T08:03:47Z — 154 symbols,
38 CLI subcommands, 33 CLI flags.

## Symbol surface

| Surface kind | Surface | Introduced phase | Supported through | Removal condition | Notes |
| --- | --- | --- | --- | --- | --- |
| symbol | `BITBUCKET_ISSUE_STORE_GUIDANCE` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `DEFAULT_BACKEND` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `DEFAULT_ISSUES_TOKEN_ENV` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `DEFERRED_ISSUES_PROVIDERS` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `FACADE_BYPASS_BASELINE` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `FILE_BACKED_STORE_TXN_ID` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `ISSUES_PROVIDERS` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `InRepoPublicBackend` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `IssueStoreBackend` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `KILL_SWITCH_ENV` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `KILL_SWITCH_NOTICE` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `LocalSyncedBackend` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `MATERIALIZE_MISSING_FROZEN_BODY` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `MemoryLocalCacheBackend` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `PROJECT_KEY_PATTERN` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `PUT_INCOMPLETE_LABEL` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `R1_BROWSE_CONTRACT` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `SHIPPED_ISSUES_PROVIDERS` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `SemanticStatusError` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `StoreResult` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_ISSUES_PROVIDER_TO_BROKER` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_contains_raw_transcript` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_default_body_path` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_fail` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_gap_closure_evidence` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_github_scope_probe` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_is_allowed_recallium_base` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_issues_destination_endpoint` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_lookup_issue_record` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_parse_absorbs_targets` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_prd_number_from_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_prd_unit_id_alias_candidates` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_redact_content` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_slug_from_prd_unit` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_store_section` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_tasks_unit_id_candidates` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `_urlopen` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `apply_initiative_capability` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assert_cycle_orthogonal_to_milestone` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assert_flat_comment_provider_non_regression` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assert_portable_graph_authority` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assert_projection_mirrors_not_freeze_authority` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assert_r1_answerability_from_metadata` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assert_r1_answerability_while_clean` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `assign_issue_to_cycle` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `audit_closure_completeness` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `authority_io_block` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `backfill_frontmatter_hybrid` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `check_canonical_projection_split_brain` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `check_projection_drift` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `close_delivery_units` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `close_done_phase_sub_issues` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `close_parent_epic_if_complete` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `comment_sync` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `comments_relations_schema_contract` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `contains_raw_transcript` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `content_hash` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `cycle_sharing_notice` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `discover_absorbed_units_anchored` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `doctor_absorb_linkage_066` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `doctor_absorb_pollution` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `doctor_issues_provider_stub` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `doctor_separate_project_local_writes` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `dual_write_body_policy` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `dual_write_projection_mirror` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `encode_planning_edge` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `evaluate_freeze_gate` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `fail` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `format_native_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `freeze_from_canonical_body` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `gap_has_absorb_provenance` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `gate_prd_060_r1_r7` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `get` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `get_backend` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `git_root` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `is_bare_integer_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `is_namespaced_native_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_comments_relations_facade` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_get_facade` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_index_key` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_search_by_unit_facade` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_store_fallback_reason` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_store_private_enough` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_store_visibility_allowed` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issue_store_visibility_gate` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issues_provider_registration_footprint` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `issues_section` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `linear_entity_mapping` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `linear_projection_schema_contract` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `lint_facade_imports` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `lint_projection_mutations` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `load_issue_unit_index` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `load_projection_ledger` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `load_put_journal` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `load_workflow_config` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `materialize_from_store` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `materialize_with_resync` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `migrate_orphan_phase_issues` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `mutate_issue_unit_index` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `normalize_semantic_status` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `normalize_task_ref` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `operator_projection_adapter_complete_claim` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `operator_projection_capability_matrix` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `operator_projection_contract` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `override_path` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `parse_planning_issues_refs` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `parse_visibility_from_content` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `planning_section` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `probe_initiative_availability` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `probe_issues_token` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `probe_store_host_privacy` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `progress_update` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `project_graph_to_linear_layout` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `projection_is_dirty` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `projection_ledger_discover_by_marker` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `projection_ledger_lookup` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `projection_ledger_reconcile_duplicates` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `projection_ledger_upsert` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `ps` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `put` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `py` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `read_issue_unit_index_locked` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `rebuild_projection_from_graph` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `reconcile_ledger_task_refs` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `redact_content` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `refuse_banned_living_doc_write` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `register_legacy_unit_mapping` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `reject_bare_integer_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_absorbed_gaps_061` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_backend_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_canonical_freeze_body` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_delivery_linked_units` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_effective_backend` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_issues_credential` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_issues_provider` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_issues_token_env` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_legacy_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_planning_issue_ref_to_gap` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_store_location` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resolve_task_ref_aliases` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `resume_projection_from_checkpoint` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `reverse_resolve_legacy_unit_id` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `save_issue_unit_index` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `save_legacy_unit_map` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `secret_scan_text` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `serialize_comments_relations_facade` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `set_projection_dirty` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `store_section` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `token_present` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `validate_project_key` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `verify_absorb_linkage_066` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `wave_regression_finding` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |
| symbol | `write_back_gap_prereqs_061` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | shim re-export |

## CLI surface

| Surface kind | Surface | Introduced phase | Supported through | Removal condition | Notes |
| --- | --- | --- | --- | --- | --- |
| cli-subcommand | `bitbucket-issue-store-guidance` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `canonical-hash` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `cleanup` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `clear-issue-fixture` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `close-delivery-units` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `comments-relations-schema` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `doctor` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `exists` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `freeze` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `get` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `issues-provider-registration` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `linear-projection-schema` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `link-brainstorm-prd` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `lint-facade-imports` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `lint-projection-mutations` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `list-backends` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `list-facade` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `mark-issue-tombstone` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `mark-issue-transferred` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `materialize` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `materialize-from-store` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `migrate-orphan-phase-issues` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `operator-projection-contract` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `probe-issues-token` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `probe-jira-init` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `probe-projection` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `progress-update` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `projection-refresh` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `put` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `resolve-absorbed-gaps-061` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `resolve-backend` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `resolve-issues` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `resolve-store-location` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `validate-local-synced` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `validate-project-key` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `verify-absorb-linkage-066` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `verify-frozen-hash` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-subcommand | `write-back-gap-prereqs` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI |
| cli-flag | `--action` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--allowlist` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--apply` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--backend` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--body-path` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--brainstorm-unit` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--checked-phase-ids` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--content` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--content-class` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--dest` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--dry-run` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--fixture` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--force` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--gap-unit-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--issue-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--no-distill` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--parent-issue-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--path` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--phase-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--planning-issue` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--prd-unit` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--prd-unit-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--project-key` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--provider` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--register` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--resync` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--root` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--task-list` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--task-ref` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--tasks-unit-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--unit-id` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--units-file` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |
| cli-flag | `--units-json` | 14 | compat-removal | zero-inventoried-imports-across-enforced-trees | package CLI flag |

## Shim exemptions

| Surface kind | Surface | Introduced phase | Supported through | Removal condition | Notes |
| --- | --- | --- | --- | --- | --- |
| shim | `scripts/planning_store.py` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | generated; module-size exempt |
| shim | `core/scripts/planning_store.py` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | core mirror |
| shim | `dist/cursor/scripts/planning_store.py` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | cursor dist mirror |
| shim | `dist/claude-code/scripts/planning_store.py` | 10 | compat-removal | zero-inventoried-imports-across-enforced-trees | claude-code dist mirror |
| condition | `compat-removal-milestone` | 15 | compat-removal | zero-inventoried-imports-across-enforced-trees | measurable removal gate |
