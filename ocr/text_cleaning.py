"""
Text cleaning for OCR output (Issue 6).

Runs *after* ocr/pipeline.py, on the raw text it produced. Deliberately
conservative: every transformation here either removes something provably
meaningless (invisible control characters), or restores something the PDF
font mangled (private-use bullets) — never anything that could be data.

The noise this targets was measured on the real 388-document corpus, not
assumed:

  * 9 267 invisible directional marks (U+200E / U+200F). Tesseract inserts
    them around Arabic fragments in a `fra+ara` pass; they are invisible on
    screen but break any substring match on the text around them.
  * 436 private-use-area characters (U+F0B7 and friends) — Wingdings/Symbol
    bullets that PDF fonts map into the PUA. They render as tofu and split
    words when a bullet sits mid-line.
  * 321 of 388 documents contain Arabic characters. Those are NOT noise:
    the corpus is genuinely bilingual (see methodology.md §1.3). Arabic is
    therefore *separated*, never deleted — a document written entirely in
    Arabic must not come out empty.

What this module explicitly does NOT do: fix OCR character errors
("STWERGY" for "SIWERGY"). Those are a property of the recognition step;
correcting them here would hide the very thing the Issue 6 evaluation is
meant to measure.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# Invisible formatting characters. Safe to drop unconditionally: they carry
# no textual meaning and only exist to hint bidirectional rendering.
INVISIBLE_CHARS = "".join([
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "‎",  # left-to-right mark      (5 266 occurrences in the corpus)
    "‏",  # right-to-left mark      (4 001 occurrences)
    "‪", "‫", "‬", "‭", "‮",  # bidi embedding/override
    "﻿",  # byte order mark
])
_INVISIBLE_RE = re.compile("[" + re.escape(INVISIBLE_CHARS) + "]")

# Private-use codepoints seen in the corpus, mapped back to what the symbol
# font meant. Anything else in the PUA becomes a space rather than being
# deleted, so it still separates words.
PRIVATE_USE_MAP = {
    "": "•",   # Symbol bullet      (356 occurrences)
    "": "✓",   # Wingdings check    (63)
    "": "▪",   # Wingdings square   (12)
    "": "-",   # hyphen             (4)
    "": "✓",   # Wingdings check    (3)
    "": "•",   # bullet             (1)
}
_PUA_RE = re.compile(r"[-]")

# Curly punctuation -> ASCII. Matters because the ground truth is typed with
# straight quotes while PDFs use typographic ones; without this, every
# "d'ouvrage" fails to match "d’ouvrage".
TYPOGRAPHY_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
    "…": "...",
}

ARABIC_RANGES = (
    ("؀", "ۿ"),  # Arabic
    ("ݐ", "ݿ"),  # Arabic Supplement
    ("ﭐ", "﷿"),  # Arabic Presentation Forms-A
    ("ﹰ", "﻿"),  # Arabic Presentation Forms-B
)

# A line is treated as page furniture only if it repeats across the document
# AND looks like a header/footer. Repetition alone is not enough: a real PV
# legitimately repeats a company name on every row of a multi-lot table
# (confirmed case 44b28d32..., "NS MEDICAL" 15 times - methodology.md 1.6).
#
# The date guard below is not theoretical. A first version of this pattern
# used a bare \d{1,2}/\d{1,2} to catch "1/2" page numbers, and silently
# deleted the line "Date d'ouverture des plis : Le 27/07/2026 a 12 heures"
# from a multi-lot PV, because "27/07" matched too and the line repeated once
# per lot. The evaluation caught it as a lost ground-truth value. Any line
# carrying a full date is therefore never furniture, whatever else it looks
# like: dates are exactly the payload Issue 7 needs.
_FULL_DATE_RE = re.compile(r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}")
_PAGE_NUMBER_RE = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}\b(?!\s*[/.-]?\s*\d)")
_PAGE_WORD_RE = re.compile(r"\b(page|A\.?O\.?\s*N)", re.IGNORECASE)
MAX_FURNITURE_LINE_LEN = 60
MIN_FURNITURE_REPEATS = 2


@dataclass
class CleanedText:
    """Result of cleaning one document.

    `text` is the cleaned full text (Arabic still in place). `text_fr` has
    Arabic runs removed, for downstream French-oriented extraction. `text_ar`
    keeps what was removed, so nothing is silently lost.
    """
    text: str
    text_fr: str
    text_ar: str
    stats: dict[str, int] = field(default_factory=dict)


def _is_arabic(char: str) -> bool:
    return any(low <= char <= high for low, high in ARABIC_RANGES)


def remove_invisible(text: str) -> str:
    return _INVISIBLE_RE.sub("", text)


def map_private_use(text: str) -> str:
    """Restore known symbol-font characters; neutralise the rest to a space."""
    return _PUA_RE.sub(lambda m: PRIVATE_USE_MAP.get(m.group(0), " "), text)


def normalize_typography(text: str) -> str:
    for src, dst in TYPOGRAPHY_MAP.items():
        text = text.replace(src, dst)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs and blank lines, without joining lines.

    Line structure is kept on purpose: PV layout is line-oriented (one field
    per line), and Issue 7's regexes will rely on it.
    """
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def is_page_furniture(line: str) -> bool:
    """Whether a line looks like a repeated header/footer rather than content."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_FURNITURE_LINE_LEN:
        return False
    if _FULL_DATE_RE.search(stripped):
        return False  # never drop a line carrying a date - see note above
    return bool(_PAGE_NUMBER_RE.search(stripped) or _PAGE_WORD_RE.search(stripped))


def strip_page_furniture(text: str) -> tuple[str, int]:
    """Drop repeated header/footer lines. Returns (text, lines_removed)."""
    lines = text.splitlines()
    counts = Counter(line.strip() for line in lines if line.strip())
    furniture = {
        line for line, n in counts.items()
        if n >= MIN_FURNITURE_REPEATS and is_page_furniture(line)
    }
    if not furniture:
        return text, 0
    kept = [line for line in lines if line.strip() not in furniture]
    return "\n".join(kept), len(lines) - len(kept)


def split_scripts(text: str) -> tuple[str, str]:
    """Separate Arabic from the rest. Returns (french_text, arabic_text).

    Works on runs rather than individual characters so that an Arabic word
    embedded mid-sentence disappears cleanly instead of leaving fragments.
    """
    french_parts: list[str] = []
    arabic_parts: list[str] = []
    buffer: list[str] = []
    buffer_is_arabic = False

    for char in text:
        if char.isspace():
            buffer.append(char)
            continue
        char_is_arabic = _is_arabic(char)
        if buffer and char_is_arabic != buffer_is_arabic:
            (arabic_parts if buffer_is_arabic else french_parts).append("".join(buffer))
            buffer = []
        buffer_is_arabic = char_is_arabic
        buffer.append(char)
    if buffer:
        (arabic_parts if buffer_is_arabic else french_parts).append("".join(buffer))

    return "".join(french_parts), "".join(arabic_parts)


def clean(text: str) -> CleanedText:
    """Full cleaning pass. Order matters: invisible characters first, so that
    later steps see contiguous words rather than fragments."""
    original_len = len(text)

    step = remove_invisible(text)
    invisible_removed = original_len - len(step)

    pua_count = len(_PUA_RE.findall(step))
    step = map_private_use(step)
    step = normalize_typography(step)
    step, furniture_removed = strip_page_furniture(step)
    step = normalize_whitespace(step)

    french, arabic = split_scripts(step)
    french = normalize_whitespace(french)

    return CleanedText(
        text=step,
        text_fr=french,
        text_ar=arabic.strip(),
        stats={
            "chars_in": original_len,
            "chars_out": len(step),
            "invisible_removed": invisible_removed,
            "private_use_mapped": pua_count,
            "furniture_lines_removed": furniture_removed,
            "arabic_chars": sum(1 for c in arabic if not c.isspace()),
        },
    )


def normalize_for_matching(value: str) -> str:
    """Aggressive normalisation used when comparing a value to a text.

    Strips accents, case and every non-alphanumeric character, so that
    "N°08/2023/CRIDOE" and "n 08 - 2023 cridoe" compare equal. Applied to
    both sides of a comparison — see scripts/evaluate_ocr.py.
    """
    decomposed = unicodedata.normalize("NFD", str(value))
    ascii_only = decomposed.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())
