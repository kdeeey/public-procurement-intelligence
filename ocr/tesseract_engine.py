"""
Thin, configurable wrapper around pytesseract.

Handles what proved necessary on the actual dev machine, not just what
`requirements.txt` lists: the Tesseract binary and the French language pack
were both absent even with pytesseract/opencv installed (see the Issue 5
reconnaissance), and `winget install` does not add tesseract.exe to PATH
without a shell restart. So this module auto-detects the common Windows
install location and falls back gracefully, rather than assuming `tesseract`
resolves on PATH the way it does in the Docker image (Dockerfile installs
tesseract-ocr via apt, which is on PATH — this fallback logic is a no-op there).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytesseract

# RESOLVED (Issue 5, measured 20/08/2026): fra-only produced 6-7 documents in
# the 390-PV corpus at near-zero confidence (0.0-30.5) — not degraded scans,
# but pages written entirely or partly in Arabic, decoded with the wrong
# language model. The corpus is genuinely bilingual (bilingual headers were
# already flagged during reconnaissance; this is full Arabic *pages*, not
# just headers). Tesseract decodes multi-language images directly when given
# more than one model — 'fra+ara' handles both scripts, so mixed-language
# pages (Arabic intro + French concurrent list, the actual data of interest)
# no longer need separating. Requires ara.traineddata in TESSDATA_PREFIX.
DEFAULT_LANG = os.getenv("OCR_LANGUAGE", "fra+ara")

# RESOLVED (Issue 5, measured 20/08/2026): --psm 6 (uniform block) was the
# starting assumption; --psm 3 (fully automatic page segmentation) measured
# better on every document type tested, not just tables:
#   - Table document (EXTRAIT DE PV - AOO N°57-2026.pdf): confidence 82.5→84.2,
#     and --psm 6 misread the `classement` column as "—" where --psm 3 read
#     the correct value "1" — the concrete field this matters for
#     (data_dictionary.md §3.2).
#   - 6 plain-prose documents (regression check): 5 improved (+2.8 to +9.2),
#     1 negligible regression (-0.2), none harmed meaningfully.
#   - 2 of 3 inspected ocr_low_confidence cases recovered to legible French
#     under --psm 3 alone (51.7→78.0, 58.5→68.6) — a bilingual-header /
#     narrow-layout segmentation issue that --psm 6's uniform-block assumption
#     mishandled.
DEFAULT_PSM = int(os.getenv("OCR_PSM", "3"))

# Tesseract's own docs treat an OSD orientation_conf below ~1.0 as essentially
# unreliable — this is used as a coarse noise floor, NOT a precision gate.
# Measured on 18 real scanned samples (Issue 5, 20/08/2026): orientation_conf
# does NOT reliably separate "rotation genuinely needed" from "already
# upright" — a false positive (rd.pdf, already correctly oriented) scored
# 13.99, *higher* than two genuine true positives (10.34, 11.00). A precise
# threshold tuned on this data would be fiction. What the same 18-document
# measurement does show is that the downside of trusting a low-confidence
# suggestion is small and bounded: the one false positive cost -0.8 OCR
# confidence points, while the four true positives gained +6.8 to +46.2. That
# asymmetry, not the confidence number itself, is why applying any non-zero
# `rotate` above this floor is an acceptable default for a prototype — not
# because the confidence value was validated as precise.
OSD_MIN_ORIENTATION_CONF = float(os.getenv("OCR_OSD_MIN_CONFIDENCE", "1.0"))

_WINDOWS_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _configure() -> str | None:
    """Point pytesseract at a working tesseract.exe; return the tessdata dir.

    Only touches Windows-specific paths when the default `tesseract` command
    isn't already resolvable — on Linux/Docker this is a no-op.
    """
    cmd = os.getenv("TESSERACT_CMD")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    elif os.name == "nt":
        for candidate in _WINDOWS_TESSERACT_CANDIDATES:
            if Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = candidate
                break

    return os.getenv("TESSDATA_PREFIX")


# Passed explicitly on every call rather than relying solely on the
# TESSDATA_PREFIX env var reaching the tesseract.exe subprocess, because of a
# real, separately-confirmed bug: pytesseract's run_tesseract() does
# `shlex.split(config, posix=False)` on Windows, and posix=False does not
# strip quote characters — so a naively quoted '--tessdata-dir "C:\...\
# tessdata"' arrives at Tesseract as a literal path string that still has '"'
# characters in it, an invalid directory, silently falling back to Tesseract's
# compiled-in default (which lacks the fra pack here). Reproduced directly via
# shlex.split() with and without quotes before fixing; safe unquoted here
# because TESSDATA_PREFIX has no spaces in it — a path that did would need a
# different fix, since this one can't quote its way out of that given
# pytesseract's parsing.
#
# NOTE on a since-corrected false lead: an earlier version of this comment
# blamed "inconsistent env inheritance across rapidly spawned subprocesses on
# Windows" for a batch of ~20 calls all failing identically. That diagnosis
# was wrong. The batch runs were driven by a throwaway test script living
# outside this repo (OS temp dir); `load_dotenv()` with no explicit path calls
# `find_dotenv()`, which searches upward from the *calling file's* directory,
# not `os.getcwd()` — confirmed directly (`find_dotenv()` returned `''` from
# that script even after `os.chdir()` into the repo). TESSDATA_PREFIX was
# therefore never loaded at all in those runs, `_TESSDATA_DIR` stayed `None`,
# and the `--tessdata-dir` branch below was never even reached — on any of the
# three attempts, which is why "fixing" the quoting bug appeared to change
# nothing. A real script living inside the repo (scripts/run_ocr.py) does not
# have this problem, since `find_dotenv()`'s upward search from scripts/ finds
# the repo-root .env directly. Verified separately that this module is correct
# under genuine repetition: 6 consecutive ocr_image() calls in one process, and
# 6 consecutive process_pdf_safe() calls, both 6/6 successful with a properly
# loaded .env.
_TESSDATA_DIR = _configure()


def _build_config(extra: str = "") -> str:
    """Shared config-string builder — every Tesseract call needs --tessdata-dir
    unquoted (see the module-level comment on _TESSDATA_DIR); centralised so
    that fix can't silently regress in a call added later."""
    config = extra
    if _TESSDATA_DIR:
        config += f" --tessdata-dir {_TESSDATA_DIR}"
    return config.strip()


@dataclass
class OcrResult:
    text: str
    mean_confidence: float
    word_count: int


@dataclass
class OrientationResult:
    rotate: int             # 0/90/180/270 — degrees to rotate to correct
    confidence: float       # Tesseract's orientation_conf, see OSD_MIN_ORIENTATION_CONF
    should_apply: bool      # rotate != 0 and confidence above the noise floor


def ocr_image(image: np.ndarray, lang: str = DEFAULT_LANG,
              psm: int = DEFAULT_PSM) -> OcrResult:
    """Run Tesseract on a preprocessed image; text and confidence together.

    Two Tesseract calls (image_to_string for text, image_to_data for
    confidence) rather than reconstructing text from the data dict — simpler
    and more robust to reading order than joining word boxes by hand. Costs
    a second pass (~1-2s/page measured), acceptable given OCR is already the
    dominant, not marginal, path through this pipeline.
    """
    config = _build_config(f"--psm {psm}")
    text = pytesseract.image_to_string(image, lang=lang, config=config)

    data = pytesseract.image_to_data(image, lang=lang, config=config,
                                     output_type=pytesseract.Output.DICT)
    confidences = [int(c) for c in data["conf"] if str(c) not in ("-1", "")]
    mean_confidence = float(np.mean(confidences)) if confidences else 0.0

    return OcrResult(text=text, mean_confidence=mean_confidence,
                     word_count=len(confidences))


def detect_orientation(gray: np.ndarray) -> OrientationResult:
    """Tesseract's OSD (Orientation and Script Detection) on a page image.

    Runs on grayscale before deskew/denoise/binarization — OSD reads whole-page
    layout cues (text block shapes, not fine character detail), and testing
    showed no benefit to feeding it the heavily-processed binarized image.

    Sparse-text pages (near-blank scans, mostly-table pages with little prose)
    can make Tesseract unable to compute OSD at all — treated as "no rotation",
    not an error, since we have no orientation signal to act on either way.
    """
    config = _build_config()
    try:
        osd = pytesseract.image_to_osd(gray, config=config,
                                       output_type=pytesseract.Output.DICT)
    except pytesseract.pytesseract.TesseractError:
        return OrientationResult(rotate=0, confidence=0.0, should_apply=False)

    rotate = int(osd.get("rotate", 0))
    confidence = float(osd.get("orientation_conf", 0.0))
    should_apply = rotate != 0 and confidence >= OSD_MIN_ORIENTATION_CONF
    return OrientationResult(rotate=rotate, confidence=confidence, should_apply=should_apply)
