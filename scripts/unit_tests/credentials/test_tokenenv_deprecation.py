"""tokenEnv deprecation-path tests (PRD 080 17.5 / R1)."""

from __future__ import annotations

import pytest

from credentials.config_surface import (
    ALIAS_NOTICE,
    IMPLICIT_DEFAULT_TABLE_TARGETS,
    CutoverError,
    DeprecationPhase,
    ConfigSurfaceError,
    assert_implicit_default_tables_absent_at_cutover,
    present_implicit_default_tables,
    resolve_config_surface,
)


class TestTokenEnvOnlyAlias:
    def test_token_variable_only_resolves_via_alias_notice_once(self) -> None:
        result = resolve_config_surface(
            {
                "projectId": "acme-demo",
                "host": {"tokenEnv": "GITHUB_TOKEN"},
                "planning": {"store": {"issues": {"tokenEnv": "SW_PLANNING_ISSUES_TOKEN"}}},
                "memory": {"tokenEnv": "BASIC_MEMORY_API_KEY"},
            }
        )
        assert result.host.source == "tokenEnv-alias"
        assert result.host.token_env == "GITHUB_TOKEN"
        assert result.planning.source == "tokenEnv-alias"
        assert result.memory.source == "tokenEnv-alias"
        assert result.notices == (ALIAS_NOTICE,)
        assert len(result.notices) == 1


class TestCredentialRefWins:
    def test_combination_warns_and_credential_ref_wins(self) -> None:
        with pytest.warns(DeprecationWarning, match="credentialRef wins"):
            result = resolve_config_surface(
                {
                    "projectId": "acme-demo",
                    "host": {
                        "credentialRef": "github-work",
                        "tokenEnv": "GITHUB_TOKEN",
                    },
                },
                deprecation_phase=DeprecationPhase.DEPRECATION,
            )
        assert result.host.source == "credentialRef"
        assert result.host.credential_ref == "github-work"
        assert result.host.token_env == "GITHUB_TOKEN"
        assert any("credentialRef wins" in item for item in result.warnings)


class TestCombinationErrorsAtCutover:
    def test_combination_errors_after_cutover(self) -> None:
        with pytest.raises(ConfigSurfaceError) as exc:
            resolve_config_surface(
                {
                    "projectId": "acme-demo",
                    "host": {
                        "credentialRef": "github-work",
                        "tokenEnv": "GITHUB_TOKEN",
                    },
                },
                deprecation_phase=DeprecationPhase.CUTOVER,
            )
        assert exc.value.code == "tokenenv-cutover-combination"

    def test_token_env_only_errors_at_cutover(self) -> None:
        with pytest.raises(ConfigSurfaceError) as exc:
            resolve_config_surface(
                {
                    "projectId": "acme-demo",
                    "host": {"tokenEnv": "GITHUB_TOKEN"},
                },
                deprecation_phase=DeprecationPhase.CUTOVER,
            )
        assert exc.value.code == "tokenenv-cutover-alias"


class TestImplicitDefaultTablesAtCutover:
    def test_named_targets_are_exactly_three(self) -> None:
        assert len(IMPLICIT_DEFAULT_TABLE_TARGETS) == 3
        assert IMPLICIT_DEFAULT_TABLE_TARGETS == (
            "host_lib.DEFAULT_TOKEN_ENV",
            "planning_store.DEFAULT_ISSUES_TOKEN_ENV",
            "closeout_ci.hardcoded_token_env_defaults",
        )

    def test_cutover_asserts_tables_absent(self) -> None:
        present = present_implicit_default_tables()
        if not present:
            # Tables already removed on this branch — cutover acceptance is a no-op.
            assert_implicit_default_tables_absent_at_cutover(
                deprecation_phase=DeprecationPhase.CUTOVER
            )
            return
        # During the deprecation release the tables are still present — cutover must fail closed.
        assert set(IMPLICIT_DEFAULT_TABLE_TARGETS).issubset(set(present))
        with pytest.raises(CutoverError) as exc:
            assert_implicit_default_tables_absent_at_cutover(
                deprecation_phase=DeprecationPhase.CUTOVER
            )
        assert exc.value.code == "implicit-default-tables-present"

    def test_deprecation_phase_skips_cutover_assert(self) -> None:
        assert_implicit_default_tables_absent_at_cutover(
            deprecation_phase=DeprecationPhase.DEPRECATION
        )
