"""
OCR pipeline (Issue 5): PDF -> per-page text, native or OCR'd, with a
document-level `ocr_status`.

Scope boundary (deliberate): this module stops at clean-ish raw text plus a
confidence signal. Header isolation, apostrophe normalization and other text
cleanup belong to Issue 6 (ocr/text_cleaning.py, not yet written) — mixing
that in here would make it harder to evaluate the OCR step on its own merits,
which is the point of measuring `ocr_status` and confidence separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ocr.pdf_to_image import extract_native_pages, page_count, render_page_image
from ocr.preprocess import preprocess_for_ocr, rotate_90_steps, to_grayscale
from ocr.tesseract_engine import detect_orientation, ocr_image

# Below this mean Tesseract confidence (0-100), a document is flagged rather
# than silently trusted — matches the OCR_CONFIDENCE_THRESHOLD env var so a
# team member can tighten/loosen it without touching code.
import os

CONFIDENCE_THRESHOLD = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "60"))

# RESOLVED (Issue 5, measured 20/08/2026, corpus case c66cad5f...): a document
# with one excellent page (conf 88.0) and one essentially blank page (a
# signature/annex page, 0 recognized words, conf 0.0) averaged to 44.0 and
# was flagged ocr_low_confidence — the blank page carries no signal, good or
# bad, and shouldn't drag down a page that's actually fine. A page below this
# word count contributes no text worth extracting either way, so it is
# dropped from the document-level mean rather than treated as a failure.
MIN_WORDS_FOR_CONFIDENCE = int(os.getenv("OCR_MIN_WORDS_FOR_CONFIDENCE", "3"))

NATIVE = "native"
OCR_SUCCESS = "ocr_success"
OCR_LOW_CONFIDENCE = "ocr_low_confidence"
OCR_FAILED = "ocr_failed"


@dataclass
class PageResult:
    page_number: int
    text: str
    source: str  # "native" | "ocr"
    confidence: float | None = None       # None for native pages — not applicable
    skew_angle_deg: float | None = None
    deskewed: bool = False
    orientation_rotate_deg: int = 0       # 0/90/180/270 applied from OSD, 0 if none
    orientation_confidence: float | None = None
    error: str | None = None


@dataclass
class DocumentOcrResult:
    pdf_path: str
    ocr_status: str
    pages: list[PageResult] = field(default_factory=list)
    mean_confidence: float | None = None  # over OCR'd pages only

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)


def process_pdf(pdf_path: str | Path, dpi: int = 300) -> DocumentOcrResult:
    """Per-page native-vs-OCR decision, then a document-level status.

    A PV can mix a typed cover page with scanned annexes, so each page is
    decided independently; the document only counts as fully `native` when
    every page is. Otherwise the status reflects the OCR'd pages: `ocr_failed`
    only when OCR was attempted and produced nothing usable at all, so a
    partially-successful multi-page document is never silently marked as a
    total failure.
    """
    pdf_path = str(pdf_path)
    native_pages = extract_native_pages(pdf_path)
    pages: list[PageResult] = []
    ocr_confidences: list[float] = []
    ocr_attempted = False
    ocr_all_failed = True

    for native in native_pages:
        if native.has_native_text:
            pages.append(PageResult(page_number=native.page_number,
                                    text=native.native_text, source="native"))
            continue

        ocr_attempted = True
        try:
            image = render_page_image(pdf_path, native.page_number, dpi=dpi)

            # Coarse orientation (0/90/180/270) before fine deskew/denoise —
            # a page scanned sideways or upside down needs correcting first,
            # otherwise Hough-based deskew (which only handles small tilts)
            # and Otsu binarization operate on a page that's fundamentally
            # the wrong way up. See OSD_MIN_ORIENTATION_CONF in
            # tesseract_engine.py for why `should_apply` is a coarse floor,
            # not a precision gate.
            orientation = detect_orientation(to_grayscale(image))
            if orientation.should_apply:
                image = rotate_90_steps(image, orientation.rotate)

            prep = preprocess_for_ocr(image)
            result = ocr_image(prep.image)
            ocr_all_failed = False
            if result.word_count >= MIN_WORDS_FOR_CONFIDENCE:
                ocr_confidences.append(result.mean_confidence)
            pages.append(PageResult(
                page_number=native.page_number, text=result.text, source="ocr",
                confidence=result.mean_confidence,
                skew_angle_deg=prep.skew_angle_deg, deskewed=prep.deskewed,
                orientation_rotate_deg=orientation.rotate if orientation.should_apply else 0,
                orientation_confidence=orientation.confidence,
            ))
        except Exception as e:  # noqa: BLE001 - one bad page must not sink the document
            pages.append(PageResult(page_number=native.page_number, text="",
                                    source="ocr", error=str(e)))

    if not ocr_attempted:
        status = NATIVE
        mean_conf = None
    elif ocr_all_failed:
        status = OCR_FAILED
        mean_conf = None
    elif not ocr_confidences:
        # Every OCR'd page was near-blank (below MIN_WORDS_FOR_CONFIDENCE) —
        # OCR ran without error but found essentially nothing to score. Not a
        # failure (nothing crashed) and not worth trusting either — flagged
        # for the same reason a low mean confidence would be.
        status = OCR_LOW_CONFIDENCE
        mean_conf = 0.0
    else:
        mean_conf = sum(ocr_confidences) / len(ocr_confidences)
        status = OCR_SUCCESS if mean_conf >= CONFIDENCE_THRESHOLD else OCR_LOW_CONFIDENCE

    return DocumentOcrResult(pdf_path=pdf_path, ocr_status=status, pages=pages,
                             mean_confidence=mean_conf)


def process_pdf_safe(pdf_path: str | Path, dpi: int = 300) -> DocumentOcrResult:
    """Same as process_pdf, but never raises — used by batch runs over a corpus
    where one corrupted PDF must not abort the whole pass."""
    try:
        return process_pdf(pdf_path, dpi=dpi)
    except Exception as e:  # noqa: BLE001
        return DocumentOcrResult(pdf_path=str(pdf_path), ocr_status=OCR_FAILED,
                                 pages=[PageResult(page_number=0, text="",
                                                   source="ocr", error=str(e))])
