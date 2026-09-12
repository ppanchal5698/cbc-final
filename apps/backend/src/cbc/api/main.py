"""Uvicorn entry: `uvicorn cbc.api.main:app`."""
from __future__ import annotations

import uvicorn

from cbc.api.app import create_app

app = create_app()


def run() -> None:
    uvicorn.run("cbc.api.main:app", host="0.0.0.0", port=8001, reload=False)


if __name__ == "__main__":
    run()
