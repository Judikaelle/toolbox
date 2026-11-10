"""Session « Tout mettre à jour » : uupd, maj-apps, notes et résumés, état, extinction éventuelle."""
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import bilan, commun, etat, inventaire, notes, resume, rpmostree, taches, uupd

DELAI_EXTINCTION = 60
CODE_REPORTE = 75
TEXTE_COMPTE_A_REBOURS = "Extinction dans 60 secondes — Annuler depuis Health Hub"
TEXTE_ANNULEE = "Extinction annulée"
MAJ_APPS = Path.home() / ".local" / "bin" / "maj-apps"
ETAPES = ("uupd", "maj-apps", "notes", "resume", "etat")
TERMINES = ("fini", "reporte", "saute", "echec")


def _fichier_annulation():
    return commun.ETAT / "annuler-extinction"


def effacer_annulation():
    _fichier_annulation().unlink(missing_ok=True)


def annulation_demandee():
    f = _fichier_annulation()
    if f.exists():
        f.unlink(missing_ok=True)
        return True
    return False


def _uupd_echoue(unite):
    code, texte = commun.run(["systemctl", "show", "-p", "Result", unite])
    return code == 0 and texte.strip().partition("=")[2] not in ("success", "")


def _lignes_uupd(unite, depuis):
    return uupd.lignes_depuis(unite, depuis.replace("T", " "))


def _maj_apps():
    return commun.run([MAJ_APPS, "--quiet"], timeout=7200)[0]


def _maj_apps_etat():
    _, texte = commun.run(["systemctl", "--user", "show", "-p", "ActiveState,SubState,Result,ExecMainStatus",
                           "maj-apps.service"])
    return dict(l.partition("=")[::2] for l in texte.splitlines() if "=" in l)


def _ecrire_leger():
    taches.reparer_orphelines()
    commun.ecrire_json(commun.ETAT / "etat.json", etat.construire(complet=False))


def _relever():
    releve = inventaire.relever()
    inventaire.enregistrer(releve)
    return releve


def _notifier(texte):
    commun.run(["notify-send", "-a", "Health Hub", texte])


def _eteindre_pc():
    """None si l'extinction est lancée, sinon le message d'erreur."""
    code, texte = commun.run(["systemctl", "poweroff"])
    return None if code == 0 else (texte.strip() or f"code de sortie {code}")


RETENTER_RESUME = timedelta(days=1)


def _essaye_recemment(tentative, maintenant):
    try:
        return datetime.fromisoformat(maintenant) - datetime.fromisoformat(tentative) < RETENTER_RESUME
    except (TypeError, ValueError):
        return False


def resumer_changements(changements, *, notes_pour=notes.notes_pour, resumer=resume.resumer,
                        jeu=commun.jeu_en_cours, maintenant=commun.maintenant):
    """Notes + résumé de chaque changement, fusionnés dans ETAT/resumes.json.
    Renvoie {"<id>@<vers>": {"resume", "source", "lien", "notes"[, "tentative"]}} pour ces changements.
    Un résumé raté (modèle muet, Ollama en panne) est noté dans "tentative" et retenté au plus une
    fois par jour, au lieu de relancer Ollama à chaque ouverture ; un jeu n'est pas une tentative."""
    chemin = commun.ETAT / "resumes.json"
    table = commun.lire_json(chemin, {})
    if not isinstance(table, dict):
        table = {}
    heure = maintenant()
    concernes, a_resumer, envoyes = {}, [], set()
    for c in changements:
        cle = f"{c['id']}@{c['vers']}"
        entree = table.get(cle)
        if not isinstance(entree, dict):
            entree = {}
        if not entree.get("resume"):
            n = notes_pour(c) or {}
            tentative = entree.get("tentative")
            entree = {"resume": None, "source": n.get("source"), "lien": n.get("lien"),
                      "notes": n.get("texte") or None}
            if tentative:
                entree["tentative"] = tentative
            if entree["notes"] and not _essaye_recemment(tentative, heure):
                a_resumer.append({"id": c["id"], "nom": c.get("nom") or c["id"], "de": c.get("de"),
                                  "vers": c.get("vers"), "notes": entree["notes"]})
                envoyes.add(cle)
        concernes[cle] = entree
    if a_resumer and not jeu():
        textes = resumer(a_resumer) or {}
        sans_jeu = not jeu()        # un jeu lancé pendant le résumé l'a interrompu : ce n'est pas un échec
        for c in changements:
            cle = f"{c['id']}@{c['vers']}"
            e = concernes[cle]
            if e.get("resume"):
                continue
            if textes.get(c["id"]):
                e["resume"] = textes[c["id"]]
                e.pop("tentative", None)
            elif sans_jeu and cle in envoyes:
                e["tentative"] = heure
    table.update(concernes)
    commun.ecrire_json(chemin, table)
    return concernes


@dataclass
class Dependances:
    uupd_actif: Callable = uupd.unite_active
    lancer_uupd: Callable = uupd.lancer
    lignes_uupd: Callable = _lignes_uupd
    lire_progression: Callable = uupd.lire_progression
    uupd_echoue: Callable = _uupd_echoue
    attendre: Callable = time.sleep
    maj_apps: Callable = _maj_apps
    maj_apps_etat: Callable = _maj_apps_etat
    relever: Callable = _relever
    resumer: Callable = resumer_changements
    ecrire_etat: Callable = etat.ecrire
    ecrire_etat_leger: Callable = _ecrire_leger
    notifier: Callable = _notifier
    eteindre_pc: Callable = _eteindre_pc
    annulation_demandee: Callable = annulation_demandee
    effacer_annulation: Callable = effacer_annulation
    jeu_en_cours: Callable = commun.jeu_en_cours
    maintenant: Callable = commun.maintenant
    deploiements: Callable = rpmostree.etat_deploiements
    historique: Path = field(default_factory=lambda: etat.HISTORIQUE_MAJ_APPS)


class _Suivi:
    """La session en cours, réécrite dans ETAT/session-en-cours.json à chaque changement."""

    def __init__(self, debut, eteindre):
        noms = ETAPES + (("extinction",) if eteindre else ())
        self.s = {"debut": debut, "fin": None, "eteindre": eteindre,
                  "etapes": {n: {"statut": "attente", "progression": 0, "detail": ""} for n in noms},
                  "global": 0, "succes": None, "extinction": None}
        self.interrompue = False
        self.lignes_uupd = []       # sortie de uupd, gardée pour le bilan de l'étape
        self.maj_apps_statut = None
        self.ecrire()

    def interrompre(self, fin):
        self.interrompue = True
        etat.marquer_interrompue(self.s, fin)

    def etape(self, nom, statut, progression=None, detail=None):
        e = self.s["etapes"][nom]
        e["statut"] = statut
        if progression is None and statut in TERMINES:
            progression = 100
        if progression is not None:
            e["progression"] = progression
        if detail is not None:
            e["detail"] = detail
        etapes = [v for k, v in self.s["etapes"].items() if k != "extinction"]
        self.s["global"] = round(sum(100 if v["statut"] in TERMINES else v["progression"]
                                     for v in etapes) / len(etapes))
        self.ecrire()

    def ecrire(self):
        try:
            commun.ecrire_json(commun.ETAT / "session-en-cours.json", self.s)
        except Exception:
            traceback.print_exc(file=sys.stderr)

    def cloturer(self, fin):
        self.s["fin"] = fin
        self.s["succes"] = not self.interrompue and \
            not any(v["statut"] == "echec" for v in self.s["etapes"].values())
        try:
            commun.ecrire_json(commun.ETAT / "sessions" / f"{self.s['debut']}.json", self.s)
        except Exception:
            traceback.print_exc(file=sys.stderr)
        try:
            (commun.ETAT / "session-en-cours.json").unlink(missing_ok=True)
        except Exception:
            traceback.print_exc(file=sys.stderr)


def _suivre_uupd(suivi, d, debut):
    unite = d.uupd_actif()
    if unite:
        detail = "déjà en cours, je la suis"
    else:
        if not d.lancer_uupd():
            suivi.etape("uupd", "echec", detail="lancement impossible")
            return
        unite, detail = "uupd-manual.service", ""
    suivi.etape("uupd", "en_cours", 0, detail)
    prog = {"etapes": {}, "global": 0, "succes": None}
    while True:
        prog = d.lire_progression(d.lignes_uupd(unite, debut))
        actuelle = next((e["titre"] for e in prog["etapes"].values() if e["statut"] == "en_cours"), detail)
        suivi.etape("uupd", "en_cours", min(prog["global"], 99), actuelle)
        if not d.uupd_actif():
            break
        d.attendre(2)
    lignes = d.lignes_uupd(unite, debut)
    suivi.lignes_uupd = lignes
    prog = d.lire_progression(lignes)
    echec = prog["succes"] is False or d.uupd_echoue(unite)
    suivi.etape("uupd", "echec" if echec else "fini", detail=detail)


def _attente_maj_apps(suivi, d):
    """Attend la fin d'un maj-apps en cours (SubState start/running) ; renvoie son statut, ou None
    si le service est inactif ou en attente de relance (auto-restart, jusqu'à 30 min)."""
    etat_ = d.maj_apps_etat()
    if etat_.get("SubState") not in ("start", "running"):
        return None
    suivi.etape("maj-apps", "en_cours", 0, "lancé par le timer")
    while etat_.get("SubState") in ("start", "running"):
        d.attendre(2)
        etat_ = d.maj_apps_etat()
    code = etat_.get("ExecMainStatus")
    if code == str(CODE_REPORTE):
        return "reporte"
    return "fini" if code == "0" and etat_.get("Result") in ("success", "", None) else "echec"


def _suivre_maj_apps(suivi, d):
    statut = _attente_maj_apps(suivi, d)
    if statut:
        suivi.etape("maj-apps", statut, detail="lancé par le timer")
        return
    suivi.etape("maj-apps", "en_cours", 0)
    code = d.maj_apps()
    statut = "reporte" if code == CODE_REPORTE else "fini" if code == 0 else "echec"
    suivi.etape("maj-apps", statut, detail="" if code in (0, CODE_REPORTE) else f"code de sortie {code}")


def _changements(diff, debut, historique):
    """(changements de la session, ceux que uupd a installés) : diff avant/après + changements maj-apps."""
    ajouts, _ = etat._changements_maj_apps(etat.lignes_historique(historique), debut)
    connus = {c["id"] for c in diff if c["categorie"] == "outils"}
    return diff + [c for c in ajouts if c["id"] not in connus]


def _resumer(suivi, d, changements):
    if d.jeu_en_cours():
        suivi.etape("notes", "saute", detail="sauté : un jeu tournait")
        suivi.etape("resume", "saute", detail="sauté : un jeu tournait")
        return
    suivi.etape("notes", "en_cours", 0)
    suivi.etape("resume", "en_cours", 0)
    table = d.resumer(changements)
    entrees = [e for e in (table.values() if isinstance(table, dict) else []) if isinstance(e, dict)]
    avec_notes = sum(1 for e in entrees if e.get("notes"))
    ecrits = sum(1 for e in entrees if e.get("resume"))
    if not changements:
        notes_, resume_ = "rien à résumer", "rien à résumer"
    else:
        n = len(changements)
        notes_ = (f"notes trouvées pour {n} changement" + ("s" if n > 1 else "")) if avec_notes == n else \
            f"notes trouvées pour {avec_notes} changement{'s' if avec_notes > 1 else ''} sur {n}" if avec_notes \
            else "aucune note trouvée"
        resume_ = f"{ecrits} résumé{'s' if ecrits > 1 else ''} écrit{'s' if ecrits > 1 else ''}" if ecrits \
            else "aucun résumé écrit"
    suivi.etape("notes", "fini", detail=notes_)
    suivi.etape("resume", "fini", detail=resume_)


def _bilan(suivi, d, avant, apres, releve_ok):
    """Détail de uupd et de maj-apps, changements et phrase de bilan de la session."""
    debut = suivi.s["debut"]
    diff = inventaire.differences(avant, apres) if releve_ok else []
    changements = _changements(diff, debut, d.historique) if releve_ok else []
    suivi.s["changements"] = changements
    etapes = suivi.s["etapes"]
    if suivi.lignes_uupd and etapes["uupd"]["statut"] in ("fini", "echec"):
        try:
            attente = bool((d.deploiements() or {}).get("en_attente"))
        except Exception:
            attente = False
        texte = bilan.detail_uupd(suivi.lignes_uupd, diff, attente)
        if texte:
            etapes["uupd"]["detail"] = texte
    maj = etapes["maj-apps"]
    if maj["statut"] == "reporte":
        maj["detail"] = "reporté (jeu en cours ou GitHub injoignable)"
    elif maj["statut"] == "fini":
        texte = bilan.detail_maj_apps(etat.lignes_historique(d.historique), debut)
        if texte:
            maj["detail"] = texte
    echec = any(etapes[n]["statut"] == "echec" for n in ("uupd", "maj-apps"))
    suivi.s["bilan"] = bilan.phrase(changements, echec=echec, inconnu=not releve_ok)
    suivi.ecrire()
    return changements


def _raison_de_rester(d):
    """Ce qui empêche d'éteindre maintenant : « annulée » (depuis la fenêtre ou le panneau, à tout
    moment de la session), un jeu en cours, ou None. Une erreur de lecture ne bloque jamais
    l'extinction : l'utilisateur n'est plus devant l'écran."""
    try:
        if d.annulation_demandee():
            return "annulée"
    except Exception:
        traceback.print_exc(file=sys.stderr)
    try:
        jeu = d.jeu_en_cours()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        jeu = None
    return f"un jeu est en cours ({jeu})" if jeu else None


def _extinction(suivi, d):
    """Compte à rebours annulable ; True si l'ordinateur doit s'éteindre."""
    raison = _raison_de_rester(d)
    if raison:
        return _annulee(suivi, d, raison)
    heure = datetime.fromisoformat(d.maintenant()) + timedelta(seconds=DELAI_EXTINCTION)
    suivi.s["extinction"] = {"a": heure.isoformat(timespec="seconds")}
    suivi.etape("extinction", "en_cours", 0)
    try:
        d.ecrire_etat_leger()
    except Exception:
        traceback.print_exc(file=sys.stderr)
    d.notifier(TEXTE_COMPTE_A_REBOURS)
    while datetime.fromisoformat(d.maintenant()) < heure:
        d.attendre(1)
        if d.annulation_demandee():
            return _annulee(suivi, d)
    suivi.etape("extinction", "fini")
    return True


def _notifier_sans_risque(d, texte):
    try:
        d.notifier(texte)
    except Exception:
        traceback.print_exc(file=sys.stderr)


def _annulee(suivi, d, raison="annulée"):
    """Enregistre l'annulation d'abord ; la notification, elle, n'est jamais fatale."""
    suivi.etape("extinction", "saute", detail=raison)
    _notifier_sans_risque(d, TEXTE_ANNULEE if raison == "annulée" else f"{TEXTE_ANNULEE} : {raison}")
    return False


def _eteindre(d):
    """None si l'extinction est lancée, sinon l'erreur (l'échec de poweroff est enregistré)."""
    try:
        return d.eteindre_pc()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return str(exc) or type(exc).__name__


def _extinction_impossible(suivi, d, erreur):
    suivi.s["extinction"] = None
    suivi.etape("extinction", "echec", detail=f"extinction impossible : {erreur}")
    suivi.cloturer(d.maintenant())
    _notifier_sans_risque(d, f"Extinction impossible : {erreur}")


def _ecrire_etat(d):
    """None si l'état est écrit, sinon le texte de l'erreur."""
    try:
        d.ecrire_etat()
        return None
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return str(exc) or type(exc).__name__


def _proteger(suivi, noms, fonction, *args):
    """Exécute une étape ; une exception la met en échec sans arrêter la session."""
    try:
        return fonction(*args)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        for nom in noms:
            suivi.etape(nom, "echec", detail=str(exc) or type(exc).__name__)


def _etape_etat(suivi, d):
    suivi.etape("etat", "en_cours", 0)
    erreur = _ecrire_etat(d)
    suivi.etape("etat", "echec" if erreur else "fini", detail=erreur or "")


def _releve(d):
    try:
        return d.relever(), None
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return {}, str(exc) or type(exc).__name__


class Interrompue(SystemExit):
    """Levée à la réception de SIGTERM (reboot, arrêt de l'unité, fermeture de la session) :
    les blocs finally s'exécutent, donc la session s'archive avant de sortir (code 143)."""


def _sur_sigterm(signum, _cadre):
    raise Interrompue(128 + signum)


_AUCUN = object()


def _poser_sigterm():
    try:
        return signal.signal(signal.SIGTERM, _sur_sigterm)
    except ValueError:      # hors du fil principal : pas de gestionnaire possible
        return _AUCUN


def executer(eteindre, *, deps):
    precedent = _poser_sigterm()
    try:
        return _executer(eteindre, deps)
    finally:
        if precedent is not _AUCUN:
            signal.signal(signal.SIGTERM, precedent)


def _archiver_ancienne(debut):
    """Une session précédente coupée sans avoir pu s'archiver (fichier en cours resté) est archivée."""
    try:
        ancienne = commun.lire_json(commun.ETAT / "session-en-cours.json", None)
        if isinstance(ancienne, dict) and ancienne.get("debut") != debut:
            etat.archiver_interrompue(ancienne)
    except Exception:
        traceback.print_exc(file=sys.stderr)


def _executer(eteindre, d):
    debut = d.maintenant()
    try:
        d.effacer_annulation()
    except Exception:
        traceback.print_exc(file=sys.stderr)
    _archiver_ancienne(debut)
    suivi = _Suivi(debut, eteindre)
    partir = False
    try:
        avant, err1 = _releve(d)
        _proteger(suivi, ("uupd",), _suivre_uupd, suivi, d, debut)
        _proteger(suivi, ("maj-apps",), _suivre_maj_apps, suivi, d)
        apres, err2 = _releve(d)
        ok = not (err1 or err2)
        changements = _proteger(suivi, ("etat",), _bilan, suivi, d, avant, apres, ok) or []
        if not ok:
            for nom in ("notes", "resume"):
                suivi.etape(nom, "echec", detail="relevé impossible : " + (err1 or err2))
        else:
            _proteger(suivi, ("notes", "resume"), _resumer, suivi, d, changements)
        _proteger(suivi, ("etat",), _etape_etat, suivi, d)
        if eteindre:
            partir = _proteger(suivi, ("extinction",), _extinction, suivi, d) is not False
            # une exception dans le compte à rebours donne None : l'extinction n'est jamais bloquée
    except (Interrompue, KeyboardInterrupt):
        partir = False
        suivi.interrompre(d.maintenant())
        raise
    finally:
        suivi.cloturer(d.maintenant())
        if partir:
            raison = _raison_de_rester(d)   # dernier contrôle, juste avant l'extinction
            if raison:
                _annulee(suivi, d, raison)
                suivi.cloturer(d.maintenant())
                partir = False
            else:
                erreur = _eteindre(d)
                if erreur:
                    _extinction_impossible(suivi, d, erreur)
                    partir = False
    if not partir:
        _ecrire_etat(d)
    return suivi.s
