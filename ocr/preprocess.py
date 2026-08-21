"""
OpenCV preprocessing for scanned PV/résultat pages, ahead of Tesseract.

Strategy confirmed by measurement (not assumption) on the local sample set —
see docs/discovery_notes.md and the OCR reconnaissance in the Issue 5 thread:

  * Skew on the 18 real scans measured 0.0°-1.1° — essentially none. Deskewing
    unconditionally would add blur for no benefit on the dominant case, so it
    only runs above SKEW_THRESHOLD_DEG.
  * CLAHE (adaptive contrast) measured WORSE than doing nothing: mean Tesseract
    confidence 85.1 vs 87.6 raw, on documents that are already high-contrast
    (bright background, dark text). Deliberately not used.
  * Adaptive thresholding produced more characters but lower confidence (80.0)
    — almost certainly noise, not signal. Not used.
  * Denoise + Otsu measured best (88.5 vs 87.6 raw) — the pipeline below.

The 26 local samples are uniformly clean (office-scanned, not phone photos).
The wider 390-PV corpus may contain worse scans (docs/etat_de_lart.md §3.2
flags phone-photo quality as a known risk) — the deskew step exists for that
case even though it rarely fires on what we've measured so far.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

SKEW_THRESHOLD_DEG = 0.5
DENOISE_STRENGTH = 10  # cv2.fastNlMeansDenoising `h` parameter


@dataclass
class PreprocessResult:
    image: np.ndarray
    skew_angle_deg: float
    deskewed: bool


def to_grayscale(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def measure_skew_angle(gray: np.ndarray) -> float:
    """Median tilt (degrees) of near-horizontal text/rule lines via Hough.

    Returns 0.0 when no reliable lines are found — an unmeasurable page should
    never be rotated on a guess.
    """
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=150,
                            minLineLength=150, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = np.degrees(np.arctan2(int(y2) - int(y1), int(x2) - int(x1)))
        if abs(angle) < 10:  # ignore verticals/diagonals — not text baselines
            angles.append(angle)
    return float(np.median(angles)) if angles else 0.0


_ROTATE_90_STEPS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                    270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def rotate_90_steps(img: np.ndarray, degrees: int) -> np.ndarray:
    """Coarse page-orientation correction (0/90/180/270), from OSD.

    Distinct from `deskew`: this corrects a whole page scanned sideways or
    upside down, not a few tenths of a degree of tilt. Applied before
    `preprocess_for_ocr` — see ocr/pipeline.py.
    """
    if degrees == 0:
        return img
    if degrees not in _ROTATE_90_STEPS:
        return img
    return cv2.rotate(img, _ROTATE_90_STEPS[degrees])


def deskew(gray: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate to correct a measured tilt.

    Rotation sign verified synthetically (rotate a clean page by a known
    angle, measure it, correct, confirm the residual angle collapses to ~0 —
    see Issue 5 test notes): passing `angle_deg` unchanged into cv2's rotation
    matrix cancels the measured tilt. The first version of this function
    negated the angle, which on inspection *doubled* the tilt instead of
    removing it (residual ~2x the original angle, same sign) — caught only by
    checking the residual angle after "correction", not by eyeballing the
    image or trusting OCR confidence alone, which barely moved either way.

    Real 26-sample corpus measures 0.0°-1.2° of skew, under SKEW_THRESHOLD_DEG,
    so this path has not yet been exercised on a genuinely skewed real page —
    only synthetically. Re-check once one turns up in the wider 390-PV corpus.
    """
    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=DENOISE_STRENGTH)


def binarize_otsu(gray: np.ndarray) -> np.ndarray:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def preprocess_for_ocr(img: np.ndarray,
                       skew_threshold_deg: float = SKEW_THRESHOLD_DEG) -> PreprocessResult:
    """grayscale -> conditional deskew -> denoise -> Otsu binarization."""
    gray = to_grayscale(img)
    angle = measure_skew_angle(gray)

    deskewed = False
    if abs(angle) > skew_threshold_deg:
        gray = deskew(gray, angle)
        deskewed = True

    gray = denoise(gray)
    binary = binarize_otsu(gray)

    return PreprocessResult(image=binary, skew_angle_deg=angle, deskewed=deskewed)
