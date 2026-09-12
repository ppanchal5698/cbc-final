"""Composition root stub — providers filled during migration phases."""
from __future__ import annotations


class Container:
    """Empty DI container placeholder."""

    def __init__(self) -> None:
        self.ready = False


container = Container()
