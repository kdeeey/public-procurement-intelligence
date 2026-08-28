"""
Tests for extraction/company_name.py::clean_company_candidate() (Issue 7/8,
revision du 27/08/2026).

Ces tests remplacent les 13 tests de `_looks_implausible()` supprimes avec
la fonction elle-meme. Chaque cas d'origine est conserve — meme chaine,
meme document source — mais l'assertion change de nature : l'ancien filtre
repondait "rejeter oui/non", le nouveau repond "quel nom y a-t-il
la-dedans ?". Les cas ou un vrai nom etait noye dans du texte parasite
attendent desormais le nom ISOLE, la ou l'ancien filtre ne pouvait que
choisir entre laisser passer la phrase entiere et detruire l'entreprise.

S'y ajoutent les 6 cas rapportes comme non filtres le 27/08/2026, chacun
devenu un test de non-regression nomme.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from extraction.company_name import clean_company_candidate  # noqa: E402


# --------------------------------------------------------------------------- #
# rejet : la valeur ne contient aucun nom d'entreprise
# --------------------------------------------------------------------------- #

def test_clean_rejects_pure_field_label_phrase():
    # doc 3d46704d054d...: la phrase entiere devenait le "nom" faute de
    # mieux, aucune entreprise n'est meme presente dans cette valeur.
    assert clean_company_candidate("JUSTIFICATION DU CHOIX DE L ATTRIBUTAIRE") is None
    assert clean_company_candidate("CONCURRENT RETENU MONTANT DE L ACTE D ENGAG") is None


def test_clean_rejects_justification_sentence_without_name():
    # L'ancien test s'appuyait sur "aucun token de structure ET >= 50
    # caracteres". Ce seuil a ete retire (mesure : 11/11 faux positifs,
    # toutes des raisons sociales longues et reelles) — c'est la structure
    # de phrase qui rejette maintenant, plus la longueur.
    assert clean_company_candidate(
        "LE CONCURRENT A PRESENTE L OFFRE LA PLUS AVANTAGEUSE") is None


def test_clean_rejects_justification_boilerplate():
    # company_id 48, doc 37526643f298...: classee #1 par total_amount_ttc
    # dans company_stats_global (Issue 10) — un fragment de "l'offre
    # economiquement la plus avantageuse", pas une entreprise.
    assert clean_company_candidate("ECONOMIQUEMENT LA PLUS AVANTAGEUSE") is None
    assert clean_company_candidate("OFFRE LA PLUS AVANTAGEUSE") is None


def test_clean_rejects_neant_anywhere():
    # company_id 5 ("- Neant") et 91 ("du marche : Neant.") : "Neant" n'est
    # jamais en tete (position variable selon le champ vide dans le PV).
    assert clean_company_candidate("- NEANT") is None
    assert clean_company_candidate("DU MARCHE NEANT") is None


def test_clean_rejects_bare_date():
    # company_id 21, doc 1a2b0ab1...: une date lue comme concurrent_retenu.
    assert clean_company_candidate("31/12/2025") is None


def test_clean_rejects_names_with_no_letter():
    # company_id 77 ("-"), 108 ("01"), 134 ("1/2"), 149 ("\\ 60").
    assert clean_company_candidate("-") is None
    assert clean_company_candidate("01") is None
    assert clean_company_candidate("1/2") is None


def test_clean_rejects_short_fragment_without_legal_marker():
    # company_id 75 ("AN"), 87 ("CT"), 146 ("TF") : verifies contre le
    # document source — dans les 3 cas le texte juste apres "Concurrent
    # retenu :" est un fragment OCR ou une abreviation de colonne de
    # tableau ("TF" = Tranche Ferme), le vrai vainqueur apparaissant
    # plusieurs lignes plus bas.
    assert clean_company_candidate("AN") is None
    assert clean_company_candidate("ct") is None
    assert clean_company_candidate("TF:") is None
    assert clean_company_candidate("S") is None


def test_clean_rejects_a_buyer_rather_than_truncating_it():
    # Une collectivite est un ACHETEUR (Procurement.acheteur_public), jamais
    # une attributaire : rejet de la valeur ENTIERE, pas une coupe sur
    # "COMMUNE" qui laisserait survivre "DCHEIRA JIHADIA" comme entreprise.
    assert clean_company_candidate("COMMUNE DCHEIRA JIHADIA TEL/FAX 0528-83-62-11") is None


# --------------------------------------------------------------------------- #
# les 6 cas rapportes comme non filtres le 27/08/2026
# --------------------------------------------------------------------------- #

def test_clean_rejects_tirage_au_sort_without_parentheses():
    # La forme parenthesee "(PAR TIRAGE AU SORT)" etait bien traitee — par
    # normalize_company_name(), qui retire un groupe parenthese de tete —
    # mais rien ne couvrait la forme sans parentheses.
    assert clean_company_candidate("APRES TIRAGE AU SORT") is None


def test_clean_rejects_bare_column_headers():
    assert clean_company_candidate("CANDIDAT MONTANT") is None
    assert clean_company_candidate("SUR LA BASE DU PRIX DE REFERENCE ARRETE A") is None


def test_clean_strips_date_glued_to_a_real_name():
    # L'ancienne detection de date deleguait a date_variants(), dont le
    # regex est ANCRE en fin de chaine (`\\s*$`) : elle ne matchait que si la
    # valeur ETAIT une date, jamais si elle en CONTENAIT une. Ici la date
    # doit couper, et le nom survivre.
    assert clean_company_candidate(
        "TANSIFT CONTRACTOR DIRECT 09/12/2025 30/12/2025") == "TANSIFT CONTRACTOR DIRECT"
    assert clean_company_candidate(
        "NEWERACOM 27 JUILLET 2026 17 AOUT 2026") == "NEWERACOM"


def test_clean_extracts_real_name_from_justification_sentence():
    # L'ancien filtre LAISSAIT PASSER ces valeurs entieres parce que la
    # presence de "SOCIETE"/"STE" desactivait sa regle de longueur
    # (`if not has_structure:`). Le nettoyage en isole le nom au lieu de
    # choisir entre tout garder et tout rejeter.
    assert clean_company_candidate(
        "DONT L OFFRE EST LA PLUS AVANTAGEUSE - SOCIETE ALHAYAT TEC SARL "
        "POUR UN MONTANT") == "SOCIETE ALHAYAT TEC SARL"
    assert clean_company_candidate(
        "CONCARRENT RETENU MONTANT DE L ACTE D ENGOGEMENT STE ANKOURI "
        "GROUPE") == "STE ANKOURI GROUPE"


# --------------------------------------------------------------------------- #
# conservation : un vrai nom ne doit jamais etre perdu ni tronque
# --------------------------------------------------------------------------- #

def test_clean_keeps_short_names_without_legal_form():
    # De vrais noms courts sans forme juridique existent dans le corpus.
    assert clean_company_candidate("TECTRA") == "TECTRA"
    assert clean_company_candidate("ENTREPRISE OUENZAR") == "ENTREPRISE OUENZAR"
    assert clean_company_candidate("CENTRALE MAROCAINE D ASSURANCES") == \
        "CENTRALE MAROCAINE D ASSURANCES"


def test_clean_keeps_long_real_name_without_legal_form():
    # Regression directe de l'ancien seuil de longueur : ces trois noms
    # (43, 44 et 37 caracteres, aucun SARL/STE) figuraient parmi les 11 faux
    # positifs mesures du critere "aucune forme juridique ET >= 30
    # caracteres". Un ET interne ne doit pas non plus scinder le nom.
    assert clean_company_candidate(
        "LABORATOIRE GEOTECHNIQUE ET TRAVAUX PUBLICS") == \
        "LABORATOIRE GEOTECHNIQUE ET TRAVAUX PUBLICS"
    assert clean_company_candidate(
        "BUREAU MAROCAIN DES ETUDES ET EXPERTISES BMEE") == \
        "BUREAU MAROCAIN DES ETUDES ET EXPERTISES BMEE"
    assert clean_company_candidate(
        "SOLUTIONS PROFESSIONNELLES GENIE CIVIL") == \
        "SOLUTIONS PROFESSIONNELLES GENIE CIVIL"


def test_clean_keeps_long_name_with_legal_form():
    assert clean_company_candidate(
        "STE LABORATOIRE D ETUDES ET D ESSAIS TECHNIQUES ET INDUSTRIELS SARL") == \
        "STE LABORATOIRE D ETUDES ET D ESSAIS TECHNIQUES ET INDUSTRIELS SARL"


def test_clean_keeps_short_acronym_with_legal_marker():
    # company_id 11 ("SEN"), 33 ("TCN"), 30 ("BIGC") : de vraies entreprises
    # a sigle court. Le nettoyage travaille sur le texte BRUT, avant que
    # normalize_company_name() ne retire le marqueur — la forme juridique
    # est donc encore visible ici, contrairement a l'ancien filtre qui
    # devait se la faire repasser par un parametre `raw`.
    assert clean_company_candidate("STE SEN SARL") == "STE SEN SARL"
    assert clean_company_candidate("SOCIETE TCN") == "SOCIETE TCN"
    assert clean_company_candidate("BIGC SARL") == "BIGC SARL"


def test_clean_prefers_the_name_over_a_longer_address():
    # Sans la priorite donnee a la forme juridique, le span d'ADRESSE
    # (3 tokens CORE) l'emportait sur le vrai nom (2 tokens) — dans un PV
    # l'adresse suit toujours le nom et peut etre plus longue que lui.
    assert clean_company_candidate(
        "EQUIPERF SARL RESIDENCE DALIA AV YACOUB EL MANSOUR -I1-APP6 "
        "MARRAKECH") == "EQUIPERF SARL"


def test_clean_drops_a_table_row_identifier_before_a_colon():
    # doc b0433c6d2fee : le PV numerote ses soumissionnaires "EL 1 :",
    # "EL 2 :" ... "EL 9 :" — un identifiant de ligne de tableau, pas un
    # morceau de raison sociale. Signale par l'utilisateur : "EL6 INNOVATIVE
    # BUILDING SOLUTIONS est une entreprise correcte mais sans EL6".
    assert clean_company_candidate("EL6 : INNOVATIVE BUILDING SOLUTIONS") == \
        "INNOVATIVE BUILDING SOLUTIONS"
    assert clean_company_candidate("EL 6 : INNOVATIVE BUILDING SOLUTIONS") == \
        "INNOVATIVE BUILDING SOLUTIONS"


def test_clean_keeps_the_left_side_when_the_colon_is_trailing():
    # Le nom n'est pas toujours a droite du deux-points : sur les 44 valeurs
    # brutes du corpus qui en contiennent un, il est tantot a droite
    # ("Attributaire : Ste APERAL"), tantot a gauche quand le deux-points
    # termine la ligne. Une regle de position ("garder ce qui suit le
    # dernier :") casserait ces cas — c'est la selection du meilleur span
    # qui tranche, dans les deux sens.
    assert clean_company_candidate("IMS TECHNOLOGY TF :") == "IMS TECHNOLOGY"
    assert clean_company_candidate("ALL MTGI Offre :") == "ALL MTGI"
    assert clean_company_candidate("Attributaire : Sté APERAL") == "STE APERAL"
    assert clean_company_candidate("Concurrent 1 : LA SOCIETE : ZIN 2M TRAV SARL AU") == \
        "ZIN 2M TRAV SARL"


def test_clean_does_not_strip_a_short_leading_token_of_a_real_name():
    # Regression volontairement verrouillee : une regle generale "retirer le
    # fragment court en tete" a ete ECRITE ET MESUREE sur les 215 noms reels
    # avant d'etre REJETEE — elle corrigeait 3 cas et en cassait 9
    # (ALI OUBANE TRAVAUX -> OUBANE TRAVAUX, BCT QUALICONSULT... ->
    # QUALICONSULT..., MY GREEN NEGOCE -> GREEN NEGOCE, FIX IT SOLUTION ->
    # IT SOLUTION...). Un sigle de 2-3 lettres en tete est parfaitement
    # ordinaire dans une raison sociale ; rien ne le distingue d'un
    # identifiant de tableau SANS le deux-points qui le suit.
    for name in ["ALI OUBANE TRAVAUX", "BCT QUALICONSULT CONSTRUCTION MAROC",
                 "MY GREEN NEGOCE", "FIX IT SOLUTION", "KIT MED SLAOUI ET CIE",
                 "NET SERVICES INFORMATIQUE BUREAUTIQUE", "TP HORIZON",
                 "FY2 GROUP", "SUD BTP", "RK WORK"]:
        assert clean_company_candidate(name) == name, name


def test_clean_keeps_compound_cardinal_directions():
    # Regression : "EST" est classe comme le verbe etre — a juste titre dans
    # "l'offre EST la plus avantageuse". Mais dans "NORD EST ELECTRONIQUE"
    # c'est un point cardinal, et le breaker coupait le nom en deux
    # fragments d'un seul mot, tous deux trop courants pour survivre au
    # garde-fou de frequence : l'entreprise entiere disparaissait. Detecte
    # par le recoupement de volumetrie de build_features (192 en entree
    # contre 193 en base), pas par une relecture du code.
    assert clean_company_candidate("NORD EST ELECTRONIQUE") == "NORD-EST ELECTRONIQUE"
    assert clean_company_candidate("SUD OUEST TRAVAUX") == "SUD-OUEST TRAVAUX"
    # ... sans affaiblir le rejet des phrases ou "EST" est bien un verbe
    assert clean_company_candidate(
        "LE CONCURRENT A PRESENTE L OFFRE LA PLUS AVANTAGEUSE") is None
    assert clean_company_candidate(
        "DONT L OFFRE EST LA PLUS AVANTAGEUSE - SOCIETE ALHAYAT TEC SARL") == \
        "SOCIETE ALHAYAT TEC SARL"


def test_clean_prefers_the_longer_span_when_scores_tie():
    # Regression : doc 1513f22dbb14, la valeur brute "(OH TTC) COSTACOM".
    # "TTC" coupe, laissant deux spans d'un token CORE chacun et sans forme
    # juridique — ["OH"] et ["COSTACOM"]. A egalite, max() gardait le
    # PREMIER, donc "OH", qui tombait ensuite sous le plancher de 3 lettres :
    # COSTACOM, l'entreprise classee #1 anomalie du corpus, disparaissait
    # entierement de la table. Le nombre de lettres departage maintenant.
    assert clean_company_candidate("(OH TTC) COSTACOM") == "COSTACOM"


def test_clean_keeps_single_word_brand_names():
    # Regression mesuree : une regle "un seul mot survivant apres une
    # phrase = residu" rejetait 6 entreprises reelles pour ne gagner que 4
    # rejets de bruit. Elle a ete retiree — ces 6 cas la documentent.
    for raw, expected in [("SEDERAM - OFFRE DE BASE", "SEDERAM"),
                          ("SANS RESERVE CHRONOTECH", "CHRONOTECH"),
                          ("EN DHTTC BAUENER", "BAUENER"),
                          ("SOCHTRAP - OFFRE DE BASE", "SOCHTRAP"),
                          ("SETRAGEC - OFFRE DE BASE", "SETRAGEC"),
                          ("P 1 _ _ BOLIGAM - OFFRE DE BASE", "BOLIGAM")]:
        assert clean_company_candidate(raw) == expected, raw


def test_clean_is_idempotent_on_already_clean_names():
    # database/crud/companies.py rappelle le nettoyage apres
    # split_groupement() — il doit etre sans effet sur un nom deja propre.
    for name in ["TECTRA", "COSTACOM", "EL6 INNOVATIVE BUILDING SOLUTIONS",
                 "SOCIETE ALHAYAT TEC SARL", "BET SG CONCEPT"]:
        once = clean_company_candidate(name)
        assert once == name
        assert clean_company_candidate(once) == once
