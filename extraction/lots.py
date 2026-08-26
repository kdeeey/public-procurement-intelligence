"""
Lot detection and segmentation (Issue 7).

A PV is not always one market. `data_dictionary.md` §3.4 already warned that
"1 PDF = 1 marché" is false; this module is where that is handled, because
`statut` is a **per-lot** property. Document 349e44bf is the confirmed trap:
lot 1 awarded to LINK RAYONNAGE MAROC, lots 2 and 3 declared infructueux. A
document-level keyword search on "infructueux" inverts its status.

The rule below was tested on the 38 real documents containing "Lot n°X"
*before* being written, and the obvious binary rule ("≥ 2 distinct numbers =
multi-lot") turned out to be wrong in two different ways:

  * 6 of the 7 single-number documents are genuine PVs covering **one lot of a
    larger tender** — "Renforcement de l'AEP de Dakhla - Lot n°2: Conduite".
    Their `lot_numero` is 2, 3 or 4 and must be kept, not flattened to None.
  * 1 document is a false positive where the number belongs to a postal
    address: "SOCIETE ROMATELEC, LOT 27-BD SAAD BOUJAMAA RESIDENCE EL MERS".

Measured today, no document combines address-lots with ≥ 2 distinct numbers,
so the address guard changes no current classification. It is implemented
anyway: the binary rule only avoids that document by coincidence, and two
addresses with different numbers would be enough to defeat it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "Lot n°2", "Lot 2", "LOT N 02", "Lot nº 2"
LOT_MENTION_RE = re.compile(r"\blot\s*n?\s*[°ºo]?\s*(\d{1,2})\b", re.IGNORECASE)

# Words that, right after the number, mean it is a street/parcel number rather
# than a tender lot. Confirmed on ROMATELEC's address; the rest are the usual
# Moroccan address components.
#
# Two OCR variants had to be added after testing on real documents, not
# guessed in advance: the same address ("LOT 27-BD SAAD BOUJAMAA") appears
# 4 times in one document, and one occurrence reads "LOT 27.8D" — a dot
# instead of a dash, and "B" misread as "8". Missing that variant let one
# genuine address slip through as a fake lot number (extraction/lots.py
# verification, doc 78a8bda5...).
ADDRESS_AFTER_RE = re.compile(
    r"^\s*[-.,]?\s*(?:BD|B\.D|[86]D|BOULEVARD|RUE|AV|AVE|AVENUE|RESIDENCE|RES\b|"
    r"HAY|QUARTIER|QUARTIE|LOTISSEMENT|IMM|IMMEUBLE|APPT|ETAGE)\b",
    re.IGNORECASE)

ADDRESS_LOOKAHEAD = 18  # characters inspected after the number

# "(3 LOTS)" in a header, when present, gives the total lot count — lets the
# awarded-but-unnumbered lot be reconstructed by complement in a
# multi_declare document. Confirmed present on 2 of 388 documents, including
# the trap document (349e44bf...) where it is the only way to recover lot 1.
TOTAL_LOTS_RE = re.compile(r"\((\d{1,2})\s*lots?\)", re.IGNORECASE)

# "Liste des lots infructueux : Lot n°02; Lot n°03."
LOTS_INFRUCTUEUX_RE = re.compile(
    r"liste\s+des\s+lots\s+infructueux\s*:?\s*([^\n]+)", re.IGNORECASE)


@dataclass
class LotMention:
    numero: int
    start: int
    end: int
    is_address: bool


@dataclass
class LotSegment:
    """One lot's slice of the document.

    `numero` is None only when the document carries no lot number at all.
    `declared_infructueux` records that an explicit "liste des lots
    infructueux" named this lot — the most reliable signal available, though
    it exists in only 1 document of 388.
    """
    numero: int | None
    text: str
    declared_infructueux: bool = False
    detection: str = "mono_sans_numero"
    warnings: list[str] = field(default_factory=list)


def find_lot_mentions(text: str) -> list[LotMention]:
    """Every "Lot n°X" occurrence, each flagged as address or genuine lot."""
    mentions = []
    for match in LOT_MENTION_RE.finditer(text):
        following = text[match.end():match.end() + ADDRESS_LOOKAHEAD]
        mentions.append(LotMention(
            numero=int(match.group(1)),
            start=match.start(),
            end=match.end(),
            is_address=bool(ADDRESS_AFTER_RE.match(following)),
        ))
    return mentions


def declared_infructueux_lots(text: str) -> set[int]:
    """Lot numbers named by an explicit "liste des lots infructueux" line."""
    match = LOTS_INFRUCTUEUX_RE.search(text)
    if not match:
        return set()
    return {int(n) for n in re.findall(r"\d{1,2}", match.group(1))}


def segment_lots(text: str) -> list[LotSegment]:
    """Split a document into one segment per lot.

    Always returns at least one segment, so callers never special-case an
    empty result. The four outcomes match the measured corpus — see the module
    docstring.
    """
    mentions = find_lot_mentions(text)
    real = [m for m in mentions if not m.is_address]
    ignored_addresses = len(mentions) - len(real)

    warnings = []
    if ignored_addresses:
        warnings.append(
            f"{ignored_addresses} occurrence(s) 'Lot N' ignoree(s) : "
            "numero d'adresse postale, pas un lot de marche")

    infructueux = declared_infructueux_lots(text)
    numeros = sorted({m.numero for m in real})

    if not numeros:
        return [LotSegment(numero=None, text=text,
                           detection="mono_sans_numero", warnings=warnings)]

    if len(numeros) == 1:
        # A PV covering a single lot of a larger tender: keep the number.
        numero = numeros[0]
        return [LotSegment(
            numero=numero,
            text=text,
            declared_infructueux=numero in infructueux,
            detection="mono_numerote",
            warnings=warnings,
        )]

    detection = "multi_declare" if infructueux else "multi_implicite"
    if not infructueux:
        warnings.append(
            "multi-lots deduit du comptage de numeros : aucune ligne "
            "'liste des lots infructueux' pour confirmer")

    segments = _split_by_lot(text, real, numeros, infructueux, detection, warnings)

    if infructueux:
        segments += _reconstruct_awarded_lots(text, numeros, infructueux, warnings)

    return sorted(segments, key=lambda s: (s.numero is None, s.numero or 0))


def _reconstruct_awarded_lots(text: str, named_numeros: list[int],
                              infructueux: set[int],
                              warnings: list[str]) -> list[LotSegment]:
    """Recover the lot(s) a 'liste des lots infructueux' line implies but
    never names — the awarded lot itself, precisely the one that matters most.

    Confirmed trap (349e44bf...): the document declares "Lot n°02; Lot n°03"
    infructueux and never prints "Lot n°01" anywhere, because the award table
    lists the winner's name and amount with the lot number as a bare "01" in
    a misordered OCR cell that LOT_MENTION_RE cannot associate with "lot".
    Without this reconstruction, _split_by_lot only emits segments for lots 2
    and 3 and the awarded lot silently disappears — the opposite of what a
    statut-by-lot design exists to prevent.

    When the total lot count is printed ("(3 LOTS)"), the missing numbers are
    exact. When it is not (the common case — measured on only 2/388
    documents), a single unnumbered segment is still emitted rather than
    dropping the content: losing the awarded lot is worse than an uncertain
    lot_numero.
    """
    total_match = TOTAL_LOTS_RE.search(text)
    if total_match:
        total = int(total_match.group(1))
        missing = sorted(set(range(1, total + 1)) - set(named_numeros) - infructueux)
        if missing:
            return [LotSegment(numero=n, text=text, declared_infructueux=False,
                               detection="multi_declare_complement",
                               warnings=list(warnings) +
                               [f"numero {n} deduit par complement (total {total} lots "
                                "affiche, non nomme explicitement)"])
                    for n in missing]
        return []

    # Total unknown: emit one unnumbered segment rather than lose the content.
    return [LotSegment(
        numero=None, text=text, declared_infructueux=False,
        detection="multi_declare_complement",
        warnings=list(warnings) + [
            "lot attribue present mais jamais numerote explicitement, et le "
            "nombre total de lots n'est pas affiche : lot_numero indetermine, "
            "contenu conserve plutot que perdu"],
    )]


def _split_by_lot(text: str, mentions: list[LotMention], numeros: list[int],
                  infructueux: set[int], detection: str,
                  warnings: list[str]) -> list[LotSegment]:
    """Slice the text at lot boundaries, one segment per distinct number.

    Each lot gets the text from its first mention to the first mention of the
    next lot. Text before the first mention (the shared header: buyer, object,
    dates) is prepended to every segment, since those fields belong to all
    lots — dropping it would leave each lot without its own context.
    """
    first_occurrence = {}
    for mention in mentions:
        first_occurrence.setdefault(mention.numero, mention.start)

    ordered = sorted(numeros, key=lambda n: first_occurrence[n])
    header_end = min(first_occurrence.values())
    header = text[:header_end]

    segments = []
    for index, numero in enumerate(ordered):
        start = first_occurrence[numero]
        end = (first_occurrence[ordered[index + 1]]
               if index + 1 < len(ordered) else len(text))
        segments.append(LotSegment(
            numero=numero,
            text=header + text[start:end],
            declared_infructueux=numero in infructueux,
            detection=detection,
            warnings=list(warnings),
        ))
    return sorted(segments, key=lambda s: s.numero or 0)
