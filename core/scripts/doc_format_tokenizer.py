#!/usr/bin/env python3
"""Shared doc-format tokenizer regex surface for spec-rigor and traceability (PRD 035 A2 R55–R56)."""
from __future__ import annotations

import doc_format

TOKENIZER_VERSION = doc_format.TOKENIZER_VERSION
RID_BULLET = doc_format.RID_BULLET
RID_BULLET_ALT = doc_format.RID_BULLET_ALT
RID_BULLET_NONCANON = doc_format.RID_BULLET_NONCANON
TRACE_ROW = doc_format.TRACE_ROW
PHASE_DEP_ROW = doc_format.PHASE_DEP_ROW
tokenize = doc_format.tokenize
extract_rd_bullets = doc_format.extract_rd_bullets
extract_traceability_rows = doc_format.extract_traceability_rows
parse_frontmatter_directives = doc_format.parse_frontmatter_directives
normalize_file_path = doc_format.normalize_file_path
