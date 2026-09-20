"""The stored Claude provider configuration: one document in `settings`."""
from __future__ import annotations

from typing import Any

from cbc.modules.ops.infrastructure.collections import settings_collection
from cbc.modules.ops.api import provider


DOC_ID = "claude"


async def load_config() -> dict[str, Any]:
    stored = await settings_collection().find_one({"_id": DOC_ID}) or provider.default_config()
    # A provider that no longer exists cannot be configured, so a document still
    # naming one is reset rather than left to resolve by fallback. `gateway`
    # joined `cloudflare` here when the supported set was cut to four; the
    # credential it held is dropped with it, which is the point - nothing reads
    # it any more and it should not sit encrypted in the document for ever.
    if stored.get("mode") in provider.RETIRED_MODES:
        cleaned = {
            **provider.default_config(),
            "updatedAt": stored.get("updatedAt"),
            "updatedBy": stored.get("updatedBy"),
        }
        await settings_collection().replace_one({"_id": DOC_ID}, {"_id": DOC_ID, **cleaned}, upsert=True)
        return cleaned
    return stored
