"""Analyse de disque avec le moteur de LinStat (`Scanner`) : catégories et plus gros dossiers d'un volume.

Trois étages, pour que l'analyse ne gêne jamais un jeu ni la fenêtre :
- la CLI `analyser` lance `_analyser` dans l'unité transitoire health-hub-analyse (systemd-run) ;
- `superviser` y lance, volume par volume, un processus enfant en `nice -n 19 ionice -c3` dans son propre
  groupe, et l'arrête (avec les processus d'analyse de LinStat) dès qu'un jeu démarre ;
- l'enfant (`python3 -m centre_bazzite.analyse`) importe LinStat, analyse le volume en lecture seule et écrit un
  résumé JSON en cache (analyses/<volume>.json). Un enfant arrêté n'écrit rien : l'ancien résumé reste.
Chaque volume a sa tâche `analyse:<chemin>` dans le panneau Activité."""
import argparse
import importlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import commun, sante, taches

LINSTAT_DIR = Path.home() / ".local/share/linstat"
LINSTAT_CMD = LINSTAT_DIR / "linstat.py"        # V3 : l'installeur de LinStat ne crée pas de commande `linstat`
PROCS = 2                       # processus d'analyse de LinStat (il en prendrait un par cœur)
AGE_MAX_JOURS = 7
RESSAI_APRES_ECHEC = timedelta(hours=24)        # une analyse en échec n'est pas relancée à chaque relevé
PAUSE_APRES_ARRET_H = 24                        # une analyse arrêtée à la demande n'est pas relancée seule avant
DELAIS_PAUSE = {"manuel": timedelta(hours=PAUSE_APRES_ARRET_H), "echec": RESSAI_APRES_ECHEC}
UNITE = "health-hub-analyse"
DOSSIERS_MAX = 10
CODE_SANS_LINSTAT = 3
CODE_DEMONTE = 4
INTERVALLE_S = 5                # le superviseur regarde l'enfant et les jeux à ce rythme
AVANCEMENT_S = 3                # l'enfant écrit son avancement dans la tâche à ce rythme
ARRET_S = 10                    # délai de grâce entre SIGTERM et SIGKILL
PAQUET = Path(__file__).resolve().parent.parent
SANS_LINSTAT = "LinStat est absent ou a changé : seul l'espace libre est affiché."
INTERROMPU = "Un jeu a démarré : l'analyse reprendra plus tard."
DEMONTE = "Le volume a été démonté pendant l'analyse : l'ancien résumé est gardé."
ARRET_MANUEL = "Analyse arrêtée à ta demande."
ARRET_SYSTEME = "L'analyse s'est arrêtée avec la session ou le PC : elle reprendra plus tard."
API_CHANGEE = (AttributeError, TypeError, ValueError)     # appel à LinStat qui ne correspond plus à son API


def charger_linstat(dossier=None):
    """Le module `linstat` de `dossier` (par défaut LINSTAT_DIR), ou None s'il manque, ne s'importe pas ou si son
    API a changé. Le dossier est placé une seule fois en tête de sys.path, pour que les processus d'analyse
    (forkserver) le retrouvent, et le module est toujours réimporté depuis ce dossier (V7)."""
    dossier = Path(dossier) if dossier is not None else LINSTAT_DIR
    if not (dossier / "linstat.py").is_file():
        return None
    while str(dossier) in sys.path:
        sys.path.remove(str(dossier))
    sys.path.insert(0, str(dossier))
    sys.modules.pop("linstat", None)
    importlib.invalidate_caches()
    try:
        module = importlib.import_module("linstat")
    except Exception:
        sys.modules.pop("linstat", None)
        return None
    scanner = getattr(module, "Scanner", None)
    if scanner is None or not hasattr(module, "CATEGORIES") \
            or not all(callable(getattr(scanner, m, None)) for m in ("run", "categories", "tree")):
        sys.modules.pop("linstat", None)
        return None
    return module


def resumer(scanner, racine, chemin, duree_s):
    """Le résumé (forme `Analyse`) d'une analyse finie : `scanner.tree(racine)` calcule d'abord les totaux."""
    scanner.tree(racine)
    gros = sorted((d for d in racine.dirs if d.total > 0), key=lambda d: d.total, reverse=True)[:DOSSIERS_MAX]
    return {"chemin": chemin, "date": commun.maintenant(), "duree_s": round(duree_s, 1),
            "total": racine.total, "total_texte": commun.taille(racine.total),
            "fichiers": getattr(scanner, "file_count", scanner.files), "erreurs": getattr(scanner, "errors", 0),
            "categories": [{"nom": nom, "octets": octets, "taille": commun.taille(octets), "nombre": nombre}
                           for nom, octets, nombre, *_ in scanner.categories()],
            # un dossier sans règle de chemin hérite de la catégorie de la racine, qui peut aussi être None (V23)
            "dossiers": [{"nom": d.name, "chemin": d.path(), "octets": d.total, "taille": commun.taille(d.total),
                          "categorie": d.cat or racine.cat} for d in gros]}


def cache(chemin, dossier=None):
    """Le résumé en cache d'un volume : <état>/analyses/var_mnt_DONNEES.json (V18), calculé à l'appel."""
    nom = chemin.strip("/").replace("/", "_") or "racine"
    return Path(dossier or commun.ETAT) / "analyses" / (nom + ".json")


def lire_analyse(chemin, dossier=None):
    a = commun.lire_json(cache(chemin, dossier), None)
    return a if isinstance(a, dict) else None


def pause(chemin, dossier=None):
    """Le repère de pause d'un volume, à côté de son résumé : <état>/analyses/var_mnt_DONNEES.pause, {"date", "raison"}.
    Il vit hors des fichiers de tâches, pour qu'« Effacer terminées » n'annule ni la pause qui suit un arrêt à ta
    demande (raison « manuel ») ni le délai qui suit un échec (« echec »). Le lancement suivant du volume le retire."""
    return cache(chemin, dossier).with_suffix(".pause")


def _poser_pause(chemin, raison, dossier=None):
    commun.ecrire_json(pause(chemin, dossier), {"date": commun.maintenant(), "raison": raison})


def marqueur_arret(dossier=None):
    """Écrit par `analyser --arreter` juste avant d'arrêter l'unité : le superviseur sait ainsi que le SIGTERM
    qu'il reçoit vient du bouton « Arrêter », pas de la fin de session ni de l'extinction."""
    return Path(dossier or commun.ETAT) / "analyses" / "arret-demande"


def etat_linstat():
    """Pour stockage.json : le moteur s'importe-t-il, et la commande « Carte détaillée » est-elle exécutable ?"""
    commande = LINSTAT_CMD.is_file() and os.access(LINSTAT_CMD, os.X_OK)
    return {"moteur": charger_linstat() is not None, "commande": str(LINSTAT_CMD) if commande else None}


def _date(texte):
    try:
        return datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def _en_pause(chemin, maintenant):
    repere = commun.lire_json(pause(chemin), None)
    if not isinstance(repere, dict):
        return False
    debut, delai = _date(repere.get("date")), DELAIS_PAUSE.get(repere.get("raison"))
    return debut is not None and delai is not None and maintenant - debut < delai


def perime(chemin, *, maintenant=None):
    """Faut-il relancer l'analyse du volume ? D'abord son repère de pause (`pause`), puis sa dernière tâche :
    - arrêtée à ta demande depuis moins de PAUSE_APRES_ARRET_H heures → non, même sans résumé (le bouton
      « Analyser » relance quand on veut) ;
    - interrompue autrement (jeu, session, extinction) → oui, elle reprend au relevé suivant (V15) ;
    - en échec depuis moins de RESSAI_APRES_ECHEC → non, même sans résumé (pas de relance à chaque relevé).
    Sinon, oui sans résumé lisible ou avec un résumé de plus de AGE_MAX_JOURS jours."""
    maintenant = maintenant or datetime.now()
    if _en_pause(chemin, maintenant):
        return False
    derniere = next((t for t in taches.lister() if t.get("id") == f"analyse:{chemin}"), None) or {}
    fin = _date(derniere.get("fin"))
    if derniere.get("statut") == "interrompu" and derniere.get("arret") == "manuel":
        if fin is not None and maintenant - fin < timedelta(hours=PAUSE_APRES_ARRET_H):
            return False
    elif derniere.get("statut") == "interrompu":
        return True
    if derniere.get("statut") == "echec" and fin is not None and maintenant - fin < RESSAI_APRES_ECHEC:
        return False
    date = _date((lire_analyse(chemin) or {}).get("date"))
    return date is None or maintenant - date > timedelta(days=AGE_MAX_JOURS)


def _nombre(n):
    return f"{n:,}".replace(",", " ")


def _montage(chemin):
    """(point de montage ?, périphérique) : ce qui doit rester identique du début à la fin d'une analyse."""
    try:
        return os.path.ismount(chemin), os.stat(chemin).st_dev
    except OSError:
        return False, None


def analyser_volume(chemin, sortie, tache, *, linstat=None, montage=_montage):
    """Le processus enfant : analyse `chemin` sans quitter son système de fichiers, écrit le résumé dans `sortie`
    (atomiquement) et renvoie 0 ; CODE_SANS_LINSTAT si LinStat manque ou a changé ; CODE_DEMONTE, sans rien
    écrire, si le volume a été démonté ou remplacé pendant l'analyse (un disque débranché laisse un dossier vide :
    son résumé à 0 octet écraserait le bon pour 7 jours)."""
    linstat = linstat or charger_linstat()
    if linstat is None:
        print(SANS_LINSTAT, file=sys.stderr)
        return CODE_SANS_LINSTAT
    avant = montage(chemin)
    debut = time.monotonic()
    try:
        scanner = linstat.Scanner(chemin, one_fs=True, procs=PROCS)
        racine = _parcourir(scanner, tache)
        resume = resumer(scanner, racine, chemin, time.monotonic() - debut)
    except API_CHANGEE as exc:      # mot-clé renommé, autre forme de categories()… : pas une trace brute
        print(f"{SANS_LINSTAT} ({type(exc).__name__} : {exc})", file=sys.stderr)
        return CODE_SANS_LINSTAT
    if montage(chemin) != avant:
        print(DEMONTE, file=sys.stderr)
        return CODE_DEMONTE
    commun.ecrire_json(sortie, resume)
    return 0


def _parcourir(scanner, tache):
    """`scanner.run()`, pendant qu'un fil écrit l'avancement dans la tâche toutes les AVANCEMENT_S secondes."""
    fin = threading.Event()

    def avancer():
        while not fin.wait(AVANCEMENT_S):
            try:
                detail = f"{_nombre(scanner.files)} fichiers, {commun.taille(scanner.total)} vus"
            except API_CHANGEE:
                return              # compteurs absents ou d'une autre forme : l'analyse continue sans avancement
            taches.avancer(tache, detail=detail)

    fil = threading.Thread(target=avancer, daemon=True) if tache else None
    if fil:
        fil.start()
    try:
        return scanner.run()
    finally:
        fin.set()
        if fil:
            fil.join()


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m centre_bazzite.analyse",
                                description="Analyse un volume avec LinStat et écrit son résumé JSON.")
    p.add_argument("chemin")
    p.add_argument("sortie")
    p.add_argument("--tache", help="tâche du panneau Activité où écrire l'avancement")
    a = p.parse_args(argv)
    return analyser_volume(a.chemin, Path(a.sortie), a.tache)


def _env():
    """L'environnement de l'enfant : le paquet centre_bazzite en tête de PYTHONPATH."""
    env = dict(os.environ)
    autres = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != str(PAQUET)]
    env["PYTHONPATH"] = os.pathsep.join([str(PAQUET)] + autres)
    return env


def _ramasser(pid, bloquant=False):
    try:
        os.waitpid(pid, 0 if bloquant else os.WNOHANG)
    except ChildProcessError:
        pass


def _tuer_groupe(pid, delai=ARRET_S):
    """Arrête l'enfant et tout son groupe (les processus d'analyse de LinStat) : SIGTERM, puis SIGKILL à ce qui
    reste après `delai` secondes. L'enfant est ramassé ici : un zombie compterait encore dans le groupe."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    limite = time.monotonic() + delai
    while time.monotonic() < limite:
        _ramasser(pid)
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    _ramasser(pid, bloquant=True)


def _derniere_ligne(fichier):
    fichier.seek(0)
    texte = fichier.read().decode("utf-8", "replace")
    if texte:
        sys.stderr.write(texte)         # tout reste lisible dans le journal de l'unité
    lignes = [l.strip() for l in texte.splitlines() if l.strip()]
    return lignes[-1] if lignes else ""


def _duree(secondes):
    minutes = round((secondes or 0) / 60)
    return "en moins d'une minute" if minutes < 1 else f"en {minutes} min"


def _issue(chemin, code, erreur):
    """(statut, détail) de la tâche d'après le code de sortie de l'enfant."""
    if code == 0:
        a = lire_analyse(chemin) or {}
        return "fini", f"{commun.taille(a.get('total'))} analysés {_duree(a.get('duree_s'))}"
    if code == CODE_SANS_LINSTAT:
        return "echec", SANS_LINSTAT
    if code == CODE_DEMONTE:
        return "echec", DEMONTE
    return "echec", erreur or f"L'analyse s'est arrêtée (code {code})."


def _titre(chemin):
    noms = {c: nom for nom, c in sante.volumes_suivis()}
    return f"Analyse de {noms.get(chemin) or Path(chemin).name or chemin}"


def _en_cours(id_, dossier_taches):
    return any(t.get("id") == id_ and t.get("statut") == "en_cours" for t in taches.lister(dossier_taches))


def arreter(etat, *, tuer=_tuer_groupe, dossier=None):
    """L'unité health-hub-analyse est arrêtée (SIGTERM) : bouton « Arrêter », fin de session ou extinction.
    `etat` est celui que tient le superviseur : {"id": tâche en cours, "pid": enfant en cours, "restants": volumes
    pas encore lancés}. Le groupe de l'enfant est tué (déjà mort si systemd l'a tué : ignoré) ; son résumé en
    cache n'est jamais touché. Avec le marqueur de `analyser --arreter`, la tâche dit ARRET_MANUEL et porte
    `"arret": "manuel"`, de même que les volumes en attente, et chacun reçoit un repère de pause : aucun n'est relancé
    seul pendant PAUSE_APRES_ARRET_H heures. Sans marqueur, ARRET_SYSTEME : tout reprend au relevé suivant (V15)."""
    dossier_taches = Path(dossier) / "taches" if dossier else None
    if etat.get("pid"):
        try:
            tuer(etat["pid"])
        except ProcessLookupError:
            pass
    marqueur = marqueur_arret(dossier)
    manuel = marqueur.exists()
    marqueur.unlink(missing_ok=True)
    champs = {"arret": "manuel"} if manuel else {}
    detail = ARRET_MANUEL if manuel else ARRET_SYSTEME
    # une tâche déjà finie (signal reçu juste après la fin de l'enfant) garde son statut
    if etat.get("id") and _en_cours(etat["id"], dossier_taches):
        taches.terminer(etat["id"], "interrompu", detail, dossier=dossier_taches, **champs)
        if manuel:
            _poser_pause(etat["id"].partition(":")[2], "manuel", dossier)
    if manuel:
        for chemin in etat.get("restants") or []:
            id_ = taches.debuter("analyse", chemin, _titre(chemin), unite=f"{UNITE}.service", dossier=dossier_taches)
            taches.terminer(id_, "interrompu", detail, dossier=dossier_taches, **champs)
            _poser_pause(chemin, "manuel", dossier)
    etat.update(id=None, pid=None, restants=[])


def gestionnaire_arret(etat, **options):
    """Le gestionnaire de SIGTERM du superviseur : `arreter`, puis sortie propre (code 0), sans lancer la suite."""
    def gerer(signum, frame):
        arreter(etat, **options)
        raise SystemExit(0)
    return gerer


def poser_arret(etat):
    """Pose le gestionnaire de SIGTERM. Seulement dans le processus de l'unité (CLI `_analyser`), jamais à l'import."""
    signal.signal(signal.SIGTERM, gestionnaire_arret(etat))


def superviser(chemins, *, lancer=subprocess.Popen, jeu=commun.jeu_en_cours, tuer=_tuer_groupe,
               attendre=time.sleep, est_monte=os.path.ismount, etat=None, apres_volume=None):
    """Analyse les volumes l'un après l'autre, chacun dans un processus enfant. Un volume qui n'est plus monté
    (disque débranché pendant la file) est sauté. Si un jeu démarre, l'enfant est arrêté, sa tâche passe
    « interrompu » et les volumes suivants ne sont pas lancés. `etat` (dict) suit la tâche et l'enfant en cours
    et les volumes restants, pour `arreter`. `apres_volume()` est appelé dès qu'un volume est fini (sa tâche
    écrite) : la CLI y republie stockage.json. Renvoie {chemin: statut}."""
    etat = {} if etat is None else etat
    chemins = list(chemins)
    res = {}
    for i, chemin in enumerate(chemins):
        etat.update(id=None, pid=None, restants=chemins[i:])
        if jeu():
            print(f"Un jeu tourne : analyse de {chemin} reportée.")
            break
        if not est_monte(chemin):
            print(f"{chemin} n'est plus monté : analyse sautée.")
            continue
        etat.update(id=f"analyse:{chemin}", restants=chemins[i + 1:])
        id_ = taches.debuter("analyse", chemin, _titre(chemin), unite=f"{UNITE}.service")
        pause(chemin).unlink(missing_ok=True)       # lancé (bouton « Analyser » ou pause échue) : la pause est levée
        with tempfile.TemporaryFile() as erreurs:
            try:
                proc = lancer(["nice", "-n", "19", "ionice", "-c3", sys.executable, "-m", "centre_bazzite.analyse",
                               chemin, str(cache(chemin)), "--tache", id_],
                              start_new_session=True, env=_env(), stderr=erreurs)
            except OSError as exc:
                statut, detail = "echec", f"Impossible de lancer l'analyse : {exc}"
            else:
                etat["pid"] = proc.pid
                while True:
                    attendre(INTERVALLE_S)
                    code = proc.poll()
                    if code is not None:
                        statut, detail = _issue(chemin, code, _derniere_ligne(erreurs))
                        break
                    if jeu():
                        tuer(proc.pid)
                        etat["pid"] = None
                        proc.poll()
                        statut, detail = "interrompu", INTERROMPU
                        break
        taches.terminer(id_, statut, detail)
        if statut == "echec":
            _poser_pause(chemin, "echec")           # pas de nouvel essai automatique avant RESSAI_APRES_ECHEC
        etat.update(id=None, pid=None)
        res[chemin] = statut
        print(f"{chemin} : {statut} — {detail}")
        if apres_volume:
            apres_volume()
        if statut == "interrompu":
            break
    etat.update(id=None, pid=None, restants=[])
    return res


if __name__ == "__main__":
    sys.exit(main())
