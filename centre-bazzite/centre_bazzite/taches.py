"""Tâches du panneau Activité : un fichier JSON par tâche dans <état>/taches/.
Les processus qui travaillent (analyse, ménage…) les écrivent, la fenêtre les affiche. Chaque fonction
calcule son dossier à l'appel (`dossier=None` : commun.ETAT / "taches")."""
import os
import re
import subprocess
from pathlib import Path

from . import commun

JOURNAL_MAX = 200
VUES = "vues.json"
INTERROMPUE = "Interrompue : la tâche s'est arrêtée sans finir."
STATUTS_FINAUX = ("fini", "echec", "interrompu")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")      # change à chaque démarrage du PC


def _dossier(dossier):
    return Path(dossier) if dossier is not None else commun.ETAT / "taches"


def _fichier(id_, dossier):
    return _dossier(dossier) / (re.sub(r"[^A-Za-z0-9._-]", "_", id_) + ".json")


def _lire(id_, dossier):
    t = commun.lire_json(_fichier(id_, dossier), None)
    return t if isinstance(t, dict) else None


def boot_id():
    """L'identifiant du démarrage en cours, ou None s'il est illisible."""
    try:
        return BOOT_ID.read_text(encoding="ascii").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def debuter(type_, cle, titre, *, unite=None, dossier=None):
    """Crée (ou remplace) la tâche `type_:cle`. Sans unité systemd, c'est le processus appelant qui travaille :
    son pid et le démarrage en cours (`boot`) servent à reconnaître une tâche abandonnée."""
    id_ = f"{type_}:{cle}"
    commun.ecrire_json(_fichier(id_, dossier), {
        "id": id_, "type": type_, "titre": titre, "statut": "en_cours", "progression": -1, "detail": "",
        "debut": commun.maintenant(), "fin": None, "unite": unite, "pid": None if unite else os.getpid(),
        "boot": None if unite else boot_id(), "etapes": [], "journal": []})
    return id_


def avancer(id_, *, progression=None, detail=None, ligne=None, dossier=None):
    t = _lire(id_, dossier)
    if t is None:
        return
    if progression is not None:
        t["progression"] = progression
    if detail is not None:
        t["detail"] = detail
    if ligne is not None:
        t["journal"] = (list(t.get("journal") or []) + [ligne])[-JOURNAL_MAX:]
    commun.ecrire_json(_fichier(id_, dossier), t)


def terminer(id_, statut, detail="", *, dossier=None, **champs):
    """`statut` : fini, echec ou interrompu. Une tâche finie est à 100 %. `champs` : clés ajoutées au fichier de la
    tâche (ex. `arret="manuel"` pour une analyse arrêtée à la demande)."""
    t = _lire(id_, dossier)
    if t is None:
        return
    t["statut"], t["detail"], t["fin"] = statut, detail, commun.maintenant()
    t.update(champs)
    if statut == "fini":
        t["progression"] = 100
    commun.ecrire_json(_fichier(id_, dossier), t)


def lister(dossier=None):
    """Les tâches, la plus récente d'abord ; les fichiers illisibles et vues.json sont ignorés."""
    res = []
    for f in _dossier(dossier).glob("*.json"):
        t = commun.lire_json(f, None)
        if isinstance(t, dict) and t.get("id"):
            res.append(t)
    return sorted(res, key=lambda t: str(t.get("debut") or ""), reverse=True)


def unite_active(unite):
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unite],
                              capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True       # dans le doute, la tâche n'est pas déclarée perdue


def pid_vivant(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:       # PermissionError : le processus existe, mais pas à nous
        return True
    return True


def _sans_unite_perdue(t, vivant, demarrage):
    """Sans unité (le ménage), le pid noté au début ; s'il date d'un autre démarrage, il a pu être repris par un
    autre processus : la tâche est perdue, même si ce pid vit."""
    if t.get("boot") and demarrage and t["boot"] != demarrage:
        return True
    return not vivant(t.get("pid"))


def reparer_orphelines(*, active=unite_active, vivant=pid_vivant, dossier=None):
    """Une tâche « en cours » dont le travailleur a disparu devient « interrompue ». Avec une unité, systemd
    répond ; sans unité, le pid et le démarrage notés au début en disent quelque chose."""
    n, demarrage = 0, boot_id()
    for t in lister(dossier):
        if t.get("statut") != "en_cours":
            continue
        perdue = (not active(t["unite"])) if t.get("unite") else _sans_unite_perdue(t, vivant, demarrage)
        # Le travailleur a pu finir pendant la vérification (systemctl peut prendre des secondes) : on relit.
        courante = _lire(t["id"], dossier)
        if perdue and courante is not None and courante.get("statut") == "en_cours":
            terminer(t["id"], "interrompu", INTERROMPUE, dossier=dossier)
            n += 1
    return n


def effacer_terminees(*, dossier=None, sessions=None):
    """Supprime les tâches finies et retient la session de mise à jour la plus récente comme « vue »
    (elle ne reparaît plus dans le panneau)."""
    n = 0
    for t in lister(dossier):
        if t.get("statut") != "en_cours":
            _fichier(t["id"], dossier).unlink(missing_ok=True)
            n += 1
    dossier_sessions = Path(sessions) if sessions is not None else commun.ETAT / "sessions"
    debuts = []
    for f in dossier_sessions.glob("*.json"):
        s = commun.lire_json(f, None)
        if isinstance(s, dict) and s.get("debut"):
            debuts.append(str(s["debut"]))
    commun.ecrire_json(_dossier(dossier) / VUES, {"session": max(debuts) if debuts else None})
    return n


def vue_session(dossier=None):
    v = commun.lire_json(_dossier(dossier) / VUES, {})
    s = v.get("session") if isinstance(v, dict) else None
    return s if isinstance(s, str) else None
