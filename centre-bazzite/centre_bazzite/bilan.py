"""Ce qu'une session de mise à jour a fait, en phrases courtes : détail par étape et bilan."""
import json

from . import etat

NOMS_MODULES = {"system": "Système", "flatpak": "Flatpak", "brew": "Homebrew"}
DEJA_A_JOUR = {"system": ("No upgrade available.", "déjà à jour"),
               "flatpak": ("Nothing to update.", "rien à mettre à jour"),
               "brew": ("Already up-to-date.", "déjà à jour")}
CATEGORIE = {"flatpak": ("applications", "application", "applications", "mise", "mises"),
             "brew": ("outils", "outil", "outils", "mis", "mis")}
SUIVI_MAJ_APPS = ("vicinae", "ollama", "uv")


def _modules(lignes):
    """{module: {"sorties": [...], "echec": bool, "erreur": str|None}} dans l'ordre du journal."""
    res = {}
    for ligne in lignes:
        try:
            d = json.loads(ligne)
        except (TypeError, ValueError):
            continue
        if not isinstance(d, dict) or not d.get("module"):
            continue
        m = res.setdefault(d["module"], {"sorties": [], "echec": False, "erreur": None})
        sortie = d.get("output")
        if d.get("msg") == "Command output" and isinstance(sortie, str) and sortie.strip():
            m["sorties"].append(sortie.strip())
        if d.get("status") == "finished" and d.get("exit_code", 0) != 0 or d.get("level") == "ERROR":
            m["echec"] = True
    return res


def _pluriel(n, singulier, pluriel):
    return f"{n} {singulier if n == 1 else pluriel}"


def _ligne_module(module, m, diff, redemarrage):
    nom = NOMS_MODULES.get(module, module.capitalize())
    if m["echec"]:
        return f"{nom} : échec ({m['sorties'][-1] if m['sorties'] else 'sans détail'})"
    phrase_a_jour = DEJA_A_JOUR.get(module)
    if phrase_a_jour and phrase_a_jour[0] in m["sorties"]:
        return f"{nom} : {phrase_a_jour[1]}"
    if module == "system":
        if redemarrage:
            return f"{nom} : nouvelle image prête, redémarrage nécessaire"
        n = sum(1 for c in diff if c["categorie"] == "systeme")
        return f"{nom} : " + (_pluriel(n, "changement", "changements") if n else "terminé, rien de nouveau")
    if module in CATEGORIE:
        categorie, singulier, pluriel, un, plusieurs = CATEGORIE[module]
        n = sum(1 for c in diff if c["categorie"] == categorie)
        if n:
            return f"{nom} : {_pluriel(n, singulier, pluriel)} {un if n == 1 else plusieurs} à jour"
    return f"{nom} : terminé, rien de nouveau"


def detail_uupd(lignes, diff, redemarrage):
    """Une ligne par module de uupd, d'après sa sortie dans le journal et le diff avant/après."""
    return "\n".join(_ligne_module(mod, m, diff, redemarrage) for mod, m in _modules(lignes).items())


def detail_maj_apps(lignes_historique, debut):
    """Résumé de la dernière exécution de maj-apps depuis `debut`, ou None si elle n'a pas laissé de ligne."""
    ligne = None
    for d in lignes_historique:
        if (d.get("date") or "") >= debut and isinstance(d.get("resultats"), list) \
                and (ligne is None or d["date"] >= ligne["date"]):
            ligne = d
    if ligne is None:
        return None
    resultats = [r for r in ligne["resultats"] if isinstance(r, dict)]
    faits = [r.get("message") for r in resultats if r.get("etat") == "mis à jour"]
    echecs = [r.get("message") for r in resultats if r.get("etat") == "échec"]
    a_faire = [r.get("message") for r in resultats if r.get("etat") in ("à faire", "à mettre à jour")]
    morceaux = faits + (["échec : " + ", ".join(echecs)] if echecs else []) \
        + (["à faire : " + ", ".join(a_faire)] if a_faire else [])
    if morceaux:
        return " ; ".join(morceaux)
    suivis = [r.get("message") for r in resultats if r.get("module") in SUIVI_MAJ_APPS]
    return "Tout est à jour" + (f" ({', '.join(suivis)})" if suivis else "")


def phrase(changements, echec=False, inconnu=False):
    """Une phrase qui résume la session."""
    if inconnu:
        return "Changements inconnus : relevé impossible."
    if not changements:
        return "Aucun changement, mais une étape a échoué." if echec else "Tout était déjà à jour."
    heures = {c["id"]: c["heure"] for c in changements if c.get("heure")}
    groupes = etat.chronologie("", changements, {"maj_apps": heures})
    n = len(changements)
    texte = f"{_pluriel(n, 'changement', 'changements')} : " + ", ".join(g["titre"] for g in groupes) + "."
    return texte + (" Une étape a échoué." if echec else "")
