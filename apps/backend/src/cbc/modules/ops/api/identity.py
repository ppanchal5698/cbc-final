"""Who a signed-in person is allowed to be.

`shared.auth.require_admin` needs this answered and may not import a module, so
the composition root registers `role_of` with it at startup.
"""
from __future__ import annotations

from cbc.modules.ops.infrastructure.collections import users


async def role_of(email: str) -> str | None:
    """The stored role for this address, or None when there is no such user."""
    user = await users().find_one({"email": email.lower()}, {"role": 1})
    return user.get("role") if user else None
