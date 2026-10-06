"""The proposal as the customer sees it: its sections and totals, its HTML, the email draft.

One rendering, three readers: the proposal screen embeds `/render`, `/pdf`
prints it, and the build_proposal job writes it to quotation.html - so what an
estimator approves on screen is what the PDF says. The API renders and serves
it. It does not email it. NFR-1 is not negotiable: the copilot drafts, sources
and calculates - a human sends.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from cbc.modules.quoting.api import quote_layout
from cbc.modules.extraction.api import line_items
from cbc.modules.extraction.api import openings as extraction_openings
from cbc.modules.extraction.api.validation import review
from cbc.modules.ops.api import identity, jobs
from cbc.modules.quoting.api import priced_lines
from cbc.modules.quoting.api import quote as quote_service
from cbc.modules.quoting.domain import alternates
from cbc.modules.quoting.domain.ladder import BY_OTHERS_ALTERNATE
from cbc.modules.quoting.domain import proposals as proposal_rules
from cbc.modules.quoting.infrastructure.collections import estimate_lines, proposals, rfis
from cbc.shared.config import settings
from cbc.modules.ops.api import freshness as freshness_settings
from cbc.modules.quoting.domain.freshness import is_lapsed
from cbc.shared.mongo import serialise


VALIDITY_DAYS = 30


NEWLINE = chr(10)


SECTION_TITLES = dict(quote_layout.SECTIONS)


# What every CBC quote excludes: it supplies material, and nothing else. These
# were four lines written for one bid - one excluded "hardware sets ... pending
# the architect", on a hardware quote - printed on every bid there was. What a
# particular bid assumes is generated from its lines (`qualifications`).
DEFAULT_EXCLUSIONS = [
    "Installation, unloading and hoisting are excluded; material is supplied F.O.B. jobsite.",
    "Electrical rough-in and power or low-voltage connections for electrified hardware and "
    "hand dryers are by others.",
]

BY_OTHERS = "Supplied by others"  # quoting.domain.ladder.BY_OTHERS_ALTERNATE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jinja(*, html: bool):
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    return Environment(
        loader=FileSystemLoader(str(settings.templates_dir)),
        autoescape=select_autoescape(["html"]) if html else False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _first_name(name: str | None) -> str:
    return (name or "").split()[0] if (name or "").split() else "there"


def email_draft(
    project: dict[str, Any], data: dict[str, Any], *, recipient: str | None = None, estimator: str | None = None,
    address: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The quotation email, drafted from templates/quotation_email.md - one draft,
    whoever asks: the proposal screen's copy button, the sign-off, the build job.
    `body` is what goes in a mail client; `document` is the whole draft with what
    the estimator should look at first. Nothing here sends anything (NFR-1)."""
    to = recipient or project.get("initiator")
    proposal = data["proposal"]
    flags = data.get("flags") or []
    manual = [
        {"description": line.get("description"), "vendor": line.get("manufacturer"),
         "reason": line.get("costSourceDetail") or "no cost yet"}
        for line in data.get("lines") or []
        if line.get("cost") is None and alternates.counts_in_base(line, alternates.in_base(project.get("alternateSpecs")))
    ]
    out_of_scope = [
        {"item": f"Door {o.get('mark')}", "reason": o.get("scopeReason") or "outside CBC's scope",
         "source_page": (o.get("evidence") or {}).get("sourcePage")}
        for o in data.get("openings") or []
        if o.get("inScope") is False
    ]
    counts = {section["key"]: len(section["lines"]) for section in data["sections"]}
    values = dict(
        initiator_name=to, initiator_email=(address or {}).get("email"), initiator_first_name=_first_name(to),
        quote_number=proposal["proposalNo"], project_name=project.get("name"),
        bid_due_date=project.get("bidDue"), project_location=project.get("location"),
        opening_count=sum(1 for o in data.get("openings") or [] if o.get("inScope") is not False
                          and not o.get("specialty")),
        accessories_count=counts.get("accessories", 0), frp_in_scope=bool(counts.get("frp")),
        grand_total=f"{data['totals']['grandTotal']:,.2f}",
        flags=[f for f in flags if f.get("blocking")] or flags[:12],
        manual_lines=manual, out_of_scope=out_of_scope, rfis=data.get("rfis") or [],
        estimator_name=estimator or (proposal.get("estimator") or {}).get("name") or "CBC Estimating",
        include_review=True,
    )
    template = _jinja(html=False).get_template("quotation_email.md")
    return {
        "to": f"{to} <{values['initiator_email']}>" if to and values["initiator_email"] else to,
        "subject": f"CBC Quotation {proposal['proposalNo']} - {project.get('name')}",
        "body": template.render(**values, body_only=True).strip(),
        "document": template.render(**values, body_only=False),
    }


async def addressed_draft(
    project: dict[str, Any], data: dict[str, Any], *, recipient: str | None = None, estimator: str | None = None,
) -> dict[str, Any]:
    """`email_draft`, addressed to the initiator alone (FR-1b): their address from
    Users, where a name on the bid is all the sign-off has."""
    address = await identity.address_of(recipient or project.get("initiator"))
    return email_draft(project, data, recipient=recipient, estimator=estimator, address=address)


async def write_email_draft(project: dict[str, Any], recipient: str | None, actor: str) -> str:
    """Write the drafted email to the project's review folder, as an artifact."""
    from cbc.shared import storage

    draft = await addressed_draft(project, await proposal_payload(project, internal=True),
                                  recipient=recipient, estimator=actor)
    target = storage.project_dir(project["slug"]) / "review" / "quotation_email_draft.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft["document"], encoding="utf-8")
    return storage.relative(target)


def _money(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def qualifications(lines: list[dict[str, Any]], openings: list[dict[str, Any]],
                   deductive: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """What this bid's quote assumes, substitutes and leaves out, from its own lines -
    said on the quote, where the customer reads the price (FR-17's NOTE among them)."""
    out: list[str] = []
    base = [line for line in lines if alternates.counts_in_base(line, deductive)]
    # A substitution's NOTE prints under its own line (FR-17), not again here.
    others = list(dict.fromkeys(
        f"{line.get('description') or line.get('part')} ({line.get('notes')})" if line.get("notes")
        else str(line.get("description") or line.get("part"))
        for line in lines if line.get("alternateGroup") == BY_OTHERS
    ))
    if others:
        listed = "; ".join(others[:8]) + (f"; and {len(others) - 8} more" if len(others) > 8 else "")
        out.append(f"Not included - the documents assign these to others: {listed}.")
    excluded: dict[str, list[str]] = {}
    for opening in openings:
        if opening.get("inScope") is False and not opening.get("specialty"):
            reason = opening.get("scopeReason") or "outside CBC's scope"
            excluded.setdefault(reason, []).append(str(opening.get("mark") or "?"))
    for reason, marks in excluded.items():
        out.append(f"Not included - {reason}: door{'s' if len(marks) > 1 else ''} {', '.join(marks)}.")
    if any("qty_assumed_one" in (line.get("flags") or []) for line in base):
        out.append("Where the hardware legend states no count, one per opening is included.")
    if any(quote_layout.section_of(line.get("division")) == "frp" for line in base):
        out.append("FRP quantities are taken from the finish plan; field measurement is the installer's.")
    return out


async def _build(project: dict[str, Any], markup: float = 0.0) -> dict[str, Any]:
    # Computed, not stored - see api/services/quote.py. Rendering a proposal used
    # to re-price and re-store the whole quote, and `/pdf` did it twice.
    totals, lines = await quote_service.totals_for(project)
    # A set's items in the legend's order - its key is the set and the item's place
    # in it, 5:01 hinges before 5:06 the wall stop - not the order they were saved in.
    lines = sorted(lines, key=lambda line: quote_layout.natural(line.get("lineKey") or ""))

    rows: list[dict[str, Any]] = []
    marked: list[dict[str, Any]] = []
    for line in lines:
        unit = line.get("sell")
        extended = line.get("extended")
        if markup and unit is not None:
            # The marked-up unit, and its extension from the exact figure - one
            # rounding per line, as the quote itself computes it.
            exact = Decimal(str(unit)) * Decimal(str(1 + markup))
            unit = _money(exact)
            extended = _money(exact * Decimal(str(line.get("qty") or 0)))
        rows.append({
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
            "manufacturer": line.get("manufacturer"),
            "openings": line.get("openings") or [],
            "qtyPerOpening": line.get("qtyPerOpening"),
        })
        # The figures every combination is added from are the printed ones.
        marked.append({**line, "extended": extended, "_row": len(rows) - 1})

    names = [*(project.get("alternates") or []), *(project.get("bidAlternates") or []),
             *(line.get("alternateGroup") for line in lines)]
    rolled = alternates.rollup(
        marked, alternates.specs(project.get("alternateSpecs"), names, project.get("bidAlternates")))

    sections: dict[str, dict[str, Any]] = {}
    for line in rolled["base"]:
        key = quote_layout.section_of(line.get("division"))
        section = sections.setdefault(
            key, {"key": key, "title": SECTION_TITLES[key], "lines": [], "subtotal": 0.0}
        )
        section["lines"].append(rows[line["_row"]])
        section["subtotal"] = round(section["subtotal"] + (line.get("extended") or 0), 2)

    offered = []
    for figure in rolled["alternates"]:
        # Offered beside the bid with its own figure (FR-14): what it adds, or for
        # a deductive alternate the base scope it takes out.
        own = rolled["lines"][figure["name"]]
        shown = own["removes"] if figure["kind"] == "deductive" else own["adds"]
        offered.append({
            "name": figure["name"], "kind": figure["kind"], "priority": figure["priority"],
            "description": figure["description"],
            "lines": [rows[line["_row"]] for line in shown],
            "replaces": [str(line.get("description") or line.get("part") or "").upper()
                         for line in own["removes"]] if figure["kind"] == "substitution" else [],
            "total": figure["net"], "withBase": figure["withBase"],
            "complete": figure["complete"] and bool(shown),
        })

    ordered = [sections[key] for key, _ in quote_layout.SECTIONS if key in sections]
    figures = dict(totals)
    if markup:
        # A markup moves every printed figure, so the totals move with them - the
        # tax on the marked-up subtotal, and the freight kept (it was dropped).
        subtotal = round(sum(s["subtotal"] for s in ordered), 2)
        tax = _money(Decimal(str(subtotal)) * Decimal(str(totals.get("taxRate") or 0)))
        freight = float(totals.get("freight") or 0)
        figures.update(subtotal=subtotal, tax=tax, grandTotal=round(subtotal + tax + freight, 2))
    figures["markup"] = markup
    return {
        "sections": ordered,
        "alternates": offered,
        # Accepted in the bid form's order - each base line taken out once.
        "cumulative": rolled["cumulative"] if len(offered) > 1 else [],
        "overlaps": rolled["overlaps"],
        "totals": figures,
        "lines": lines,
    }


async def export_for_review(project: dict[str, Any]) -> None:
    """Write the estimator's edits in Mongo down to the files the review reads.

    The blocking flags are derived from `extracted/` and `priced/`, while a cost
    typed on the quote grid lands in Mongo. Without this the gate would hold a
    line the estimator had already priced, with Approve disabled and nothing on
    screen to clear it.

    Skipped while a pipeline job is queued or running: the run owns those files,
    and an export would overwrite a pass's output before it was imported.
    """
    if await jobs.active_pipeline_job(project["_id"]):
        return
    # Openings that never reached Mongo would export as an empty take-off over
    # the one on disk - the priced export already refuses that; this one does not.
    if await extraction_openings.list_for_project(project["_id"], limit=1):
        await line_items.export_line_items(project)
    await priced_lines.export_quote_lines(project)


async def proposal_payload(project: dict[str, Any], *, internal: bool = False) -> dict[str, Any]:
    """The proposal as rendered. Takes the project so callers do not re-load it.

    `internal` adds what the document and the email are built from - the lines,
    the openings, the review flags, the open RFIs - which the screen never needs.
    """
    stored = await proposals().find_one({"projectId": project["_id"]}) or {}
    built = await _build(project, stored.get("markup", 0.0))
    lines = built.pop("lines")
    openings = await extraction_openings.list_for_project(project["_id"])

    flagged = await extraction_openings.count(project["_id"], status="needs_look")
    # What another party supplies is not CBC's to price: Evernorth's eight security
    # vendor and frame-seal lines read "8 lines unpriced" on a finished quote.
    unpriced = await estimate_lines().count_documents(
        {"projectId": project["_id"], "cost": None, "alternateGroup": {"$ne": BY_OTHERS_ALTERNATE}}
    )

    # A lapsed sheet means the margin on those lines is not
    # real, and purchasing has to confirm the cost before the proposal leaves
    # the building. It blocks until purchasing confirms or an override is
    # recorded, which is why the override names who made it.
    bands = await freshness_settings.load()
    priced = await estimate_lines().find(
        {"projectId": project["_id"]}, {"multiplierEffectiveDate": 1}
    ).to_list(length=None)
    lapsed = sum(1 for line in priced if is_lapsed(line, bands.catalog_stale_days))
    acknowledged = bool(stored.get("lapsedAcknowledgedBy"))
    lapsed_blocking = bool(lapsed) and not acknowledged

    # The review's own rule set decides which findings hold the hand-off (a line
    # with no cost, a below-band margin with no reason, ...). Derived from the
    # files on every read, so a caller that wants the estimator's latest edits
    # counted exports them first - see MarkComplete. Reads the tier sheet
    # synchronously, hence the thread.
    flags = await asyncio.to_thread(review.read_flags, project["slug"])
    blocking_flags = [f for f in flags if f.get("blocking")]
    notes = []
    if lapsed_blocking:
        notes.append(
            f"{lapsed} line(s) are priced from a sheet past its review window. "
            "Purchasing has to confirm the cost, or an override has to be recorded, "
            "before this is handed off."
        )
    if blocking_flags:
        notes.append(
            f"{len(blocking_flags)} review flag(s) block approval: "
            + "; ".join(f"{f.get('opening') or 'bid'} - {f.get('note')}" for f in blocking_flags)
        )
    # FR-14: an addendum or a new version after the proposal was issued makes
    # this the next revision - a draft until approved again, superseding that one.
    revision = proposal_rules.revision(project, stored)
    number = stored.get("proposalNo") or f"Q-{project['code'].split('-')[-1]}"
    superseded = revision["supersedes"]
    if revision["reissue"]:
        notes.append(
            f"The bid changed after the proposal issued {_day(superseded.get('at'))}: this is revision "
            f"{revision['number']}, a draft until it is approved again. Approving it supersedes "
            f"{proposal_rules.numbered(number, superseded.get('revision') or 0)}."
        )

    return {
        "proposal": {
            "proposalNo": proposal_rules.numbered(number, revision["number"]),
            "revision": revision["number"],
            "supersedes": {
                "proposalNo": proposal_rules.numbered(number, superseded.get("revision") or 0),
                "issuedOn": _day(superseded.get("at")),
            } if superseded else None,
            "date": (stored.get("date") or date.today()).isoformat()
            if not isinstance(stored.get("date"), str)
            else stored["date"],
            "validityDays": VALIDITY_DAYS,
            "customer": stored.get("customer") or {"name": project.get("gc")},
            "salesRep": stored.get("salesRep") or {"name": project.get("initiator")},
            "estimator": stored.get("estimator") or {},
            "markup": stored.get("markup", 0.0),
            # An estimator who removed every exclusion meant none, not the defaults.
            "exclusions": stored["exclusions"] if stored.get("exclusions") is not None else DEFAULT_EXCLUSIONS,
            "signoff": stored.get("signoff") or [],
            "sentAt": stored.get("sentAt"),
            # Until an estimator approves it (MarkComplete), it prints as a draft -
            # and again once the bid changes under it, until it is re-approved.
            "draft": not stored.get("approvedBy") or revision["reissue"],
        },
        "project": serialise(project),
        **built,
        "qualifications": qualifications(lines, openings, alternates.in_base(project.get("alternateSpecs"))),
        # The rating each door carries, so a hardware group can print its doors'.
        "doorRatings": {
            str(o.get("mark")): str(o.get("fireRating")).strip()
            for o in openings if o.get("mark") and str(o.get("fireRating") or "").strip()
        },
        "readiness": {
            "flaggedLineItems": flagged,
            "unpricedQuoteLines": unpriced,
            "lapsedLines": lapsed,
            "lapsedAcknowledgedBy": stored.get("lapsedAcknowledgedBy"),
            "blockingFlags": blocking_flags,
            "blocking": lapsed_blocking or bool(blocking_flags),
            "note": (
                " ".join(notes)
                or "Advisory flags are shown, not blocked - the estimator decides."
            ),
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
        **({
            "lines": lines, "openings": openings, "flags": flags,
            "rfis": [r.get("question") for r in await rfis().find(
                {"bidRequestId": project["_id"], "status": "open"}).to_list(200) if r.get("question")],
        } if internal else {}),
    }


def _printable(row: dict[str, Any]) -> dict[str, Any]:
    return quote_layout.line(
        description=row["description"],
        part_number=row["part"],
        quantity=row["qty"],
        sale_ea=row["unitPrice"],
        ext_price=row["extPrice"],
        group=row.get("group"),
        division=row.get("division"),
        substitution_note=row.get("substitutionNote"),
        price_status=row.get("priceStatus"),
        manufacturer=row.get("manufacturer"),
        openings=row.get("openings"),
        qty_per_opening=row.get("qtyPerOpening"),
    )


def _day(value: Any) -> str | None:
    if not value:
        return None
    return value.date().isoformat() if isinstance(value, datetime) else str(value)[:10]


def render_html(project: dict[str, Any], data: dict[str, Any], autoprint: bool) -> str:
    """The quotation document, from the payload: what the screen shows, the PDF prints
    and the build job files - one layout (`quote_layout`), one template."""
    proposal, totals = data["proposal"], data["totals"]
    # Grouped as the take-off priced it - a hardware set for the doors that cite
    # it, each group naming those doors and their ratings - with the substitution
    # NOTE under the line it is about (FR-7, FR-17).
    blocks = quote_layout.blocks(
        [_printable(row) for section in data["sections"] for row in section["lines"]],
        data.get("doorRatings"),
    )
    offered = [
        {"name": alt["name"], "kind": alt.get("kind") or "additive", "description": alt.get("description"),
         "replaces": alt.get("replaces") or [], "total": alt["total"], "with_base": alt.get("withBase"),
         "complete": alt.get("complete", all(row["extPrice"] is not None for row in alt["lines"])),
         "lines": [_printable(row) for row in alt["lines"]]}
        for alt in data.get("alternates") or []
    ]
    html = _jinja(html=True).get_template("quotation.html").render(
        quote_number=proposal["proposalNo"],
        quote_date=proposal["date"],
        validity_days=VALIDITY_DAYS,
        project={
            "name": project.get("jobName") or project.get("name"),
            "location": project.get("location"),
            "architect": project.get("architect"),
            "bid_due_date": _day(project.get("bidDue")),
            "order_number": project.get("p21OrderNo"),
            # Bid forms ask for every addendum acknowledged by number (FR-14).
            "addenda": [{"number": a.get("number"), "issued_on": _day(a.get("issuedOn"))}
                        for a in sorted(project.get("addenda") or [], key=lambda a: a.get("number") or 0)],
            "version": project.get("version"),
        },
        customer={"gc": (proposal.get("customer") or {}).get("name") or project.get("gc"),
                  "initiator": project.get("initiator")},
        estimator=proposal.get("estimator") or {},
        notes=proposal["exclusions"],
        qualifications=data.get("qualifications") or [],
        blocks=blocks,
        alternates=offered,
        # "Base bid with Alternate 1 + Alternate 2", in the bid form's order.
        cumulative=[{"label": " + ".join(c["through"] for c in data["cumulative"][: n + 1]), "total": c["total"]}
                    for n, c in enumerate(data.get("cumulative") or [])],
        totals={
            "subtotal": totals["subtotal"],
            "freight": totals.get("freight"),
            "project_state": totals.get("taxJurisdiction"),
            "tax_rate": totals.get("taxRate"),
            "tax": totals.get("tax"),
            "tax_exempt": bool(totals.get("taxExempt")),
            "grand_total": totals["grandTotal"],
        },
        draft=proposal.get("draft", True),
        # "Revision 1 - supersedes Q-1234 issued 2026-10-02" (FR-14).
        supersedes=proposal.get("supersedes"),
        unpriced=data["readiness"].get("unpricedQuoteLines") or 0,
        flag_count=data["readiness"]["flaggedLineItems"],
    )
    if autoprint:
        html += "<script>window.addEventListener('load',()=>window.print())</script>"
    return html
