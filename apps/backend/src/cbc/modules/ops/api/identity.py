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


async def directory(emails: list[str]) -> dict[str, dict]:
    """Name and initials for a set of addresses, keyed by lower-cased email.

    The board shows who a bid is assigned to. Addresses not in `users` are
    simply absent, so a bid assigned to someone since deleted degrades to the
    raw address rather than vanishing.
    """
    wanted = sorted({e.lower() for e in emails if e})
    if not wanted:
        return {}
    rows = await users().find(
        {"email": {"$in": wanted}}, {"email": 1, "name": 1, "initials": 1}
    ).to_list(length=len(wanted))
    return {
        row["email"]: {
            "email": row["email"],
            "name": row.get("name") or row["email"],
            "initials": row.get("initials") or "",
        }
        for row in rows
    }


async def assignable() -> list[dict]:
    """Everyone a bid may be assigned to, for the board's estimator picker.

    Names of colleagues, which the board already shows - so this is readable by
    any signed-in actor, unlike the admin-only `/api/users`.
    """
    rows = await users().find({}, {"email": 1, "name": 1, "initials": 1}).to_list(length=200)
    return sorted(
        (
            {
                "email": row["email"],
                "name": row.get("name") or row["email"],
                "initials": row.get("initials") or "",
            }
            for row in rows
        ),
        key=lambda u: u["name"].lower(),
    )
