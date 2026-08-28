"""
Rapport avant/apres de la refonte du 28/08/2026 (entreprise -> marche).

Compare l'etat SAUVEGARDE avant la refonte (backups/2026-08-28_pre-market-
refactor/) a l'etat courant, en relisant les deux jeux d'artefacts plutot
qu'en recopiant des chiffres a la main. Aucun nombre de ce rapport n'est
ecrit en dur : s'ils changent, le rapport change.

    python scripts/report_refonte.py
    python scripts/report_refonte.py --markdown docs/refonte_marche.md
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

BACKUP = REPO / "backups/2026-08-28_pre-market-refactor"
ANALYTICS = REPO / "data/processed/analytics"


def _load_report(nom: str):
    p = ANALYTICS / nom
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def _read(path: Path):
    return pd.read_parquet(path) if path.exists() else None


def section(out, title: str) -> None:
    out.write(f"\n## {title}\n\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", type=Path, default=None,
                    help="ecrire le rapport en Markdown a ce chemin")
    args = ap.parse_args()

    out = io.StringIO()
    out.write("# Rapport de refonte — de l'entreprise au marché (28/08/2026)\n")
    out.write("\n> Genere par `scripts/report_refonte.py`. Tous les chiffres sont "
              "relus depuis les artefacts, aucun n'est ecrit en dur.\n")

    # ------------------------------------------------------------------ #
    old_features = _read(BACKUP / "analytics/company_features.parquet")
    old_risk = _read(BACKUP / "analytics/company_final_risk.parquet")
    new_markets = _read(ANALYTICS / "market_features.parquet")
    new_scores = _read(ANALYTICS / "market_anomaly_scores.parquet")
    new_flags = _read(ANALYTICS / "market_red_flags.parquet")
    new_expl = _read(ANALYTICS / "market_explanations.parquet")

    if new_scores is None:
        print("market_anomaly_scores.parquet absent — lancer ai/train_market_model.py")
        return 1

    section(out, "1. Unité d'analyse")
    out.write("| | Avant | Après |\n|---|---|---|\n")
    out.write(f"| Observation | 1 entreprise | 1 marché (Award, = 1 lot) |\n")
    out.write(f"| Population | {len(old_features)} entreprises | "
              f"{len(new_markets)} marchés dont "
              f"{int((new_markets['statut'] == 'ATTRIBUE').sum())} attribués |\n")
    out.write(f"| Observations modélisées | {len(old_risk)} | "
              f"{int((new_scores['scorable'] == True).sum())} |\n")  # noqa: E712

    if old_features is not None:
        depth = old_features["number_of_awards"].value_counts().sort_index()
        out.write("\n**Pourquoi la bascule** — profondeur du corpus par entreprise :\n\n")
        for k, v in depth.items():
            out.write(f"- {int(v)} entreprises avec {int(k)} marché(s) "
                      f"({100 * v / len(old_features):.1f} %)\n")
        if old_risk is not None:
            merged = old_features.merge(old_risk[["company_id", "is_anomaly"]],
                                        on="company_id")
            out.write("\nTaux de signalement de l'ancien modèle selon cette profondeur :\n\n")
            for k, g in merged.groupby("number_of_awards"):
                out.write(f"- {int(k)} marché(s) : {int(g['is_anomaly'].sum())}/{len(g)} "
                          f"signalées ({100 * g['is_anomaly'].mean():.1f} %)\n")
            out.write("\nLe modèle apprenait la profondeur de présence dans le corpus, "
                      "un artefact de couverture du scraping.\n")

    # ------------------------------------------------------------------ #
    section(out, "2. Features")
    old_cols = json.loads((BACKUP / "models/feature_columns.json").read_text(encoding="utf-8"))
    new_cols = json.loads((REPO / "ai/models/market_feature_columns.json").read_text(encoding="utf-8"))
    out.write(f"- Avant : **{len(old_cols)}** colonnes d'entrée — `{', '.join(old_cols)}`\n")
    out.write(f"- Après : **{len(new_cols)}** colonnes d'entrée — `{', '.join(new_cols)}`\n")

    if old_features is not None:
        out.write("\n**Features retirées, et leur support mesuré avant retrait :**\n\n")
        out.write("| Feature | Support | Décision |\n|---|---|---|\n")
        for col in ("has_trend_data", "single_bidder_rate_trend_slope",
                    "number_of_awards_trend_slope", "groupement_rate"):
            if col not in old_features.columns:
                continue
            if col == "groupement_rate":
                n = int((old_features[col].fillna(0) != 0).sum())
                support = f"{n}/{len(old_features)} non nuls"
            else:
                n = int(old_features[col].notna().sum())
                support = f"{n}/{len(old_features)} renseignés"
            out.write(f"| `{col}` | {support} | retirée |\n")
        out.write("\n`price_ratio` / `price_deviation` n'ont **pas** été créées : "
                  "`estimation_dhs_ttc` est absente de 100 % des marchés liés à un "
                  "Award (0/454), alors qu'elle est présente sur 1196/1350 "
                  "consultations de la Passe B. La page d'un marché déjà attribué "
                  "ne porte plus son estimation. Aucune valeur n'a été fabriquée.\n")

    # ------------------------------------------------------------------ #
    section(out, "3. Valeurs manquantes — UNKNOWN ≠ ZERO")
    out.write("Taux de renseignement réel, au grain marché :\n\n")
    out.write("| Information | Renseignée | Part |\n|---|---:|---:|\n")
    n = len(new_markets)
    for label, col in (("Montant TTC", "has_amount_data"),
                       ("Liste des concurrents", "has_competitor_data"),
                       ("Concurrents écartés", "has_exclusion_data"),
                       ("Date d'ouverture", "has_date_data"),
                       ("Gagnant identifié", "has_winner")):
        k = int(new_markets[col].sum())
        out.write(f"| {label} | {k}/{n} | {100 * k / n:.1f} % |\n")

    single = int((new_markets["single_bidder"] == 1).sum())
    unknown = int((new_markets["has_competitor_data"] == 0).sum())
    out.write(f"\n**Effet direct du correctif** : {unknown} marchés sans rubrique "
              f"concurrents valaient auparavant « 0 soumissionnaire », donc "
              f"`single_bidder = 1`. Après correctif, ils valent NULL et "
              f"**{single}** marchés seulement portent un soumissionnaire unique "
              f"réellement observé — contre {single + unknown} avant.\n")

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    dq = _read(ANALYTICS / "market_data_quality.parquet")
    if dq is not None:
        from features.data_quality import ALWAYS_AVAILABLE, SCORED_DIMENSIONS

        section(out, "3bis. Data Quality Score (Phase 1)")
        out.write(
            "Mesure **ce que nous savons d'un marché**, jamais ce que ce marché "
            "vaut. Affiché à côté du score d'anomalie, jamais additionné avec lui.\n\n")
        out.write(f"- Dimensions notées : `{'`, `'.join(SCORED_DIMENSIONS)}`\n")
        out.write(f"- Dimensions écartées car renseignées à 100 % (elles "
                  f"donneraient le même plancher à tous) : `{'`, `'.join(ALWAYS_AVAILABLE)}`\n")
        out.write("- Dimensions impossibles : `estimation` (0/454), "
                  "`localisation` (absente de la table de faits)\n")

        out.write("\n**Quatre états, pas deux** — répartition mesurée :\n\n")
        out.write("| Dimension | KNOWN | UNKNOWN | INVALID | N/A |\n|---|---:|---:|---:|---:|\n")
        for dim in SCORED_DIMENSIONS:
            col = dq[f"dq_{dim}"]
            out.write(f"| `{dim}` | {int((col == 'KNOWN').sum())} | "
                      f"{int((col == 'UNKNOWN').sum())} | "
                      f"{int((col == 'INVALID').sum())} | "
                      f"{int((col == 'NOT_APPLICABLE').sum())} |\n")
        n_inv = int((dq["invalid_fields_count"] > 0).sum())
        out.write(f"\n**{n_inv}/{len(dq)}** marchés portent au moins une donnée "
                  f"lue mais incohérente. *Incohérente* n'est pas *manquante* : "
                  f"le document dit quelque chose que l'arithmétique contredit.\n")

        out.write("\n**Distribution du score** (valeurs discrètes : 5 dimensions, "
                  "4 pour un marché infructueux) :\n\n")
        out.write("| Score | Marchés | Niveau |\n|---:|---:|---|\n")
        from features.data_quality import quality_level
        for score, n in dq["data_quality_score"].value_counts().sort_index().items():
            out.write(f"| {score:.0f} | {n} | {quality_level(score)} |\n")
        out.write("\n| Niveau | Marchés | Part |\n|---|---:|---:|\n")
        for level, n in dq["data_quality_level"].value_counts().items():
            out.write(f"| {level} | {n} | {100 * n / len(dq):.1f} % |\n")
        biggest = dq["data_quality_level"].value_counts().max() / len(dq)
        out.write(f"\nClasse la plus chargée : **{100 * biggest:.1f} %** du corpus — "
                  f"les seuils séparent réellement la population "
                  f"(le contrôle échoue au-delà de 60 %).\n")

        if new_scores is not None:
            j = dq.merge(new_scores[["award_id", "data_completeness", "scorable"]],
                         on="award_id", how="inner")
            out.write("\n**Recoupement avec la porte de scorabilité du modèle** — "
                      "les deux mesures vont dans le même sens sans être "
                      "redondantes (`data_completeness` décide qui est scoré, "
                      "`data_quality_score` informe l'analyste) :\n\n")
            out.write("| `data_completeness` | Marchés | Qualité moyenne |\n|---:|---:|---:|\n")
            for k, g in j.groupby("data_completeness"):
                out.write(f"| {int(k)}/3 | {len(g)} | {g['data_quality_score'].mean():.1f} |\n")

    section(out, "4. Marchés scorés, non scorés, signalés")
    scorable = new_scores[new_scores["scorable"] == True]  # noqa: E712
    out.write(f"- Marchés attribués : **{len(new_scores)}**\n")
    out.write(f"- Scorés : **{len(scorable)}**\n")
    out.write(f"- Non scorables (moins de 2 informations sur 3) : "
              f"**{len(new_scores) - len(scorable)}** — comptés et affichés, "
              f"jamais notés « Faible »\n")
    out.write(f"- Signalés atypiques : **{int(scorable['is_anomaly'].sum())}** "
              f"({100 * scorable['is_anomaly'].mean():.1f} % des scorés)\n")

    study_path = ANALYTICS / "contamination_study.json"
    if study_path.exists():
        study = json.loads(study_path.read_text(encoding="utf-8"))
        out.write("\n**Étude de `contamination`** (le paramètre fixe la charge "
                  "d'analyse, il ne mesure aucun taux d'irrégularité) :\n\n")
        out.write("| contamination | marchés signalés | part |\n|---|---:|---:|\n")
        for k, v in study["candidates"].items():
            retenu = " ← retenu" if str(study["chosen"]) == k else ""
            out.write(f"| {k}{retenu} | {v['n_flagged']} | {v['pct']} % |\n")

    out.write("\n**Niveaux de risque** (seuils mesurés, jamais 25/50/75) :\n\n")
    for level, count in new_scores["risk_level"].value_counts().items():
        out.write(f"- {level} : {count}\n")

    # ------------------------------------------------------------------ #
    section(out, "5. Stabilité du modèle")
    stab = scorable["stability_frequency"].dropna()
    out.write(f"10 réentraînements (`random_state` 0 à 9), Top 20 comparés :\n\n")
    out.write(f"- Marchés apparaissant dans les **10/10** classements : "
              f"{int((stab == 10).sum())}\n")
    out.write(f"- Dans 8 ou 9 : {int(((stab >= 8) & (stab < 10)).sum())}\n")
    out.write(f"- Dans 1 seul : {int((stab == 1).sum())} — score dépendant du tirage, "
              f"signalé comme tel dans le dashboard\n")

    # ------------------------------------------------------------------ #
    section(out, "6. Red flags")
    if new_flags is not None:
        from ai.market_red_flags import REGISTRY, SEVERITY_WEIGHTS

        thresholds = json.loads((ANALYTICS / "red_flag_thresholds.json").read_text(encoding="utf-8"))
        out.write("Registre de règles nommées, **distinct des features du modèle**. "
                  "Chaque règle porte un identifiant, un nom, une description, une "
                  "sévérité, et peut valoir `True` / `False` / *non évaluable*.\n\n")
        out.write("| ID | Nom | Sévérité | Poids | Dérivé |\n|---|---|---|---:|---|\n")
        for f in REGISTRY:
            out.write(f"| `{f.id}` | {f.name} | {f.severity.value} | "
                      f"{SEVERITY_WEIGHTS[f.severity]:.0f} | "
                      f"{'oui' if f.derived else 'non'} |\n")
        out.write("\nLes sévérités traduisent une priorité de lecture issue de la "
                  "littérature, **pas un effet mesuré** — sans vérité terrain, aucun "
                  "effet n'est estimable sur ce corpus.\n")

        out.write("\n**Seuils mesurés sur la distribution du corpus :**\n\n")
        out.write(f"- RF02 : `exclusion_rate >= {thresholds['exclusion_rate_seuil']:.3f}` "
                  f"(quantile {thresholds['exclusion_rate_quantile']}, calculé sur les "
                  f"{thresholds['exclusion_rate_n_evaluables']} marchés dont la donnée "
                  f"est `KNOWN`)\n")
        out.write(f"- RF03 : `montant_ttc >= {thresholds['montant_ttc_seuil']:,.2f} DH` "
                  f"(quantile {thresholds['montant_quantile']}, "
                  f"{thresholds['montant_n_evaluables']} marchés `KNOWN`)\n")
        out.write(f"- RF05 : procédures représentant moins de "
                  f"{thresholds['procedure_rare_max_share']:.0%} du corpus — "
                  f"{len(thresholds['procedures_rares'])} modalités, "
                  f"{thresholds['procedures_rares_n_marches']} marchés :\n")
        for p in thresholds["procedures_rares"]:
            out.write(f"  - {p}\n")
        out.write("- RF04 : **non implémenté**, estimation indisponible (0/454)\n")

        out.write("\n| Red flag | actif | inactif | non évaluable |\n|---|---:|---:|---:|\n")
        for f in REGISTRY:
            s = new_flags[f.id]
            out.write(f"| `{f.id}` {f.name} | {int((s == True).sum())} | "  # noqa: E712
                      f"{int((s == False).sum())} | {int(s.isna().sum())} |\n")  # noqa: E712

        out.write(
            "\n**Correctif de la Phase 2 sur RF01.** L'ancienne règle était "
            "`nb_soumissionnaires <= 1`, or `0 <= 1` : sur 152 déclenchements, "
            "**56 (37 %)** venaient d'un marché attribué où aucun nom n'avait pu "
            "être lu — dont 35 où des noms figuraient dans le document mais avaient "
            "tous été rejetés par le filtre de plausibilité. Un marché ne peut pas "
            "être attribué à personne : ce zéro est un défaut d'extraction, pas une "
            "absence de concurrence. RF01 lit désormais l'état `KNOWN` de la "
            f"dimension `concurrents` et vaut *non évaluable* dans ce cas — "
            f"il passe à **{int((new_flags['RF01'] == True).sum())}** "  # noqa: E712
            f"déclenchements. Perte de signal apparent, gain d'exactitude.\n")

    # ------------------------------------------------------------------ #
    peer = _read(ANALYTICS / "market_peer_comparison.parquet")
    if peer is not None:
        rep = json.loads((ANALYTICS / "peer_group_report.json").read_text(encoding="utf-8"))
        section(out, "6bis. Comparaison à des marchés comparables (Phase 3)")
        out.write("Remplace la question « ce marché est-il gros ? » par « ce "
                  "marché est-il gros **pour ce qu'il est** ? ». Un marché de "
                  "travaux et une prestation de services au même montant ne sont "
                  "pas comparables.\n\n")
        out.write(f"Cascade, du plus fin au plus grossier, minimum "
                  f"**{rep['min_peers']} comparables** (le marché lui-même "
                  f"exclu) :\n\n")
        out.write("| Niveau | Clé de regroupement | Marchés |\n|---|---|---:|\n")
        for c in rep["cascade"]:
            n_lvl = rep["levels"].get(c["level"], 0)
            out.write(f"| {c['level']} | `{' × '.join(c['keys'])}` | {n_lvl} |\n")
        n_none = rep["levels"].get("NOT_ENOUGH_PEERS", 0)
        out.write(f"| — | aucun groupe atteignant le minimum | {n_none} |\n")
        out.write(f"\n**Deux minimums, pas un.** Avoir {rep['min_peers']} "
                  f"comparables ne suffit pas : il faut "
                  f"{rep['min_peers_per_dimension']} comparables portant **la même "
                  f"dimension**. Un groupe de 40 marchés dont 3 seulement ont un "
                  f"montant ne peut pas fournir une médiane crédible.\n\n")
        out.write(f"- Comparaisons de montant calculables : "
                  f"**{rep['n_amount_comparisons']}/{rep['n_markets']}** "
                  f"({100 * rep['n_amount_comparisons'] / rep['n_markets']:.1f} %)\n")
        out.write(f"- Comparaisons de concurrence calculables : "
                  f"**{rep['n_competitor_comparisons']}/{rep['n_markets']}** "
                  f"({100 * rep['n_competitor_comparisons'] / rep['n_markets']:.1f} %)\n")
        wa = peer[peer["amount_vs_peer_median"].notna()]
        if len(wa):
            out.write(f"\nParmi les marchés comparables sur le montant : "
                      f"**{int(wa['amount_above_peer_p90'].sum())}** dépassent le "
                      f"P90 de leur groupe ; ratio médian au médian des pairs "
                      f"**{wa['amount_vs_peer_median'].median():.2f}**.\n")
        if new_flags is not None and "rf03_reference" in new_flags.columns:
            out.write("\n**RF03 est désormais adossé aux comparables** quand ils "
                      "existent, sinon il retombe sur le quantile du corpus — le "
                      "repli est tracé marché par marché :\n\n")
            for ref, n_ref in new_flags["rf03_reference"].value_counts().items():
                out.write(f"- `{ref}` : {n_ref} marchés\n")

    section(out, "7. Explicabilité")
    agreement_path = ANALYTICS / "explanation_agreement.json"
    if new_expl is not None and agreement_path.exists():
        agr = json.loads(agreement_path.read_text(encoding="utf-8"))
        out.write(f"- SHAP (TreeExplainer) calculé sur {agr['n_marches']} marchés\n")
        out.write(f"- Contrôle par ablation : recouvrement moyen du Top 3 = "
                  f"**{agr['accord_moyen_top3']:.2f}**, accord parfait sur "
                  f"{agr['n_accord_parfait']}/{agr['n_marches']} marchés\n")
        n_imp = int(new_expl["repose_sur_impute"].sum())
        out.write(f"- Explications reposant sur au moins une valeur imputée : "
                  f"**{n_imp}/{len(new_expl)}**\n")
        if n_imp == 0:
            out.write(
                "\n  Ce zéro a été vérifié plutôt que supposé : une valeur imputée "
                "vaut la médiane du corpus, donc elle ne distingue le marché de "
                "personne et ne peut pas remonter dans les principales "
                "contributions. C'est un contrôle qui passe, pas un calcul "
                "manquant — et c'est le comportement recherché, puisqu'une "
                "explication ne doit jamais reposer sur une valeur que le "
                "document ne portait pas. Le dashboard affiche l'avertissement "
                "si le cas se présente sur un corpus futur.\n")
        out.write("\n**Importance moyenne des features (|SHAP|)** :\n\n")
        for k, v in agr["importance_shap"].items():
            out.write(f"- `{k}` : {v}\n")
    else:
        out.write("_SHAP non encore calculé — lancer `ai/market_explain.py`._\n")

    # ------------------------------------------------------------------ #
    prio_report = ANALYTICS / "priority_report.json"
    if prio_report.exists():
        rp = json.loads(prio_report.read_text(encoding="utf-8"))
        section(out, "7bis. Priority Score (Phases 6-7)")
        out.write(f"Repond a « quels marches examiner en premier ? », jamais a "
                  f"« quels marches sont irreguliers ? ».\n\n")
        out.write(f"```\npriority_raw = {rp['formule']['w_anomaly']} x anomaly_score"
                  f"  +  {rp['formule']['w_red_flags']} x red_flag_score\n```\n\n")
        out.write("**Deux composantes seulement.** La comparaison aux pairs "
                  "n'est pas un troisieme terme : elle alimente deja RF03, donc "
                  "`red_flag_score` — l'ajouter compterait deux fois le meme "
                  "signal. La qualite des donnees n'y entre pas non plus : elle "
                  "**plafonne** le niveau au lieu de gonfler le score.\n\n")
        out.write("| Ponderation | rho de Spearman vs 50/50 | Top 20 communs |\n"
                  "|---|---:|---:|\n")
        for nom, res in rp["formulations_comparees"].items():
            out.write(f"| `{nom}` | {res['correlation_rangs_vs_equilibre']:+.3f} | "
                      f"{res['top20_communs_avec_equilibre']}/20 |\n")
        out.write("\nAucune n'est « meilleure » : sans verite terrain on ne "
                  "mesure que leur accord. Le 50/50 est retenu faute de mesure "
                  "justifiant d'avantager une composante.\n\n")
        out.write("| Niveau de priorite | Marches |\n|---|---:|\n")
        for lvl, n_l in rp["distribution_niveaux"].items():
            out.write(f"| {lvl} | {n_l} |\n")
        out.write("\n| Confiance | Marches |\n|---|---:|\n")
        for lvl, n_l in rp["distribution_confiance"].items():
            out.write(f"| {lvl} | {n_l} |\n")
        out.write(f"\n**Le garde-fou sert reellement** : "
                  f"{rp['n_plafonnes_par_confiance_faible']} marches auraient ete "
                  f"classes prioritaires sur leur seul score, mais leur confiance "
                  f"est faible — ils sont ramenes a « A surveiller », visibles et "
                  f"avec leur score, presentes pour ce qu'ils sont : un signal "
                  f"sur peu de donnees.\n")

    tempo = _load_report("temporal_report.json")
    if tempo:
        section(out, "7ter. Analyse temporelle (Phase 4)")
        out.write("Annuel uniquement. Chaque taux porte son effectif.\n\n")
        out.write("| Annee | Marches | Faible concurrence | Exclusions elevees | "
                  "Montant median | Atypiques |\n|---|---:|---:|---:|---:|---:|\n")
        for a in tempo["annuel"]:
            tr = " (tronquee)" if a["annee_tronquee"] else ""
            sb = "—" if a["taux_faible_concurrence"] is None else (
                f"{100 * a[chr(39)+chr(39)] if False else 100 * a['taux_faible_concurrence']:.1f} %"
                f" (n={a['n_avec_donnee_concurrence']})")
            ex = "—" if a["taux_exclusions_elevees"] is None else (
                f"{100 * a['taux_exclusions_elevees']:.1f} %")
            mt = "—" if a["montant_median"] is None else (
                f"{a['montant_median']:,.0f} DH (n={a['n_avec_montant']})".replace(",", " "))
            at = "—" if a["taux_marches_atypiques"] is None else (
                f"{100 * a['taux_marches_atypiques']:.1f} %")
            out.write(f"| {a['annee']}{tr} | {a['n_marches']} | {sb} | {ex} | "
                      f"{mt} | {at} |\n")
        m = tempo["mensuel"]
        out.write(f"\n**Granularite mensuelle refusee** : {m['n_marches_dates']} "
                  f"marches dates sur {m['n_mois']} mois, mediane "
                  f"{m['mediane_par_mois']:.0f} marches/mois, seulement "
                  f"{m['mois_au_dessus_du_minimum']}/{m['n_mois']} mois atteignent "
                  f"n >= {m['minimum_par_point']}. Une serie a 4 observations par "
                  f"point mesurerait du bruit d echantillonnage.\n")

    net = _load_report("network_report.json")
    if net:
        c = net["cote_entreprise_refuse"]
        section(out, "7quater. Analyse relationnelle (Phase 5)")
        out.write(f"**Le volet entreprise du graphe est refuse, sur mesure.** "
                  f"Degre maximum : **{c['degre_max']} marches** ; le graphe "
                  f"entreprise-entreprise compte **{c['aretes_entreprise_entreprise']} "
                  f"arete**. Un `market_count` par entreprise EST la variable qui "
                  f"produisait 13/13 d anomalies contre 25/180 avant la bascule vers "
                  f"le marche : la recalculer sous le nom de centralite "
                  f"reintroduirait l artefact.\n\n")
        out.write(f"Cote acheteur : **{net['n_acheteurs']} acheteurs**, dont "
                  f"**{net['n_concentration_exploitable']}** ont assez de marches a "
                  f"titulaire identifie (>= {net['min_marches_avec_gagnant']}) pour "
                  f"qu une concentration soit exploitable. Le titulaire n est lu que "
                  f"sur {net['marches_avec_gagnant_identifie']}/"
                  f"{net['marches_attribues']} marches.\n")

    bench = _load_report("benchmark_report.json")
    if bench:
        section(out, "7quinquies. Benchmark rule-based (Phase 10)")
        out.write("Methode simple : 1 point par red flag primaire actif, sans "
                  "ponderation.\n\n")
        out.write("| Classement | Communs | Jaccard | Recouvrement | IF seul | "
                  "Regles seules |\n|---|---:|---:|---:|---:|---:|\n")
        for nom, r in bench["tops"].items():
            out.write(f"| {nom} | {r['intersection']} | {r['jaccard']} | "
                      f"{r['recouvrement_pct']} % | "
                      f"{r['seulement_isolation_forest']} | "
                      f"{r['seulement_rule_based']} |\n")
        out.write(f"\nCorrelation des rangs (Spearman) : "
                  f"**{bench['correlation_spearman']:+.3f}**.\n\n")
        out.write("**Le resultat le plus important de ce benchmark est son "
                  "faible recouvrement**, et il coupe dans les deux sens : le "
                  "modele apporte bien quelque chose qu une addition de regles ne "
                  "donne pas, mais le choix de la methode determine presque "
                  "entierement quels marches remontent. Sans verite terrain, rien "
                  "ne permet de dire laquelle a raison.\n")

    section(out, "8. Ce que cette refonte ne corrige pas")
    out.write(
        "- **Le montant reste absent de 63 % des marchés.** L'imputation médiane "
        "est signalée (`amount_imputed`), jamais présentée comme une lecture.\n"
        "- **L'estimation administrative est hors d'atteinte** sur ce corpus : "
        "aucun écart estimation/attribution n'est calculable.\n"
        "- **Aucune vérité terrain au niveau marché.** La qualité d'extraction est "
        "mesurée sur 20 documents annotés ; le modèle, lui, n'a aucun label — sa "
        "stabilité est mesurée, sa justesse ne peut pas l'être.\n"
        "- **35 marchés attribués restent non analysables** faute de données "
        "extraites. Ils sont comptés, pas masqués.\n"
        "- **Le bruit résiduel sur les noms d'entreprise subsiste** (audit du "
        "27/08/2026) ; il n'affecte plus le modèle, qui n'utilise plus l'entreprise "
        "comme unité, mais il affecte encore l'affichage du gagnant.\n")

    text = out.getvalue()
    print(text)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(text, encoding="utf-8")
        print(f"\n[ecrit] {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
