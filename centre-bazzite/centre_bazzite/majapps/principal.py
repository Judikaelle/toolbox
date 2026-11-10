"""Orchestration : verrou, modules, rapport, historique, notification."""

import fcntl
import json
import locale
import time

from ..commun import jeu_en_cours
from .appimages import mod_appimages
from .distrobox import mod_distrobox
from .doublons import mod_doublons
from .geproton import mod_ge_proton
from .godot import mod_godot
from .linstat import mod_linstat
from .ollama import mod_ollama
from .outils import CODE_REPORTE, ECHEC, ETAT, HISTORIQUE, NOTIFIE, RAPPORT, Resultat, reseau_ok
from .rapport import a_notifier, changements, cles_manuelles, ligne, notifier, redaction
from .uv import mod_uv
from .vicinae import mod_vicinae

try:
    locale.setlocale(locale.LC_TIME, "")
except locale.Error:
    pass

MODULES = [
    ("vicinae", mod_vicinae),
    ("ollama", mod_ollama),
    ("uv", mod_uv),
    ("distrobox", mod_distrobox),
    ("ge-proton", mod_ge_proton),
    ("godot", mod_godot),
    ("appimages", mod_appimages),
    ("linstat", mod_linstat),
    ("doublons", mod_doublons),
]


def main(argv: list[str]) -> int:
    if "--report" in argv:
        print(RAPPORT.read_text() if RAPPORT.exists() else "Aucun rapport pour l'instant.")
        return 0
    simulation = "--check" in argv
    ETAT.mkdir(parents=True, exist_ok=True)
    with open(ETAT / "verrou", "w") as verrou:
        try:
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("maj-apps tourne déjà.")
            return 0
        if not simulation:
            jeu = jeu_en_cours()
            if jeu:
                print("Jeu en cours (%s) : mises à jour reportées de 30 min." % jeu)
                return CODE_REPORTE
        if not reseau_ok():
            print("Pas d'accès à GitHub : mises à jour reportées.")
            return 1 if simulation else CODE_REPORTE

        resultats = []
        for nom, module in MODULES:
            try:
                r = module(simulation)
            except Exception as exc:
                r = Resultat(nom, ECHEC, "%s : %s" % (nom, exc), "")
            for x in ([] if r is None else r if isinstance(r, list) else [r]):
                resultats.append(x)
                if not simulation:  # suivi au fil de l'eau dans le journal systemd
                    print(ligne(x), flush=True)

        texte = redaction(resultats, simulation)
        if simulation:
            print("\n" + texte)
            return 0
        RAPPORT.write_text(texte + "\n")
        with open(HISTORIQUE, "a") as fh:
            fh.write(json.dumps({"date": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "resultats": [r._asdict() for r in resultats],
                                 "changements": changements(resultats)},
                                ensure_ascii=False) + "\n")
        try:
            deja = json.loads(NOTIFIE.read_text())
        except (OSError, ValueError):
            deja = []
        if "--quiet" not in argv and a_notifier(resultats, deja):
            notifier(resultats)
        NOTIFIE.write_text(json.dumps(cles_manuelles(resultats), ensure_ascii=False))
        return 1 if any(r.etat == ECHEC for r in resultats) else 0
