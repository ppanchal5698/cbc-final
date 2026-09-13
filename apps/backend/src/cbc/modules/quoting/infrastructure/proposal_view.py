"""The proposal as the customer sees it: its sections and totals, its HTML, the email draft.

The API renders and serves it. It does not email it. NFR-1 is not negotiable:
the copilot drafts, sources and calculates - a human sends.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from cbc.domain import quote_layout
from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.infrastructure.collections import estimate_lines, proposals
from cbc.shared.config import settings
from cbc.shared.mongo import serialise


VALIDITY_DAYS = 30


NEWLINE = chr(10)


SECTION_TITLES = {
    "door": "Doors / Frames / Hardware",
    "accessories": "Restroom Accessories",
    "frp": "FRP Wall Panels",
    "other": "Other",
}


DEFAULT_EXCLUSIONS = [
    "Installation, unloading and hoisting are excluded; material F.O.B. jobsite.",
    "Hardware sets are excluded pending the architect resolving any duplicate listings.",
    "Hand dryer voltage per drawing note; electrical rough-in by others.",
    "FRP quantities are based on the finish plan; field measurement is the installer's responsibility.",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def write_email_draft(project: dict[str, Any], recipient: str | None, actor: str) -> str:
    """Write the drafted body to the project's review folder as an artifact."""
    from cbc.shared import storage

    target = storage.project_dir(project["slug"]) / "review" / "quotation_email_draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        NEWLINE.join(
            [
                "# Quotation email - DRAFT",
                "",
                "> Written by the Ops-Hub. **Nothing has been sent** (NFR-1).",
                f"> An estimator ({actor}) signed this off on {date.today().isoformat()}.",
                "",
                f"**To:** {recipient or 'no sales initiator recorded on this bid'}",
                f"**Subject:** CBC Quotation for {project.get('name')}",
                "",
                "See the proposal screen for the current body and totals.",
            ]
        ),
        encoding="utf-8",
    )
    return storage.relative(target)


def _section_of(division: str | None) -> str:
    if not division:
        return "door"
    if division.startswith("10"):
        return "accessories"
    if division.startswith("06"):
        return "frp"
    return "door"


async def _build(project: dict[str, Any], markup: float = 0.0) -> dict[str, Any]:
    # Computed, not stored - see api/services/quote.py. Rendering a proposal used
    # to re-price and re-store the whole quote, and `/pdf` did it twice.
    totals, lines = await quote_service.totals_for(project)

    sections: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = _section_of(line.get("division"))
        section = sections.setdefault(
            key, {"key": key, "title": SECTION_TITLES[key], "lines": [], "subtotal": 0.0}
        )
        unit = line.get("sell")
        extended = line.get("extended")
        if markup and unit is not None:
            unit = round(unit * (1 + markup), 2)
            extended = round(unit * float(line.get("qty") or 0), 2)
        section["lines"].append(
            {
                "part": line.get("part"),
                "qty": line.get("qty"),
                "uom": "EA",
                "description": (line.get("description") or "").upper(),
                "unitPrice": unit,
                "extPrice": extended,
                "priceStatus": line.get("priceStatus"),
                # Carried so the shared layout can group by door and print the
                # substitution note. Dropping them here is what made the
                # customer-facing document differ from the pipeline's.
                "group": line.get("group"),
                "division": line.get("division"),
                "substitutionNote": line.get("substitutionNote"),
            }
        )
        section["subtotal"] = round(section["subtotal"] + (extended or 0), 2)

    ordered = [sections[k] for k in ("door", "accessories", "frp", "other") if k in sections]
    subtotal = round(sum(s["subtotal"] for s in ordered), 2)
    grand = round(subtotal + (totals.get("tax") or 0), 2)

    # A markup moves every printed figure, so the subtotal has to move with them.
    # Printing the quote's own subtotal against marked-up section totals puts a
    # sum on a customer-facing sheet that does not add up.
    return {
        "sections": ordered,
        "totals": {
            **totals,
            "markup": markup,
            **({"subtotal": subtotal, "grandTotal": grand} if markup else {}),
        },
    }


async def proposal_payload(project: dict[str, Any]) -> dict[str, Any]:
    """The proposal as rendered. Takes the project so callers do not re-load it."""
    stored = await proposals().find_one({"projectId": project["_id"]}) or {}
    built = await _build(project, stored.get("markup", 0.0))

    flagged = await extraction_openings.count(project["_id"], status="needs_look")
    unpriced = await estimate_lines().count_documents(
        {"projectId": project["_id"], "cost": None}
    )

    return {
        "proposal": {
            "proposalNo": stored.get("proposalNo") or f"Q-{project['code'].split('-')[-1]}",
            "date": (stored.get("date") or date.today()).isoformat()
            if not isinstance(stored.get("date"), str)
            else stored["date"],
            "validityDays": VALIDITY_DAYS,
            "customer": stored.get("customer") or {"name": project.get("gc")},
            "salesRep": stored.get("salesRep") or {"name": project.get("initiator")},
            "estimator": stored.get("estimator") or {},
            "markup": stored.get("markup", 0.0),
            "exclusions": stored.get("exclusions") or DEFAULT_EXCLUSIONS,
            "signoff": stored.get("signoff") or [],
            "sentAt": stored.get("sentAt"),
        },
        "project": serialise(project),
        **built,
        "readiness": {
            "flaggedLineItems": flagged,
            "unpricedQuoteLines": unpriced,
            "blocking": False,
            "note": "Flagged and unpriced lines are shown, not blocked - the estimator decides.",
            # A draft produced on a provider Claude Code warns about can be wrong
            # as a whole document, not just in one field - and it will not look it.
            "degraded": bool(project.get("degraded")),
            "producedBy": project.get("producedBy"),
            "degradedNote": (
                "Produced on {model} ({mode}), which Claude Code reports problems with: "
                "{why} Re-run on a supported model before trusting these numbers."
            ).format(
                model=(project.get("producedBy") or {}).get("model", "an unknown model"),
                mode=(project.get("producedBy") or {}).get("mode", "?"),
                why=" ".join((project.get("producedBy") or {}).get("warnings") or []),
            ) if project.get("degraded") else None,
        },
    }


def render_html(project: dict[str, Any], data: dict[str, Any], autoprint: bool) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(settings.templates_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # One layout, shared with the pipeline renderer (cbc.domain.quote_layout).
    # This used to build its own blocks: one group per *section* rather than per
    # door, so FR-7's "grouped by door with subtotals" held only on the path a
    # customer never sees - and a hand-built line dict with no key for
    # `substitution_note`, so a direct equal printed with no mention that
    # anything had been substituted.
    blocks = quote_layout.blocks(
        [
            quote_layout.line(
                description=line["description"],
                part_number=line["part"],
                quantity=line["qty"],
                sale_ea=line["unitPrice"],
                ext_price=line["extPrice"],
                group=line.get("group"),
                division=line.get("division"),
                substitution_note=line.get("substitutionNote"),
                price_status=line.get("priceStatus"),
            )
            for section in data["sections"]
            for line in section["lines"]
        ]
    )

    html = env.get_template("quotation.html").render(
        quote_number=data["proposal"]["proposalNo"],
        quote_date=data["proposal"]["date"],
        validity_days=VALIDITY_DAYS,
        project={
            "name": project.get("name"),
            "location": project.get("location"),
            "architect": project.get("architect"),
            "bid_due_date": None,
        },
        customer={"gc": project.get("gc"), "initiator": project.get("initiator")},
        estimator=data["proposal"]["estimator"],
        notes=data["proposal"]["exclusions"],
        blocks=blocks,
        totals={
            "subtotal": data["totals"]["subtotal"],
            "freight": data["totals"].get("freight"),
            "project_state": data["totals"].get("taxJurisdiction"),
            "tax_rate": data["totals"]["taxRate"],
            "tax": data["totals"]["tax"],
            "grand_total": data["totals"]["grandTotal"],
        },
        flag_count=data["readiness"]["flaggedLineItems"],
    )
    if autoprint:
        html += "<script>window.addEventListener('load',()=>window.print())</script>"
    return html
