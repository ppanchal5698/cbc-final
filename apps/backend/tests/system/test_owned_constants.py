"""A number with an owner is not restated where an agent reads it.

The audit found the 0.75 confidence floor, the margin bands, Hager multipliers,
adders, tax rates and freshness windows copied into agent, skill and memory files -
and copies drift: vendor_tiers.md already disagreed with the live tier sheet. A
value an agent needs either comes from a tool (bands, multipliers, adders, tax) or
is rendered into the prompt from its owner (the floor, the freshness windows).

Each family's values are read from its owner when the test runs, so changing the
owner changes what is checked. A line is flagged only when it holds one of those
values *and* a word from that family - "0.29" in a margin sentence and "6 months"
in a sentence about doors are not restatements.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from tests.shared import ROOT

REFERENCE = ROOT / "data" / "reference-library"
PROMPTS = ROOT / "apps" / "backend" / "src" / "cbc" / "worker_kit" / "prompts.py"
# A family's own seed states its values; anywhere else it is a copy. The floor and
# the freshness windows are owned by Python modules, which are not scanned.
OWNER_SEEDS = {
    "margin bands": REFERENCE / "margins" / "margin_framework.json",
    "multipliers": REFERENCE / "multipliers" / "vendor_tiers.json",
    "adders": REFERENCE / "adders" / "manual_adders.json",
    "tax rates": REFERENCE / "tax" / "sales_tax_rates.json",
}


def _formats(value: float) -> set[str]:
    """How a fraction gets written: 0.29, 0.290, .29, 29%."""
    out = {f"{value:.2f}", f"{value:.3f}", f"{value:g}", f"{value * 100:g}%", f"{value * 100:g} %"}
    out |= {text[1:] for text in list(out) if text.startswith("0.")}
    return out


def _months(months: int) -> set[str]:
    out = {f"{months} months", f"{months}-month", f"{months} mo"}
    if months % 12 == 0:
        years = months // 12
        out |= {f"{years} years", f"{years}-year", f"{years} year"}
    return out


def _json(rel: str) -> dict:
    return json.loads((REFERENCE / rel).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _families() -> dict[str, tuple[set[str], re.Pattern[str]]]:
    """name -> (values as written, the words that make a line about that family)."""
    from cbc.modules.ops.api import freshness_rules
    from cbc.modules.pricing.api.confidence import CONFIDENCE_FLOOR

    tiers = _json("multipliers/vendor_tiers.json")["vendors"]
    multipliers = {
        value
        for vendor in tiers
        for value in [vendor.get("multiplier"), *(vendor.get("categories") or {}).values()]
        if isinstance(value, (int, float)) and value != 1.0
    }
    adders = {
        item["list_adder"]
        for item in _json("adders/manual_adders.json")["hager_list_adders"]["items"]
        if isinstance(item.get("list_adder"), (int, float))
    }
    return {
        # The floor is written as "below 0.75 is flagged", "auto-accepted", or as a
        # row under a "Score" header, as often as it is called a confidence.
        "confidence floor": (
            _formats(CONFIDENCE_FLOOR),
            re.compile(r"confiden|floor|score|flag|accept|settled", re.I),
        ),
        "margin bands": (
            set().union(*(_formats(band["margin"]) for band in _json("margins/margin_framework.json")["bands"])),
            re.compile(r"margin|band|markup", re.I),
        ),
        "multipliers": (
            set().union(*(_formats(value) for value in multipliers)),
            # Not "tier": the matcher's ladder calls its rows tiers too.
            re.compile(r"multiplier|discount", re.I),
        ),
        "adders": ({f"{value:.2f}" for value in adders}, re.compile(r"adder", re.I)),
        "tax rates": (
            set().union(*(_formats(rate) for rate in _json("tax/sales_tax_rates.json")["rates"].values())),
            re.compile(r"\btax", re.I),
        ),
        "freshness windows": (
            _months(freshness_rules.FRESH_MONTHS)
            | _months(freshness_rules.DISCARD_AFTER_MONTHS)
            | _months(freshness_rules.CATALOG_STALE_MONTHS),
            re.compile(r"fresh|stale|discard|lapse|reliab|review window", re.I),
        ),
    }


def _number(text: str) -> re.Pattern[str]:
    # Not part of a longer number: 0.3 must not match 0.3005, nor 6 months 16 months.
    return re.compile(r"(?<![\d.])" + re.escape(text) + r"(?![\d])")


def _documents() -> list[Path]:
    """Agent text, the prompts, tool descriptions, and the reference notes the
    reference tools serve - every place an agent reads a number."""
    return [
        *sorted((ROOT / ".claude").rglob("*.md")),
        ROOT / "CLAUDE.md",
        PROMPTS,
        *sorted((ROOT / "mcp-servers").glob("*/tools.py")),
        *sorted(REFERENCE.rglob("*.json")),
    ]


def _context(lines: list[str], index: int) -> str:
    """The text that says what a number on `lines[index]` is about.

    A table row rarely repeats its column's name - `| 2 | ... | 0.75-0.94 |` sits
    under a header that says "Confidence" - so a row is read with its table's
    header. A prose line is read with the line before it, where a wrapped
    sentence usually names its subject.
    """
    line = lines[index]
    if line.lstrip().startswith("|"):
        start = index
        while start > 0 and lines[start - 1].lstrip().startswith("|"):
            start -= 1
        return lines[start] + "\n" + line
    return (lines[index - 1] if index else "") + "\n" + line


@pytest.mark.parametrize("path", _documents(), ids=lambda p: str(p.relative_to(ROOT)).replace("\\", "/"))
def test_no_owned_constant_is_restated(path: Path) -> None:
    found = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        context = _context(lines, number - 1)
        for family, (values, words) in _families().items():
            if path == OWNER_SEEDS.get(family) or not words.search(context):
                continue
            hits = sorted(v for v in values if _number(v).search(line))
            if hits:
                found.append(f"{path.name}:{number} [{family}] {hits}: {line.strip()[:110]}")
    assert not found, "restated constants - point at the owner instead:\n" + "\n".join(found)


def test_the_check_would_catch_a_restatement(tmp_path: Path) -> None:
    """Only worth having if it fails: one restatement per family is caught."""
    values = _families()
    samples = {
        "confidence floor": "below the 0.75 confidence floor",
        "margin bands": "commodity margin is 27%",
        "multipliers": "the Hager locks multiplier is 0.29",
        "tax rates": "Ohio sales tax 8%",
        "freshness windows": "a PO is fresh for 6 months",
    }
    for family, sentence in samples.items():
        candidates, words = values[family]
        assert words.search(sentence) and any(_number(v).search(sentence) for v in candidates), family
