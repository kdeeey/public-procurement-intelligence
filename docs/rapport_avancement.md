# Cahier des charges & état d'avancement

**Projet** : Exploitation des marchés publics — Chaîne Big Data & IA
**Type** : Prototype académique — 15 jours
**Équipe** : 2 étudiantes — IA & Big Data
**Date** : 17/08/2026
**Source des données** : [marchespublics.gov.ma](https://www.marchespublics.gov.ma) (PMMP)

> Document préparé pour validation de l'approche par l'encadrante, avant le début de l'implémentation.

---

## 0. Résumé

Avant d'écrire la moindre ligne de scraper, nous avons passé plusieurs jours à explorer manuellement le site réel du Portail Marocain des Marchés Publics (PMMP), vérifier les conditions légales de collecte, et rassembler plus de 25 documents réels (consultations, procès-verbaux, résultats définitifs) auprès de 15+ acheteurs publics différents.

Ce document résume la démarche suivie, les sources de données confirmées, le modèle de données qui en résulte, et les points sur lesquels nous souhaitons votre avis avant de commencer l'implémentation du pipeline.

---

## 1. Objectif du projet

Construire un prototype de chaîne Big Data et IA capable de collecter automatiquement des informations publiques sur les marchés publics marocains, d'en extraire le contenu (OCR/NLP), de le structurer, et de produire des indicateurs de risque explicables destinés à assister — jamais remplacer — l'analyse humaine.

> **Principe directeur** : le système ne qualifie jamais une entreprise de frauduleuse. Il produit un score et des facteurs explicatifs destinés à orienter une investigation humaine (human-in-the-loop).

---

## 2. Démarche suivie

Plutôt que de partir des hypothèses de structure de données définies au départ, nous avons choisi de valider chaque hypothèse contre le site réel avant de coder quoi que ce soit :

1. **Exploration manuelle du site** — navigation réelle des pages de recherche, de détail, et des différents types d'annonces, pour identifier les champs et sources réellement disponibles.
2. **Vérification légale** — contrôle de `robots.txt` (inexistant), des conditions d'utilisation (prérequis techniques uniquement) et des mentions légales (lien non fonctionnel). En l'absence de politique explicite, nous appliquons nos propres règles de scraping éthique (débit limité, aucun contournement d'authentification, données publiques uniquement).
3. **Collecte d'un échantillon de validation** — plus de 25 documents réels sauvegardés à la main avec valeurs attendues notées, pour servir de vérité terrain à l'évaluation de l'OCR et de l'extraction.
4. **Rédaction d'un dictionnaire de données** — uniquement une fois l'échantillon jugé suffisant, pour éviter de figer un modèle basé sur des suppositions.

---

## 3. Sources de données confirmées

Le site distingue en réalité trois sources complémentaires, toutes rattachées à une même référence de marché — plus riche que l'hypothèse de départ d'une source unique.

| Source | Contenu | Rôle |
|---|---|---|
| **Consultations** | Métadonnées du marché en HTML : référence, objet, acheteur, montant estimé, dates, procédure. Aucun OCR nécessaire. | Base — infos du marché |
| **Extraits de PV** *(prioritaire)* | Liste tous les concurrents et leurs montants, pas seulement le gagnant. | Source la plus riche pour l'analyse de concurrence |
| **Résultats définitifs** *(secours)* | Gagnant et montant retenu uniquement. | Utilisée quand aucun PV n'est disponible |

### Champs confirmés — Consultations
```text
reference, objet, acheteur_public, mode_passation, categorie_principale,
estimation_dhs_ttc, caution_provisoire, qualifications, allotissement,
date_limite_remise_plis, lieu_execution, date_mise_ligne
```

### Champs confirmés — PV / Résultats
```text
concurrent_retenu, montant_offre_retenue, liste_concurrents, montant_par_concurrent,
statut_attribution, justification_choix, delai_execution, date_achevement_commission
```

> **Limitation confirmée** : `ICE` et `RC` des entreprises gagnantes ne sont pas publiés sur le portail (vérifié sur l'ensemble de l'échantillon). Le regroupement par entreprise reposera donc sur le nom (avec normalisation), et le référentiel fiscal restera nécessairement synthétique — cohérent avec la limite déjà anticipée dans le cahier des charges initial.

---

## 4. Ce qui a été fait

| Chantier | Détail | Statut |
|---|---|---|
| Dépôt & workflow Git | Branches main/develop/feature, guide de contribution | ✅ Fait |
| Exploration du site réel | 3 sources confirmées, champs réels validés | ✅ Fait |
| Vérification légale | robots.txt, CGU, mentions légales | ✅ Fait |
| Échantillon de validation | 25+ documents réels, 15+ acheteurs | ✅ Fait |
| Dictionnaire de données | Modèles Procurement / Award / Company / Document | ✅ Fait |
| Environnement technique | Docker Compose, requirements.txt, structure des modules | ✅ Fait |
| Découpage en tâches | Backlog de 15 issues, calé sur le planning | ✅ Fait |
| Spiders (scraping) | Consultations + PV/Résultats | ⏳ À faire |
| Pipeline OCR & extraction | — | ⏳ À faire |

---

## 5. Points à valider avec vous

1. Prioriser le **PV** plutôt que le **Résultat définitif** comme source principale d'attribution (le PV contient un sur-ensemble des données : tous les concurrents, pas seulement le gagnant) — cette priorité vous semble-t-elle pertinente ?
2. Le scraper ne remplira jamais le formulaire d'identification demandé pour certains téléchargements de dossier (identité + acceptation de conditions requises) — nous marquons simplement ces documents comme non téléchargeables. Cette position est-elle raisonnable pour un projet académique ?
3. Le référentiel fiscal restera **synthétique**, faute d'accès aux données DGI — le mécanisme de croisement sera démontré, pas validé sur des données réelles. Ce périmètre correspond-il à ce qui est attendu ?
4. Pour rester réaliste sur 15 jours, l'échantillon de scraping sera filtré par plage de date et catégorie (ex : Travaux, période récente) plutôt que d'aspirer l'historique complet (134 000+ annonces) — ce périmètre vous paraît-il suffisant pour démontrer la chaîne complète ?

---

## 6. Prochaines étapes

Sous réserve de votre retour sur les points ci-dessus : développement des spiders de collecte (Consultations, PV/Résultats), puis pipeline OCR et extraction, en suivant le découpage détaillé dans le backlog du projet.

---

*Détails complets dans `docs/discovery_notes.md` et `docs/data_dictionary.md` du dépôt du projet.*
