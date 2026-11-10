"""Outils communs : chemins, commandes, JSON atomique, horodatage, détection de jeu."""
import json
import math
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from . import steam

ETAT = Path.home() / ".local" / "state" / "centre-bazzite"
CACHE = Path.home() / ".cache" / "centre-bazzite"


def run(cmd, timeout=120, entree=None):
    """Exécute la commande ; renvoie (code, stdout + stderr), ou (-1, message) si exception."""
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                           timeout=timeout, input=entree)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:
        return -1, str(exc)


def ecrire_json(chemin, donnees):
    """Écriture atomique : fichier temporaire propre à cet appel, puis os.replace.
    Plusieurs processus écrivent le même fichier (plasmoïde, fenêtre, session, minuteur) :
    un nom temporaire commun ferait échouer l'un ou laisserait un JSON tronqué."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(donnees, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=chemin.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texte)
        os.replace(tmp, chemin)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def lire_json(chemin, defaut):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _arrondi(x, decimales=0):
    """Au plus proche, moitié vers le haut : les mêmes opérations que la copie QML de taille()."""
    f = 10 ** decimales
    return math.floor(x * f + 0.5) / f


def taille(octets):
    """Taille lisible en base 1024, virgule décimale : « 500 Mo », « 1,2 Go », « 239 Go », « 3,3 To ».
    L'arrondi décide de l'unité et des décimales : 9,96 Gio donne « 10 Go », 1023,5 Gio « 1,0 To »."""
    o = max(0, octets or 0)
    mo = _arrondi(o / 1024 ** 2)
    if mo < 1024:
        return f"{mo:.0f} Mo"
    go = _arrondi(o / 1024 ** 3, 1)
    if go < 10:
        return f"{go:.1f}".replace(".", ",") + " Go"
    go = _arrondi(o / 1024 ** 3)
    if go < 1024:
        return f"{go:.0f} Go"
    return f"{_arrondi(o / 1024 ** 4, 1):.1f}".replace(".", ",") + " To"


# Unités décimales de g_format_size (flatpak) : « kB » vaut 1000 octets.
UNITES_SI = {"byte": 1, "bytes": 1, "b": 1, "kb": 10 ** 3, "mb": 10 ** 6, "gb": 10 ** 9, "tb": 10 ** 12, "pb": 10 ** 15}


def lire_taille(texte):
    """Octets d'une taille écrite par flatpak : « 753.1 MB » -> 753 100 000. Avec LC_ALL=C, le nombre et l'unité
    sont séparés par une espace insécable (U+00A0). None si le texte n'est pas une taille."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([A-Za-z]+)\s*", str(texte or "").replace("\u00a0", " "))
    facteur = UNITES_SI.get(m.group(2).lower()) if m else None
    if facteur is None:
        return None
    return round(float(m.group(1).replace(",", ".")) * facteur)


def maintenant():
    return datetime.now().isoformat(timespec="seconds")


def est_jeu(comm, environ):
    """Même règle que freeze-watch : un processus lancé par Steam/umu (SteamGameId)
    qui n'est pas un processus annexe de Wine ou de Steam."""
    m = re.search(rb"(?:^|\0)SteamGameId=([^\0]*)", environ)
    if not m or m.group(1) in (b"", b"0"):
        return False
    c = comm.strip()
    if c.startswith(("wineserver", "steam")) or "winedevice" in c \
            or "explorer" in c or c.endswith(".so"):
        return False
    return True


# RF-I1 : les processus qui portent SteamGameId sans être le jeu (lanceur de Steam, conteneur, services de Wine). Ils
# ne servent qu'à choisir le nom montré : la présence d'un jeu reste la règle de est_jeu.
ENVELOPPES = frozenset(("reaper", "pv-adverb", "srt-bwrap", "bwrap", "python3", "umu-run", "proton", "steam.exe",
                        "wineserver", "explorer.exe", "services.exe", "winedevice.exe", "plugplay.exe", "svchost.exe",
                        "rpcss.exe"))


def _enveloppe(nom):
    nom = nom.lower()
    return nom in ENVELOPPES or nom.startswith("pressure-vessel")


def _temps_processeur(dossier):
    """utime + stime de <pid>/stat (champs 14 et 15), en tops d'horloge ; le nom entre parenthèses peut contenir des
    espaces et des parenthèses, d'où la dernière « ) »."""
    stat = (Path(dossier) / "stat").read_bytes()
    champs = stat[stat.rindex(b")") + 1:].split()
    return int(champs[11]) + int(champs[12])


def _nom_par_processeur(proc):
    """Parmi les processus de jeu (est_jeu), hors enveloppes, le nom de celui qui a pris le plus de temps processeur
    (comme freeze-watch), ou None."""
    meilleur, temps_max = None, -1
    for p in Path(proc).iterdir():
        if not p.name.isdigit():
            continue
        try:
            comm = (p / "comm").read_bytes().decode("utf-8", errors="replace")
            nom = comm.strip()
            if not nom or _enveloppe(nom) or not est_jeu(comm, (p / "environ").read_bytes()):
                continue
            temps = _temps_processeur(p)
        except (OSError, ValueError, IndexError):
            continue
        if temps > temps_max:
            meilleur, temps_max = nom, temps
    return meilleur


def _nommer(proc, environ, premier, home):
    """RF-I1 : le nom à montrer pour un jeu déjà détecté : celui de l'appmanifest de SteamGameId, sinon le processus de
    jeu le plus gourmand hors enveloppes, sinon `premier` (le comportement d'avant). Une erreur à une étape passe à la
    suivante : jamais d'exception (seules les Exception sont attrapées : le SystemExit du SIGTERM du service passe)."""
    try:
        m = re.search(rb"(?:^|\0)SteamGameId=([^\0]*)", environ)
        nom = steam.nom_du_jeu(m.group(1).decode("ascii"), home) if m else None
        if nom:
            return nom
    except Exception:
        pass
    try:
        nom = _nom_par_processeur(proc)
        if nom:
            return nom
    except Exception:
        pass
    return premier


def jeu_en_cours(proc=Path("/proc"), *, home=None):
    """Le nom du jeu qui tourne, ou None. La présence est celle du premier processus de jeu (est_jeu) : elle décide du
    mode jeu et ne dépend jamais de la recherche du nom (RF-I1, voir _nommer ; `home` : où chercher Steam, le vrai
    home par défaut). `comm` est lu en octets : le noyau le coupe à 15 octets, parfois au milieu d'un caractère, et un
    nom illisible ne doit jamais faire lever la détection (W7)."""
    for p in Path(proc).iterdir():
        if not p.name.isdigit():
            continue
        try:
            comm = (p / "comm").read_bytes().decode("utf-8", errors="replace")
            environ = (p / "environ").read_bytes()
            if not est_jeu(comm, environ):
                continue
        except (OSError, ValueError):
            continue
        premier = comm.strip()
        return _nommer(proc, environ, premier, home) if premier else premier
    return None
