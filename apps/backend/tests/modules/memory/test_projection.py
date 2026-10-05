"""The memory graph's rows, from the documents they mirror. No database."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId

from cbc.modules.catalog.api.learning import spec_key
from cbc.modules.memory.domain import projection

TIERS = {
    "vendors": [
        {"key": "hager", "name": "Hager", "tier": "Hager Advantage Program", "account": "HGR 17907",
         "multiplier": None, "effective_date": "2026-03-02",
         "categories": {"locks": 0.29, "architectural_hinges": 0.21},
         "discounts": {"locks": "50/42%", "architectural_hinges": "50/58%"}},
        {"key": "national_guard", "name": "National Guard", "multiplier": 0.45, "effective_date": "2026-01-01"},
    ],
    "excluded": [{"name": "Allegion", "reason": "distributor only"}],
}


def test_one_vendor_per_real_name_whichever_source_names_it():
    rows = projection.vendor_rows(TIERS, [{"vendor": "national_guard"}, {"vendor": "pemko"}], ["National Guard", "Hager", "Pemko"])
    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == {"hager", "national_guard", "allegion", "pemko"}
    assert by_key["hager"]["program"] == "Hager Advantage Program"
    assert by_key["allegion"]["excludedReason"] == "distributor only"


def test_a_vendor_prices_by_category_or_by_one_account_multiplier():
    rows = {r["key"]: r for r in projection.multiplier_rows(TIERS)}
    assert rows["hager:locks"]["value"] == 0.29 and rows["hager:locks"]["discount"] == "50/42%"
    assert rows["hager:architectural_hinges"]["effective"] == "2026-03-02"
    assert rows["national_guard:all"]["value"] == 0.45
    assert "hager:all" not in rows  # Hager has no single multiplier


def test_reference_entries_keep_what_cbc_has_not_supplied_as_null():
    customers = projection.customer_rows({"customers": [{"name": "Wendys", "margin": None, "note": "via Banner"}]})
    assert customers == [{"key": "wendys", "name": "Wendys", "specialMargin": None,
                          "specialMarginNote": "via Banner", "source": None}]
    frp = {r["key"]: r for r in projection.frp_rows(
        {"status": "PENDING", "panel_size": None, "panel_size_note": "4 x 8", "waste_pct": 0.1})}
    assert set(frp) == {"panel_size", "waste_pct"}
    assert frp["panel_size"]["value"] is None and frp["panel_size"]["note"] == "4 x 8"
    depth = projection.frame_depth_rows({"wall_types": [{"type": "Masonry", "depth": "5-3/4", "depth_inches": 5.75}]})
    assert depth[0]["key"] == "masonry" and depth[0]["inches"] == 5.75


def test_a_catalog_row_without_a_part_is_not_a_catalog_item():
    rows = projection.catalog_rows([
        {"part": "BB1279", "manufacturer": "Hager", "cost": "24.5", "priceBookId": ObjectId("6aaa50f3e970e6bd50c63fcb")},
        {"part": "", "manufacturer": "Hager"},
    ])
    assert [r["key"] for r in rows] == ["hager:BB1279"]
    assert rows[0]["cost"] == 24.5 and rows[0]["priceBook"] == "6aaa50f3e970e6bd50c63fcb"


def test_an_approved_bid_becomes_sets_spec_lines_and_its_workflow():
    pid = ObjectId()
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    project = {"_id": pid, "code": "CBC-1", "name": "Wendys Acheson", "brand": "Wendy's", "gc": "Acme Builders"}
    approval = {"approvedBy": "kevin@cbc.com", "approvedAt": start,
                "totalsSnapshot": {"grandTotal": 12000.0, "cost": 9000.0, "margin": 0.25}}
    lines = [
        {"group": "SET 01", "part": "BB1279", "manufacturer": "Hager", "description": "HINGE 4.5x4.5 US26D",
         "qty": 3, "cost": 24.5, "costSource": "LIST_X_MULTIPLIER", "margin": 0.27, "division": "08 71 00"},
        {"group": "SET 01", "part": None, "manufacturer": None, "description": "WALL STOP", "qty": 1,
         "cost": None, "costSource": "MANUAL", "addedByHand": True},
    ]
    jobs = [
        {"_id": ObjectId(), "type": "extract_bid_set", "status": "done", "attempts": 2,
         "startedAt": start, "finishedAt": start + timedelta(minutes=4), "createdAt": start},
        {"_id": ObjectId(), "type": "match_and_price", "status": "done", "attempts": 1, "createdAt": start},
    ]
    rows = projection.bid_rows(project, approval, lines, [{"mark": "101"}], jobs, spec_key)

    bid = rows["bid"]
    assert bid["key"] == str(pid) and bid["total"] == 12000.0 and bid["margin"] == 0.25
    assert (bid["lineCount"], bid["pricedLineCount"], bid["manualLineCount"], bid["handLineCount"]) == (2, 1, 1, 1)
    assert bid["retries"] == 1 and bid["openingCount"] == 1
    assert rows["brands"] == [{"key": "wendy_s", "name": "Wendy's"}]
    assert rows["gcs"] == [{"key": "acme_builders", "name": "Acme Builders"}]
    assert rows["sets"] == [{"key": f"{pid}:SET 01", "name": "SET 01", "division": "08 71 00", "section": "08 71 00"}]
    assert rows["covers"] == [{"section": "08 71 00", "lines": 1, "extended": 0.0}]

    hinge, stop = rows["items"]
    assert hinge["itemKey"] == "hager:BB1279" and hinge["qty"] == 3.0
    assert hinge["specKey"] == spec_key("Hager BB1279 HINGE 4.5x4.5 US26D")
    assert stop["itemKey"] is None and stop["addedByHand"] is True

    assert [s["type"] for s in rows["steps"]] == ["extract_bid_set", "match_and_price"]
    assert rows["steps"][0]["durationS"] == 240.0 and rows["steps"][1]["durationS"] is None


def test_a_section_sits_in_its_parent_section_and_its_division():
    from cbc.modules.pricing.api import pricing

    rows = projection.section_rows(
        ["10 28 13", "08 71 00", "09 77 00", None],
        pricing.band_for_division,
        lambda code: code[:5] in pricing.DIVISION_BANDS,
    )
    sections = {s["key"]: s for s in rows["sections"]}
    assert set(sections) == {"08 71 00", "09 77 00", "10 28 00", "10 28 13"}
    assert sections["10 28 13"]["parent"] == "10 28 00" and sections["10 28 13"]["level"] == 3
    assert sections["10 28 00"]["parent"] is None and sections["10 28 00"]["division"] == "10"
    assert sections["08 71 00"]["title"] == "Door Hardware"
    # The band pricing applies, and whether that is only its default.
    assert (sections["10 28 13"]["marginBand"], sections["10 28 13"]["bandIsFallback"]) == ("accessories", False)
    assert (sections["09 77 00"]["marginBand"], sections["09 77 00"]["bandIsFallback"]) == ("commodity", True)
    assert [d["key"] for d in rows["divisions"]] == ["08", "09", "10"]
    assert projection.section_code("10 28") == "10 28 00" and projection.section_code("hinge") is None


def test_the_derived_accessories_band_is_a_band_like_the_others():
    rows = {r["key"]: r for r in projection.margin_band_rows(
        {"bands": [{"key": "commodity", "margin": 0.27}], "accessories_derived": 0.56})}
    assert rows["commodity"]["derived"] is False
    assert rows["accessories"]["margin"] == 0.56 and rows["accessories"]["derived"] is True

