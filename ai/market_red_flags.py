"""
Red flags metier au grain marche — registre de regles (Phase 2, 28/08/2026).

SEPARATION VOULUE, ET POURQUOI
-------------------------------
Deux choses differentes, deliberement gardees distinctes :

  A. Les FEATURES du modele (ai/train_market_model.py) — numeriques,
     imputees, encodees, lisibles par Isolation Forest, illisibles par un
     analyste.
  B. Les RED FLAGS de ce module — des regles nommees, chacune vraie, fausse
     ou non evaluable sur un marche donne, comprehensibles sans connaitre
     le modele.

Un red flag n'est PAS une composante du score d'anomalie et n'est jamais
fusionne arithmetiquement avec lui. Mesure a l'appui : la correlation entre
`anomaly_score` et le nombre de red flags actifs vaut **+0,096** — les deux
signaux sont quasi independants. C'est ce qui justifie de les presenter
cote a cote (et, en Phase 6, de les combiner), pas de les additionner
aveuglement.

TOUTE CONDITION EST ADOSSEE AUX ETATS DE features/data_quality.py
------------------------------------------------------------------
Aucune regle ne relit les valeurs brutes pour decider si l'information
existe : elles consomment toutes les quatre etats KNOWN / UNKNOWN /
INVALID / NOT_APPLICABLE produits par le module de qualite. Une seule
source de verite, donc aucune possibilite qu'un red flag et le Data
Quality Score disent l'inverse l'un de l'autre sur le meme marche.

Un flag ne se declenche jamais sur une valeur absente, imputee ou
incoherente. Dans ces cas il vaut None (NOT_EVALUABLE), jamais False :
dire "pas de red flag" sur un marche dont on ignore tout serait un faux
negatif presente comme un controle passe.

CORRECTIF DE LA PHASE 2 — RF01 COMPTAIT DES DEFAUTS D'EXTRACTION
------------------------------------------------------------------
L'ancienne regle etait `nb_soumissionnaires <= 1`. Or 0 <= 1. Mesure au
28/08/2026 : sur les 152 RF01 actifs, **56 (37 %) venaient d'un marche
ATTRIBUE ou aucun nom n'avait pu etre lu** — dont 35 ou des noms figuraient
bel et bien dans le document mais avaient tous ete rejetes par le filtre de
plausibilite. Un marche ne peut pas etre attribue a personne : ce 0 est un
defaut de notre chaine d'extraction, pas une absence de concurrence.

features/data_quality.py marque desormais ces marches `INVALID` sur la
dimension `concurrents`, et RF01 lit cet etat : il devient NOT_EVALUABLE
au lieu de se declencher. Le red flag le plus frequent du systeme perd
ainsi 37 % de ses declenchements — c'est une perte de signal apparent qui
est un gain d'exactitude.

RF04 N'EXISTE PAS — ET C'EST MESURE
------------------------------------
Le red flag "ecart entre estimation et attribution" est IMPOSSIBLE sur ce
corpus : `estimation_dhs_ttc` est renseignee pour 1196/1350 consultations
de la Passe B mais **0/454** des marches lies a un Award — la page d'un
marche deja attribue ne porte plus son estimation. Aucune valeur n'est
fabriquee pour combler ce trou. Sa numerotation est laissee vide pour que
son absence se voie plutot qu'elle ne se devine.

VOCABULAIRE
-----------
Aucun libelle n'affirme une irregularite. "Atypique", "inhabituel",
"a verifier" — jamais "fraude", "corruption", "irregulier". Le systeme
signale des caracteristiques, il ne conclut pas.

    python -m ai.market_red_flags
"""

from __future__ import annotations

import enum
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from features.data_quality import State, assess_market  # noqa: E402

SCORES_PATH = REPO / "data/processed/analytics/market_anomaly_scores.parquet"
RED_FLAGS_PATH = REPO / "data/processed/analytics/market_red_flags.parquet"
THRESHOLDS_PATH = REPO / "data/processed/analytics/red_flag_thresholds.json"

# --------------------------------------------------------------------------- #
# Seuils — MESURES a l'execution sur la distribution reelle, jamais figes ici.
# Le projet a deja paye le prix d'un seuil ecrit en dur devenu faux quand la
# population a change (voir database/crud/counts.py).
# --------------------------------------------------------------------------- #

# RF02 : quantile de `exclusion_rate`. 0,90 avait ete essaye et MESURE
# degenere — il vaut exactement 1,000 sur ce corpus (59,9 % des marches
# evaluables sont a 0, puis une queue chargee a 1), c'est-a-dire "100 % des
# concurrents ecartes" : une borne, pas un seuil. 0,80 donne 0,50, soit
# "au moins la moitie des concurrents ecartes" — mesure ET interpretable.
EXCLUSION_RATE_QUANTILE = 0.80

# RF03 : quantile de `montant_ttc` sur tout le corpus. Depuis la Phase 3,
# ce n'est plus la reference PRINCIPALE mais le REPLI : quand une
# comparaison a des marches comparables existe (ai/market_peer_analysis.py),
# elle fait autorite. Le repli reste necessaire — la comparaison aux pairs
# n'est calculable que pour 67/314 marches, faute d'assez de comparables
# portant eux-memes un montant. `rf03_reference` trace lequel des deux a
# servi, marche par marche.
MONTANT_QUANTILE = 0.95

# RF05 : part maximale du corpus en dessous de laquelle une procedure est
# dite rare. Mesure : la distribution est franchement bimodale — 2
# procedures couvrent 98,1 % des marches, les 4 autres n'en totalisent que
# 6. Le seuil a 5 % et le seuil a 2 % designent donc EXACTEMENT le meme
# ensemble ; le choix de la valeur ne change rien, ce qui est en soi un
# resultat de robustesse.
PROCEDURE_RARE_MAX_SHARE = 0.05


class Severity(str, enum.Enum):
    """Niveau d'attention, PAS une probabilite ni une gravite mesuree.

    A dire tel quel en soutenance : sans verite terrain, aucun effet ne
    peut etre estime sur ce corpus. Ces niveaux traduisent une priorite de
    lecture issue de la litterature (Fazekas et al. : la concurrence est
    l'indicateur le mieux etabli, la taille du contrat le plus ambigu), pas
    une mesure faite ici. Ils sont donc revisables par decision humaine,
    et ils ne se transforment jamais en probabilite.
    """
    ELEVEE = "elevee"
    MOYENNE = "moyenne"
    FAIBLE = "faible"


SEVERITY_WEIGHTS = {Severity.ELEVEE: 3.0, Severity.MOYENNE: 2.0, Severity.FAIBLE: 1.0}


@dataclass(frozen=True)
class RedFlag:
    id: str
    name: str
    description: str
    severity: Severity
    # (etats de qualite, ligne, seuils) -> True | False | None(non evaluable)
    evaluate: Callable[[dict, pd.Series, dict], bool | None]
    derived: bool = False   # RF06 : calcule a partir des autres, hors comptage


# --------------------------------------------------------------------------- #
# Conditions
# --------------------------------------------------------------------------- #

def _rf01(states, row, thresholds):
    """Faible concurrence : un seul soumissionnaire identifie.

    Evaluable uniquement si la dimension `concurrents` est KNOWN. UNKNOWN
    (pas de rubrique) et INVALID (marche attribue sans aucun nom lisible)
    donnent tous deux NOT_EVALUABLE — c'est le correctif de la Phase 2.

    Mesure sur les 244 marches evaluables : mediane 2 soumissionnaires,
    96 marches (39,3 %) a un seul. Le seuil est donc "exactement 1", pas un
    quantile : c'est la definition metier du soumissionnaire unique, elle
    ne se calibre pas.
    """
    if states["concurrents"] is not State.KNOWN:
        return None
    nb = pd.to_numeric(row.get("nb_soumissionnaires"), errors="coerce")
    return None if pd.isna(nb) else bool(nb <= 1)


def _rf02(states, row, thresholds):
    """Taux d'exclusion de concurrents atypiquement eleve.

    Exige les DEUX informations (nombre d'ecartes ET nombre de
    soumissionnaires) : le taux n'existe pas sinon. Un taux superieur a 1
    est arithmetiquement impossible et marque INVALID en amont — 18
    marches, tous avec 1 seul concurrent liste pour 2 a 3 ecartes, soit une
    incoherence entre les deux rubriques extraites.
    """
    if states["exclusions"] is not State.KNOWN:
        return None
    taux = pd.to_numeric(row.get("exclusion_rate"), errors="coerce")
    return None if pd.isna(taux) else bool(taux >= thresholds["exclusion_rate_seuil"])


def _rf03(states, row, thresholds):
    """Montant atypiquement eleve PAR RAPPORT A DES MARCHES COMPARABLES.

    Branche sur ai/market_peer_analysis.py depuis la Phase 3. La question
    "ce marche est-il gros ?" a ete remplacee par "ce marche est-il gros
    POUR CE QU'IL EST ?" — un marche de travaux et une prestation de
    services au meme montant ne sont pas comparables.

    Trois cas, dans cet ordre :
      1. une comparaison aux pairs existe -> elle fait autorite (le marche
         est-il au-dessus du P90 de ses comparables) ;
      2. pas de comparaison possible mais montant KNOWN -> repli sur le
         quantile du corpus entier, moins pertinent mais mieux que rien,
         et le repli est trace par `rf03_reference` ;
      3. montant non KNOWN -> non evaluable.

    Le repli concerne la majorite des marches : la comparaison aux pairs
    n'est calculable que pour 67/314 d'entre eux, faute d'assez de
    comparables portant eux-memes un montant (63 % du corpus n'a pas de
    montant extrait). Ne pas le dire laisserait croire que tous les RF03
    sont adosses a des comparables.
    """
    if states["montant"] is not State.KNOWN:
        return None
    au_dessus_p90 = row.get("amount_above_peer_p90")
    if au_dessus_p90 is not None and not (
            isinstance(au_dessus_p90, float) and pd.isna(au_dessus_p90)):
        return bool(au_dessus_p90)
    montant = pd.to_numeric(row.get("montant_ttc"), errors="coerce")
    return None if pd.isna(montant) else bool(montant >= thresholds["montant_ttc_seuil"])


# RF04 : volontairement absent. Voir la docstring du module.


def _rf05(states, row, thresholds):
    """Procedure rare dans le corpus.

    ATTENTION, limite a dire a l'analyste plutot qu'a masquer : la rarete
    n'est pas une irregularite. Sur les 6 marches concernes, 4 sont des
    concours ou consultations d'architecture — une categorie parfaitement
    reguliere, simplement peu frequente ici. Ce flag signale "ce marche
    n'a pas suivi la voie habituelle de ce corpus", rien de plus, et sa
    severite est fixee a FAIBLE pour cette raison.

    `mode_passation` est renseigne a 100 % : ce flag n'est jamais
    NOT_EVALUABLE, sauf valeur manquante inattendue.
    """
    procedure = row.get("mode_passation")
    if procedure is None or (isinstance(procedure, float) and pd.isna(procedure)):
        return None
    rares = thresholds.get("procedures_rares") or []
    return bool(procedure in rares)


def _rf06(states, row, thresholds):
    """Plusieurs signaux atypiques observes simultanement.

    DERIVE des flags primaires : ne compte jamais dans `red_flag_count` ni
    dans `red_flag_score`, sous peine de compter deux fois le meme signal
    (defaut mesure lors de la phase precedente : la repartition sautait de
    1 a 3 flags, aucun marche n'en affichait exactement 2).

    Non evaluable si moins de 2 flags primaires ont pu etre evalues : "0
    signal sur 1 regle applicable" ne dit pas la meme chose que "0 signal
    sur 4".
    """
    primaires = _evaluate_primary(states, row, thresholds)
    actifs = sum(1 for v in primaires.values() if v is True)
    evaluables = sum(1 for v in primaires.values() if v is not None)
    return actifs >= 2 if evaluables >= 2 else None


REGISTRY: tuple[RedFlag, ...] = (
    RedFlag(
        id="RF01",
        name="Faible concurrence",
        description=(
            "Un seul soumissionnaire identifié dans le document. La concurrence "
            "effective est faible sur ce marché — ce qui peut avoir des causes "
            "parfaitement légitimes (marché très spécialisé, délai court, "
            "prestation sur mesure)."),
        severity=Severity.ELEVEE,
        evaluate=_rf01,
    ),
    RedFlag(
        id="RF02",
        name="Exclusions atypiques",
        description=(
            "La part de concurrents écartés place ce marché dans le quintile "
            "supérieur du corpus. Une exclusion est une décision motivée de la "
            "commission ; leur proportion élevée justifie une lecture du PV, "
            "jamais une conclusion."),
        severity=Severity.MOYENNE,
        evaluate=_rf02,
    ),
    RedFlag(
        id="RF03",
        name="Montant atypique",
        description=(
            "Le montant attribué place ce marché dans les 5 % les plus élevés "
            "du corpus. Un gros marché n'a rien d'anormal en soi : c'est un "
            "critère de priorisation proportionné à l'enjeu financier."),
        severity=Severity.MOYENNE,
        evaluate=_rf03,
    ),
    RedFlag(
        id="RF05",
        name="Procédure rare",
        description=(
            "La procédure de passation est peu fréquente dans ce corpus. "
            "La rareté n'est pas une irrégularité : la majorité des cas "
            "concernés sont des concours d'architecture, une catégorie "
            "régulière mais peu représentée ici."),
        severity=Severity.FAIBLE,
        evaluate=_rf05,
    ),
    RedFlag(
        id="RF06",
        name="Signaux multiples",
        description=(
            "Au moins deux red flags primaires sont actifs simultanément. "
            "C'est la combinaison qui retient l'attention, pas chaque signal "
            "pris isolément."),
        severity=Severity.MOYENNE,
        evaluate=_rf06,
        derived=True,
    ),
)

PRIMARY_FLAGS = tuple(f.id for f in REGISTRY if not f.derived)
FLAGS_BY_ID = {f.id: f for f in REGISTRY}


def _evaluate_primary(states, row, thresholds) -> dict[str, bool | None]:
    return {f.id: f.evaluate(states, row, thresholds)
            for f in REGISTRY if not f.derived}


# --------------------------------------------------------------------------- #
# Seuils mesures
# --------------------------------------------------------------------------- #

def measure_thresholds(pdf: pd.DataFrame) -> dict:
    """Seuils lus sur la distribution du corpus, pas choisis a priori.

    Deux quantiles et une liste de procedures rares. Ils definissent "eleve
    par rapport aux autres marches de ce corpus", la seule reference dont
    on dispose — ils n'ont AUCUNE valeur normative externe : un quintile
    superieur n'est pas un seuil reglementaire, et le dashboard doit le
    presenter ainsi.
    """
    scorable = pdf[pdf["scorable"] == True]  # noqa: E712
    states = scorable.apply(assess_market, axis=1)

    # Seuls les etats KNOWN alimentent les seuils : calibrer sur une valeur
    # incoherente reviendrait a laisser un defaut d'extraction deplacer la
    # frontiere de tous les autres marches.
    ex_known = scorable.loc[[s["exclusions"] is State.KNOWN for s in states],
                            "exclusion_rate"]
    mt_known = scorable.loc[[s["montant"] is State.KNOWN for s in states],
                            "montant_ttc"]
    ex_known = pd.to_numeric(ex_known, errors="coerce").dropna()
    mt_known = pd.to_numeric(mt_known, errors="coerce").dropna()

    parts = pdf["mode_passation"].value_counts(normalize=True)
    rares = sorted(parts[parts < PROCEDURE_RARE_MAX_SHARE].index.tolist())

    return {
        "exclusion_rate_seuil": float(ex_known.quantile(EXCLUSION_RATE_QUANTILE)),
        "exclusion_rate_quantile": EXCLUSION_RATE_QUANTILE,
        "exclusion_rate_n_evaluables": int(len(ex_known)),
        "montant_ttc_seuil": float(mt_known.quantile(MONTANT_QUANTILE)),
        "montant_quantile": MONTANT_QUANTILE,
        "montant_n_evaluables": int(len(mt_known)),
        "procedures_rares": rares,
        "procedure_rare_max_share": PROCEDURE_RARE_MAX_SHARE,
        "procedures_rares_n_marches": int(
            pdf["mode_passation"].isin(rares).sum()),
    }


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #

def evaluate_market(row: pd.Series, thresholds: dict) -> dict[str, bool | None]:
    """Un marche -> {RFxx: True | False | None}. None = non evaluable."""
    states = assess_market(row)
    flags = _evaluate_primary(states, row, thresholds)
    for f in REGISTRY:
        if f.derived:
            flags[f.id] = f.evaluate(states, row, thresholds)
    return flags


def summarize(flags: dict[str, bool | None]) -> dict:
    """Comptes et score, sur les flags PRIMAIRES uniquement.

    `red_flag_score` est rescale sur les flags reellement evaluables pour
    ce marche, exactement comme le score composite d'ai/scoring.py et pour
    la meme raison : un marche dont 2 regles sur 4 sont inapplicables ne
    doit pas etre mecaniquement plafonne a 50 % parce qu'il nous manque des
    donnees. Le nombre de regles evaluables est publie a cote du score,
    pour que ce rescale reste lisible.
    """
    primaires = {k: v for k, v in flags.items() if k in PRIMARY_FLAGS}
    declenches = [k for k, v in primaires.items() if v is True]
    evaluables = [k for k, v in primaires.items() if v is not None]

    poids_actifs = sum(SEVERITY_WEIGHTS[FLAGS_BY_ID[k].severity] for k in declenches)
    poids_evaluables = sum(SEVERITY_WEIGHTS[FLAGS_BY_ID[k].severity] for k in evaluables)
    score = round(100 * poids_actifs / poids_evaluables, 1) if poids_evaluables else None

    return {
        "red_flag_count": len(declenches),
        "red_flags_evaluable": len(evaluables),
        "red_flags_triggered": ", ".join(declenches) if declenches else "",
        "red_flag_score": score,
    }


def describe(flags: dict[str, bool | None]) -> str:
    """Phrase destinee a un analyste.

    Formulation contrainte : ce module dit ce qui a ete observe et ce qui
    est reste inconnu, jamais qu'un marche serait irregulier.
    """
    actifs = [FLAGS_BY_ID[k].name for k in PRIMARY_FLAGS if flags.get(k) is True]
    non_eval = [FLAGS_BY_ID[k].name for k in PRIMARY_FLAGS if flags.get(k) is None]

    if actifs:
        base = "Signaux observés : " + " ; ".join(actifs) + "."
    else:
        base = "Aucun red flag actif parmi ceux qui ont pu être évalués."
    if non_eval:
        base += (" Non évaluable(s), faute de donnée lisible dans le document : "
                 + ", ".join(non_eval) + ".")
    base += (" Ces signaux orientent une analyse humaine ; ils ne constituent "
             "ni une preuve ni une présomption d'irrégularité.")
    return base


PEER_PATH = REPO / "data/processed/analytics/market_peer_comparison.parquet"


def main() -> int:
    pdf = pd.read_parquet(SCORES_PATH)
    # Comparables (Phase 3) : optionnels. Sans eux, RF03 retombe sur le
    # quantile du corpus — le module reste executable seul.
    if PEER_PATH.exists():
        peers = pd.read_parquet(PEER_PATH)[
            ["award_id", "amount_above_peer_p90", "peer_group_level",
             "n_peers_amount", "amount_vs_peer_median"]]
        pdf = pdf.merge(peers, on="award_id", how="left")
        print(f"comparables charges : {int(pdf['amount_above_peer_p90'].notna().sum())} "
              f"marches ont une reference de montant par groupe comparable")
    else:
        print("comparables absents — RF03 utilise le quantile du corpus entier")
    thresholds = measure_thresholds(pdf)

    print("=== registre des red flags ===")
    for f in REGISTRY:
        marque = " (derive)" if f.derived else ""
        print(f"  {f.id} — {f.name:<24} severite={f.severity.value:<8}{marque}")
    print("  RF04 — non implemente : estimation absente de 100 % des marches "
          "attribues (0/454)")

    print("\n=== seuils mesures sur le corpus ===")
    print(f"  RF02 exclusion_rate >= {thresholds['exclusion_rate_seuil']:.3f}"
          f"  (quantile {EXCLUSION_RATE_QUANTILE}, "
          f"{thresholds['exclusion_rate_n_evaluables']} marches KNOWN)")
    print(f"  RF03 montant_ttc   >= {thresholds['montant_ttc_seuil']:,.2f} DH"
          f"  (quantile {MONTANT_QUANTILE}, "
          f"{thresholds['montant_n_evaluables']} marches KNOWN)")
    print(f"  RF05 procedures rares (< {PROCEDURE_RARE_MAX_SHARE:.0%} du corpus) : "
          f"{len(thresholds['procedures_rares'])} modalites, "
          f"{thresholds['procedures_rares_n_marches']} marches")
    for p in thresholds["procedures_rares"]:
        print(f"         - {p}")

    rows = []
    for _, row in pdf.iterrows():
        flags = evaluate_market(row, thresholds)
        record = {"award_id": row["award_id"]}
        record.update({k: v for k, v in flags.items()})
        record.update(summarize(flags))
        # Trace explicite de la reference employee par RF03, pour que le
        # dashboard ne presente pas un repli comme une comparaison a des pairs.
        p90 = row.get("amount_above_peer_p90")
        record["rf03_reference"] = (
            "pairs" if p90 is not None and not (isinstance(p90, float) and pd.isna(p90))
            else ("corpus" if flags["RF03"] is not None else "non evaluable"))
        record["explication"] = describe(flags)
        rows.append(record)
    flags_pdf = pd.DataFrame(rows)

    result = pdf[["award_id", "reference", "acheteur_public", "statut", "scorable",
                  "anomaly_score_0_100", "is_anomaly", "stability_frequency",
                  "data_completeness"]].merge(flags_pdf, on="award_id", how="left")

    print(f"\n=== frequence des red flags ({len(result)} marches attribues) ===")
    print(f"{'flag':<8}{'nom':<26}{'actif':>7}{'inactif':>9}{'non evaluable':>15}")
    for f in REGISTRY:
        col = result[f.id]
        print(f"  {f.id:<6}{f.name:<26}{int((col == True).sum()):>7}"  # noqa: E712
              f"{int((col == False).sum()):>9}{int(col.isna().sum()):>15}")  # noqa: E712

    print("\n=== effet du correctif RF01 (Phase 2) ===")
    print("  Ancienne regle `nb <= 1` : 152 marches actifs, dont 56 (37 %) sans")
    print("  aucun nom lisible — un defaut d'extraction compte comme un signal.")
    print(f"  Nouvelle regle (dimension `concurrents` KNOWN requise) : "
          f"{int((result['RF01'] == True).sum())} actifs, "  # noqa: E712
          f"{int(result['RF01'].isna().sum())} non evaluables.")

    print("\n=== repartition du nombre de flags primaires actifs ===")
    for n, g in result.groupby("red_flag_count"):
        scorable = g[g["scorable"] == True]  # noqa: E712
        moyenne = scorable["anomaly_score_0_100"].mean()
        print(f"  {int(n)} flag(s) : {len(g):3d} marches, score d'anomalie moyen "
              f"{moyenne:5.1f}, {int(scorable['is_anomaly'].sum()):2d} signales par le modele")

    corr = (result.loc[result["scorable"] == True, "anomaly_score_0_100"]  # noqa: E712
            .corr(result.loc[result["scorable"] == True, "red_flag_count"]))
    print(f"\n  correlation(score d'anomalie, nombre de red flags) = {corr:+.3f}")
    print("  Les deux approches se recoupent sans se confondre. Un marche tres")
    print("  atypique SANS red flag nomme est une combinaison inhabituelle")
    print("  qu'aucune regle ne couvre — c'est ce qu'un modele non supervise")
    print("  apporte en plus d'une liste de regles.")

    RED_FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(RED_FLAGS_PATH, index=False)
    THRESHOLDS_PATH.write_text(json.dumps(thresholds, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    print(f"\nEcrit : {RED_FLAGS_PATH}")
    print(f"Ecrit : {THRESHOLDS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
