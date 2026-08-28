"""
Documents deliberement exclus du pipeline OCR, avec leur raison.

Vit ici, et non dans scripts/run_ocr.py ou la constante est nee, pour deux
raisons : `scripts/` n'est pas un package importable, et surtout la liste
est desormais lue par DEUX consommateurs — le script d'OCR, qui saute ces
fichiers, et database/crud/documents.py, qui inscrit l'exclusion en base
(Document.ocr_status = EXCLUDED + ocr_excluded_reason). Une seule source de
verite, sinon les deux finiraient par diverger.

Module volontairement sans dependance (ni pytesseract, ni cv2, ni fitz) :
la couche database doit pouvoir l'importer sans tirer toute la pile OCR.

Diagnostic complet de chaque cas : docs/methodology.md Sec 1.2 et Sec 1.5.
Consequence sur le modele de donnees : data_dictionary.md Sec 3.5 — ces deux
references ont une Procurement collectable mais aucun Award exploitable.
"""

from __future__ import annotations

EXCLUDED_STEMS: dict[str, str] = {
    "65597f99d131db2a59fabcab9bb39929f9f1f9f1ff518a1ef60e0ccdb0bfcf78":
        "faux positif OSD confirme : page 2 rotee a 180 deg a tort, illisible, "
        "alors que le score document (64,7) passe le seuil grace a la page 1",
    "9d2a5e0783702e0198d5bdfe23c3212d72fa6501308724cbb85bf03d2b6d01e1":
        "page OCR reellement blanche (luminosite mesuree 254,96/255)",
}
