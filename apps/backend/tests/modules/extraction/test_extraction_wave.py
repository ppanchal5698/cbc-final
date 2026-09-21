"""Which take-offs the worker starts together, and what each one is told.

Wave 2 is three take-offs that read different pages and write different files.
Nothing in it reads another's output, so nothing in it has to wait - and yet a
measured run spent 11 of its 17 minutes doing exactly that, because the
orchestrator emitted its three `Agent` calls in three separate messages.

The prompt had asked for one message. Asking is not a mechanism.
"""
from __future__ import annotations

import json

import pytest

from cbc.modules.extraction.api import passes
from cbc.worker_kit import prompts


@pytest.fixture()
def bid(tmp_path, monkeypatch):
    monkeypatch.setattr(passes.storage, "project_dir", lambda _slug: tmp_path)
    monkeypatch.setattr(passes.sheetmap, "sheetmap_path", lambda _slug: tmp_path / "_sheetmap.json")
    (tmp_path / "extracted").mkdir()

    def write(roles: dict[str, list[int]], **scope):
        pages = []
        for role, numbers in roles.items():
            for number in numbers:
                pages.append({"source_page": number, "roles": [role]})
        sheets = {"files": [{"path": "uploads/raw/a.pdf", "pages": pages}]}
        (tmp_path / "_sheetmap.json").write_text(json.dumps(sheets), encoding="utf-8")
        (tmp_path / "extracted" / "scope_summary.json").write_text(
            json.dumps({"frp_in_scope": True, "div10_in_scope": True, **scope}), encoding="utf-8"
        )

    return write


PROJECT = {"slug": "fixture", "code": "CBC-1"}
JOB = {"type": "extract_bid_set"}


def test_all_three_takeoffs_are_started_together(bid) -> None:
    bid({"door_schedule": [16], "frp": [23], "div10": [19, 18]})
    assert [label for label, _prompt in passes.extraction_wave(JOB, PROJECT)] == [
        "takeoff", "frp", "div10"
    ]


def test_a_specialty_out_of_scope_is_not_started(bid) -> None:
    """The scope file gates the leg and its seed alike, so they cannot disagree."""
    bid({"door_schedule": [16], "frp": [23], "div10": [19]}, frp_in_scope=False)
    assert [label for label, _p in passes.extraction_wave(JOB, PROJECT)] == ["takeoff", "div10"]


def test_one_leg_is_not_a_wave(bid) -> None:
    """Fanning out a single pass drops the orchestrator prompt for no benefit."""
    bid({"door_schedule": [16]}, frp_in_scope=False, div10_in_scope=False)
    assert passes.extraction_wave(JOB, PROJECT) == []


def test_only_an_extraction_fans_out(bid) -> None:
    bid({"door_schedule": [16], "frp": [23], "div10": [19]})
    assert passes.extraction_wave({"type": "match_and_price"}, PROJECT) == []
    assert passes.extraction_wave({"type": "build_proposal"}, PROJECT) == []


def test_no_sheetmap_falls_back_to_a_single_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(passes.storage, "project_dir", lambda _slug: tmp_path)
    monkeypatch.setattr(passes.sheetmap, "sheetmap_path", lambda _slug: tmp_path / "missing.json")
    assert passes.extraction_wave(JOB, PROJECT) == []


# ── what a leg is told ──────────────────────────────────────────────────────

def _briefs():
    return dict(prompts.build_wave(
        PROJECT, [("takeoff", [16]), ("frp", [23]), ("div10", [19])]
    ))


def test_a_leg_is_told_not_to_delegate() -> None:
    """It is the specialist. There is nobody to delegate to."""
    for label, text in _briefs().items():
        assert "Do not call the Agent tool" in text, label
        assert "Delegate with the Agent tool" not in text, label


def test_a_leg_is_told_which_files_belong_to_its_siblings() -> None:
    """They share one workspace, so writing a sibling's file overwrites live work."""
    briefs = _briefs()
    assert "extracted/frp_takeoff.json" in briefs["takeoff"]
    assert "extracted/div10_takeoff.json" in briefs["takeoff"]
    assert "extracted/door_schedule.json" in briefs["frp"]


def test_a_leg_is_told_its_artifact_already_exists() -> None:
    for label, text in _briefs().items():
        assert "already written" in text, label
        assert "confirming a document, not producing one" in text, label


def test_the_takeoff_leg_patches_and_the_specialists_save() -> None:
    briefs = _briefs()
    assert "propose_patch" in briefs["takeoff"]
    assert "save_artifact" in briefs["frp"]
    assert "save_artifact" in briefs["div10"]


def test_each_leg_carries_only_its_own_pages() -> None:
    briefs = dict(prompts.build_wave(
        PROJECT, [("takeoff", [16]), ("frp", [23]), ("div10", [19, 18])]
    ))
    assert "16" in briefs["takeoff"]
    assert "23" in briefs["frp"]
    assert "19, 18" in briefs["div10"]


def test_the_takeoff_leg_gets_the_sheets_the_schedule_does_not_print(bid) -> None:
    """Handing is read off the door swing, and the leg was never given a plan.

    The orchestrator path assigns takeoff-engineer door_schedule,
    door_schedule_candidate, hardware, div08_specs *and* floor_plan, and the 95%
    ladder ends "floor plans (validate / fill gaps)". The wave path handed it
    schedule pages only. A real run then said, on every opening in the bid:

        "floor-plan swing (sheet A2.0) is outside this session's page scope,
         so handing stays flagged rather than filled"

    It was being asked for a field and denied the sheet that carries it.
    """
    bid({
        "door_schedule": [16],
        "floor_plan": [40, 41, 42],
        "hardware": [50, 51, 52],
        "div08_specs": [60],
        "frp": [23],
    })
    legs = dict(passes.extraction_wave(JOB, PROJECT))
    pages = legs["takeoff"]

    assert "16" in pages, "the schedule is still the primary read"
    assert "40" in pages and "41" in pages, "floor plans, for the swing"
    assert "60" in pages, "the Division 08 specs"
    assert "42" not in pages, "an allowance, not the whole role - these cost tokens"
    assert "52" not in pages


def test_the_allowance_counts_sheets_the_leg_does_not_already_have(bid) -> None:
    """`pages_for` ranks, it does not filter.

    The same few sheets top every role's list, so taking the first N of each
    added nothing and left the discriminating floor plans - which sit further
    down - unseen. Measured on a real bid: `floor_plan` resolved to
    [14, 1, 24, 10, ...] where 14 and 1 were already schedule pages.
    """
    bid({"door_schedule": [16], "floor_plan": [16, 40], "frp": [23]})
    pages = dict(passes.extraction_wave(JOB, PROJECT))["takeoff"]

    assert "40" in pages, "the overlap must not consume the allowance"
