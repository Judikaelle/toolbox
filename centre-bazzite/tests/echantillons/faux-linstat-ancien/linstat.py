"""Faux LinStat d'une version dont l'API a changé : `CATEGORIES` est là, mais `Scanner` n'existe pas
(l'analyse passerait par une autre fonction). Health Hub doit le refuser et se replier sur l'espace libre."""

CATEGORIES = [
    ("Jeux", (66, 133, 244), "pak vpk"),
    ("Autres", (150, 150, 150), ""),
]


def analyser(dossier):
    return {"dossier": dossier, "total": 0}
