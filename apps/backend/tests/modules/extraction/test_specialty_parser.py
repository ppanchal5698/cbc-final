"""Division 10 and FRP read off the sheets rather than invented by a model.

Both take-offs were placeholders - `NOT_EXTRACTED` with empty `items`,
`NOT_MEASURED` with empty `areas` - so every Div 10 and FRP field on a quote came
from a model filling a blank.

The contract is the take-off's: **never silently wrong**. A schedule row that
identifies an accessory is read; a sentence that merely names one is reported as
a mention and never priced; geometry nobody measured stays null and flagged.
"""
from __future__ import annotations

import pytest

from cbc.modules.extraction.infrastructure import specialty_parser as sp


# ── what the row says it is ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "line,expected",
    [
        ("C | SURFACE MOUNTED JUMBO ROLL TOILET TISSUE DISPENSER", "toilet_tissue_dispenser"),
        ("D | COAT HOOK | BRADLEY 9114-0000000", "coat_hook"),
        ("AUTOMATIC ROLL PAPER TOWEL DISPENSER", "paper_towel_dispenser"),
        ("SOAP DISPENSER (ECOLAB)", "soap_dispenser"),
        ("GRAB BAR REQUIREMENT AS PER CODE", "grab_bar"),
        ("SANITARY NAPKIN DISPOSAL", "napkin_disposal"),
        ("OPEN FRONT SEAT AND SEAT COVER", "seat_cover_dispenser"),
    ],
)
def test_a_row_is_typed_from_how_the_schedule_names_it(line, expected) -> None:
    assert sp._product_type(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "CONTRACTOR MAKING FINAL HOOK-UPS. (THIS WILL ALSO INCLUDE PURCHASED",
        "ENSURE MODEL IS HARDWIRED",
        "ALL DRAWINGS AND SPECIFICATIONS ARE THE EXCLUSIVE PROPERTY",
    ],
)
def test_a_row_naming_no_accessory_is_not_one(line) -> None:
    """"FINAL HOOK-UPS" is an electrical note; it became a coat hook."""
    assert sp._product_type(line) is None


def test_a_row_naming_two_accessories_is_flagged_not_guessed() -> None:
    """Two schedule columns clustered onto one row.

    Taking the first match silently made a tissue dispenser into a grab bar.
    """
    line = "AOR TO DETERMINE GRAB BAR REQUIREMENT | TOILET PAPER DISPENSER:"
    found = sp._product_types(line)
    assert len(found) > 1 and "grab_bar" in found


# ── who makes it ────────────────────────────────────────────────────────────

def test_only_the_vendors_cbc_quotes_for_division_10_count() -> None:
    assert sp._manufacturer_in("SCHEDULE ON | BOBRICK B-3974") == ("Bobrick", "BOBRICK")
    # A hinge maker on a door schedule is not a washroom accessory supplier.
    assert sp._manufacturer_in("HAGER 3580 lock") is None


@pytest.mark.parametrize(
    "line,token,model",
    [
        ("BOBRICK B-3974 | ENSURE", "BOBRICK", "B-3974"),
        ("ASI MODEL NO.0042 SURFACE", "ASI", "0042"),
        ("BRADLEY 9114-0000000 STAIN", "BRADLEY", "9114-0000000"),
    ],
)
def test_the_model_is_the_number_printed_after_the_manufacturer(line, token, model) -> None:
    assert sp._model_after(line, token) == model


# ── an item versus a mention ────────────────────────────────────────────────

def _item(**over):
    base = {"product_type": "mirror", "manufacturer": "Bobrick",
            "specified_model": "B-165", "source_page": 19, "notes": "x"}
    return {**base, **over}


def test_an_item_needs_a_manufacturer_and_a_model(monkeypatch, tmp_path) -> None:
    """Eighteen rows of which six were real read as data and priced as data."""
    rows = [
        _item(),
        _item(product_type="hand_dryer", manufacturer=None, specified_model=None),
        _item(product_type="shelf", manufacturer="ASI", specified_model=None),
    ]
    monkeypatch.setattr(sp, "div10_items_on_page", lambda pdf, page: rows)
    envelope = sp.div10_envelope(tmp_path / "bid.pdf", [19])

    assert [item["product_type"] for item in envelope["items"]] == ["mirror"]
    assert {m["product_type"] for m in envelope["mentions"]} == {"hand_dryer", "shelf"}
    assert "div10_mentions_need_review" in envelope["flags"]


def test_a_mention_is_reported_once_per_type_per_page(monkeypatch, tmp_path) -> None:
    """Three prose rows naming MIRROR answer "is there a row for it?" once."""
    rows = [_item(manufacturer=None, specified_model=None, notes=f"note {n}") for n in range(3)]
    monkeypatch.setattr(sp, "div10_items_on_page", lambda pdf, page: rows)
    envelope = sp.div10_envelope(tmp_path / "bid.pdf", [19])
    assert len(envelope["mentions"]) == 1
    assert envelope["mentions"][0]["why_not_an_item"]


def test_no_rows_at_all_says_so(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sp, "div10_items_on_page", lambda pdf, page: [])
    envelope = sp.div10_envelope(tmp_path / "bid.pdf", [19])
    assert envelope["status"] == "NOT_EXTRACTED"
    assert envelope["flags"] == ["no_div10_items_found"]


def test_a_count_is_never_defaulted_to_one(monkeypatch, tmp_path) -> None:
    """Counting accessories means reading elevations, not a schedule row.

    A default of 1 quotes one grab bar for a building with nothing on the line
    to say the count was never read.
    """
    from cbc.modules.extraction.api.claude_output import Div10Item

    assert Div10Item(product_type="grab_bar").qty is None
    assert Div10Item(product_type="grab_bar", qty="").qty is None
    assert Div10Item(product_type="grab_bar", qty="4").qty == 4.0


def test_the_review_signal_survives_the_import_model() -> None:
    """`extra="ignore"` drops undeclared fields, so a mention would reach no one."""
    from cbc.modules.extraction.api.claude_output import Div10Takeoff

    parsed = Div10Takeoff.model_validate({
        "status": "EXTRACTED",
        "items": [],
        "mentions": [{"product_type": "hand_dryer", "source_page": 19,
                      "excerpt": "OPTIONAL HAND DRYER", "why_not_an_item": "no model"}],
        "pages_read": [19],
        "source_file": "bid.pdf",
    })
    assert parsed.mentions[0].product_type == "hand_dryer"
    assert parsed.pages_read == [19]


# ── FRP: what prose can say, and what only a drawing can ────────────────────

def _page(text: str):
    class _Page:
        def get_text(self, *a, **k):
            return text

    class _Doc:
        name = "bid.pdf"

        def __getitem__(self, _index):
            return _Page()

        def close(self):
            pass

    return _Doc()


def _findings(monkeypatch, text: str, pages=(1,)):
    import fitz

    monkeypatch.setattr(fitz, "open", lambda *a, **k: _page(text))
    from pathlib import Path

    return sp.frp_findings(Path("bid.pdf"), list(pages))


def test_frp_geometry_is_never_invented(monkeypatch) -> None:
    """Perimeter, corners and wall height come off scaled elevations.

    A guessed linear-foot figure prices a wall that does not exist.
    """
    found = _findings(monkeypatch, "NON-TILE FIBERGLASS REINFORCED POLYESTER (FRP) PANELS")
    assert found["frp_in_scope"] is True
    assert found["status"] == "NOT_MEASURED"
    assert found["quantity"] is None and found["areas"] == []
    for field in ("perimeter_lf", "wall_height_ft", "inside_corners", "outside_corners"):
        assert f"{field}_not_measured" in found["flags"]
    assert found["blocked_on"]


def test_the_product_kind_is_read_from_the_specification(monkeypatch) -> None:
    found = _findings(monkeypatch, "TEXTURED NON-TILE FRP PANELS")
    assert found["product_type"] == "non_tile/textured"


def test_no_frp_on_the_sheets_is_not_frp_in_scope(monkeypatch) -> None:
    found = _findings(monkeypatch, "HOLLOW METAL DOOR AND FRAME SCHEDULE")
    assert found["frp_in_scope"] is False
    assert found["status"] == "NOT_FOUND"


def test_a_vendor_elsewhere_on_the_sheet_is_not_the_frp_vendor(monkeypatch) -> None:
    """Bobrick makes washroom accessories, not FRP.

    Scanning the whole page attributed FRP to whichever vendor the sheet named
    anywhere - a manufacturer on a quote that no one specified.
    """
    found = _findings(
        monkeypatch,
        "BOBRICK B-165 MIRROR AT EACH LAVATORY\nNON-TILE FRP PANELS TO 4'-0\" AFF\n",
    )
    assert found["manufacturer"] is None
    assert "manufacturer_missing" in found["flags"]


def test_a_vendor_named_with_the_frp_is_the_frp_vendor(monkeypatch) -> None:
    found = _findings(monkeypatch, "FRP PANELS: NUDO FIBERLITE, WHITE\n")
    assert found["manufacturer"] == "Nudo"
    assert "manufacturer_missing" not in found["flags"]


def test_an_existing_scope_summary_still_reports_what_is_in_scope(tmp_path, monkeypatch) -> None:
    """Those flags gate the FRP and Div 10 seeds.

    Returning only `written: False` when the file already existed meant that on
    every re-run neither specialty artifact was seeded, and both specialists
    started from a blank page again - the exact thing the seeds exist to stop.
    """
    import json

    from cbc.modules.extraction.infrastructure import pretakeoff

    monkeypatch.setattr(pretakeoff.storage, "project_dir", lambda _slug: tmp_path)
    path = tmp_path / "extracted" / "scope_summary.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"frp_in_scope": True, "div10_in_scope": False}), encoding="utf-8")

    result = pretakeoff.seed_scope_summary("fixture")
    assert result["written"] is False
    assert result["frp_in_scope"] is True
    assert result["div10_in_scope"] is False
