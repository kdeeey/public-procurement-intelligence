"""
Verrou de non-regression sur la regle UNKNOWN != ZERO (refonte du 28/08/2026).

Le defaut corrige ici traversait toute la chaine : `_bulleted_names()`
renvoyait une liste vide aussi bien quand la rubrique etait ABSENTE du
document que quand elle etait PRESENTE et ne nommait personne. En aval,
`number_of_bidders` lisait donc "0 soumissionnaire" pour 107 des 454 Award
(23,6 % du corpus) dont le document ne disait simplement rien — et
`single_bidder_rate` en faisait des marches a soumissionnaire unique.

Un trou d'extraction devenait ainsi un signal de risque. Ces tests
empechent la confusion de revenir, a l'endroit exact ou elle naissait.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from extraction.extractor import extract_document  # noqa: E402
from extraction.fields import extract_concurrent_retenu_brut, extract_concurrents  # noqa: E402
from extraction.patterns import NEANT_RE  # noqa: E402

SANS_RUBRIQUE = """
Royaume du Maroc
Appel d'offres ouvert N° 12/2026
Objet : travaux de voirie
Date d'ouverture des plis : 12/03/2026
Concurrent retenu : SOCIETE ALPHA SARL
"""

RUBRIQUE_VIDE = """
Appel d'offres ouvert N° 13/2026
Liste des concurrents :
Neant

Concurrent retenu : SOCIETE BETA SARL
"""

RUBRIQUE_REMPLIE = """
Appel d'offres ouvert N° 14/2026
Liste des concurrents :
- SOCIETE ALPHA SARL
- SOCIETE BETA SARL
- SOCIETE GAMMA SARL

Concurrent retenu : SOCIETE ALPHA SARL
"""


def test_rubrique_absente_donne_none_jamais_liste_vide():
    """Le coeur du correctif : pas de rubrique -> on ne sait pas."""
    result = extract_concurrents(SANS_RUBRIQUE)
    assert result.liste_concurrents is None
    assert result.concurrents_ecartes is None
    assert result.number_of_bidders is None, (
        "un document sans rubrique concurrents ne doit jamais compter "
        "0 soumissionnaire : c'est un inconnu, pas une observation")


def test_rubrique_presente_mais_neant_donne_zero_observe():
    """L'autre moitie de la distinction : la rubrique existe et ne nomme
    personne. La, 0 est une vraie mesure et doit etre conservee comme telle."""
    result = extract_concurrents(RUBRIQUE_VIDE)
    assert result.liste_concurrents == []
    assert result.number_of_bidders == 0


def test_rubrique_remplie_compte_les_noms():
    result = extract_concurrents(RUBRIQUE_REMPLIE)
    assert result.number_of_bidders == 3


def test_award_serialise_conserve_les_trois_etats():
    """La distinction doit survivre a extract_document(), qui produit le
    JSON que database/crud/awards.py recharge ensuite en base."""
    inconnu = extract_document("doc_inconnu", SANS_RUBRIQUE)[0]
    zero = extract_document("doc_zero", RUBRIQUE_VIDE)[0]
    assert inconnu.liste_concurrents is None
    assert zero.liste_concurrents == []


def test_neant_tolere_la_puce_de_mise_en_page():
    """'- Neant' est une valeur absente, pas un nom de gagnant.

    Mesure au 28/08/2026 : 2 marches (054e0f7e1874, 19494f11e7ca) etaient
    classes ATTRIBUE parce que le motif ancre echouait sur la puce de tete,
    donc le bloc passait pour une valeur presente.
    """
    for forme in ("Neant", "Néant", "- Néant", "• neant", "Néant.", "- Neant :"):
        assert NEANT_RE.match(forme), f"{forme!r} doit etre reconnu comme absent"

    texte = "Concurrent retenu :\n- Néant\n"
    assert extract_concurrent_retenu_brut(texte) is None


def test_neant_ne_mange_pas_un_vrai_nom():
    """Garde-fou dans l'autre sens : la tolerance ajoutee ne doit pas
    avaler une raison sociale qui commencerait par les memes lettres."""
    for forme in ("NEANTIS SARL", "- SOCIETE NEANT PLUS", "Neant Industries"):
        assert not NEANT_RE.match(forme), f"{forme!r} est un nom, pas une absence"
