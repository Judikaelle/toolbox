"""Vicinae : réinstallé depuis la release GitHub, retour automatique si la nouvelle version ne démarre pas."""

import shutil
import time
from pathlib import Path

from .outils import (
    A_FAIRE, A_JOUR, BIN, CACHE, LIB, MANUEL, MIS_A_JOUR, SHARE, Resultat, asset, effacer, fmt,
    github, notes_release, run, service_actif, telecharger, version)


SERVICE_VICINAE = SHARE / "systemd/user/vicinae.service"
VICINAE_SYSTEME = Path("/usr/local/lib/vicinae")


def reecrire_service(texte, binaire):
    """Comme l'installeur officiel : ExecStart pointe vers le binaire installé."""
    return texte.replace("ExecStart=vicinae", "ExecStart=%s" % binaire)


def mod_vicinae(simulation):
    lib = LIB / "vicinae"
    binaire = BIN / "vicinae"
    if not lib.is_dir():
        if VICINAE_SYSTEME.is_dir():
            return Resultat(
                "vicinae", MANUEL,
                "Vicinae est installé dans /usr/local : impossible de le mettre à jour sans root",
                "réinstalle-le dans ~/.local (une seule fois) :\n"
                "    curl -fsSL https://vicinae.com/install | bash -s -- --prefix ~/.local\n"
                "    systemctl --user restart vicinae")
        return None
    _, sortie = run([binaire, "version"], timeout=30)
    installe = version(sortie)
    release = github("vicinaehq/vicinae")
    derniere = version(release["tag_name"])
    resultats = []
    if VICINAE_SYSTEME.is_dir():
        resultats.append(Resultat(
            "vicinae", MANUEL, "Ancienne copie de Vicinae encore présente dans /usr/local",
            "la retirer (une seule fois) :\n"
            "    sudo rm -rf /usr/local/lib/vicinae /usr/local/bin/vicinae "
            "/usr/local/bin/vicinae-node /usr/local/lib/systemd/user/vicinae.service "
            "/usr/local/share/applications/vicinae.desktop "
            "/usr/local/share/applications/vicinae-url-handler.desktop"))
    if installe and installe >= derniere:
        return resultats + [Resultat("vicinae", A_JOUR, "Vicinae %s" % fmt(installe), "")]
    titre = "Vicinae %s → %s" % (fmt(installe), fmt(derniere))
    if simulation:
        return resultats + [Resultat("vicinae", A_FAIRE, titre, "")]

    url, digest = asset(release, "Vicinae-x86_64.AppImage")
    appimage = telecharger(url, CACHE / ("Vicinae-%s.AppImage" % release["tag_name"]), digest)
    appimage.chmod(0o755)
    travail = LIB / "vicinae.maj"
    ancien = LIB / "vicinae.ancien"
    effacer(travail, ancien)
    travail.mkdir(parents=True)
    code, sortie = run([appimage, "--appimage-extract"], timeout=900, cwd=travail)
    nouveau = travail / "squashfs-root"
    if code != 0 or not (nouveau / "usr/bin/vicinae").exists():
        effacer(travail)
        raise RuntimeError("extraction de l'AppImage impossible : %s" % sortie.strip()[-200:])
    run(["chmod", "-R", "u=rwX,go=rX", nouveau])

    service_avant = SERVICE_VICINAE.read_text() if SERVICE_VICINAE.exists() else None
    lib.rename(ancien)
    nouveau.rename(lib)
    try:
        installer_annexes_vicinae(lib)
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "restart", "vicinae.service"], timeout=60)
        time.sleep(5)
        _, sortie = run([binaire, "version"], timeout=30)
        if not service_actif("vicinae.service") or version(sortie) != derniere:
            raise RuntimeError("la nouvelle version ne démarre pas")
    except Exception as exc:
        effacer(lib)
        ancien.rename(lib)
        if service_avant is not None:
            SERVICE_VICINAE.write_text(service_avant)
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "restart", "vicinae.service"], timeout=60)
        effacer(travail)
        raise RuntimeError("%s ; retour à la version %s" % (exc, fmt(installe)))
    effacer(ancien, travail, appimage)
    return resultats + [Resultat("vicinae", MIS_A_JOUR, titre, "",
                                       fmt(installe), fmt(derniere), notes_release(release))]


def installer_annexes_vicinae(lib):
    """Ce que fait l'installeur officiel en mode --prefix ~/.local, hors étapes root
    (capabilities du serveur d'entrées, modules-load)."""
    BIN.mkdir(parents=True, exist_ok=True)
    for nom, cible in (("vicinae", lib / "usr/bin/vicinae"), ("vicinae-node", lib / "usr/bin/node")):
        lien = BIN / nom
        if cible.exists():
            if lien.is_symlink() or lien.exists():
                lien.unlink()
            lien.symlink_to(cible)
    source = lib / "usr/lib/systemd/user/vicinae.service"
    if source.exists():
        SERVICE_VICINAE.parent.mkdir(parents=True, exist_ok=True)
        SERVICE_VICINAE.write_text(reecrire_service(source.read_text(), BIN / "vicinae"))
    apps = SHARE / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    for f in (lib / "usr/share/applications").glob("vicinae*.desktop"):
        shutil.copy2(f, apps / f.name)
    themes = lib / "usr/share/vicinae/themes"
    if themes.is_dir():
        shutil.copytree(themes, SHARE / "vicinae/themes", dirs_exist_ok=True)
    icone = lib / "usr/share/icons/hicolor/512x512/apps/vicinae.png"
    if icone.exists():
        dest = SHARE / "icons/hicolor/512x512/apps"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icone, dest / icone.name)
