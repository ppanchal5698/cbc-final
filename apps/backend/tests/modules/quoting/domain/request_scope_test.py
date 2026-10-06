"""The scope a bid request states in its own words (FR-1, FR-1a)."""
from __future__ import annotations

import pytest

from cbc.modules.quoting.domain import request_scope


@pytest.mark.parametrize("notes,expected", [
    ("Hardware only per the GC", {"doors", "frames", "division10", "frp"}),
    ("Please quote doors, frames & hardware. Div 10 by owner.", {"division10"}),
    ("Doors and frames by GC; quote hardware and accessories", {"doors", "frames"}),
    ("HM frames are N.I.C.", {"frames"}),
    ("No FRP on this one", {"frp"}),
    ("Toilet partitions furnished by the tenant", {"division10"}),
    ("Overhead doors by others - quote all swing doors", set()),
    ("Quote everything per plans", set()),
    ("", set()),
])
def test_a_request_gives_these_to_someone_else(notes, expected) -> None:
    assert set(request_scope.excluded(notes)) == expected


def test_the_words_that_said_so_are_kept() -> None:
    assert request_scope.excluded("Doors by others.")["doors"] == "Doors by others"


@pytest.mark.parametrize("key,division,category", [
    ("door:hollow metal|3'-0\"|7'-0\"||90 MIN|", "08 11 13", "doors"),
    ("frame:hollow metal|3'-0\"|7'-0\"|||", "08 11 13", "frames"),
    ("10:A1", "10 28 13", "division10"),
    ("06:2", "06 64", "frp"),
    ("1:01", "08 71 00", None),
])
def test_each_line_is_one_part_of_the_scope(key, division, category) -> None:
    assert request_scope.category_of(key, division) == category
