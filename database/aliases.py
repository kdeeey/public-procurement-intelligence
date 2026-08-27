"""
Lecture de la table de correspondance sigle -> raison sociale complete
(`data/reference/company_aliases.csv`, Issue 14, 27/08/2026).

Pourquoi ce module plutot qu'une colonne de plus dans `companies` : la
correspondance est une ANNOTATION HUMAINE, pas un produit du pipeline. Elle
ne doit pas etre effacee par le prochain `TRUNCATE + reload` — et il y en a
eu quatre dans la seule journee du 27/08/2026. Un fichier versionne survit
aux rechargements, une colonne non.

Le contrat central est `confirme_dans_le_document` :

  oui         le PDF source a ete OUVERT et le nom complet y a ete vu.
              Seul cas ou le dashboard presente la correspondance comme un
              fait.
  a_verifier  correspondance trouvee sur le web, document pas encore
              rouvert. Affichee comme une PISTE, jamais comme un fait.
  non         piege identifie : le sigle ressemble a une entreprise reelle
              mais ne la designe pas dans ce corpus. Voir TFC dans le CSV —
              le cas qui a motive ce module.

Cette distinction n'est pas de la prudence decorative. Rattacher un marche
a une entreprise reelle sur la seule foi d'une correspondance de nom, en
affichant un score de risque a cote, produit quelque chose qui se lit comme
une accusation. Le projet dit depuis le debut que le score oriente
l'analyse humaine et ne conclut jamais ; l'appliquer ici, c'est refuser de
transformer une homonymie en attribution.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

ALIASES_PATH = Path(__file__).resolve().parents[1] / "data/reference/company_aliases.csv"

CONFIRMED = "oui"
UNVERIFIED = "a_verifier"
REJECTED = "non"


@dataclass(frozen=True)
class Alias:
    normalized_name: str
    nom_complet: str
    # Nom de remplacement quand le libelle extrait est inutilisable comme
    # identite mais contient un nom lisible. Vide dans la quasi-totalite des
    # cas — voir corrections() et sa docstring pour la regle d'usage.
    nom_corrige: str
    ville: str
    source_url: str
    confirme: str
    verifie_le: str
    notes: str

    @property
    def is_confirmed(self) -> bool:
        return self.confirme == CONFIRMED

    @property
    def is_rejected(self) -> bool:
        return self.confirme == REJECTED

    def display(self) -> str | None:
        """Le libelle a afficher a cote du sigle, ou None s'il n'y a rien
        d'etabli. Une piste non confirmee reste marquee comme telle."""
        if self.is_rejected or not self.nom_complet:
            return None
        if self.is_confirmed:
            return self.nom_complet
        return f"{self.nom_complet} (à confirmer)"


def load_aliases(path: Path | None = None) -> dict[str, Alias]:
    """CSV -> {normalized_name: Alias}. Les lignes de commentaire `#` en
    tete du fichier portent le mode d'emploi et sont ignorees ici."""
    target = path or ALIASES_PATH
    if not target.exists():
        return {}

    with target.open(encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        out: dict[str, Alias] = {}
        for row in rows:
            key = (row.get("normalized_name") or "").strip()
            if not key:
                continue
            out[key] = Alias(
                normalized_name=key,
                nom_complet=(row.get("nom_complet") or "").strip(),
                nom_corrige=(row.get("nom_corrige") or "").strip(),
                ville=(row.get("ville") or "").strip(),
                source_url=(row.get("source_url") or "").strip(),
                confirme=(row.get("confirme_dans_le_document") or UNVERIFIED).strip(),
                verifie_le=(row.get("verifie_le") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
    return out


def coverage(normalized_names: list[str], aliases: dict[str, Alias] | None = None) -> dict:
    """Combien de noms de la table sont couverts, et a quel titre — sert au
    dashboard a annoncer l'etat d'avancement de l'annotation plutot que de
    laisser croire que les colonnes vides n'existent pas."""
    aliases = aliases if aliases is not None else load_aliases()
    known = [n for n in normalized_names if n in aliases]
    return {
        "total": len(normalized_names),
        "annotes": len(known),
        "confirmes": sum(1 for n in known if aliases[n].is_confirmed),
        "a_verifier": sum(1 for n in known if aliases[n].confirme == UNVERIFIED),
        "rejetes": sum(1 for n in known if aliases[n].is_rejected),
    }


def corrections(path: Path | None = None) -> dict[str, str]:
    """{nom extrait illisible: nom lisible de remplacement}.

    Sert le cas ou l'extraction produit un libelle inutilisable comme
    identite d'entreprise, mais qui CONTIENT litteralement un nom lisible.
    Exemple reel :

        "LOACFE DTENETEEMENT LA SOCIETE ECLANOUR SARL JUSTIFICATIONDUCHOIXDEL"
        -> "SOCIETE ECLANOUR SARL"

    Deux options existaient pour ce cas : rejeter la ligne (le marche
    apparait alors sans attributaire) ou conserver le nom lisible. La
    seconde a ete retenue — un marche attribue a un nom lisible vaut mieux
    qu'un marche sans attributaire, puisque l'information EXISTE dans le
    document.

    Regle d'usage, a ne pas relacher : la correction doit etre une
    SOUS-CHAINE litterale du texte source, jamais une reconstitution. On
    supprime du bruit autour d'un nom, on n'invente pas un nom. Et
    `Award.concurrent_retenu_brut` conserve de toute facon le texte
    integral, donc rien n'est perdu.
    """
    return {k: a.nom_corrige for k, a in load_aliases(path).items() if a.nom_corrige}
