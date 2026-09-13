"""The HTTP surface as it stands: every route, and who may call it.

Three pins, all derived from the live app so they cannot drift from it:

- the route table: method, path, declared status and whether it is admin-only;
- every non-public operation, called with a wrong internal token;
- every admin-only operation, called by a signed-in estimator.

The last two record whatever the app answers rather than asserting 401 and 403,
so a route that validates its body before checking the caller's role shows up in
the snapshot instead of being assumed away.

And one check across the whole package: every operation has at least one real
response pinned by a module recipe, not just its authorization rows.
"""
from __future__ import annotations

import json

import pytest

from cbc.api.app import create_app
from cbc.shared.auth import PUBLIC_PATHS
from tests.characterization._harness import SNAPSHOTS, UPDATE, fill, route_table
from tests.shared import TEST_ACTOR, mongo_client, opshub_client

TEST_DB = "cbc_opshub_char_contract"
ROUTES = route_table(create_app(background=False))


@pytest.fixture(scope="module")
def client():
    with opshub_client(TEST_DB, isolated_storage=True, role="admin") as test_client:
        yield test_client


def _request(client, op: str, **kwargs):
    method, template = op.split(" ", 1)
    body = {} if method in {"POST", "PUT", "PATCH"} else None
    return client.request(method, fill(template), json=body, **kwargs)


def test_the_route_table(snapshots) -> None:
    assert len(ROUTES) == 124
    snapshots.pin_value("routes", ROUTES)


@pytest.mark.parametrize("op", [r["op"] for r in ROUTES if r["op"].split(" ", 1)[1] not in PUBLIC_PATHS])
def test_a_wrong_internal_token_is_rejected(client, snapshots, op: str) -> None:
    response = _request(client, op, headers={"X-Internal-Token": "wrong"})
    snapshots.pin(op, response, variant="wrong token")


@pytest.fixture()
def as_estimator():
    raw = mongo_client(serverSelectionTimeoutMS=5000)

    def set_role(role: str) -> None:
        raw[TEST_DB]["users"].update_one({"email": TEST_ACTOR}, {"$set": {"role": role}})

    set_role("estimator")
    try:
        yield
    finally:
        set_role("admin")
        raw.close()


@pytest.mark.parametrize("op", [r["op"] for r in ROUTES if r["admin"]])
def test_an_estimator_calling_an_admin_route(client, snapshots, as_estimator, op: str) -> None:
    response = _request(client, op)
    snapshots.pin(op, response, variant="estimator")


def test_every_operation_has_a_characterized_response() -> None:
    """Reads the committed snapshots, so it is skipped while they are being recorded."""
    if UPDATE:
        pytest.skip("run again without UPDATE_SNAPSHOTS to check the recorded snapshots")
    pinned: set[str] = set()
    for path in SNAPSHOTS.glob("test_*.json"):
        if path.name == "test_contract.json":
            continue
        pinned |= {key.split(" #", 1)[0] for key in json.loads(path.read_text(encoding="utf-8"))}
    missing = [r["op"] for r in ROUTES if r["op"] not in pinned]
    assert not missing, f"{len(missing)} operation(s) have no characterized response:\n" + "\n".join(missing)
