"""
Regexes for extracting structured fields from OCR'd PV text (Issue 7).

Every pattern here is deliberately tolerant of a *missing or mis-read
separator*. That is not defensive programming for its own sake — it is the
measured weak point of the OCR on this corpus. Three of the six residual
failures of Issue 6 come from exactly this (methodology.md §2.9):

    6163200          the decimal comma of "61 632,00" was dropped
    13107 /2026      the "/" of "13/07/2026" was read as "1" then "0"
    3 322 992,OO     the decimals were read as letters O

A strict pattern would reject all three. The cost of tolerance is a wider net
that may catch extra candidates; the extractors in fields.py resolve that by
preferring labelled matches over loose ones, never the other way round.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #

# Digits including the characters the OCR substitutes for them. "O"/"o"/"Q"
# for zero is the confirmed case (3 322 992,OO); "l"/"I" for one and "S" for
# five are the other classic confusions of this font family.
DIGIT = r"[0-9OoQlIS]"

# Thousands separator: space, non-breaking space, dot, or nothing at all.
THOUSANDS_SEP = r"[ . ]?"

# Date separator: the usual ones, plus "1" and "0" because the "/" is read as
# a digit on some scans, plus a bare space.
#
# Two-tier on purpose. A single permissive class is wrong in both directions
# at once: tested on doc 9140a66a..., DATE_SEP matched "28/12/2023" as
# "28"+"/1"+"2"+"/2023" — the tolerant class greedily ate the real "/" *and*
# the leading "1" of "12" as "separator", turning a clean date into 28/02/2023.
# The corrupted case it exists for ("13107 /2026") only needs the tolerant
# class when the strict one fails, never before.
DATE_SEP_STRICT = r"[/.\-]"
DATE_SEP_TOLERANT = r"[/.\-\s01]{1,3}"

MONTHS_FR = ("janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
             "septembre|octobre|novembre|d[ée]cembre")

# --------------------------------------------------------------------------- #
# Amounts
# --------------------------------------------------------------------------- #

# A number with optional grouping and optional decimals. Decimals are optional
# on purpose: "6163200" (comma lost) must still be captured, and fields.py
# decides what it means rather than the regex silently discarding it.
AMOUNT = (rf"{DIGIT}{{1,3}}(?:{THOUSANDS_SEP}{DIGIT}{{3}})*"
          rf"(?:\s*[,.]\s*{DIGIT}{{1,3}})?")

# Guarded the same way as AMOUNT_TTC_RE/AMOUNT_HT_RE below: without (?<!\w),
# a bare OCR-confusable letter mid-word (the "S" in "Dhs", "l"/"I" elsewhere)
# can be picked up as a spurious 1-digit amount.
AMOUNT_RE = re.compile(rf"(?<!\w){AMOUNT}")

# TTC / HT markers, in every spelling seen in the corpus: "DH/TTC", "DHS TTC",
# "T.T.C", "toutes taxes comprises", "H.T", "hors taxes".
TTC_MARKER = r"(?:T\s*\.?\s*T\s*\.?\s*C|toutes\s+taxes\s+comprises)"
HT_MARKER = r"(?:H\s*\.?\s*T\b|hors\s+taxes)"

# Currency word between the amount and its base marker — confirmed on doc
# 9140a66a...: "un montant de 721 224.86 Dirhams TTC" (the currency is
# spelled out, not just the "DH"/"MAD" abbreviation this used to allow for).
CURRENCY = r"(?:DHS?|MAD|Dirhams?)"
# (?<!\w) rather than \b: DIGIT includes letters (O/o/Q/l/I/S), so a plain \b
# does not stop a match starting mid-word. Confirmed on doc 9140a66a...: with
# no guard, AMOUNT_TTC_RE matched "s T.T.C" out of "Dhs T.T.C" — the "S" in
# the digit-confusion class treated the literal "s" of "Dhs" as a one-digit
# amount ("5"), the same over-permissiveness trap noted in patterns.py's
# module docstring, now caught concretely. (?<!\w) requires the character
# immediately before the amount to be a non-word character (space, start of
# string, punctuation), which "Dhs"'s internal "h" is not.
AMOUNT_TTC_RE = re.compile(rf"(?<!\w)({AMOUNT})\s*{CURRENCY}?\s*[/\-]?\s*{TTC_MARKER}",
                           re.IGNORECASE)
AMOUNT_HT_RE = re.compile(rf"(?<!\w)({AMOUNT})\s*{CURRENCY}?\s*[/\-]?\s*{HT_MARKER}",
                          re.IGNORECASE)

# The dominant real layout is the reverse of the two above: a table header
# names the base ("Concurrents / Montant d'acte d'engagement en Dhs TTC"),
# and the amount itself sits on the *next* line, next to the bidder's name —
# confirmed on doc 3a6a7d16..., where AMOUNT_TTC_RE/AMOUNT_HT_RE never match
# at all because no amount is immediately adjacent to the word "TTC"
# anywhere in the text. fields.py falls back to this header + forward search
# only when the immediate-adjacency patterns above find nothing.
# [\s\S] rather than [^\n]: confirmed on doc ea9b61ee..., a wrapped two-column
# header prints "Montants des actes d'engagement ... apres\navant
# verifications DH TTC ... DH TTC" — the word "TTC" only appears after a line
# break the header text itself wraps across. Same fix as LABEL_REFERENCE.
HEADER_TTC_RE = re.compile(rf"montant[\s\S]{{0,60}}{TTC_MARKER}", re.IGNORECASE)
HEADER_HT_RE = re.compile(rf"montant[\s\S]{{0,60}}{HT_MARKER}", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

# Strict pass first (real "/", ".", "-" only) so a clean date like
# "28/12/2023" is never put at risk by the tolerant class below. The tolerant
# pass is a fallback fields.py only reaches for when the strict one fails —
# see the DATE_SEP_STRICT / DATE_SEP_TOLERANT comment above.
DATE_NUMERIC_STRICT_RE = re.compile(
    rf"\b({DIGIT}{{1,2}}){DATE_SEP_STRICT}({DIGIT}{{1,2}}){DATE_SEP_STRICT}({DIGIT}{{4}})\b")
DATE_NUMERIC_TOLERANT_RE = re.compile(
    rf"\b({DIGIT}{{1,2}}){DATE_SEP_TOLERANT}({DIGIT}{{1,2}}){DATE_SEP_TOLERANT}({DIGIT}{{4}})\b")

# DIGIT rather than \d for the day, same tolerance as the numeric patterns —
# confirmed on doc 48f26629ef23...: "Mercredi l5 juillet 2026" (day OCR'd as
# "l5", the letter l substituting for 1). The year keeps \d{4}: a substituted
# letter inside a year is not a confirmed corpus case and would risk
# swallowing unrelated digits from a genuine 4-digit run.
DATE_TEXTUAL_RE = re.compile(
    rf"\b({DIGIT}{{1,2}})\s*(?:er)?\s+({MONTHS_FR})\s+(\d{{4}})\b", re.IGNORECASE)

LABEL_DATE_OUVERTURE = re.compile(
    r"date\s*(?:et\s*heure)?\s*d[’'`\s]*ouverture\s+des\s+plis\s*:?", re.IGNORECASE)
# The connector between "travaux" and "commission" tolerates 0-2 arbitrary
# tokens rather than requiring literally "de la": text_cleaning.split_scripts
# strips a bidi-wrapped Arabic word that stands in for this connector, and
# what it leaves behind varies by document — confirmed on 4 different real
# shapes: "travaux commission" (both "de" and "la" gone, 03d5069b92a3...),
# "travaux de commission" ("la" gone, ea9b61ee0d2b..., 3d46704d054d...),
# "travaux de 1 commission" ("la" replaced by a stray "1", ca886572a390...),
# and the earlier-confirmed "travaux la commission" ("de" gone,
# 2a36f6540d91...). A fixed set of optional literal words could not cover
# all four at once; matching 0-2 arbitrary tokens can, without needing to
# know in advance what the corruption leaves behind.
LABEL_DATE_ACHEVEMENT = re.compile(
    r"date\s+d[’'`\s]*ach[èeé]vement\s+des\s+travaux\s+(?:\S+\s+){0,2}commission\s*:?",
    re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Reference
# --------------------------------------------------------------------------- #

# References have no fixed format across buyers (data_dictionary.md §2):
# "AON31/2024/SO2300UP", "22/2026/DAAC/BG", "10008361", "211/2025/SRMFM".
# Anchored on the label rather than on a shape, precisely because the shape
# varies.
# [\s\S] instead of [^\n], deliberately: tested on doc 9140a66a..., the
# reference sits on the line *after* "... D'APPEL D'OFFRES OUVERT" ("N°08/
# 2023/CRIDOE" starts the next line). A newline-excluding gap can never match
# that layout, so the label silently failed on it. The 40-char cap keeps this
# from reaching past the actual title block into unrelated text.
# n(?![a-zà-öø-ÿ]) rather than a bare "n": the lazy [\s\S]{0,40}? stops at
# the FIRST "n" it can reach, and the standard title phrase "Appel d'offres
# ouvert NATIONAL N° 38/2024" puts one right there — the "N" of "NATIONAL",
# not the real "N°" that follows it. Confirmed on 3 documents (3d46704d054d,
# 4eac1e85166e, 03d5069b92a3), all producing the same telltale garbage value
# "ATIONAL" (REFERENCE_VALUE grabbing the rest of that word). The lookahead
# blocks any "n" that is followed by another letter — i.e. part of a longer
# word — while still accepting "N°", "N:", or a bare "N" directly followed
# by a digit.
# Two more label wordings, added after measuring their frequency across the
# corpus rather than guessing: "AO n°..." (16/388 documents, the abbreviated
# form of "Appel d'Offres") and "Numero :" (2/388 — confirmed on doc
# ea9b61ee0d2b..., where it also happens to be the *only* usable label
# because that document's "offres" is itself OCR-corrupted to "0705",
# making the appel-d'offres alternative unmatchable regardless).
LABEL_REFERENCE = re.compile(
    r"(?:appel\s+d[’'`\s]*offres?[\s\S]{0,40}?n(?![a-zà-öø-ÿ])\s*[°ºo:]?|"
    r"r[ée]f[ée]rence\s*:?|march[ée]\s+n(?![a-zà-öø-ÿ])\s*[°ºo:]?|"
    r"num[ée]ro\s*:?|AO\s*n(?![a-zà-öø-ÿ])\s*[°ºo:]?)\s*",
    re.IGNORECASE)
# "/" may be followed by a single stray space in the OCR text ("N°19/ 2024")
# — confirmed on doc 1046ec535626..., where the plain character class (no
# whitespace allowed at all) truncated the value to "19/" right before the
# space, losing "2024" entirely. Handled only right after "/", not as
# general whitespace tolerance, to avoid bleeding into the surrounding
# prose on documents where the reference is genuinely unpadded.
REFERENCE_VALUE = re.compile(r"[A-Z0-9](?:[A-Z0-9.\-]|/\s?){2,40}", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Winner / bidders
# --------------------------------------------------------------------------- #

LABEL_CONCURRENT_RETENU = re.compile(
    r"(?:concurrents?\s+retenus?|soumissionnaire\s+retenu|attributaire|"
    r"offres?\s+retenues?)\s*:?", re.IGNORECASE)

LABEL_LISTE_CONCURRENTS = re.compile(
    r"liste\s+des\s+concurrents?[^\n:]{0,60}:?", re.IGNORECASE)

LABEL_ECARTES = re.compile(
    r"liste\s+des\s+concurrents?\s+(?:[ée]cart[ée]s?|[ée]vinc[ée]s?)[^\n:]{0,80}:?",
    re.IGNORECASE)

# A consortium is a single winner made of several companies — the Award model
# must keep it whole (data_dictionary.md §3.1), never split it.
GROUPEMENT_RE = re.compile(r"\bgroupement\b", re.IGNORECASE)

# The winner's name is sometimes embedded in a justification sentence rather
# than following the label directly — confirmed on doc 9140a66a...:
# "L'offre economiquement la plus avantageuse est l'offre presentee par la
# societe TECTRA, pour un montant de 721 224.86 Dirhams TTC". Captures up to
# the next comma/period/"pour", which is exactly "TECTRA" on that document.
# Only tried on non-groupement blocks — a groupement's "societe X et la
# societe Y" must stay whole, never truncated to the first company found.
SOCIETE_NAME_RE = re.compile(
    r"soci[ée]t[ée]\s+([^,\.\n]{2,60}?)(?:\s*,|\s+pour\b|\.|$)", re.IGNORECASE)

# Gates SOCIETE_NAME_RE: only strip "societe" from a candidate when this
# specific justification phrasing is present. A plain table listing
# ("Societe MAIRAV") never contains "presentee par" — only the descriptive
# sentence form does, and only there is "societe" a connector word rather
# than part of the printed value (data_dictionary.md's own example keeps
# "Societe" in a name: "Groupement ART STAM SARL AU et TECH-LUX SARL AU").
PRESENTE_PAR_RE = re.compile(r"pr[ée]sent[ée]e?\s+par", re.IGNORECASE)

# A line that only restates the label / a table caption ("Concurrent retenu
# Montant d'acte d'engagement") rather than carrying a value — confirmed on
# doc 03d5069b...: the real value (a groupement's names) sits two lines below
# the label, past exactly one such re-stated header line.
# French function words included on purpose: caption lines are short table
# headers built almost entirely out of them ("Montant de l'acte d'engagement
# en Dhs TTC") — without "en"/"l"/"du"/"le"/"la", that exact line failed the
# all-words-must-be-known check (missing just "en") and was returned as if it
# were the winner's name, confirmed on docs 3a6a7d16..., aabc5317...,
# ca886572..., 5ed398a3..., 4eac1e85166e..., 551178cf065f....
_CAPTION_WORDS = frozenset({
    "concurrent", "concurrents", "retenu", "retenus", "montant", "montants",
    "d", "de", "des", "du", "le", "la", "l", "en", "acte", "actes",
    "engagement", "attributaire", "soumissionnaire", "soumissionnaires",
    "nom", "offre", "offres", "financiere", "financieres", "dhs", "dh",
    "mad", "ttc", "ht", "t.t.c", "h.t", "lettres", "chiffres", "lot", "n",
    "delai", "execution",
})

# Words that mark the start of a *different* section following the winner's
# name — the block collector must stop before these, not absorb them.
# Confirmed on 9 of 16 concurrent_retenu ground-truth documents: without a
# stop marker, the collector kept appending lines past the real value (the
# amount, then "Justification du choix...", sometimes even the achevement
# date), producing a technically-non-empty but badly polluted result like
# "IMS TECHNOLOGY TF :2 196 000.00 ... Justification du choix de
# l'attributaire : ... Date d'achevement des travaux de la commission : ...".
NEW_SECTION_RE = re.compile(
    r"\bjustification\b|\bdate\s+d[’'`\s]*ach[èeé]vement\b|\bfait\s+[àa]\b|"
    r"\bsign[ée]\b|\ble\s+pr[ée]sident\b", re.IGNORECASE)

# "Néant" marks an absent value; NENAT is the confirmed OCR variant.
NEANT_RE = re.compile(r"^\s*(?:n[ée]ant|nenat|n[ée]ent)\s*\.?\s*$", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Statut
# --------------------------------------------------------------------------- #

INFRUCTUEUX_RE = re.compile(r"infructueu", re.IGNORECASE)
LOTS_INFRUCTUEUX_RE = re.compile(
    r"liste\s+des\s+lots\s+infructueux\s*:?\s*([^\n]+)", re.IGNORECASE)

# Deliberately NOT a plain search for "excessif": all 5 occurrences in the
# corpus are the heading "Justifier les prix jugés excessifs : Articles 05
# et 10", a per-article price justification, never a rejected offer. Only an
# explicit rejection counts (ocr/matching.py → infer_statut_indices()).
OFFRE_EXCESSIVE_RE = re.compile(
    r"(?:offres?|prix)[^\n]{0,40}(?:jug[ée]e?s?|d[ée]clar[ée]e?s?)[^\n]{0,20}"
    r"excessi[fv]e?s?[^\n]{0,40}(?:[ée]cart|rejet|non\s+retenu)", re.IGNORECASE)
JUSTIFICATION_PRIX_RE = re.compile(
    r"justifier\s+les\s+prix\s+jug[ée]s\s+excessifs", re.IGNORECASE)
