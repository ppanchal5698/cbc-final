"""Project access — re-export migrated projects_access."""
from __future__ import annotations

from cbc.http.projects_access import load as load_project

__all__ = ["load_project", "load"]

load = load_project
