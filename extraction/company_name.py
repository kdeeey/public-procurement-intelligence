"""
Isolation du nom d'entreprise dans la valeur brute de `concurrent_retenu`
(Issue 7 / Issue 8, revision du 27/08/2026).

Applique EN AMONT, dans extraction/fields.py::extract_concurrent_retenu() :
c'est la valeur extraite elle-meme qui est corrigee, pas seulement la
Company derivee. Le texte brut d'origine reste conserve dans
`Award.concurrent_retenu_brut` pour la tracabilite.

POURQUOI CE MODULE REMPLACE `_looks_implausible()`
--------------------------------------------------
L'ancien filtre etait une liste de mots-clefs de REJET, agrandie a chaque
session (`NOISE_LEADING_WORDS`, `NOISE_WORDS_ANYWHERE`,
`NOISE_WORDS_WHEN_NO_STRUCTURE`, seuil de longueur...). Audit exhaustif du
27/08/2026 sur les 200 Company reellement en base : **107/200 (53,5%)
affectees** — 34 bruit pur + 73 noms reels noyes dans du texte parasite,
la ou la documentation annoncait ~15%. Deux causes de fond, mesurees
(voir bigdata/README.md pour le detail) :

  1. Un filtre qui ne sait que REJETER ne peut rien faire des 73 cas
     contamines : les rejeter detruit 73 entreprises reelles, les garder
     casse la deduplication ("TANSIFT CONTRACTOR DIRECT 09/12/2025
     30/12/2025" et "TANSIFT CONTRACTOR DIRECTR-CE" sont la meme
     entreprise en deux lignes). Il faut ROGNER, pas seulement rejeter.
  2. La longueur ne discrimine rien. Sur les 11 faux positifs du critere
     "aucune forme juridique ET >= 30 caracteres", 11/11 sont de vrais
     noms ("LABORATOIRE GEOTECHNIQUE ET TRAVAUX PUBLICS", "CENTRALE
     MAROCAINE D ASSURANCES", "BUREAU MAROCAIN DES ETUDES ET EXPERTISES
     BMEE") : la raison sociale marocaine est frequemment une longue
     phrase descriptive sans SARL. C'est pour ca que l'ancien seuil avait
     du etre relache a 50 puis neutralise par `has_structure` — et c'est
     ce contournement qui laissait passer les phrases de 79 caracteres
     contenant "SOCIETE".

LA CAUSE AMONT
--------------
Le defaut nait dans `extraction/fields.py::_collect_value_block()` : il
ramasse jusqu'a 6 lignes / 400 caracteres apres le label et ne s'arrete
qu'a un montant plausible, avalant l'en-tete de colonne, la phrase de
justification et l'adresse qui suivent le nom. `_collect_value_block()`
n'est PAS modifie — sa fenetre sert aussi aux extracteurs de montant et de
statut, la deplacer invaliderait les taux d'Issue 7 mesures contre
`ground_truth.json`. C'est sa SORTIE qui est nettoyee ici, pour le seul
champ `concurrent_retenu`, avant qu'elle ne soit persistee.

`extract_statut()` continue de recevoir la valeur BRUTE, pas la valeur
nettoyee : le statut se lit sur la presence d'un texte apres le label, et
lui passer None la ou le nettoyage n'a trouve aucun nom ferait basculer a
tort des marches ATTRIBUE en INFRUCTUEUX. Verifie contre
`ground_truth.json` (scripts/validate_extraction.py).

LA METHODE : SPAN DE NOM, PAS LISTE DE MOTS INTERDITS
------------------------------------------------------
Chaque token est classe en trois categories, et une seule regle generale
en decoule :

  * BREAKER  — libelle de champ/colonne, verbe conjugue administratif,
    preposition de phrase, mot-nombre ecrit en toutes lettres. Un breaker
    ne fait jamais partie d'une raison sociale ; il coupe.
  * NEUTRE   — articles et conjonctions (DE, D, LA, ET, EL...), chiffres
    isoles, ponctuation. Ne coupe pas (sinon "LABORATOIRE GEOTECHNIQUE ET
    TRAVAUX PUBLICS" serait scinde en deux) mais ne compte pas comme nom.
  * CORE     — tout le reste, plus les formes juridiques.

Le nom retenu est le plus long span contigu sans breaker (a egalite, celui
qui porte une forme juridique, puis le premier). Si aucun span ne contient
de token CORE, il n'y a pas de nom dans la valeur -> rejet.

Cette regle unique remplace les quatre listes de rejet precedentes ET
recupere les cas contamines, ce que l'ancienne approche ne pouvait pas
faire par construction.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- #
# vocabulaires
# --------------------------------------------------------------------------- #

# Formes juridiques / marqueurs de structure. Comptent comme CORE (elles font
# partie du nom imprime) et servent a departager deux spans de meme longueur.
# "AU" en est volontairement ABSENT bien qu'il apparaisse dans "SARL AU" :
# c'est aussi l'article contracte francais, et le classer comme forme
# juridique faisait survivre "APRES TIRAGE AU SORT" sous la forme du seul
# token "AU" (mesure). Il est traite en NEUTRAL_TOKENS a la place — un
# "SARL AU" garde de toute facon son SARL.
LEGAL_TOKENS = {
    "SARL", "STE", "SOCIETE", "SOCIETES", "SOC", "SA", "SNC", "SAS",
    "GROUPEMENT", "GROUPE", "GROUP", "GRP", "ETS", "BET", "ENTREPRISE",
}

# Libelles de champ et de colonne de tableau lus dans les PV. Inclut les
# variantes OCR reellement observees dans le corpus (CONCARRENT/CONEURRENT/
# ONCURRENT/CENCURRENTS/RCTENU/REFENU/MORITANT/ENGOGEMENT/COMMISSIO/
# INFERCTAUX/LOTN/POURLELOT) — ce ne sont pas des mots nouveaux, ce sont les
# memes mots abimes par Tesseract.
FIELD_LABELS = {
    "MONTANT", "MONTANTS", "MORITANT", "TMONTANT",
    "CONCURRENT", "CONCURRENTS", "CONCARRENT", "CONEURRENT", "ONCURRENT",
    "CENCURRENTS", "SOUMISSIONNAIRE", "SOUMISSIONNAIRES",
    "CANDIDAT", "CANDIDATS", "ATTRIBUTAIRE", "PRESTATAIRE",
    "RETENU", "RETENUE", "RETENUS", "RCTENU", "REFENU",
    "CLASSEMENT", "OBSERVATIONS", "OBSERVATION", "PAGE",
    "JUSTIFICATION", "JUSTIFICATIONS", "CHOIX", "MOTIF", "MOTIFS",
    "CRITERE", "CRITERES",
    "COMMISSION", "COMMISSIO", "PLIS", "OUVERTURE",
    "ENGAGEMENT", "ENGAGEMENTS", "ENGOGEMENT", "ACTE", "ACTES", "PACTE",
    "LOT", "LOTS", "LOTN", "POURLELOT",
    "OFFRE", "OFFRES", "TTC", "HT", "DH", "DHS", "DHTTC",
    "DIRHAM", "DIRHAMS", "CENTIME", "CENTIMES", "MAD",
    "TF", "TC", "NOTE", "GLOBALE", "RESERVE", "RESERVES",
    "INFRUCTUEUX", "INFERCTAUX", "DEFINITIF", "DEFINITIFS", "PROVISOIRE",
    "PRIX", "REFERENCE", "BASE", "CREDITS", "BUDGETAIRES", "BUDGET",
    "APPEL", "TIRAGE", "SORT", "EXAMEN", "MARCHE", "MARCHES",
    "MOINS", "DISANT", "DISANTS", "DISANTE", "DISANTES",
    "AVANTAGEUSE", "AVANTAGEUX", "ECONOMIQUEMENT", "NEANT",
    "TEL", "FAX", "BD", "BVD", "AV", "AVENUE", "RESIDENCE", "DOUAR", "APP",
    "ARCHITECTE", "ARCHITECTES", "MAITRE", "OUVRAGE",
    # Vocabulaire du GABARIT REGLEMENTAIRE imprime dans les PV (renvois au
    # decret des marches publics, mentions de dossier administratif, delais).
    # Ajoute apres le rechargement du 27/08/2026 : le rognage cree une
    # nouvelle famille de residus que l'ancien filtre rejetait en bloc sur
    # sa regle de longueur ("FIXES DANS LE REGLEMENT DE LA CONSULTATION",
    # "PIECES PRODUITES AU TITRE DU COMPLEMENT DU DOSSIER ADMINISTRATIF...").
    # Liste BORNEE, pas une liste ouverte : c'est le lexique fini d'un
    # formulaire type, pas une enumeration de cas particuliers.
    "ARTICLE", "ARTICLES", "DECRET", "DECRETS", "REGLEMENT", "CONSULTATION",
    "DOSSIER", "DOSSIERS", "ADMINISTRATIF", "ADMINISTRATIFS", "ADDITIFS",
    "PIECE", "PIECES", "CONFORMEMENT", "DISPOSITION", "DISPOSITIONS",
    "ALINEA", "DELAI", "DELAIS", "EXECUTION", "TAUX", "HONORAIRE",
    "HONORAIRES", "ATTRIBUTION", "PROSPECTUS", "DOCUMENT", "DOCUMENTS",
    "PREVU", "PREVUS", "PREVUE", "PREVUES", "FIXE", "FIXES", "FIXEE",
    "FIXEES", "PRODUITES", "COMPLEMENT", "CONDITION", "CONDITIONS",
    "SIGNE", "SIGNEE", "RECONDUCTIBLE", "ANNEE", "ANNEES", "AFFERENT",
    "AFFERENTE", "TITRE", "DECISION", "RECTIFICATION", "VERIFICATION",
    "AVANTAGEUSES", "RELATIF", "RELATIVE", "TAXES", "COMPRISES",
}

# Verbes conjugues et participes du francais administratif. Une raison sociale
# n'en contient jamais ; leur presence signe une phrase.
VERB_TOKENS = {
    "EST", "SONT", "ETAIT", "ETAIENT", "SERA", "AYANT", "AYANTS",
    "OBTENU", "OBTENUE", "PRESENTE", "PRESENTEE", "PRESENTES",
    "ARRETE", "ARRETEE", "DECLARE", "DECLAREE", "DECLARATION",
    "JUGE", "JUGEE", "DEPASSE", "ALLOUES", "ALLOUEES",
    "RECTIFIES", "RECTIFIEES", "CONFORMES", "CONFORME",
    "ADMISSIBLE", "ADMISSIBLES", "ADMIS", "ECARTE", "ECARTES",
    "ATTRIBUE", "ATTRIBUEE", "SISE", "SIS", "EXPLOITATION",
    "ELEVEE", "ELEVE", "ELEVEES", "BASSE", "FAIBLE",
}

# Prepositions et conjonctions de subordination : elles introduisent une
# proposition, jamais un nom propre. Distinctes des articles (NEUTRAL_TOKENS).
SENTENCE_PREPS = {
    "SUR", "LORS", "APRES", "AVANT", "DONT", "AVEC", "POUR", "SANS",
    "PAR", "ENTRE", "SOUS", "SELON", "QUE", "QUI", "EN", "AINSI",
}

# Nombres ecrits en toutes lettres — sinon "AVEC UN MONTANT DE NEUF MILLIONS
# DEUX CENT SOIXANTE-DEUX MILLE NEUF CENT QUATRE DIRHAMS" forme le plus long
# span de la chaine et l'emporterait sur le vrai nom.
NUMBER_WORDS = {
    "ZERO", "UN", "UNE", "DEUX", "TROIS", "QUATRE", "CINQ", "SIX", "SEPT",
    "HUIT", "NEUF", "DIX", "ONZE", "DOUZE", "TREIZE", "QUATORZE", "QUINZE",
    "SEIZE", "VINGT", "VINGTS", "TRENTE", "QUARANTE", "CINQUANTE",
    "SOIXANTE", "CENT", "CENTS", "MILLE", "MILLION", "MILLIONS",
    "MILLIARD", "MILLIARDS", "ET-UN", "QUATRE-VINGTS", "TRENTE-SIX",
    "SOIXANTE-DEUX", "QUATRE-VINGT",
}

# Articles, conjonctions de coordination et particules : neutres. Ne coupent
# pas un span (un vrai nom en contient : "LABORATOIRE D EXPERTISES D ETUDES
# ET D ESSAIS L3E") mais ne suffisent pas a en constituer un.
NEUTRAL_TOKENS = {
    "LA", "LE", "LES", "L", "DE", "DES", "DU", "D", "ET", "A", "AU", "AUX",
    "EL", "AL", "N", "NO", "S", "PLUS",
    # Mots-outils grammaticaux : ni un nom, ni un marqueur de champ. Neutres
    # (et non breakers) pour ne pas scinder une raison sociale qui en
    # contiendrait un. Une valeur qui n'est faite QUE de ceux-la n'a aucun
    # token CORE et se rejette d'elle-meme ("QU ELLE NE SOIT SIGNEE").
    "QU", "QUE", "ELLE", "IL", "NE", "PAS", "SOIT", "SONT", "TOUT", "TOUS",
    "TOUTE", "TOUTES", "CE", "CETTE", "CES", "SON", "SA", "SES", "LEUR",
    "LEURS", "MIEUX", "AINSI", "MEME", "MEMES",
}

# Collectivites et administrations : ce sont des ACHETEURS
# (Procurement.acheteur_public), jamais des entreprises attributaires. Leur
# presence signe une capture de la mauvaise ligne du PV ("COMMUNE DCHEIRA
# JIHADIA TEL/FAX 0528-83-62-11"). Rejet de la VALEUR ENTIERE, pas un
# simple breaker : couper sur "COMMUNE" laisserait survivre le nom de la
# commune ("DCHEIRA JIHADIA") comme si c'etait une entreprise.
ADMIN_ENTITY_TOKENS = {
    "COMMUNE", "COMMUNES", "PREFECTURE", "PROVINCE", "MINISTERE",
    "REGION", "CONSEIL", "WILAYA", "MUNICIPALITE",
}

BREAKERS = FIELD_LABELS | VERB_TOKENS | SENTENCE_PREPS | NUMBER_WORDS

MIN_REAL_LETTERS_WITHOUT_LEGAL = 3

# Mots presents dans au moins 50% des 388 PV du corpus, generes par
# scripts/generate_common_words.py (voir sa docstring). Servent a UN SEUL
# usage : rejeter un nom reduit a un unique mot generique du gabarit
# ("TRAVAUX" 94,8%, "TECHNIQUES" 73,2%, "PUBLICS" 64,7%) sans toucher aux
# vraies marques d'un seul mot (SEDERAM, CHRONOTECH, BOLIGAM : 0,3% chacune).
#
# Le seuil de 2% est MESURE sur les deux populations, pas choisi a priori.
# Frequence documentaire des 48 vrais noms d'entreprise d'un seul mot du
# corpus (TECTRA, COSTACOM, NOVEC, SEDERAM, CHRONOTECH, BOLIGAM, SEN,
# SGIAT...) : MAXIMUM 1,03% (NOVEC, SGIAT, AEBDM, SEN a 4 documents sur
# 388). Frequence des residus generiques a rejeter : MAROCAINE 3,35%,
# GLOBAL 4,38%, RAPPORT 5,93%, PUBLIC 10,82%, TECHNIQUE 21,65%. Les deux
# populations ne se recouvrent pas ; 2% tombe entre les deux avec une
# marge d'un facteur ~2 de chaque cote.
#
# La regle ne s'applique QU'AUX spans reduits a un seul token CORE :
# "MAROC" (74,0%) seul est rejete, mais "MAROC BUREAU" et "MAROC INGENOV"
# passent, parce que la combinaison, elle, est distinctive. Elle ne
# s'applique pas non plus quand une forme juridique accompagne le mot.
#
# Restent non rattrapables par cette regle, et assumes : les fragments OCR
# rares, indiscernables d'un nom rare par la frequence seule (TFC 0,26%,
# DIRNAMS 0,77%, MONFANT 0,26%, TIC 1,55%).
COMMON_WORD_DF_THRESHOLD = 0.02
_COMMON_WORDS_PATH = Path(__file__).with_name("corpus_common_words.json")
try:
    CORPUS_COMMON_WORDS: frozenset[str] = frozenset(
        json.loads(_COMMON_WORDS_PATH.read_text(encoding="utf-8"))["words"])
except (OSError, KeyError, ValueError):  # fichier non genere : regle inactive
    CORPUS_COMMON_WORDS = frozenset()

_DATE_NUM_RE = re.compile(r"\b\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{2,4}\b")
_MONTHS = ("JANVIER|FEVRIER|MARS|AVRIL|MAI|JUIN|JUILLET|AOUT|SEPTEMBRE"
           "|OCTOBRE|NOVEMBRE|DECEMBRE")
_DATE_TXT_RE = re.compile(r"\b\d{1,2}\s+(?:" + _MONTHS + r")\s+\d{4}\b")
# L'apostrophe est un SEPARATEUR, pas un caractere de token — meme
# convention que normalize_company_name(), qui remplace deja toute
# ponctuation par une espace. Sans ca "L'ATTRIBUTAIRE" formait un seul
# token, absent de FIELD_LABELS, donc classe CORE : la phrase
# "Justification du choix de l'attributaire" survivait au nettoyage sous la
# forme "L ATTRIBUTAIRE" (mesure par tests/test_statistics.py).
_APOSTROPHE_RE = re.compile(r"['‘’ʼ]")
_TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9&-]*")
# Points cardinaux composes — voir clean_company_candidate() pour la mesure
# qui a impose cette soudure.
_CARDINAL_RE = re.compile(r"(NORD|SUD)\s+(EST|OUEST)")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _classify(token: str) -> str:
    """BREAKER | NEUTRAL | CORE — voir la docstring du module."""
    bare = token.strip("-&")
    if not bare:
        return "NEUTRAL"
    if bare in BREAKERS:
        return "BREAKER"
    # Compose entierement de breakers ("MOINS-DISANT") : c'est le meme
    # libelle, l'OCR a seulement colle les deux mots par un tiret.
    parts = [p for p in bare.split("-") if p]
    if len(parts) > 1 and all(p in BREAKERS for p in parts):
        return "BREAKER"
    # Libelle tronque par l'OCR ou par la fin du bloc collecte
    # ("...D ACTE D ENGAG" pour ENGAGEMENT, "COMMISSIO" pour COMMISSION).
    # Regle generale plutot qu'une entree par troncature observee, mais
    # bornee des deux cotes pour ne pas mordre sur de vrais noms : au moins
    # 5 caracteres (sinon "TECH" tuerait "CLEAN TECH" via TECHNIQUE) et
    # seulement contre des libelles d'au moins 8 caracteres.
    if len(bare) >= 5 and any(lab.startswith(bare) and len(lab) >= 8
                              for lab in BREAKERS):
        return "BREAKER"
    if bare in LEGAL_TOKENS:
        return "CORE"
    if bare in NEUTRAL_TOKENS:
        return "NEUTRAL"
    if not re.search(r"[A-Z]", bare):          # purement numerique
        return "NEUTRAL"
    if len(re.findall(r"[A-Z]", bare)) == 1:   # lettre isolee ("E", "P")
        return "NEUTRAL"
    return "CORE"


def clean_company_candidate(raw: str) -> str | None:
    """Texte brut de `concurrent_retenu` -> le nom d'entreprise seul, ou
    None si la valeur n'en contient aucun.

    Rogne d'abord (dates, blobs numeriques, texte de phrase autour du nom),
    rejette ensuite (aucun token CORE ne subsiste).
    """
    if not raw:
        return None

    s = _APOSTROPHE_RE.sub(" ", _fold(raw.upper()))

    # "NORD EST", "SUD OUEST"... : points cardinaux composes. Sans cette
    # soudure, le "EST" est classe comme le VERBE etre (il l'est bien dans
    # "l'offre EST la plus avantageuse") et coupe le nom en deux fragments
    # d'un seul mot, chacun trop courant pour survivre au garde-fou de
    # frequence. Mesure : "NORD EST ELECTRONIQUE" — une entreprise reelle
    # nommee dans son PV — etait entierement rejetee pour cette raison.
    s = _CARDINAL_RE.sub(lambda m: f"{m.group(1)}-{m.group(2)}", s)

    # Le deux-points est un SEPARATEUR, pas un caractere de nom : le PV est
    # ecrit en "Libelle : valeur", et ce libelle survit regulierement dans le
    # bloc collecte. Trouve sur EL6 (doc b0433c6d2fee), signale comme "une
    # entreprise correcte mais sans EL6" : le document numerote ses
    # soumissionnaires "EL 1 :", "EL 2 :" ... "EL 9 :" — un identifiant de
    # ligne de tableau, pas un morceau de raison sociale.
    #
    # Couper ici plutot que "garder ce qui suit le dernier deux-points" :
    # sur les 44 valeurs brutes du corpus qui contiennent un ":", le nom est
    # tantot A DROITE ("Attributaire : Ste APERAL", "sans reserve : LABOTEST
    # et LPEE") tantot A GAUCHE quand le deux-points est final ("IMS
    # TECHNOLOGY TF :", "ALL MTGI Offre :"). La selection du meilleur span
    # tranche correctement dans les deux sens, une regle de position non.
    s = s.replace(":", " | ")

    # Les dates deviennent des separateurs, pas des tokens : une date au
    # milieu d'un nom ("TANSIFT CONTRACTOR DIRECT 09/12/2025 30/12/2025")
    # doit couper, pas etre ignoree token par token.
    s = _DATE_NUM_RE.sub(" | ", s)
    s = _DATE_TXT_RE.sub(" | ", s)

    matches = list(_TOKEN_RE.finditer(s))
    if not matches:
        return None
    tokens = [m.group(0) for m in matches]

    if any(t.strip("-&") in ADMIN_ENTITY_TOKENS for t in tokens):
        return None

    # Un span = suite contigue de tokens sans BREAKER ni separateur "|".
    spans: list[list[str]] = []
    current: list[str] = []
    for i, tok in enumerate(tokens):
        if _classify(tok) == "BREAKER":
            if current:
                spans.append(current)
            current = []
            continue
        if current and "|" in s[matches[i - 1].end():matches[i].start()]:
            spans.append(current)
            current = []
        current.append(tok)
    if current:
        spans.append(current)

    # On ne garde que les spans portant au moins un token CORE : un span
    # d'articles seuls ("DE LA") n'est pas un nom.
    candidates = [sp for sp in spans if any(_classify(t) == "CORE" for t in sp)]
    if not candidates:
        return None

    def score(sp: list[str]) -> tuple[int, int, int]:
        """Priorite : forme juridique, puis nombre de mots, puis nombre de
        lettres.

        1. La forme juridique prime sur la longueur. Mesure : sans elle,
           "EQUIPERF SARL RESIDENCE DALIA AV YACOUB EL MANSOUR -I1-APP6
           MARRAKECH" retenait le span d'ADRESSE (3 tokens CORE) plutot que
           le vrai nom (2 tokens) — dans un PV, l'adresse suit toujours le
           nom et peut etre plus longue que lui.
        2. Le nombre de lettres departage les ex aequo. Sans ce troisieme
           critere, `max()` gardait le PREMIER span a egalite de score :
           sur "(OH TTC) COSTACOM" (doc 1513f22dbb14), les spans ["OH"] et
           ["COSTACOM"] ont tous deux 1 token CORE et aucune forme
           juridique, donc "OH" l'emportait par sa seule position — puis
           tombait sous MIN_REAL_LETTERS_WITHOUT_LEGAL, et l'entreprise
           entiere etait rejetee. Trouve en verifiant COSTACOM apres
           rechargement, pas en relisant le code.
        """
        n_core = sum(1 for t in sp if _classify(t) == "CORE")
        has_legal = any(t.strip("-&") in LEGAL_TOKENS for t in sp)
        n_letters = sum(len(re.findall(r"[A-Z]", t)) for t in sp)
        return (1 if has_legal else 0, n_core, n_letters)

    best = max(candidates, key=score)

    # Rogner les tokens NEUTRAL de bord : ils n'appartiennent pas au nom
    # ("1 SOCIETE PLANET PROJECT" -> "SOCIETE PLANET PROJECT", "PROMAMEC _"
    # -> "PROMAMEC").
    while best and _classify(best[0]) == "NEUTRAL":
        best = best[1:]
    while best and _classify(best[-1]) == "NEUTRAL":
        best = best[:-1]
    if not best:
        return None

    cleaned = " ".join(best)
    has_legal = any(t.strip("-&") in LEGAL_TOKENS for t in best)
    n_named = sum(1 for t in best
                  if _classify(t) == "CORE" and t.strip("-&") not in LEGAL_TOKENS)

    # Une forme juridique toute seule n'est pas un nom : "GROUPEMENT",
    # "SOCIETES" sont ce qui reste d'une phrase tronquee, pas une entite.
    if n_named == 0:
        return None

    # Un nom sans aucune forme juridique et sous le plancher de lettres
    # reelles est un fragment OCR, pas un nom (cas AN/CT/TF deja mesures en
    # remontant aux documents sources — voir l'historique du filtre).
    if not has_legal and len(re.findall(r"[A-Z]", cleaned)) < MIN_REAL_LETTERS_WITHOUT_LEGAL:
        return None

    # Un mot unique present dans plus de la moitie des PV du corpus n'est
    # pas une marque, c'est du vocabulaire de formulaire (voir
    # CORPUS_COMMON_WORDS). Ne s'applique qu'aux spans reduits a un seul
    # token CORE, et jamais quand une forme juridique accompagne le mot.
    if not has_legal and n_named == 1:
        only = next(t.strip("-&") for t in best if _classify(t) == "CORE")
        if only in CORPUS_COMMON_WORDS:
            return None

    # PAS de regle "un seul mot survivant = residu de phrase" : essayee et
    # MESUREE trop agressive — elle rejetait 6 entreprises reelles a un mot
    # (SEDERAM, CHRONOTECH, BOLIGAM, BAUENER, SOCHTRAP, SETRAGEC, toutes
    # issues de "<NOM> - OFFRE DE BASE" ou "SANS RESERVE <NOM>") pour ne
    # gagner que 4 rejets. Les mots generiques qu'elle visait (BASE, ELEVEE,
    # ARCHITECTE) sont traites la ou ils appartiennent : dans FIELD_LABELS
    # et VERB_TOKENS. Un nom de marque d'un seul mot est parfaitement
    # ordinaire ; une regle sur le NOMBRE de mots ne peut pas les separer.

    return cleaned
