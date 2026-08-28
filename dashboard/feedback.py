"""
Feedback analyste (Phase 8, 28/08/2026) — collecte, sans boucle de retour.

CE QUE CE MODULE FAIT, ET SURTOUT CE QU'IL NE FAIT PAS
--------------------------------------------------------
Il enregistre le jugement d'un analyste sur un marche signale. Il ne
modifie NI le modele, NI les seuils, NI les red flags. Aucune fonction ici
n'est appelee par ai/ ; la dependance ne va que dans un sens
(dashboard -> fichier). C'est une contrainte de conception, pas une etape
non encore faite :

  * reentrainer sur quelques dizaines d'avis humains produirait un modele
    qui apprend les preferences d'un annotateur, pas des caracteristiques
    de marches ;
  * et cela detruirait la seule chose que ces avis pourront servir plus
    tard — un jeu d'evaluation independant du modele qu'il evalue.

Ce que ces avis permettront quand ils seront assez nombreux : mesurer un
taux de faux positifs, reperer les red flags qui ne servent a rien,
preparer une version supervisee. Rien de tout cela n'est fait ici.

POURQUOI UN CSV VERSIONNE ET NON UNE TABLE POSTGRESQL
-------------------------------------------------------
Precedent explicite du projet, `database/aliases.py` : une annotation
humaine ne doit pas etre effacee par le prochain TRUNCATE + reload — et il
y en a eu quatre dans la seule journee du 27/08/2026, plus un autre le
28/08. Un fichier versionne survit aux rechargements, une colonne non.

Le fichier est ecrit en UTF-8 explicite : ce projet a deja vu un
`.gitignore` corrompu par un `>>` PowerShell en UTF-16.

    from dashboard.feedback import load_reviews, upsert_review, review_stats
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REVIEWS_PATH = REPO / "data/reference/analyst_reviews.csv"

UNREVIEWED = "UNREVIEWED"
RELEVANT = "RELEVANT"
FALSE_POSITIVE = "FALSE_POSITIVE"
TO_REVIEW = "TO_REVIEW"

STATUSES = (RELEVANT, FALSE_POSITIVE, TO_REVIEW)

STATUS_LABELS = {
    RELEVANT: "Pertinent — mérite l'examen",
    FALSE_POSITIVE: "Faux positif — rien à signaler",
    TO_REVIEW: "À examiner — avis en suspens",
    UNREVIEWED: "Non examiné",
}

FIELDNAMES = ["award_id", "review_status", "analyst_label", "analyst_comment",
              "reviewer", "review_timestamp"]


@dataclass(frozen=True)
class Review:
    award_id: int
    review_status: str
    analyst_label: str
    analyst_comment: str
    reviewer: str
    review_timestamp: str


def load_reviews(path: Path | None = None) -> dict[int, Review]:
    """{award_id: Review}. Fichier absent -> dictionnaire vide, jamais une
    erreur : un corpus non encore annote est l'etat normal au depart."""
    target = path or REVIEWS_PATH
    if not target.exists():
        return {}
    out: dict[int, Review] = {}
    with target.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(l for l in fh if not l.startswith("#")):
            try:
                award_id = int(row["award_id"])
            except (KeyError, TypeError, ValueError):
                continue
            out[award_id] = Review(
                award_id=award_id,
                review_status=(row.get("review_status") or UNREVIEWED).strip(),
                analyst_label=(row.get("analyst_label") or "").strip(),
                analyst_comment=(row.get("analyst_comment") or "").strip(),
                reviewer=(row.get("reviewer") or "").strip(),
                review_timestamp=(row.get("review_timestamp") or "").strip(),
            )
    return out


def upsert_review(award_id: int, review_status: str, analyst_comment: str = "",
                  analyst_label: str = "", reviewer: str = "",
                  path: Path | None = None) -> Review:
    """Ajoute ou remplace l'avis sur un marche.

    Le fichier entier est reecrit : quelques centaines de lignes au plus,
    et une reecriture complete evite les etats partiels d'un append
    interrompu. L'horodatage est pose ici, jamais fourni par l'appelant,
    pour qu'il reflete le moment reel de la saisie.
    """
    if review_status not in STATUSES:
        raise ValueError(
            f"statut inconnu : {review_status!r} (attendus : {', '.join(STATUSES)})")

    target = path or REVIEWS_PATH
    reviews = load_reviews(target)
    review = Review(
        award_id=int(award_id), review_status=review_status,
        analyst_label=analyst_label.strip(),
        # Les sauts de ligne casseraient le CSV a la relecture.
        analyst_comment=" ".join(analyst_comment.split()),
        reviewer=reviewer.strip(),
        review_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    reviews[int(award_id)] = review

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# Avis d'analystes sur les marches signales (Phase 8).\n")
        fh.write("# Annotation HUMAINE : ce fichier ne doit jamais etre regenere\n")
        fh.write("# par le pipeline, et il survit aux rechargements de la base.\n")
        fh.write("# Il n'alimente AUCUN reentrainement — voir dashboard/feedback.py.\n")
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in sorted(reviews.values(), key=lambda x: x.award_id):
            writer.writerow({
                "award_id": r.award_id, "review_status": r.review_status,
                "analyst_label": r.analyst_label,
                "analyst_comment": r.analyst_comment,
                "reviewer": r.reviewer, "review_timestamp": r.review_timestamp,
            })
    return review


def review_stats(award_ids, path: Path | None = None) -> dict:
    """Compte des avis sur une population donnee.

    `taux_faux_positifs` porte sur les seuls marches EXAMINES, pas sur la
    population entiere : diviser par le total ferait baisser le taux a
    mesure que des marches restent non examines, ce qui se lirait comme une
    amelioration alors que rien n'aurait ete evalue. None tant qu'aucun
    avis n'existe.
    """
    reviews = load_reviews(path)
    ids = [int(a) for a in award_ids]
    presents = [reviews[a] for a in ids if a in reviews]
    par_statut = {s: sum(1 for r in presents if r.review_status == s) for s in STATUSES}
    n_examines = par_statut[RELEVANT] + par_statut[FALSE_POSITIVE]
    return {
        "total": len(ids),
        "examines": n_examines,
        "non_examines": len(ids) - len(presents),
        "en_suspens": par_statut[TO_REVIEW],
        **{s.lower(): par_statut[s] for s in STATUSES},
        "taux_faux_positifs": (par_statut[FALSE_POSITIVE] / n_examines
                               if n_examines else None),
    }
