"""Distrobox : distrobox upgrade, sauf les conteneurs à garder stables."""

import re

from .. import config
from .outils import A_FAIRE, A_JOUR, ECHEC, ETAT, PROC, REPORTE, Resultat, run


# Deux listes de la configuration locale ([majapps.distrobox]), relues à chaque passe :
# - exclure : conteneurs à ne jamais mettre à jour automatiquement, nom -> raison affichée ;
# - applis : conteneurs qui portent une appli qu'on ne met pas à jour sous les pieds de l'utilisateur,
#   nom du conteneur -> (nom du processus dans /proc/*/comm, nom affiché). Une appli Chromium/Electron
#   mise à jour pendant qu'elle tourne lance ses nouveaux processus depuis le nouveau binaire et peut planter.

# erreurs d'apt qui viennent du réseau : on réessaiera à la prochaine passe au lieu de signaler un échec
RESEAU = re.compile(r"Failed to fetch|Impossible de récupérer|Temporary failure resolving|"
                    r"Échec temporaire de résolution|Could not resolve|Could not connect|"
                    r"Impossible de se connecter|Connection timed out|Délai d'attente dépassé|"
                    r"Unable to connect|Network is unreachable", re.I)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def appli_ouverte(comm, proc=None):
    """Vrai si un processus de ce nom tourne (lecture de /proc/*/comm)."""
    racine = proc if proc is not None else PROC
    try:
        entrees = list(racine.iterdir())
    except OSError:
        return False
    for d in entrees:
        if not d.name.isdigit():
            continue
        try:
            if (d / "comm").read_text().strip() == comm:
                return True
        except OSError:
            continue
    return False


def erreur_lisible(sortie, code):
    """La ligne qui explique l'échec : sans couleurs ni en-tête « Upgrading … » de distrobox,
    de préférence la dernière erreur d'apt (« E: … »)."""
    lignes = [ANSI.sub("", l).strip() for l in (sortie or "").splitlines()]
    lignes = [l for l in lignes if l and not l.startswith("Upgrading ")]
    erreurs = [l for l in lignes if l.startswith("E:") or re.search(r"\berr(eu)?r", l, re.I)]
    if erreurs:
        return erreurs[-1]
    if lignes:
        return lignes[-1]
    return "erreur sans message (code %s)" % code


def mod_distrobox(simulation):
    code, sortie = run(["podman", "ps", "-a", "--filter", "label=manager=distrobox",
                        "--format", "{{.Names}}|{{.State}}"], timeout=60)
    if code != 0:
        raise RuntimeError("liste des conteneurs impossible : %s" % sortie.strip()[:200])
    conteneurs = [l.split("|", 1) for l in sortie.splitlines() if "|" in l]
    if not conteneurs:
        return None
    exclus, applis = config.distrobox_exclus(), config.distrobox_applis()
    a_traiter = [(n, e) for n, e in conteneurs if n not in exclus]
    ignores = ["%s (%s)" % (n, exclus[n]) for n, _e in conteneurs if n in exclus]
    note = ("non mis à jour : " + ", ".join(ignores)) if ignores else ""
    noms = ", ".join(n for n, _e in a_traiter) or "aucun"
    if simulation:
        return Resultat("distrobox", A_FAIRE if a_traiter else A_JOUR,
                        "Distrobox à mettre à jour : %s" % noms, note)
    echecs, reportes = [], []
    for nom, etat in a_traiter:
        appli = applis.get(nom)
        if appli and appli_ouverte(appli[0]):
            reportes.append("%s : reporté, %s est ouvert (mis à jour à la prochaine passe où il "
                            "sera fermé)" % (nom, appli[1]))
            continue
        code, sortie = run(["distrobox", "upgrade", nom], timeout=3600)
        if etat != "running":
            run(["podman", "stop", nom], timeout=120)
        if code == 0:
            continue
        journal = ETAT / ("distrobox-%s.log" % nom)
        try:
            ETAT.mkdir(parents=True, exist_ok=True)
            journal.write_text(sortie or "")
            ou = " (journal complet : %s)" % journal
        except OSError:
            ou = ""
        message = erreur_lisible(sortie, code)
        if RESEAU.search(sortie or ""):
            reportes.append("%s : reporté, réseau indisponible — %s%s" % (nom, message, ou))
        else:
            echecs.append("%s : %s%s" % (nom, message, ou))
    details = "\n".join(echecs + reportes + ([note] if note else []))
    if echecs:
        return Resultat("distrobox", ECHEC, "Distrobox : %d échec(s)" % len(echecs), details)
    if reportes:
        return Resultat("distrobox", REPORTE, "Distrobox : %d conteneur(s) reporté(s)" % len(reportes),
                        details)
    return Resultat("distrobox", A_JOUR, "Distrobox à jour : %s" % noms, note)
