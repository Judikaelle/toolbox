"""Bilan hebdomadaire de Health Hub : les points de santé de la semaine, ce qui a changé, et la
notification du lundi (un clic dessus ouvre Health Hub). Remplace l'ancien script bazzite-health."""
import glob
from datetime import datetime, timedelta
from pathlib import Path

from . import commun, etat, inventaire

HEALTH_HUB = Path.home() / ".local" / "bin" / "health-hub"
FENETRE = timedelta(days=7)
DELAI_NOTIFICATION = 3600
PUCE = {"ok": "·", "attention": "!", "alerte": "!!"}
NIVEAU = {"echec": "alerte", "attention": "attention"}
LIGNES_MAX = 3


def _fichier(nom, dossier=None):
    return Path(dossier or commun.ETAT) / nom


def semaine(maintenant, *, sessions, lignes_maj_apps, changements_systeme):
    du = (maintenant - FENETRE).isoformat(timespec="seconds")
    au = maintenant.isoformat(timespec="seconds")
    dans = lambda date: bool(date) and du < date <= au
    # un outil vu à la fois par l'inventaire (brew) et par maj-apps ne compte qu'une fois
    connus = {c.get("id") for c in changements_systeme if c.get("categorie") == "outils"}
    changements = len(changements_systeme) + sum(
        1 for ligne in lignes_maj_apps if dans(ligne.get("date"))
        for c in ligne.get("changements") or [] if c.get("module") and c["module"] not in connus)
    recentes = [s for s in sessions if dans(s.get("debut"))]
    return {"du": du, "au": au, "changements": changements, "sessions": len(recentes),
            "echecs": sum(1 for s in recentes if s.get("succes") is False)}


def resultats_depuis_points(points_):
    return [(NIVEAU[p["gravite"]], p["titre"], p.get("detail") or "")
            for p in points_ if p.get("gravite") in NIVEAU and not p.get("en_sourdine")]


def rapport_json(resultats, quand):
    return {"date": quand,
            "points": [{"niveau": niveau, "titre": titre, "details": details}
                       for niveau, titre, details in resultats]}


def _jour(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso or "?")


def rediger(bilan):
    s = bilan.get("semaine") or {}
    lignes = [f"Bilan de la semaine — Health Hub — {_jour(bilan.get('date'))}", "=" * 58, ""]
    for p in bilan.get("points") or []:
        lignes.append(f"[{PUCE.get(p['niveau'], '?')}] {p['titre']}")
        if p.get("details"):
            lignes.append("    " + p["details"])
    soucis = [p for p in bilan.get("points") or [] if p["niveau"] != "ok"]
    lignes += ["", "-" * 58,
               "Rien à signaler." if not soucis else f"{len(soucis)} point(s) à regarder.",
               f"Cette semaine : {s.get('changements', 0)} mises à jour, {s.get('sessions', 0)} sessions "
               f"({s.get('echecs', 0)} en échec)."]
    return "\n".join(lignes)


def texte_notification(bilan):
    soucis = [p for p in bilan.get("points") or [] if p["niveau"] != "ok"]
    if not soucis:
        n = (bilan.get("semaine") or {}).get("changements", 0)
        return "Health Hub : bonne semaine", f"Tout va bien. {n} mises à jour appliquées cette semaine.", "low"
    urgence = "critical" if any(p["niveau"] == "alerte" for p in soucis) else "normal"
    corps = "\n".join("• " + p["titre"] for p in soucis[:LIGNES_MAX])
    return f"Health Hub : {len(soucis)} point(s) à regarder", corps, urgence


def notifier(bilan, *, run=commun.run):
    """Envoie la notification et attend (au plus une heure) un clic sur « Ouvrir Health Hub »."""
    titre, corps, urgence = texte_notification(bilan)
    _, sortie = run(["notify-send", "-a", "Health Hub", "-i", "centre-bazzite", "-u", urgence, "--wait",
                     "-A", "default=Ouvrir Health Hub", titre, corps], timeout=DELAI_NOTIFICATION)
    if "default" not in (sortie or ""):
        return False
    run(["systemd-run", "--user", "--collect", "--quiet", str(HEALTH_HUB)])
    return True


def _sessions(dossier=None):
    res = []
    for f in sorted(glob.glob(str(Path(dossier or commun.ETAT) / "sessions" / "*.json"))):
        s = commun.lire_json(Path(f), None)
        if isinstance(s, dict):
            res.append(s)
    return res


def construire(*, maintenant=None):
    maintenant = maintenant or datetime.now()
    debut = (maintenant - FENETRE).isoformat(timespec="seconds")
    # Première semaine : pas de relevé vieux de 7 jours, on part du plus ancien de la fenêtre.
    avant = inventaire.releve_avant(debut) or inventaire.plus_ancien_releve()
    apres = inventaire.dernier_releve()
    systeme = inventaire.differences(avant, apres) if avant and apres else []
    donnees = commun.lire_json(commun.ETAT / "etat.json", {})
    pts = donnees.get("points") if isinstance(donnees, dict) else None
    sem = semaine(maintenant, sessions=_sessions(), lignes_maj_apps=etat.lignes_historique(),
                  changements_systeme=systeme)
    return rapport_json(resultats_depuis_points(pts or []), maintenant.isoformat(timespec="seconds")) | {
        "semaine": sem}


def ecrire(bilan):
    commun.ecrire_json(_fichier("bilan-hebdo.json"), bilan)
    chemin = _fichier("bilan-hebdo.txt")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(rediger(bilan) + "\n", encoding="utf-8")
