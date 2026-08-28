"""
Couche FEATURES — lectures derivees du corpus, hors modele.

Distincte de `bigdata/spark/jobs/` (qui construit les tables de features a
partir de PostgreSQL, avec Spark) et de `ai/` (qui entraine et explique) :
ce paquet contient des lectures pures, en pandas, sans dependance Spark ni
sklearn, testables isolement.

Premier module : `data_quality` — ce que nous savons d'un marche, jamais ce
que ce marche vaut.
"""
