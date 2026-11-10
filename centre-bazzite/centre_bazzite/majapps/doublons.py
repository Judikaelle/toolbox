"""Doublons : signale un binaire de ~/.local/bin qui masque la version Homebrew."""

import os
from pathlib import Path

from .outils import A_JOUR, BIN, BREW_BIN, MANUEL, Resultat, est_script_pip


def doublons_brew(dossier_local, dossier_brew):
    """Exécutables de dossier_local qui existent aussi dans Homebrew. Comme
    ~/.local/bin passe avant brew dans le PATH, c'est la vieille copie qui gagne."""
    trouves = []
    for f in sorted(Path(dossier_local).iterdir()):
        if not (Path(dossier_brew) / f.name).exists():
            continue
        if f.is_symlink() and str(f.resolve()).startswith(str(Path(dossier_brew).resolve().parent)):
            continue
        if f.is_file() and os.access(f, os.X_OK) and not est_script_pip(f):
            trouves.append(f.name)
    return trouves


def mod_doublons(_simulation):
    trouves = doublons_brew(BIN, BREW_BIN)
    if not trouves:
        return Resultat("doublons", A_JOUR, "Aucun binaire ne masque Homebrew", "")
    return Resultat("doublons", MANUEL,
                    "%d binaire(s) de ~/.local/bin masquent Homebrew : %s"
                    % (len(trouves), ", ".join(trouves)),
                    "Homebrew les met à jour chaque nuit, pas les copies de ~/.local/bin, "
                    "qui passent avant dans le PATH.\n    les retirer : gio trash "
                    + " ".join("~/.local/bin/%s" % t for t in trouves))
