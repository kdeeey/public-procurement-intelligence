"""
PMMP — dashboard d'aide a l'analyse des marches publics.

Coque et routage. Reprend la structure de la maquette Claude Design
(`frontend/PMMP Dashboard.dc.html`) : barre laterale de 252 px avec le
logo, cinq entrees de navigation, trois panneaux d'information en pied, et
la zone de contenu a droite.

    streamlit run dashboard/pmmp_app.py

CE QUE CETTE APPLICATION EST, ET CE QU'ELLE N'EST PAS
------------------------------------------------------
Elle repond a « quels marches un analyste devrait-il examiner en priorite,
et pourquoi ? ». Elle ne repond pas a « ce marche est-il frauduleux ? ».
Aucune page n'emploie le vocabulaire de la fraude ou de la corruption : le
systeme signale des caracteristiques, il ne conclut pas.

RAPPORT AUX AUTRES APPLICATIONS DU DEPOT
------------------------------------------
`dashboard/app.py` (demonstration a 7 onglets, incluant l'etage entreprise
deprecie et les analyses transversales) et `dashboard/validation_app.py`
(page de controle interne) restent en place, inchangees. Cette application
couvre le perimetre de la maquette : les cinq pages du brief produit, sans
la page entreprise ni la page benchmark, que `dashboard.md` Sec 12 exclut
explicitement de la conception.

TOUTES LES VALEURS VIENNENT DES ARTEFACTS REELS
-------------------------------------------------
Aucun compteur, aucun seuil et aucune option de filtre n'est ecrit en dur.
La maquette portait des valeurs de gabarit ; elles ont ete remplacees par
les valeurs calculees, y compris la ou elles different (la qualite moyenne
du corpus, notamment).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import streamlit as st  # noqa: E402

from dashboard import data_access as da  # noqa: E402
from dashboard import design_system as ds  # noqa: E402
from dashboard import view_anomalies, view_apercu, view_import  # noqa: E402
from dashboard import view_marches, view_xai  # noqa: E402

PAGES = {
    "Vue générale": view_apercu.render,
    "Marchés publics": view_marches.render,
    "Anomalies et priorités": view_anomalies.render,
    "XAI · Explicabilité": view_xai.render,
    "Importation": view_import.render,
}

st.set_page_config(page_title="PMMP — Analyse des marchés publics",
                   page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")


# --------------------------------------------------------------------------- #
# Panneaux d'information — chiffres relus, jamais recopies
# --------------------------------------------------------------------------- #

@st.dialog("Méthodologie", width="large")
def _panel_methodologie() -> None:
    kpis = da.corpus_kpis()
    bands = da.measured_risk_bands()
    study = da.load_json_report("contamination_study.json")
    registry_size = len(__import__(
        "dashboard.detail_panel", fromlist=["x"]).red_flag_registry())

    st.markdown("**Ce que mesure le score d'anomalie**")
    st.write(
        "Un modèle Isolation Forest isole les marchés dont la combinaison de "
        "variables est rare dans le corpus. Un score élevé signifie uniquement : "
        "ce marché présente des caractéristiques inhabituelles par rapport aux "
        "autres marchés du corpus."
        + (f" {kpis['scorables']} marchés sont scorés sur {kpis['total']} au corpus."
           if kpis["scorables"] and kpis["total"] else ""))

    st.markdown("**Red flags métier**")
    st.write(
        f"{registry_size} règles explicites sont évaluées indépendamment du modèle. "
        "Chaque règle peut être active, inactive, ou non évaluable lorsque "
        "l'information nécessaire n'a pas été lue dans le document. Une règle non "
        "évaluable n'est jamais repliée sur « inactive ».")

    st.markdown("**Niveaux de risque — bornes mesurées**")
    if bands:
        st.write(
            f"Faible jusqu'à {bands['faible_max']:.1f}, Modéré jusqu'à "
            f"{bands['modere_max']:.1f}, Élevé jusqu'à {bands['eleve_max']:.1f}, "
            f"Critique au-delà. La frontière du niveau Faible est celle que le "
            f"modèle choisit lui-même ; le sous-groupe signalé est ensuite coupé "
            f"en terciles mesurés de sa propre distribution. Jamais 25/50/75."
            .replace(".", ","))
    else:
        st.write("Bornes non calculables : aucun marché scoré n'est chargé.")

    st.markdown("**Priorité d'analyse**")
    st.write(
        "La priorité combine le score du modèle et le score de red flags, puis "
        "elle est plafonnée par le niveau de confiance. Un score élevé assis sur "
        "des données faibles n'est pas classé prioritaire."
        + (f" {len(da.capped_awards())} marché(s) sont concernés par ce plafond."
           if da.capped_awards() else ""))
    if study.get("chosen") is not None:
        st.write(
            f"Le nombre de marchés signalés est fixé par le paramètre de "
            f"priorisation du modèle (contamination = {study['chosen']}), comparé "
            f"à {len(study.get('candidates', {}))} valeurs avant d'être retenu. "
            f"C'est une capacité d'examen, pas un taux d'irrégularité.")

    st.markdown("**Absence de vérité terrain**")
    st.write(
        "Aucun marché du corpus n'est étiqueté. Aucun taux de détection, de "
        "précision ou de performance du modèle ne peut donc être calculé, et "
        "aucun n'est affiché.")


@st.dialog("Qualité des données", width="large")
def _panel_qualite() -> None:
    kpis = da.corpus_kpis()
    levels = da.counts_by_quality_level()
    rates = da.fill_rates()

    st.caption("Qualité de l'information extraite, et non qualité ou régularité "
               "du marché.")

    st.markdown("**Score global du corpus**")
    if kpis["qualite_moyenne"] is not None:
        repartition = " · ".join(
            f"{ds.quality_display(r['niveau'])} {int(r['n'])}"
            for _, r in levels.iterrows()) if not levels.empty else "—"
        st.write(f"{kpis['qualite_moyenne']:.1f} / 100 — niveau "
                 f"{ds.quality_display(kpis['qualite_niveau'])}. "
                 f"Répartition : {repartition}.".replace(".", ",", 1))
    else:
        st.write("Score non calculé : market_data_quality.parquet est absent.")

    st.markdown("**Cinq dimensions évaluées**")
    st.write("Montant, concurrents, exclusions, date d'ouverture, attributaire. "
             "Chaque dimension porte un état lu dans le document, jamais une "
             "valeur par défaut.")

    st.markdown("**Quatre états, jamais confondus**")
    for key in ("KNOWN", "UNKNOWN", "INVALID", "NOT_APPLICABLE"):
        s = ds.STATE_DISPLAY[key]
        st.write(f"- `{key}` — {s['desc']}.")
    st.write("Une donnée absente n'est jamais affichée comme un zéro.")

    st.markdown("**Complétude mesurée**")
    labels = {"montant_ttc": "Montant TTC", "reference": "Référence",
              "date_ouverture": "Date d'ouverture",
              "nb_soumissionnaires": "Nombre de soumissionnaires",
              "gagnant_attribues": "Attributaire (marchés attribués)"}
    for key, label in labels.items():
        r = rates.get(key)
        if r and r["pct"] is not None:
            st.write(f"- {label} : renseigné sur {r['n']}/{r['total']} "
                     f"({r['pct']:.0f} %), soit absent dans "
                     f"{100 - r['pct']:.0f} % des cas.")


@st.dialog("À propos · Limites", width="large")
def _panel_limites() -> None:
    kpis = da.corpus_kpis()
    st.markdown("**Nature du produit**")
    st.write("PMMP est un prototype académique d'aide à l'analyse, non déployé. "
             "Il hiérarchise des dossiers à examiner. Il ne conclut pas.")

    st.markdown("**Formulation obligatoire**")
    st.write(ds.DISCLAIMER)

    st.markdown("**Ce que le corpus ne permet pas**")
    st.write("- Pas de carte géographique : la localisation n'est pas exploitable "
             "dans la table analytique.")
    st.write("- Pas de graphe d'entreprises : le degré maximal observé est de deux "
             "marchés par entreprise, le graphe entreprise↔entreprise compte une "
             "seule arête.")
    st.write("- Pas d'écart au prix estimé : l'estimation administrative est "
             "absente de la totalité des marchés attribués.")
    st.write("- Pas d'indicateur de performance du modèle : sans vérité terrain, "
             "il serait inventé.")

    st.markdown("**Périodicité**")
    annees = kpis.get("annees")
    years = da.counts_by_year()
    tronquee = years[years["tronquee"]] if not years.empty else years
    periode = f"{annees[0]}–{annees[1]}" if annees else "non déterminée"
    st.write(f"Corpus de {ds.fmt_int(kpis['total'], '—')} marchés sur {periode}."
             + (f" L'année {int(tronquee.iloc[0]['annee'])} est incomplète et n'est "
                f"pas comparable aux années pleines." if not tronquee.empty else "")
             + " Tous les chiffres sont recalculés à chaque exécution du pipeline.")

    manquants = da.missing_sources()
    if manquants:
        st.markdown("**Sources analytiques absentes**")
        for name, label, cmd in manquants:
            st.write(f"- `{name}` ({label}) — relancer `{cmd}`")


# --------------------------------------------------------------------------- #
# Barre laterale
# --------------------------------------------------------------------------- #

def _sidebar() -> str:
    with st.sidebar:
        logo = ds.asset_uri("logo-dgi.png")
        if logo:
            st.markdown(
                f'<div style="padding:0 var(--space-3) var(--space-6)">'
                f'<img src="{logo}" alt="Direction Générale des Impôts" '
                f'style="width:96px;height:auto;display:block" /></div>',
                unsafe_allow_html=True)
        st.markdown(
            '<h6 style="margin:0 var(--space-3) var(--space-2);'
            'color:var(--color-neutral-500)">Navigation</h6>',
            unsafe_allow_html=True)

        page = st.radio("Navigation", list(PAGES), key="nav_page",
                        label_visibility="collapsed")

        st.markdown(
            f'<div style="border-top:1px solid {ds.TOKENS["divider"]};'
            f'margin:var(--space-6) 0 var(--space-3)"></div>',
            unsafe_allow_html=True)
        if st.button("Méthodologie", key="nav_methodo"):
            _panel_methodologie()
        if st.button("Qualité des données", key="nav_qualite"):
            _panel_qualite()
        if st.button("À propos · Limites", key="nav_limites"):
            _panel_limites()

        manquants = da.missing_sources()
        ok = not manquants
        color = ds.RISK["low"]["base"] if ok else ds.RISK["mid"]["base"]
        label = ("Corpus analytique chargé" if ok
                 else f"{len(manquants)} source(s) manquante(s)")
        detail = (f"{len(da.SOURCES)} tables analytiques · prototype académique"
                  if ok else "certaines pages afficheront un état vide")
        st.markdown(
            f'<div style="margin-top:var(--space-6);padding:0 var(--space-3)">'
            f'<div style="display:flex;align-items:center;gap:var(--space-2)">'
            f'<span style="width:7px;height:7px;border-radius:50%;'
            f'background:{color};flex:0 0 7px"></span>'
            f'<span style="font-size:11.5px;color:{ds.TOKENS["n700"]}">{label}</span>'
            f'</div><div style="font-size:10.5px;line-height:1.4;'
            f'color:{ds.TOKENS["n500"]};margin-top:3px">{detail}</div></div>',
            unsafe_allow_html=True)
    return page


# --------------------------------------------------------------------------- #
# Point d'entree
# --------------------------------------------------------------------------- #

def main() -> None:
    ds.inject_css()
    page = _sidebar()

    manquants = da.missing_sources()
    if len(manquants) == len(da.SOURCES):
        ds.render_section_header("PMMP — Analyse des marchés publics")
        ds.render_empty_state(
            "Aucune table analytique n'est disponible",
            "Le dossier data/processed/analytics/ ne contient aucun des parquet "
            "attendus. Rejouer la chaîne : "
            + " ; ".join(cmd for _, _, cmd in manquants[:3]) + " …")
        return

    PAGES[page]()


main()
