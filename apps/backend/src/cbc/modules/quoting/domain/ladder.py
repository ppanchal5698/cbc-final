"""The cost of one take-off line, by the ladder - decided in code.

  0. Allegion -> the base line is the Hager equal, for the estimator to name; the
     specified Allegion part is an alternate priced by the distributor (Banner /
     SecLock). Never priced off a list.
  1. P21 last PO
  2. Special net (CBC's negotiated sheet)
  3. Catalog row
  4. Price book list x the vendor's multiplier for that section
  5. Division 10 only: the part's direct equal in a brand CBC prices, from the
     cross-reference, with a substitution note for the GC (Matrix 6.4)
  6. Otherwise MANUAL, saying what each rung found.

Each rung takes a row only when the matcher says the row is this item; a rung
that finds several rows at different prices says so and the next rung is not
tried, because a cheaper or dearer list price for an item CBC holds a net for
would be wrong in a way nobody sees. A sheet past its review window is skipped,
and the line says why.

Pure: the line and the bid's rows in, the file rows out. Every number comes from
a row the detail names (NFR-3); the arithmetic is pricing's.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from cbc.modules.quoting.domain import matcher
from cbc.modules.quoting.domain.takeoff import Line

ALLEGION_ALTERNATE = "Allegion as specified"
BY_OTHERS_ALTERNATE = "Supplied by others"
_US_FINISH = re.compile(r"\bUS\d{1,3}[A-Z]?\b", re.I)
_PART_LIKE = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9][A-Z0-9\-/.]*$", re.I)


def vendor_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


@dataclass
class Sources:
    """Everything the ladder reads, fetched once for the whole bid."""

    models: Callable[[str], list[str]]  # the forms of a part to try, most specific first
    finish: matcher.FinishKey
    lapsed: Callable[[Any], bool]  # a dated sheet past the review window
    cost_from_list: Callable[[float, float], float]
    multiplier_category: Callable[[str, Any], str | None]
    special_nets: list[dict[str, Any]] = field(default_factory=list)
    special_net_effective: str | None = None
    catalog: list[dict[str, Any]] = field(default_factory=list)
    book: list[dict[str, Any]] = field(default_factory=list)
    books: dict[str, dict[str, Any]] = field(default_factory=dict)  # priceBookId -> {name, effective}
    tiers: dict[str, dict[str, Any]] = field(default_factory=dict)  # vendor key -> tier record
    last_po: Callable[[str, str | None], dict[str, Any] | None] | None = None
    special_margin: tuple[float, str] | None = None
    priced_at: str = ""
    equals: dict[str, Any] = field(default_factory=dict)  # the Division 10 direct-equal matrix
    equal_rows: list[dict[str, Any]] = field(default_factory=list)  # catalog rows of the brands it names
    adders: list[dict[str, Any]] = field(default_factory=list)  # Hager list adders: {name, list_adder}
    hardware_equals: dict[str, dict[str, Any]] = field(default_factory=dict)  # part key -> the equal named for it


# How a legend says each Hager list adder (NR-4). One added in Settings without an
# entry here is named when the legend uses every word of its name.
_ADDER_SAID = {
    "sfic construction core included with lockset": re.compile(r"\bSFIC\b"),
    "lead lined": re.compile(r"\bLEAD[\s-]*LINED\b"),
    "extended lip asa strike": re.compile(r"\bEXT(?:ENDED|\.)?[\s-]*LIP\b"),
    "tactile warning": re.compile(r"\bTACTILE\b"),
    "3/4 inch latchbolt": re.compile(r"3/4\s*(?:\"|IN(?:CH)?\.?)?\s*(?:THROW\s*)?LATCH"),
    "anti-microbial (26d finish only)": re.compile(r"\bANTI[\s-]*MICROBIAL\b"),
}
_ADDER_FILLER = {"INCLUDED", "WITH", "INCH", "ONLY", "FINISH", "THE", "AND", "FOR"}


def named_adders(text: str, adders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The list adders a legend asks for on this item - never applied here. CBC's
    rule is that adding one is a deliberate, recorded act; the estimator does it."""
    said = str(text or "").upper()
    words = set(re.split(r"[^A-Z0-9/]+", said))
    found = []
    for adder in adders:
        name = str(adder.get("name") or "")
        pattern = _ADDER_SAID.get(name.strip().lower())
        if pattern is not None:
            named = bool(pattern.search(said))
        else:
            wanted = {w for w in re.split(r"[^A-Z0-9/]+", re.sub(r"\([^)]*\)", "", name.upper()))
                      if len(w) > 1 and w not in _ADDER_FILLER}
            named = bool(wanted) and wanted <= words
        if named and adder.get("list_adder") is not None:
            found.append({"name": name, "list_adder": float(adder["list_adder"])})
    return found


def _desc_finish(text: Any) -> str | None:
    found = _US_FINISH.search(str(text or ""))
    return found.group(0) if found else None


def guess_part(line: Line) -> str | None:
    """A legend that put the model in its description: the first token that looks
    like a part number and is not a finish code."""
    for token in re.split(r"[\s,;()]+", line.description or ""):
        if _PART_LIKE.match(token) and not _US_FINISH.fullmatch(token) and not matcher.dimensions(token):
            return token
    return None


def _candidates_note(rows: Iterable[dict[str, Any]], show: Callable[[dict[str, Any]], str]) -> str:
    rows = list(rows)
    shown = "; ".join(show(r) for r in rows[:3])
    return shown + (f"; +{len(rows) - 3} more" if len(rows) > 3 else "")


def _row(line: Line, src: Sources) -> dict[str, Any]:
    out: dict[str, Any] = {
        "line_id": line.key,
        "group": line.group,
        "group_type": "accessories" if line.division.startswith("10") else "frp" if line.division.startswith(("06", "09")) else "door",
        "division": line.division,
        "part_number": line.part,
        "description": line.description or line.part,
        "manufacturer": line.manufacturer,
        "finish": line.finish,
        "quantity": line.qty,
        "unit": line.unit,
        "qty_per_opening": line.qty_per_opening,
        "openings": list(line.openings),
        "source_file": line.source_file,
        "source_page": line.source_page,
        "cost": None,
        "cost_source": "MANUAL",
        "price_status": "NEEDS_JUDGMENT",
        "priced_at": src.priced_at,
        "flags": list(line.flags),
    }
    if line.alternate:
        out["alternate_group"] = BY_OTHERS_ALTERNATE
        out["notes"] = line.alternate
    elif line.alternate_group:
        out["alternate_group"] = line.alternate_group  # the doors' bid alternate (FR-14)
    if src.special_margin:
        out["margin"], out["margin_override_reason"] = src.special_margin
    return out


def _priced(row: dict[str, Any], cost: float, source: str, detail: str, **provenance: Any) -> dict[str, Any]:
    row.update(cost=round(float(cost), 2), cost_source=source, cost_source_detail=detail,
               price_status="PRICED", **{k: v for k, v in provenance.items() if v is not None})
    return row


def _rung_special_net(spec: matcher.Spec, models: list[str], src: Sources) -> matcher.Choice:
    return matcher.choose(
        spec, src.special_nets, models=models,
        model_of=lambda r: r.get("part_number"), finish_of=lambda r: _desc_finish(r.get("description")),
        size_of=lambda r: r.get("description"), price_of=lambda r: r.get("net_price"),
        describe=lambda r: r.get("description"), finish=src.finish,
    )


def _rung_catalog(spec: matcher.Spec, models: list[str], vendor: str, src: Sources) -> matcher.Choice:
    rows = [r for r in src.catalog if not vendor or r.get("vendorKey") == vendor]
    return matcher.choose(
        spec, rows, models=models,
        model_of=lambda r: r.get("part"), finish_of=lambda r: _desc_finish(r.get("description")),
        size_of=lambda r: f"{r.get('part') or ''} {r.get('description') or ''}", price_of=lambda r: r.get("cost"),
        describe=lambda r: r.get("description"), finish=src.finish,
    )


def _rung_book(spec: matcher.Spec, models: list[str], vendor: str, src: Sources) -> matcher.Choice:
    rows = [r for r in src.book if not vendor or r.get("vendor") == vendor]
    return matcher.choose(
        spec, rows, models=models,
        model_of=lambda r: r.get("model"), finish_of=lambda r: r.get("finish"),
        size_of=lambda r: r.get("size"), price_of=lambda r: r.get("listPrice"),
        describe=lambda r: f"{r.get('description') or ''} {r.get('table') or ''}", finish=src.finish,
    )


def _show_net(r: dict[str, Any]) -> str:
    return f"{r.get('item_code')} {r.get('description')} ${r.get('net_price')}"


def _show_catalog(r: dict[str, Any]) -> str:
    return f"{r.get('manufacturer')} {r.get('part')} ${r.get('cost')}"


def _show_book(r: dict[str, Any]) -> str:
    return f"{r.get('model')} {r.get('size') or ''} {r.get('finish') or ''} ${r.get('listPrice')} p.{r.get('page')}".replace("  ", " ")


MAX_CANDIDATES = 8  # rows offered to whoever chooses; more than this, the legend says too little
# Where an undecided row keeps its candidates until they are chosen among. Not a
# field of the priced file: the job takes it off before it writes.
UNDECIDED = "_undecided"


def _undecided(row: dict[str, Any], label: str, choice: matcher.Choice, show) -> list[dict[str, Any]]:
    """This item, at several prices: someone picks, and no cheaper or dearer rung is
    tried in the meantime. `UNDECIDED` keeps the rows for whoever does."""
    row["cost_source_detail"] = (f"{label}: {choice.reason}: {_candidates_note(choice.candidates, show)}"
                                 " - an estimator picks which")
    row["flags"].append("ambiguous_match")
    row[UNDECIDED] = {"rung": label, "candidates": choice.candidates[:MAX_CANDIDATES],
                      "shown": [show(r) for r in choice.candidates[:MAX_CANDIDATES]],
                      # the row before anyone chose, so each close match prices from it
                      "base": {**row, "flags": list(row["flags"])}}
    return [row]



def _from_net(row: dict[str, Any], net: dict[str, Any], src: Sources, tried: list[str]) -> dict[str, Any] | None:
    """The line priced at a special net - or None, said in `tried`, when the sheet is past review."""
    if src.lapsed(src.special_net_effective):
        tried.append(f"special net {net.get('item_code')} skipped - the sheet dated "
                     f"{src.special_net_effective} is past review")
        return None
    return _priced(
        row, net["net_price"], "SPECIAL_NET",
        f"special-net sheet ({net.get('section') or 'Hager special nets'}) item {net.get('item_code')} "
        f"- {net.get('description')}",
        part_number=net.get("part_number") or row.get("part_number"), manufacturer="Hager",
        multiplier_effective_date=src.special_net_effective,
        price_book_version=f"Hager special-net sheet, effective {src.special_net_effective}",
    )


def _from_book(row: dict[str, Any], entry: dict[str, Any], src: Sources, vendor: str,
               tried: list[str]) -> dict[str, Any] | None:
    """The line priced at a price-book row times its section's multiplier - or None,
    said in `tried`, when no multiplier covers the section or a sheet is past review."""
    entry_vendor = entry.get("vendor") or vendor
    category = src.multiplier_category(entry_vendor, entry.get("section"))
    tier = src.tiers.get(entry_vendor) or {}
    multiplier = (tier.get("categories") or {}).get(category) if category else tier.get("multiplier")
    effective = entry.get("effective")
    where = (f"{entry.get('file')} p.{entry.get('page')} (printed {entry.get('printedPage')}) "
             f"{entry.get('model')} {entry.get('size') or ''} {entry.get('finish') or ''}").replace("  ", " ")
    if multiplier is None:
        tried.append(f"price book {where} list ${entry.get('listPrice')}, but no {entry_vendor} multiplier "
                     f"covers its section {entry.get('section')!r}")
        return None
    if src.lapsed(tier.get("effective_date")) or src.lapsed(effective):
        tried.append(f"price book {where} skipped - the sheet or its multiplier is past review")
        return None
    cost = src.cost_from_list(float(entry["listPrice"]), float(multiplier))
    book = src.books.get(str(entry.get("priceBookId"))) or {}
    by_model = entry.get("readBy") == "model"  # a page the reader could not parse
    priced = _priced(
        row, cost, "LIST_X_MULTIPLIER",
        f"{where} list ${entry['listPrice']:.2f} x {category or 'account'} {multiplier:g} -> ${cost:.2f}"
        + (" - the list price was read off the page by the model; confirm it against the sheet" if by_model else ""),
        part_number=entry.get("model"), manufacturer=row.get("manufacturer") or entry_vendor.title(),
        list_price=entry.get("listPrice"), multiplier=float(multiplier), multiplier_tier=category or "all",
        multiplier_effective_date=tier.get("effective_date") or effective,
        price_book_version=f"{book.get('name') or entry.get('file')}, effective {effective}",
        catalog_page=entry.get("page"),
    )
    if by_model:
        priced["flags"].append("price_read_by_model")
    return priced


def _price_candidate(row: dict[str, Any], index: int, src: Sources) -> dict[str, Any] | None:
    """`row` priced at one of its undecided candidates, through the rung that found
    them. None when there is no such candidate or its sheet cannot be priced from."""
    pending = row.get(UNDECIDED) or {}
    candidates = pending.get("candidates") or []
    if not 0 <= index < len(candidates):
        return None
    chosen, tried = candidates[index], []
    rung = pending.get("rung")
    if rung == "special net":
        return _from_net(row, chosen, src, tried)
    if rung == "catalog":
        return _from_catalog(row, chosen, src, row.get("manufacturer"), tried)
    return _from_book(row, chosen, src, vendor_key(row.get("manufacturer")), tried)


def price_choice(row: dict[str, Any], index: int, reason: str, src: Sources) -> dict[str, Any] | None:
    """An undecided row priced at the candidate someone chose - through the same
    rung, with the same checks - and saying who chose it and why. None when the
    choice is not one of the rows, or its sheet cannot be priced from."""
    priced = _price_candidate(row, index, src)
    if priced is None:
        return None
    priced[UNDECIDED]["chosen"] = index
    priced["flags"] = [f for f in priced["flags"] if f != "ambiguous_match"] + ["model_chose_match"]
    priced["cost_source_detail"] += (f"; chosen among {len(priced[UNDECIDED]['candidates'])} by the model ({reason.strip()})"
                                     " - an estimator confirms it")
    return priced


def _as_matched(priced: dict[str, Any], choice: matcher.Choice, base: dict[str, Any], rung: str,
                show: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    """Say when the row is a size of the series the legend named, not the part
    itself - and keep the series' other rows beside it, so the estimator has the
    close matches FR-8 offers on a line in the review band."""
    if choice.series:
        priced["flags"].append("series_match")
        rows = (choice.nearby or choice.candidates)[:MAX_CANDIDATES]
        at = next((i for i, candidate in enumerate(rows) if candidate is choice.row), None)
        if len(rows) > 1 and at is not None:
            priced[UNDECIDED] = {"rung": rung, "candidates": rows, "shown": [show(r) for r in rows],
                                 "base": base, "chosen": at}
    return priced


# FR-8: "confidence score per match". The order of the evidence, not a measured
# probability: CBC's own purchase of the part, then its special net, a catalog or
# price-book row for the part, a size of its series or a brand's equal, a row the
# model chose among several, rows nobody has chosen among. ponytail: calibrate
# against the estimators' quotes once ground_truth/ arrives.
_SOURCE_CONFIDENCE = {"P21_LAST_PO": 0.95, "SPECIAL_NET": 0.95, "CATALOG_BASELINE": 0.92,
                      "LIST_X_MULTIPLIER": 0.90}
_FLAG_CONFIDENCE = (("ambiguous_match", 0.60), ("model_chose_match", 0.75), ("direct_equal", 0.80),
                    ("series_match", 0.80), ("price_read_by_model", 0.80), ("hardware_equal", 0.80))


def match_confidence(row: dict[str, Any]) -> float | None:
    """How sure the match is; None for a line that is not matched to a row at all -
    a door or frame from its supplier, a cost typed by hand, a part as specified
    that its distributor or vendor quotes (Evernorth's Schlage locks read "pick
    match" with nothing to pick)."""
    flags = row.get("flags") or []
    for flag, score in _FLAG_CONFIDENCE:
        if flag in flags:
            return score
    if row.get("cost_source") in ("DISTRIBUTOR_MANUAL", "VENDOR_RFQ"):
        return None
    if row.get("cost") is None:
        return 0.0 if row.get("part_number") else None
    return _SOURCE_CONFIDENCE.get(str(row.get("cost_source") or ""))


CLOSE_MATCHES = 3  # FR-8: "offer 3 close matches"
# What choosing one sets on the line: the part, its cost, and where that came from.
_MATCH_FIELDS = ("part_number", "manufacturer", "cost", "cost_source", "cost_source_detail", "list_price",
                 "multiplier", "multiplier_tier", "multiplier_effective_date", "price_book_version")


def close_matches(row: dict[str, Any], src: Sources) -> list[dict[str, Any]]:
    """FR-8: the rows an estimator may choose among for an undecided line, each
    priced through the same rung and checks - the model's pick first when it made
    one, so the line's own match is among them and can be chosen back."""
    pending = row.get(UNDECIDED) or {}
    base = pending.get("base")
    if not base:
        return []
    order = list(range(len(pending.get("candidates") or [])))
    if pending.get("chosen") in order:
        order.remove(pending["chosen"])
        order.insert(0, pending["chosen"])
    found: list[dict[str, Any]] = []
    for index in order:
        trial = _price_candidate({**base, "flags": list(base["flags"]), UNDECIDED: pending}, index, src)
        if trial is not None:
            found.append({"label": pending["shown"][index], **{k: trial.get(k) for k in _MATCH_FIELDS}})
        if len(found) == CLOSE_MATCHES:
            break
    return found


def _from_catalog(row: dict[str, Any], catalog_row: dict[str, Any], src: Sources, manufacturer: str | None,
                  tried: list[str]) -> dict[str, Any] | None:
    """The line priced at a catalog row - or None, said in `tried`, when its book is past review."""
    book = src.books.get(str(catalog_row.get("priceBookId"))) or {}
    effective = book.get("effective")
    if src.lapsed(effective):
        tried.append(f"catalog row {catalog_row.get('part')} skipped - {book.get('name') or 'its price book'} "
                     f"dated {effective} is past review")
        return None
    basis = (f"; list ${catalog_row['listPrice']} x {catalog_row['multiplier']}"
             if catalog_row.get("listPrice") and catalog_row.get("multiplier") else "")
    return _priced(
        row, catalog_row["cost"], "CATALOG_BASELINE",
        f"product catalog ({catalog_row.get('seedSource') or 'catalog'}) {catalog_row.get('manufacturer')} "
        f"part {catalog_row.get('part')}{basis}",
        part_number=catalog_row.get("part"), manufacturer=catalog_row.get("manufacturer") or manufacturer,
        list_price=catalog_row.get("listPrice"), multiplier=catalog_row.get("multiplier") or None,
        multiplier_effective_date=effective,
        price_book_version=f"{book.get('name')}, effective {effective}" if book.get("name") else None,
    )


_EQUAL_BRANDS = {"Bobrick": "bobrick", "ASI": "asi", "Bradley": "bradley", "Gamco": "gamco"}


def _norm(text: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _matrix_row(part: str, equals: dict[str, Any]) -> dict[str, Any] | None:
    """The cross-reference row naming this part, in whichever column and however
    its brand's catalog writes it (`B-212`, `10-0714`, `G-2116`)."""
    prefixes = [p for p in (equals.get("catalog_prefixes") or {}).values() if p]
    wanted = _norm(part)
    for entry in equals.get("rows") or []:
        for value in entry.values():
            if value and wanted in {_norm(value), *(_norm(prefix + value) for prefix in prefixes)}:
                return entry
    return None


def _direct_equal(row: dict[str, Any], line: Line, spec: matcher.Spec, src: Sources,
                  tried: list[str]) -> dict[str, Any] | None:
    """A Division 10 part CBC cannot price, offered as the direct equal CBC can buy
    for least - the GC approves a direct equal before it is ordered, so the cost is
    what decides between them, and the matrix's brand order only breaks a tie. (CBC
    buys ASI at 0.375 of list and Bradley at 0.53 on current programs; Bobrick's
    tier is 1.0 and dated 2020 - first in the matrix was the dearest.)"""
    entry = _matrix_row(spec.part or "", src.equals)
    if entry is None:
        return None
    prefixes = src.equals.get("catalog_prefixes") or {}
    specified = vendor_key(line.manufacturer)
    best: tuple[dict[str, Any], dict[str, Any]] | None = None
    for brand in src.equals.get("preferred_brands") or []:
        value, key = entry.get(brand), _EQUAL_BRANDS.get(brand, vendor_key(brand))
        if not value or key == specified:
            continue
        form = (prefixes.get(brand) or "") + value
        choice = _rung_catalog(matcher.Spec(part=form, manufacturer=brand, finish=spec.finish, text=spec.text),
                               [form, value], key, replace(src, catalog=src.equal_rows))
        if choice.row is None:
            continue
        # Each brand is priced on its own copy: `_priced` writes into the row it is given.
        priced = _from_catalog({**row, "flags": list(row["flags"])}, choice.row, src, brand, tried)
        if priced is not None and (best is None or priced["cost"] < best[0]["cost"]):
            best = (priced, choice.row)
    if best is None:
        tried.append(f"the cross-reference lists equals for {spec.part}, but none the catalog prices")
        return None
    priced, chosen = best
    specified_as = " ".join(v for v in (line.manufacturer, line.part) if v)
    # The NOTE the quote prints (FR-17): what is offered for what was specified.
    # Why this equal - no price for the specified part, the lowest cost of those
    # CBC carries - is CBC's own business, and stays in the cost detail.
    priced["substitution_note"] = (
        f"{chosen.get('manufacturer')} {chosen.get('part')} is offered as a direct equal to the specified "
        f"{specified_as}, subject to approval before ordering.")
    priced["cost_source_detail"] += (
        f"; {specified_as} specified and unpriced - the cross-reference's equal CBC buys for least")
    priced["flags"].append("direct_equal")
    return priced


def _equal_on_file(line: Line, src: Sources) -> dict[str, Any] | None:
    """The equal an estimator named for this part before, by its most specific form:
    `4040XP-RW/PA` finds the one named for `4040XP`."""
    for form in src.models(line.part or "") if line.part else ():
        found = src.hardware_equals.get(re.sub(r"[^A-Z0-9]", "", form.upper()))
        if found and found.get("equal_part"):
            return found
    return None


def _allegion_rows(line: Line, src: Sources) -> list[dict[str, Any]]:
    """The Hager equal as the base line, and the Allegion part as specified beside it."""
    specified = " ".join(v for v in (line.manufacturer, line.part, line.description) if v)
    equal = _equal_on_file(line, src)
    if equal is not None:
        # The equal an estimator named on an earlier quote, priced like any part.
        maker = equal.get("equal_manufacturer") or "Hager"
        offered = replace(line, part=equal["equal_part"], manufacturer=maker,
                          description=f"{maker} {equal['equal_part']} - equal to {specified}")
        [base] = _ladder(offered, src)
        base["cost_source_detail"] += (f"; the equal on file for the specified {line.manufacturer or 'Allegion'} "
                                       f"{line.part}" + (f", named by {equal['named_by']}" if equal.get("named_by") else ""))
        base["substitution_note"] = (f"{maker} {equal['equal_part']} offered for the specified {specified}; the "
                                     "product as specified is priced as an alternate.")
        base["flags"].append("hardware_equal")
    else:
        base = _row(line, src)
        base.update(
            part_number=None, manufacturer="Hager",
            description=f"Hager equal to {specified}",
            cost_source_detail=(f"Allegion specified ({specified}): price the Hager equal - no equal is on "
                                "file for this part yet, so an estimator names it"),
            substitution_note=(f"Hager equal offered for the specified {specified}; the product as specified "
                               "is priced as an alternate."),
        )
        base["flags"].append("allegion_equal_needed")
    # The Allegion part as specified is offered instead of the equal: a substitution,
    # which takes this line out of the bid it is accepted with.
    base["deducted_by"] = [ALLEGION_ALTERNATE]
    alternate = _row(line, src)
    alternate.update(
        line_id=f"{line.key}:allegion", cost_source="DISTRIBUTOR_MANUAL", alternate_group=ALLEGION_ALTERNATE,
        cost_source_detail="Allegion - distributor quote (Banner Solutions / SecLock); never priced off a list",
    )
    alternate["flags"].append("allegion_distributor_manual")
    return [base, alternate]


def price(line: Line, src: Sources) -> list[dict[str, Any]]:
    """The file rows for one take-off line: one, or two for an Allegion part - each
    carrying the list adders its legend names, for the estimator to add (NR-4)."""
    rows = _price_rows(line, src)
    named = named_adders(f"{line.description} {line.text}", src.adders) if line.division.startswith("08") else []
    for row in rows if named else ():
        row["adder_candidates"] = named
        row["flags"].append("adder_named")
    return rows


def _price_rows(line: Line, src: Sources) -> list[dict[str, Any]]:
    if matcher.is_allegion(line.part, line.description, manufacturer=line.manufacturer):
        if line.alternate:  # another party supplies it: there is no equal for CBC to find
            row = _row(line, src)
            row.update(cost_source="DISTRIBUTOR_MANUAL",
                       cost_source_detail="Allegion, supplied by others per the schedule - not CBC's to price")
            return [row]
        return _allegion_rows(line, src)
    return _ladder(line, src)


def _ladder(line: Line, src: Sources) -> list[dict[str, Any]]:
    """Rungs 1 to 6 for a part CBC can price: always one row."""
    row = _row(line, src)
    if line.alternate and not line.part:
        # Evernorth's card readers are the security vendor's and its seals come with
        # the aluminum frames: there is no part for CBC to name, and nothing to price.
        row["cost_source_detail"] = f"{line.alternate} - not CBC's to price"
        return [row]
    if line.unit == "SET" and not line.part:
        # A whole set to price by hand: the take-off already says why.
        row["cost_source_detail"] = f"{line.description}; price the set from the sheet"
        # A whole set the legend did not itemise carries its doors' notes; an item
        # the legend sells as a SET (seals) carries only its own words.
        if line.text and {"hardware_set_not_in_legend", "hardware_set_not_itemised"} & set(line.flags):
            row["cost_source_detail"] += f"; the schedule says {line.text}"
        return [row]
    if line.key.startswith(("door:", "frame:")):
        # A door or frame is priced from its supplier - P21's last PO for the same
        # specification, or a quote - never off a hardware list, and never by a part
        # number guessed out of "3'-0" X 7'-0"". A size past stock is a vendor quote
        # (requirements 5.2, 7.2).
        if "custom_size" in line.flags:
            row.update(cost_source="VENDOR_RFQ", cost_source_detail=(
                f"{line.description}: a size past stock (over 8'-0\") - request a quote from the door supplier"))
        else:
            row["cost_source_detail"] = (f"{line.description}: price from the door supplier - P21's last PO "
                                         "for this specification, or a quote")
        if line.text:
            row["cost_source_detail"] += f"; the schedule says {line.text}"
        return [row]
    # Only a door hardware legend writes the model into its description; a
    # specialty row's description is a location (`6/A2.2`), not a part.
    part = line.part or (guess_part(line) if line.division.startswith("08") else None)
    if not part:
        row["cost_source_detail"] = ("no part number on the legend - name the part, then price it"
                                     if line.division.startswith("08")
                                     else "no product named on the drawings - name it, then price it")
        row["flags"].append("no_part_number")
        return [row]
    if line.qty is None:
        row["flags"].append("quantity_unread")

    vendor = vendor_key(line.manufacturer)
    models = src.models(part)
    spec = matcher.Spec(part=part, manufacturer=line.manufacturer, finish=line.finish, text=line.text)
    tried: list[str] = []

    # 1. P21 last PO.
    if src.last_po is not None:
        po = src.last_po(part, line.manufacturer)
        if po and po.get("cost") is not None:
            priced = _priced(row, po["cost"], "P21_LAST_PO", po.get("detail") or "P21 last PO",
                             last_po_date=po.get("po_date"))
            if po.get("status") == "aging":
                priced["flags"].append("cost_aging")  # sold 6-12 months ago: check for an increase
            return [priced]
        if po and po.get("context"):
            tried.append(po["context"])

    # 2. Special net - CBC's sheet is Hager's.
    if vendor in ("", "hager"):
        choice = _rung_special_net(spec, models, src)
        if choice.ambiguous:
            return _undecided(row, "special net", choice, _show_net)
        if choice.candidates and choice.row is None:
            tried.append(f"special net: {choice.reason}")
        if choice.row is not None:
            base = {**row, "flags": list(row["flags"])}  # before pricing writes into it
            priced = _from_net(row, choice.row, src, tried)
            if priced is not None:
                return [_as_matched(priced, choice, base, "special net", _show_net)]

    # 3. Catalog row.
    choice = _rung_catalog(spec, models, vendor, src)
    if choice.ambiguous:
        return _undecided(row, "catalog", choice, _show_catalog)
    catalog_row = choice.row
    if choice.candidates and catalog_row is None:
        tried.append(f"catalog: {choice.reason}")
    if catalog_row is not None:
        base = {**row, "flags": list(row["flags"])}  # before pricing writes into it
        priced = _from_catalog(row, catalog_row, src, line.manufacturer, tried)
        if priced is not None:
            return [_as_matched(priced, choice, base, "catalog", _show_catalog)]

    # 4. Price book list x the multiplier for its section.
    choice = _rung_book(spec, models, vendor, src)
    if choice.ambiguous:
        return _undecided(row, "price book", choice, _show_book)
    if choice.candidates and choice.row is None:
        tried.append(f"price book: {choice.reason}")
    if choice.row is not None:
        base = {**row, "flags": list(row["flags"])}  # before pricing writes into it
        priced = _from_book(row, choice.row, src, vendor, tried)
        if priced is not None:
            return [_as_matched(priced, choice, base, "price book", _show_book)]

    # 5. Division 10: the direct equal CBC can price.
    if line.division.startswith("10") and src.equals:
        offered = _direct_equal(row, line, spec, src, tried)
        if offered is not None:
            return [offered]

    # 6. Nothing the ladder can stand behind.
    tried.append(f"no special net, catalog row or price-book row for {part}"
                 + (f" ({line.manufacturer})" if line.manufacturer else ""))
    via = [str(d) for d in (src.tiers.get(vendor) or {}).get("distributors") or [] if d]
    if via:  # purchasing buys this vendor through a distributor: its price is entered by hand (NR-2)
        row.update(cost_source="DISTRIBUTOR_MANUAL", cost_source_detail="; ".join(tried)
                   + f" - bought through {' / '.join(via)}: enter the distributor's price")
        return [row]
    row["cost_source_detail"] = "; ".join(tried) + " - needs a distributor or vendor quote"
    return [row]
