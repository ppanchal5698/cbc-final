"""Which pages a pass must look at rather than read, for callers outside extraction.

`worker_kit.prompts` puts the checklist in the take-off prompt, and the readiness
script checks the machinery is installed at all. Both reached into
`extraction.infrastructure.visual_pages` to do it, which the layering rule
forbids: nothing outside a module may import its insides. The implementation
stays where it is; this is the doorway.
"""
from __future__ import annotations

from typing import Any

from cbc.modules.extraction.infrastructure import visual_pages as _visual_pages


def prompt_checklist(slug: str) -> str:
    """The mandatory-vision-read block for a take-off prompt, or "" when there is none."""
    return _visual_pages.prompt_checklist(slug)


def build(
    slug: str,
    *,
    openings_seeded: int = 0,
    signals_by_path: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide which pages need a full-page image, and pre-render them."""
    return _visual_pages.build_visual_pages(
        slug, openings_seeded=openings_seeded, signals_by_path=signals_by_path
    )
