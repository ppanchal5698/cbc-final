"""Which priced row a specified hardware item is - decided in code, from what the
legend wrote and nothing else.

A specified item can be priced from three kinds of row: a special net (CBC's
negotiated price), a catalog row, or a price-book row (list x multiplier). Each
holds several rows per model - one per finish, size or variant (`431S` is a
threshold at 36", 42", 44" and 48"; `3553` is a lock with and without IC). A row
is this item only when the model is the item's, and the finish and size the
legend wrote agree with the row's. One row left is a match. Several left at one
price is a match too - the price does not depend on the choice. Several prices
left is a question for the estimator, never the first row: picking one is how a
48" threshold was quoted at the 36" price.

Pure: rows in, a decision out. The pricer fetches the rows, and the part
candidates (catalog's normaliser) that say which forms of the part to try.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

# Allegion sells through distributors only (Banner Solutions / SecLock), so a
# run never prices it off a list. Matched as words: "ives" inside "adhesives" is
# not Ives.
_ALLEGION_WORDS = re.compile(
    # LOCKNETICS is Allegion's; LOCKNET alone is a security-door maker that is not.
    r"\b(?:VON\s*DUPRIN|LCN|SCHLAGE|IVES|ALLEGION|GLYNN[\s-]*JOHNSON|LOCKNETICS)\b", re.I)
_ALLEGION_MAKERS = {"zero", "zero international", "falcon"}  # ambiguous as words, plain as a maker

# A number glued to letters is a part number (BB1279), never a size.
_NUMBER = r"(\d+(?:\.\d+)?)(?:[\s-]+(\d+)/(\d+))?"
_FRACTION = r"(?<![A-Za-z0-9.])" + _NUMBER
_MARK = r"""(?:"|”|″|''|\s?in(?:ch(?:es)?)?\b)"""
# The second number of `20X40` follows its `X` with no space, as a part writes it.
_BY = re.compile(_FRACTION + r"\s*" + _MARK + r"?\s*[xX×]\s*" + _NUMBER + _MARK + "?", re.I)
_INCHES = re.compile(_FRACTION + _MARK, re.I)
_FEET = re.compile(r"""(?<![A-Za-z0-9.])(\d+)\s*'\s*-?\s*(?:""" + _NUMBER + r""")?\s*(?:"|”|″)?""")
_LARGEST = 240.0  # inches; anything bigger is a part number's digits, not a size
# What a finish code looks like: US26D, a BHMA number (626, 652), Hager's 26D.
# Not a bare 36 or 16 - a description's dimensions are not finishes - nor 21J
# or 33E, which are parts: the bare codes end in B or D.
_FINISH_TOKEN = re.compile(r"^(?:US\d{1,3}[A-Z]?|[67]\d{2}|\d{1,2}[BD])$", re.I)


def is_allegion(*texts: Any, manufacturer: Any = None) -> bool:
    if str(manufacturer or "").strip().lower() in _ALLEGION_MAKERS:
        return True
    return any(_ALLEGION_WORDS.search(str(t or "")) for t in (manufacturer, *texts))


def _number(whole: str, num: str | None, den: str | None) -> float:
    value = float(whole)
    if num and den and float(den):
        value += float(num) / float(den)
    return round(value, 4)


def _inches(match: re.Match[str]) -> str:
    feet, whole, num, den = match.groups()
    return f'{round(float(feet) * 12 + (_number(whole, num, den) if whole else 0), 4):g}"'


def dimensions(text: Any) -> tuple[float, ...]:
    """The sizes a description states, in inches, sorted: `4-1/2" x 4-1/2"` ->
    (4.5, 4.5); `36"` -> (36,); `3'-0" x 7'-0"` -> (36, 84). Bare numbers say
    nothing - a part number is a number too."""
    raw = _FEET.sub(_inches, str(text or ""))  # feet and inches, as inches
    found: list[float] = []
    rest = raw
    for match in _BY.finditer(raw):
        found += [_number(*match.groups()[:3]), _number(*match.groups()[3:])]
        rest = rest.replace(match.group(0), " ")
    for match in _INCHES.finditer(rest):
        found.append(_number(*match.groups()))
    return tuple(sorted(v for v in found if 0 < v <= _LARGEST))


def _sizes_agree(wanted: tuple[float, ...], offered: tuple[float, ...]) -> bool:
    """A row that states no size fits any; one that does must state the legend's.
    One side may say more - `10" x 34" (for 36" door)` is still a 10 x 34 plate -
    but never something else: 4-1/2 x 4 is not 4-1/2 x 4-1/2."""
    if not wanted or not offered:
        return True
    want, have = Counter(wanted), Counter(offered)
    return not (want - have) or not (have - want)


@dataclass(frozen=True)
class Spec:
    """One specified item as the legend wrote it."""

    part: str | None
    manufacturer: str | None = None
    finish: str | None = None
    text: str = ""  # everything else the legend says about it: size, variant, options


@dataclass
class Choice:
    """What one rung found for one spec."""

    row: dict[str, Any] | None = None  # the matched row, when there is one
    candidates: list[dict[str, Any]] = field(default_factory=list)  # every row still in play
    reason: str = ""  # why there is no match, for the estimator
    # Rows that are this item at different prices: a person decides. Otherwise a
    # miss (no row, or none in the legend's finish or size) lets the next source try.
    ambiguous: bool = False


FinishKey = Callable[[str | None], str | None]


def finish_key(text: str | None, resolve: Callable[[str], dict[str, Any] | None] | None = None) -> str | None:
    """One key per finish whichever nomenclature wrote it: `626`, `26D/626`, `US26D`
    and `US26D (626) - Satin Chrome` agree when the crosswalk says so (NR-3).
    A vendor's own code (ALM, BLK) is itself. Text that names no finish is None,
    which filters nothing - never a key no row could match."""
    raw = " ".join(str(text or "").upper().split())
    if not raw:
        return None
    pieces = [t for t in re.split(r"[^A-Z0-9]+", raw) if t]
    if resolve is not None:
        for piece in [raw, *pieces]:
            found = resolve(piece)
            if found and not found.get("ambiguous") and found.get("us_code"):
                return str(found["us_code"]).upper().removeprefix("US")
    for piece in pieces:
        if _FINISH_TOKEN.match(piece):
            return piece.removeprefix("US")
    return pieces[0].removeprefix("US") if len(pieces) == 1 else None


def spec_finish(spec: Spec, key: FinishKey) -> str | None:
    """The finish the legend gave: its finish column, else the first finish code
    among the item's words (never the part itself)."""
    if spec.finish:
        return key(spec.finish)
    for token in re.split(r"[\s,;/()]+", spec.text.upper()):
        if token and token != str(spec.part or "").upper() and _FINISH_TOKEN.match(token):
            return key(token)
    return None


def _words(text: Any) -> set[str]:
    return {w for w in re.split(r"[^A-Z0-9]+", str(text or "").upper()) if len(w) >= 2}


def choose(
    spec: Spec,
    rows: Iterable[dict[str, Any]],
    *,
    models: Iterable[str],
    model_of: Callable[[dict[str, Any]], Any],
    finish_of: Callable[[dict[str, Any]], Any],
    size_of: Callable[[dict[str, Any]], Any],
    price_of: Callable[[dict[str, Any]], Any],
    finish: FinishKey,
    describe: Callable[[dict[str, Any]], Any] | None = None,
) -> Choice:
    """The row this spec is, among rows of one kind - or why there is none.

    `models` are the forms of the part to try, most specific first. `describe`
    gives a row's words, for the last step: when rows at different prices are
    left, a word the legend used that only some of them carry (IC, MOP, 48)
    says which.
    """
    rows = list(rows)
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(str(model_of(row) or "").strip().upper(), []).append(row)
    # The most specific form of the part that the rows know: `PEMKO-275A-42` is
    # tried whole, then as `275A-42`, then `275A` - never as a prefix of anything.
    models = list(models)
    matched: list[dict[str, Any]] = []
    for model in models:
        matched = by_model.get(model.upper(), [])
        if matched:
            break
    series = False
    if not matched:
        # The legend named a series and the rows are its sizes: `B-5806` against
        # `B-5806.99x48`. Only past a separator - `B-580616x18` is another series -
        # and never chosen by length: the checks below decide, or a person does.
        for model in models:
            prefix = model.upper()
            if len(prefix) < 3 or not re.search(r"\d", prefix):
                continue
            matched = [row for key, group in by_model.items()
                       if len(key) > len(prefix) and key.startswith(prefix) and not key[len(prefix)].isalnum()
                       for row in group]
            if matched:
                series = True
                break
    if not matched:
        return Choice(reason="no row for this part")

    wanted_finish = spec_finish(spec, finish)
    if wanted_finish:
        same = [r for r in matched if finish(finish_of(r)) in (None, wanted_finish)]
        if not same:
            offered = sorted({str(finish_of(r)) for r in matched if finish_of(r)})
            return Choice(candidates=matched, reason=f"not listed in finish {wanted_finish} (listed: {', '.join(offered)})")
        matched = same

    wanted_size = dimensions(f"{spec.part or ''} {spec.text}")
    sized = [r for r in matched if _sizes_agree(wanted_size, dimensions(size_of(r)))]
    if not sized:
        return Choice(candidates=matched, reason="not listed in the size the legend gives")
    matched = sized

    prices = {round(float(p), 2) for p in (price_of(r) for r in matched) if p is not None}
    if not prices:
        return Choice(candidates=matched, reason="the row carries no price")
    if len(prices) == 1:
        return Choice(row=matched[0], candidates=matched)
    if describe is not None:
        said = _words(f"{spec.part or ''} {spec.text}")
        worded = [(row, _words(describe(row))) for row in matched]
        shared = set.intersection(*(words for _, words in worded))
        telling = said & (set.union(*(words for _, words in worded)) - shared)
        kept = [row for row, words in worded if telling and telling <= words]
        if kept and len({round(float(price_of(r)), 2) for r in kept if price_of(r) is not None}) == 1:
            return Choice(row=kept[0], candidates=kept)
    what = "sizes of the series" if series else "rows"
    return Choice(candidates=matched, ambiguous=True,
                  reason=f"{len(matched)} {what} at {len(prices)} prices - the legend does not say which")
