"""Démarrage : durée (systemd-analyze), ce qui ralentit, historique des démarrages et résumé pour etat.json ; ce qui
se lance tout seul (autostart XDG, unités systemd de l'utilisateur) et les services système (lecture seule).
Le relevé n'écrit que dans `dossier` (par défaut commun.ETAT, calculé à l'appel). Seuls `regler` et `remettre`
touchent au bureau, et seulement là : un fichier de ~/.config/autostart ou `systemctl --user enable|disable`
(jamais sudo). Les commandes et les dossiers sont injectables."""
import math
import os
import re
import shutil
import statistics
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import commun, modejeu, taches

TIMEOUT = 30
GARDE_HISTORIQUE = 30
VOISINS = 10                    # démarrages d'avant pris pour « habituel » et pour la référence du point
MIN_HABITUEL = 3
MIN_REFERENCE = 5
MIN_ECART_S = 5.0
FACTEUR_LENT = 1.3
MIN_RALENTISSEUR_S = 1.0
MIN_FOND_S = 5.0
SEUIL_UNITE_LENTE_S = 10.0
MAX_RALENTISSEURS = 5
MAX_FOND = 3

PHASES = ("firmware", "loader", "kernel", "initrd", "userspace")
NOMS_PHASES = {"firmware": "Firmware (BIOS/UEFI)", "loader": "Chargeur de démarrage", "kernel": "Noyau",
               "initrd": "initrd", "userspace": "Espace utilisateur"}
SEUILS_PHASES = {"firmware": 10.0, "loader": 5.0, "kernel": 10.0, "initrd": 10.0, "userspace": 20.0}
# Phases à une seule cause : candidates à « ce qui ralentit le plus » avec les unités.
PHASES_CANDIDATES = ("firmware", "loader")

EXPLICATIONS_PHASES = {
    "firmware": "Le BIOS/UEFI de la carte mère teste la mémoire et les périphériques avant même Linux. "
                "Health Hub n'y peut rien : ça se règle dans le BIOS (démarrage rapide, « Fast Boot »).",
    "loader": "Le menu de démarrage (GRUB) et le chargement du noyau. "
              "Au-delà de quelques secondes, c'est souvent le délai d'attente du menu.",
    "kernel": "Le noyau Linux prépare le matériel.",
    "initrd": "Le petit système de démarrage prépare les disques avant de lancer le vrai système.",
    "userspace": "Les services du système démarrent, jusqu'à l'écran de connexion.",
}
EXPLICATIONS = {
    "NetworkManager-wait-online.service":
        "Le système attend que le réseau soit connecté avant de finir de démarrer : sur Bazzite, le contrôle du "
        "démarrage (greenboot) l'attend. Le couper fait gagner ce temps, mais un service qui a besoin du réseau "
        "dès le démarrage peut alors échouer.",
    "uupd.service": "Les mises à jour automatiques de Bazzite. Elles tournent en arrière-plan après le démarrage, "
                    "sans retarder le bureau.",
    "greenboot-healthcheck.service": "Bazzite vérifie que le démarrage s'est bien passé (greenboot).",
    "bootc-update-ca-trust.service": "Mise à jour des certificats de sécurité du système.",
    "dracut-pre-udev.service": "Étape de l'initrd qui précède la détection du matériel "
                               "(chargement des modules du noyau).",
    "systemd-udev-settle.service": "Attente de la fin de la détection du matériel, pour de vieux services "
                                   "qui en ont besoin.",
    "plymouth-quit-wait.service": "Attente de la fin de l'écran de démarrage.",
    # Idées reprises et adaptées de « Bilan Santé » (BiasedMonkey/bilan-sante, verifs_demarrage.py, GPL-3.0).
    "ModemManager.service": "Gère les modems 3G/4G. Sans modem, il ne sert à rien, mais il ne retarde pas le bureau.",
    "lvm2-monitor.service": "Surveille les volumes LVM. Inutile si tu n'utilises pas LVM.",
    "systemd-binfmt.service": "Enregistre les formats d'exécutables (Wine, AppImage…). Rarement gênant.",
}

_UNITES = {"h": 3600.0, "min": 60.0, "s": 1.0, "ms": 0.001, "us": 1e-6, "µs": 1e-6, "μs": 1e-6, "d": 86400.0}
_MORCEAU = re.compile(r"(\d+(?:\.\d+)?)(min|ms|us|µs|μs|h|d|s)")


def duree_s(texte):
    """« 1h 2min 3.456s », « 865ms », « 12µs »… en secondes ; None si ce n'est pas une durée."""
    reste = (texte or "").strip()
    if not reste:
        return None
    total, pos = 0.0, 0
    while pos < len(reste):
        m = _MORCEAU.match(reste, pos)
        if not m:
            return None
        total += float(m.group(1)) * _UNITES[m.group(2)]
        pos = m.end()
        while pos < len(reste) and reste[pos] == " ":
            pos += 1
    return total


def _arrondi(x, decimales=0):
    f = 10 ** decimales
    return math.floor(x * f + 0.5) / f


def duree_lisible(s):
    """4,6 s ; 15 s ; 1 min 5 s."""
    s = max(0.0, float(s))
    dixiemes = _arrondi(s, 1)
    if dixiemes < 10:
        return f"{dixiemes:.1f}".replace(".", ",") + " s"
    entier = int(_arrondi(s))
    if entier < 60:
        return f"{entier} s"
    h, reste = divmod(entier, 3600)
    m, sec = divmod(reste, 60)
    morceaux = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else []) + ([f"{sec} s"] if sec else [])
    return " ".join(morceaux)


def lire_time(texte):
    """`systemd-analyze time` -> {"total", "phases": {cle: secondes}} ; None si le démarrage n'est pas fini ou illisible."""
    texte = texte or ""
    if "not yet finished" in texte:
        return None
    m = re.search(r"Startup finished in (.+?)\s*=\s*(.+?)\s*$", texte, re.M)
    if not m:
        return None
    total = duree_s(m.group(2))
    if total is None:
        return None
    phases = {}
    for valeur, cle in re.findall(r"(?:^|\+)\s*(.+?)\s+\((\w+)\)", m.group(1)):
        s = duree_s(valeur)
        if cle in PHASES and s is not None:
            phases[cle] = s
    ordonnees = {k: phases[k] for k in PHASES if k in phases}
    return {"total": total, "phases": ordonnees}


def lire_blame(texte):
    """`systemd-analyze blame` -> [(unité, secondes)] dans l'ordre de la sortie, sans les .device."""
    res = []
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if " " not in ligne:
            continue
        valeur, unite = ligne.rsplit(None, 1)
        s = duree_s(valeur)
        if s is None or unite.endswith(".device"):
            continue
        res.append((unite, s))
    return res


_PREFIXE_ARBRE = re.compile(r"^[\s│|]*(?:└─|├─|`-|\|-)?")
_LIGNE_CHAINE = re.compile(r"^(\S+)\s+@(.*?)(?:\s+\+(.+))?$")


def lire_chaine(texte):
    """`systemd-analyze critical-chain` -> {unité: secondes propres}, seulement les unités qui ont un « + »."""
    res = {}
    for ligne in (texte or "").splitlines():
        reste = ligne[_PREFIXE_ARBRE.match(ligne).end():].rstrip()
        m = _LIGNE_CHAINE.match(reste)
        if not m or m.group(3) is None:
            continue
        s = duree_s(m.group(3))
        if s is not None:
            res.setdefault(m.group(1), s)
    return res


def _explication_unite(unite, secondes):
    return EXPLICATIONS.get(unite) or (f"{unite} a pris {duree_lisible(secondes)} au démarrage. S'il tourne en "
                                       "parallèle des autres, il ne retarde pas forcément l'arrivée au bureau.")


def _unite(unite, s, type_, portee):
    return {"id": f"unite:{unite}", "nom": unite, "secondes": s, "duree": duree_lisible(s), "type": type_,
            "lent": s >= SEUIL_UNITE_LENTE_S, "portee": portee, "explication": _explication_unite(unite, s)}


def ralentisseurs(duree, blame, chaine, session=()):
    """(ce qui ralentit le plus, ce qui tourne en arrière-plan) : voir la décision D2. `session` : `--user blame` ; ses
    unités d'au moins 5 s (hors .device) rejoignent seulement « en arrière-plan », avec la portée « session »."""
    candidats, fond = [], []
    for p in (duree or {}).get("phases") or []:
        if p["cle"] in PHASES_CANDIDATES and p["secondes"] >= MIN_RALENTISSEUR_S:
            candidats.append({"id": f"phase:{p['cle']}", "nom": p["nom"], "secondes": p["secondes"],
                              "duree": duree_lisible(p["secondes"]), "type": "phase", "lent": bool(p.get("lent")),
                              "portee": "systeme", "explication": EXPLICATIONS_PHASES[p["cle"]]})
    for unite, s in blame or []:
        if s < MIN_RALENTISSEUR_S:
            continue
        if unite in chaine:
            type_ = "bureau"
        elif unite.startswith(("dracut-", "initrd-")):
            type_ = "initrd"
        else:
            type_ = "fond"
        r = _unite(unite, s, type_, "systeme")
        if type_ == "fond":
            if s >= MIN_FOND_S:
                fond.append(r)
        else:
            candidats.append(r)
    fond.extend(_unite(unite, s, "fond", "session") for unite, s in session or ()
                if s >= MIN_FOND_S and not unite.endswith(".device"))
    candidats.sort(key=lambda r: -r["secondes"])
    fond.sort(key=lambda r: -r["secondes"])
    return candidats[:MAX_RALENTISSEURS], fond[:MAX_FOND]


def noter(historique, boot_id, debut, total):
    """Ajoute le démarrage une seule fois (par boot_id) ; garde les 30 derniers, le plus ancien d'abord."""
    res = [e for e in historique if isinstance(e, dict)]
    if boot_id and not any(e.get("boot_id") == boot_id for e in res):
        res.append({"boot_id": boot_id, "debut": debut, "total": float(total)})
    return res[-GARDE_HISTORIQUE:]


def _total(entree):
    t = entree.get("total") if isinstance(entree, dict) else None
    return float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def _totaux(historique):
    return [t for t in map(_total, historique or []) if t is not None]


def habituel(historique, boot_id):
    """(médiane, totaux) des 10 démarrages d'avant celui-ci (le plus récent d'abord) ; médiane None sous 3."""
    historique = [e for e in historique or [] if isinstance(e, dict)]
    ids = [e.get("boot_id") for e in historique]
    avant = historique[:ids.index(boot_id)] if boot_id in ids else historique
    totaux = list(reversed(_totaux(avant)[-VOISINS:]))
    return (statistics.median(totaux) if len(totaux) >= MIN_HABITUEL else None), totaux


def lent(historique):
    """Les 3 derniers démarrages dépassent chacun max(1,3 × réf, réf + 5 s) ; réf = médiane des 10 d'avant (≥ 5)."""
    totaux = _totaux(historique)
    derniers, avant = totaux[-3:], totaux[:-3][-VOISINS:]
    if len(derniers) < 3 or len(avant) < MIN_REFERENCE:
        return None
    ref = statistics.median(avant)
    seuil = max(FACTEUR_LENT * ref, ref + MIN_ECART_S)
    if all(t > seuil for t in derniers):
        return {"total": derniers[-1], "reference": ref}
    return None


def _btime_proc():
    """L'allumage (btime de /proc/stat) en ISO, ou None."""
    try:
        for ligne in Path("/proc/stat").read_text(encoding="ascii").splitlines():
            if ligne.startswith("btime "):
                return datetime.fromtimestamp(int(ligne.split()[1])).isoformat(timespec="seconds")
    except (OSError, ValueError, IndexError):
        pass
    return None


def _erreur(quoi, texte, sous=""):
    ligne = next((l.strip() for l in (texte or "").splitlines() if l.strip()), "sans réponse")
    return f"{quoi} (systemd-analyze{sous} : {ligne[:120]})"


def _pas_fini(texte):
    """« Bootup is not yet finished » : `time` et `critical-chain` refusent tant que le démarrage n'est pas fini."""
    return "not yet finished" in (texte or "")


def _commande(run, sous, avec_pager=False):
    cmd = ["env", "LC_ALL=C", "systemd-analyze", sous] + (["--no-pager"] if avec_pager else [])
    return run(cmd, timeout=TIMEOUT)


BLAME_SESSION = ["env", "LC_ALL=C", "systemd-analyze", "--user", "blame", "--no-pager"]


def _blame_session(run):
    """Les unités de ta session (`systemd-analyze --user blame`) ; un échec (bus de session absent…) ne dit rien : la
    liste reste vide. Idée reprise de « Bilan Santé » (BiasedMonkey/bilan-sante, verifs_demarrage.py, GPL-3.0)."""
    code, texte = run(BLAME_SESSION, timeout=TIMEOUT)
    return lire_blame(texte) if code == 0 else []


def construire(*, run=commun.run, boot=taches.boot_id, btime=None, dossier=None, lancement=None, systeme=None,
               retour=None):
    """Relève la durée, ce qui ralentit, ce qui se lance tout seul et les services système ; l'historique du dossier
    donne l'« habituel ». N'écrit rien. Par défaut, `lancement` et `systeme` lisent la vraie machine avec `run`.
    `retour` : le résultat d'un `regler` ou d'un `remettre` ({"id", "code", "phrase", "date"}), recopié pour la
    fenêtre ; None pour un simple relevé (il efface le retour d'avant)."""
    dossier = Path(dossier) if dossier is not None else commun.ETAT
    lancement = lancement or (lambda: au_lancement(run=run, dossier=dossier))
    systeme = systeme or (lambda blame: services_systeme(run=run, blame=blame))
    btime = btime or _btime_proc
    erreurs = []
    boot_id = boot()

    code, texte = _commande(run, "time")
    lu = lire_time(texte)
    duree = None
    pas_fini = _pas_fini(texte)
    if lu:
        phases = [{"cle": k, "nom": NOMS_PHASES[k], "secondes": s, "duree": duree_lisible(s),
                   "lent": s > SEUILS_PHASES[k]} for k, s in lu["phases"].items()]
        duree = {"total": lu["total"], "phases": phases}
    elif not pas_fini:
        erreurs.append(_erreur("Durée illisible", texte))

    # Démarrage pas fini (I-3) : `blame` répond, ou refuse, avec une liste partielle, et `critical-chain` refuse. Ce
    # n'est pas une erreur ; blame trie seulement l'onglet Système, et rien n'est classé (sans la chaîne, « en
    # arrière-plan, sans retarder le bureau » serait faux).
    code, texte = _commande(run, "blame", True)
    blame = lire_blame(texte) if code == 0 else []
    if code != 0 and not pas_fini:
        erreurs.append(_erreur("Services lents illisibles", texte, " blame"))
    chaine = {}
    if not pas_fini:
        code, texte = _commande(run, "critical-chain", True)
        if code == 0:
            chaine = lire_chaine(texte)
        elif _pas_fini(texte):          # fini entre `time` et `critical-chain` : comme pas fini
            pas_fini = True
        else:
            erreurs.append(_erreur("Chaîne de démarrage illisible", texte, " critical-chain"))

    liste, fond = ([], []) if pas_fini else ralentisseurs(duree, blame, chaine, _blame_session(run))
    historique = commun.lire_json(dossier / "demarrages.json", [])
    usuel, precedents = habituel(historique if isinstance(historique, list) else [], boot_id)
    # Une lecture qui échoue (bus de session absent…) laisse sa partie vide et le dit, sans faire tomber le relevé.
    try:
        au_lanc = lancement()
    except Exception as exc:
        erreurs.append(f"Ce qui se lance tout seul illisible ({exc})")
        au_lanc = {"entrees": [], "ignorees": 0}
    if isinstance(au_lanc, dict) and au_lanc.get("illisible"):     # les applis sont là, pas les unités
        erreurs.append(f"Tes services et minuteurs illisibles ({au_lanc['illisible']})")
    try:
        services = systeme(blame)
    except Exception as exc:
        erreurs.append(f"Services système illisibles ({exc})")
        services = []
    return {"genere": commun.maintenant(), "boot_id": boot_id, "debut": btime(), "duree": duree,
            "habituel": usuel, "precedents": precedents, "ralentisseurs": liste, "arriere_plan": fond,
            "lancement": au_lanc, "systeme": services, "erreurs": erreurs, "retour": retour}


def ecrire(dossier=None, **sources):
    """Écrit demarrage.json ; un démarrage fini entre aussi, une seule fois, dans demarrages.json."""
    dossier = Path(dossier) if dossier is not None else commun.ETAT
    d = construire(dossier=dossier, **sources)
    if d["duree"]:
        historique = commun.lire_json(dossier / "demarrages.json", [])
        historique = noter(historique if isinstance(historique, list) else [], d["boot_id"], d["debut"],
                           d["duree"]["total"])
        commun.ecrire_json(dossier / "demarrages.json", historique)
    chemin = dossier / "demarrage.json"
    commun.ecrire_json(chemin, d)
    return chemin


def resume(dossier=None):
    """Le résumé pour etat.json ; ne lit que demarrage.json et demarrages.json (pas de commande). None si absent."""
    dossier = Path(dossier) if dossier is not None else commun.ETAT
    d = commun.lire_json(dossier / "demarrage.json", None)
    if not isinstance(d, dict):
        return None
    duree = d.get("duree")
    total = duree.get("total") if isinstance(duree, dict) else None
    usuel = d.get("habituel")
    if total is None:
        phrase = "Démarrage en cours de relevé."
    else:
        phrase = f"Démarré en {duree_lisible(total)}"
        if usuel is not None:
            phrase += f" · habituel : {duree_lisible(usuel)}"
    historique = commun.lire_json(dossier / "demarrages.json", [])
    return {"total": total, "habituel": usuel, "phrase": phrase,
            "lent": lent(historique if isinstance(historique, list) else [])}


# --- Ce qui se lance tout seul, services système, régler et remettre (Task 2 ; décisions D4 à D8) ---

JOURNAL = "demarrage-journal.json"
AUTOSTART_SYSTEME = Path("/etc/xdg/autostart")
RACINES_GLOBALES = (Path("/etc/systemd/user"), Path("/usr/lib/systemd/user"), Path("/usr/local/lib/systemd/user"))

# Listes verrouillées (figées par un test) : Health Hub ne propose jamais de les couper.
ESSENTIELS_UTILISATEUR = ("pipewire", "wireplumber", "dbus", "xdg-", "plasma-", "kde", "org.kde.", "at-spi",
                          "systemd-", "gpg-agent", "p11-kit", "gvfs", "grub-boot-success")           # préfixes
ESSENTIELS_AUTOSTART = ("org.kde.plasmashell.desktop", "polkit-kde-authentication-agent-1.desktop",
                        "pam_kwallet_init.desktop", "at-spi-dbus-bus.desktop", "xdg-user-dirs.desktop",
                        "powerdevil.desktop", "kaccess.desktop", "xembedsniproxy.desktop", "gmenudbusmenuproxy.desktop",
                        "org.kde.plasma-fallback-session-restore.desktop")                        # fichiers
ESSENTIELS_SYSTEME = ("systemd-", "dbus", "NetworkManager.service", "polkit", "sddm", "plasmalogin", "gdm",
                      "display-manager", "nvidia-", "bootc-", "rpm-ostree", "ostree-", "greenboot-", "tuned",
                      "power-profiles", "upower", "udisks2", "rtkit", "firewalld", "auditd", "chronyd", "uupd")  # préfixes
# Les unités de Health Hub : modifiables, avec cet avertissement dans la confirmation.
HEALTH_HUB = {
    "centre-bazzite-releve.timer": "Health Hub ne se mettra plus à jour tout seul : ses pages montreront des données "
                                   "anciennes.",
    "health-hub-modejeu.service": "Le mode jeu automatique ne s'activera plus.",
    "maj-apps.timer": "Vicinae, Ollama, uv et distrobox ne seront plus mis à jour la nuit.",
    "bazzite-health.timer": "Plus de bilan de la semaine le lundi.",
}

RAISON_ESSENTIEL = "Essentiel au bureau."
RAISON_PLASMA = "Lancé par un service de Plasma."
RAISON_BAZZITE = "Activé par Bazzite pour tous les comptes."
RAISON_NOM = "Nom de fichier inhabituel : Health Hub n'y touche pas."
A_L_OUVERTURE = "À l'ouverture de session"
A_LA_DEMANDE = "À la demande"
ARRETE = "Arrêté"
SANS_PROCHAINE = "Sans prochaine échéance"
TYPES_UNITES = {".service": "service", ".timer": "minuteur", ".socket": "socket"}

LISTE_UTILISATEUR = ["env", "LC_ALL=C", "systemctl", "--user", "list-unit-files", "--type=service,timer,socket",
                     "--no-legend", "--no-pager"]
# NextElapseUSecMonotonic : un minuteur OnBootSec/OnUnitActiveSec (le relevé horaire) n'a pas de date calendaire.
SHOW_UTILISATEUR = ["env", "LC_ALL=C", "systemctl", "--user", "show", "--timestamp=unix", "-p", "Id", "-p",
                    "Description", "-p", "FragmentPath", "-p", "ActiveState", "-p", "NextElapseUSecRealtime", "-p",
                    "NextElapseUSecMonotonic"]
LISTE_SYSTEME = ["env", "LC_ALL=C", "systemctl", "list-unit-files", "--type=service,timer", "--state=enabled",
                 "--no-legend", "--no-pager"]
SHOW_SYSTEME = ["env", "LC_ALL=C", "systemctl", "show", "-p", "Id", "-p", "Description"]

# Un id n'est accepté que sous l'une de ces formes, puis seulement s'il est retrouvé, modifiable, par une relecture.
_ID_AUTOSTART = re.compile(r"autostart:([A-Za-z0-9._@+-]+\.desktop)")
_ID_UNITE = re.compile(r"unite:([A-Za-z0-9._@:\\-]+\.(?:service|timer|socket))")
_MODELE = re.compile(r"@\.[^.]+$")          # « lecteur@.service » : un modèle sans instance
_ILLISIBLE = object()

INCONNUE = "Entrée inconnue : {id_}."
VERROUILLE = "« {nom} » est verrouillé : Health Hub n'y touche pas."
DEJA = "« {nom} » est déjà dans cet état."
PHRASES_REGLER = {("appli", False): "« {nom} » ne se lancera plus à l'ouverture de session.",
                  ("appli", True): "« {nom} » se lancera à la prochaine ouverture de session.",
                  ("minuteur", False): "Minuteur « {nom} » arrêté.",
                  ("minuteur", True): "Minuteur « {nom} » remis en route."}
REVENU = "« {nom} » est revenu comme avant."
CHANGE = "« {nom} » a changé depuis : rien n'est touché."
RIEN = "Rien à remettre pour {id_}."


class LectureImpossible(Exception):
    """systemctl n'a pas pu lister les unités (bus de session absent…)."""


def _premiere_ligne(texte):
    return next((l.strip() for l in (texte or "").splitlines() if l.strip()), "sans réponse")[:200]


def _sortie(texte, code):
    """La sortie de systemctl sur une ligne, pour « Échec : … »."""
    return " ".join(l.strip() for l in (texte or "").splitlines() if l.strip()) or f"code {code}"


# --- Fichiers .desktop (D6) : lus et écrits ligne à ligne, le reste gardé octet pour octet ---

def _decouper(texte):
    r"""Les lignes avec leur fin (« \n », ou « \r\n » dans la ligne) ; seule « \n » coupe."""
    morceaux = texte.split("\n")
    return [m + "\n" for m in morceaux[:-1]] + ([morceaux[-1]] if morceaux[-1] else [])


def _fin(ligne):
    return "\r\n" if ligne.endswith("\r\n") else "\n" if ligne.endswith("\n") else ""


def _cle(ligne):
    """La clé de « Cle=valeur » (espaces autour enlevés), ou None : ligne vide, commentaire ou en-tête."""
    s = ligne.strip()
    if not s or s.startswith(("#", "[")) or "=" not in s:
        return None
    return s.split("=", 1)[0].strip()


def _section(lignes):
    """(en-tête, fin) de la première section [Desktop Entry], ou None."""
    debut = None
    for i, ligne in enumerate(lignes):
        s = ligne.strip()
        if s.startswith("["):
            if debut is not None:
                return debut, i
            if s == "[Desktop Entry]":
                debut = i
    return (debut, len(lignes)) if debut is not None else None


def lire_desktop(texte):
    """Les clés de [Desktop Entry] ; « Name[fr] » passe avant « Name », « Comment[fr] » avant « Comment »."""
    lignes = _decouper(texte or "")
    zone = _section(lignes)
    res = {}
    if zone is None:
        return res
    for ligne in lignes[zone[0] + 1:zone[1]]:
        cle = _cle(ligne)
        if cle is not None:
            res.setdefault(cle, ligne.split("=", 1)[1].strip())
    for cle in ("Name", "Comment"):
        if f"{cle}[fr]" in res:
            res[cle] = res[f"{cle}[fr]"]
    return res


def _poser(texte, valeurs):
    """`texte` où chaque clé de `valeurs` vaut sa valeur dans [Desktop Entry] : ses lignes sont remplacées, ou une ligne
    est ajoutée après la dernière ligne non vide de la section. Tout le reste est gardé octet pour octet."""
    lignes = _decouper(texte)
    zone = _section(lignes)
    if zone is None:
        raise ValueError("pas de section [Desktop Entry]")
    debut, fin = zone
    manquantes = dict(valeurs)
    for i in range(debut + 1, fin):
        cle = _cle(lignes[i])
        if cle in valeurs:
            lignes[i] = f"{cle}={valeurs[cle]}{_fin(lignes[i])}"
            manquantes.pop(cle, None)
    if manquantes:
        j = max(i for i in range(debut, fin) if lignes[i].strip())
        fin_ligne = _fin(lignes[j]) or _fin(lignes[debut]) or "\n"
        if not _fin(lignes[j]):
            lignes[j] += fin_ligne
        lignes[j + 1:j + 1] = [f"{c}={v}{fin_ligne}" for c, v in manquantes.items()]
    return "".join(lignes)


def _vrai(d, cle):
    return d.get(cle, "").strip().lower() == "true"


def _actif_desktop(d):
    return not (_vrai(d, "Hidden") or d.get("X-GNOME-Autostart-enabled", "").strip().lower() == "false")


def _pour_kde(d, existe):
    """Montrée sous Plasma : OnlyShowIn contient KDE (s'il est là), NotShowIn ne le contient pas, TryExec existe."""
    bureaux = lambda cle: [b.strip() for b in d.get(cle, "").split(";") if b.strip()]
    if "OnlyShowIn" in d and "KDE" not in bureaux("OnlyShowIn"):
        return False
    if "KDE" in bureaux("NotShowIn"):
        return False
    return not d.get("TryExec") or bool(existe(d["TryExec"]))


def _lire_fichier(chemin):
    """Le texte UTF-8 exact (sans conversion des fins de ligne), None si absent, _ILLISIBLE sinon."""
    try:
        return Path(chemin).read_bytes().decode("utf-8")
    except FileNotFoundError:
        return _ILLISIBLE if os.path.lexists(chemin) else None
    except (OSError, UnicodeDecodeError):
        return _ILLISIBLE


def _ecrire_fichier(chemin, texte):
    """Écriture atomique (fichier temporaire du même dossier, puis os.replace) ; None supprime le fichier. Le dossier
    est créé s'il manque ; un fichier remplacé garde ses droits."""
    chemin = Path(chemin)
    if texte is None:
        chemin.unlink(missing_ok=True)
        return
    chemin.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = chemin.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=chemin.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(texte.encode("utf-8"))
        os.chmod(tmp, mode)
        os.replace(tmp, chemin)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- Journal (D7) ---

def _chemin_journal(dossier):
    return (Path(dossier) if dossier is not None else commun.ETAT) / JOURNAL


def lire_journal(dossier=None):
    """{id: {"date", "avant", "apres"}} ; un fichier absent ou abîmé vaut {}."""
    j = commun.lire_json(_chemin_journal(dossier), {})
    return {k: v for k, v in j.items() if isinstance(v, dict)} if isinstance(j, dict) else {}


def _ligne_valide(ligne):
    return isinstance(ligne, dict) and isinstance(ligne.get("avant"), dict) and isinstance(ligne.get("apres"), dict)


def _modifie(journal, id_):
    ligne = (journal or {}).get(id_)
    if not _ligne_valide(ligne):
        return None
    return {"date": ligne.get("date"), "avant": bool(ligne["avant"].get("actif"))}


def _entree(id_, nom, description, type_, actif, groupe, modifiable, raison, quand, avertissement, journal):
    return {"id": id_, "nom": nom, "description": description, "type": type_, "actif": actif, "groupe": groupe,
            "modifiable": modifiable, "raison": raison, "quand": quand, "avertissement": avertissement,
            "modifie": _modifie(journal, id_)}


# --- Applis au démarrage de session (autostart XDG) ---

def _autostart_utilisateur():
    return Path.home() / ".config" / "autostart"


def _desktops(dossier):
    try:
        return [p.name for p in Path(dossier).glob("*.desktop")]
    except OSError:
        return []


def _entree_appli(fichier, texte_systeme, texte_utilisateur, existe, journal):
    """L'Entree d'un fichier autostart, ou None s'il est ignoré (illisible, sans [Desktop Entry], autre bureau, TryExec
    absent). Le fichier utilisateur de même nom remplace celui du système."""
    effectif = texte_utilisateur if texte_utilisateur is not None else texte_systeme
    if not isinstance(effectif, str) or _section(_decouper(effectif)) is None:
        return None
    d = lire_desktop(effectif)
    if not _pour_kde(d, existe):
        return None
    ds = lire_desktop(texte_systeme) if isinstance(texte_systeme, str) else {}
    id_ = f"autostart:{fichier}"
    if fichier in ESSENTIELS_AUTOSTART:
        groupe, modifiable, raison = "essentiel", False, RAISON_ESSENTIEL
    elif _vrai(d, "X-systemd-skip") or _vrai(ds, "X-systemd-skip"):
        groupe, modifiable, raison = "essentiel", False, RAISON_PLASMA
    elif not _ID_AUTOSTART.fullmatch(id_):     # la CLI le refuserait : on ne propose pas de le couper
        groupe, modifiable, raison = "toi", False, RAISON_NOM
    else:
        groupe, modifiable, raison = "toi", True, None
    nom = d.get("Name") or ds.get("Name") or Path(fichier).stem
    description = d.get("Comment") or ds.get("Comment") or ""
    return _entree(id_, nom, description, "appli", _actif_desktop(d), groupe, modifiable, raison, A_L_OUVERTURE, None,
                   journal)


def applis(systeme=None, utilisateur=None, existe=shutil.which, journal=None):
    """(entrées, ignorées) des applis lancées à l'ouverture de session. `systeme` : /etc/xdg/autostart, `utilisateur` :
    ~/.config/autostart (calculés à l'appel). Seuls les *.desktop sont lus ; ignorées = illisibles ou hors Plasma."""
    systeme = Path(systeme) if systeme is not None else AUTOSTART_SYSTEME
    utilisateur = Path(utilisateur) if utilisateur is not None else _autostart_utilisateur()
    journal = journal if isinstance(journal, dict) else {}
    entrees, ignorees = [], 0
    for fichier in sorted(set(_desktops(systeme)) | set(_desktops(utilisateur))):
        e = _entree_appli(fichier, _lire_fichier(systeme / fichier), _lire_fichier(utilisateur / fichier), existe,
                          journal)
        if e is None:
            ignorees += 1
        else:
            entrees.append(e)
    entrees.sort(key=lambda e: e["nom"].casefold())
    return entrees, ignorees


def fichiers_autostart(systeme=None, utilisateur=None, existe=shutil.which):
    """Les fichiers *.desktop effectivement lus pour `applis` (mêmes entrées, même priorité : le fichier utilisateur de
    même nom l'emporte sur celui du système). Ceux qu'`applis` ignore n'y figurent pas."""
    systeme = Path(systeme) if systeme is not None else AUTOSTART_SYSTEME
    utilisateur = Path(utilisateur) if utilisateur is not None else _autostart_utilisateur()
    entrees, _ = applis(systeme, utilisateur, existe)
    fichiers = sorted(e["id"].split(":", 1)[1] for e in entrees)
    return [utilisateur / f if (utilisateur / f).is_file() else systeme / f for f in fichiers]


# --- Unités systemd de l'utilisateur (D4, D5) ---

def _racine_utilisateur():
    return Path.home() / ".config" / "systemd" / "user"


def _donnees_utilisateur():
    return Path.home() / ".local" / "share" / "systemd" / "user"


def _proprietes(texte):
    """`systemctl show` (blocs séparés par une ligne vide) -> {Id: {propriété: valeur}}."""
    res = {}
    for bloc in re.split(r"\n\s*\n", (texte or "").strip()):
        p = {}
        for ligne in bloc.splitlines():
            if "=" in ligne:
                cle, valeur = ligne.split("=", 1)
                p[cle.strip()] = valeur.strip()
        if p.get("Id"):
            res[p["Id"]] = p
    return res


def _noms_lies(racines):
    """Les noms des liens de `<racine>/*.wants` et `*.requires` : les unités que ces racines activent."""
    noms = set()
    for racine in racines:
        try:
            for d in list(Path(racine).glob("*.wants")) + list(Path(racine).glob("*.requires")):
                noms.update(p.name for p in d.iterdir())
        except OSError:
            continue
    return noms


def _dans(fragment, dossiers):
    """Le fichier de l'unité est directement dans l'un des dossiers (liens de /home suivis)."""
    if not fragment:
        return False
    parent = os.path.realpath(Path(fragment).parent)
    return any(parent == os.path.realpath(d) for d in dossiers)


def _lire_unites(run):
    """Les unités candidates de `systemctl --user` : [{"nom", "etat", "active", "prochaine", "description",
    "fragment"}]. Écartées : états autres qu'enabled/disabled (static, indirect, generated, transient, alias, masked…),
    modèles sans instance, et le .service qu'un .timer du même nom déclenche."""
    code, texte = run(LISTE_UTILISATEUR, timeout=TIMEOUT)
    if code != 0:
        raise LectureImpossible(f"systemctl --user list-unit-files : {_premiere_ligne(texte)}")
    etats = {}
    for ligne in texte.splitlines():
        champs = ligne.split()
        if len(champs) >= 2 and champs[0].endswith(tuple(TYPES_UNITES)):
            etats.setdefault(champs[0], champs[1])
    minuteurs = {n[:-len(".timer")] for n in etats if n.endswith(".timer")}
    noms = [n for n, e in etats.items() if e in ("enabled", "disabled") and not _MODELE.search(n)
            and not (n.endswith(".service") and n[:-len(".service")] in minuteurs)]
    props = {}
    if noms:
        code, texte = run(SHOW_UTILISATEUR + noms, timeout=TIMEOUT)
        if code != 0:       # sinon tous les minuteurs seraient « Arrêté », et « Remettre » croirait l'entrée changée
            raise LectureImpossible(f"systemctl --user show : {_premiere_ligne(texte)}")
        props = _proprietes(texte)
    res = []
    for n in noms:
        p = props.get(n, {})
        description = p.get("Description", "")
        res.append({"nom": n, "etat": etats[n], "active": p.get("ActiveState", ""),
                    "prochaine": p.get("NextElapseUSecRealtime", ""),
                    "prochaine_monotone": p.get("NextElapseUSecMonotonic", ""),
                    "description": "" if description == n else description, "fragment": p.get("FragmentPath", "")})
    return res


def fichiers_unites(run=commun.run):
    """Les fichiers (FragmentPath) des unités candidates de `systemctl --user` ; ceux sans chemin sont sautés.
    Lève LectureImpossible si systemctl ne répond pas."""
    return [Path(u["fragment"]) for u in _lire_unites(run) if u["fragment"]]


def _en_date(maintenant):
    if maintenant is None:
        return datetime.now().astimezone()
    if isinstance(maintenant, datetime):
        return maintenant
    return datetime.fromisoformat(str(maintenant))


def quand_minuteur(prochaine, active, maintenant=None, prochaine_monotone="", monotone=time.monotonic):
    """« Prochaine : aujourd'hui à 22 h 30 », « … demain à 04 h 45 », « … le 16 nov. à 10 h 06 » ; « Arrêté » pour un
    minuteur inactif. `prochaine` : NextElapseUSecRealtime en `@<epoch>` (--timestamp=unix) ;
    `prochaine_monotone` : NextElapseUSecMonotonic (« 13h 9min 3.08s » depuis l'allumage, « 0 » ou « infinity » sans
    échéance), ramené à l'heure avec `monotone()` (l'horloge CLOCK_MONOTONIC de systemd). Le plus tôt des deux."""
    if active != "active":
        return ARRETE
    maintenant = _en_date(maintenant)
    echeances = []
    m = re.fullmatch(r"@(\d+)", (prochaine or "").strip())
    if m:
        echeances.append(float(m.group(1)))
    s = duree_s(prochaine_monotone) if prochaine_monotone else None
    if s:
        echeances.append(maintenant.timestamp() + s - monotone())
    if not echeances:
        return SANS_PROCHAINE
    d = datetime.fromtimestamp(min(echeances), tz=maintenant.tzinfo) if maintenant.tzinfo else \
        datetime.fromtimestamp(min(echeances))
    heure = f"{d.hour:02d} h {d.minute:02d}"
    if d.date() == maintenant.date():
        return f"Prochaine : aujourd'hui à {heure}"
    if d.date() == maintenant.date() + timedelta(days=1):
        return f"Prochaine : demain à {heure}"
    return f"Prochaine : le {d.day}{'er' if d.day == 1 else ''} {modejeu.MOIS[d.month - 1]} à {heure}"


def _entree_unite(u, perso, lies_utilisateur, lies_globaux, journal, maintenant, monotone=time.monotonic):
    """L'Entree d'une unité candidate, ou None (unité du fournisseur désactivée, que Health Hub n'a pas touchée)."""
    nom, etat = u["nom"], u["etat"]
    id_ = f"unite:{nom}"
    if etat == "disabled" and not (_dans(u["fragment"], perso) or _ligne_valide(journal.get(id_))):
        return None
    avertissement = None
    if nom in HEALTH_HUB:
        groupe, modifiable, raison, avertissement = "healthhub", True, None, HEALTH_HUB[nom]
    elif nom.startswith(ESSENTIELS_UTILISATEUR):
        groupe, modifiable, raison = "essentiel", False, RAISON_ESSENTIEL
    elif etat == "disabled":
        groupe, modifiable, raison = "toi", True, None
    elif nom in lies_globaux or nom not in lies_utilisateur:
        # un lien pour tous les comptes l'emporte (`systemctl --user disable` n'y peut rien) ; une unité activée
        # sans lien trouvé dans ton dossier reste aussi en lecture seule
        groupe, modifiable, raison = "bazzite", False, RAISON_BAZZITE
    else:
        groupe, modifiable, raison = "toi", True, None
    type_ = TYPES_UNITES[Path(nom).suffix]
    actif = etat == "enabled"
    if type_ == "minuteur":
        quand = quand_minuteur(u["prochaine"], u["active"], maintenant, u["prochaine_monotone"], monotone)
    elif type_ == "socket" or not actif:
        quand = A_LA_DEMANDE
    else:
        quand = A_L_OUVERTURE
    return _entree(id_, nom, u["description"], type_, actif, groupe, modifiable, raison, quand, avertissement, journal)


def _contexte_unites(racine_utilisateur, racines_globales):
    """(dossiers des unités de l'utilisateur, unités liées par l'utilisateur, unités liées pour tous les comptes)."""
    racine = Path(racine_utilisateur) if racine_utilisateur is not None else _racine_utilisateur()
    globales = tuple(racines_globales) if racines_globales is not None else RACINES_GLOBALES
    return (racine, _donnees_utilisateur()), _noms_lies([racine]), _noms_lies(globales)


def unites_utilisateur(run=commun.run, racine_utilisateur=None, racines_globales=None, journal=None, maintenant=None,
                       monotone=time.monotonic):
    """Les Entree des services, minuteurs et sockets de `systemctl --user` (groupes : décision D4). Lève
    LectureImpossible si systemctl ne répond pas. `racine_utilisateur` : ~/.config/systemd/user ; `racines_globales` :
    /etc/systemd/user, /usr/lib/systemd/user, /usr/local/lib/systemd/user ; `maintenant` et `monotone` (horloges)
    donnent le « quand » des minuteurs."""
    journal = journal if isinstance(journal, dict) else {}
    perso, lies_utilisateur, lies_globaux = _contexte_unites(racine_utilisateur, racines_globales)
    maintenant = _en_date(maintenant)
    res = [e for e in (_entree_unite(u, perso, lies_utilisateur, lies_globaux, journal, maintenant, monotone)
                       for u in _lire_unites(run)) if e is not None]
    res.sort(key=lambda e: e["nom"].casefold())
    return res


def au_lancement(*, run=commun.run, dossier=None, systeme=None, utilisateur=None, racine_utilisateur=None,
                 racines_globales=None, existe=shutil.which, maintenant=None):
    """`lancement` de demarrage.json : les applis, puis les unités ; `modifie` vient du journal de `dossier`. Les applis
    ne dépendent pas de systemd : s'il ne répond pas, elles restent (avec leur « Remettre comme avant »), sans unité,
    et `illisible` dit pourquoi (None sinon)."""
    journal = lire_journal(dossier)
    entrees, ignorees = applis(systeme, utilisateur, existe=existe, journal=journal)
    illisible = None
    try:
        unites = unites_utilisateur(run=run, racine_utilisateur=racine_utilisateur, racines_globales=racines_globales,
                                    journal=journal, maintenant=maintenant)
    except LectureImpossible as exc:
        unites, illisible = [], str(exc)
    return {"entrees": entrees + unites, "ignorees": ignorees, "illisible": illisible}


# --- Services système (D8) : lecture seule, la commande sudo est seulement montrée ---

def services_systeme(run=commun.run, blame=()):
    """Les services et minuteurs système activés, triés par durée (blame) décroissante puis par nom. Un essentiel n'a
    pas de commande ; les autres ont `sudo systemctl disable [--now] <u>`. Lève LectureImpossible si systemctl ne
    répond pas. Les modèles sans instance sont écartés (ils feraient échouer tout `show`)."""
    code, texte = run(LISTE_SYSTEME, timeout=TIMEOUT)
    if code != 0:
        raise LectureImpossible(f"systemctl list-unit-files : {_premiere_ligne(texte)}")
    noms = []
    for ligne in texte.splitlines():
        champs = ligne.split()
        if len(champs) >= 2 and champs[1] == "enabled" and champs[0].endswith((".service", ".timer")) \
                and not _MODELE.search(champs[0]) and champs[0] not in noms:
            noms.append(champs[0])
    props = {}
    if noms:
        code, texte = run(SHOW_SYSTEME + noms, timeout=TIMEOUT)
        props = _proprietes(texte) if code == 0 else {}
    durees = {}
    for unite, s in blame or ():
        durees.setdefault(unite, s)
    res = []
    for n in noms:
        essentiel = n.startswith(ESSENTIELS_SYSTEME)
        s = durees.get(n)
        description = props.get(n, {}).get("Description", "")
        res.append({"unite": n, "description": "" if description == n else description, "secondes": s,
                    "duree": duree_lisible(s) if s is not None else None, "essentiel": essentiel,
                    "explication": EXPLICATIONS.get(n),
                    "commande": None if essentiel else
                    f"sudo systemctl disable {'--now ' if n.endswith('.timer') else ''}{n}"})
    res.sort(key=lambda s: (s["secondes"] is None, -(s["secondes"] or 0.0), s["unite"].casefold()))
    return res


# --- Régler et remettre (D5 à D7) ---

def _verifier_id(id_):
    """(« autostart » | « unite », nom) pour un id bien formé, sinon None (jamais de « / » ni de « .. »)."""
    if not isinstance(id_, str) or "/" in id_ or ".." in id_:
        return None
    m = _ID_AUTOSTART.fullmatch(id_)
    if m:
        return "autostart", m.group(1)
    m = _ID_UNITE.fullmatch(id_)
    if m and not m.group(1).startswith("-"):
        return "unite", m.group(1)
    return None


def _retrouver(genre, nom, *, run, systeme, utilisateur, racine_utilisateur, racines_globales, existe, journal):
    """(Entree | None, état lu) par une nouvelle lecture de la machine. État : {"systeme", "utilisateur"} (textes,
    None si absent ; _ILLISIBLE possible pour l'utilisateur) pour une appli ; la ligne de _lire_unites pour une unité."""
    if genre == "autostart":
        systeme = Path(systeme) if systeme is not None else AUTOSTART_SYSTEME
        utilisateur = Path(utilisateur) if utilisateur is not None else _autostart_utilisateur()
        texte_systeme, texte_utilisateur = _lire_fichier(systeme / nom), _lire_fichier(utilisateur / nom)
        entree = _entree_appli(nom, texte_systeme, texte_utilisateur, existe, journal)
        etat = {"systeme": texte_systeme if isinstance(texte_systeme, str) else None,
                "utilisateur": texte_utilisateur, "chemin": utilisateur / nom}
        return entree, etat
    perso, lies_utilisateur, lies_globaux = _contexte_unites(racine_utilisateur, racines_globales)
    u = next((u for u in _lire_unites(run) if u["nom"] == nom), None)
    if u is None:
        return None, None
    return _entree_unite(u, perso, lies_utilisateur, lies_globaux, journal, None), u


def _texte_bascule(texte_systeme, texte_utilisateur, actif):
    """Le fichier utilisateur après la bascule (D6) ; None : le supprimer."""
    if not actif:
        return _poser(texte_utilisateur if texte_utilisateur is not None else texte_systeme, {"Hidden": "true"})
    if texte_utilisateur is not None and texte_systeme is not None and _actif_desktop(lire_desktop(texte_systeme)) \
            and (texte_utilisateur == _poser(texte_systeme, {"Hidden": "true"})
                 or "Exec" not in lire_desktop(texte_utilisateur)):
        # la copie masquée exacte (celle de KDE ou de Health Hub), ou un masque minimal sans Exec (I-2 : avec
        # Hidden=false, il remplacerait le fichier du système par une entrée sans programme) : le système revient
        return None
    base = texte_utilisateur if texte_utilisateur is not None else texte_systeme
    valeurs = {"Hidden": "false"}
    if lire_desktop(base).get("X-GNOME-Autostart-enabled", "").strip().lower() == "false":
        valeurs["X-GNOME-Autostart-enabled"] = "true"       # sinon l'entrée resterait coupée
    return _poser(base, valeurs)


def _commande_bascule(nom, actif):
    """D5 : un minuteur prend effet tout de suite (--now) ; un service ou un socket à la prochaine session."""
    return (["systemctl", "--user", "enable" if actif else "disable"]
            + (["--now"] if nom.endswith(".timer") else []) + [nom])


def _toujours_apres(genre, etat, apres):
    """L'entrée est-elle encore dans l'état laissé par Health Hub ?"""
    if genre == "autostart":
        return etat["utilisateur"] == apres.get("fichier")
    actif = bool(apres.get("actif"))
    if etat["etat"] != ("enabled" if actif else "disabled"):
        return False
    return not etat["nom"].endswith(".timer") or etat["active"] == ("active" if actif else "inactive")


def _meme_etat(a, b):
    """Même état (actif) et même fichier utilisateur, octet pour octet."""
    return bool(a.get("actif")) == bool(b.get("actif")) and a.get("fichier") == b.get("fichier")


def regler(id_, actif, *, run=commun.run, dossier=None, systeme=None, utilisateur=None, racine_utilisateur=None,
           racines_globales=None, existe=shutil.which):
    """Coupe (actif False) ou remet (True) une entrée de « Au lancement » -> (code, phrase). L'entrée est retrouvée par
    une nouvelle lecture : id mal formé, inconnu ou verrouillé -> code 2 sans rien toucher. Le journal est écrit avant
    le fichier ou systemctl, et rendu tel qu'il était si systemctl échoue (code 1)."""
    actif = bool(actif)
    genre_nom = _verifier_id(id_)
    if genre_nom is None:
        return 2, INCONNUE.format(id_=id_)
    genre, nom = genre_nom
    journal = lire_journal(dossier)
    try:
        entree, etat = _retrouver(genre, nom, run=run, journal=journal, systeme=systeme, utilisateur=utilisateur,
                                  racine_utilisateur=racine_utilisateur, racines_globales=racines_globales,
                                  existe=existe)
    except LectureImpossible as exc:
        return 1, f"Échec : {exc}"
    if entree is None:
        return 2, INCONNUE.format(id_=id_)
    if not entree["modifiable"]:
        return 2, VERROUILLE.format(nom=entree["nom"])
    if entree["actif"] == actif:
        return 0, DEJA.format(nom=entree["nom"])
    if genre == "autostart":
        nouveau = _texte_bascule(etat["systeme"], etat["utilisateur"], actif)
        avant = {"actif": entree["actif"], "fichier": etat["utilisateur"]}
        apres = {"actif": actif, "fichier": nouveau}
    else:
        avant, apres = {"actif": entree["actif"], "fichier": None}, {"actif": actif, "fichier": None}
    precedente = journal.get(id_)
    if _ligne_valide(precedente) and _toujours_apres(genre, etat, precedente["apres"]):
        # deuxième bascule d'un état que Health Hub a lui-même laissé : l'état d'origine reste celui à remettre. Si
        # l'entrée a changé ailleurs depuis (I-1), l'« avant » est l'état relu : sinon « Remettre » l'effacerait.
        avant = precedente["avant"]
    chemin_journal = _chemin_journal(dossier)
    if _meme_etat(avant, apres):
        # revenue exactement à son « avant » (T2 n° 58) : plus rien à remettre, la ligne tombe
        nouveau_journal = {k: v for k, v in journal.items() if k != id_}
    else:
        nouveau_journal = {**journal, id_: {"date": commun.maintenant(), "avant": avant, "apres": apres}}
    try:
        commun.ecrire_json(chemin_journal, nouveau_journal)
    except OSError as exc:
        return 1, f"Échec : journal impossible à écrire ({exc})"
    try:
        if genre == "autostart":
            _ecrire_fichier(etat["chemin"], nouveau)
        else:
            code, texte = run(_commande_bascule(nom, actif), timeout=TIMEOUT)
            if code != 0:
                raise RuntimeError(_sortie(texte, code))
    except (OSError, RuntimeError) as exc:
        try:
            commun.ecrire_json(chemin_journal, journal)     # la ligne d'avant, ou aucune
        except OSError:
            pass
        return 1, f"Échec : {exc}"
    cle = ("minuteur" if entree["type"] == "minuteur" else "appli", actif)
    return 0, PHRASES_REGLER[cle].format(nom=entree["nom"])


def _retirer(dossier, journal, id_):
    reste = {k: v for k, v in journal.items() if k != id_}
    commun.ecrire_json(_chemin_journal(dossier), reste)


def remettre(id_, *, run=commun.run, dossier=None, systeme=None, utilisateur=None, racine_utilisateur=None,
             racines_globales=None, existe=shutil.which):
    """Rend l'état noté `avant` dans le journal -> (code, phrase), seulement si l'entrée est toujours dans l'état
    `apres` ; sinon rien n'est touché et la ligne tombe (code 2)."""
    genre_nom = _verifier_id(id_)
    if genre_nom is None:
        return 2, INCONNUE.format(id_=id_)
    genre, nom = genre_nom
    journal = lire_journal(dossier)
    ligne = journal.get(id_)
    if not _ligne_valide(ligne):
        return 2, RIEN.format(id_=id_)
    try:
        entree, etat = _retrouver(genre, nom, run=run, journal=journal, systeme=systeme, utilisateur=utilisateur,
                                  racine_utilisateur=racine_utilisateur, racines_globales=racines_globales,
                                  existe=existe)
    except LectureImpossible as exc:
        return 1, f"Échec : {exc}"
    nom_visible = entree["nom"] if entree else nom
    if entree is not None and not entree["modifiable"]:
        return 2, VERROUILLE.format(nom=nom_visible)
    if entree is None or not _toujours_apres(genre, etat, ligne["apres"]):
        try:
            _retirer(dossier, journal, id_)
        except OSError as exc:
            return 1, f"Échec : journal impossible à écrire ({exc})"
        return 2, CHANGE.format(nom=nom_visible)
    avant = ligne["avant"]
    try:
        if genre == "autostart":
            fichier = avant.get("fichier")
            _ecrire_fichier(etat["chemin"], fichier if isinstance(fichier, str) else None)
        else:
            code, texte = run(_commande_bascule(nom, bool(avant.get("actif"))), timeout=TIMEOUT)
            if code != 0:
                return 1, f"Échec : {_sortie(texte, code)}"
    except OSError as exc:
        return 1, f"Échec : {exc}"
    try:
        _retirer(dossier, journal, id_)
    except OSError as exc:      # la remise est faite ; le journal garde sa ligne, que le clic suivant retirera
        return 1, f"Échec : « {nom_visible} » est revenu comme avant, mais le journal est impossible à écrire ({exc})."
    return 0, REVENU.format(nom=nom_visible)
