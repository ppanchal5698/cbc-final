from __future__ import annotations

import pytest

from tests.characterization._harness import Snapshots


@pytest.fixture(scope="module")
def snapshots(request):
    """One snapshot file per test module; written only under UPDATE_SNAPSHOTS=1."""
    snaps = Snapshots(request.module.__name__.rsplit(".", 1)[-1])
    yield snaps
    snaps.save()
