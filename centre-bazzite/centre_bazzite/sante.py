"""Santé de la machine : SSD, températures, GPU, volumes, services, journal, plantages, gels, Ollama,
et les contrôles repris de bazzite-health (mises à jour disponibles, ménage, stockage), mis en cache."""
import json
import os
import re
import shutil
import stat
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from . import commun, config
from . import securite as securite_mod

UDISKS = "org.freedesktop.UDisks2"
RAPPORT = commun.ETAT / "bilan-hebdo.json"
GELS = Path.home() / ".local" / "share" / "freeze-jeu"
OLLAMA_PS = "http://127.0.0.1:11434/api/ps"
# Contrôles lents (réseau, parcours de dossiers) : calculés à part, lus depuis ce cache par collecter().
CONTROLES = commun.ETAT / "controles.json"
MOTIFS_ES = ("i/o error", "critical medium error", "reset superspeed", "exfat:", "ext4-fs error",
             "csum failed", "device offline", "failed command")
PILOTE_NVIDIA = Path("/proc/driver/nvidia/version")
TELECHARGEMENT_MIN = 50 * 1024 ** 2


def _kelvin(k):
    return round(k - 273.15, 2)


def lire_smart(json_texte):
    a = json.loads(json_texte)["data"][0]
    v = {k: x["data"] for k, x in a.items()}
    capteurs = [t for t in v.get("temp_sensors", []) if t]
    k = capteurs[0] if capteurs else v.get("wctemp", 0)
    return {
        "usure": v["percent_used"],
        "reserve": v["avail_spare"],
        "seuil_reserve": v["spare_thresh"],
        "temperature": _kelvin(k),
        "erreurs_media": v["media_errors"],
        "arrets_brutaux": v["unsafe_shutdowns"],
        "heures": v.get("power_on_hours"),
        "ecrit_to": v["total_data_written"] / 1e12,
    }


def _donnees(texte):
    """Valeurs des lignes JSON `{"type":..,"data":..}` renvoyées par busctl."""
    out = []
    for ligne in texte.splitlines():
        try:
            out.append(json.loads(ligne)["data"])
        except (ValueError, KeyError, TypeError):
            continue
    return out


DISQUE_ENTIER = re.compile(r"/block_devices/((?:nvme\d+n\d+)|(?:sd[a-z]+)|(?:vd[a-z]+))$")


def _peripheriques(lignes):
    """{objet Drive UDisks: "/dev/<disque>"} pour les disques entiers (pas les partitions)."""
    res = {}
    for ligne in lignes:
        m = DISQUE_ENTIER.search(ligne.strip())
        if not m:
            continue
        code, sortie = commun.run(["busctl", "--json=short", "get-property", UDISKS, ligne.strip(),
                                   "org.freedesktop.UDisks2.Block", "Drive"])
        valeurs = _donnees(sortie) if code == 0 else []
        if valeurs and isinstance(valeurs[0], str) and valeurs[0] != "/":
            res.setdefault(valeurs[0], "/dev/" + m.group(1))
    return res


def ssd():
    code, arbre = commun.run(["busctl", "--json=short", "--list", "tree", UDISKS])
    lignes = arbre.splitlines() if code == 0 else []
    disques = [l.strip() for l in lignes if "/drives/" in l]
    peripheriques = _peripheriques(lignes)
    resultat = []
    for obj in disques:
        code, sortie = commun.run(["busctl", "--json=short", "get-property", UDISKS, obj,
                                   "org.freedesktop.UDisks2.Drive", "Model", "ConnectionBus"])
        valeurs = _donnees(sortie) if code == 0 else []
        modele, bus = (valeurs + ["", ""])[:2]
        sante_disque = None
        code, avert = commun.run(["busctl", "--json=short", "get-property", UDISKS, obj,
                                  "org.freedesktop.UDisks2.NVMe.Controller", "SmartCriticalWarning"])
        if code == 0:
            code, smart = commun.run(["busctl", "--json=short", "call", UDISKS, obj,
                                      "org.freedesktop.UDisks2.NVMe.Controller",
                                      "SmartGetAttributes", "a{sv}", "0"])
            if code == 0:
                try:
                    sante_disque = lire_smart(smart)
                    liste = (_donnees(avert) or [[]])[0]
                    sante_disque["avertissements"] = list(liste)
                    if sante_disque["heures"] is None:
                        code, h = commun.run(["busctl", "--json=short", "get-property", UDISKS,
                                              obj, "org.freedesktop.UDisks2.NVMe.Controller",
                                              "SmartPowerOnHours"])
                        valeurs = _donnees(h) if code == 0 else []
                        sante_disque["heures"] = valeurs[0] if valeurs else None
                except (ValueError, KeyError, IndexError, TypeError):
                    sante_disque = None
        resultat.append({"modele": modele, "bus": bus or ("nvme" if sante_disque is not None else "?"),
                         "peripherique": peripheriques.get(obj), "sante": sante_disque})
    return resultat


def _json_depuis_accolade(texte):
    """sensors -j peut faire précéder le JSON de lignes d'erreur."""
    i, j = texte.find("{"), texte.rfind("}")
    return json.loads(texte[i:j + 1]) if i >= 0 and j > i else {}


def lire_sensors(json_texte):
    d = _json_depuis_accolade(json_texte)
    cpu = ssd_t = None
    for nom, bloc in d.items():
        if not isinstance(bloc, dict):
            continue
        if cpu is None and "Package id 0" in bloc:
            cpu = bloc["Package id 0"].get("temp1_input")
        if ssd_t is None and nom.startswith("nvme") and "Composite" in bloc:
            ssd_t = bloc["Composite"].get("temp1_input")
    return {"cpu": cpu, "ssd": ssd_t}


def temperatures():
    code, sortie = commun.run(["sensors", "-j"])
    return lire_sensors(sortie)


def lire_nvidia(csv):
    ligne = csv.strip().splitlines()[0]
    nom, temp, watts, utilisee, totale = [c.strip() for c in ligne.split(",")]
    return {"nom": nom, "temperature": int(temp), "watts": float(watts),
            "vram_utilisee_go": round(float(utilisee) / 1024, 2),
            "vram_totale_go": round(float(totale) / 1024, 2)}


def gpu():
    code, sortie = commun.run(["nvidia-smi", "--query-gpu=name,temperature.gpu,power.draw,"
                               "memory.used,memory.total", "--format=csv,noheader,nounits"])
    if code != 0:
        raise RuntimeError(sortie.strip())
    return lire_nvidia(sortie)


def espace(nom, chemin, u, decimales=1):
    gio = 1024 ** 3
    return {"nom": nom, "chemin": chemin,
            "libre_go": round(u.free / gio, decimales), "total_go": round(u.total / gio, decimales),
            "pourcent_utilise": round(100 * (u.total - u.free) / u.total, 1) if u.total else 0.0}


def volumes_suivis():
    """[(nom, chemin)] des volumes suivis, ceux de la configuration locale (config.volumes), lus à l'appel."""
    return [(v.nom, v.chemin) for v in config.volumes()]


def volumes_attendus():
    """[{"nom", "chemin"}] des volumes qui doivent être montés : attendus dans la configuration, et pas facultatifs
    (un volume facultatif peut être débranché sans que rien soit signalé)."""
    return [{"nom": v.nom, "chemin": v.chemin} for v in config.volumes() if v.attendu and not v.facultatif]


def volumes(montages=None, est_monte=os.path.ismount):
    montages = volumes_suivis() if montages is None else montages
    return [espace(nom, chemin, shutil.disk_usage(chemin)) for nom, chemin in montages if est_monte(chemin)]


def services_en_echec():
    noms = []
    for extra in ([], ["--user"]):
        code, sortie = commun.run(["systemctl", *extra, "--failed", "--no-legend", "--plain",
                                   "--no-pager"])
        for ligne in sortie.splitlines():
            mots = ligne.replace("●", " ").split()
            if code == 0 and mots:
                noms.append(mots[0])
    return noms


def erreurs_journal():
    code, sortie = commun.run(["journalctl", "-b", "-p", "err", "-o", "json", "--no-pager"])
    compte = Counter()
    for ligne in sortie.splitlines():
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        msg = e.get("MESSAGE")
        if isinstance(msg, list):  # message binaire
            msg = "(message binaire)"
        compte[(msg or "", e.get("SYSLOG_IDENTIFIER") or e.get("_COMM") or "")] += 1
    return [{"message": m, "source": s, "nombre": n} for (m, s), n in compte.most_common(10)]


def plantages(jours=7):
    code, sortie = commun.run(["coredumpctl", "list", "--json=short", f"--since=-{jours}d",
                               "--no-pager"])
    if code != 0:
        return []
    try:
        lignes = json.loads(sortie)
    except ValueError:
        return []
    return [{"exe": Path(c.get("exe") or "?").name, "signal": c.get("sig"),
             "date": datetime.fromtimestamp(c.get("time", 0) / 1e6).isoformat(timespec="seconds")}
            for c in lignes]


def bilan_hebdo(chemin=RAPPORT):
    return commun.lire_json(chemin, None)


def gels(dossier=GELS):
    try:
        noms = sorted(p.name for p in Path(dossier).iterdir() if p.is_dir() or p.suffix == ".txt")
    except OSError:
        noms = []
    return {"nombre": len(noms), "dernier": noms[-1] if noms else None}


def ollama(ouvrir=urllib.request.urlopen):
    code, sortie = commun.run(["systemctl", "--user", "is-active", "ollama.service"])
    if sortie.strip() != "active":
        return {"actif": False, "depuis": None, "modeles_charges": []}
    _, ts = commun.run(["systemctl", "--user", "show", "ollama.service",
                        "-p", "ActiveEnterTimestamp"])
    depuis = ts.strip().partition("=")[2] or None
    try:
        with ouvrir(OLLAMA_PS, timeout=3) as r:
            modeles = [m.get("name") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        modeles = []
    return {"actif": True, "depuis": depuis, "modeles_charges": modeles}


# --- Contrôles repris de bazzite-health (sans `sudo -n smartctl` : UDisks2 couvre SMART) ---

# flatpak numérote les refs : " 1.\t   \torg.kde.Platform\t6.10\tr"
REF_NUMEROTEE = re.compile(r"^\s*\d+\.\s+((?:org|com|io|net|app|dev|tv)\.[\w.-]+)")
ID_FLATPAK = re.compile(r"^[A-Za-z][\w-]*(?:\.[\w-]+)+$")
UNITES_JOURNAL = "BKMGTPE"


def lire_upgrade_check(code, sortie):
    """`rpm-ostree upgrade --check` : 77 = rien de neuf ; 0 = la version disponible ; sinon, ou si le code 0
    ne donne aucune version lisible, la vérification a échoué (None) : jamais un faux « à jour »."""
    if code == 77:
        return {"disponible": None}
    if code != 0:
        return None
    for ligne in sortie.splitlines():
        if "Version:" in ligne:
            mots = ligne.split("Version:", 1)[1].split()
            if mots:
                return {"disponible": mots[0]}
    return None


def lire_remote_ls(sortie):
    """Identifiants de `flatpak remote-ls --updates --columns=application` ; un avertissement mêlé
    à la sortie n'est pas une application."""
    return [l.strip() for l in sortie.splitlines() if ID_FLATPAK.match(l.strip())]


def lire_runtimes_inutilises(sortie):
    return [m.group(1) for m in map(REF_NUMEROTEE.match, sortie.splitlines()) if m]


def version_pilote_nvidia(chemin=None):
    """« 615.78.08 », lu dans /proc/driver/nvidia/version ; None sans pilote NVIDIA chargé."""
    try:
        m = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", Path(chemin or PILOTE_NVIDIA).read_text())
    except OSError:
        return None
    return ".".join(m.groups()) if m else None


def gl_nvidia_obsoletes(version_pilote, sortie_runtimes):
    """Pilotes GL NVIDIA Flatpak d'une autre version que le pilote chargé. Ils sont épinglés,
    donc `flatpak uninstall --unused` ne les retire jamais."""
    if not version_pilote:
        return []
    courant = "nvidia-" + version_pilote.replace(".", "-")
    obsoletes = []
    for ligne in sortie_runtimes.splitlines():
        champs = ligne.split()
        if len(champs) < 2:
            continue
        app, branche = champs[0], champs[1]
        if re.match(r"org\.freedesktop\.Platform\.GL(32)?\.nvidia-", app) and not app.endswith(courant):
            obsoletes.append(f"runtime/{app}/x86_64/{branche}")
    return obsoletes


def lire_disk_usage(sortie):
    """Octets de « Archived and active journals take up 1.2G in the file system. »."""
    m = re.search(r"take up ([\d.,]+)\s*([BKMGTPE]?)", sortie)
    if not m:
        return None
    try:
        valeur = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return round(valeur * 1024 ** UNITES_JOURNAL.index(m.group(2) or "B"))


def lire_erreurs_disque(texte):
    """Lignes du noyau qui trahissent une erreur d'E/S ou de système de fichiers (les 3 dernières en exemple)."""
    lignes = [l.strip() for l in texte.splitlines() if any(m in l.lower() for m in MOTIFS_ES)]
    return {"nombre": len(lignes), "exemples": lignes[-3:]}


# Repris et adapté de Bilan Santé PC de BiasedMonkey, https://github.com/BiasedMonkey/bilan-sante (GPL-3.0).
XID_APPLICATION = frozenset({13, 31, 43, 45, 68, 69})   # fautes d'un programme, pas de la carte
_XID = re.compile(r"NVRM: Xid \([^)]*\): (\d+)", re.I)
_MOTIFS_NOYAU = {
    "gpu": re.compile(r"NVRM: Xid|GPU has fallen off the bus|amdgpu.*\b(timeout|reset|hang|fault|failed|error)\b"
                      r"|ring \S+ timeout|gpu reset|nouveau.*\b(error|fault)\b|i915.*\b(hang|error)\b", re.I),
    "materiel": re.compile(r"Machine check|Hardware Error|EDAC\b.*(\b(CE|UE)\b|corrected)", re.I),
    "usb": re.compile(r"usb .*(error -71|error -110|Cannot enable|unable to enumerate|device descriptor read"
                      r"|not accepting address)", re.I),
    "plantages": re.compile(r"segfault at|general protection", re.I),
}
_TEMPERATURE = re.compile(r"temperature above threshold", re.I)


def _message_noyau(ligne):
    """Le texte après « kernel: » (sans date ni machine)."""
    return ligne.split("kernel: ", 1)[-1].strip()


def lire_noyau(texte):
    """Lignes du journal du noyau classées : disque, gpu, materiel, usb, plantages (une fois par catégorie)."""
    lignes = {c: [] for c in _MOTIFS_NOYAU}
    graves, chute = 0, False
    # la ligne de commande du noyau (ses options de démarrage) n'est pas une erreur
    texte = "\n".join(l for l in texte.splitlines() if "command line" not in l.lower())
    for ligne in texte.splitlines():
        for categorie, motif in _MOTIFS_NOYAU.items():
            if not motif.search(ligne) or (categorie == "materiel" and _TEMPERATURE.search(ligne)):
                continue
            lignes[categorie].append(_message_noyau(ligne))
            if categorie == "gpu":
                m = _XID.search(ligne)
                numero = int(m.group(1)) if m else None
                if numero == 79 or "fallen off the bus" in ligne.lower():
                    chute = True
                if numero not in XID_APPLICATION:
                    graves += 1
    def resume(c):
        # les 3 derniers messages distincts, chacun à sa dernière occurrence, du plus ancien au plus récent
        distincts = list(dict.fromkeys(reversed(lignes[c])))[:3][::-1]
        return {"nombre": len(lignes[c]), "exemples": distincts}
    resultat = {"disque": lire_erreurs_disque(texte)}
    for c in ("gpu", "materiel", "usb", "plantages"):
        resultat[c] = resume(c)
    resultat["gpu"].update(graves=graves, chute=chute)
    return resultat


def taille_dossier(chemin):
    """Place occupée sur le disque (st_blocks × 512), sans suivre les liens ; erreurs ignorées."""
    total = 0
    for racine, dossiers, fichiers in os.walk(chemin, onerror=lambda e: None):
        for nom in dossiers + fichiers:
            try:
                total += os.lstat(os.path.join(racine, nom)).st_blocks * 512
            except OSError:
                pass
    return total


def telechargements_incomplets(dossiers):
    """Fichiers d'au moins 50 Mio présents à moins de 90 % sur le disque (téléchargement interrompu)."""
    suspects, vus = [], set()
    for dossier in dossiers:
        dossier = Path(dossier)
        if not dossier.is_dir() or dossier.resolve() in vus:
            continue
        vus.add(dossier.resolve())
        for racine, _d, fichiers in os.walk(dossier, onerror=lambda e: None):
            for nom in fichiers:
                try:
                    st = os.lstat(os.path.join(racine, nom))
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_size < TELECHARGEMENT_MIN:
                    continue
                presents = st.st_blocks * 512
                if presents < 0.9 * st.st_size:
                    suspects.append({"nom": nom, "octets": st.st_size,
                                     "present": int(100 * presents / st.st_size)})
    return sorted(suspects, key=lambda s: -s["octets"])


def journal_noyau(run=None):
    """Le journal du noyau du démarrage en cours, lu une seule fois et classé par catégorie ; None si illisible."""
    code, sortie = (run or commun.run)(["journalctl", "-k", "-b", "--no-pager"], timeout=60)
    return lire_noyau(sortie) if code == 0 else None


def non_montes(attendus=None, est_monte=os.path.ismount):
    attendus = [v["chemin"] for v in volumes_attendus()] if attendus is None else attendus
    return [c for c in attendus if not est_monte(c)]


def _essai(nom, fonction):
    """Le résultat d'un contrôle, ou None s'il lève : la panne est écrite sur stderr (journal de l'unité)."""
    try:
        return fonction()
    except Exception as exc:
        print(f"contrôle {nom} en échec : {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def controles(*, run=commun.run, home=Path.home(), mesurer=shutil.disk_usage):
    """Les contrôles lents de bazzite-health. Une clé vaut None si sa vérification a échoué
    (hors ligne, commande en erreur) : ce n'est jamais un problème à signaler."""
    home = Path(home)
    date = commun.maintenant()      # avant les vérifications : comparée à la fin de la dernière passe de uupd

    def image():
        return lire_upgrade_check(*run(["rpm-ostree", "upgrade", "--check"], timeout=300))

    def flatpak():
        code, sortie = run(["flatpak", "remote-ls", "--updates", "--columns=application"], timeout=180)
        return {"a_mettre_a_jour": lire_remote_ls(sortie)} if code == 0 else None

    def runtimes():
        # Répondre « n » : la liste s'affiche, rien n'est désinstallé. Le refus peut rendre un code
        # non nul ; seule une sortie sans aucune ref est alors un échec.
        code, sortie = run(["flatpak", "uninstall", "--unused"], timeout=180, entree="n\n")
        inutilises = lire_runtimes_inutilises(sortie)
        if code != 0 and not inutilises:
            return None
        gl, version = [], version_pilote_nvidia()
        if version:
            code, liste = run(["flatpak", "list", "--runtime", "--columns=application,branch"], timeout=60)
            if code != 0:
                return None
            gl = gl_nvidia_obsoletes(version, liste)
        # un GL obsolète déjà désépinglé figure aussi dans --unused
        inutilises = [r for r in inutilises if not any(f"/{r}/" in g for g in gl)]
        return {"inutilises": inutilises, "gl_obsoletes": gl}

    def caches():
        code, sortie = run(["journalctl", "--disk-usage"], timeout=30)
        return {"miniatures": taille_dossier(home / ".cache" / "thumbnails"),
                "corbeille": taille_dossier(home / ".local" / "share" / "Trash"),
                "journal": lire_disk_usage(sortie) if code == 0 else None}

    return {"date": date, "image": _essai("image", image), "flatpak": _essai("flatpak", flatpak),
            "runtimes": _essai("runtimes", runtimes),
            "telechargements": _essai("telechargements", lambda: telechargements_incomplets(
                [home / "Téléchargements", home / "Downloads"])),
            "caches": _essai("caches", caches),
            "boot": _essai("boot", lambda: espace("Démarrage", "/boot", mesurer("/boot"), decimales=2))}


def ecrire_controles():
    commun.ecrire_json(CONTROLES, controles())
    return CONTROLES


def lire_controles(chemin=None):
    d = commun.lire_json(chemin or CONTROLES, None)
    return d if isinstance(d, dict) else None


# Une vérification impossible (réseau absent au relevé de démarrage…) est refaite au relevé horaire suivant
# (Ruling V41). Le minuteur repart du début du relevé précédent et la date des contrôles est prise quelques
# secondes après : un seuil d'1 h pile laisserait passer ce relevé-là ; 50 min ne le manque jamais.
CLES_RESEAU = ("image", "flatpak", "runtimes")
RESSAI_APRES_ECHEC = timedelta(minutes=50)


def controles_perimes(heures=20, chemin=None, maintenant=None):
    """Vrai si les contrôles en cache ont au moins `heures` heures, ou sont absents ou illisibles, ou si
    l'une des vérifications de CLES_RESEAU a échoué il y a plus de RESSAI_APRES_ECHEC."""
    c = lire_controles(chemin) or {}
    try:
        date = datetime.fromisoformat(c["date"])
    except (KeyError, TypeError, ValueError):
        return True
    age = (maintenant or datetime.now()) - date
    if any(c.get(cle) is None for cle in CLES_RESEAU) and age >= RESSAI_APRES_ECHEC:
        return True
    return age >= timedelta(hours=heures)


# Repris et adapté de Bilan Santé PC de BiasedMonkey,
# https://github.com/BiasedMonkey/bilan-sante (GPL-3.0) : memoire() et _pression().
def _pression(chemin):
    """Pressure Stall Information : % du temps où des tâches attendent (`some avg300`) ; None si absente."""
    try:
        texte = Path(chemin).read_text(encoding="utf-8")
    except OSError:
        return None
    for ligne in texte.splitlines():
        genre, *champs = ligne.split()
        if genre == "some":
            for champ in champs:
                cle, _, val = champ.partition("=")
                if cle == "avg300":
                    return float(val)
    return None


def memoire(proc=Path("/proc"), blocs=Path("/sys/block")):
    """RAM, swap, attente due à la mémoire (PSI) et zram, en octets. Lit /proc et /sys, sans bibliothèque."""
    ko = {}
    for ligne in (proc / "meminfo").read_text(encoding="utf-8").splitlines():
        cle, _, reste = ligne.partition(":")
        champs = reste.split()
        if champs:
            ko[cle] = int(champs[0]) * 1024
    zram = []
    for dev in sorted(blocs.glob("zram*")):
        try:
            mm = (dev / "mm_stat").read_text(encoding="utf-8").split()
            if len(mm) >= 2 and int(mm[0]):
                algo = re.search(r"\[([^\]]+)\]", (dev / "comp_algorithm").read_text(encoding="utf-8"))
                zram.append({"nom": dev.name, "donnees": int(mm[0]), "compresse": int(mm[1]),
                             "algo": algo.group(1) if algo else ""})
        except (OSError, ValueError):
            continue
    return {"total": ko["MemTotal"], "disponible": ko["MemAvailable"], "swap_total": ko["SwapTotal"],
            "swap_utilise": ko["SwapTotal"] - ko["SwapFree"],
            "attente": _pression(proc / "pressure" / "memory"), "zram": zram}


def securite():
    """Sécurité de la machine (ports, pare-feu, démarrage suspect, dossiers temporaires) : voir securite.collecter."""
    return securite_mod.collecter()


def collecter():
    """Mesures de santé ; les contrôles lents sont lus depuis leur cache, jamais calculés ici."""
    sources = {"ssd": ssd, "temperatures": temperatures, "gpu": gpu, "volumes": volumes,
               "services_en_echec": services_en_echec, "erreurs_journal": erreurs_journal,
               "plantages": plantages, "bilan_hebdo": bilan_hebdo, "gels": gels,
               "ollama": ollama, "controles": lire_controles, "journal_noyau": journal_noyau,
               "non_montes": non_montes, "attendus": volumes_attendus, "memoire": memoire,
               "securite": securite}
    resultat = {}
    for cle, fonction in sources.items():
        try:
            resultat[cle] = fonction()
        except Exception:
            resultat[cle] = None
    journal = resultat.pop("journal_noyau")
    resultat["erreurs_disque"] = journal["disque"] if journal else None
    resultat["noyau"] = {c: v for c, v in journal.items() if c != "disque"} if journal else None
    return resultat
