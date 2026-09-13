"""The stored Claude provider configuration: one document in `settings`."""
from __future__ import annotations

from typing import Any

from cbc.modules.ops.infrastructure.collections import settings_collection
from cbc.modules.ops.api import provider


DOC_ID = "claude"


async def load_config() -> dict[str, Any]:
    stored = await settings_collection().find_one({"_id": DOC_ID}) or provider.default_config()
    # Cloudflare provider was removed; drop any leftover mode so the UI and
    # worker do not try to resolve CLOUDFLARE_* credentials.
    if stored.get("mode") == "cloudflare":
        cleaned = {
            **provider.default_config(),
            "updatedAt": stored.get("updatedAt"),
            "updatedBy": stored.get("updatedBy"),
        }
        await settings_collection().replace_one({"_id": DOC_ID}, {"_id": DOC_ID, **cleaned}, upsert=True)
        return cleaned
    return stored
