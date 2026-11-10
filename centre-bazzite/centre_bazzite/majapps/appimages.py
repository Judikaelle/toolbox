"""AppImages suivies (celles de la configuration locale) : remplacées, l'ancienne gardée en .ancien, jamais pendant
qu'elles tournent."""

import hashlib
import json
import os
import re
import shutil
from collections import namedtuple
from datetime import datetime
from pathlib import Path

from .. import config
from .outils import (
    A_FAIRE, A_JOUR, CACHE, ECHEC, ETAT, MIS_A_JOUR, PROC, REPORTE, Resultat, asset,
    effacer, github, notes_release, telecharger)


# Une AppImage suivie : nom (clé de l'état), libellé, dépôt GitHub, fichier de la release
# (expression régulière), dossier, fichier installé (nom fixe ou motif glob),
# fichiers .desktop dont les lignes Exec pointent vers l'AppImage.
AppImage = namedtuple("AppImage", "nom libelle depot fichier dossier installe desktops")


def appimages_suivies():
    """Les AppImages de la configuration locale ([[majapps.appimages]]), relue à chaque passe ; aucune par défaut."""
    return [AppImage(a["cle"], a["nom"], a["depot"], a["motif_asset"], a["dossier"], a["fichier"], a["desktop"])
            for a in config.appimages()]


def sha256_fichier(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as fh:
        while bloc := fh.read(1 << 20):
            h.update(bloc)
    return h.hexdigest()


def appimage_en_cours(chemin, proc=PROC):
    """Vrai si un processus utilise cette AppImage : son exécutable ou sa ligne de commande
    la désigne, ou elle est montée (/tmp/.mount_*) par FUSE."""
    cible = os.path.realpath(chemin)
    for p in Path(proc).iterdir():
        if not p.name.isdigit():
            continue
        try:
            if os.path.realpath(p / "exe") == cible:
                return True
        except OSError:
            pass
        try:
            args = (p / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(a.startswith(b"/") and os.path.realpath(os.fsdecode(a)) == cible for a in args):
            return True
    try:
        for l in (Path(proc) / "mounts").read_text().splitlines():
            champs = l.split()
            if len(champs) > 1 and ".mount_" in champs[1] and os.path.realpath(champs[0]) == cible:
                return True
    except OSError:
        pass
    return False


def etat_appimages():
    try:
        return json.loads((ETAT / "appimages.json").read_text())
    except (OSError, ValueError):
        return {}


def noter_appimage(nom, tag, sha):
    etat = etat_appimages()
    etat[nom] = {"tag": tag, "sha256": sha}
    ETAT.mkdir(parents=True, exist_ok=True)
    (ETAT / "appimages.json").write_text(json.dumps(etat, indent=1))


def reecrire_exec(texte, ancien, nouveau):
    """Dans les lignes Exec=, remplace le chemin de l'ancienne AppImage par le nouveau
    (même dossier, même façon de l'écrire : /var/home ou /home)."""
    cible = os.path.realpath(ancien)
    lignes = []
    for l in texte.splitlines(keepends=True):
        if l.startswith("Exec="):
            morceaux = re.split(r"(\s+)", l[len("Exec="):])
            for i, mot in enumerate(morceaux):
                brut = mot.strip('"')
                if brut.startswith("/") and os.path.realpath(brut) == cible:
                    morceaux[i] = mot.replace(brut, os.path.join(os.path.dirname(brut), Path(nouveau).name))
            l = "Exec=" + "".join(morceaux)
        lignes.append(l)
    return "".join(lignes)


def ecrire_atomique(chemin, texte):
    """Fichier temporaire dans le même dossier puis os.replace : jamais à moitié écrit."""
    chemin = Path(chemin)
    temp = chemin.with_name(chemin.name + ".maj")
    try:
        temp.write_text(texte)
        shutil.copymode(chemin, temp)
        os.replace(temp, chemin)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def remplacer_appimage(app, installee, cache, dest):
    """Met en place le fichier `cache` (déjà vérifié par SHA-256). Au moindre souci,
    on défait ce qui a été fait : rien n'est remplacé. Une fois le nouveau fichier en
    place (et les .desktop à jour), la mise à jour est faite : un souci pour garder
    l'ancienne version est renvoyé comme avertissement (texte), pas comme erreur."""
    ancien = installee.with_name(installee.name + ".ancien")
    reserve = installee.with_name(installee.name + ".ancien.tmp")
    nouveau = dest.with_name(dest.name + ".nouveau")
    modifies = {}  # .desktop réellement réécrits -> texte d'origine
    try:
        shutil.copyfile(cache, nouveau)
        nouveau.chmod(0o755)
        if dest == installee:
            reserve.unlink(missing_ok=True)
            os.link(installee, reserve)  # l'ancien contenu reste lisible après le remplacement
            os.replace(nouveau, dest)
        else:
            textes = {}
            for d in app.desktops:
                if Path(d).exists() and installee.name in Path(d).read_text():
                    avant = Path(d).read_text()
                    apres = reecrire_exec(avant, installee, dest)
                    if any(l.startswith("Exec=") and installee.name in l for l in apres.splitlines()):
                        raise RuntimeError("%s : ligne Exec non reconnue, pas réécrite" % Path(d).name)
                    textes[d] = (avant, apres)
            os.replace(nouveau, dest)
            for d, (avant, apres) in textes.items():
                ecrire_atomique(d, apres)  # atomique : s'il échoue, d n'a pas changé
                modifies[d] = avant
    except BaseException:
        for d, avant in modifies.items():
            ecrire_atomique(d, avant)
        effacer(nouveau, reserve)
        if dest != installee:
            effacer(dest)
        raise
    try:
        if dest == installee:
            os.replace(reserve, ancien)
        else:
            for autre in Path(app.dossier).glob(app.installe + ".ancien"):
                if autre != ancien:
                    autre.unlink()  # une seule génération gardée
            os.replace(installee, ancien)
    except OSError as exc:
        effacer(reserve)
        return "ancienne version non gardée : %s" % exc
    return ""


def maj_appimage(app, simulation, proc=PROC):
    installees = sorted(Path(app.dossier).glob(app.installe), key=lambda f: f.stat().st_mtime)
    if not installees:
        return None
    installee = installees[-1]
    release = github(app.depot)
    tag = release["tag_name"]
    motif = re.compile(app.fichier)
    noms = [a["name"] for a in release.get("assets", []) if motif.fullmatch(a.get("name", ""))]
    if not noms:
        raise RuntimeError("aucun fichier %s dans la release %s" % (app.fichier, tag))
    url, digest = asset(release, noms[0])
    attendu = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
    note = etat_appimages().get(app.nom)
    if note is None:
        # premier passage : on ne rétrograde jamais un fichier plus récent que la release
        sha = sha256_fichier(installee)
        publiee = datetime.fromisoformat(release["published_at"]).timestamp()
        if sha == attendu or publiee <= installee.stat().st_mtime:
            if not simulation:
                noter_appimage(app.nom, tag, sha)
            return Resultat(app.nom, A_JOUR, "%s %s" % (app.libelle, tag), "")
        installe = "version inconnue"
    elif note.get("tag") == tag:
        return Resultat(app.nom, A_JOUR, "%s %s" % (app.libelle, tag), "")
    else:
        installe = note.get("tag")
    titre = "%s %s → %s" % (app.libelle, installe, tag)
    if appimage_en_cours(installee, proc):
        return Resultat(app.nom, REPORTE, titre,
                        "%s est en cours d'utilisation : mise à jour au prochain passage" % app.libelle)
    if simulation:
        return Resultat(app.nom, A_FAIRE, titre, "")

    cache = telecharger(url, CACHE / ("%s-%s" % (app.nom, noms[0])), digest)
    try:
        cache.chmod(0o755)
        with open(cache, "rb") as fh:
            if fh.read(4) != b"\x7fELF":
                raise RuntimeError("%s n'est pas un exécutable ELF : fichier rejeté" % noms[0])
        fixe = not any(c in app.installe for c in "*?[")
        dest = installee if fixe else Path(app.dossier) / noms[0]
        if appimage_en_cours(installee, proc):  # le téléchargement a pu durer des minutes
            return Resultat(app.nom, REPORTE, titre,
                            "%s est en cours d'utilisation : mise à jour au prochain passage" % app.libelle)
        avertissement = remplacer_appimage(app, installee, cache, dest)
    finally:
        effacer(cache)
    try:
        noter_appimage(app.nom, tag, attendu)
    except OSError as exc:
        avertissement = (avertissement + "\n" if avertissement else "") + \
            "état non enregistré : %s" % exc
    return Resultat(app.nom, MIS_A_JOUR, titre, avertissement, installe, tag, notes_release(release))


def mod_appimages(simulation):
    resultats = []
    for app in appimages_suivies():
        try:
            r = maj_appimage(app, simulation, PROC)
        except Exception as exc:
            r = Resultat(app.nom, ECHEC, "%s : %s" % (app.libelle, exc), "")
        if r is not None:
            resultats.append(r)
    return resultats
