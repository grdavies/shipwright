#!/usr/bin/env python3
"""Conformance probe — direct IssuesClient import must fail facade lint (PRD 061 R2a)."""

from __future__ import annotations

from issues_lib import IssuesClient  # noqa: F401 — intentional bypass probe
