"""Aides communes aux outils de mise à jour : chemins, états, exécution, GitHub, téléchargement vérifié."""

import hashlib
import json
import re
import shutil
import socket
import subprocess
import urllib.request
from collections import namedtuple
from pathlib import Path


HOME = Path.home()
BIN = HOME / ".local/bin"
LIB = HOME / ".local/lib"
SHARE = HOME / ".local/share"
ETAT = HOME / ".local/state/maj-apps"
CACHE = HOME / ".cache/maj-apps"
RAPPORT = ETAT / "rapport.txt"
HISTORIQUE = ETAT / "historique.jsonl"
NOTIFIE = ETAT / "deja-signale.json"
BREW_BIN = Path("/home/linuxbrew/.linuxbrew/bin")
PROC = Path("/proc")

CODE_REPORTE = 75

A_JOUR, MIS_A_JOUR, A_FAIRE, MANUEL, REPORTE, ECHEC = (
    "à jour", "mis à jour", "à mettre à jour", "à faire", "reporté", "échec")
PUCE = {A_JOUR: "·", MIS_A_JOUR: "+", A_FAIRE: "→", MANUEL: "!", REPORTE: "~", ECHEC: "!!"}

Resultat = namedtuple("Resultat", "module etat message details de vers notes",
                      defaults=(None, None, None))


def run(cmd, timeout=120, cwd=None):
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return -1, str(exc)


def version(texte):
    """Premier numéro de version X.Y[.Z] trouvé dans le texte, en tuple d'entiers."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", texte or "")
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def version_ge(nom):
    """GE-Proton11-12[-x86_64] -> (11, 12)."""
    m = re.match(r"GE-Proton(\d+)-(\d+)", nom or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def fmt(v):
    return ".".join(str(x) for x in v) if v else "?"


def github(depot):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % depot,
        headers={"User-Agent": "maj-apps", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def notes_release(release):
    return (release.get("body") or "")[:20000]


def asset(release, nom):
    for a in release.get("assets", []):
        if a.get("name") == nom:
            return a["browser_download_url"], a.get("digest") or ""
    raise RuntimeError("fichier %s absent de la release %s" % (nom, release.get("tag_name")))


def telecharger(url, dest, digest):
    """Télécharge url vers dest en vérifiant la somme SHA-256 publiée par GitHub.
    Sans somme publiée, on refuse : on n'installe rien qu'on ne peut pas vérifier."""
    dest = Path(dest)
    if not digest.startswith("sha256:"):
        raise RuntimeError("aucune somme SHA-256 publiée pour %s : téléchargement refusé" % dest.name)
    attendu = digest.split(":", 1)[1].lower()
    dest.parent.mkdir(parents=True, exist_ok=True)
    partiel = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "maj-apps"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(partiel, "wb") as fh:
            while bloc := r.read(1 << 20):
                h.update(bloc)
                fh.write(bloc)
    except BaseException:
        partiel.unlink(missing_ok=True)
        raise
    if h.hexdigest() != attendu:
        partiel.unlink(missing_ok=True)
        raise RuntimeError("somme SHA-256 incorrecte pour %s : fichier rejeté" % dest.name)
    partiel.replace(dest)
    return dest


def effacer(*chemins):
    for c in chemins:
        c = Path(c)
        if c.is_symlink() or c.is_file():
            c.unlink(missing_ok=True)
        elif c.exists():
            shutil.rmtree(c, ignore_errors=True)


def service_actif(nom):
    code, _ = run(["systemctl", "--user", "is-active", "--quiet", nom], timeout=15)
    return code == 0


def reseau_ok():
    try:
        socket.create_connection(("api.github.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


def est_script_pip(chemin):
    """Point d'entrée généré par pip (« #!python / import sys / from paquet import … »).
    Il appartient à un paquet installé avec pip --user : ce n'est pas une vieille copie."""
    try:
        with open(chemin, "rb") as fh:
            debut = fh.read(400)
    except OSError:
        return False
    premiere = debut.split(b"\n", 1)[0]
    return premiere.startswith(b"#!") and b"python" in premiere \
        and b"\nimport sys\n" in debut and b"\nfrom " in debut
