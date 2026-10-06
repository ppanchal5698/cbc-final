"""A fire rating as a schedule writes it, read as minutes - one reader for the whole app.

Schedules write a rating every way there is: `90`, `90 MIN`, `1-1/2 HR`, `1½ HR`,
`3/4 HR`, `B LABEL`, `NR`. Each place that needed minutes read them its own way,
and the matcher joined every digit it found: `1-1/2 HR` was 112 minutes, so a
90-minute part was refused, and `3 HR` was 3, so a 20-minute part was accepted.

CBC requirements 6.1 [W]: ratings are non-rated, 20, 45, 60, 90 or 180 minutes
(and 120 for 2-hour walls); letter labels A = 3 hr, C = 45 min, and B = 60 or 90 -
which is ambiguous, so it reads as no minutes and says so.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

UNRATED = 0  # a schedule that says the door is not rated - a rating, unlike no answer

_NOT_RATED = re.compile(r"^\s*(?:N\.?R\.?|NON[-\s]?RATED|NOT\s+RATED|NONE|NO|0\s*(?:MIN)?|[-–—]+|N/?A)\s*$", re.I)
_LETTER = re.compile(r"^\s*([ABC])(?:\s*[-\s]?LABEL)?\s*$", re.I)
_LABELS = {"A": 180, "C": 45}  # B is 60 or 90: no single answer
_HOURS = re.compile(r"(\d+(?:\.\d+)?)?\s*(?:[-\s]\s*)?(\d/\d|[½¾⅓¼])?\s*(?:HOURS?|HRS?\.?|H\b)", re.I)
_MINUTES = re.compile(r"\b(\d{2,3})\s*(?:MIN(?:UTES?)?\.?|M\b)?", re.I)
_UNICODE = {"½": Fraction(1, 2), "¾": Fraction(3, 4), "⅓": Fraction(1, 3), "¼": Fraction(1, 4)}
RATINGS = (20, 45, 60, 90, 120, 180)


def minutes(value: Any) -> int | None:
    """The rating in minutes; 0 for a door the schedule says is not rated; None when
    the text gives no single answer (blank, `B LABEL`, `SEE NOTE`)."""
    text = str(value or "").strip()
    if not text:
        return None
    if _NOT_RATED.match(text):
        return UNRATED
    letter = _LETTER.match(text)
    if letter:
        return _LABELS.get(letter.group(1).upper())
    hours = _HOURS.search(text)
    if hours and (hours.group(1) or hours.group(2)):
        whole = Fraction(hours.group(1)) if hours.group(1) else Fraction(0)
        part = hours.group(2)
        if part:
            whole += _UNICODE.get(part) or Fraction(part)
        found = int(whole * 60)
        return found if found in RATINGS else None
    mins = _MINUTES.search(text)
    if mins and int(mins.group(1)) in RATINGS:
        return int(mins.group(1))
    return None


def label(value: Any) -> str | None:
    """How the quote prints a rating: `90 MIN`, `3 HR`, `NOT RATED`; None when unread."""
    found = minutes(value)
    if found is None:
        return None
    if found == UNRATED:
        return "NOT RATED"
    return f"{found // 60} HR" if found >= 120 and found % 60 == 0 else f"{found} MIN"


def is_rated(value: Any) -> bool:
    return bool(minutes(value))


if __name__ == "__main__":  # the readings the schedules actually print
    for written, expected in [("90", 90), ("90 MIN", 90), ("1-1/2 HR", 90), ("1 1/2 HR", 90), ("1½ HR", 90),
                              ("1.5 HRS", 90), ("3 HR", 180), ("3/4 HR", 45), ("1 HR", 60), ("2 HR", 120),
                              ("20 MIN", 20), ("45", 45), ("A LABEL", 180), ("C", 45), ("B LABEL", None),
                              ("NR", 0), ("-", 0), ("", None), ("SEE NOTE 4", None), ("12", None)]:
        assert minutes(written) == expected, (written, minutes(written), expected)
    assert label("1-1/2 HR") == "90 MIN" and label("3 HR") == "3 HR" and label("NR") == "NOT RATED"
    print("fire_rating ok")
