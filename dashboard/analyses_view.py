"""
Vues d'analyse transversale (Phases 4, 5, 10 — dashboard final, Phase 11).

Trois lectures qui ne portent pas sur un marche en particulier :
evolution annuelle, structure par acheteur, et comparaison du modele a une
methode simple. Plus les statistiques de feedback analyste (Phase 8).

Regle d'affichage commune a tout ce module : chaque chiffre est montre
AVEC son effectif, et chaque analyse refusee est montree comme refusee,
avec la mesure qui a motive le refus. Un onglet vide sans explication
laisserait croire a un oubli.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parent.parent
ANALYTICS = REPO / "data/processed/analytics"


def _load_json(nom: str) -> dict | None:
    p = ANALYTICS / nom
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _load_parquet(nom: str) -> pd.DataFrame | None:
    p = ANALYTICS / nom
    return pd.read_parquet(p) if p.exists() else None


# --------------------------------------------------------------------------- #
def render_temporal() -> None:
    st.subheader("Évolution annuelle")
    rep = _load_json("temporal_report.json")
    if rep is None:
        st.info("Analyse temporelle non calculée — lancer "
                "`ai/market_temporal_analysis.py`.")
        return

    yearly = pd.DataFrame(rep["annuel"])
    table = pd.DataFrame({
        "année": yearly["annee"].astype(int).astype(str)
                 + yearly["annee_tronquee"].map({True: " ⚠ tronquée", False: ""}),
        "marchés": yearly["n_marches"],
        "faible concurrence": yearly.apply(
            lambda r: "—" if pd.isna(r["taux_faible_concurrence"])
            else f"{100 * r['taux_faible_concurrence']:.1f} % (n={int(r['n_avec_donnee_concurrence'])})",
            axis=1),
        "exclusions élevées": yearly.apply(
            lambda r: "—" if pd.isna(r["taux_exclusions_elevees"])
            else f"{100 * r['taux_exclusions_elevees']:.1f} % (n={int(r['n_avec_donnee_exclusions'])})",
            axis=1),
        "montant médian": yearly.apply(
            lambda r: "—" if pd.isna(r["montant_median"])
            else f"{r['montant_median']:,.0f} DH (n={int(r['n_avec_montant'])})".replace(",", " "),
            axis=1),
        "marchés atypiques": yearly.apply(
            lambda r: "—" if pd.isna(r["taux_marches_atypiques"])
            else f"{100 * r['taux_marches_atypiques']:.1f} %", axis=1),
    })
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.caption(
        "**Chaque taux porte son effectif.** Un taux calculé sur 27 marchés et "
        "le même taux sur 73 ne se lisent pas pareil — c'est pourquoi le "
        "dénominateur est affiché partout plutôt que résumé.")

    tronquee = rep.get("annee_tronquee")
    st.warning(
        f"**{tronquee} est une année tronquée** (corpus arrêté en août). Ses "
        "totaux ne se comparent pas aux années pleines et elle est exclue de "
        "tout calcul d'évolution.")

    ruptures = rep.get("ruptures", {}).get("taux_faible_concurrence", [])
    if ruptures:
        st.markdown("**Évolution de la faible concurrence, années pleines :**")
        for r in ruptures:
            st.markdown(
                f"- {r['de']} → {r['a']} : {100 * r['valeur_avant']:.1f} % → "
                f"{100 * r['valeur_apres']:.1f} % (**{100 * r['ecart']:+.1f} pts**, "
                f"n={r['n_avant']} puis {r['n_apres']})")
        st.caption(
            "Aucun test statistique de rupture n'est appliqué : avec trois "
            "années pleines, aucun n'aurait de puissance. Écarts bruts et "
            "effectifs, rien de plus.")

    m = rep.get("mensuel", {})
    if m:
        st.error(
            f"**Analyse mensuelle refusée.** {m['n_marches_dates']} marchés datés "
            f"répartis sur {m['n_mois']} mois, médiane **{m['mediane_par_mois']:.0f} "
            f"marchés/mois** ; seulement {m['mois_au_dessus_du_minimum']} mois sur "
            f"{m['n_mois']} atteignent le minimum de {m['minimum_par_point']}. Une "
            "série à 4 observations par point mesurerait du bruit "
            "d'échantillonnage présenté comme une tendance.")


# --------------------------------------------------------------------------- #
def render_network() -> None:
    st.subheader("Structure relationnelle — par acheteur")
    rep = _load_json("network_report.json")
    reseau = _load_parquet("acheteur_network.parquet")
    if rep is None or reseau is None:
        st.info("Analyse relationnelle non calculée — lancer "
                "`ai/network_analysis.py`.")
        return

    cote = rep["cote_entreprise_refuse"]
    st.error(
        f"**Le volet entreprise du graphe n'existe pas, et c'est mesuré.** "
        f"Degré maximum : **{cote['degre_max']} marchés** — aucune entreprise "
        f"n'en atteint 3. Le graphe entreprise↔entreprise compte "
        f"**{cote['aretes_entreprise_entreprise']} arête**. Surtout, un "
        f"`market_count` par entreprise *est* la variable dont ce projet a "
        f"démontré qu'elle produisait 13/13 d'anomalies contre 25/180 : la "
        f"recalculer sous le nom de « centralité » réintroduirait l'artefact "
        f"que la bascule vers le marché a éliminé.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Acheteurs", rep["n_acheteurs"])
    c2.metric("Concentration exploitable", rep["n_concentration_exploitable"],
              help=f"Au moins {rep['min_marches_avec_gagnant']} marchés avec un "
                   f"titulaire identifié.")
    c3.metric("Marchés avec titulaire identifié",
              f"{rep['marches_avec_gagnant_identifie']}/{rep['marches_attribues']}")

    exploitables = reseau[reseau["concentration_exploitable"]]
    if len(exploitables):
        table = exploitables.nlargest(15, "indice_concentration_hhi")[[
            "acheteur_public", "n_marches", "n_marches_avec_gagnant",
            "n_titulaires_distincts", "part_du_premier_titulaire",
            "indice_concentration_hhi", "titulaire_le_plus_frequent"]].copy()
        table["part_du_premier_titulaire"] = table["part_du_premier_titulaire"].map(
            lambda v: "—" if pd.isna(v) else f"{100 * v:.0f} %")
        table["indice_concentration_hhi"] = table["indice_concentration_hhi"].round(3)
        st.dataframe(table, use_container_width=True, hide_index=True)

    st.warning(
        "**Une concentration élevée n'est pas une entente.** Elle a des causes "
        "ordinaires avant d'en avoir d'extraordinaires : marché local étroit, "
        "spécialité technique, faible nombre d'opérateurs qualifiés. C'est une "
        "structure à regarder, jamais un constat.")
    st.caption(
        "Le titulaire n'étant lu que sur une partie des marchés, une "
        "concentration calculée sur 2 marchés identifiés sur 12 ne mesure rien — "
        "d'où le seuil d'exploitabilité et l'affichage systématique des deux "
        "effectifs.")


# --------------------------------------------------------------------------- #
def render_benchmark() -> None:
    st.subheader("Isolation Forest face à une méthode simple")
    rep = _load_json("benchmark_report.json")
    if rep is None:
        st.info("Benchmark non calculé — lancer `ai/benchmark_rulebased.py`.")
        return

    st.markdown(
        "Méthode simple : **1 point par red flag primaire actif** (RF01, RF02, "
        "RF03, RF05), sans pondération. Volontairement plus fruste que le "
        "`red_flag_score` — une baseline doit rester une baseline.")

    tops = rep["tops"]
    table = pd.DataFrame([
        {"classement": nom.replace("top", "Top "),
         "marchés communs": r["intersection"],
         "Jaccard": r["jaccard"],
         "recouvrement": f"{r['recouvrement_pct']} %",
         "vus par IF seul": r["seulement_isolation_forest"],
         "vus par les règles seules": r["seulement_rule_based"],
         "ex æquo à la frontière": r["marches_ex_aequo_a_la_frontiere"]}
        for nom, r in tops.items()])
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.metric("Corrélation des rangs (Spearman)",
              f"{rep['correlation_spearman']:+.3f}")

    st.warning(
        f"**Les deux méthodes désignent des marchés largement différents** "
        f"(Jaccard {tops['top20']['jaccard']}, ρ = {rep['correlation_spearman']:+.3f}). "
        "C'est le résultat le plus important de ce benchmark, et il coupe dans "
        "les deux sens : le modèle apporte bien quelque chose qu'une addition de "
        "règles ne donne pas — mais le choix de la méthode détermine presque "
        "entièrement quels marchés remontent. Sans vérité terrain, **rien ne "
        "permet de dire laquelle a raison.**")

    st.caption(rep.get("avertissement", ""))
    st.caption(
        "Le score de règles ne prend que quelques valeurs distinctes : les ex "
        "æquo à la frontière d'un Top N sont départagés de façon déterministe "
        "mais arbitraire, et leur nombre est affiché pour que cette limite reste "
        "visible.")


# --------------------------------------------------------------------------- #
def render_feedback_stats(award_ids) -> None:
    st.subheader("Feedback analyste")
    from dashboard.feedback import RELEVANT, FALSE_POSITIVE, TO_REVIEW, review_stats

    stats = review_stats(award_ids)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Marchés", stats["total"])
    c2.metric("Examinés", stats["examines"])
    c3.metric("Pertinents", stats[RELEVANT.lower()])
    c4.metric("Faux positifs", stats[FALSE_POSITIVE.lower()])

    if stats["taux_faux_positifs"] is None:
        st.info(
            "**Aucun avis enregistré pour l'instant.** Le taux de faux positifs "
            "reste indéfini — il n'est pas affiché à 0 %, ce qui se lirait comme "
            "un résultat alors que rien n'a été évalué.")
    else:
        st.metric("Taux de faux positifs",
                  f"{100 * stats['taux_faux_positifs']:.0f} %",
                  help="Calculé sur les seuls marchés examinés, jamais sur la "
                       "population entière : diviser par le total ferait baisser "
                       "le taux à mesure que des marchés restent non examinés.")

    st.caption(
        f"{stats['non_examines']} marché(s) non examiné(s), "
        f"{stats[TO_REVIEW.lower()]} en suspens. Les avis sont enregistrés dans "
        "`data/reference/analyst_reviews.csv`, versionné — ils survivent aux "
        "rechargements de la base, contrairement à une colonne SQL.")
    st.warning(
        "**Ce feedback ne modifie ni le modèle, ni les seuils, ni les red "
        "flags.** Réentraîner sur quelques dizaines d'avis produirait un modèle "
        "qui apprend les préférences d'un annotateur — et détruirait la seule "
        "chose que ces avis pourront servir : un jeu d'évaluation indépendant du "
        "modèle qu'il évalue.")


# --------------------------------------------------------------------------- #
def render_analyses(df: pd.DataFrame) -> None:
    onglets = st.tabs(["📅 Évolution annuelle", "🔗 Structure par acheteur",
                       "⚖️ Benchmark", "🧑‍⚖️ Feedback analyste"])
    with onglets[0]:
        render_temporal()
    with onglets[1]:
        render_network()
    with onglets[2]:
        render_benchmark()
    with onglets[3]:
        render_feedback_stats(df["award_id"].tolist() if not df.empty else [])
