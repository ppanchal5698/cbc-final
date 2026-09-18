"""Is this PDF actually readable, and does its text sit on the page?

Both quoting (which renders the deliverable) and extraction (which gates it
before delivery) have to answer that. The check itself knows nothing about
either - it opens bytes and looks - so it lives in `shared`, where both may
import it. It used to live in `quoting.api.proposal_artifacts`, which meant
extraction imported quoting to reach it and closed the last module cycle in the
graph.
"""
from __future__ import annotations

from pathlib import Path

import fitz


def pdf_problems(content: bytes, label: str) -> list[str]:
    """Independently open the export; a filename or a PDF header proves nothing."""
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            if not document.is_pdf or document.needs_pass or not document.page_count:
                return [f"{label}: PDF is encrypted or has no readable pages"]
            if document.is_repaired:
                return [f"{label}: PDF is damaged and required structural repair"]
            has_text = False
            problems = []
            for number, page in enumerate(document, 1):
                words = page.get_text("words", clip=fitz.INFINITE_RECT())
                has_text = has_text or bool(words)
                bounds = page.rect + (-1, -1, 1, 1)
                if any(not bounds.contains(fitz.Rect(word[:4])) for word in words):
                    problems.append(f"{label}: PDF page {number} has text outside the page bounds")
            if not has_text:
                problems.append(f"{label}: PDF has no readable quotation text")
            return problems
    except Exception as exc:  # noqa: BLE001 - a corrupt file is a finding, not a crash
        return [f"{label}: PDF could not be read: {exc}"]


def exported_pdf_problems(root: Path, label_prefix: str, relatives: tuple[str, ...]) -> list[str]:
    """Check whichever of these exports exist under `root`.

    Absence is allowed: the pre-render gate runs before the worker writes the
    PDF, and a missing renderer is recorded on the email draft instead.
    """
    problems: list[str] = []
    for relative in relatives:
        path = root / relative
        if not path.exists():
            continue
        try:
            problems.extend(pdf_problems(path.read_bytes(), f"{label_prefix}/{relative}"))
        except OSError as exc:
            problems.append(f"{label_prefix}/{relative}: PDF could not be read: {exc}")
    return problems


def _demo() -> None:
    """Runnable check: a real PDF passes, junk is reported rather than raised."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quotation")
    good = doc.tobytes()
    doc.close()
    assert pdf_problems(good, "good") == [], pdf_problems(good, "good")

    junk = pdf_problems(b"not a pdf at all", "junk")
    assert junk and "could not be read" in junk[0].lower() or "encrypted" in junk[0].lower(), junk

    empty = fitz.open()
    empty.new_page()
    blank = empty.tobytes()
    empty.close()
    assert any("no readable quotation text" in p for p in pdf_problems(blank, "blank"))
    print("pdfcheck demo OK")


if __name__ == "__main__":
    _demo()
