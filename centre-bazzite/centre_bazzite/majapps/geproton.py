"""GE-Proton : signale une nouvelle version (à installer avec ProtonPlus)."""

from .outils import A_JOUR, MANUEL, SHARE, Resultat, github, version_ge


COMPAT_TOOLS = SHARE / "Steam/compatibilitytools.d"


def mod_ge_proton(_simulation):
    installees = [v for v in (version_ge(d.name) for d in COMPAT_TOOLS.glob("GE-Proton*")) if v]
    if not installees:
        return None
    derniere_tag = github("GloriousEggroll/proton-ge-custom")["tag_name"]
    derniere = version_ge(derniere_tag)
    if max(installees) >= derniere:
        return Resultat("ge-proton", A_JOUR, "GE-Proton %d-%d" % max(installees), "")
    return Resultat("ge-proton", MANUEL, "%s disponible" % derniere_tag,
                    "l'installer avec ProtonPlus, puis la choisir dans Steam")
