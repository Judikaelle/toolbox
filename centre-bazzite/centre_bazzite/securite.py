"""Sécurité de la machine : ports ouverts, pare-feu, fichiers de démarrage suspects, binaires dans les dossiers
temporaires (lecture seule, aucun droit administrateur)."""
# Repris et adapté de Bilan Santé PC de BiasedMonkey, https://github.com/BiasedMonkey/bilan-sante (GPL-3.0).
import ipaddress
import os
import re
import stat
import sys
from pathlib import Path

from . import commun, config, demarrage

PROGRAMMES_CONNUS = frozenset({
    "steam", "steamwebhelper", "kdeconnectd", "spotify", "zen", "firefox", "chrome", "chromium", "brave",
    "discord", "Discord", "avahi-daemon", "systemd-resolve", "cupsd", "NetworkManager", "chronyd", "sshd",
    "syncthing", "qbittorrent", "transmission", "sunshine", "Socket Process"})
_PROG = re.compile(r'users:\(\("([^"]+)"')


def lire_ss(texte):
    """Écoutes d'une sortie `ss -tulpnH` ; les lignes illisibles sont ignorées."""
    sortie = []
    for ligne in (texte or "").splitlines():
        champs = ligne.split()
        if len(champs) < 5 or champs[0] not in ("tcp", "udp"):
            continue
        hote, _, port = champs[4].rpartition(":")
        if not port.isdigit():
            continue
        hote = hote.split("%")[0].strip("[]")
        prog = _PROG.search(ligne)
        sortie.append({"proto": champs[0], "hote": hote, "port": int(port),
                       "prog": prog.group(1) if prog else None})
    return sortie


def _expose(hote):
    """Vrai si l'adresse d'écoute accepte le réseau (ni boucle locale ni multicast)."""
    if hote in ("*", ""):
        return True
    try:
        adresse = ipaddress.ip_address(hote)
    except ValueError:
        return False
    return not (adresse.is_loopback or adresse.is_multicast)


def ports(texte, serveurs_connus=()):
    """Ports exposés, classés : programmes inconnus (tcp), programmes connus, ports sans programme visible."""
    connus_tous = PROGRAMMES_CONNUS | set(serveurs_connus)
    exposes = [e for e in lire_ss(texte) if _expose(e["hote"])]
    inconnus, connus = {}, {}
    for prog in {e["prog"] for e in exposes if e["prog"]}:
        siens = [e for e in exposes if e["prog"] == prog]
        tcp = {e["port"] for e in siens if e["proto"] == "tcp"}
        if prog not in connus_tous and tcp:
            inconnus[prog] = tcp
            udp = {e["port"] for e in siens if e["proto"] == "udp"}
            if udp:             # l'UDP d'un programme inconnu reste visible, chez les connus
                connus[prog] = udp
        else:
            connus[prog] = {e["port"] for e in siens}
    systeme = {e["port"] for e in exposes if not e["prog"]}
    liste = lambda d: [{"prog": p, "ports": sorted(v)} for p, v in sorted(d.items())]
    return {"inconnus": liste(inconnus), "connus": liste(connus), "systeme": sorted(systeme)}


def pare_feu(run=None):
    """État de firewalld : {"actif", "zone", "ports", "services", "ouvre_hauts"}, ou None si illisible.
    On décide par le code de sortie de `firewall-cmd --state` : 0 (et « running ») actif, 252 (NOT_RUNNING) arrêté ;
    tout autre code (délai dépassé, erreur D-Bus 36, 253, 254...) : repli sur `systemctl is-active firewalld`."""
    run = run or commun.run
    # firewall-cmd réessaie 10 × 1 s quand firewalld est arrêté : 3 s, puis systemctl répond vite
    code, sortie = run(["firewall-cmd", "--state"], timeout=3)
    arrete = {"actif": False, "zone": None, "ports": [], "services": [], "ouvre_hauts": False}
    if code == 252:
        return arrete
    if code != 0 or "running" not in sortie.split():
        code, sortie = run(["systemctl", "is-active", "firewalld"], timeout=10)
        etat = sortie.strip()
        if code == 0 and etat == "active":
            return {"actif": True, "zone": None, "ports": [], "services": [], "ouvre_hauts": False}
        if code == 3 and etat in ("inactive", "failed"):
            return arrete
        return None                 # dont 4 : unité inconnue, firewalld absent ou illisible

    def lire(*args):
        c, s = run(["firewall-cmd", *args], timeout=10)
        return s.split() if c == 0 else []
    zone = lire("--get-default-zone")
    ouverts = lire("--list-ports")
    return {"actif": True, "zone": zone[0] if zone else None, "ports": ouverts,
            "services": lire("--list-services"), "ouvre_hauts": "1025-65535/tcp" in ouverts}


# --- Fichiers de démarrage suspects ---
# Repris et adapté de Bilan Santé PC de BiasedMonkey, https://github.com/BiasedMonkey/bilan-sante (GPL-3.0) :
# MOTIFS_SUSPECTS, _fichiers_demarrage, fichiers_demarrage (sans le motif npm de l'attaque AUR, ni les empreintes).
MOTIFS_SUSPECTS = [
    ("echec", "télécharge et exécute un script", re.compile(
        r"(curl|wget)\b[^\n|;]*\|\s*(sudo\s+)?(ba|z|da|fi|k)?sh\b|(ba|z)?sh\s+(-c\s+)?[\"']?\$\((curl|wget)|<\((curl|wget)",
        re.I)),
    ("echec", "décode et exécute un contenu caché (base64)", re.compile(
        r"base64\s+(-d|--decode)[^\n]*\|\s*(ba|z)?sh|eval\s*\(?\s*\$?\(?.*base64", re.I)),
    ("echec", "ouvre un accès à distance (shell inversé)", re.compile(
        r"\bnc(at)?\s+[^\n]*-[ec]\b|/dev/tcp/|socat\s[^\n]*exec:|python[23]?\s+-c\s+[\"'][^\n]*socket", re.I)),
    ("echec", "remplace sudo/su par autre chose", re.compile(
        r"^\s*(alias\s+(?P<nom>sudo|su|pkexec|passwd|doas)\s*=(?![\"']?(?P=nom)\s*[\"']?\s*$)|function\s+(sudo|su|pkexec|passwd)\b"
        r"|(sudo|su|pkexec|passwd)\s*\(\)\s*\{)")),
    ("attention", "précharge une bibliothèque dans tous les programmes (LD_PRELOAD)",
     re.compile(r"LD_PRELOAD\s*=", re.I)),
    ("attention", "lance quelque chose depuis un dossier temporaire",
     re.compile(r"(^|[\s\"'=])(/tmp|/dev/shm|/var/tmp)/(?!\.mount_)\S+")),
    ("attention", "contacte une adresse du réseau Tor (.onion)", re.compile(r"\b[a-z2-7]{16,56}\.onion\b", re.I)),
]
LECTURE_MAX = 1024 * 1024     # un fichier de démarrage n'est lu que sur son premier Mio
RC_SHELL = (".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zprofile", ".zshenv", ".zlogin",
            ".xprofile", ".xinitrc", ".pam_environment")


def chercher(texte):
    """Le premier motif suspect (dans l'ordre de MOTIFS_SUSPECTS), lignes commentées ignorées :
    {"gravite", "quoi", "numero", "ligne"} ou None."""
    lignes = (texte or "").splitlines()
    for gravite, quoi, motif in MOTIFS_SUSPECTS:
        for numero, ligne in enumerate(lignes, 1):
            if ligne.lstrip().startswith("#"):
                continue
            if motif.search(ligne):
                return {"gravite": gravite, "quoi": quoi, "numero": numero, "ligne": ligne.strip()[:200]}
    return None


def _reguliers(chemins):
    return sorted(f for f in chemins if f.is_file())


ROLE_UNITE_DIRECTE = "service systemd personnel (hors page Démarrage)"


def fichiers_demarrage(home, etc, autostart, unites):
    """[(fichier, rôle)] de ce qui s'exécute tout seul : rc des shells, fish, session Plasma, services et profils
    système, puis les *.desktop d'autostart et les unités `systemd --user` passés en liste. Fichiers réguliers
    seulement ; tout chemin sous /usr/ (image signée, en lecture seule) est sauté."""
    home, etc = Path(home), Path(etc)
    fish = home / ".config" / "fish"
    trouves = [(home / nom, "script du shell") for nom in RC_SHELL]
    trouves.append((fish / "config.fish", "configuration de fish"))
    trouves += [(f, "configuration de fish") for f in _reguliers((fish / "conf.d").glob("*.fish"))]
    trouves += [(f, "fonction fish") for f in _reguliers((fish / "functions").glob("*.fish"))]
    trouves += [(f, "script de session Plasma") for f in _reguliers((home / ".config" / "plasma-workspace" / "env").glob("*"))]
    trouves += [(f, "service systemd système") for f in _reguliers((etc / "systemd" / "system").glob("*.service"))]
    trouves += [(f, "profil du shell (système)") for f in _reguliers((etc / "profile.d").glob("*"))]
    trouves += [(Path(f), "démarrage automatique") for f in autostart]
    # les unités du dossier personnel sont lues en direct (un service statique, déclenché par un minuteur de même
    # nom, ne sort pas de `systemctl --user list-unit-files`) ; celles de `unites` ne sont lues qu'une fois
    directes = _reguliers(list((home / ".config" / "systemd" / "user").glob("*.service"))
                          + list((home / ".config" / "systemd" / "user").glob("*.timer")))
    listees = {Path(f).resolve() for f in unites}       # celles que la page Démarrage affiche
    trouves += [(f, "service systemd personnel" if f.resolve() in listees else ROLE_UNITE_DIRECTE) for f in directes]
    vus = {f.resolve() for f in directes}
    for f in map(Path, unites):
        if f.resolve() not in vus:
            vus.add(f.resolve())
            trouves.append((f, "service systemd personnel"))
    return [(f, r) for f, r in trouves if not str(f).startswith("/usr/") and f.is_file()]


def _lire_ou_lever(chemin):
    """Le texte d'un fichier régulier (suivi à travers un lien : les dotfiles en sont souvent), None pour tout autre
    type (tube, périphérique : l'ouverture non bloquante évite de rester pendu) ; lève OSError si illisible."""
    fd = os.open(chemin, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        return f.read(LECTURE_MAX).decode("utf-8", errors="replace")


def _lire(chemin):
    try:
        return _lire_ou_lever(chemin)
    except OSError:
        return None


def demarrage_suspect(fichiers, incomplet=False):
    """{"lus", "incomplet", "trouves": [{"chemin", "role", "gravite", "quoi", "numero", "ligne"}]} ; un fichier
    illisible n'est ni compté ni signalé. `incomplet` : les unités n'ont pas pu être listées."""
    lus, trouves = 0, []
    for fichier, role in fichiers:
        texte = _lire(fichier)
        if texte is None:
            continue
        lus += 1
        t = chercher(texte)
        if t:
            trouves.append({"chemin": str(fichier), "role": role, **t})
    return {"lus": lus, "incomplet": incomplet, "trouves": trouves}


def ld_preload(chemin=Path("/etc/ld.so.preload")):
    """Les lignes non vides de /etc/ld.so.preload (presque toujours vide) ; absent : [] ; illisible : l'erreur est levée
    (la mesure vaut alors None, pas « rien à signaler »)."""
    try:
        texte = _lire_ou_lever(chemin)
    except FileNotFoundError:
        return []
    return [l.strip() for l in (texte or "").splitlines() if l.strip()]


# --- Binaires dans les dossiers temporaires ---
# Repris et adapté de Bilan Santé PC de BiasedMonkey, https://github.com/BiasedMonkey/bilan-sante (GPL-3.0) :
# executables_temporaires et _est_elf.
RACINES_TEMPORAIRES = (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm"))
PLAFOND_FICHIERS = 200_000


def _ouvrir_sans_atime(chemin, drapeaux):
    """Ouvre `chemin` sans rafraîchir son atime (sinon systemd-tmpfiles ne nettoierait plus ce qu'on a lu) ;
    O_NOATIME exige d'être propriétaire : sur PermissionError, on rouvre sans (ces fichiers-là sont rafraîchis)."""
    try:
        return os.open(chemin, drapeaux | os.O_NOATIME)
    except PermissionError:
        return os.open(chemin, drapeaux)


def _est_elf(chemin):
    """Vrai pour un fichier régulier (jamais un lien, un tube ni un périphérique) qui commence par l'en-tête ELF."""
    try:
        fd = _ouvrir_sans_atime(chemin, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return False
    with os.fdopen(fd, "rb") as f:
        try:
            return stat.S_ISREG(os.fstat(f.fileno()).st_mode) and f.read(4) == b"\x7fELF"
        except OSError:
            return False


def _entrees(dossier):
    """Les noms du dossier, lus par un descripteur ouvert sans toucher à l'atime ; illisible : liste vide."""
    try:
        fd = _ouvrir_sans_atime(dossier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return []
    try:
        with os.scandir(fd) as it:
            return [e.name for e in it]
    except OSError:
        return []
    finally:
        os.close(fd)


def _fichiers(racine, ignores=(), lstat=os.lstat):
    """(chemin, lstat) des fichiers et des dossiers sous `racine`, sans suivre les liens ; dossiers illisibles,
    `.mount_*`, `ignores` et autres systèmes de fichiers (comme `find -xdev`) sautés ; une racine ignorée n'est pas
    parcourue. Aucune lecture ne rafraîchit un atime."""
    ignores = {str(i) for i in ignores}
    if str(racine) in ignores:
        return
    try:
        dev = lstat(racine).st_dev
    except OSError:
        return
    pile = [str(racine)]
    while pile:
        dossier = pile.pop()
        for nom in _entrees(dossier):
            chemin = os.path.join(dossier, nom)
            try:
                st = lstat(chemin)
            except OSError:
                continue
            yield chemin, st
            if (stat.S_ISDIR(st.st_mode) and st.st_dev == dev and not nom.startswith(".mount_")
                    and chemin not in ignores):
                pile.append(chemin)


def temporaires(racines=RACINES_TEMPORAIRES, ignores=(), plafond=PLAFOND_FICHIERS):
    """Binaires ELF exécutables dans les dossiers temporaires : {"nombre", "exemples" (5 premiers chemins triés),
    "examines" (fichiers et dossiers), "plafond_atteint"}."""
    trouves, examines, atteint = [], 0, False
    for racine in racines:
        if atteint:
            break
        for chemin, st in _fichiers(racine, ignores):
            if examines >= plafond:
                atteint = True
                break
            examines += 1
            if stat.S_ISREG(st.st_mode) and st.st_mode & 0o111 and _est_elf(chemin):
                trouves.append(chemin)
    trouves.sort()
    return {"nombre": len(trouves), "exemples": trouves[:5], "examines": examines, "plafond_atteint": atteint}


def executables_cache(racine):
    """Les 5 sous-dossiers de `racine` (~/.cache) qui ont le plus de fichiers exécutables : [{"dossier", "nombre"}]."""
    racine = Path(racine)
    comptes, examines = {}, 0
    for chemin, st in _fichiers(racine):
        if examines >= PLAFOND_FICHIERS:        # fichiers et dossiers, comme pour les dossiers temporaires
            break
        examines += 1
        relatif = os.path.relpath(chemin, racine).split(os.sep)
        if len(relatif) > 1 and stat.S_ISREG(st.st_mode) and st.st_mode & 0o111:
            comptes[relatif[0]] = comptes.get(relatif[0], 0) + 1
    ordre = sorted(comptes.items(), key=lambda c: (-c[1], c[0]))[:5]
    return [{"dossier": d, "nombre": n} for d, n in ordre]


# --- Collecte ---

def _essai(nom, fonction):
    """Le résultat d'une mesure, ou None si elle lève : la panne est écrite sur stderr."""
    try:
        return fonction()
    except Exception as exc:
        print(f"sécurité {nom} en échec : {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def _ports(run, serveurs_connus):
    code, sortie = run(["ss", "-tulpnH"], timeout=10)
    if code != 0:
        return None
    return ports(sortie, serveurs_connus)


def _demarrage(run, home, etc):
    autostart = demarrage.fichiers_autostart(etc / "xdg" / "autostart", home / ".config" / "autostart")
    try:
        unites, incomplet = demarrage.fichiers_unites(run), False
    except demarrage.LectureImpossible:
        unites, incomplet = [], True
    return demarrage_suspect(fichiers_demarrage(home, etc, autostart, unites), incomplet)


def collecter(run=None, home=None, etc=Path("/etc"), racines_temporaires=RACINES_TEMPORAIRES,
              preload=Path("/etc/ld.so.preload")):
    """{"pare_feu", "ports", "demarrage", "ld_preload", "temporaires", "cache"} ; une mesure qui échoue vaut None."""
    run = run or commun.run
    home, etc = Path(home) if home is not None else Path.home(), Path(etc)
    reglages = _essai("config", config.securite)   # lu une fois ; en échec, ports et temporaires valent None
    return {
        "pare_feu": _essai("pare_feu", lambda: pare_feu(run)),
        "ports": _essai("ports", lambda: _ports(run, reglages["serveurs_connus"])),
        "demarrage": _essai("demarrage", lambda: _demarrage(run, home, etc)),
        "ld_preload": _essai("ld_preload", lambda: ld_preload(preload)),
        "temporaires": _essai("temporaires", lambda: temporaires(
            racines_temporaires, reglages["temporaires_ignores"])),
        "cache": _essai("cache", lambda: executables_cache(home / ".cache")),
    }
