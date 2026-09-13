"""The confidence below which a match is flagged for an estimator, never auto-accepted.

`.claude/rules/accuracy-trust.md` (NFR-2): every matched line carries a confidence,
and below 0.75 it is flagged for review. That one number decides whether
quoting's matching rules auto-match, whether catalog's match cache keeps a
decision, whether extraction flags a row and an opening, and how the review
summary colours a line. It is written here and nowhere else;
tests/architecture/test_confidence_floor.py fails on a second copy, and holds the
web app's line-item row - which cannot import it - to the same value.
"""
from __future__ import annotations

CONFIDENCE_FLOOR = 0.75
