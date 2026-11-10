"""Assemblage de etat.json : couleur, phrases, « depuis ta dernière visite », santé, points."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from . import commun, inventaire, points as points_mod, rpmostree, sante as sante_mod, taches, uupd
from . import modejeu as modejeu_mod

FENETRE_ECHECS = timedelta(days=7)
HISTORIQUE_MAJ_APPS = Path.home() / ".local" / "state" / "maj-apps" / "historique.jsonl"
PREMIER_PASSAGE = "Premier passage : rien à comparer pour l'instant."


def _heure_exec(execution):
    return (execution or {}).get("fin") or (execution or {}).get("debut")


def chronologie(depuis, changements, executions):
    """Regroupe les changements par moment de mise à jour, triés par heure.
    `executions` = {"uupd": dernière exécution|None, "maj_apps": {module: heure}, "apres": iso}."""
    heure_uupd = _heure_exec(executions.get("uupd"))
    maj_apps = executions.get("maj_apps") or {}
    apres = executions.get("apres") or depuis
    version = next((c["vers"] for c in changements
                    if c["categorie"] == "systeme" and c["id"] == "image"), None)
    groupes = {}

    def ajouter(cle, heure, categorie, c):
        g = groupes.setdefault(cle, {"heure": heure, "titre": None, "categorie": categorie,
                                     "changements": []})
        g["changements"].append(c)

    for c in changements:
        cat = c["categorie"]
        if cat == "outils" and c["id"] in maj_apps:
            heure = c.get("heure") or maj_apps[c["id"]]
            ajouter(("maj", c["id"], heure), heure, cat, c)
        else:
            ajouter(cat, heure_uupd or apres, cat, c)
    for cle, g in groupes.items():
        if isinstance(cle, tuple):
            c = g["changements"][0]
            g["titre"] = f"{c['nom']} {c['vers']}"
        elif cle == "systeme":
            g["titre"] = f"Bazzite {version}" if version else "Paquets système"
        elif cle == "applications":
            n = len(g["changements"])
            g["titre"] = f"{n} application" + ("s" if n > 1 else "")
        else:
            n = len(g["changements"])
            g["titre"] = f"{n} outil" + ("s" if n > 1 else "") + " Homebrew"
    return sorted(groupes.values(), key=lambda g: (g["heure"] or "", g["titre"]))


def _actifs(points_):
    return [p for p in points_ if not p.get("en_sourdine") and p.get("gravite") != "info"]


DISPONIBLES = "Des mises à jour sont disponibles."


def phrases(couleur, points_, nb_changements, premier=False):
    if couleur == "en_cours":
        return "Mise à jour en cours…", "Tu peux continuer à utiliser ton PC."
    # « maj:dispo: » est une information : il ne colore pas, mais change la première ligne, même en vert.
    dispo = any(str(p.get("id", "")).startswith("maj:dispo:") and not p.get("en_sourdine") for p in points_)
    if couleur == "vert":
        ligne1, ligne2 = DISPONIBLES if dispo else "Tout est à jour.", "Rien à signaler."
    else:
        actifs = _actifs(points_)
        attente = any(str(p.get("id", "")).startswith("redemarrage:") for p in actifs)
        echecs = [str(p.get("id", "")) for p in actifs if p.get("gravite") == "echec"]
        if any(i.startswith("maj:echec") for i in echecs):
            ligne1 = "Une mise à jour a échoué."
        elif echecs:
            ligne1 = "Un problème demande ton attention."
        elif dispo:
            ligne1 = DISPONIBLES
        else:
            ligne1 = "Des mises à jour t'attendent." if attente else "Tout est à jour."
        n = len(actifs)
        ligne2 = "Une chose mérite un coup d'œil." if n <= 1 else f"{n} choses méritent un coup d'œil."
    if premier:
        ligne1 = PREMIER_PASSAGE
    return ligne1, ligne2


def lignes_historique(historique=None):
    """Les lignes de l'historique de maj-apps (par défaut le fichier réel)."""
    historique = HISTORIQUE_MAJ_APPS if historique is None else historique
    res = []
    try:
        for ligne in Path(historique).read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ligne)
            except ValueError:
                continue
            if isinstance(d, dict):
                res.append(d)
    except OSError:
        pass
    return res


def _changements_maj_apps(lignes, depuis):
    """(changements, {module: heure}) des lignes d'historique postérieures à `depuis`."""
    changements, heures = [], {}
    for d in lignes:
        date = d.get("date") or ""
        if not date or date <= depuis or not d.get("changements"):
            continue
        for c in d["changements"]:
            module = c.get("module")
            if not module:
                continue
            changements.append({"categorie": "outils", "id": module,
                                "nom": module if module == "uv" else module.capitalize(),
                                "de": c.get("de"), "vers": c.get("vers"), "heure": date})
            heures[module] = date
    return changements, heures


UNITE_SESSION = "centre-bazzite-maj.service"
INTERROMPUE = "interrompue"


def session_maj_active():
    """L'unité de la session « Tout mettre à jour » tourne-t-elle encore ? Dans le doute : oui."""
    _, texte = commun.run(["systemctl", "--user", "is-active", UNITE_SESSION], timeout=15)
    return texte.strip() not in ("inactive", "failed")


def marquer_interrompue(s, fin):
    """Session coupée (reboot, arrêt de l'unité, coupure) : l'étape en cours passe en échec
    « interrompue », celles jamais lancées sont sautées, et la session est un échec."""
    for e in (s.get("etapes") or {}).values():
        if not isinstance(e, dict):
            continue
        if e.get("statut") == "en_cours":
            e["statut"], e["detail"] = "echec", INTERROMPUE
        elif e.get("statut") == "attente":
            e["statut"], e["detail"] = "saute", "session interrompue"
    s["fin"] = s.get("fin") or fin
    s["succes"] = False
    s["extinction"] = None
    return s


def archiver_interrompue(s):
    """Archive une session restée « en cours » ; une archive déjà écrite par la session fait foi."""
    fin = commun.maintenant()
    chemin = commun.ETAT / "sessions" / f"{s.get('debut') or fin}.json"
    if not chemin.exists():
        commun.ecrire_json(chemin, marquer_interrompue(s, fin))


def _session_en_cours(active=session_maj_active):
    """La session du fichier en cours, si son unité tourne encore ; sinon elle est archivée
    comme interrompue et le fichier supprimé (sans quoi le Centre resterait « en cours » à vie)."""
    chemin = commun.ETAT / "session-en-cours.json"
    if not chemin.exists():
        return None
    s = commun.lire_json(chemin, None)
    if active():
        return s if isinstance(s, dict) else None
    if isinstance(s, dict):
        archiver_interrompue(s)
    chemin.unlink(missing_ok=True)
    return None


def _extinction_annulee(session):
    """« Annuler l'extinction » a été demandé pendant cette session « et éteindre »."""
    if not session or not session.get("eteindre"):
        return False
    e = (session.get("etapes") or {}).get("extinction") or {}
    return e.get("statut") == "saute" or (commun.ETAT / "annuler-extinction").exists()


def _derniere_session():
    fichiers = sorted((commun.ETAT / "sessions").glob("*.json"))
    for f in reversed(fichiers):
        s = commun.lire_json(f, None)
        if isinstance(s, dict):
            return s
    return None


SANS_DETAIL = "Détails non enregistrés pour cette session."


def sessions_depuis(depuis):
    """Entrées de chronologie, une par session de Health Hub terminée depuis `depuis` (même sans changement)."""
    res = []
    for f in sorted((commun.ETAT / "sessions").glob("*.json")):
        s = commun.lire_json(f, None)
        if not isinstance(s, dict):
            continue
        heure = s.get("fin") or s.get("debut")
        if not heure or heure <= depuis:
            continue
        titre = ("Mise à jour et extinction" if s.get("eteindre") else "Mise à jour vérifiée") \
            if s.get("succes") else "Mise à jour incomplète"
        res.append({"heure": heure, "titre": titre, "categorie": "session", "changements": [],
                    "ligne": s.get("bilan") or SANS_DETAIL})
    return sorted(res, key=lambda g: g["heure"])


TAILLE_NOTES_MAX = 4000


def _resumes(changements):
    table = commun.lire_json(commun.ETAT / "resumes.json", {})
    resumes, notes = {}, {}
    if not isinstance(table, dict):
        return resumes, notes
    for c in changements:
        e = table.get(f"{c['id']}@{c['vers']}")
        if not isinstance(e, dict):
            continue
        if e.get("resume"):
            resumes[c["id"]] = e["resume"]
        texte = (e.get("notes") or "")[:TAILLE_NOTES_MAX] or None
        if e.get("source") or e.get("lien") or texte:
            notes[c["id"]] = {"source": e.get("source"), "lien": e.get("lien"), "texte": texte}
    return resumes, notes


def construire(complet=True, *, collecter=sante_mod.collecter,
               deploiements=rpmostree.etat_deploiements, unite_active=uupd.unite_active,
               executions=uupd.executions_depuis, historique=HISTORIQUE_MAJ_APPS,
               session_active=session_maj_active, jeu=commun.jeu_en_cours,
               ollama=sante_mod.ollama, controles=sante_mod.lire_controles, modejeu=modejeu_mod.resume):
    fichier = commun.ETAT / "etat.json"
    visites = commun.lire_json(commun.ETAT / "visites.json", {})
    visites = visites if isinstance(visites, dict) else {}
    depuis = visites.get("derniere")
    lignes = lignes_historique(historique)

    changements, execs, heures_maj = [], [], {}
    if depuis:
        avant = inventaire.releve_du(visites.get("releve")) or inventaire.releve_avant(depuis)
        apres = inventaire.dernier_releve()
        if avant and apres:
            changements = inventaire.differences(avant, apres)
        ajouts, heures_maj = _changements_maj_apps(lignes, depuis)
        connus = {c["id"] for c in changements if c["categorie"] == "outils"}
        changements += [c for c in ajouts if c["id"] not in connus]
    # Les échecs de uupd se lisent sur une semaine (pas seulement depuis la visite) : un échec
    # reste signalé jusqu'à la réussite d'une exécution plus récente.
    fenetre = (datetime.now() - FENETRE_ECHECS).isoformat(timespec="seconds")
    recentes = executions(min(depuis, fenetre) if depuis else fenetre)
    if depuis:
        execs = [e for e in recentes if (e.get("fin") or e.get("debut") or "") > depuis]
    derniere_exec = execs[-1] if execs else None

    sante = None
    if not complet:
        precedent = commun.lire_json(fichier, None)
        sante = precedent.get("sante") if isinstance(precedent, dict) else None
        if isinstance(sante, dict):
            try:        # peu coûteux : « Arrêter Ollama » se voit dès le rafraîchissement suivant
                sante = dict(sante, ollama=ollama())
            except Exception:
                pass
            try:        # cache des contrôles : « centre-bazzite controles » se voit aussitôt (Ruling V5)
                sante = dict(sante, controles=controles())
            except Exception:
                pass
    if not isinstance(sante, dict):
        sante = collecter()     # santé illisible : le rafraîchissement léger devient complet

    dep = deploiements()
    maj_apps = next((d for d in reversed(lignes) if d.get("resultats")), None)
    session = _session_en_cours(session_active)
    unite = None if session else unite_active()
    en_cours = session or ({"unite": unite} if unite else None)
    pts = points_mod.points(sante, dep, maj_apps, _derniere_session(), uupd=recentes)
    pts = points_mod.points_avec_sourdines(pts, sante)
    for p in pts:       # la page de chaque point : ses listes « À regarder » suivent les compteurs du menu
        p["rubrique"] = points_mod.rubrique(p["id"])
        p["domaine"] = points_mod.domaine(p["id"])          # son onglet dans la page Santé (Task 19)
    couleur = points_mod.couleur(pts, en_cours)
    phrase, phrase2 = phrases(couleur, pts, len(changements), premier=not depuis)

    if depuis:
        apres_date = (inventaire.dernier_releve() or {}).get("date")
        chrono = chronologie(depuis, changements, {"uupd": derniere_exec, "maj_apps": heures_maj,
                                                   "apres": apres_date})
        sessions = sessions_depuis(depuis)
        chrono = sorted(chrono + sessions, key=lambda g: g["heure"] or "")
        derniere_maj = {"heure": sessions[-1]["heure"], "bilan": sessions[-1]["ligne"]} if sessions else None
    else:
        chrono, derniere_maj = [], None
    resumes, notes = _resumes(changements)
    try:        # D14 : le résumé du mode jeu, en complet comme en léger ; illisible, il manque sans rien bloquer
        resume_modejeu = modejeu()
    except Exception:
        resume_modejeu = None
    return {
        "genere": commun.maintenant(),
        "couleur": couleur,
        "phrase": phrase,
        "phrase2": phrase2,
        "en_cours": en_cours,
        "extinction": (session or {}).get("extinction"),
        "extinction_annulee": _extinction_annulee(session),
        "redemarrage": bool((dep or {}).get("en_attente")),
        "jeu": jeu(),       # spec 7.3 : les interfaces proposent d'attendre la fin de la partie
        "modejeu": resume_modejeu,
        "depuis_visite": {"depuis": depuis or None, "nombre": len(changements), "chronologie": chrono},
        "derniere_maj": derniere_maj,
        "sante": sante,
        "points": pts,
        "compteurs": points_mod.compteurs(pts),
        "resumes": resumes,
        "notes": notes,
    }


def ecrire():
    taches.reparer_orphelines()
    chemin = commun.ETAT / "etat.json"
    commun.ecrire_json(chemin, construire())
    return chemin


def marquer_vu():
    dernier = inventaire.dernier_releve()
    commun.ecrire_json(commun.ETAT / "visites.json",
                       {"derniere": commun.maintenant(), "releve": (dernier or {}).get("date")})
