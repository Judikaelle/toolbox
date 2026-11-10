"""Rapport : lignes, changements, rédaction et notification."""

import time

from .outils import ECHEC, MANUEL, MIS_A_JOUR, PUCE, run


def ligne(r):
    texte = "[%s] %s" % (PUCE[r.etat], r.message)
    if r.details:
        texte += "\n" + "\n".join("    " + l for l in r.details.splitlines())
    return texte


def changements(resultats):
    return [{"module": r.module, "de": r.de, "vers": r.vers, "notes": r.notes}
            for r in resultats if r.etat == MIS_A_JOUR]


def redaction(resultats, simulation):
    titre = "Mises à jour hors uupd — %s%s" % (
        time.strftime("%A %d %B %Y à %H:%M"), " (simulation)" if simulation else "")
    corps = "\n".join(ligne(r) for r in resultats) or "Rien à vérifier."
    return "%s\n%s\n\n%s" % (titre, "=" * len(titre), corps)


def cles_manuelles(resultats):
    return sorted("%s|%s" % (r.module, r.message) for r in resultats if r.etat == MANUEL)


def a_notifier(resultats, deja_signale):
    """Toujours pour une mise à jour faite ou un échec ; une action manuelle
    n'est signalée qu'une fois (pas de rappel chaque nuit)."""
    if any(r.etat in (MIS_A_JOUR, ECHEC) for r in resultats):
        return True
    nouvelles = set(cles_manuelles(resultats)) - set(deja_signale)
    return bool(nouvelles)


def notifier(resultats):
    faits = [r.message for r in resultats if r.etat == MIS_A_JOUR]
    echecs = [r.message for r in resultats if r.etat == ECHEC]
    manuels = [r.message for r in resultats if r.etat == MANUEL]
    lignes = ["✓ " + m for m in faits] + ["✗ " + m for m in echecs] + ["• " + m for m in manuels]
    titre = "Mises à jour : %d appliquée(s)" % len(faits)
    if echecs:
        titre += ", %d échec(s)" % len(echecs)
    elif not faits:
        titre = "Mises à jour : action manuelle à faire"
    corps = "\n".join(lignes[:6]) + "\n\nDétail : maj-apps --report"
    run(["notify-send", "-a", "Mises à jour", "-u", "critical" if echecs else "normal",
         "-i", "system-software-update", titre, corps], timeout=20)
