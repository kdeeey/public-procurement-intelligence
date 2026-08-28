"""
Verrous sur le feedback analyste (Phase 8, 28/08/2026).

Ce que ces tests protegent :

  1. Le feedback ne touche PAS au modele. Contrainte structurelle, verifiee
     par l'absence de dependance vers ai/ — pas seulement promise dans une
     docstring.
  2. Le taux de faux positifs porte sur les marches EXAMINES, jamais sur la
     population entiere, et vaut None tant qu'aucun avis n'existe.
  3. Un avis remplace le precedent sans dupliquer la ligne.
  4. Le fichier reste relisible : commentaires ignores, UTF-8, pas de saut
     de ligne dans un commentaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from dashboard.feedback import (  # noqa: E402
    FALSE_POSITIVE, RELEVANT, STATUSES, TO_REVIEW, UNREVIEWED, load_reviews,
    review_stats, upsert_review,
)


@pytest.fixture
def csv_temp(tmp_path) -> Path:
    return tmp_path / "analyst_reviews.csv"


def test_fichier_absent_donne_dictionnaire_vide():
    """Un corpus non encore annote est l'etat normal au depart, pas une
    erreur."""
    assert load_reviews(Path("/inexistant/nulle_part.csv")) == {}


def test_avis_enregistre_puis_relu(csv_temp):
    upsert_review(42, RELEVANT, analyst_comment="Vu le PV, un seul offreur",
                  reviewer="analyste1", path=csv_temp)
    reviews = load_reviews(csv_temp)
    assert set(reviews) == {42}
    r = reviews[42]
    assert r.review_status == RELEVANT
    assert r.analyst_comment == "Vu le PV, un seul offreur"
    assert r.review_timestamp   # pose par le module, jamais par l'appelant


def test_second_avis_remplace_le_premier_sans_doublon(csv_temp):
    upsert_review(7, RELEVANT, path=csv_temp)
    upsert_review(7, FALSE_POSITIVE, analyst_comment="verification faite",
                  path=csv_temp)
    reviews = load_reviews(csv_temp)
    assert len(reviews) == 1
    assert reviews[7].review_status == FALSE_POSITIVE


def test_statut_inconnu_refuse(csv_temp):
    with pytest.raises(ValueError):
        upsert_review(1, "FRAUDE_CONFIRMEE", path=csv_temp)


def test_commentaire_multiligne_ne_casse_pas_le_csv(csv_temp):
    upsert_review(3, TO_REVIEW, analyst_comment="ligne un\nligne deux\n\ttab",
                  path=csv_temp)
    assert load_reviews(csv_temp)[3].analyst_comment == "ligne un ligne deux tab"


def test_taux_faux_positifs_none_sans_avis(csv_temp):
    """Ne jamais afficher 0 % : cela se lirait comme un resultat alors que
    rien n'a ete evalue."""
    stats = review_stats([1, 2, 3], path=csv_temp)
    assert stats["taux_faux_positifs"] is None
    assert stats["non_examines"] == 3


def test_taux_faux_positifs_porte_sur_les_examines(csv_temp):
    """Diviser par la population entiere ferait BAISSER le taux a mesure
    que des marches restent non examines — ce qui se lirait comme une
    amelioration alors que rien n'aurait ete fait."""
    upsert_review(1, RELEVANT, path=csv_temp)
    upsert_review(2, FALSE_POSITIVE, path=csv_temp)
    upsert_review(3, TO_REVIEW, path=csv_temp)
    stats = review_stats([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], path=csv_temp)
    assert stats["examines"] == 2            # TO_REVIEW n'est pas un examen conclu
    assert stats["taux_faux_positifs"] == 0.5   # 1 sur 2, pas 1 sur 10
    assert stats["non_examines"] == 7
    assert stats["en_suspens"] == 1


def test_unreviewed_n_est_pas_un_statut_enregistrable():
    """UNREVIEWED est l'absence d'avis, pas un avis : il ne doit pas
    pouvoir etre ecrit dans le fichier."""
    assert UNREVIEWED not in STATUSES


def test_le_feedback_ne_depend_pas_du_modele():
    """Contrainte structurelle, verifiee sur le source plutot que promise.

    Si ce module importait ai/, une boucle de retour deviendrait possible
    par inadvertance : le modele apprendrait les preferences d'un
    annotateur, et ces avis cesseraient d'etre un jeu d'evaluation
    independant du modele qu'ils evaluent.
    """
    source = (REPO / "dashboard/feedback.py").read_text(encoding="utf-8")
    for interdit in ("from ai.", "import ai", "sklearn", "joblib"):
        assert interdit not in source, (
            f"dashboard/feedback.py ne doit rien importer du modele : {interdit!r}")
