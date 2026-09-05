"""Kernel freshness bands: conversion and classification, no I/O."""
from __future__ import annotations

from cbc.core import freshness as core
from cbc.services.freshness import DEFAULTS, from_document


def test_days_from_months_matches_the_published_defaults() -> None:
    assert core.days_from_months(24) == 730
    assert core.days_from_months(30) == 913
    assert core.FRESH_DAYS == 730
    assert core.DISCARD_AFTER_DAYS == 913
    assert core.CATALOG_STALE_DAYS == core.FRESH_DAYS


def test_classify_default_bands() -> None:
    assert core.classify(700)["status"] == "fresh"
    assert core.classify(800)["status"] == "unreliable"
    assert core.classify(1000)["status"] == "stale"
    assert core.classify(-1)["status"] == "future_dated"


def test_from_document_falls_back_when_the_row_is_broken() -> None:
    assert from_document(None) == DEFAULTS
    assert from_document({"catalogStaleMonths": "nope"}) == DEFAULTS
    assert from_document({"catalogStaleMonths": 24, "discardAfterMonths": 12}) == DEFAULTS


def test_from_document_accepts_admin_months() -> None:
    bands = from_document({"catalogStaleMonths": 6, "discardAfterMonths": 12})
    assert bands.catalog_stale_days == core.days_from_months(6)
    assert bands.discard_after_days == core.days_from_months(12)
    assert "6 months" in bands.rule
