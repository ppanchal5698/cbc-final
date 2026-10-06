"""The confidence below which a match is flagged for an estimator, never auto-accepted.

NFR-2: every matched line carries a confidence, and below this floor it is
flagged for review. That one number decides whether
quoting's matching rules auto-match, whether catalog's match cache keeps a
decision, whether extraction flags a row and an opening, and how the review
summary colours a line. It is written here and nowhere else;
tests/architecture/test_confidence_floor.py fails on a second copy, and holds the
web app's line-item row - which cannot import it - to the same value.
"""
from __future__ import annotations

CONFIDENCE_FLOOR = 0.75

# Requirements 7.1: at or above this a match is proposed as it stands; between the
# floor and this it is proposed with its close matches beside it; below the floor
# it is the estimator's to price.
AUTO_PROPOSE = 0.90


def band(confidence: float | None) -> str | None:
    """`auto`, `review` or `manual` for a match's confidence - None when the line
    was not matched to a row at all."""
    if confidence is None:
        return None
    if confidence >= AUTO_PROPOSE:
        return "auto"
    return "review" if confidence >= CONFIDENCE_FLOOR else "manual"
