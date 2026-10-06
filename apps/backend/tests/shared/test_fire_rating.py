"""One reading of a fire rating for the whole app (requirements 6.1)."""
from __future__ import annotations

import pytest

from cbc.shared import fire_rating


@pytest.mark.parametrize(("written", "minutes"), [
    ("90", 90), ("90 MIN", 90), ("1-1/2 HR", 90), ("1 1/2 HR", 90), ("1½ HR", 90), ("1.5 HRS", 90),
    ("3 HR", 180), ("3/4 HR", 45), ("1 HR", 60), ("2 HR", 120), ("20 MIN", 20), ("45", 45),
    ("A LABEL", 180), ("C", 45), ("B LABEL", None), ("NR", 0), ("-", 0), ("", None), ("SEE NOTE 4", None),
    ("12", None),
])
def test_every_way_a_schedule_writes_a_rating_reads_as_minutes(written, minutes) -> None:
    assert fire_rating.minutes(written) == minutes


def test_a_rating_prints_one_way() -> None:
    assert (fire_rating.label("1-1/2 HR"), fire_rating.label("3 HR"), fire_rating.label("NR")) == (
        "90 MIN", "3 HR", "NOT RATED")
    assert fire_rating.label("B LABEL") is None
