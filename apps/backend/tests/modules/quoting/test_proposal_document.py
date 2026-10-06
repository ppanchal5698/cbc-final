"""The proposal as the customer reads it: one layout, generated qualifications, one email draft."""
from __future__ import annotations

from cbc.modules.quoting.api import quote_layout
from cbc.modules.quoting.infrastructure import proposal_view


def _line(**over):
    base = dict(description="ENTRY LOCK", part_number="3553", quantity=3, sale_ea=101.37, ext_price=304.11,
                group="01", division="08 71 00", openings=["101", "102", "103"], qty_per_opening=1)
    base.update(over)
    return quote_layout.line(**base)


def test_a_hardware_set_names_its_doors_and_each_doors_rating_when_they_differ() -> None:
    [block] = quote_layout.blocks([_line()], {"101": "90 MIN", "102": "90 MIN", "103": "20 MIN"})
    [group] = block["groups"]
    assert group["doors"] == ["101", "102", "103"]
    assert group["door_labels"] == ["101 (90 MIN)", "102 (90 MIN)", "103 (20 MIN)"]
    [same] = quote_layout.blocks([_line()], {"101": "90 MIN", "102": "90 MIN", "103": "90 MIN"})[0]["groups"]
    assert same["ratings"] == ["90 MIN"] and same["door_labels"] == ["101", "102", "103"]


def test_a_group_with_a_line_still_to_price_has_no_total_yet() -> None:
    [block] = quote_layout.blocks([_line(), _line(part_number=None, sale_ea=None, ext_price=None)])
    assert block["groups"][0]["complete"] is False and block["complete"] is False


def test_frp_filed_under_09_77_prints_in_the_frp_block() -> None:
    assert quote_layout.section_of("09 77 13") == "frp" and quote_layout.section_of("09 91 00") == "other"


def test_qualifications_say_what_the_quote_leaves_out_and_assumes() -> None:
    lines = [
        {"description": "ENTRY LOCK", "flags": ["qty_assumed_one"], "division": "08 71 00",
         "substitutionNote": "Bradley 915 is offered as a direct equal to the specified Bobrick B-212."},
        {"description": "CLOSER", "alternateGroup": "Supplied by others",
         "notes": "supplied by the storefront supplier per the legend"},
        {"description": "FRP PANEL", "division": "06 64 00"},
    ]
    openings = [{"mark": "100A", "inScope": False, "scopeReason": "aluminum storefront, by others"},
                {"mark": "100B", "inScope": False, "scopeReason": "aluminum storefront, by others"},
                {"mark": "B-5806", "inScope": False, "specialty": {"kind": "div10"}}]

    said = proposal_view.qualifications(lines, openings)

    assert said == [
        "Not included - the documents assign these to others: CLOSER (supplied by the storefront supplier per "
        "the legend).",
        "Not included - aluminum storefront, by others: doors 100A, 100B.",
        "Where the hardware legend states no count, one per opening is included.",
        "FRP quantities are taken from the finish plan; field measurement is the installer's.",
    ]  # the substitution's NOTE prints under its own line, not here


def _payload(**over):
    data = {
        "proposal": {"proposalNo": "Q-1", "date": "2026-10-06", "estimator": {"name": "Kevin"},
                     "exclusions": list(proposal_view.DEFAULT_EXCLUSIONS), "customer": {"name": "Turner"},
                     "draft": True},
        "sections": [{"key": "door", "title": "Doors, Frames & Hardware", "subtotal": 304.11, "lines": [
            {"part": "3553", "qty": 3.0, "uom": "EA", "description": "ENTRY LOCK", "unitPrice": 101.37,
             "extPrice": 304.11, "priceStatus": "PRICED", "group": "01", "division": "08 71 00",
             "substitutionNote": None, "manufacturer": "Hager", "openings": ["101", "102", "103"], "qtyPerOpening": 1},
        ]}],
        "alternates": [],
        "totals": {"subtotal": 304.11, "freight": None, "taxJurisdiction": "OH", "taxRate": 0.08, "tax": 24.33,
                   "grandTotal": 328.44},
        "readiness": {"flaggedLineItems": 0, "unpricedQuoteLines": 0},
        "qualifications": [], "doorRatings": {"101": "90 MIN"},
    }
    data.update(over)
    return data


def test_the_customer_document_carries_no_cost_margin_or_review_codes() -> None:
    html = proposal_view.render_html({"name": "Wendy's", "initiator": "Kellan"}, _payload(), False)
    assert "Hardware set 01" in html and "doors 101, 102, 103" in html and "$304.11" in html
    assert "1 per opening &times; 3 openings" in html
    for internal in ("Cost EA", "Margin", "PRICED", "NEEDS_JUDGMENT"):
        assert internal not in html
    assert "DRAFT" in html


def test_an_approved_proposal_prints_without_the_draft_banner() -> None:
    approved = _payload()
    approved["proposal"] = {**approved["proposal"], "draft": False}
    assert "not yet approved" not in proposal_view.render_html({"name": "Wendy's"}, approved, False)


def test_one_email_draft_with_nothing_meant_for_a_model_in_it() -> None:
    data = _payload(lines=[{"description": "EXIT DEVICE", "manufacturer": "Von Duprin", "cost": None,
                            "costSourceDetail": "distributor quote"}],
                    openings=[{"mark": "100A", "inScope": False, "scopeReason": "aluminum storefront"}],
                    flags=[], rfis=["Confirm hinge count per leaf at door 104"])

    draft = proposal_view.email_draft({"name": "Wendy's", "initiator": "Kellan Smith"}, data)

    assert draft["to"] == "Kellan Smith" and draft["subject"] == "CBC Quotation Q-1 - Wendy's"
    assert draft["body"].startswith("Hi Kellan,") and "DRAFT" not in draft["body"]
    assert "# Quotation Email - DRAFT" in draft["document"] and "Never a group email" not in draft["document"]
    for expected in ("EXIT DEVICE (Von Duprin) - distributor quote", "Door 100A - aluminum storefront",
                     "Confirm hinge count per leaf at door 104", "Total: **$328.44**"):
        assert expected in draft["body"]


def test_the_draft_goes_to_the_initiator_by_address_or_says_it_has_none() -> None:
    """FR-1b: the PDF returns to the person who asked for it - one address, theirs."""
    bid = {"name": "Wendy's", "initiator": "Kellan"}
    addressed = proposal_view.email_draft(bid, _payload(), address={"name": "Kellan Smith", "email": "kellan@cbc.test"})
    assert addressed["to"] == "Kellan <kellan@cbc.test>"
    assert "**To:** Kellan <kellan@cbc.test>" in addressed["document"]

    unknown = proposal_view.email_draft(bid, _payload())
    assert unknown["to"] == "Kellan" and "no address on file" in unknown["document"]


def test_a_bare_set_name_reads_as_a_hardware_set_and_doors_print_as_they_are() -> None:
    blocks = quote_layout.blocks([_line(), _line(group="Doors", description="HOLLOW METAL DOOR"),
                                  _line(group="GROUP 05", description="Hardware GROUP 05 as scheduled")])
    titles = {group["name"]: group["title"] for group in blocks[0]["groups"]}
    # Evernorth's GROUP 05 is a set the schedule cites and the legend never listed.
    assert titles == {"01": "Hardware set 01", "Doors": "Doors", "GROUP 05": "Hardware set 05"}
