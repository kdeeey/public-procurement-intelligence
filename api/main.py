"""
API FastAPI — Issue 13, expose les résultats déjà calculés (Issues 8-12)
pour que le futur dashboard (Issue 14) n'ait pas besoin d'un accès direct
à PostgreSQL ni aux fichiers Parquet.

Scope volontairement réduit, décision assumée pas un oubli (voir
bigdata/README.md, section "Sécurité — hors périmètre de ce prototype") :
lecture seule stricte (aucun POST/PUT/DELETE nulle part dans routes/),
sans authentification/JWT/RBAC/audit logs — prototype démonstratif de 15
jours, non déployé, pas multi-utilisateur. `api/auth/` et
`api/middleware/` restent vides, scaffoldés pour l'architecture cible
mais non implémentés ici.

    uvicorn api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes import awards, companies, stats
from api.schemas import RISK_DISCLAIMER

DESCRIPTION = f"""
API en lecture seule exposant les résultats du pipeline PMMP
(entreprises, marchés, scores de risque).

**{RISK_DISCLAIMER}**

Prototype démonstratif, non déployé, sans authentification —
voir `bigdata/README.md` ("Sécurité — hors périmètre de ce prototype")
pour la décision de scope.
"""

app = FastAPI(
    title="Public Procurement Intelligence API",
    description=DESCRIPTION,
    version="0.1.0",
)

app.include_router(companies.router)
app.include_router(awards.router)
app.include_router(stats.router)


@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "disclaimer": RISK_DISCLAIMER}
