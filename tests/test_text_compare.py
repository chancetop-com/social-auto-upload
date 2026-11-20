# -*- coding: utf-8 -*-
"""Shared name comparison: trim, collapse whitespace and casefold."""

from __future__ import annotations

from utils.text_compare import normalize_text


def test_normalize_text_trims_and_collapses_whitespace():
    assert normalize_text("  Shang   Hai \t\n") == "shang hai"


def test_normalize_text_casefolds_non_ascii():
    assert normalize_text("İstanbul") == "i̇stanbul"
    assert normalize_text("人民 公园") == "人民 公园"


def test_normalize_text_keeps_none_distinct_from_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""
    assert normalize_text(" \t\n") == ""
