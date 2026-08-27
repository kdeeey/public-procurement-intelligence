"""
Company resolution: raw text -> one or more Company rows, deduplicated by
normalize_company_name(). See database/normalization.py for the rule itself
and split_groupement() for the groupement case.

CHANGEMENT DU 27/08/2026 — le filtre de plausibilite a disparu d'ici.
`_looks_implausible()` et ses quatre listes de mots interdits
(`NOISE_LEADING_WORDS`, `NOISE_WORDS_ANYWHERE`,
`NOISE_WORDS_WHEN_NO_STRUCTURE`, seuil de longueur) sont remplaces par
`extraction/company_name.py::clean_company_candidate()`, applique
desormais EN AMONT dans extraction/fields.py. Raison mesuree : sur les 200
Company que produisait l'ancien filtre, 107 (53,5%) etaient affectees — un
filtre qui ne sait que rejeter ne pouvait rien faire des 73 cas ou un vrai
nom etait noye dans du texte parasite. Detail complet dans la docstring de
`extraction/company_name.py` et dans bigdata/README.md.

L'appel est conserve ici malgre le nettoyage amont, pour deux raisons :
les membres issus de `split_groupement()` n'ont jamais ete nettoyes
individuellement, et le nettoyage est idempotent (un nom deja propre en
ressort inchange, verifie sur les 93 noms propres du corpus).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from database.aliases import corrections, load_aliases
from database.models import Company
from database.normalization import normalize_company_name, split_groupement
from extraction.company_name import clean_company_candidate

# Liste de rejet CURATEE, chargee depuis data/reference/company_aliases.csv :
# les valeurs dont `confirme_dans_le_document` vaut "non".
#
# Pourquoi une liste, apres avoir justement remplace quatre listes de rejet
# par une regle generale ? Parce que ce n'est pas la meme chose. Les
# anciennes listes etaient des REGLES devinees a partir de quelques exemples,
# jamais mesurees, et qui grossissaient a chaque session. Celle-ci est une
# DONNEE : chaque entree a ete verifiee contre le texte du PV, la preuve est
# citee dans le fichier ("le PV ecrit 'six Dirnams toutes taxes comprises'",
# "le PV ecrit 'Monfant de l'acte d'engagement'"), le fichier est versionne
# et date, et chaque ligne est recontrolable.
#
# La regle structurelle de extraction/company_name.py reste la premiere
# barriere et traite le cas general. Cette liste ne rattrape que le residu
# qu'aucune regle generale ne peut atteindre : des fragments OCR rares,
# indiscernables d'un nom de marque rare par la forme ou la frequence. Le
# cas TFC ("Montant TTC" mal lu, qui ressemble a une vraie entreprise
# casablancaise) et le cas inverse NORD EST ELECTRONIQUE (une vraie
# entreprise que j'avais classee bruit) montrent que seule la lecture du
# document tranche — donc que la connaissance doit etre stockee, pas devinee.
#
# Le meme fichier porte aussi les CORRECTIONS (colonne `nom_corrige`) : un
# libelle inutilisable comme identite, mais qui contient litteralement un
# nom lisible, est remplace par ce nom plutot que rejete. Voir
# database/aliases.py::corrections() pour la regle — la valeur de
# remplacement doit toujours etre une sous-chaine du texte source.
try:
    _REJECTED = frozenset(
        k for k, a in load_aliases().items() if a.is_rejected)
    _CORRECTIONS = corrections()
except Exception:  # fichier absent : le filtre structurel suffit
    _REJECTED = frozenset()
    _CORRECTIONS = {}

# A real company name never runs this long — measured on the 318
# concurrent_retenu values in data/processed/extracted/: p95 = 139 chars,
# p99 = 198, and the single value over 255 chars (393) is confirmed noise
# on inspection. Conserve comme garde-fou de derniere ligne : PostgreSQL
# leverait une erreur de longueur VARCHAR la ou None est le bon resultat.
MAX_PLAUSIBLE_NAME_LENGTH = 250


def get_or_create_company(session: Session, raw_name: str) -> Company | None:
    """One raw company name -> its Company row, creating it if new.

    None quand la valeur ne contient aucun nom d'entreprise isolable
    (clean_company_candidate) ou se normalise en chaine vide — jamais de
    Company vide ou fabriquee. Le nettoyage est mesure, pas exhaustif :
    voir bigdata/README.md pour le taux de bruit residuel nomme.
    """
    if len(raw_name) > MAX_PLAUSIBLE_NAME_LENGTH:
        return None
    cleaned = clean_company_candidate(raw_name)
    if not cleaned:
        return None
    normalized = normalize_company_name(cleaned)
    if not normalized:
        return None
    if normalized in _REJECTED:
        # Bruit confirme par lecture du document source — jamais une Company.
        # L'Award perd son lien vers une entreprise, ce qui est le resultat
        # correct : mieux vaut un marche sans attributaire identifie qu'un
        # marche attribue a une entite qui n'existe pas.
        return None

    if normalized in _CORRECTIONS:
        # Libelle inutilisable mais contenant un nom lisible : on garde le
        # nom, pas le bruit. Le texte brut integral reste dans
        # Award.concurrent_retenu_brut, donc la tracabilite est intacte.
        cleaned = _CORRECTIONS[normalized]
        normalized = normalize_company_name(cleaned)
        if not normalized:
            return None

    existing = session.query(Company).filter_by(normalized_name=normalized).one_or_none()
    if existing:
        return existing

    company = Company(normalized_name=normalized, display_name=cleaned.strip())
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
