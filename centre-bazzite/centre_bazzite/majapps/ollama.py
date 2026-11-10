"""Ollama : réinstallé depuis la release GitHub ; remis au lendemain si le serveur tourne."""

import tarfile

from .outils import (
    A_FAIRE, A_JOUR, BIN, CACHE, LIB, MIS_A_JOUR, REPORTE, Resultat, asset, effacer, fmt, github,
    notes_release, run, service_actif, telecharger, version)


def mod_ollama(simulation):
    binaire = BIN / "ollama"
    lib = LIB / "ollama"
    if not binaire.exists():
        return None
    _, sortie = run([binaire, "--version"], timeout=30)
    installe = version(sortie)
    release = github("ollama/ollama")
    derniere = version(release["tag_name"])
    if installe and installe >= derniere:
        return Resultat("ollama", A_JOUR, "Ollama %s" % fmt(installe), "")
    titre = "Ollama %s → %s" % (fmt(installe), fmt(derniere))
    if service_actif("ollama.service"):
        return Resultat("ollama", REPORTE, titre,
                        "le serveur tourne (ia-on) : mise à jour au prochain passage")
    if simulation:
        return Resultat("ollama", A_FAIRE, titre, "téléchargement d'environ 1,5 Go")

    url, digest = asset(release, "ollama-linux-amd64.tar.zst")
    archive = telecharger(url, CACHE / ("ollama-%s.tar.zst" % release["tag_name"]), digest)
    travail = LIB / "ollama.maj"
    sauvegarde = LIB / "ollama.ancien"
    effacer(travail, sauvegarde)
    travail.mkdir(parents=True)
    with tarfile.open(archive, "r:zst") as tar:
        tar.extractall(travail, filter="data")
    if not (travail / "bin/ollama").exists() or not (travail / "lib/ollama").is_dir():
        effacer(travail)
        raise RuntimeError("archive Ollama inattendue (bin/ollama ou lib/ollama absent)")
    _, sortie = run([travail / "bin/ollama", "--version"], timeout=30)
    if version(sortie) != derniere:
        effacer(travail)
        raise RuntimeError("le nouveau binaire ne répond pas : %s" % sortie.strip()[-200:])

    sauvegarde.mkdir()
    if lib.exists():
        lib.rename(sauvegarde / "lib")
    binaire.rename(sauvegarde / "ollama")
    try:
        (travail / "lib/ollama").rename(lib)
        (travail / "bin/ollama").rename(binaire)
        _, sortie = run([binaire, "--version"], timeout=30)
        if version(sortie) != derniere:
            raise RuntimeError("vérification après installation : %s" % sortie.strip()[-200:])
    except Exception as exc:
        effacer(lib, binaire)
        if (sauvegarde / "lib").exists():
            (sauvegarde / "lib").rename(lib)
        (sauvegarde / "ollama").rename(binaire)
        effacer(travail, sauvegarde)
        raise RuntimeError("%s ; retour à la version %s" % (exc, fmt(installe)))
    effacer(travail, sauvegarde, archive)
    return Resultat("ollama", MIS_A_JOUR, titre, "",
                    fmt(installe), fmt(derniere), notes_release(release))
