"""
Systeme de design du dashboard PMMP — jetons CSS et composants reutilisables.

SOURCE VISUELLE
---------------
Porte le theme institutionnel clair defini par la maquette Claude Design
(`frontend/PMMP Dashboard.dc.html`), lui-meme un retheme de la couche de
jetons du design system Nocturne (`frontend/_ds/*/styles.css`) : seule la
couche `:root` est surchargee, les classes de composants (`.card`, `.tag`,
`.table`, `.btn`, `.input`, `.field`, `.elev-*`) sont reprises telles quelles.

CE MODULE NE CONTIENT AUCUNE DONNEE
------------------------------------
Il ne sait ni lire un parquet ni calculer un score. Il recoit des valeurs
deja calculees et les met en forme. Toute valeur affichee vient de
`dashboard/data_access.py`, qui lit les artefacts reels du pipeline.

REGLES D'AFFICHAGE APPLIQUEES ICI, PAS SEULEMENT DOCUMENTEES
--------------------------------------------------------------
  * `fmt_montant(None)` rend "Non extrait", jamais "0 DH" ni une cellule
    vide ambigue. Meme regle pour `fmt_int`, `fmt_score`, `fmt_texte`.
  * "Donnees insuffisantes" prend le role `none` : un gris neutre, une
    pastille CARREE (et non ronde) et un liste hors de l'echelle de
    gravite. Il ne doit ressembler ni au vert "Faible" ni au rouge.
  * Un red flag non evaluable est visuellement distinct d'un red flag
    inactif : trait gris pointille contre trait vert plein.
  * Le rouge et l'orange sont reserves aux signaux, jamais decoratifs.

VOCABULAIRE
-----------
Aucun libelle de ce module n'affirme une irregularite. "Atypique",
"signal", "priorite d'analyse", "donnees insuffisantes" — jamais "fraude",
"corruption", "entreprise suspecte". La maquette contenait deux libelles a
ne pas reprendre (elle nommait RF05 "Attribution repetee" et donnait a RF02
une severite elevee) : le registre reel de `ai/market_red_flags.py` fait
foi partout, la maquette n'est qu'un gabarit visuel.
"""

from __future__ import annotations

import base64
import re
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "frontend" / "assets"

# --------------------------------------------------------------------------- #
# Jetons — repris tels quels de la surcharge claire de la maquette
# --------------------------------------------------------------------------- #

TOKENS = {
    "bg": "#F8FAFC", "surface": "#FFFFFF", "text": "#0F172A",
    "accent": "#2563EB", "divider": "#E2E8F0",
    "n100": "#F8FAFC", "n200": "#F1F5F9", "n300": "#E2E8F0", "n400": "#CBD5E1",
    "n500": "#94A3B8", "n600": "#64748B", "n700": "#475569", "n800": "#334155",
    "n900": "#0F172A",
    "a100": "#EFF6FF", "a200": "#DBEAFE", "a300": "#BFDBFE", "a400": "#93C5FD",
    "a500": "#3B82F6", "a600": "#2563EB", "a700": "#1D4ED8", "a800": "#1E3A8A",
    "a900": "#172554",
}

# Semantique de risque. `none` vit dans la rampe neutre a dessein : ni
# rassurant, ni alarmant (voir dashboard.md Sec 2.3).
RISK = {
    "crit": {"base": "#DC2626", "text": "#B91C1C", "bg": "#FEF2F2", "line": "#FECACA"},
    "high": {"base": "#EA580C", "text": "#C2410C", "bg": "#FFF7ED", "line": "#FED7AA"},
    "mid": {"base": "#F59E0B", "text": "#B45309", "bg": "#FFFBEB", "line": "#FDE68A"},
    "low": {"base": "#16A34A", "text": "#15803D", "bg": "#F0FDF4", "line": "#BBF7D0"},
    "none": {"base": "#94A3B8", "text": "#475569", "bg": "#F1F5F9", "line": "#CBD5E1"},
}
WARN = {"bg": "#FEF3C7", "line": "#FCD34D", "text": "#92400E", "base": "#F59E0B"}

# Registre UNIQUE de roles couleur pour tous les badges de statut de la page
# (priorite, niveau de risque, etat de qualite KNOWN/INVALID/UNKNOWN, red
# flags actif/inactif/non evaluable). `render_status_badge` ne lit QUE ce
# dict : un role donne la meme paire (texte, fond) partout ou il est utilise,
# ce qui est la garantie demandee — pas une convention a respecter au coup
# par coup dans chaque appelant.
STATUS_ROLES = {**RISK, "warn": {"base": WARN["base"], "text": WARN["text"],
                                 "bg": WARN["bg"], "line": WARN["line"]}}

# --------------------------------------------------------------------------- #
# Libelles d'affichage
#
# Les valeurs stockees dans les parquet sont NON ACCENTUEES ("Tres
# prioritaire", "Donnees insuffisantes", "Non evaluable") — c'est la forme
# produite par ai/priority_score.py et ai/train_market_model.py. On ne
# touche pas a la donnee : on lui associe une graphie d'affichage ici. Le
# filtrage et les comparaisons se font toujours sur la valeur brute.
# --------------------------------------------------------------------------- #

PRIORITY_ORDER = ["Tres prioritaire", "Prioritaire", "A surveiller", "Faible",
                  "Donnees insuffisantes"]
PRIORITY_DISPLAY = {
    "Tres prioritaire": "Très prioritaire",
    "Prioritaire": "Prioritaire",
    "A surveiller": "À surveiller",
    "Faible": "Faible",
    "Donnees insuffisantes": "Données insuffisantes",
}
PRIORITY_ROLE = {
    "Tres prioritaire": "crit", "Prioritaire": "high", "A surveiller": "mid",
    "Faible": "low", "Donnees insuffisantes": "none",
}
PRIORITY_HELP = {
    "Tres prioritaire": "Signal fort : à examiner en premier.",
    "Prioritaire": "Signal net : à examiner.",
    "A surveiller": "Signal modéré : à revoir si le temps le permet.",
    "Faible": "Aucun écart notable au corpus.",
    "Donnees insuffisantes": ("Analyse non fiable : informations extraites "
                              "insuffisantes. Ce n'est pas un niveau faible."),
}

RISK_LEVEL_ORDER = ["Critique", "Eleve", "Modere", "Faible", "Non evaluable"]
RISK_LEVEL_DISPLAY = {
    "Critique": "Critique", "Eleve": "Élevé", "Modere": "Modéré",
    "Faible": "Faible", "Non evaluable": "Non évaluable",
}
RISK_LEVEL_ROLE = {
    "Critique": "crit", "Eleve": "high", "Modere": "mid", "Faible": "low",
    "Non evaluable": "none",
}

QUALITY_ORDER = ["Excellent", "Bon", "Moyen", "Faible", "Non evaluable"]
QUALITY_STYLE = {
    "Excellent": {"c": TOKENS["a800"], "bg": TOKENS["a100"], "b": TOKENS["a300"]},
    "Bon": {"c": TOKENS["a700"], "bg": TOKENS["a100"], "b": TOKENS["a200"]},
    "Moyen": {"c": RISK["mid"]["text"], "bg": RISK["mid"]["bg"], "b": RISK["mid"]["line"]},
    "Faible": {"c": WARN["text"], "bg": WARN["bg"], "b": WARN["line"]},
    "Non evaluable": {"c": RISK["none"]["text"], "bg": RISK["none"]["bg"],
                      "b": RISK["none"]["line"]},
}
QUALITY_DISPLAY = {k: ("Non évaluable" if k == "Non evaluable" else k)
                   for k in QUALITY_ORDER}

# Teintes de REMPLISSAGE des barres de qualite — distinctes des couleurs de
# texte de QUALITY_STYLE, qui sont des tons sombres pensés pour un fond
# clair et rendaient les barres illisibles. Reprend la palette de la
# maquette : rampe accent pour les trois premiers niveaux, ambre pour
# "Faible", neutre pour l'etat non evaluable.
QUALITY_BAR_COLOR = {
    "Excellent": TOKENS["a800"], "Bon": TOKENS["accent"],
    "Moyen": TOKENS["a400"], "Faible": RISK["mid"]["base"],
    "Non evaluable": RISK["none"]["base"],
}

CONFIDENCE_DISPLAY = {"Elevee": "Élevée", "Moyenne": "Moyenne",
                      "Faible": "Faible", "Insuffisante": "Insuffisante"}

# Les quatre etats de features/data_quality.py. Jamais fusionnes deux a
# deux : ne pas savoir (UNKNOWN) et savoir faux (INVALID) appellent des
# actions differentes de l'analyste.
#
# `role` pointe dans STATUS_ROLES : c'est la MEME cle de couleur que celle
# utilisee pour "Faible" (low), "A surveiller" (warn/mid) et "Donnees
# insuffisantes" (none) ailleurs dans le dashboard — Connu, Incoherent et
# Absent partagent donc strictement la meme teinte que leur equivalent
# semantique partout ou il apparait. UNKNOWN et NOT_APPLICABLE partagent le
# role neutre `none` (les deux sont "on ne juge pas ce marche sur cette
# dimension") ; `dashed` distingue NOT_APPLICABLE par une bordure, pas une
# nuance de gris differente qui romprait l'egalite de couleur exigee.
STATE_DISPLAY = {
    "KNOWN": {"label": "Connu", "desc": "lu dans le document", "mark": "✓",
              "role": "low", "dashed": False},
    "UNKNOWN": {"label": "Absent", "desc": "absent du document", "mark": "?",
                "role": "none", "dashed": False},
    "INVALID": {"label": "Incohérent", "desc": "lu mais incohérent", "mark": "!",
                "role": "warn", "dashed": False},
    "NOT_APPLICABLE": {"label": "Sans objet", "desc": "sans objet pour ce marché",
                       "mark": "–", "role": "none", "dashed": True},
}

DISCLAIMER = ("Les scores sont des signaux statistiques destinés à orienter une "
              "analyse humaine. Ils ne constituent ni une preuve ni une "
              "accusation de fraude.")

MISSING_TEXT = "Non extrait"
MISSING_ID = "Non identifié"
MISSING_GENERIC = "Non disponible"


# --------------------------------------------------------------------------- #
# Formatage — l'absence est toujours nommee, jamais rendue par un zero
# --------------------------------------------------------------------------- #

def is_missing(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


REFERENCE_CROSS_FIELDS = ("categorie_principale", "secteur")


def is_suspicious_reference(value, row=None) -> bool:
    """Detecte une valeur `reference` qui n'est manifestement pas une
    reference de marche mais un fragment d'OCR ayant fui depuis un autre
    champ (nom de colonne, mot isole, valeur tronquee).

    Le probleme est en amont, dans le pipeline d'extraction : ces valeurs
    sont deja presentes telles quelles dans market_features.parquet (ex.
    "Date", "une", "Fourniture", "QUI", "06/"). On ne corrige jamais le
    Parquet source ; cette regle ne fait que decider ce qui peut etre
    PRESENTE a l'ecran comme une reference credible. Trois signaux,
    combines en OU (n'importe lequel suffit) :

    1. Aucun chiffre dans la valeur — toutes les references reelles du
       corpus portent une annee ou un numero de sequence.
    2. Moins de 4 caracteres — trop court pour porter une structure de
       reference (numero + separateur + annee).
    3. Elle se termine par "/" ou "-" — fragment tronque a l'extraction.
    4. Elle correspond exactement (insensible a la casse) a la valeur
       d'un autre champ du meme enregistrement (secteur, categorie) — signe
       d'un decalage de colonne.

    LIMITE ASSUMEE : ces regles eliminent les cas grossiers observes dans
    le corpus mais ne peuvent pas prouver qu'une valeur qui les passe est
    une reference authentique (ex. un vrai sigle court avec un chiffre
    resterait accepte). Elles ne peuvent pas non plus recuperer la vraie
    reference quand elle a ete perdue a l'extraction.
    """
    if is_missing(value):
        return False
    s = str(value).strip()
    if not s:
        return False
    if not any(ch.isdigit() for ch in s):
        return True
    if len(s) < 4:
        return True
    if s[-1] in "/-":
        return True
    if row is not None:
        low = s.lower()
        for field in REFERENCE_CROSS_FIELDS:
            other = row.get(field) if hasattr(row, "get") else None
            if not is_missing(other) and str(other).strip().lower() == low:
                return True
    return False


def display_reference(value, row=None) -> str:
    """Valeur affichee pour la colonne Reference : la vraie reference, ou
    "Sans reference" — que la cause soit une absence reelle (deja geree en
    amont) ou une valeur suspecte detectee par `is_suspicious_reference`.
    Les deux cas rendent le meme libelle, avec le meme style italique gris :
    dans les deux cas, l'analyste n'a pas de reference exploitable."""
    if is_missing(value) or is_suspicious_reference(value, row):
        return "Sans référence"
    return str(value)


def fmt_montant(value, missing: str = MISSING_TEXT) -> str:
    """Montant en dirhams, ou le libelle d'absence. Jamais "0,00 DH" pour
    une valeur non extraite — un montant nul et un montant non lu sont deux
    informations differentes."""
    if is_missing(value):
        return missing
    return f"{float(value):,.2f} DH".replace(",", " ").replace(".", ",", 1) \
        .replace(" ", " ")


def fmt_int(value, missing: str = MISSING_TEXT) -> str:
    if is_missing(value):
        return missing
    return str(int(value))


def fmt_score(value, decimals: int = 1, missing: str = MISSING_GENERIC) -> str:
    if is_missing(value):
        return missing
    return f"{float(value):.{decimals}f}".replace(".", ",")


def fmt_texte(value, missing: str = MISSING_GENERIC) -> str:
    return missing if is_missing(value) else str(value)


def fmt_date(value, missing: str = MISSING_TEXT) -> str:
    if is_missing(value):
        return missing
    try:
        return pd.to_datetime(value).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)


def priority_display(value) -> str:
    return PRIORITY_DISPLAY.get(value, fmt_texte(value, MISSING_GENERIC))


def priority_role(value) -> str:
    return PRIORITY_ROLE.get(value, "none")


def risk_display(value) -> str:
    return RISK_LEVEL_DISPLAY.get(value, fmt_texte(value, MISSING_GENERIC))


def quality_display(value) -> str:
    return QUALITY_DISPLAY.get(value, fmt_texte(value, MISSING_GENERIC))


def confidence_display(value) -> str:
    return CONFIDENCE_DISPLAY.get(value, fmt_texte(value, MISSING_GENERIC))


def flag_state(value) -> str:
    """True / False / None (non evaluable) -> cle d'etat.

    None n'est JAMAIS replie sur False : dire "pas de red flag" sur un
    marche dont l'information n'a pas ete lue serait un faux negatif
    presente comme un controle passe (ai/market_red_flags.py)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "unknown"
    return "active" if bool(value) else "inactive"


# `role` pointe dans STATUS_ROLES, comme STATE_DISPLAY ci-dessus : le badge
# "Actif" partage la couleur de tout autre signal `crit` du dashboard,
# "Inactif" et "Non évaluable" partagent le neutre `none`. Le vert de `bar`
# pour "Inactif" est une nuance volontaire distincte du badge (voir
# `detail_panel.py::red_flag_rows_html`) : l'absence de signal reste
# indiquee positivement sur l'accent de la carte, jamais sur le badge de
# texte, qui reste neutre pour ne pas laisser croire a un etat "verifie bon".
FLAG_STYLE = {
    "active": {"label": "Actif", "role": "crit",
               "bar": RISK["crit"]["base"], "dashed": False},
    "inactive": {"label": "Inactif", "role": "none",
                 "bar": RISK["low"]["base"], "dashed": False},
    "unknown": {"label": "Non évaluable", "role": "none",
                "bar": TOKENS["n400"], "dashed": True},
}


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=8)
def asset_uri(name: str) -> str:
    """PNG local -> data URI, pour pouvoir l'inserer dans du HTML rendu par
    Streamlit (qui ne sert pas les fichiers du depot). Renvoie une chaine
    vide si l'asset manque : l'icone disparait, la page reste lisible."""
    path = ASSETS / name
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def market_icon(size: int = 14) -> str:
    uri = asset_uri("icone-marche.png")
    if not uri:
        return ""
    return (f'<img src="{uri}" alt="" style="width:{size}px;height:auto;'
            f'flex:0 0 {size}px;display:block" />')


@lru_cache(maxsize=4)
def market_icon_uri(size: int = 28) -> str:
    """L'icone de marche, reduite, en data URI — pour la colonne image du
    tableau.

    Reduite et non servie telle quelle : l'original pese 42 Ko en base64 et
    `st.column_config.ImageColumn` reemet la valeur DANS CHAQUE CELLULE.
    Sur 454 lignes cela ferait ~19 Mo transmis pour une vignette de 28 px.
    La miniature retombe a ~3 Ko, soit ~1,4 Mo au total. Renvoie une chaine
    vide si Pillow ou l'asset manquent : la colonne disparait alors
    proprement plutot que d'afficher une image cassee.
    """
    path = ASSETS / "icone-marche.png"
    if not path.exists():
        return ""
    try:
        import io

        from PIL import Image

        with Image.open(path) as im:
            thumb = im.convert("RGBA")
            thumb.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            thumb.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — une icone absente n'empeche pas de lire
        return ""


# --------------------------------------------------------------------------- #
# Feuille de style — injectee une seule fois par execution
# --------------------------------------------------------------------------- #

def _css() -> str:
    t, r = TOKENS, RISK
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
@import url('https://cdn.jsdelivr.net/npm/@phosphor-icons/web@2.1.1/src/regular/style.css');
:root {{
  --color-bg:{t['bg']}; --color-surface:{t['surface']}; --color-text:{t['text']};
  --color-accent:{t['accent']}; --color-divider:{t['divider']};
  --color-neutral-100:{t['n100']}; --color-neutral-200:{t['n200']};
  --color-neutral-300:{t['n300']}; --color-neutral-400:{t['n400']};
  --color-neutral-500:{t['n500']}; --color-neutral-600:{t['n600']};
  --color-neutral-700:{t['n700']}; --color-neutral-800:{t['n800']};
  --color-neutral-900:{t['n900']};
  --color-accent-100:{t['a100']}; --color-accent-200:{t['a200']};
  --color-accent-300:{t['a300']}; --color-accent-400:{t['a400']};
  --color-accent-500:{t['a500']}; --color-accent-600:{t['a600']};
  --color-accent-700:{t['a700']}; --color-accent-800:{t['a800']};
  --font-heading:"Inter",system-ui,sans-serif; --font-body:"Inter",system-ui,sans-serif;
  --space-1:2.8px; --space-2:5.6px; --space-3:8.4px; --space-4:11.2px;
  --space-6:16.8px; --space-8:22.4px;
  --radius-sm:4px; --radius-md:8px; --radius-lg:14px;
  --shadow-sm:0 0 0 1px {t['divider']};
  --shadow-md:0 0 0 1px {t['divider']},0 4px 16px rgba(15,23,42,0.06);
  --shadow-lg:0 0 0 1px {t['n400']},0 20px 50px rgba(15,23,42,0.14);
  --risk-crit:{r['crit']['base']}; --risk-crit-text:{r['crit']['text']};
  --risk-crit-bg:{r['crit']['bg']}; --risk-crit-line:{r['crit']['line']};
  --risk-high:{r['high']['base']}; --risk-high-text:{r['high']['text']};
  --risk-high-bg:{r['high']['bg']}; --risk-high-line:{r['high']['line']};
  --risk-mid:{r['mid']['base']}; --risk-mid-text:{r['mid']['text']};
  --risk-mid-bg:{r['mid']['bg']}; --risk-mid-line:{r['mid']['line']};
  --risk-low:{r['low']['base']}; --risk-low-text:{r['low']['text']};
  --risk-low-bg:{r['low']['bg']}; --risk-low-line:{r['low']['line']};
  --risk-none:{r['none']['base']}; --risk-none-text:{r['none']['text']};
  --risk-none-bg:{r['none']['bg']}; --risk-none-line:{r['none']['line']};
  --warn-bg:{WARN['bg']}; --warn-line:{WARN['line']}; --warn-text:{WARN['text']};
}}

/* ---- coque Streamlit ------------------------------------------------- */
.stApp {{ background:var(--color-bg); }}
html, body, [class*="css"] {{ font-family:var(--font-body); color:var(--color-text); }}
header[data-testid="stHeader"] {{ background:transparent; height:0; }}
[data-testid="stToolbar"] {{ right:8px; }}
[data-testid="stAppViewBlockContainer"],
.block-container {{ padding:28px 34px 64px; max-width:1400px; }}
[data-testid="stVerticalBlock"] {{ gap:var(--space-4); }}
h1,h2,h3,h4,h5,h6 {{ font-family:var(--font-heading); font-weight:500;
  line-height:1.12; letter-spacing:-0.015em; color:var(--color-text); }}
h3 {{ font-size:25px; }} h5 {{ font-size:16px; }}
h6 {{ font-size:13px; letter-spacing:0.08em; text-transform:uppercase; }}
.text-muted {{ color:var(--color-neutral-600); }}
a {{ color:var(--color-accent); text-decoration:none; }}
a:hover {{ color:var(--color-accent-800); text-decoration:underline; }}

/* ---- composants du design system ------------------------------------- */
.card {{ display:flex; flex-direction:column; gap:var(--space-2);
  padding:var(--space-3); border-radius:var(--radius-md);
  background:var(--color-surface); }}
.elev-sm {{ box-shadow:var(--shadow-sm); }}
.card-kicker {{ font-size:10px; letter-spacing:0.1em; text-transform:uppercase;
  color:var(--color-accent); }}
.card-meta {{ display:flex; align-items:center; gap:6px; font-size:11px;
  color:var(--color-neutral-600); }}
.tag {{ display:inline-flex; align-items:center; font-size:11px;
  letter-spacing:0.02em; padding:3px 10px; border-radius:6px; }}
.pmmp-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
.pmmp-table th {{ text-align:left; font-size:11px; letter-spacing:0.08em;
  text-transform:uppercase; color:var(--color-neutral-600);
  padding:var(--space-3) var(--space-2); border-bottom:1px solid var(--color-divider); }}
.pmmp-table td {{ padding:var(--space-3) var(--space-2);
  border-bottom:1px solid var(--color-neutral-200); vertical-align:top; }}

/* ---- barre laterale : nav du design ---------------------------------- */
[data-testid="stSidebar"] {{ background:var(--color-surface);
  box-shadow:var(--shadow-sm); width:252px !important; }}
[data-testid="stSidebar"] > div:first-child {{ padding-top:var(--space-6); }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap:2px; }}
[data-testid="stSidebar"] [role="radiogroup"] > label {{
  display:flex; align-items:center; gap:var(--space-3);
  padding:var(--space-3); margin:0; border-radius:var(--radius-md);
  font-family:var(--font-heading); font-size:13px; cursor:pointer;
  color:var(--color-neutral-800); background:transparent; transition:background .12s; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:hover {{
  background:var(--color-neutral-200); }}
/* Le cercle du radio : la nav n'en a pas. Il est rendu invisible et de
   taille nulle, PAS `display:none` — retirer l'element de l'arbre retirait
   aussi l'input, et le clic sur l'entree de navigation ne changeait plus
   de page. Trouve en cliquant dans le navigateur, pas en relisant le CSS. */
[data-testid="stSidebar"] [role="radiogroup"] > label > div:first-child {{
  width:0 !important; height:0 !important; min-width:0 !important;
  margin:0 !important; padding:0 !important; opacity:0; overflow:hidden; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {{
  background:var(--color-accent-100); color:var(--color-accent-800);
  font-weight:500; box-shadow:inset 2px 0 0 var(--color-accent); }}
[data-testid="stSidebar"] [role="radiogroup"] > label p {{ font-size:13px; }}
[data-testid="stSidebar"] [role="radiogroup"] > label::before {{
  font-family:"Phosphor"; font-size:17px; line-height:1;
  color:var(--color-neutral-500); flex:0 0 17px; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked)::before {{
  color:var(--color-accent); }}
/* Points de code releves dans la feuille Phosphor elle-meme, pas devines :
   squares-four e464, list-dashes e2f4, chart-line-up e156, chart-bar e150,
   upload-simple e4c0 — les memes icones que la maquette. */
[data-testid="stSidebar"] [role="radiogroup"] > label:nth-of-type(1)::before {{ content:"\\e464"; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:nth-of-type(2)::before {{ content:"\\e2f4"; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:nth-of-type(3)::before {{ content:"\\e156"; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:nth-of-type(4)::before {{ content:"\\e150"; }}
[data-testid="stSidebar"] [role="radiogroup"] > label:nth-of-type(5)::before {{ content:"\\e4c0"; }}
[data-testid="stSidebar"] .stButton button {{
  width:100%; justify-content:flex-start; border:none; background:transparent;
  color:var(--color-neutral-600); font-size:13px; font-weight:400;
  padding:var(--space-2) var(--space-3); border-radius:var(--radius-md); }}
[data-testid="stSidebar"] .stButton button:hover {{
  background:var(--color-neutral-200); color:var(--color-text); }}

/* ---- onglets (barre a 3 onglets de la Vue generale) ------------------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap:2px; padding:3px; background:var(--color-neutral-200);
  border-radius:999px; display:inline-flex; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] [data-baseweb="tab"] {{
  padding:var(--space-2) var(--space-6); border-radius:999px; height:auto;
  font-family:var(--font-heading); font-size:12.5px; font-weight:500;
  color:var(--color-neutral-600); background:transparent; }}
[data-testid="stTabs"] [aria-selected="true"] {{
  background:var(--color-surface) !important; color:var(--color-text) !important;
  box-shadow:var(--shadow-sm); }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {{ display:none; }}

/* ---- boutons, champs -------------------------------------------------- */
.stButton button {{ font-family:var(--font-heading); font-weight:500;
  font-size:13.5px; border-radius:var(--radius-md);
  border:1px solid var(--color-divider); background:var(--color-surface);
  color:var(--color-text); padding:6px 14px; }}
.stButton button:hover {{ border-color:var(--color-accent);
  color:var(--color-accent); background:var(--color-accent-100); }}
.stButton button[kind="primary"] {{ background:transparent;
  border-color:var(--color-accent); color:var(--color-accent); }}
.stButton button[kind="primary"]:hover {{ background:var(--color-accent-100); }}
[data-testid="stTextInput"] input, [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stTextArea"] textarea, [data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
  background:var(--color-neutral-100); border-color:var(--color-divider);
  border-radius:var(--radius-md); font-size:13.5px; }}
[data-testid="stWidgetLabel"] p {{ font-size:12px; color:var(--color-neutral-700); }}

/* ---- tableaux Streamlit ---------------------------------------------- */
[data-testid="stDataFrame"] {{ border-radius:var(--radius-md); overflow:hidden;
  box-shadow:var(--shadow-sm); }}
/* ---- cartes : voir dashboard/design_system.py::card() ------------------
   Streamlit 1.57 a cesse d'envelopper `st.container(border=True)` dans un
   `data-testid="stVerticalBlockBorderWrapper")` (verifie aux outils de
   developpement : ce testid n'existe plus nulle part dans le DOM rendu) —
   la bordure par defaut de Streamlit s'appliquait alors directement sur
   `stVerticalBlock`, via une classe generee (`st-emotion-cache-XXXXXX`) qui
   n'est pas un identifiant stable a cibler en CSS. `card()` desactive donc
   ce `border=True` et pose lui-meme, en PREMIER enfant de chaque carte, un
   marqueur invisible `.pmmp-card-marker` ; la regle ci-dessous stylise le
   `stVerticalBlock` qui le CONTIENT DIRECTEMENT en premier enfant — jamais
   un ancetre plus large qui contiendrait une carte plus loin dans l'arbre. */
div[data-testid="stVerticalBlock"]:has(
    > div[data-testid="stElementContainer"]:first-child .pmmp-card-marker) {{
  background:var(--color-surface); border:none;
  border-radius:var(--radius-md); box-shadow:var(--shadow-sm);
  padding:var(--space-6) var(--space-8); }}
/* Carte imbriquee dans une carte (si un jour introduite) : jamais de second
   cadre ni de second ombrage — une seule intensite d'ombre, sur la carte de
   premier niveau uniquement. */
div[data-testid="stVerticalBlock"]:has(
    > div[data-testid="stElementContainer"]:first-child .pmmp-card-marker)
  div[data-testid="stVerticalBlock"]:has(
    > div[data-testid="stElementContainer"]:first-child .pmmp-card-marker) {{
  box-shadow:none; padding:0; background:transparent; }}

/* ---- panneau lateral glissant : voir dashboard/detail_panel.py ------- */
div[data-testid="stDialog"] > div,
div[data-testid="stDialog"] div[role="dialog"] {{
  position:fixed !important; top:0 !important; right:0 !important;
  bottom:0 !important; left:auto !important; transform:none !important;
  width:min(680px,100vw) !important; max-width:min(680px,100vw) !important;
  height:100vh !important; max-height:100vh !important;
  border-radius:0 !important; box-shadow:var(--shadow-lg) !important;
  background:var(--color-surface) !important;
  animation:pmmp-slide-in .22s cubic-bezier(.22,.61,.36,1); }}
/* Le dialogue a TROIS enfants directs, releves dans le DOM et non supposes :
   1. le bandeau de titre, 2. le corps, 3. le bouton de fermeture.
   Les traiter uniformement faisait gonfler le titre a toute la hauteur ;
   viser `:last-child` visait le bouton, et le corps restait tronque sans
   defilement. Colonne flex : titre fige, corps extensible et seul a
   defiler, bouton hors flux. */
div[data-testid="stDialog"] div[role="dialog"] {{
  display:flex !important; flex-direction:column !important; }}
div[data-testid="stDialog"] div[role="dialog"] > div:nth-of-type(1) {{
  flex:0 0 auto !important;
  padding:var(--space-6) var(--space-8) 0 !important; }}
div[data-testid="stDialog"] div[role="dialog"] > div:nth-of-type(2) {{
  flex:1 1 auto !important; min-height:0 !important;
  max-height:none !important; overflow-y:auto !important;
  overflow-x:hidden !important;
  padding:var(--space-4) var(--space-8) var(--space-8) !important; }}
@keyframes pmmp-slide-in {{ from {{ transform:translateX(100%); }}
  to {{ transform:translateX(0); }} }}

/* ---- fragments reutilisables ----------------------------------------- */
.pmmp-kpi {{ background:var(--color-surface); box-shadow:var(--shadow-sm);
  border-radius:var(--radius-md); padding:var(--space-6); }}
.pmmp-kpi-label {{ font-size:11.5px; font-weight:500; color:var(--color-neutral-600);
  display:flex; align-items:center; justify-content:space-between; gap:var(--space-2); }}
.pmmp-kpi-value {{ font-family:var(--font-heading); font-size:28px; font-weight:500;
  letter-spacing:-0.03em; margin-top:var(--space-2); line-height:1.1;
  font-variant-numeric:tabular-nums; }}
.pmmp-kpi-sub {{ font-size:11.5px; color:var(--color-neutral-600); margin-top:2px; }}
.pmmp-note {{ padding:var(--space-4) var(--space-6); background:var(--color-surface);
  box-shadow:var(--shadow-sm); border-left:2px solid var(--color-accent);
  border-radius:0 var(--radius-md) var(--radius-md) 0; font-size:13px;
  color:var(--color-neutral-800); line-height:1.55; }}
.pmmp-warn {{ padding:var(--space-4) var(--space-6); background:var(--warn-bg);
  box-shadow:0 0 0 1px var(--warn-line); border-radius:var(--radius-md);
  font-size:12.5px; color:var(--warn-text); line-height:1.55; }}
.pmmp-empty {{ border:1px dashed var(--color-neutral-400); border-radius:var(--radius-md);
  padding:var(--space-8); background:var(--color-neutral-100);
  font-size:12.5px; color:var(--color-neutral-600); line-height:1.55; }}
.pmmp-caption {{ font-size:11.5px; color:var(--color-neutral-600); line-height:1.5; }}
.pmmp-panel {{ background:var(--color-surface); box-shadow:var(--shadow-sm);
  border-radius:var(--radius-md); padding:var(--space-6) var(--space-8); }}
</style>
"""


def inject_css() -> None:
    """Injecte la feuille de style, une fois par execution du script.

    Appelee depuis la coque (`pmmp_app.py`) avant tout rendu. Streamlit
    reconstruit le DOM a chaque re-run : la feuille doit donc etre reemise
    a chaque passage, elle ne peut pas etre memorisee en session.

    Deux nettoyages, chacun impose par un defaut constate a l'ecran :

    1. Les commentaires sont retires par une expression reguliere sur le
       bloc `/* ... */` ENTIER, pas ligne a ligne. Un premier essai
       filtrait les lignes commencant par `/*` : sur un commentaire de
       plusieurs lignes, seule la premiere disparaissait et les suivantes
       restaient dans la feuille, qui devenait invalide a partir de la —
       toutes les regles suivantes cessaient silencieusement de
       s'appliquer.
    2. Les lignes vides sont supprimees ensuite. `st.markdown` passe le
       contenu par un parseur Markdown avant de l'inserer, et une ligne
       vide y termine le bloc HTML : tout ce qui suivait s'affichait comme
       du TEXTE au milieu de la page, feuille de style comprise.
    """
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    lines = [ln for ln in css.splitlines() if ln.strip()]
    st.markdown("\n".join(lines), unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Composants
# --------------------------------------------------------------------------- #

def render_section_header(title: str, subtitle: str = "", right_html: str = "") -> None:
    right = (f'<div style="display:flex;align-items:center;gap:var(--space-2);'
             f'flex-wrap:wrap">{right_html}</div>') if right_html else ""
    sub = (f'<p class="text-muted" style="font-size:13.5px;margin:var(--space-2) 0 0;'
           f'max-width:680px">{subtitle}</p>') if subtitle else ""
    st.markdown(
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;'
        f'gap:var(--space-8);flex-wrap:wrap;margin-bottom:var(--space-6)">'
        f'<div><h3 style="margin:0">{title}</h3>{sub}</div>{right}</div>',
        unsafe_allow_html=True)


def info_icon(tooltip: str) -> str:
    """Icone (i) discrete portant une nuance en infobulle native (`title`),
    plutot que dans le texte visible. Meme convention partout : une carte ne
    montre qu'UN message clé, la nuance est a portee de survol."""
    if not tooltip:
        return ""
    return (f'<span title="{_esc(tooltip)}" style="color:{TOKENS["n400"]};'
            f'cursor:help"><i class="ph ph-info" style="font-size:13px"></i></span>')


def render_metric_card(label: str, value: str, sub: str = "", help_text: str = "",
                       muted: bool = False, size: int = 28) -> str:
    """Carte KPI. `muted` sert l'etat "Donnees insuffisantes" : la valeur
    reste lisible mais sort de la hierarchie visuelle des signaux."""
    color = TOKENS["n700"] if muted else TOKENS["text"]
    info = info_icon(help_text)
    return (f'<div class="pmmp-kpi"><div class="pmmp-kpi-label">'
            f'<span>{_esc(label)}</span>{info}</div>'
            f'<div class="pmmp-kpi-value" style="font-size:{size}px;color:{color}">'
            f'{_esc(value)}</div>'
            f'<div class="pmmp-kpi-sub">{_esc(sub)}</div></div>')


def render_metric_row(cards: list[str]) -> None:
    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(186px,1fr));'
        f'gap:var(--space-4)">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_status_badge(label: str, role: str | None = None, big: bool = False,
                        square_dot: bool = False, dot: bool = True,
                        text_color: str | None = None, bg_color: str | None = None,
                        base_color: str | None = None) -> str:
    """LE composant de badge de statut de tout le dashboard — priorité,
    niveau de risque, état de qualité des données, red flags, qualité de
    l'information. Un seul point de rendu garantit un même rayon d'arrondi,
    un même padding, une même taille de police et une même hauteur quel que
    soit le texte, pour tous ces cas : ne pas dupliquer un `<span class="tag"
    style=...>` ad hoc ailleurs.

    Deux façons de choisir la couleur, jamais mélangées :
      * `role` — pour tout ce qui a un sens dans `STATUS_ROLES` (priorité,
        risque, état de qualité, red flag). C'est le cas normal : la couleur
        est alors garantie identique partout où ce role est utilisé.
      * `text_color`/`bg_color` (+ `base_color` pour le point) — pour un
        palier qui n'est PAS un role de risque, comme les paliers "Excellent"
        / "Bon" de `QUALITY_STYLE` (bleu accent, pas rouge/orange/vert) : la
        FORME du badge reste identique, seule sa teinte est fournie par
        l'appelant plutôt que par `STATUS_ROLES`.

    `square_dot` distingue "Données insuffisantes" des niveaux de gravité :
    forme différente, pas seulement couleur.
    """
    k = STATUS_ROLES.get(role, STATUS_ROLES["none"])
    text_color = text_color or k["text"]
    bg_color = bg_color or k["bg"]
    base_color = base_color or k.get("base", text_color)
    pad = "5px 12px" if big else "3px 9px"
    size = "12.5px" if big else "11px"
    mark = (f'<span style="width:7px;height:7px;flex:0 0 7px;background:{base_color};'
            f'border-radius:{"1px" if square_dot else "50%"};'
            f'{"border:1px dashed " + TOKENS["n600"] + ";" if square_dot else ""}'
            f'"></span>') if dot else ""
    return (f'<span class="tag" style="gap:var(--space-2);padding:{pad};'
            f'border-radius:999px;font-size:{size};font-weight:500;color:{text_color};'
            f'background:{bg_color};white-space:nowrap">{mark}{_esc(label)}</span>')


def render_priority_badge(value, big: bool = False) -> str:
    role = priority_role(value)
    return render_status_badge(priority_display(value), role, big=big,
                               square_dot=(role == "none"))


def render_data_quality_badge(score, level, big: bool = False) -> str:
    """Badge qualite des donnees. Mesure ce que NOUS savons du marche,
    jamais ce que ce marche vaut — le libelle le rappelle en info-bulle.

    Passe par `render_status_badge` comme tout autre badge de statut, avec
    ses propres couleurs (`QUALITY_STYLE`, une rampe accent bleue — la
    qualité n'est pas un niveau de risque) fournies en `text_color`/
    `bg_color` plutôt qu'un `role` de `STATUS_ROLES`."""
    q = QUALITY_STYLE.get(level, QUALITY_STYLE["Non evaluable"])
    txt = (f"{fmt_score(score, 0, '—')} · {quality_display(level)}"
           if not is_missing(score) else quality_display(level))
    badge = render_status_badge(txt, big=big, dot=False,
                                text_color=q["c"], bg_color=q["bg"])
    return (f'<span title="Qualité de l\'information extraite du document, et '
            f'non qualité ou régularité du marché.">{badge}</span>')


def render_flag_chip(code: str, state: str, tip: str = "") -> str:
    """Petit badge RF01/RF02/… (colonne « Red flags » du tableau). Même
    composant que partout ailleurs ; le pointillé distingue seulement l'état
    non évaluable, sur la bordure — jamais une couleur différente pour un
    même role."""
    s = FLAG_STYLE[state]
    badge = render_status_badge(code, s["role"], dot=False)
    if s["dashed"]:
        return (f'<span title="{_esc(tip)}" style="display:inline-block;'
                f'outline:1px dashed {TOKENS["n400"]};outline-offset:1px;'
                f'border-radius:999px">{badge}</span>')
    return f'<span title="{_esc(tip)}">{badge}</span>'


def render_state_pill(state_key: str) -> str:
    s = STATE_DISPLAY.get(state_key, STATE_DISPLAY["UNKNOWN"])
    return render_status_badge(s["label"], s["role"], dot=False)


def render_stability_dots(value) -> str:
    """Stabilite : n reperes sur 10 remplis.

    Une valeur de 0 ne signifie PAS "instable" mais "jamais entre dans un
    Top 20" — c'est-a-dire hors de la zone que cette mesure observe (voir
    ai/priority_score.py). L'info-bulle le dit, la barre ne le suggere pas."""
    if is_missing(value):
        return ('<span class="pmmp-caption" title="Marché non scoré : la stabilité '
                'n\'est pas mesurée.">Non disponible</span>')
    n = int(value)
    tip = (f"Stabilité du signal : ce marché apparaît dans {n} des 10 classements "
           f"produits par 10 réentraînements. 0 signifie qu'il n'est jamais entré "
           f"dans un Top 20, pas qu'il est instable.")
    dots = "".join(
        f'<span style="width:5px;height:11px;border-radius:2px;flex:0 0 5px;'
        f'background:{TOKENS["accent"] if i < n else TOKENS["divider"]}"></span>'
        for i in range(10))
    return (f'<span title="{_esc(tip)}" style="display:inline-flex;gap:6px;'
            f'align-items:center"><span style="display:inline-flex;gap:2px;'
            f'align-items:center">{dots}</span>'
            f'<span style="font-size:12px;color:{TOKENS["n700"]}">{n}/10</span></span>')


def render_disclaimer(compact: bool = False) -> None:
    size = "12.5px" if compact else "13px"
    st.markdown(f'<div class="pmmp-note" style="font-size:{size}">{DISCLAIMER}</div>',
                unsafe_allow_html=True)


def render_empty_state(title: str, detail: str = "") -> None:
    body = f'<div style="margin-top:var(--space-2)">{_esc(detail)}</div>' if detail else ""
    st.markdown(f'<div class="pmmp-empty"><strong>{_esc(title)}</strong>{body}</div>',
                unsafe_allow_html=True)


def render_warning(text: str, title: str = "") -> None:
    head = (f'<div style="font-weight:500;margin-bottom:var(--space-1)">'
            f'{_esc(title)}</div>') if title else ""
    st.markdown(f'<div class="pmmp-warn">{head}{_esc(text)}</div>',
                unsafe_allow_html=True)


def render_caption(text: str) -> None:
    st.markdown(f'<div class="pmmp-caption">{text}</div>', unsafe_allow_html=True)


@contextmanager
def card(title: str = "", meta: str = "", help: str = ""):
    """Carte de surface contenant des WIDGETS (graphique, tableau, champ).

    Pourquoi un conteneur et non un `<div>` ouvert puis referme par deux
    appels a `st.markdown` : Streamlit rend chaque appel dans son propre
    bloc du DOM et referme les balises restees ouvertes. Une carte ecrite
    en deux morceaux se dessinait donc AVANT son contenu, qui debordait
    dessous — vu a l'ecran, pas deduit du code. `st.container(border=True)`
    produit un vrai conteneur, restyle en carte du design system par la
    regle `stVerticalBlockBorderWrapper` de la feuille.

    `help` porte une nuance methodologique de section (ex. limite du
    controle par ablation) en infobulle sur une icone (i) a cote du titre,
    plutot qu'en paragraphe repete sous chaque marche consulte.

    `border=False` : Streamlit 1.57 applique sa PROPRE bordure grise plate a
    `border=True`, sans l'ombre du design system — verifie aux outils de
    developpement, pas suppose. La carte pose donc son propre marqueur
    `.pmmp-card-marker` (voir la regle CSS `pmmp-card-marker` de `_css()`)
    et laisse la feuille de style dessiner fond, ombre et bordure.
    """
    box = st.container(border=False)
    with box:
        header = ""
        if title:
            header = (
                f'<div style="display:flex;align-items:baseline;'
                f'justify-content:space-between;gap:var(--space-4);'
                f'margin-bottom:var(--space-2)">'
                f'<h5 style="margin:0">{_esc(title)} {info_icon(help)}</h5>'
                f'<span class="card-meta" style="font-size:11.5px">'
                f'{_esc(meta)}</span></div>')
        # Marqueur + titre dans le MEME appel a st.markdown : deux appels
        # separes creeraient deux `stElementContainer`, et seul le premier
        # porte la regle CSS qui dessine la carte — le second (le titre)
        # se retrouverait hors du cadre stylise.
        st.markdown(
            f'<span class="pmmp-card-marker" '
            f'style="position:absolute;width:0;height:0;overflow:hidden">'
            f'</span>{header}', unsafe_allow_html=True)
        yield box


def _esc(value) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


esc = _esc
