"""Traceback redaction coverage for Secret wrapper (PRD 080 1.4 / R3)."""

from __future__ import annotations

import traceback

import pytest

from credentials import Secret


_TEST_VALUE = "unit-test-traceback-value-ghijkl"


def _raise_chained_with_wrapped() -> None:
    wrapped = Secret(_TEST_VALUE)
    try:
        raise ValueError(f"inner failure while holding {wrapped!r}")
    except ValueError as inner:
        raise RuntimeError(f"outer failure with {wrapped}") from inner


class TestSecretTracebackRedaction:
    def test_repr_and_str_never_expose_value(self) -> None:
        wrapped = Secret(_TEST_VALUE)
        assert _TEST_VALUE not in repr(wrapped)
        assert _TEST_VALUE not in str(wrapped)
        assert f"{wrapped}" == "<redacted>"

    def test_formatted_traceback_redacts_secret_in_chain(self) -> None:
        try:
            _raise_chained_with_wrapped()
        except RuntimeError:
            formatted = traceback.format_exc()
        assert _TEST_VALUE not in formatted
        assert "<redacted>" in formatted

    def test_many_nested_exceptions_keep_redaction(self) -> None:
        wrapped = Secret(_TEST_VALUE)

        def level_three() -> None:
            raise TypeError(str(wrapped))

        def level_two() -> None:
            try:
                level_three()
            except TypeError as exc:
                raise OSError(repr(wrapped)) from exc

        def level_one() -> None:
            try:
                level_two()
            except OSError as exc:
                raise RuntimeError(f"top-level {wrapped!s}") from exc

        try:
            level_one()
        except RuntimeError:
            formatted = traceback.format_exc()
        assert _TEST_VALUE not in formatted
        assert formatted.count("<redacted>") >= 1
