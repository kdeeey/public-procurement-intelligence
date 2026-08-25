"""
Company name normalization and groupement splitting (Issue 8).

Two separate concerns, kept as two functions rather than one:

  * normalize_company_name() — casse/accents/prefixe/suffixe/ponctuation,
    applied to ONE already-isolated company name. Validated against the
    real corpus during the Issue 8 design discussion: merges "STE TP
    HORIZON SARL" / "Sté TP HORIZON SARL", keeps "STE MAROCAINE DES" /
    "CENTRALE MAROCAINE D'ASSURANCES" / "LA MAROCAINE D'ASSAINISSEMENT ET"
    as 3 distinct entities despite sharing "MAROCAINE", and deliberately
    does NOT correct OCR character errors ("SIWERGY" vs "STWERGY" stay
    distinct) or strip trailing addresses — out of scope by design.

  * split_groupement() — turns ONE groupement string into several member
    strings *before* normalize_company_name() runs on each. A groupement is
    one winning Award backed by 2+ companies (data_dictionary.md §3.1,
    "jamais scinde" refers to the Award record, not to how Company rows are
    derived from it) — Award<->Company is many-to-many precisely so a
    groupement's members can be distinct Company rows sharing one Award.
"""

from __future__ import annotations

import re
import unicodedata

LEADING_PREFIXES = ["LA SOCIETE", "SOCIETE", "STE", "SOC"]
LEGAL_SUFFIXES = ["SARL AU", "S A R L AU", "S A R L", "SARL", "SA", "SNC", "AU"]

LEGAL_SUFFIX_TRAILING_RE = re.compile(
    r"(SARL\s*AU|S\.?A\.?R\.?L\s*AU|SARL|S\.?A\.?R\.?L|S\.?A|SNC)\s*$", re.IGNORECASE)

# Marqueur fort : "et (la) societe/ste X" — chaque nouveau membre est
# reintroduit par son propre "Societe"/"Ste", donc un "ET" a l'interieur de
# ce marqueur ne peut jamais appartenir au nom d'un seul membre. Accents
# tolerés explicitement (SOCI[EÉ]T[EÉ], ST[EÉ]) plutôt que de compter sur
# re.IGNORECASE, qui ne fait pas de pliage d'accents — confirmé sur le texte
# réel (doc 03d5069b...) : "la Société" avec un é accentué ne matchait pas
# du tout tant que seule la forme non accentuée était couverte.
MARKER_SPLIT_RE = re.compile(
    r"\bET\s+(?:LA\s+)?(?:SOCI[EÉ]T[EÉ]|ST[EÉ])\b", re.IGNORECASE)

GROUPEMENT_PREFIX_RE = re.compile(r"^\s*-?\s*GROUPEMENT\s*(?:ENTRE)?\s*", re.IGNORECASE)


def _fold_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def normalize_company_name(raw: str) -> str:
    """Cle de deduplication pour Company.normalized_name.

    Ordre : casse+accents -> ponctuation -> prefixe de tete (un seul) ->
    suffixe juridique final (un seul, le plus long en premier).
    """
    if not raw:
        return ""
    s = _fold_accents(raw.upper())
    s = re.sub(r"[.,;:'\"‘’“”«»|]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for prefix in sorted(LEADING_PREFIXES, key=len, reverse=True):
        if s == prefix or s.startswith(prefix + " "):
            s = s[len(prefix):].strip()
            break
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        if s == suffix or s.endswith(" " + suffix):
            s = s[: -len(suffix)].strip()
            break
    return re.sub(r"\s+", " ", s).strip()


def split_groupement(raw: str) -> list[str]:
    """Un texte de groupement -> une liste de noms d'entreprise bruts, un
    par membre. Ne fait AUCUNE normalisation elle-meme — appeler
    normalize_company_name() sur chaque element du resultat ensuite.

    Deux niveaux, dans cet ordre :

      1. Marqueur fort "et (la) societe/ste" (voir MARKER_SPLIT_RE).
      2. Repli " ET " nu, mais accepte seulement si CHAQUE segment obtenu se
         termine par une forme juridique reconnue (SARL, SARL AU, SA...).
         Motive par un piege reel confirme en Issue 7 (doc 03d5069b...) :
         "Societe DANY D'ESSAIS ET ETUDES SARL" contient un "ET" qui fait
         partie du nom lui-meme. Un split naif y produirait "Societe DANY
         D'ESSAIS" (ne se termine par aucune forme juridique) — la
         validation le rejette et le texte entier reste un seul membre.

    Si aucun des deux niveaux ne produit un decoupage fiable, retourne le
    texte entier comme unique membre plutot que de risquer un faux
    decoupage — perdre la segmentation vaut mieux que fabriquer une
    entreprise qui n'existe pas.

    Chaque membre est ensuite coupe a la premiere virgule : dans tous les
    cas reels observes, la virgule separe la raison sociale de son adresse
    ("SARL, Tanger"), jamais l'interieur d'un nom d'entreprise.
    """
    text = GROUPEMENT_PREFIX_RE.sub("", raw).strip()

    parts = MARKER_SPLIT_RE.split(text)
    if len(parts) >= 2:
        members = [p.strip(" ,;") for p in parts if p.strip(" ,;")]
    else:
        candidates = re.split(r"\bET\b", text, flags=re.IGNORECASE)
        trimmed = [c.strip(" ,;") for c in candidates if c.strip(" ,;")]
        if len(trimmed) >= 2 and all(LEGAL_SUFFIX_TRAILING_RE.search(c) for c in trimmed):
            members = trimmed
        else:
            members = [text.strip(" ,;")]

    return [m.split(",")[0].strip() for m in members]
