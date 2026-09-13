"""Mongo transaction helper falls back when MONGODB_TRANSACTIONS is off."""
from __future__ import annotations

import asyncio

from cbc.shared import mongo as cbc_db


def test_run_transaction_fallback_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("MONGODB_TRANSACTIONS", raising=False)
    assert cbc_db.transactions_enabled() is False

    async def work(session):
        assert session is None
        return "ok"

    assert asyncio.run(cbc_db.run_transaction(work)) == "ok"


def test_transactions_enabled_flag(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_TRANSACTIONS", "1")
    assert cbc_db.transactions_enabled() is True
