"""MinerU parser runtime settings: presets, resolution, and validation.

Two kinds of settings exist (see docs):

- Runtime (`PARSER_*`): the next parse job picks them up; no restart. Resolved
  here the same way Claude credentials are: process env → `.env` → saved
  settings document → profile preset.
- Container (`MINERU_*` in `infra/mineru/<profile>.env`): need a rebuild /
  restart of the GPU service. Shown read-only in the UI from MinerU `/health`.

MinerU's own `MINERU_FORMULA_ENABLE` / `MINERU_TABLE_ENABLE` override request
bodies, so they are never set on the container; app settings use `PARSER_*`.
"""
from __future__ import annotations

import os
from typing import Any, Literal

from cbc.shared import envfile

DOC_ID = "parsing"

PROFILES = ("low", "medium", "high")
Profile = Literal["low", "medium", "high"]

# Backends accepted by MinerU 3.4 `/tasks`. http-client* omitted (SSRF surface).
BACKENDS = ("pipeline", "hybrid-engine", "vlm-engine")
EFFORTS = ("low", "medium", "high")
METHODS = ("auto", "txt", "ocr")

# Field name → env variable. Booleans and ints are stored as strings in .env.
FIELDS: dict[str, str] = {
    "url": "PARSER_URL",
    "profile": "PARSER_PROFILE",
    "backend": "PARSER_BACKEND",
    "effort": "PARSER_EFFORT",
    "method": "PARSER_METHOD",
    "lang": "PARSER_LANG",
    "tables": "PARSER_TABLES",
    "formulas": "PARSER_FORMULAS",
    "imageAnalysis": "PARSER_IMAGE_ANALYSIS",
    "windowPages": "PARSER_WINDOW_PAGES",
    "windowTimeoutSeconds": "PARSER_WINDOW_TIMEOUT_SECONDS",
    "waitMaxSeconds": "PARSER_WAIT_MAX_SECONDS",
}

PRESETS: dict[str, dict[str, Any]] = {
    "low": {
        "backend": "pipeline",
        "effort": None,
        "method": "auto",
        "lang": "en",
        "tables": True,
        "formulas": False,
        "imageAnalysis": False,
        "windowPages": 8,
        "windowTimeoutSeconds": 1800,
        "waitMaxSeconds": 1800,
        "hardware": "4–6 GB VRAM, 16 GB RAM",
    },
    "medium": {
        "backend": "hybrid-engine",
        "effort": "medium",
        "method": "auto",
        "lang": "en",
        "tables": True,
        "formulas": False,
        "imageAnalysis": False,
        "windowPages": 16,
        "windowTimeoutSeconds": 1800,
        "waitMaxSeconds": 1800,
        "hardware": "8–12 GB VRAM, 32 GB RAM",
    },
    "high": {
        "backend": "hybrid-engine",
        "effort": "high",
        "method": "auto",
        "lang": "en",
        "tables": True,
        "formulas": False,
        "imageAnalysis": True,
        "windowPages": 32,
        "windowTimeoutSeconds": 1800,
        "waitMaxSeconds": 1800,
        "hardware": "16 GB+ VRAM, 64 GB RAM",
    },
}

_BOOL_FIELDS = frozenset({"tables", "formulas", "imageAnalysis"})
_INT_FIELDS = frozenset({"windowPages", "windowTimeoutSeconds", "waitMaxSeconds"})


def default_config() -> dict[str, Any]:
    """Empty stored document: profile low, no URL (parsing off)."""
    return {"profile": "low", "url": ""}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_field(field: str, raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if field in _BOOL_FIELDS:
        return _truthy(raw)
    if field in _INT_FIELDS:
        return _as_int(raw, PRESETS["low"][field])
    if field == "url":
        return str(raw).strip()
    if field == "profile":
        text = str(raw).strip().lower()
        return text if text in PROFILES else "low"
    if field == "effort" and str(raw).strip().lower() in ("", "none", "null"):
        return None
    return str(raw).strip()


def validate(config: dict[str, Any]) -> list[str]:
    """Return human-readable problems; empty means ok."""
    problems: list[str] = []
    profile = config.get("profile") or "low"
    if profile not in PROFILES:
        problems.append(f"profile must be one of {PROFILES}")
    backend = config.get("backend")
    if backend is not None and backend not in BACKENDS:
        problems.append(f"backend must be one of {BACKENDS}")
    effort = config.get("effort")
    if effort is not None and effort not in EFFORTS:
        problems.append(f"effort must be one of {EFFORTS}")
    if effort is not None and backend != "hybrid-engine":
        problems.append("effort is only valid with hybrid-engine")
    method = config.get("method")
    if method is not None and method not in METHODS:
        problems.append(f"method must be one of {METHODS}")
    window = config.get("windowPages")
    if window is not None and not (1 <= int(window) <= 200):
        problems.append("windowPages must be between 1 and 200")
    for timeout_field in ("windowTimeoutSeconds", "waitMaxSeconds"):
        value = config.get(timeout_field)
        if value is not None and not (60 <= int(value) <= 7200):
            problems.append(f"{timeout_field} must be between 60 and 7200")
    return problems


def resolve(
    config: dict[str, Any] | None, *, prefer_config: bool = False
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (effective settings, {field: source}).

    Source is `env` | `dotenv` | `db` | `profile`. Process env always wins and
    locks the field in the UI. `prefer_config` is the Settings Test button:
    typed/saved values beat `.env`.
    """
    config = dict(config or default_config())
    file_env = envfile.read()
    sources: dict[str, str] = {}
    resolved: dict[str, Any] = {}

    # Profile first so preset fill works; still overridable per field below.
    profile_raw = None
    from_env = os.environ.get(FIELDS["profile"])
    if from_env:
        profile_raw = from_env
        sources["profile"] = "env"
    else:
        from_file = file_env.get(FIELDS["profile"])
        if from_file and not prefer_config:
            profile_raw = from_file
            sources["profile"] = "dotenv"
        elif config.get("profile"):
            profile_raw = config["profile"]
            sources["profile"] = "db"
        elif from_file:
            profile_raw = from_file
            sources["profile"] = "dotenv"
        else:
            profile_raw = "low"
            sources["profile"] = "profile"

    profile = _coerce_field("profile", profile_raw) or "low"
    resolved["profile"] = profile
    preset = dict(PRESETS[profile])

    for field, variable in FIELDS.items():
        if field == "profile":
            continue
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
        # Preset (or empty URL = parsing off).
        if field == "url":
            resolved[field] = ""
            sources[field] = "profile"
        elif field in preset:
            resolved[field] = preset[field]
            sources[field] = "profile"
        else:
            resolved[field] = None
            sources[field] = "profile"

    # hybrid effort default when backend is hybrid and effort unset
    if resolved.get("backend") == "hybrid-engine" and not resolved.get("effort"):
        resolved["effort"] = preset.get("effort") or "medium"
        if sources.get("effort") == "profile":
            pass
    if resolved.get("backend") != "hybrid-engine":
        resolved["effort"] = None

    return resolved, sources


def enabled(resolved: dict[str, Any] | None = None) -> bool:
    """True when PARSER_URL is set — parsing is on."""
    if resolved is None:
        resolved, _ = resolve(None)
    return bool(str(resolved.get("url") or "").strip())


async def load_stored() -> dict[str, Any]:
    """Resolve parsing settings from the settings collection (ops-owned)."""
    from cbc.modules.ops.infrastructure.collections import settings_collection

    stored = await settings_collection().find_one({"_id": DOC_ID}) or {}
    resolved, _ = resolve(stored)
    return resolved


def public_config(
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Settings payload: effective values, sources, locked flags, presets."""
    resolved, sources = resolve(config)
    fields: dict[str, Any] = {}
    for field in FIELDS:
        fields[field] = {
            "value": resolved.get(field),
            "source": sources.get(field, "profile"),
            "locked": sources.get(field) == "env",
        }
    return {
        "enabled": enabled(resolved),
        "fields": fields,
        "presets": {
            name: {k: v for k, v in preset.items()}
            for name, preset in PRESETS.items()
        },
        "backends": list(BACKENDS),
        "efforts": list(EFFORTS),
        "methods": list(METHODS),
        "profiles": list(PROFILES),
    }


def persist_env_file(config: dict[str, Any]) -> bool:
    """Mirror saved runtime settings into `.env` (PARSER_* only)."""
    updates: dict[str, str | None] = {}
    for field, variable in FIELDS.items():
        value = config.get(field)
        if value is None or value == "":
            # Keep URL empty meaning off; clear other empties.
            if field == "url":
                updates[variable] = ""
            else:
                updates[variable] = None
            continue
        if isinstance(value, bool):
            updates[variable] = "1" if value else "0"
        else:
            updates[variable] = str(value)
    return envfile.upsert(updates)


def mineru_task_body(resolved: dict[str, Any]) -> dict[str, Any]:
    """Fields for MinerU POST /tasks from resolved settings."""
    body: dict[str, Any] = {
        "backend": resolved.get("backend") or "pipeline",
        "parse_method": resolved.get("method") or "auto",
        "lang_list": [resolved.get("lang") or "en"],
        "formula_enable": bool(resolved.get("formulas")),
        "table_enable": bool(resolved.get("tables")),
        "return_middle_json": True,
    }
    if resolved.get("backend") == "hybrid-engine" and resolved.get("effort"):
        body["effort"] = resolved["effort"]
    if resolved.get("imageAnalysis"):
        body["image_analysis"] = True
    return body
