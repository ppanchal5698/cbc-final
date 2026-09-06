"""Proposal - the customer-facing document, and the point where the system stops.

The API renders and serves it. It does not email it. NFR-1 is not negotiable:
the copilot drafts, sources and calculates - a human sends.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from cbc.config import settings
from cbc.db import db, serialise
from cbc.http.deps import Actor
from cbc.schemas import HandOff, ProposalSettings
from cbc.http.projects_access import load
from cbc.persistence import proposals as proposal_rules
from cbc.domain import quote_layout
from cbc.services import audit, quote as quote_service

router = APIRouter(prefix="/api/projects/{code}/proposal", tags=["proposal"])

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


def _write_email_draft(project: dict[str, Any], recipient: str | None, actor: str) -> str:
    """Write the drafted body to the project's review folder as an artifact."""
    from cbc.services import storage

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


@router.get("")
async def get_proposal(code: str) -> dict[str, Any]:
    return await _proposal_payload(await load(code))


async def _proposal_payload(project: dict[str, Any]) -> dict[str, Any]:
    """The proposal as rendered. Takes the project so callers do not re-load it."""
    stored = await db.proposals.find_one({"projectId": project["_id"]}) or {}
    built = await _build(project, stored.get("markup", 0.0))

    flagged = await db.line_items.count_documents(
        {"projectId": project["_id"], "status": "needs_look"}
    )
    unpriced = await db.quote_lines.count_documents(
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


@router.patch("")
async def update_proposal(code: str, body: ProposalSettings, actor: Actor) -> dict:
    project = await load(code)
    changes = body.model_dump(exclude_unset=True)

    await db.proposals.update_one(
        {"projectId": project["_id"]},
        {
            "$set": {**changes, "updatedAt": _now()},
            "$setOnInsert": {
                "projectId": project["_id"],
                "proposalNo": f"Q-{project['code'].split('-')[-1]}",
                "date": date.today().isoformat(),
                "createdAt": _now(),
            },
        },
        upsert=True,
    )
    await audit.record("proposal.update", actor, {"projectId": project["_id"]}, after=changes)
    return await _proposal_payload(project)


@router.get("/render", response_class=HTMLResponse)
async def render_proposal(code: str, autoprint: bool = False) -> HTMLResponse:
    """Render the customer-facing HTML from the shared Jinja template.

    autoprint opens the browser print dialog, which is the fallback path to a PDF
    when no local renderer is installed.
    """
    project = await load(code)
    data = await _proposal_payload(project)
    html = await asyncio.to_thread(_render_proposal_html, project, data, autoprint)
    return HTMLResponse(html)


def _render_proposal_html(project: dict[str, Any], data: dict[str, Any], autoprint: bool) -> str:
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


@router.get("/pdf")
async def proposal_pdf(code: str) -> Response:
    """Download the proposal as a PDF.

    Rendered locally - no converter is fetched from the internet. If no renderer
    is installed the caller is told plainly rather than handed a broken file.
    """
    project = await load(code)
    html = (await render_proposal(code)).body.decode("utf-8")

    try:
        from weasyprint import HTML  # type: ignore
    except Exception as exc:
        # WeasyPrint imports on Windows but fails to load its GTK libraries with
        # an OSError, so this cannot narrow to ImportError.
        raise HTTPException(
            501,
            "No working local PDF renderer. Use the printable view and print to PDF "
            "from the browser, or install the WeasyPrint native libraries (GTK "
            f"runtime on Windows). Underlying error: {exc}",
        ) from exc

    # WeasyPrint is CPU-bound and takes seconds on a long proposal; inline it
    # blocked every other request for the duration.
    pdf_bytes = await asyncio.to_thread(
        HTML(string=html, base_url=str(settings.repo_root)).write_pdf
    )
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{project["code"]}-proposal.pdf"'},
    )


@router.post("/complete")
async def mark_complete(code: str, actor: Actor, body: HandOff | None = None) -> dict:
    """Sign off and route the bid to the sales initiator - inside this app only.

    NFR-1 is untouched: the estimator approves, the bid appears in the named
    person's queue, and the drafted body is written to disk for them to send.
    Nothing is transmitted from here, by any means.
    """
    project = await load(code)
    recipient = (body.recipient if body else None) or project.get("initiator")

    # This call *is* the estimator's approval, so it is where §3.30's required
    # `approvedBy` gets its value - a named person, never a system actor. Before
    # this the field did not exist and the only trace was a signoff entry the
    # hand-off pushed for itself, which is not an approval by anyone.
    totals, _lines = await quote_service.totals_for(project)
    stored = await db.proposals.find_one({"projectId": project["_id"]}) or {}
    approval = proposal_rules.approve(
        approved_by=actor,
        totals=totals,
        terms={
            "validityDays": VALIDITY_DAYS,
            "poRequired": True,
            "supplyOnly": True,
            "exclusions": stored.get("exclusions") or DEFAULT_EXCLUSIONS,
        },
    )

    await db.proposals.update_one(
        {"projectId": project["_id"]},
        {
            "$set": {
                **approval,
                "completedAt": _now(),
                "completedBy": actor,
                "handedOffTo": recipient,
                "handOffNote": body.note if body else None,
            },
            "$push": {
                "signoff": {"role": "estimator", "by": actor, "at": _now(), "state": "complete"}
            },
        },
        upsert=True,
    )
    await db.projects.update_one(
        {"_id": project["_id"]},
        {"$set": {"handedOffTo": recipient, "handedOffAt": _now(), "updatedAt": _now()}},
    )

    draft_path = _write_email_draft(project, recipient, actor)

    await audit.record(
        "proposal.hand_off",
        actor,
        {"projectId": project["_id"]},
        after={"recipient": recipient},
        note="in-app hand-off; nothing transmitted",
    )
    return {
        "status": "complete",
        "sent": False,
        "handedOffTo": recipient,
        "draftPath": draft_path,
        # Both branches say it, because "nothing has been sent" is the thing the
        # estimator needs to read back on every hand-off (NFR-1).
        "message": (
            f"Signed off and routed to {recipient}. Nothing has been sent."
            if recipient
            else "Signed off, but no sales initiator is recorded on this bid, "
            "so there is nobody to route it to. Nothing has been sent."
        ),
    }


@router.get("/email-draft")
async def email_draft(code: str) -> dict:
    """The prepared body, for the estimator to copy into their own mail client."""
    project = await load(code)
    data = await _proposal_payload(project)
    stored = await db.proposals.find_one({"projectId": project["_id"]}) or {}

    flags = []
    if data["readiness"]["flaggedLineItems"]:
        flags.append(f"{data['readiness']['flaggedLineItems']} extracted line(s) still flagged")
    if data["readiness"]["unpricedQuoteLines"]:
        flags.append(f"{data['readiness']['unpricedQuoteLines']} line(s) need a manual price")

    body = NEWLINE.join(
        [
            f"Hi {(stored.get('handedOffTo') or project.get('initiator') or 'there').split()[0]},",
            "",
            f"Quotation {data['proposal']['proposalNo']} for {project.get('name')} is ready.",
            "",
            f"- Total: ${data['totals']['grandTotal']:,.2f}",
            f"- Supply-only material. HP purchase order required. Valid {VALIDITY_DAYS} days.",
            "- Freight: TBD, handled when the quote becomes a job.",
            *(["", "Needs attention before it goes out:"] if flags else []),
            *[f"- {flag}" for flag in flags],
            "",
            "Thanks,",
            stored.get("completedBy") or "CBC Estimating",
        ]
    )

    return {
        "to": stored.get("handedOffTo") or project.get("initiator"),
        "subject": f"CBC Quotation {data['proposal']['proposalNo']} - {project.get('name')}",
        "body": body,
        "sent": False,
        "note": "Copy this into your own mail client. The system does not send (NFR-1).",
    }
