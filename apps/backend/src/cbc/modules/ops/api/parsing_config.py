"""LlamaParse runtime settings: resolution and validation.

Resolved the same way Claude credentials are: process env → `.env` → saved
settings document → built-in default. Process env always wins and locks the field
in the UI, so an operator can pin a value the Settings screen cannot override.

`PARSER_API_KEY` is the on/off switch the way `PARSER_URL` used to be: empty means
parsing is off and Claude reads PDFs through pdf-tools instead. The key is never
returned to the browser - `public_config` reports only whether it is set.
"""
from __future__ import annotations

import os
from typing import Any

from cbc.shared import envfile

DOC_ID = "parsing"

# `fast` is excluded deliberately: it returns no granular bounding boxes, and
# without those a priced line has no rectangle on the sheet to point at, which
# NFR-3 does not allow. Cost per page rises steeply across the rest.
TIERS = ("cost_effective", "agentic", "agentic_plus")
DEFAULT_TIER = "cost_effective"

# Field name → env variable. Ints are stored as strings in .env.
FIELDS: dict[str, str] = {
    "apiKey": "PARSER_API_KEY",
    "tier": "PARSER_TIER",
    "lang": "PARSER_LANG",
    "windowPages": "PARSER_WINDOW_PAGES",
    "windowConcurrency": "PARSER_WINDOW_CONCURRENCY",
    "windowTimeoutSeconds": "PARSER_WINDOW_TIMEOUT_SECONDS",
    "waitMaxSeconds": "PARSER_WAIT_MAX_SECONDS",
}

# Never echoed back to the browser.
SECRET_FIELDS = frozenset({"apiKey"})

# Kept out of `envfile.apply_to_environ`, for the same reason the Claude provider
# variables are: a value this screen *saved* into `.env` must not come back as
# process environment on the next start. `resolve` reports process env as `env`,
# which locks the field in the UI and makes the PUT handler ignore what was
# typed - so saving a tier once and restarting left the field permanently
# greyed out, with later saves returning 200 and changing nothing.
#
# A genuine process variable - Compose, or `infisical run` injecting before
# Python starts - still wins and still locks, which is the intended meaning:
# the operator pinned it outside the app.
MANAGED = frozenset(FIELDS.values())

DEFAULTS: dict[str, Any] = {
    "apiKey": "",
    "tier": DEFAULT_TIER,
    "lang": "en",
    "windowPages": 8,
    # Windows are parsed concurrently. A window is ~97% waiting on the API, so
    # this is the single biggest lever on how long a bid set takes; it is capped
    # because the API is rate limited and unbounded fan-out fails rather than
    # finishes.
    "windowConcurrency": 4,
    "windowTimeoutSeconds": 1800,
    "waitMaxSeconds": 1800,
}

_INT_FIELDS = frozenset(
    {"windowPages", "windowConcurrency", "windowTimeoutSeconds", "waitMaxSeconds"}
)


def default_config() -> dict[str, Any]:
    """The stored document when nothing has been saved: empty.

    Deliberately not seeded with `tier`. `resolve` reports where each value came
    from and the Settings screen shows it, so seeding a value here would have it
    reported as `db` - telling an operator the tier was saved in the database
    when nothing ever was. `DEFAULTS` supplies the fallbacks and `resolve` labels
    them `default`, which is the truth.
    """
    return {}


def _coerce_field(field: str, raw: Any) -> Any:
    if raw is None:
        return None
    if field in _INT_FIELDS:
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None
    if field == "tier":
        return str(raw).strip().lower()
    return str(raw).strip()


def validate(config: dict[str, Any]) -> list[str]:
    """Return human-readable problems; empty means ok."""
    problems: list[str] = []
    tier = config.get("tier")
    if tier is not None and tier not in TIERS:
        if tier == "fast":
            problems.append(
                "tier `fast` returns no granular bounding boxes, so a parsed line "
                f"would have no rectangle to point at. Use one of {TIERS}"
            )
        else:
            problems.append(f"tier must be one of {TIERS}")
    window = config.get("windowPages")
    if window is not None and not (1 <= int(window) <= 200):
        problems.append("windowPages must be between 1 and 200")
    concurrency = config.get("windowConcurrency")
    if concurrency is not None and not (1 <= int(concurrency) <= 16):
        problems.append("windowConcurrency must be between 1 and 16")
    for timeout_field in ("windowTimeoutSeconds", "waitMaxSeconds"):
        value = config.get(timeout_field)
        if value is not None and not (60 <= int(value) <= 7200):
            problems.append(f"{timeout_field} must be between 60 and 7200")
    return problems


def resolve(
    config: dict[str, Any] | None, *, prefer_config: bool = False
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (effective settings, {field: source}).

    Source is `env` | `dotenv` | `db` | `default`. Process env always wins and
    locks the field in the UI. `prefer_config` is the Settings Test button:
    typed/saved values beat `.env`.
    """
    config = dict(config or default_config())
    file_env = envfile.read()
    sources: dict[str, str] = {}
    resolved: dict[str, Any] = {}

    for field, variable in FIELDS.items():
        from_env = os.environ.get(variable)
        if from_env is not None and from_env != "":
            resolved[field] = _coerce_field(field, from_env)
            sources[field] = "env"
            continue
        from_file = file_env.get(variable)
        if from_file is not None and from_file != "" and not prefer_config:
            resolved[field] = _coerce_field(field, from_file)
            sources[field] = "dotenv"
            continue
        if field in config and config[field] is not None and config[field] != "":
            resolved[field] = _coerce_field(field, config[field])
            sources[field] = "db"
            continue
        if from_file is not None and from_file != "":
            resolved[field] = _coerce_field(field, from_file)
            sources[field] = "dotenv"
            continue
        resolved[field] = DEFAULTS.get(field)
        sources[field] = "default"

    return resolved, sources


def enabled(resolved: dict[str, Any] | None = None) -> bool:
    """True when PARSER_API_KEY is set — parsing is on."""
    if resolved is None:
        resolved, _ = resolve(None)
    return bool(str(resolved.get("apiKey") or "").strip())


async def load_stored() -> dict[str, Any]:
    """Resolve parsing settings from the settings collection (ops-owned)."""
    from cbc.modules.ops.infrastructure.collections import settings_collection

    stored = await settings_collection().find_one({"_id": DOC_ID}) or {}
    resolved, _ = resolve(stored)
    return resolved


def public_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Settings payload: effective values, sources, locked flags, tiers.

    The API key is reported as set/unset and never by value: this payload goes
    to the browser and into the characterization snapshots.
    """
    resolved, sources = resolve(config)
    fields: dict[str, Any] = {}
    for field in FIELDS:
        value = resolved.get(field)
        if field in SECRET_FIELDS:
            value = "set" if str(value or "").strip() else ""
        fields[field] = {
            "value": value,
            "source": sources.get(field, "default"),
            "locked": sources.get(field) == "env",
        }
    return {
        "enabled": enabled(resolved),
        "fields": fields,
        "tiers": list(TIERS),
    }


def persist_env_file(config: dict[str, Any]) -> bool:
    """Mirror saved runtime settings into `.env` (PARSER_* only).

    Only fields the caller actually sent are written. A field that is absent
    means "unchanged", not "clear it" - the Settings screen deliberately omits
    the API key when it was not retyped, so that it cannot post a masked
    placeholder over a real secret.

    Treating absent as empty cost a real key: a Save with an untouched API key
    field wrote `PARSER_API_KEY=""` and parsing silently went off. `envfile.upsert`
    also *deletes* a variable given None, so the same mistake on the other fields
    removes them from `.env` outright rather than resetting them.
    """
    updates: dict[str, str | None] = {}
    for field, variable in FIELDS.items():
        if field not in config:
            continue
        value = config.get(field)
        if value is None:
            continue
        # An explicit empty string is a real instruction: clearing the key is how
        # an operator turns parsing off.
        updates[variable] = str(value)
    return envfile.upsert(updates)
