# Méthode de travail — Guide de collaboration

Ce document explique comment on organise le travail sur ce dépôt à deux. L'objectif : ne jamais casser `main`, éviter les conflits, et garder un historique clair.

---

## 1. Structure des branches

```text
main       → version stable, toujours fonctionnelle
develop    → branche d'intégration, où on regroupe les features avant de les valider
feature/*  → une branche par module/fonctionnalité en cours de développement
```

Exemples de branches `feature/*` (voir README §39) :

```text
feature/scraping
feature/ocr
feature/extraction
feature/bigdata
feature/ai
feature/security
feature/dashboard
```

**Règle de base :** on ne travaille jamais directement sur `main` ni sur `develop`. On crée toujours une branche `feature/...` pour du nouveau travail.

---

## 2. Workflow au quotidien

### Avant de commencer une nouvelle tâche

```bash
git checkout develop
git pull
```

Ça évite de partir d'une version périmée et donc de futurs conflits.

### Créer sa branche de travail

```bash
git checkout -b feature/nom-de-la-tache
```

Utiliser un nom clair lié au module (`feature/ocr`, `feature/document-downloader`, etc.).

### Travailler, committer

```bash
git add <fichiers concernés>
git commit -m "feat: description claire du changement"
```

⚠️ Éviter `git add .` sans vérifier — toujours faire `git status` avant pour ne pas ajouter par erreur `.env` ou des fichiers temporaires.

### Convention des messages de commit (voir README §40)

```text
feat:     nouvelle fonctionnalité
fix:      correction de bug
docs:     documentation
data:     ajout/modif de schéma ou données
security: sécurité (auth, RBAC, etc.)
test:     tests
```

Exemple : `feat: add PMMP scraper for consultations`

### Pousser sa branche

```bash
git push -u origin feature/nom-de-la-tache
```

(Le `-u` seulement la première fois ; ensuite `git push` suffit.)

---

## 3. Fusionner son travail (Pull Request)

1. Sur GitHub, ouvrir une **Pull Request** : `feature/nom-de-la-tache` → `develop`.
2. L'autre personne relit rapidement (même juste survoler le diff).
3. Merge sur GitHub une fois que ça a l'air correct.
4. Nettoyer localement :

```bash
git checkout develop
git pull
git branch -d feature/nom-de-la-tache
```

**Pourquoi une PR et pas un merge direct ?** Ça permet à l'autre personne de voir ce qui a changé avant que ça arrive sur `develop`, et ça évite les surprises quand on récupère le code de l'autre.

---

## 4. Promotion vers `main`

`main` doit toujours rester stable et démontrable. On y fusionne `develop` seulement à la fin d'une étape validée (voir README §49 — Étape 1, 2, 3...), pas à chaque petit commit.

```bash
git checkout main
git pull
git merge develop
git push
```

---

## 5. En cas de conflit

Si `git pull` ou `git merge` signale un conflit :

1. Ne pas paniquer, ne pas faire `git checkout .` ou `git reset --hard` pour "faire disparaître" le problème — ça peut supprimer du travail.
2. Ouvrir les fichiers en conflit, chercher les marqueurs `<<<<<<<`, `=======`, `>>>>>>>`.
3. Choisir/fusionner manuellement le bon contenu, supprimer les marqueurs.
4. `git add <fichier résolu>` puis `git commit`.
5. En cas de doute, s'appeler ou se message avant de trancher.

---

## 6. Répartition du travail

Le projet est découpé en 5 modules (voir README §9) qui s'enchaînent plutôt qu'ils ne tournent en parallèle :

```text
Module 1 → Gestion documentaire
Module 2 → OCR & Extraction
Module 3 → Big Data
Module 4 → IA & Valorisation
Module 5 → Cybersécurité
```

En pratique, on avance souvent ensemble sur le même module (ex : une personne fait le scraper de métadonnées, l'autre le téléchargement des documents), avec chacun sa branche `feature/...`, fusionnées dans `develop` au fur et à mesure.

---

## 7. Règles importantes

- ❌ Ne jamais commit `.env` (contient les mots de passe/secrets) — seul `.env.example` va sur GitHub.
- ❌ Ne jamais push direct sur `main`.
- ❌ Ne jamais faire `git push --force` sans en parler à l'autre avant.
- ✅ Toujours `git pull` sur `develop` avant de démarrer une nouvelle branche.
- ✅ Commits petits et fréquents plutôt qu'un seul gros commit à la fin.
- ✅ Messages de commit clairs (voir §2).

---

Des questions ou un blocage git ? On regarde ensemble avant de forcer quoi que ce soit.
