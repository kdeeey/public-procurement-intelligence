"""
Verrous sur le registre de red flags marche (Phase 2, 28/08/2026).

Ce que ces tests protegent, dans l'ordre d'importance :

  1. Un red flag ne se declenche JAMAIS sur une donnee absente, imputee ou
     incoherente. Sans information exploitable il vaut None
     (NOT_EVALUABLE), jamais False ("verifie, rien a signaler"). Un False
     fabrique serait un faux negatif presente comme un controle passe.
  2. RF01 ne compte plus les defauts d'extraction. Un marche ATTRIBUE sans
     aucun soumissionnaire lisible n'est pas un marche a soumissionnaire
     unique — c'est un marche qu'on ne sait pas lire. Mesure avant
     correctif : 56 des 152 RF01 actifs (37 %) etaient dans ce cas.
  3. RF06 est derive et ne se compte jamais lui-meme.
  4. Le score est rescale sur les regles reellement evaluables, pondere par
     severite.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from ai.market_red_flags import (  # noqa: E402
    FLAGS_BY_ID, PRIMARY_FLAGS, REGISTRY, SEVERITY_WEIGHTS, Severity,
    describe, evaluate_market, summarize,
)

SEUILS = {
    "exclusion_rate_seuil": 0.5,
    "montant_ttc_seuil": 10_000_000.0,
    "procedures_rares": ["Concours Architectural"],
}


def marche(**kwargs) -> pd.Series:
    base = {
        "statut": "ATTRIBUE",
        "montant_ttc": 500_000.0,
        "has_competitor_data": 1, "nb_soumissionnaires": 4,
        "has_exclusion_data": 1, "exclusion_rate": 0.25,
        "date_ouverture_plis": pd.Timestamp("2025-03-12"), "annee": 2025,
        "has_winner": 1,
        "mode_passation": "Appel d'offres ouvert",
    }
    base.update(kwargs)
    return pd.Series(base)


# --------------------------------------------------------------------------- #
# Registre
# --------------------------------------------------------------------------- #

def test_registre_complet_et_rf04_absent():
    ids = [f.id for f in REGISTRY]
    assert ids == ["RF01", "RF02", "RF03", "RF05", "RF06"]
    assert "RF04" not in ids, (
        "RF04 exige une estimation, absente de 100 % des marches attribues "
        "(0/454) — ne pas l'implementer est une decision mesuree")
    assert PRIMARY_FLAGS == ("RF01", "RF02", "RF03", "RF05")


def test_chaque_flag_est_documente():
    for f in REGISTRY:
        assert f.name and f.description
        assert isinstance(f.severity, Severity)
        assert callable(f.evaluate)


# --------------------------------------------------------------------------- #
# UNKNOWN / INVALID != ZERO
# --------------------------------------------------------------------------- #

def test_donnee_absente_donne_non_evaluable_jamais_inactif():
    flags = evaluate_market(marche(has_competitor_data=0, nb_soumissionnaires=None,
                                   has_exclusion_data=0, exclusion_rate=None,
                                   montant_ttc=None), SEUILS)
    for fid in ("RF01", "RF02", "RF03"):
        assert flags[fid] is None, (
            f"{fid} doit etre non evaluable sans donnee, pas inactif — "
            "un False affirmerait un controle qui n'a pas eu lieu")


def test_donnee_presente_et_negative_donne_bien_inactif():
    """Quand l'information existe, un flag inactif est une vraie
    observation et doit se distinguer d'un inconnu."""
    flags = evaluate_market(marche(nb_soumissionnaires=8), SEUILS)
    assert flags["RF01"] is False
    assert flags["RF02"] is False
    assert flags["RF03"] is False


# --------------------------------------------------------------------------- #
# RF01 — le correctif de la Phase 2
# --------------------------------------------------------------------------- #

def test_rf01_se_declenche_sur_un_seul_soumissionnaire():
    assert evaluate_market(marche(nb_soumissionnaires=1), SEUILS)["RF01"] is True


def test_rf01_ne_compte_plus_un_defaut_d_extraction():
    """LE correctif de la Phase 2. Un marche ATTRIBUE avec 0 soumissionnaire
    lisible est marque INVALID par features/data_quality.py ; RF01 doit
    devenir non evaluable, pas se declencher.

    Avant : `nb <= 1` et 0 <= 1, donc 56 des 152 RF01 actifs (37 %)
    venaient d'un marche ou aucun nom n'avait pu etre lu — dont 35 ou des
    noms figuraient bien dans le document mais avaient tous ete rejetes
    par le filtre de plausibilite."""
    flags = evaluate_market(marche(nb_soumissionnaires=0), SEUILS)
    assert flags["RF01"] is None, (
        "0 soumissionnaire sur un marche attribue est un defaut de lecture, "
        "jamais une observation de faible concurrence")


def test_rf01_reste_evaluable_sur_un_infructueux_sans_soumissionnaire():
    """Sur un marche infructueux, 0 soumissionnaire n'a rien de
    contradictoire : l'information est lisible et le flag s'evalue."""
    flags = evaluate_market(marche(statut="INFRUCTUEUX", has_winner=0,
                                   nb_soumissionnaires=0), SEUILS)
    assert flags["RF01"] is True


# --------------------------------------------------------------------------- #
# RF02, RF03, RF05
# --------------------------------------------------------------------------- #

def test_rf02_utilise_le_seuil_mesure():
    assert evaluate_market(marche(exclusion_rate=0.6), SEUILS)["RF02"] is True
    assert evaluate_market(marche(exclusion_rate=0.4), SEUILS)["RF02"] is False


def test_rf02_non_evaluable_sur_taux_impossible():
    """Plus d'ecartes que de soumissionnaires : incoherence entre deux
    rubriques (18 marches mesures). Utiliser un taux de 300 % comme red
    flag transformerait un bug d'extraction en signal de risque."""
    assert evaluate_market(
        marche(nb_soumissionnaires=1, exclusion_rate=3.0), SEUILS)["RF02"] is None


def test_rf03_jamais_evalue_sur_un_montant_absent():
    assert evaluate_market(marche(montant_ttc=None), SEUILS)["RF03"] is None
    assert evaluate_market(marche(montant_ttc=50_000_000.0), SEUILS)["RF03"] is True


def test_rf05_repere_une_procedure_rare():
    assert evaluate_market(
        marche(mode_passation="Concours Architectural"), SEUILS)["RF05"] is True
    # Procedure courante : le flag doit etre INACTIF, pas non evaluable —
    # `mode_passation` est renseigne a 100 %, donc toujours lisible.
    assert evaluate_market(
        marche(mode_passation="Appel d'offres ouvert"), SEUILS)["RF05"] is False
    # Procedure absente : la, et seulement la, le flag n'est pas evaluable.
    assert evaluate_market(marche(mode_passation=None), SEUILS)["RF05"] is None


def test_rf05_severite_faible_car_rarete_n_est_pas_irregularite():
    """4 des 6 marches concernes sont des concours d'architecture, une
    categorie parfaitement reguliere. La severite doit refleter cette
    ambiguite."""
    assert FLAGS_BY_ID["RF05"].severity is Severity.FAIBLE


# --------------------------------------------------------------------------- #
# RF06 et agregation
# --------------------------------------------------------------------------- #

def test_rf06_ne_se_compte_pas_lui_meme():
    flags = evaluate_market(marche(nb_soumissionnaires=1, exclusion_rate=0.9), SEUILS)
    assert flags["RF01"] is True and flags["RF02"] is True
    assert flags["RF06"] is True
    assert summarize(flags)["red_flag_count"] == 2, (
        "RF06 est derive : l'inclure ferait passer 2 flags pour 3")


def test_rf06_non_evaluable_si_moins_de_deux_regles_applicables():
    flags = evaluate_market(marche(has_competitor_data=0, nb_soumissionnaires=None,
                                   has_exclusion_data=0, exclusion_rate=None,
                                   montant_ttc=None,
                                   mode_passation=None), SEUILS)
    assert flags["RF06"] is None


def test_score_rescale_sur_les_regles_evaluables_et_pondere():
    """Un marche dont la moitie des regles est inapplicable ne doit pas
    etre mecaniquement plafonne : le score se rescale sur ce qui a pu etre
    evalue, pondere par severite."""
    flags = evaluate_market(marche(nb_soumissionnaires=1, has_exclusion_data=0,
                                   exclusion_rate=None, montant_ttc=None), SEUILS)
    s = summarize(flags)
    # RF01 actif (poids 3) et RF05 inactif (poids 1) sont evaluables.
    assert s["red_flags_evaluable"] == 2
    assert s["red_flag_count"] == 1
    attendu = 100 * SEVERITY_WEIGHTS[Severity.ELEVEE] / (
        SEVERITY_WEIGHTS[Severity.ELEVEE] + SEVERITY_WEIGHTS[Severity.FAIBLE])
    assert s["red_flag_score"] == round(attendu, 1)


def test_score_none_si_aucune_regle_evaluable():
    flags = {fid: None for fid in PRIMARY_FLAGS}
    assert summarize(flags)["red_flag_score"] is None


# --------------------------------------------------------------------------- #
# Vocabulaire
# --------------------------------------------------------------------------- #

def test_aucun_libelle_n_affirme_une_irregularite():
    interdits = ("fraude", "corruption", "irregulier", "irrégulier",
                 "malversation", "detourne", "détourne")
    textes = [f.name.lower() + " " + f.description.lower() for f in REGISTRY]
    textes.append(describe(evaluate_market(marche(nb_soumissionnaires=1), SEUILS)).lower())
    for texte in textes:
        for mot in interdits:
            assert mot not in texte, f"vocabulaire interdit : {mot!r}"


def test_explication_signale_les_regles_non_evaluables():
    flags = evaluate_market(marche(nb_soumissionnaires=1, montant_ttc=None), SEUILS)
    texte = describe(flags)
    assert "Non evaluable" in texte
    assert "ni une preuve ni une presomption" in texte
