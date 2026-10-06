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


async def address_of(who: str | None) -> dict | None:
    """Name and address for someone a bid records by name or by address - its
    sales initiator. A lone first name counts when exactly one user has it."""
    who = (who or "").strip()
    if not who:
        return None
    if "@" in who:
        row = await users().find_one({"email": who.lower()}, {"name": 1}) or {}
        return {"name": row.get("name") or who, "email": who.lower()}
    rows = await users().find({}, {"email": 1, "name": 1}).to_list(length=500)
    wanted = who.lower()
    found = [r for r in rows if (r.get("name") or "").strip().lower() == wanted]
    if not found and " " not in wanted:
        found = [r for r in rows if (r.get("name") or "").lower().split()[:1] == [wanted]]
    if len(found) != 1:
        return None
    return {"name": found[0].get("name") or who, "email": found[0]["email"]}


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
