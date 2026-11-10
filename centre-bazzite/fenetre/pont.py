"""Pont entre la fenêtre QML et le moteur : lit etat.json et lance la CLI du Health Hub.
La fenêtre ne calcule rien : elle affiche l'état écrit par le moteur et lui délègue chaque action."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QProcess, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))     # le moteur : centre_bazzite.taches
from centre_bazzite import menage as moteur_menage  # noqa: E402
from centre_bazzite import taches as moteur_taches  # noqa: E402

PROGRAMME = "centre-bazzite"
ETAT_JSON = Path.home() / ".local" / "state" / "centre-bazzite" / "etat.json"
INTERVALLE_SUIVI_MS = 5000
# Tours de suivi accordés après un lancement, le temps que la session apparaisse dans l'état.
TOURS_APRES_LANCEMENT = 3
SESSIONS_MAX = 30
TACHES_MAX = 20
RECENTE = timedelta(hours=24)
# Les étapes d'une session « Tout mettre à jour », dans l'ordre du moteur (copie de session.ETAPES + extinction).
ORDRE_ETAPES = ("uupd", "maj-apps", "notes", "resume", "etat", "extinction")
NOMS_ETAPES = {"uupd": "Mise à jour du système", "maj-apps": "Mise à jour des outils",
               "notes": "Notes de version", "resume": "Résumé des nouveautés",
               "etat": "Bilan de santé", "extinction": "Extinction"}


def _etapes(session):
    etapes = session.get("etapes") or {}
    return [{"nom": n, "titre": NOMS_ETAPES[n], "statut": e.get("statut", "attente"),
             "progression": e.get("progression", 0), "detail": e.get("detail", "")}
            for n in ORDRE_ETAPES if isinstance((e := etapes.get(n)), dict)]


def _tache_session(s, statut, progression, detail):
    return {"id": f"maj:{s.get('debut')}", "type": "maj", "titre": "Tout mettre à jour", "statut": statut,
            "progression": progression, "detail": detail, "debut": s.get("debut"), "fin": s.get("fin"),
            "unite": None, "etapes": _etapes(s), "journal": []}


def _date(texte):
    try:
        return datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def taches_affichees(etat, sessions, fichiers, vue_session, maintenant):
    """Ce que montre le panneau Activité : la session en cours, la dernière session finie (24 h, tant qu'on ne
    l'a pas effacée), puis les tâches des fichiers. En cours d'abord, puis les plus récentes ; 20 au plus."""
    res = []
    en_cours = etat.get("en_cours") if isinstance(etat, dict) else None
    if isinstance(en_cours, dict) and en_cours.get("debut"):
        courante = next((n for n in ORDRE_ETAPES
                         if (en_cours.get("etapes") or {}).get(n, {}).get("statut") == "en_cours"), None)
        detail = (en_cours["etapes"][courante].get("detail") or "") if courante else ""
        titre = NOMS_ETAPES.get(courante, "")
        res.append(_tache_session(en_cours, "en_cours", en_cours.get("global", -1),
                                  f"{titre} : {detail}" if titre and detail else titre))
    elif isinstance(en_cours, dict):
        res.append({"id": "maj:uupd", "type": "maj", "titre": NOMS_ETAPES["uupd"], "statut": "en_cours",
                    "progression": -1, "detail": "", "debut": None, "fin": None,
                    "unite": en_cours.get("unite"), "etapes": [], "journal": []})
    vivante = en_cours.get("debut") if isinstance(en_cours, dict) else None
    derniere = next((s for s in sessions if s.get("fin") and s.get("debut") != vivante), None)
    if derniere is not None:
        fin = _date(derniere["fin"])
        if fin and maintenant - fin < RECENTE and str(derniere.get("debut", "")) > (vue_session or ""):
            res.append(_tache_session(derniere, "fini" if derniere.get("succes") else "echec", 100,
                                      derniere.get("bilan") or ""))
    res.extend(fichiers)
    res.sort(key=lambda t: str(t.get("debut") or ""), reverse=True)
    res.sort(key=lambda t: t.get("statut") != "en_cours")
    return res[:TACHES_MAX]


class Pont(QObject):
    etatChange = Signal()
    tachesChange = Signal()
    stockageChange = Signal()

    def __init__(self, chemin=ETAT_JSON, intervalle_ms=INTERVALLE_SUIVI_MS, parent=None, presse_papiers=None,
                 etat_force=False):
        super().__init__(parent)
        # État forcé (--etat, captures) : le pont affiche un dossier de fixture et ne lance aucune commande.
        self._etat_force = etat_force
        self._chemin = Path(chemin)
        self._etat = {}
        self._taches = []
        self._stockage = {}
        self._presse_papiers = presse_papiers
        self._tours_restants = 0
        self._veilleur = QFileSystemWatcher(self)
        self._veilleur.fileChanged.connect(self.recharger)
        self._veilleur.directoryChanged.connect(self.recharger)
        self._minuteur = QTimer(self)
        self._minuteur.setInterval(intervalle_ms)
        self._minuteur.timeout.connect(self._suivre)
        try:
            self._chemin.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.recharger()

    def _lire_etat(self):
        return self._etat

    etat = Property("QVariantMap", _lire_etat, notify=etatChange)

    def _lire_sessions(self):
        """Les sessions de mise à jour passées (dossier « sessions » à côté d'etat.json), la plus récente d'abord."""
        sessions = []
        for fichier in sorted((self._chemin.parent / "sessions").glob("*.json"), reverse=True):
            try:
                donnees = json.loads(fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(donnees, dict):
                sessions.append(donnees)
        sessions.sort(key=lambda s: str(s.get("debut", "")), reverse=True)
        return sessions[:SESSIONS_MAX]

    sessions = Property("QVariantList", _lire_sessions, notify=etatChange)

    def _lire_taches(self):
        return self._taches

    taches = Property("QVariantList", _lire_taches, notify=tachesChange)

    def _calculer_taches(self):
        dossier = self._chemin.parent / "taches"
        return taches_affichees(self._etat, self._lire_sessions(), moteur_taches.lister(dossier),
                                moteur_taches.vue_session(dossier), datetime.now())

    def _lire_stockage(self):
        return self._stockage

    stockage = Property("QVariantMap", _lire_stockage, notify=stockageChange)

    @Slot()
    def recharger(self):
        """Relit etat.json, stockage.json et les tâches ; un fichier absent ou illisible garde l'état précédent."""
        self._surveiller()
        try:
            donnees = json.loads(self._chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            donnees = None
        if isinstance(donnees, dict) and donnees != self._etat:
            self._etat = donnees
            self.etatChange.emit()
        try:
            stock = json.loads((self._chemin.parent / "stockage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stock = None
        if isinstance(stock, dict) and stock != self._stockage:
            self._stockage = stock
            self.stockageChange.emit()
        taches = self._calculer_taches()
        if taches != self._taches:
            self._taches = taches
            self.tachesChange.emit()
        self._ajuster_suivi()

    def _surveiller(self):
        # Le moteur remplace etat.json (écriture atomique) : le veilleur perd alors le fichier,
        # d'où la surveillance du dossier et le réarmement à chaque lecture.
        dossier, fichier = str(self._chemin.parent), str(self._chemin)
        if self._chemin.parent.is_dir() and dossier not in self._veilleur.directories():
            self._veilleur.addPath(dossier)
        if self._chemin.exists() and fichier not in self._veilleur.files():
            self._veilleur.addPath(fichier)
        # Les tâches : un fichier par tâche, remplacé à chaque avancée, d'où la surveillance du dossier.
        taches = str(self._chemin.parent / "taches")
        if Path(taches).is_dir() and taches not in self._veilleur.directories():
            self._veilleur.addPath(taches)

    def _ajuster_suivi(self):
        """Pendant une mise à jour ou un compte à rebours, l'état est recalculé toutes les 5 s."""
        actif = bool(self._etat.get("en_cours") or self._etat.get("extinction")) \
            or self._tours_restants > 0
        if actif and not self._minuteur.isActive():
            self._minuteur.start()
        elif not actif:
            self._minuteur.stop()

    def _suivre(self):
        if self._tours_restants > 0:
            self._tours_restants -= 1
        self.rafraichir()
        self.recharger()

    def _demarrer(self, programme, arguments):
        """Point unique de lancement des commandes : rien ne part sur un état forcé."""
        if self._etat_force:
            return
        ok, _pid = QProcess.startDetached(programme, [str(a) for a in arguments])
        if not ok:
            print(f"Impossible de lancer : {programme} {' '.join(map(str, arguments))}", file=sys.stderr)

    def _cli(self, *arguments):
        self._demarrer(PROGRAMME, arguments)

    def _suivre_un_moment(self):
        """Quelques rafraîchissements de l'état après une action, le temps qu'elle produise son effet."""
        self._tours_restants = TOURS_APRES_LANCEMENT
        self._ajuster_suivi()

    def _lancer_mise_a_jour(self, *options):
        self._cli("maj", *options)
        self._suivre_un_moment()

    # memeSiJeu : l'utilisateur a confirmé « Lancer quand même » alors qu'un jeu tourne (sinon la CLI refuse).
    @Slot()
    @Slot(bool)
    def toutMettreAJour(self, memeSiJeu=False):
        self._lancer_mise_a_jour(*(["--meme-si-jeu"] if memeSiJeu else []))

    @Slot()
    @Slot(bool)
    def mettreAJourEtEteindre(self, memeSiJeu=False):
        self._lancer_mise_a_jour("--eteindre", *(["--meme-si-jeu"] if memeSiJeu else []))

    @Slot()
    def annulerExtinction(self):
        self._cli("annuler-extinction")

    @Slot()
    def redemarrer(self):
        self._cli("redemarrer")

    @Slot(str)
    def sourdine(self, point_id):
        self._cli("sourdine", point_id)

    @Slot(str)
    def sansSourdine(self, point_id):
        self._cli("sans-sourdine", point_id)

    @Slot()
    def arreterOllama(self):
        self._demarrer("systemctl", ["--user", "stop", "ollama.service"])
        self._suivre_un_moment()

    @Slot()
    def rafraichir(self):
        self._cli("rafraichir", "--leger")

    @Slot()
    def verifier(self):
        """« Vérifier maintenant » : un rafraîchissement complet (le léger ne relit pas la santé)."""
        self._cli("rafraichir")
        self._suivre_un_moment()

    @Slot()
    def rafraichirStockage(self):
        """Ouverture de la page Stockage : relève les disques et leurs volumes (lecture seule)."""
        self._cli("stockage")

    def _volume_connu(self, chemin):
        return any(isinstance(v, dict) and v.get("chemin") == chemin and chemin
                   for d in self._stockage.get("disques") or [] if isinstance(d, dict)
                   for v in d.get("volumes") or [])

    @Slot(str)
    def analyser(self, chemin):
        """« Analyser » : lance l'analyse LinStat d'un volume (seulement ceux de stockage.json)."""
        if self._volume_connu(chemin):
            self._cli("analyser", chemin)
            self._suivre_un_moment()

    @Slot()
    def arreterAnalyse(self):
        """« Arrêter » : arrête l'analyse en cours (la CLI ne fait rien s'il n'y en a pas)."""
        self._cli("analyser", "--arreter")
        self._suivre_un_moment()

    @Slot(str)
    def carteDetaillee(self, chemin):
        """« Carte détaillée » : ouvre la fenêtre LinStat sur un volume, si sa commande est connue."""
        commande = (self._stockage.get("linstat") or {}).get("commande")
        if commande and self._volume_connu(chemin):
            self._demarrer(commande, [chemin])

    @Slot(str, "QVariantList")
    def menage(self, id_, elements):
        """« Libérer… » confirmé : lance le ménage d'une recommandation de stockage.json avec l'empreinte des
        `elements` que le dialogue a montrés (cible, libellé, taille ; obligatoires, Ruling V60) : la CLI ne fait rien
        si sa liste a changé depuis, puis revérifie chaque élément. Une commande à copier (le journal) n'est jamais
        lancée."""
        reco = next((r for r in self._stockage.get("recommandations") or []
                     if isinstance(r, dict) and r.get("id") == id_ and id_), None)
        if reco is None or reco.get("mode") == "copier":
            return
        self._cli("menage", id_, "--empreinte", moteur_menage.empreinte(list(elements)))
        self._suivre_un_moment()

    @Slot()
    def effacerTerminees(self):
        self._cli("taches", "--effacer")

    @Slot(str)
    def copier(self, texte):
        """Met le texte dans le presse-papiers (résolu à l'appel : le pont se crée aussi sans QGuiApplication)."""
        (self._presse_papiers or QGuiApplication.clipboard()).setText(texte)

    @Slot()
    def marquerVu(self):
        self._cli("vu")

    @Slot()
    def resumer(self):
        self._cli("resumer")

    @Slot(str)
    def agir(self, point_id):
        """Lance l'action proposée par un point signalé ; seules les commandes de etat.json sont lancées."""
        for p in self._etat.get("points") or []:
            if isinstance(p, dict) and p.get("id") == point_id:
                commande = (p.get("action") or {}).get("commande") or []
                if commande:
                    self._demarrer(commande[0], commande[1:])
                    self._suivre_un_moment()
                return
