"""Shared deliver unit-test fixtures."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest

_SAFE_CWD = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _restore_cwd_after_deliver_finalize_tests() -> Generator[None, None, None]:
    """Guard against finalize_run primary rebind leaving cwd on torn-down tmp repos."""
    yield
    try:
        os.chdir(_SAFE_CWD)
    except OSError:
        pass
