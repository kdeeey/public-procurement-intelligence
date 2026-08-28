"""
Vue MARCHE du dashboard (refonte du 28/08/2026).

Module separe plutot qu'une reecriture de dashboard/app.py : l'etage
entreprise reste affiche tel quel, en descriptif, et cette vue devient
l'entree principale. Deux fichiers, deux responsabilites, aucun risque de
casser l'existant en deplacant du code qui marche.

SOURCE DES DONNEES : les parquet produits par ai/train_market_model.py,
ai/market_red_flags.py et ai/market_explain.py — pas PostgreSQL. Les scores
marche ne sont pas (encore) recharges en base ; les lire directement evite
d'inventer une table intermediaire pour une vue de demonstration. Le
chemin cible reste l'API (backlog Issue 14).

REGLE D'AFFICHAGE APPLIQUEE PARTOUT ICI
----------------------------------------
Rien de ce qui est affiche ne doit pouvoir se lire comme une accusation, et
rien d'impute ne doit pouvoir se lire comme une observation. Concretement :

  * un marche non scorable affiche "Donnees insuffisantes", jamais un
    score, jamais "Faible" ;
  * un montant impute est marque comme tel a cote de la valeur ;
  * un red flag non evaluable est affiche distinctement d'un red flag
    inactif ;
  * la stabilite du score est montree a cote du score lui-meme, parce
    qu'un score instable ne se lit pas comme un score stable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parent.parent
ANALYTICS = REPO / "data/processed/analytics"

SCORES_PATH = ANALYTICS / "market_anomaly_scores.parquet"
RED_FLAGS_PATH = ANALYTICS / "market_red_flags.parquet"
EXPLANATIONS_PATH = ANALYTICS / "market_explanations.parquet"
FEATURES_PATH = ANALYTICS / "market_features.parquet"
DATA_QUALITY_PATH = ANALYTICS / "market_data_quality.parquet"
PEER_PATH = ANALYTICS / "market_peer_comparison.parquet"
PRIORITY_PATH = ANALYTICS / "market_priority.parquet"
THRESHOLDS_PATH = ANALYTICS / "red_flag_thresholds.json"
CONTAMINATION_PATH = ANALYTICS / "contamination_study.json"

QUALITY_ICON = {"Excellent": "🟢", "Bon": "🟢", "Moyen": "🟡",
                "Faible": "🔴", "Non evaluable": "⚪"}

# Libelles des quatre etats de features/data_quality.py — le dashboard ne
# doit jamais afficher UNKNOWN et INVALID de la meme facon : ne pas savoir
# et savoir faux appellent des actions differentes de l'analyste.
STATE_DISPLAY = {
    "KNOWN": ("✓", "lu dans le document"),
    "UNKNOWN": ("✗", "absent du document"),
    "INVALID": ("⚠", "lu mais incohérent"),
    "NOT_APPLICABLE": ("–", "sans objet pour ce marché"),
}

PRIORITY_ICON = {"Tres prioritaire": "🔴", "Prioritaire": "🟠",
                 "A surveiller": "🟡", "Faible": "🟢",
                 "Donnees insuffisantes": "⚪"}

LEVEL_ORDER = ["Critique", "Eleve", "Modere", "Faible", "Non evaluable"]
LEVEL_ICON = {"Critique": "🔴", "Eleve": "🟠", "Modere": "🟡",
              "Faible": "🟢", "Non evaluable": "⚪"}

FLAG_ICON = {True: "🔴", False: "🟢", None: "⚪"}
FLAG_TEXT = {True: "actif", False: "inactif", None: "non evaluable"}


@st.cache_data(ttl=60)
def load_markets() -> pd.DataFrame:
    """Scores + red flags + features, joints au grain marche.

    Renvoie un DataFrame vide plutot que de lever si un parquet manque : la
    page doit pouvoir dire "relancez telle etape" au lieu de planter.
    """
    if not SCORES_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(SCORES_PATH)
    if RED_FLAGS_PATH.exists():
        flags = pd.read_parquet(RED_FLAGS_PATH)
        flag_cols = [c for c in flags.columns if c.startswith("RF")] + [
            "red_flag_count", "red_flags_evaluable", "red_flags_triggered",
            "red_flag_score", "explication"]
        df = df.merge(flags[["award_id"] + [c for c in flag_cols if c in flags.columns]],
                      on="award_id", how="left")
    if EXPLANATIONS_PATH.exists():
        expl = pd.read_parquet(EXPLANATIONS_PATH)
        df = df.merge(expl, on="award_id", how="left")
    if DATA_QUALITY_PATH.exists():
        df = df.merge(pd.read_parquet(DATA_QUALITY_PATH), on="award_id", how="left")
    if PEER_PATH.exists():
        df = df.merge(pd.read_parquet(PEER_PATH), on="award_id", how="left")
    if PRIORITY_PATH.exists():
        prio = pd.read_parquet(PRIORITY_PATH)[
            ["award_id", "priority_score", "priority_level", "confidence_level"]]
        df = df.merge(prio, on="award_id", how="left")
    return df


@st.cache_data(ttl=60)
def load_thresholds() -> dict:
    out = {}
    for path, key in ((THRESHOLDS_PATH, "red_flags"), (CONTAMINATION_PATH, "contamination")):
        if path.exists():
            out[key] = json.loads(path.read_text(encoding="utf-8"))
    return out


def _fmt_montant(value, imputed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "non extrait"
    txt = f"{float(value):,.2f} DH".replace(",", " ")
    return txt + (" (imputé)" if imputed else "")


def _winner(row) -> str:
    companies = row.get("companies")
    if companies is None or (hasattr(companies, "__len__") and len(companies) == 0):
        return "non identifié"
    return " + ".join(str(c) for c in companies)


# --------------------------------------------------------------------------- #
def render_market_list(df: pd.DataFrame) -> None:
    st.subheader("Marchés à examiner")

    if df.empty:
        st.info("Aucun résultat marché. Lancer `ai/train_market_model.py`, "
                "`ai/market_red_flags.py` puis `ai/market_explain.py`.")
        return

    scorables = df[df["scorable"] == True]  # noqa: E712
    non_scorables = df[df["scorable"] != True]  # noqa: E712

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Marchés attribués", len(df))
    c2.metric("Analysés par le modèle", len(scorables))
    c3.metric("Signalés atypiques", int(scorables["is_anomaly"].sum()),
              help="Nombre fixé par le paramètre `contamination` (10 %). "
                   "C'est une charge d'analyse, pas un taux d'irrégularité.")
    c4.metric("Données insuffisantes", len(non_scorables),
              help="Moins de 2 informations extraites sur 3 (montant, "
                   "concurrents, exclusions). Non scorés — jamais 'Faible'.",
              delta_color="off")
    if "data_quality_score" in df.columns:
        moyenne = df["data_quality_score"].mean()
        c5.metric("Qualité moyenne des données",
                  "—" if pd.isna(moyenne) else f"{moyenne:.0f}/100",
                  help="Part des informations réellement lues dans le document, "
                       "sur 5 dimensions (montant, concurrents, exclusions, date, "
                       "gagnant). Mesure ce que NOUS savons du marché, jamais ce "
                       "que le marché vaut.")

    st.caption(
        "**Le nombre de marchés signalés est un curseur, pas une mesure.** "
        "Il fixe combien de dossiers un analyste examinera en priorité ; le "
        "faire varier change la longueur de la liste, jamais l'ordre.")

    f1, f2, f3 = st.columns([2, 2, 2])
    query = f1.text_input("Filtrer par référence, acheteur ou objet",
                          placeholder="ex : 2026, COMMUNE, travaux…")
    niveaux = f2.multiselect("Niveau", LEVEL_ORDER, default=["Critique", "Eleve", "Modere"])
    tri = f3.selectbox("Trier par", ["Score décroissant", "Stabilité puis score",
                                     "Nombre de red flags"])

    shown = df[df["risk_level"].isin(niveaux)].copy()
    if query:
        mask = pd.Series(False, index=shown.index)
        for col in ("reference", "acheteur_public", "objet"):
            if col in shown.columns:
                mask |= shown[col].astype(str).str.contains(query, case=False, na=False)
        shown = shown[mask]

    if tri == "Score décroissant":
        shown = shown.sort_values("anomaly_score_0_100", ascending=False, na_position="last")
    elif tri == "Stabilité puis score":
        shown = shown.sort_values(["stability_frequency", "anomaly_score_0_100"],
                                  ascending=False, na_position="last")
    else:
        shown = shown.sort_values(["red_flag_count", "anomaly_score_0_100"],
                                  ascending=False, na_position="last")

    table = pd.DataFrame({
        "réf.": shown["reference"].fillna("—"),
        "objet": shown["objet"].fillna("—").astype(str).str.slice(0, 70),
        "acheteur": shown["acheteur_public"].fillna("—").astype(str).str.slice(0, 45),
        "gagnant": shown.apply(_winner, axis=1),
        "montant TTC": shown["montant_ttc"],
        "procédure": shown["mode_passation"].fillna("—").astype(str).str.slice(0, 30),
        "score": shown["anomaly_score_0_100"],
        "niveau": shown["risk_level"].map(lambda v: f"{LEVEL_ICON.get(v, '')} {v}"),
        "stabilité": shown["stability_frequency"].map(
            lambda v: "—" if pd.isna(v) else f"{int(v)}/10"),
        "red flags": shown.apply(
            lambda r: "—" if pd.isna(r.get("red_flags_evaluable"))
            else f"{int(r['red_flag_count'])}/{int(r['red_flags_evaluable'])}", axis=1),
        "priorité": shown.apply(
            lambda r: "—" if pd.isna(r.get("priority_score"))
            else f"{PRIORITY_ICON.get(r.get('priority_level'), '')} "
                 f"{r['priority_score']:.0f}", axis=1),
        "confiance": shown.get(
            "confidence_level", pd.Series(index=shown.index, dtype="object")),
        "data quality": shown.apply(
            lambda r: "—" if pd.isna(r.get("data_quality_score"))
            else f"{QUALITY_ICON.get(r.get('data_quality_level'), '')} "
                 f"{r['data_quality_score']:.0f}/100", axis=1),
        "champs invalides": shown.get(
            "invalid_fields_count", pd.Series(index=shown.index, dtype="float")).map(
            lambda v: "" if pd.isna(v) or v == 0 else f"⚠ {int(v)}"),
    })
    st.dataframe(table, use_container_width=True, height=520, hide_index=True,
                 column_config={
                     "montant TTC": st.column_config.NumberColumn(format="%.2f"),
                     "score": st.column_config.NumberColumn(format="%.1f"),
                 })

    st.caption(
        f"**{len(shown)} marché(s) affiché(s)** sur {len(df)} attribués. "
        "*stabilité* = nombre de fois sur 10 réentraînements où ce marché "
        "apparaît dans le Top 20 ; *red flags* = actifs / évaluables ; "
        "*qualité* = informations réellement extraites sur 3.")


# --------------------------------------------------------------------------- #
def render_market_detail(df: pd.DataFrame) -> None:
    st.subheader("Détail d'un marché")
    if df.empty:
        st.info("Aucun résultat marché disponible.")
        return

    ordered = df.sort_values("anomaly_score_0_100", ascending=False, na_position="last")
    labels = ordered.apply(
        lambda r: f"[{r['risk_level']}] {r['reference'] or '(sans référence)'} — "
                  f"{str(r['acheteur_public'])[:40]}", axis=1).tolist()
    choice = st.selectbox("Marché", labels, index=0)
    row = ordered.iloc[labels.index(choice)]

    st.markdown(f"### Marché {row['reference'] or '(sans référence)'}")
    st.caption(f"{row['objet'] or '—'}")

    c1, c2, c3, c4 = st.columns(4)
    if row["scorable"] != True:  # noqa: E712
        c1.metric("Score d'anomalie", "—")
        c2.metric("Niveau", "⚪ Non évaluable")
        st.error(
            "**Données insuffisantes pour analyser ce marché.** Moins de deux "
            "informations sur trois (montant, concurrents, exclusions) ont pu "
            "être extraites du document. Ce marché n'est pas scoré — l'absence "
            "de score est une information, pas un score faible. Le signaler "
            "comme atypique reviendrait à sanctionner un défaut de notre propre "
            "chaîne d'extraction.")
    else:
        c1.metric("Score d'anomalie", f"{row['anomaly_score_0_100']:.1f}")
        c2.metric("Niveau", f"{LEVEL_ICON.get(row['risk_level'],'')} {row['risk_level']}")
        stab = row.get("stability_frequency")
        c3.metric("Stabilité", "—" if pd.isna(stab) else f"{int(stab)}/10",
                  help="Nombre de réentraînements (sur 10 graines aléatoires) "
                       "où ce marché ressort dans le Top 20.")
        c4.metric("Red flags actifs",
                  "—" if pd.isna(row.get("red_flags_evaluable"))
                  else f"{int(row['red_flag_count'])}/{int(row['red_flags_evaluable'])}")

        if not pd.isna(stab) and stab <= 3:
            st.warning(
                f"**Score sensible à la configuration du modèle** — ce marché "
                f"n'apparaît que dans {int(stab)} des 10 classements. À "
                f"interpréter avec prudence : un autre tirage aléatoire ne le "
                f"remonterait probablement pas.")
        elif not pd.isna(stab) and stab >= 8:
            st.success(f"**Stabilité élevée** — ce marché ressort dans "
                       f"{int(stab)}/10 des réentraînements.")

    # --- fiche marche ---------------------------------------------------- #
    st.markdown("#### Le marché")
    left, right = st.columns(2)
    left.markdown(
        f"- **Acheteur** : {row['acheteur_public'] or '—'}\n"
        f"- **Gagnant** : {_winner(row)}\n"
        f"- **Procédure** : {row['mode_passation'] or '—'}\n"
        f"- **Secteur** : {row['categorie_principale'] or '—'}")
    right.markdown(
        f"- **Montant TTC** : {_fmt_montant(row['montant_ttc'])}\n"
        f"- **Montant HT** : {_fmt_montant(row['montant_ht'])}\n"
        f"- **Soumissionnaires** : "
        f"{'non extrait' if pd.isna(row['nb_soumissionnaires']) else int(row['nb_soumissionnaires'])}\n"
        f"- **Concurrents écartés** : "
        f"{'non extrait' if pd.isna(row['nb_concurrents_ecartes']) else int(row['nb_concurrents_ecartes'])}")

    # --- comparaison aux marches comparables (Phase 3) ------------------- #
    st.markdown("#### Comparaison à des marchés comparables")
    niveau = row.get("peer_group_level")
    if niveau is None or (isinstance(niveau, float) and pd.isna(niveau)):
        st.info("Comparaison non calculée — lancer `ai/market_peer_analysis.py`.")
    elif niveau == "NOT_ENOUGH_PEERS":
        st.warning(
            "**Pas assez de marchés comparables** dans le corpus pour situer "
            "celui-ci. Aucune référence n'est inventée pour combler ce vide.")
    else:
        st.caption(f"Groupe de comparaison : `{row.get('peer_group_key')}` "
                   f"(niveau *{niveau}*, {int(row['n_peers'])} marchés comparables, "
                   f"ce marché exclu).")
        ratio = row.get("amount_vs_peer_median")
        if ratio is not None and not pd.isna(ratio):
            pct = row.get("amount_percentile_peer")
            ecart = (ratio - 1) * 100
            st.markdown(
                f"**Montant : {ecart:+.0f} % par rapport à la médiane de ses "
                f"{int(row['n_peers_amount'])} comparables** — plus élevé que "
                f"{pct:.0%} d'entre eux.")
        else:
            st.markdown("**Montant** : non comparable — soit le montant n'a pas "
                        "été extrait, soit moins de 10 comparables en portent un "
                        "(63 % du corpus n'a pas de montant).")
        rc = row.get("competitors_vs_peer_median")
        if rc is not None and not pd.isna(rc):
            st.markdown(
                f"**Nombre de soumissionnaires : {(rc - 1) * 100:+.0f} %** par "
                f"rapport à la médiane de ses "
                f"{int(row['n_peers_competitors'])} comparables.")

    # --- red flags -------------------------------------------------------- #
    st.markdown("#### Red flags")
    # Le registre de ai/market_red_flags.py est la source unique des noms,
    # descriptions et severites — le dashboard ne redefinit aucun libelle,
    # sinon les deux finiraient par diverger.
    from ai.market_red_flags import REGISTRY

    if not any(f.id in df.columns for f in REGISTRY):
        st.info("Red flags non calculés — lancer `ai/market_red_flags.py`.")
    else:
        if pd.notna(row.get("red_flag_score")):
            st.markdown(f"**Score red flags : {row['red_flag_score']:.0f}/100** "
                        f"— {int(row['red_flag_count'])} règle(s) active(s) sur "
                        f"{int(row['red_flags_evaluable'])} évaluable(s), "
                        f"pondérées par sévérité.")
        for f in REGISTRY:
            value = row.get(f.id)
            value = None if value is None or pd.isna(value) else bool(value)
            derive = " *(dérivé)*" if f.derived else ""
            st.markdown(f"{FLAG_ICON[value]} **{f.id} — {f.name}**{derive} "
                        f"*({FLAG_TEXT[value]}, sévérité {f.severity.value})*")
            if value is True:
                st.caption(f"　{f.description}")
        st.caption(
            "**RF04 (écart estimation / attribution) n'existe pas** : "
            "l'estimation administrative est absente de 100 % des marchés "
            "attribués du corpus. Aucune valeur n'est fabriquée pour la "
            "remplacer.")
        st.caption(
            "Les sévérités traduisent une priorité de lecture issue de la "
            "littérature, **pas un effet mesuré** : sans vérité terrain, aucun "
            "effet ne peut être estimé sur ce corpus.")
        st.caption(str(row.get("explication") or ""))

    # --- qualite des donnees ---------------------------------------------- #
    st.markdown("#### Qualité des données")
    if pd.notna(row.get("data_quality_score")):
        niveau = row.get("data_quality_level")
        st.markdown(f"**Data Quality : {row['data_quality_score']:.0f}/100 — "
                    f"{QUALITY_ICON.get(niveau, '')} {niveau}**")
        st.caption(
            f"{int(row['known_fields_count'])} information(s) lue(s), "
            f"{int(row['missing_fields_count'])} absente(s), "
            f"{int(row['invalid_fields_count'])} incohérente(s), "
            f"{int(row['not_applicable_fields_count'])} sans objet — "
            f"score calculé sur {int(row['evaluable_fields_count'])} dimension(s). "
            "Ce score mesure ce que nous savons de ce marché, pas ce qu'il vaut.")
        if int(row["invalid_fields_count"]) > 0:
            st.warning(
                "**Au moins une information a été lue mais est incohérente.** "
                "Une donnée incohérente n'est pas une donnée manquante : le "
                "document dit quelque chose que l'arithmétique contredit "
                "(par exemple plus de concurrents écartés que de "
                "soumissionnaires, ou un marché attribué sans aucun "
                "soumissionnaire lisible). À vérifier sur le PV source avant "
                "toute interprétation.")

    checks = [
        ("Montant", row.get("dq_montant")),
        ("Concurrents", row.get("dq_concurrents")),
        ("Exclusions", row.get("dq_exclusions")),
        ("Date d'ouverture", row.get("dq_date")),
        ("Gagnant", row.get("dq_gagnant")),
    ]
    lines = []
    for label, state in checks:
        if state is None or (isinstance(state, float) and pd.isna(state)):
            continue
        icone, texte = STATE_DISPLAY.get(str(state), ("?", str(state)))
        lines.append(f"{icone} **{label}** — {texte}")
    if row.get("extraction_warning"):
        lines.append("⚠ Extraction ayant produit des avertissements")
    else:
        lines.append("✓ Aucun avertissement d'extraction")
    st.markdown("  \n".join(lines))
    if row.get("extraction_warning"):
        st.warning(
            "**Données issues d'une extraction comportant des avertissements.** "
            "Le score reste affiché, mais il repose sur un texte dont la "
            "segmentation en lots ou le nettoyage a signalé une incertitude.")

    # --- explication du modele -------------------------------------------- #
    st.markdown("#### Explication du modèle (SHAP)")
    if pd.isna(row.get("explication_modele")):
        st.info("Explications non calculées — lancer `ai/market_explain.py`.")
    else:
        st.info(str(row["explication_modele"]))
        try:
            noms = json.loads(row["shap_top_features"])
            valeurs = json.loads(row["shap_top_values"])
            st.bar_chart(pd.DataFrame({"contribution": valeurs}, index=noms))
        except (TypeError, ValueError, KeyError):
            pass
        accord = row.get("accord_shap_ablation")
        if accord is not None and not pd.isna(accord):
            if accord < 1.0:
                st.warning(
                    f"**Les deux méthodes d'explication divergent partiellement** "
                    f"(recouvrement {accord:.0%} sur le Top 3). SHAP lit la "
                    f"structure des arbres, l'ablation ne mesure que la réponse "
                    f"du modèle. Lire le document avant de commenter ce marché.")
            else:
                st.success("SHAP et le contrôle par ablation désignent les mêmes "
                           "facteurs principaux.")
        if row.get("repose_sur_impute"):
            st.warning(
                "**Cette explication repose au moins en partie sur une valeur "
                "imputée**, c'est-à-dire remplacée par la médiane du corpus faute "
                "d'avoir été lue dans le document. Ce n'est pas une observation.")

    st.caption(
        "SHAP explique la sortie du **modèle**, pas le monde : il indique en quoi "
        "ce marché se distingue des autres du corpus, jamais qu'il serait "
        "irrégulier. Sur un Isolation Forest, la grandeur expliquée est une "
        "profondeur d'isolement — ce n'est pas une probabilité.")
