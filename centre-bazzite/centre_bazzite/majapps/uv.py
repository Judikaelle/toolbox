"""uv : remplacé depuis la release GitHub (uv et uvx), avec retour arrière."""

import os
import shutil
import tarfile

from .outils import (
    A_FAIRE, A_JOUR, BIN, CACHE, LIB, MIS_A_JOUR, Resultat, asset, effacer, fmt, github,
    notes_release, run, telecharger, version)


def mod_uv(simulation):
    binaire = BIN / "uv"
    if not binaire.exists() or binaire.is_symlink():
        return None
    _, sortie = run([binaire, "--version"], timeout=30)
    installe = version(sortie)
    release = github("astral-sh/uv")
    derniere = version(release["tag_name"])
    if installe and installe >= derniere:
        return Resultat("uv", A_JOUR, "uv %s" % fmt(installe), "")
    titre = "uv %s → %s" % (fmt(installe), fmt(derniere))
    if simulation:
        return Resultat("uv", A_FAIRE, titre, "")

    nom = "uv-x86_64-unknown-linux-gnu"
    url, digest = asset(release, nom + ".tar.gz")
    archive = telecharger(url, CACHE / ("uv-%s.tar.gz" % release["tag_name"]), digest)
    travail = LIB / "uv.maj"
    effacer(travail)
    travail.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(travail, filter="data")
    _, sortie = run([travail / nom / "uv", "--version"], timeout=30)
    if version(sortie) != derniere:
        effacer(travail)
        raise RuntimeError("le nouveau binaire ne répond pas : %s" % sortie.strip()[-200:])
    remplaces = []
    try:
        for outil in ("uv", "uvx"):
            neuf = travail / nom / outil
            if not neuf.exists():
                continue
            if (BIN / outil).exists():
                shutil.copy2(BIN / outil, travail / (outil + ".ancien"))
                remplaces.append(outil)
            os.replace(neuf, BIN / outil)
    except Exception as exc:
        for outil in remplaces:
            os.replace(travail / (outil + ".ancien"), BIN / outil)
        effacer(travail)
        raise RuntimeError("%s ; retour à la version %s" % (exc, fmt(installe)))
    effacer(travail, archive)
    return Resultat("uv", MIS_A_JOUR, titre, "",
                    fmt(installe), fmt(derniere), notes_release(release))
