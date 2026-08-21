"""
PDF -> page images/text, and the native-vs-scanned decision (Issue 5).

Decision rule (data_dictionary.md §4): try PyMuPDF's native text layer first,
per page — a PV can mix a typed cover page with scanned annexes, so the
decision is made per page rather than assuming one PDF is entirely one kind.
A page counts as native when it yields more than NATIVE_TEXT_MIN_CHARS of
text; anything at or below that (usually 0, since scans have no text layer at
all) is treated as needing OCR.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np

# A handful of stray characters (e.g. a lone page-border artefact) should not
# be mistaken for a native text layer — this threshold is the same one used
# during the reconnaissance that measured 8 native / 18 scanned on the local
# sample set (consistent with the 70.8% scanned figure on 390 PVs).
NATIVE_TEXT_MIN_CHARS = 20

DEFAULT_DPI = 300  # matches the reconnaissance measurements this module is based on


@dataclass
class PageContent:
    page_number: int
    native_text: str
    has_native_text: bool


def extract_native_pages(pdf_path: str | Path) -> list[PageContent]:
    """Per-page native text, without rendering any image (cheap first pass)."""
    doc = fitz.open(pdf_path)
    try:
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            pages.append(PageContent(
                page_number=i + 1,
                native_text=text,
                has_native_text=len(text) > NATIVE_TEXT_MIN_CHARS,
            ))
        return pages
    finally:
        doc.close()


def render_page_image(pdf_path: str | Path, page_number: int,
                      dpi: int = DEFAULT_DPI) -> np.ndarray:
    """Rasterize one page (1-indexed) to a BGR image, for pages needing OCR."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 1:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return img
    finally:
        doc.close()


def page_count(pdf_path: str | Path) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()
