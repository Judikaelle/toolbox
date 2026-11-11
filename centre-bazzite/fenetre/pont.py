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
from centre_bazzite import modejeu as moteur_modejeu  # noqa: E402
from centre_bazzite import taches as moteur_taches  # noqa: E402

PROGRAMME = "centre-bazzite"
ETAT_JSON = Path.home() / ".local" / "state" / "centre-bazzite" / "etat.json"
INTERVALLE_SUIVI_MS = 5000
# Tours de suivi accordés après un lancement, le temps que la session apparaisse dans l'état.
TOURS_APRES_LANCEMENT = 3
SESSIONS_MAX = 30
TACHES_MAX = 20
RECENTE = timedelta(hours=24)
# UI-m2 : « Remettre le bureau comme avant » lance `modejeu restaurer`, qui écrit cette tâche du panneau Activité ; le
# bouton attend sa fin (au plus ATTENTE_RESTAURATION_MS) et montre sa phrase.
RESTAURATION = "modejeu:restaurer"
ATTENTE_RESTAURATION_MS = 120000
SANS_NOUVELLES = "Pas de nouvelles de la remise du bureau : regarde le panneau Activité."
# I-4 : une ligne de « Au lancement » reste « occupée » jusqu'à la réponse de sa commande, au plus ce délai.
ATTENTE_DEMARRAGE_MS = 30000
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
    jeuxChange = Signal()
    demarrageChange = Signal()
    demarrageOccupeChange = Signal()
    restaurationChange = Signal()

    def __init__(self, chemin=ETAT_JSON, intervalle_ms=INTERVALLE_SUIVI_MS, parent=None, presse_papiers=None,
                 etat_force=False):
        super().__init__(parent)
        # État forcé (--etat, captures) : le pont affiche un dossier de fixture et ne lance aucune commande.
        self._etat_force = etat_force
        self._chemin = Path(chemin)
        self._etat = {}
        self._taches = []
        self._stockage = {}
        self._jeux = {}
        self._demarrage = {}
        self._presse_papiers = presse_papiers
        self._tours_restants = 0
        self._veilleur = QFileSystemWatcher(self)
        self._veilleur.fileChanged.connect(self.recharger)
        self._veilleur.directoryChanged.connect(self.recharger)
        self._minuteur = QTimer(self)
        self._minuteur.setInterval(intervalle_ms)
        self._minuteur.timeout.connect(self._suivre)
        # UI-m2 : la remise du bureau lancée par la fenêtre, une seule à la fois.
        self._en_restauration = False
        self._tache_avant = None            # la tâche « modejeu:restaurer » telle qu'elle était au clic
        self._retour_restauration = ""      # la phrase de la dernière remise finie
        self._delai_restauration = QTimer(self)
        self._delai_restauration.setSingleShot(True)
        self._delai_restauration.setInterval(ATTENTE_RESTAURATION_MS)
        self._delai_restauration.timeout.connect(self._sans_nouvelles)
        # I-4 : les lignes de « Au lancement » dont la commande tourne -> `genere` de demarrage.json au clic.
        self._occupes = {}
        self._delai_demarrage = QTimer(self)
        self._delai_demarrage.setSingleShot(True)
        self._delai_demarrage.setInterval(ATTENTE_DEMARRAGE_MS)
        self._delai_demarrage.timeout.connect(self._liberer_demarrage)
        self.demarrageChange.connect(self._suivre_demarrage)
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

    def _lire_jeux(self):
        return self._jeux

    jeux = Property("QVariantMap", _lire_jeux, notify=jeuxChange)

    def _lire_demarrage(self):
        return self._demarrage

    demarrage = Property("QVariantMap", _lire_demarrage, notify=demarrageChange)

    def _lire_occupes(self):
        return list(self._occupes)

    demarrageOccupes = Property("QVariantList", _lire_occupes, notify=demarrageOccupeChange)

    def _lire_en_restauration(self):
        return self._en_restauration

    restaurationEnCours = Property(bool, _lire_en_restauration, notify=restaurationChange)

    def _lire_retour_restauration(self):
        return self._retour_restauration

    retourRestauration = Property(str, _lire_retour_restauration, notify=restaurationChange)

    @Slot()
    def recharger(self):
        """Relit etat.json, stockage.json, jeux.json, demarrage.json et les tâches ; un fichier absent ou illisible garde l'état
        précédent."""
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
        try:
            jeux = json.loads((self._chemin.parent / "jeux.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            jeux = None
        if isinstance(jeux, dict) and jeux != self._jeux:
            self._jeux = jeux
            self.jeuxChange.emit()
        try:
            demarrage = json.loads((self._chemin.parent / "demarrage.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            demarrage = None
        if isinstance(demarrage, dict) and demarrage != self._demarrage:
            self._demarrage = demarrage
            self.demarrageChange.emit()
        taches = self._calculer_taches()
        if taches != self._taches:
            self._taches = taches
            self.tachesChange.emit()
        self._suivre_restauration()
        self._oublier_retour_si_partie()
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
        """Point unique de lancement des commandes : rien ne part sur un état forcé. Vrai si la commande est partie."""
        if self._etat_force:
            return False
        ok, _pid = QProcess.startDetached(programme, [str(a) for a in arguments])
        if not ok:
            print(f"Impossible de lancer : {programme} {' '.join(map(str, arguments))}", file=sys.stderr)
        return bool(ok)

    def _cli(self, *arguments):
        return self._demarrer(PROGRAMME, arguments)

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

    def _partie_en_cours(self):
        """Un jeu vu par le dernier état, ou le mode jeu actif."""
        modejeu = self._etat.get("modejeu")
        return bool(self._etat.get("jeu")) or (isinstance(modejeu, dict) and modejeu.get("etat") == "actif")

    @Slot()
    def rafraichirJeux(self):
        """Ouverture de la page Jeux : relève les bibliothèques (jeux.json), le stockage (le ménage des jeux vit dans
        stockage.json) et l'état (le résumé du mode jeu). Lecture seule. Pendant une partie, seulement l'état (RF-m3) :
        les relevés lourds attendent, comme ceux du relevé horaire (D10)."""
        if not self._partie_en_cours():
            self._cli("jeux")
            self._cli("stockage")
        self._cli("rafraichir", "--leger")

    @Slot()
    def rafraichirDemarrage(self):
        """Ouverture de la page Démarrage : relève la durée, ce qui se lance tout seul et les services (lecture seule)."""
        self._cli("demarrage")

    @Slot(str, bool)
    def reglerDemarrage(self, id_, actif):
        """Une bascule de « Au lancement » : la CLI revérifie que l'entrée est modifiable (id verrouillé ou inconnu :
        refusé, rien n'est touché). Elle republie demarrage.json, avec son retour, que le pont relit."""
        self._occuper(id_, "regler", id_, "oui" if actif else "non")

    @Slot(str)
    def remettreDemarrage(self, id_):
        """« Remettre comme avant » : la CLI rend l'état noté au journal, seulement si l'entrée n'a pas changé depuis."""
        self._occuper(id_, "remettre", id_)

    def _occuper(self, id_, *arguments):
        """Lance `demarrage <arguments>` pour une ligne libre ; partie, la ligne est « occupée » (I-4) : un second clic
        ne relance rien. Rien ne part sur un état forcé (V46)."""
        if id_ in self._occupes or not self._cli("demarrage", *arguments):
            return
        self._occupes[id_] = self._demarrage.get("genere")
        self._delai_demarrage.start()
        self.demarrageOccupeChange.emit()

    def _suivre_demarrage(self):
        """La réponse d'une commande : demarrage.json réécrit (`genere` changé) avec le retour de son entrée. Un relevé
        qui finit entre-temps (sans ce retour) ne libère pas la ligne."""
        retour = self._demarrage.get("retour")
        id_ = retour.get("id") if isinstance(retour, dict) else None
        if id_ in self._occupes and self._demarrage.get("genere") != self._occupes[id_]:
            del self._occupes[id_]
            if not self._occupes:
                self._delai_demarrage.stop()
            self.demarrageOccupeChange.emit()

    def _liberer_demarrage(self):
        """Pas de réponse à temps (CLI absente, demarrage.json impossible à écrire) : les lignes reviennent."""
        if self._occupes:
            self._occupes.clear()
            self.demarrageOccupeChange.emit()

    def _gels(self):
        gels = self._jeux.get("gels")
        return gels if isinstance(gels, dict) else {}

    @Slot(str)
    def ouvrirGel(self, fichier):
        """« Ouvrir » d'une capture de gel : seulement un nom de fichier (sans « / ») de jeux.json, dans le dossier des
        gels ; la capture s'ouvre avec l'application par défaut."""
        gels = self._gels()
        dossier = gels.get("dossier")
        if not fichier or "/" in fichier or fichier in (".", "..") or not isinstance(dossier, str) or not dossier:
            return
        chemin = Path(dossier) / fichier
        if any(isinstance(g, dict) and isinstance(g.get("fichier"), str) and Path(g["fichier"]) == chemin
               for g in gels.get("liste") or []):
            self._demarrer("xdg-open", [str(chemin)])

    @Slot()
    def ouvrirDossierGels(self):
        """« Ouvrir le dossier » des captures de gel, s'il est connu (jeux.json)."""
        dossier = self._gels().get("dossier")
        if isinstance(dossier, str) and dossier:
            self._demarrer("xdg-open", [dossier])

    @Slot(str, bool)
    def reglerModeJeu(self, cle, valeur):
        """Un interrupteur du mode jeu : seulement une clé connue du moteur ; l'état suit quelques secondes."""
        if cle not in moteur_modejeu.CLES:
            return
        self._cli("modejeu", "regler", cle, "oui" if valeur else "non")
        self._suivre_un_moment()

    @Slot()
    def restaurerModeJeu(self):
        """« Remettre le bureau comme avant » : `modejeu restaurer`, qui ne fait rien si le service tourne (P5). Une
        seule à la fois (UI-m2) : elle est « en cours » jusqu'à la fin de la tâche que la CLI écrit, dont la phrase
        devient le retour montré par la fenêtre."""
        if self._en_restauration or not self._cli("modejeu", "restaurer"):
            return
        self._tache_avant = self._tache_restauration()
        self._en_restauration, self._retour_restauration = True, ""
        self.restaurationChange.emit()
        self._delai_restauration.start()
        self._suivre_un_moment()

    def _tache_restauration(self):
        return next((t for t in self._taches if isinstance(t, dict) and t.get("id") == RESTAURATION), None)

    def _suivre_restauration(self):
        """La remise lancée par la fenêtre est finie quand sa tâche, une autre que celle d'avant le clic (le pid du
        processus y est noté), a un statut final."""
        if not self._en_restauration:
            return
        t = self._tache_restauration()
        if t is not None and t != self._tache_avant and t.get("statut") in moteur_taches.STATUTS_FINAUX:
            self._fin_restauration(str(t.get("detail") or ""))

    def _oublier_retour_si_partie(self):
        """La phrase de la dernière remise ne reste pas affichée pendant la partie suivante."""
        modejeu = self._etat.get("modejeu") if isinstance(self._etat, dict) else None
        if (self._retour_restauration and not self._en_restauration and isinstance(modejeu, dict)
                and modejeu.get("etat") == "actif"):
            self._retour_restauration = ""
            self.restaurationChange.emit()

    def _sans_nouvelles(self):
        """Aucune tâche finie à temps (CLI absente, plantée avant d'écrire sa tâche) : le bouton revient et le dit."""
        if self._en_restauration:
            self._fin_restauration(SANS_NOUVELLES)

    def _fin_restauration(self, retour):
        self._delai_restauration.stop()
        self._en_restauration, self._tache_avant, self._retour_restauration = False, None, retour
        self.restaurationChange.emit()

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
