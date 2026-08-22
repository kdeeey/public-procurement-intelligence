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

import re
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

# Guards against a malformed /MediaBox reporting a wildly oversized physical
# page — confirmed on a real corpus document (c87a91a5..., Issue 5/6): the
# PDF declared a MediaBox of 2479x3507 *points* (34x48 inches), while its
# embedded scan image was an entirely ordinary 2479x3507 *pixel* A4 scan, same
# as every other document in the corpus. The page's units were off by exactly
# the 300/72 dpi-to-pt ratio — a known bug pattern in some scan-to-PDF tools
# that write pixel dimensions straight into MediaBox without converting to
# points. Rendering "at 300 dpi" against that MediaBox blew the image up to
# 151 Mpx/page (10330x14613px) with no new information (pure interpolation of
# a 2479x3507px source), and took ~2 hours through fastNlMeansDenoising for
# this one document alone.
# Capping the longest rendered side rather than capping dpi directly fixes
# this at the source for ANY future document with a similarly malformed
# MediaBox, not just this one: for a normal A4 page at dpi=300 the longest
# side is ~3507px, comfortably under this cap, so ordinary documents render
# exactly as before. 4000px leaves headroom for legitimately larger physical
# pages (e.g. A3 plans) while decisively correcting a MediaBox that lies by
# 4x or more.
MAX_RENDER_DIMENSION_PX = 4000

# Guards against a native text layer that exists but is unusable — found by the
# Issue 6 ground-truth annotation, not by any automated check: several PDFs
# carry a text layer produced with a broken font encoding, so PyMuPDF extracts
# character soup ("ROYAI]ME DU i\{AROC" instead of "ROYAUME DU MAROC") while
# `len(text) > NATIVE_TEXT_MIN_CHARS` still passes. Those documents were
# classified `native`, skipped OCR entirely, and stored garbage silently — the
# worst possible failure mode, because nothing downstream signals it.
#
# Two thresholds rather than one, because neither alone separates the confirmed
# cases from healthy documents (measured over the 113 native documents of the
# corpus):
#   * MALFORMED_TOKEN_MAX_RATIO — share of word-like tokens that are not clean
#     letter sequences. Healthy median 19%, p90 32%; confirmed-broken 43%+.
#     Also catches Arabic-script pages whose text layer is mojibake.
#   * NOISE_CHARS_MAX_PER_1000 — density of []{}\| characters, which broken
#     font maps sprinkle inside words. Healthy median 0.0; confirmed-broken
#     4.8 and 11.7.
# One confirmed case scores 27% malformed (inside the healthy range) but 4.8
# noise, the other 43% malformed — hence the OR. Together they flag 15/113
# native documents (13%).
#
# KNOWN LIMITATION — a second, milder failure class is NOT detected here: a PDF
# whose text layer came from someone else's mediocre OCR (confirmed case:
# "Marché n' 19/CS/2026", "siqnalisation"). That text is ~90% correct French,
# so both metrics rate it healthy. It stays classified `native`. Impact is much
# lower (the text is usable, with scattered character errors) but it means
# `native` does not guarantee a pristine text layer.
MALFORMED_TOKEN_MAX_RATIO = 0.35
NOISE_CHARS_MAX_PER_1000 = 4.0

_TOKEN_RE = re.compile(r"\S{3,}")
_CLEAN_TOKEN_RE = re.compile(r"^[A-Za-zÀ-ÿ]+[.,;:)]?$")
_NOISE_CHARS_RE = re.compile("[" + re.escape('[]{}\\|') + "]")


def text_looks_corrupted(text: str) -> bool:
    """True when an extracted text layer is present but not usable as text.

    Deliberately conservative: a page wrongly sent to OCR only costs time,
    while a corrupted page wrongly kept as `native` silently poisons every
    downstream extraction step.
    """
    if not text:
        return False
    tokens = [t for t in _TOKEN_RE.findall(text) if any(c.isalpha() for c in t)]
    if len(tokens) >= 20:
        malformed = sum(1 for t in tokens if not _CLEAN_TOKEN_RE.match(t)) / len(tokens)
        if malformed > MALFORMED_TOKEN_MAX_RATIO:
            return True
    noise_per_1000 = len(_NOISE_CHARS_RE.findall(text)) / max(len(text) / 1000, 0.1)
    return noise_per_1000 > NOISE_CHARS_MAX_PER_1000


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
            usable = (len(text) > NATIVE_TEXT_MIN_CHARS
                      and not text_looks_corrupted(text))
            pages.append(PageContent(
                page_number=i + 1,
                native_text=text if usable else "",
                has_native_text=usable,
            ))
        return pages
    finally:
        doc.close()


def render_page_image(pdf_path: str | Path, page_number: int,
                      dpi: int = DEFAULT_DPI) -> np.ndarray:
    """Rasterize one page (1-indexed) to a BGR image, for pages needing OCR.

    `dpi` is a request, not a guarantee: if the page's /MediaBox implies an
    output larger than MAX_RENDER_DIMENSION_PX on its longest side, the
    effective dpi is scaled down to respect that cap instead — see the
    module-level comment on MAX_RENDER_DIMENSION_PX for why.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        effective_dpi = dpi
        longest_side_pt = max(page.rect.width, page.rect.height)
        if longest_side_pt > 0:
            projected_px = longest_side_pt / 72 * dpi
            if projected_px > MAX_RENDER_DIMENSION_PX:
                effective_dpi = int(MAX_RENDER_DIMENSION_PX / (longest_side_pt / 72))
        pix = page.get_pixmap(dpi=effective_dpi)
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
