"""
Genere extraction/corpus_common_words.json — les tokens qui apparaissent
dans une large majorite des PV du corpus (Issue 7/8, 27/08/2026).

A quoi ca sert. `extraction/company_name.py` isole le nom d'entreprise en
prenant le plus long span sans mot-outil. Quand tout le reste a ete coupe,
il arrive qu'il ne survive qu'UN mot, et ce mot est parfois un terme
generique du gabarit de PV plutot qu'une marque : "TRAVAUX" (present dans
94,8% des 388 documents), "TECHNIQUES" (73,2%), "PUBLICS" (64,7%). Un nom
d'entreprise d'un seul mot est parfaitement ordinaire (SEDERAM, CHRONOTECH,
BOLIGAM — mesures a 0,3% de frequence documentaire chacun), donc on ne peut
pas rejeter sur le nombre de mots ; on peut en revanche rejeter sur le fait
qu'un mot present dans les trois quarts des PV du corpus n'est
statistiquement pas une marque.

Le seuil est MESURE, pas choisi a priori : voir COMMON_WORD_DF_THRESHOLD
dans extraction/company_name.py pour la justification et les cas limites.

Volontairement calcule sur le corpus du projet et non sur une liste de mots
francais courants exterieure : ce qui compte ici n'est pas "ce mot est-il
courant en francais" mais "ce mot fait-il partie du gabarit imprime des PV
marocains" — deux choses differentes ("PUBLICS" est banal dans ce corpus,
rare ailleurs).

    python scripts/generate_common_words.py
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ocr.text_cleaning import clean  # noqa: E402

OCR_DIR = REPO / "data/processed/ocr"
OUT_PATH = REPO / "extraction/corpus_common_words.json"

# Meme seuil que COMMON_WORD_DF_THRESHOLD (extraction/company_name.py) —
# duplique ici pour que le fichier genere soit deja filtre et reste petit.
DF_THRESHOLD = 0.02

_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9&-]*")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def main() -> int:
    txt_files = sorted(OCR_DIR.glob("*.txt"))
    if not txt_files:
        print(f"aucun texte OCR dans {OCR_DIR}", file=sys.stderr)
        return 1

    df: Counter[str] = Counter()
    for path in txt_files:
        text = clean(path.read_text(encoding="utf-8")).text
        df.update(set(_TOKEN_RE.findall(_fold(text.upper()))))

    n_docs = len(txt_files)
    common = sorted(w for w, n in df.items()
                    if n / n_docs >= DF_THRESHOLD and len(w) >= 3)

    OUT_PATH.write_text(json.dumps({
        "n_documents": n_docs,
        "df_threshold": DF_THRESHOLD,
        "note": ("Tokens presents dans au moins df_threshold des documents du "
                 "corpus OCR. Genere par scripts/generate_common_words.py — "
                 "ne pas editer a la main."),
        "words": common,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{n_docs} documents analyses")
    print(f"{len(common)} tokens au-dessus de {DF_THRESHOLD:.0%} -> {OUT_PATH}")
    print("Les 25 plus frequents :")
    for w, n in df.most_common(400):
        if w in set(common):
            print(f"  {w:20} {n:4d}  ({100 * n / n_docs:5.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
