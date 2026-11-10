"""Godot : signale une nouvelle version."""

from .outils import A_JOUR, MANUEL, SHARE, Resultat, fmt, github, version


GODOT_DIR = SHARE / "godot"


def mod_godot(_simulation):
    binaires = sorted(GODOT_DIR.glob("Godot_v*_linux.x86_64"))
    installees = [v for v in (version(b.name) for b in binaires) if v]
    if not installees:
        return None
    tag = github("godotengine/godot")["tag_name"]
    derniere = version(tag)
    if max(installees) >= derniere:
        return Resultat("godot", A_JOUR, "Godot %s" % fmt(max(installees)), "")
    return Resultat("godot", MANUEL, "Godot %s disponible (installé : %s)"
                    % (tag, fmt(max(installees))),
                    "https://godotengine.org/download/linux/ — pense aussi aux export templates")
