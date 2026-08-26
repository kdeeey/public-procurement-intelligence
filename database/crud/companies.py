"""
Company resolution: raw text -> one or more Company rows, deduplicated by
normalize_company_name(). See database/normalization.py for the rule itself
and split_groupement() for the groupement case.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from database.models import Company
from database.normalization import normalize_company_name, split_groupement
from ocr.matching import date_variants

# A real company name never runs this long — measured on the 318
# concurrent_retenu values in data/processed/extracted/: p95 = 139 chars,
# p99 = 198, and the single value over 255 chars (393) is confirmed noise
# on inspection ("Lot no1 : Travaux d'amenagement des voies... Son offre
# est l'offre economiquement la plus avantageuse... Lot no2 : Travaux
# d'amenagement..." — a lot description plus boilerplate justification
# text, no company name present at all, the same unreliable-extraction
# category Issue 7 already documented on scrambled-layout documents).
# Rejecting it here (get_or_create_company returns None) rather than
# widening the column: storing this as a "Company" would fabricate a fake
# entity, which is worse than the PostgreSQL length error it would
# otherwise raise (confirmed by actually running against real PostgreSQL,
# not SQLite, which enforces no VARCHAR length at all).
MAX_PLAUSIBLE_NAME_LENGTH = 250

# Deuxieme filtre, plus fin que la seule longueur : mesure sur les 292
# Company que produisait le pipeline avant ce filtre. 28% (83/292) etaient
# du bruit pur, 10% (28/292) un nom reel noye dans du texte parasite — le
# plafond de 250 caracteres ne rattrapait que les 2 cas les plus extremes
# (254 et 393 caracteres), pas ce bruit plus court.
#
# 1. Aucun token de forme juridique/structure ET longueur suspecte pour un
#    nom propre. Mesure sur les 246 Company sans token de structure :
#    inspection manuelle de la tranche 50-90 caracteres (30 valeurs) n'a
#    trouve AUCUN nom d'entreprise reel, seulement des fragments de phrase
#    ("le concurrent a presente l'offre la plus avantageuse", "sans reserve
#    : TRAFFITEC- RIFL BIOMETRICS- RPR- ES DATA SERVICES"...). La tranche
#    30-50 est melangee (vrais noms sans forme juridique comme "CENTRALE
#    MAROCAINE D'ASSURANCES", 31 caracteres, y coexistent avec du bruit) —
#    50 caracteres est le seuil ou le bruit devient exclusif dans
#    l'echantillon inspecte, pas une valeur choisie a priori.
# 2. Premier mot du nom normalise = un mot de tete de phrase extraite,
#    jamais le debut d'un nom d'entreprise reel — la position compte : ces
#    memes mots ailleurs dans la chaine ne declenchent rien (une entreprise
#    peut legitimement contenir "GESTION" ou un mot proche sans que ce soit
#    le premier token).
STRUCTURE_TOKENS = {"SARL", "STE", "SOCIETE", "SA", "SNC", "GROUPEMENT"}
SUSPICIOUS_LENGTH_WITHOUT_STRUCTURE = 50
NOISE_LEADING_WORDS = {"JUSTIFICATION", "MONTANT", "MONTANTS", "ATTRIBUTAIRE",
                       "CONCURRENT", "CONCURRENTS"}

# 3. Boilerplate justification vocabulary ("l'offre economiquement la plus
#    avantageuse"), checked ANYWHERE in the name rather than only leading —
#    found in Issue 10 (company_id 48, source doc 37526643f298...: raw
#    concurrent_retenu "economiquement la Plus avantageuse.", a truncated
#    fragment of that exact phrase) ranked #1 by total_amount_ttc in
#    company_stats_global, the single most visible spot a noisy entry could
#    occupy. Neither word is leading-position-safe like NOISE_LEADING_WORDS
#    (the phrase gets truncated at different points depending on how much
#    of the sentence extraction kept), so it needs its own anywhere-position
#    check — but gated on "no structure token", same guard as the length
#    rule: an unconditional anywhere-position check would also reject 2
#    real names measured in the corpus ("...la plus avantageuse - Societe
#    ALHAYAT TEC SARL...", "...Societe BIRG sarl au...") that happen to
#    contain "avantageuse" in their surrounding sentence noise but do carry
#    a real SARL-suffixed name — those must stay recoverable.
NOISE_WORDS_WHEN_NO_STRUCTURE = {"AVANTAGEUSE", "ECONOMIQUEMENT"}

# 4. Bruit trouve en inspectant manuellement les 217 Company restantes apres
#    le correctif "(...)" (Issue 10) — 4 sous-categories, aucune couverte par
#    les regles ci-dessus :
#
#    a. "NEANT" ("- Neant", "du marche : Neant.") : mot de formulaire pour
#       "champ vide", jamais un nom d'entreprise. Contrairement a
#       NOISE_LEADING_WORDS, NEANT n'est pas toujours en tete (position
#       variable selon ou le champ vide apparait dans le PV) — verifie
#       n'importe ou dans le nom, sans condition sur has_structure : aucun
#       nom reel du corpus ne contient legitimement ce mot.
#    b. Un pattern de date lu comme concurrent_retenu ("31/12/2025",
#       doc 1a2b0ab1...) — reutilise le meme regex que
#       ocr/matching.py::date_variants() plutot que d'en ecrire un nouveau
#       (voir _looks_like_date ci-dessous) : jamais anticipe avant Issue 10,
#       aucune regle precedente ne le couvrait.
#    c. Aucune lettre du tout ("-", "01", "1/2", "\ 60") — un nom
#       d'entreprise contient toujours au moins une lettre.
#    d. Fragments a 1-2 lettres reelles sans marqueur de forme juridique
#       ("AN", "CT", "TF", "S", "E", "Y", et par extension "^LZ"/"U 0 E"/
#       "__ U" une fois les caracteres non-alphabetiques ignores). Verifie
#       sur les 3 cas ambigus (AN/CT/TF) en remontant au document source,
#       meme methode que pour "(OH TTC) COSTACOM" : dans les 3, le texte
#       immediatement apres "Concurrent/Soumissionnaire retenu :" est un
#       fragment OCR illisible ou une abreviation de colonne de tableau
#       ("TF"/"TC" = Tranche Ferme/Conditionnelle), le vrai nom du
#       vainqueur apparaissant plusieurs lignes plus bas dans le tableau des
#       montants (ex. doc 9ff585fd...: "TF: 736 955.00 DH" a cote de
#       "IMS TECHNOLOGY", pas "TF" seul) — meme defaut d'extraction que
#       COSTACOM, pas trois incidents isoles.
#
#       Le seuil ne peut PAS se baser sur normalized (le marqueur juridique
#       en est deja retire par normalize_company_name — "STE SEN SARL"
#       devient "SEN" avant meme que ce filtre ne s'execute : chercher
#       SARL/STE dans le nom normalise ne le trouve donc quasiment jamais
#       pour le cas prefixe/suffixe simple). Il faut re-verifier le texte
#       BRUT (avant normalisation) pour savoir si un marqueur existait —
#       d'ou le parametre `raw` optionnel de _looks_implausible ci-dessous.
#       Compte les LETTRES reelles (pas la longueur totale de la chaine,
#       qui inclurait les caracteres de bruit comme "^" dans "^LZ") : mesure
#       sur les 217 Company, aucun nom reel sous ce seuil n'existe SANS
#       marqueur juridique dans son texte brut — "SEN"/"TCN" (3 lettres)
#       gardees uniquement parce que "STE"/"SOCIETE" est present dans leur
#       display_name original, "BIGC"/"SEMH" (4 lettres) au-dessus du
#       seuil de toute facon.
NOISE_WORDS_ANYWHERE = {"NEANT"}
MIN_REAL_LETTERS_WITHOUT_MARKER = 3

# Meme regex que date_variants() (ocr/matching.py) : JJ<sep>MM<sep>AAAA,
# separateur tolerant (`\D` = tout non-chiffre). Une valeur qui matche
# produit une liste de variantes differente de [valeur] ; une valeur qui ne
# matche pas ressort inchangee — pas besoin de dupliquer le regex.
def _looks_like_date(value: str) -> bool:
    return date_variants(value) != [value]


def _fold_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _raw_has_legal_marker(raw: str) -> bool:
    """Le marqueur de forme juridique dans le texte BRUT, avant que
    normalize_company_name() ne le retire (prefixe/suffixe simple) — voir
    le point 4d ci-dessus pour pourquoi verifier `normalized` ne suffit
    pas."""
    words = _fold_accents(raw.upper()).split()
    return any(w.strip(".,;:'\"") in STRUCTURE_TOKENS for w in words)


def _looks_implausible(normalized: str, raw: str | None = None) -> bool:
    words = normalized.split()
    if not words:
        return True
    if not re.search(r"[A-Za-z]", normalized):
        return True
    if _looks_like_date(normalized):
        return True
    if words[0] in NOISE_LEADING_WORDS:
        return True
    if any(w in NOISE_WORDS_ANYWHERE for w in words):
        return True
    has_structure = any(w in STRUCTURE_TOKENS for w in words)
    if not has_structure:
        if len(normalized) >= SUSPICIOUS_LENGTH_WITHOUT_STRUCTURE:
            return True
        if any(w in NOISE_WORDS_WHEN_NO_STRUCTURE for w in words):
            return True
        has_marker = raw is not None and _raw_has_legal_marker(raw)
        if not has_marker:
            n_letters = len(re.findall(r"[A-Za-z]", normalized))
            if n_letters < MIN_REAL_LETTERS_WITHOUT_MARKER:
                return True
    return False


def get_or_create_company(session: Session, raw_name: str) -> Company | None:
    """One raw company name -> its Company row, creating it if new.

    None when `raw_name` normalizes to an empty string (pure punctuation/
    noise slipping through from an unvalidated field like liste_concurrents),
    is implausibly long (MAX_PLAUSIBLE_NAME_LENGTH), or fails the plausibility
    check in _looks_implausible() — never silently create a blank or
    fabricated Company. This filter is measured, not exhaustive (see the
    comment above _looks_implausible and database/README.md for the
    residual error rate after applying it) — some noise will still pass,
    and a small number of real names may be rejected.
    """
    if len(raw_name) > MAX_PLAUSIBLE_NAME_LENGTH:
        return None
    normalized = normalize_company_name(raw_name)
    if not normalized or _looks_implausible(normalized, raw=raw_name):
        return None

    existing = session.query(Company).filter_by(normalized_name=normalized).one_or_none()
    if existing:
        return existing

    company = Company(normalized_name=normalized, display_name=raw_name.strip())
    session.add(company)
    session.flush()  # obtain company.id for the caller's award_companies link
    return company


def resolve_companies(session: Session, concurrent_retenu: str | None) -> list[Company]:
    """The winner field of an Award -> the Company row(s) behind it.

    A groupement resolves to 2+ Company rows (data_dictionary.md §3.1 — the
    Award record itself is never split, but its winner can be more than one
    legal entity). Everything else resolves to exactly one, or zero when
    concurrent_retenu is empty or pure noise.
    """
    if not concurrent_retenu:
        return []
    if "GROUPEMENT" in concurrent_retenu.upper():
        members = split_groupement(concurrent_retenu)
    else:
        members = [concurrent_retenu]
    companies = [get_or_create_company(session, m) for m in members]
    return [c for c in companies if c is not None]
