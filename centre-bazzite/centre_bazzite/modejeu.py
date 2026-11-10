"""Mode jeu automatique (spec §4.4, §6.6) : pendant une partie, Ollama est arrêté, Ne pas déranger est activé, le
profil d'énergie « performance » est tenu et les relevés lourds de Health Hub sont reportés ; tout revient comme avant
à la fin de la partie, même après un plantage du service ou un redémarrage du PC.

Sûreté :
- l'état d'avant (Ollama tournait-il ? quels modèles ?) est écrit dans modejeu.json **avant** toute action ;
- Ne pas déranger et le profil ne sont que des maintiens D-Bus (Inhibit, HoldProfile), que le bus lève si le service
  meurt : jamais SetActiveProfile ni tuned-adm, qui ne se restaurent pas ;
- Ollama n'est relancé que s'il tournait avant, dans le même démarrage du PC, si le mode jeu l'a pris en charge, et
  s'il est arrêté ;
- tout effet passe par un objet injecté (`bureau`, `run`, `ouvrir`, `jeu`, `boot`, `publier`) : ce module n'importe
  jamais dbus ; le vrai bureau est bureau.BureauDBus.

Les chemins sont calculés à l'appel : modejeu.json dans commun.ETAT (`dossier=None`), les réglages de la fenêtre à
côté de config.CHEMIN."""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import commun, config, sante, taches

ACTIONS = ("ollama", "ne_pas_deranger", "profil", "taches")
CLES = ("actif", *ACTIONS)
INTERVALLE_S = 5            # un tour de détection
ABSENCES_FIN = 2            # tours sans jeu avant la fin de partie (≈ 10 s : passe les relances de lanceurs)
ATTENTE_OLLAMA_S = 10       # comme ia-off
OLLAMA = "ollama.service"
UNITE = "health-hub-modejeu"
APPLI = "centre-bazzite"
PROFIL = "performance"
RAISON = "Health Hub : mode jeu ({jeu})"
RAISON_SANS_JEU = "Health Hub : mode jeu"
RELANCER_APRES_REDEMARRAGE = False      # D8 : Ollama n'est pas lancé au démarrage du PC (unité désactivée)
AVERTISSEMENT_MODELE = "Ollama répondait avec {modeles} : arrêté quand même, le jeu passe d'abord."
DESACTIVE = "Désactivé dans les réglages."
DEMARRAGE_ILLISIBLE = "Démarrage illisible : Ollama n'est pas touché."
_DEJA_ECRIT = {}          # {source: messages en cours} (W8-m7, W10)


def _une_fois(source, messages, ecrire=None):
    """`messages` : les messages actuels de `source` (vide quand tout va bien). La boucle repasse toutes les 5 s :
    chacun n'est écrit que lorsqu'il apparaît (W8-m7) ; un message disparu est oublié, et réécrit s'il revient (W10).
    Sur stderr, ou par `ecrire`."""
    deja = _DEJA_ECRIT.get(source, set())
    for message in messages:
        if message not in deja:
            if ecrire is None:
                print(message, file=sys.stderr)
            else:
                ecrire(message)
    _DEJA_ECRIT[source] = set(messages)


def _raison(jeu):
    """La raison donnée à D-Bus ; sans nom de jeu lisible, pas de « (None) » (W10)."""
    return RAISON.format(jeu=jeu) if jeu else RAISON_SANS_JEU


def _etat_service(run):
    """None si le service du mode jeu est arrêté (is-active : 3 inactif ou en échec, 4 unité inconnue) ;
    « service_actif » s'il tourne ; « inconnu » pour tout autre code (délai -1, gestionnaire injoignable…) (W8-m6)."""
    code = run(["systemctl", "--user", "is-active", f"{UNITE}.service"])[0]
    if code == 0:
        return "service_actif"
    return None if code in (3, 4) else "inconnu"


class BureauIndisponible(Exception):
    """Une panne du bureau (D-Bus absent, refus, délai) : l'action passe en « echec », les autres continuent."""


def _action(statut, detail):
    return {"statut": statut, "detail": detail}


def fichier(dossier=None):
    return (Path(dossier) if dossier is not None else commun.ETAT) / "modejeu.json"


def fichier_reglages():
    """Les interrupteurs de la fenêtre : ~/.config/health-hub/modejeu.json, à côté de config.toml."""
    return config.CHEMIN.with_name("modejeu.json")


def _texte(valeur):
    return valeur if isinstance(valeur, str) else None


def _partie(partie):
    """W8-m4 : une partie lue avec les types attendus, quoi que contienne le fichier. Un champ abîmé prend la valeur
    sûre : réglage décoché, Ollama arrêté avant, démarrage inconnu ; la partie se clôt alors sans relancer Ollama ni
    reprendre de maintien."""
    if not isinstance(partie, dict):
        return None
    reglages = partie.get("reglages") if isinstance(partie.get("reglages"), dict) else {}
    avant = partie.get("avant") if isinstance(partie.get("avant"), dict) else {}
    modeles = avant.get("modeles") if isinstance(avant.get("modeles"), list) else []
    actions = partie.get("actions") if isinstance(partie.get("actions"), dict) else {}
    return {"jeu": _texte(partie.get("jeu")), "debut": _texte(partie.get("debut")),
            "boot_id": _texte(partie.get("boot_id")),
            "reglages": {cle: reglages.get(cle) is True for cle in CLES},
            "avant": {"ollama": avant.get("ollama") is True, "modeles": [m for m in modeles if isinstance(m, str)]},
            "actions": {a: v for a, v in actions.items() if a in ACTIONS and isinstance(v, dict)},
            "avertissement": _texte(partie.get("avertissement"))}


def lire(dossier=None):
    """{"service", "partie", "derniere"} : chacun un dict, ou None (absent, illisible ou mal formé) ; la partie est
    normalisée (`_partie`) : un fichier abîmé ne fait jamais lever la reprise."""
    donnees = commun.lire_json(fichier(dossier), {})
    if not isinstance(donnees, dict):
        donnees = {}
    res = {cle: donnees.get(cle) if isinstance(donnees.get(cle), dict) else None for cle in ("service", "derniere")}
    res["partie"] = _partie(donnees.get("partie"))
    return res


def reglages():
    """Les défauts (tout coché), puis [modejeu] de config.toml, puis les interrupteurs de la fenêtre. Une clé inconnue
    ou une valeur non booléenne est ignorée."""
    res = dict.fromkeys(CLES, True)
    avertissements = []
    res.update(config.modejeu(avertir=avertissements.append))
    _une_fois("reglages", avertissements, config._avertir)
    fenetre = commun.lire_json(fichier_reglages(), {})
    if isinstance(fenetre, dict):
        res.update({cle: valeur for cle, valeur in fenetre.items() if cle in CLES and isinstance(valeur, bool)})
    return res


def regler(cle, valeur):
    """Un interrupteur de la fenêtre, écrit de façon atomique ; les autres clés du fichier sont gardées."""
    if cle not in CLES:
        raise ValueError(f"réglage inconnu : {cle}")
    if not isinstance(valeur, bool):
        raise ValueError(f"oui ou non attendu : {valeur!r}")
    donnees = commun.lire_json(fichier_reglages(), {})
    if not isinstance(donnees, dict):
        donnees = {}
    donnees[cle] = valeur
    commun.ecrire_json(fichier_reglages(), donnees)


def taches_en_pause(*, jeu=commun.jeu_en_cours, reglages=reglages):
    """Le nom du jeu qui tourne si les relevés lourds doivent attendre (mode jeu actif, « taches » coché), sinon None."""
    r = reglages()
    if not (r.get("actif") and r.get("taches")):
        return None
    return jeu() or None


class ModeJeu:
    """Le mode jeu d'un processus : la partie en cours et les maintiens que ce processus tient (cookies, en mémoire
    seulement : ils meurent avec ses connexions). `bureau=None` : aucun maintien possible (restauration en CLI)."""

    def __init__(self, bureau, *, run=commun.run, ouvrir=urllib.request.urlopen, jeu=commun.jeu_en_cours,
                 reglages=reglages, boot=taches.boot_id, maintenant=commun.maintenant, dossier=None,
                 publier=lambda: None, attendre=time.sleep):
        self.bureau = bureau
        self.run, self.ouvrir, self.jeu, self.reglages = run, ouvrir, jeu, reglages
        self.boot, self.maintenant, self.dossier = boot, maintenant, dossier
        self.publier, self.attendre = publier, attendre
        self.partie = None          # P5 : la boucle suit la partie qu'elle a en mémoire
        self.absences = 0
        self.a_reprendre = False    # W8-m3 : partie adoptée à la reprise, maintiens pas encore repris
        self.cookies = {}           # {"ne_pas_deranger" | "profil": cookie}

    # --- fichier et publication ---

    def _ecrire(self, **champs):
        donnees = lire(self.dossier)
        donnees.update(champs)
        commun.ecrire_json(fichier(self.dossier), donnees)

    def _publier(self):
        """P6 : une publication en échec ne coupe jamais le mode jeu."""
        try:
            self.publier()
        except Exception as exc:
            _une_fois("publication", [f"Mode jeu : état non publié ({type(exc).__name__}: {exc})"])
        else:
            _une_fois("publication", [])

    # --- Ollama ---

    def _ollama_actif(self):
        return self.run(["systemctl", "--user", "is-active", OLLAMA])[0] == 0

    def _modeles(self):
        try:
            with self.ouvrir(sante.OLLAMA_PS, timeout=3) as r:
                return [m.get("name") for m in json.loads(r.read()).get("models", []) if m.get("name")]
        except Exception:
            return []

    def _attendre_arret(self):
        """Comme ia-off : jusqu'à ATTENTE_OLLAMA_S secondes pour que l'unité ne soit plus active."""
        for _ in range(ATTENTE_OLLAMA_S):
            if not self._ollama_actif():
                return True
            self.attendre(1)
        return not self._ollama_actif()

    def _arreter_ollama(self, partie):
        if not partie["reglages"].get("ollama"):
            return _action("desactive", DESACTIVE)
        if not partie["avant"]["ollama"]:
            return _action("rien", "Ollama était déjà arrêté.")
        if partie["boot_id"] is None:       # RF-m7 : sans démarrage lisible, il ne pourrait jamais être relancé (P4)
            return _action("rien", DEMARRAGE_ILLISIBLE)
        self.run(["systemctl", "--user", "stop", OLLAMA])
        if not self._attendre_arret():
            return _action("echec", "Ollama refuse de s'arrêter.")
        if partie["avant"]["modeles"]:
            partie["avertissement"] = AVERTISSEMENT_MODELE.format(modeles=", ".join(partie["avant"]["modeles"]))
        return _action("fait", "Ollama arrêté, mémoire vidéo rendue.")

    def _meme_demarrage(self, partie):
        """P4 : un démarrage illisible (None) n'est jamais « le même »."""
        actuel = self.boot()
        return actuel is not None and partie.get("boot_id") == actuel

    def _relancer_ollama(self, partie):
        """P4 : seulement ce que le mode jeu a changé — réglage coché pour cette partie, Ollama actif avant, même
        démarrage du PC, et Ollama arrêté maintenant (s'il tourne, c'est toi qui l'as relancé)."""
        if (partie.get("reglages") or {}).get("ollama") is not True:
            return _action("desactive", DESACTIVE)
        if (partie.get("avant") or {}).get("ollama") is not True:
            return _action("rien", "Ollama n'est pas relancé : il était arrêté avant la partie.")
        if partie.get("boot_id") is None:   # RF-m7 : démarrage illisible au début, Ollama n'a pas été arrêté
            return _action("rien", "Démarrage illisible : Ollama n'est pas relancé.")
        if not self._meme_demarrage(partie) and not RELANCER_APRES_REDEMARRAGE:
            return _action("rien", "Le PC a redémarré : Ollama n'est pas relancé.")
        if self._ollama_actif():
            return _action("rien", "Ollama tourne déjà.")
        code, texte = self.run(["systemctl", "--user", "start", OLLAMA])
        if code != 0:
            return _action("echec", f"Impossible : {texte.strip() or f'code {code}'}")
        return _action("fait", "Ollama relancé.")

    # --- maintiens du bureau ---

    def _tenir(self, action, jeu):
        """Prend le maintien `action` (ne_pas_deranger ou profil) pour `jeu` ; le cookie reste en mémoire."""
        raison = _raison(jeu)
        try:
            if self.bureau is None:
                raise BureauIndisponible("aucun accès au bureau")
            if action == "ne_pas_deranger":
                self.cookies[action] = self.bureau.inhiber_notifications(raison)
                return _action("fait", "Ne pas déranger activé.")
            self.cookies[action] = self.bureau.tenir_profil(PROFIL, raison)
            return _action("fait", f"Profil « {PROFIL} » tenu pendant la partie.")
        except Exception as exc:
            return _action("echec", f"Impossible : {exc}")

    def _lacher(self):
        """Relâche le profil puis lève Ne pas déranger (seulement les cookies de ce processus), puis ferme toujours
        les connexions (P1) : un maintien obtenu dont la réponse s'est perdue tombe avec elles."""
        retour = {}
        for action, methode, detail in (("profil", "relacher_profil", "Profil d'avant rétabli."),
                                        ("ne_pas_deranger", "lever_notifications", "Ne pas déranger levé.")):
            cookie = self.cookies.pop(action, None)
            if cookie is None:
                continue
            try:
                getattr(self.bureau, methode)(cookie)
                retour[action] = _action("fait", detail)
            except Exception as exc:
                retour[action] = _action("echec", f"Impossible : {exc}")
        self._fermer()
        return retour

    def _fermer(self):
        self.cookies = {}
        if self.bureau is None:
            return
        try:
            self.bureau.fermer()
        except Exception as exc:
            _une_fois("fermeture", [f"Mode jeu : connexions D-Bus mal fermées ({type(exc).__name__}: {exc})"])
        else:
            _une_fois("fermeture", [])

    def _jeu_actuel(self):
        """W7 : une détection en erreur vaut « pas de jeu » (une absence pendant une partie) : mieux vaut rétablir le
        bureau que le figer."""
        try:
            nom = self.jeu()
        except Exception as exc:
            _une_fois("detection", [f"Mode jeu : détection du jeu en erreur ({type(exc).__name__}: {exc})"])
            return None
        _une_fois("detection", [])
        return nom

    # --- cycle d'une partie ---

    def debuter(self, nom):
        """L'état d'avant est écrit d'abord ; puis Ollama, Ne pas déranger, le profil et les tâches, chacun écrit dès
        qu'il est fait. Une action en échec n'empêche pas les suivantes. Une seule publication, à la fin (P6)."""
        r = self.reglages()
        ollama = self._ollama_actif()
        partie = {"jeu": nom, "debut": self.maintenant(), "boot_id": self.boot(),
                  "reglages": {cle: bool(r.get(cle)) for cle in CLES},
                  "avant": {"ollama": ollama, "modeles": self._modeles() if ollama else []},
                  "actions": {}, "avertissement": None}
        self._ecrire(partie=partie)
        self.partie, self.absences = partie, 0
        for action in ACTIONS:
            if action == "ollama":
                resultat = self._arreter_ollama(partie)
            elif not partie["reglages"][action]:
                resultat = _action("desactive", DESACTIVE)
            elif action == "taches":        # D10 : chaque relevé relit la condition, rien à tenir ni à remettre
                resultat = _action("fait", "Relevés de Health Hub en pause pendant la partie.")
            else:
                resultat = self._tenir(action, nom)
            partie["actions"][action] = resultat
            self._ecrire(partie=partie)
        self._publier()

    def finir(self, fin_par):
        """Remet le bureau comme avant : maintiens lâchés et connexions fermées, puis Ollama s'il le faut ; la partie
        devient la dernière (une seule écriture atomique), puis une publication (P6)."""
        partie = self.partie or lire(self.dossier)["partie"]
        retour = self._lacher()
        if partie is None:
            return
        retour["ollama"] = self._relancer_ollama(partie)
        derniere = {"jeu": partie.get("jeu"), "debut": partie.get("debut"), "fin": self.maintenant(),
                    "fin_par": fin_par, "actions": partie.get("actions") or {}, "retour": retour,
                    "avertissement": partie.get("avertissement")}
        self._ecrire(derniere=derniere, partie=None)
        self.partie, self.absences, self.a_reprendre = None, 0, False
        self._publier()

    def tour(self):
        """Un passage de la boucle : début de partie au premier jeu vu, fin après ABSENCES_FIN tours sans jeu, ou
        aussitôt si l'interrupteur général est coupé (D13)."""
        r = self.reglages()
        if self.partie is None:
            if r.get("actif"):
                nom = self._jeu_actuel()
                if nom:
                    self.debuter(nom)
            return
        if not r.get("actif"):
            self.finir("desactive")
            return
        if self._jeu_actuel():
            self.absences = 0
            if self.a_reprendre:
                self._reprendre_maintiens()
            return
        self.absences += 1
        if self.absences >= ABSENCES_FIN:
            self.finir("reprise" if self.a_reprendre else "fin")

    def _reprendre_maintiens(self):
        """Partie adoptée, jeu vu : Ne pas déranger et le profil sont repris selon les réglages de la partie ; Ollama
        n'est pas touché."""
        partie = self.partie
        for action in ("ne_pas_deranger", "profil"):
            if partie["reglages"][action]:
                partie["actions"][action] = self._tenir(action, partie["jeu"])
        self.a_reprendre = False
        self._ecrire(partie=partie)
        self._publier()

    def _reprendre(self, *, restauration):
        """La règle commune à `demarrer` et à `restaurer`, pour une partie restée ouverte dans modejeu.json : autre
        démarrage du PC → close sans relancer Ollama ; mode jeu coupé entre-temps → close aussitôt (W8-m5) ; sinon la
        règle de la boucle, ABSENCES_FIN passages sans jeu avant la fin (W8-m3) : un lanceur qui relance son jeu ne
        fait jamais relancer Ollama en pleine partie."""
        partie = lire(self.dossier)["partie"]
        if partie is None:
            return "rien"
        self.partie = partie
        if not self._meme_demarrage(partie):
            self.finir("redemarrage")
            return "redemarrage"
        if not self.reglages().get("actif"):
            self.finir("desactive")
            return "restaure"
        if restauration:
            for passage in range(ABSENCES_FIN):
                if passage:
                    self.attendre(INTERVALLE_S)
                if self._jeu_actuel():
                    return "jeu_en_cours"
            etat = _etat_service(self.run)      # W10 : le service a pu redémarrer pendant l'attente
            if etat:
                return etat
            self.finir("reprise")
            return "restaure"
        # Le service adopte la partie, sans absence comptée : `servir` attend INTERVALLE_S avant le premier tour, puis
        # ABSENCES_FIN tours sans jeu la finissent (W10).
        self.a_reprendre, self.absences = True, 0
        if self._jeu_actuel():
            self._reprendre_maintiens()
        return "continue"

    def demarrer(self):
        """Au lancement du service : `service` est écrit, puis une partie restée ouverte est adoptée (« continue » :
        maintiens repris dès que le jeu est vu, Ollama pas touché, fin après ABSENCES_FIN tours sans jeu), close
        aussitôt si le mode jeu a été coupé (« restaure »), ou close sans relancer Ollama (« redemarrage »)."""
        self._ecrire(service={"pid": os.getpid(), "boot_id": self.boot(), "depuis": self.maintenant()})
        resultat = self._reprendre(restauration=False)
        if resultat in ("rien", "continue"):        # « restaure » et « redemarrage » ont publié en fermant la partie
            self._publier()                         # etat.json dit tout de suite que le service tourne (essai T10)
        return resultat

    def suspendre(self):
        """D7 (SIGTERM : fin de session, relance d'install.sh, extinction) : les maintiens tombent avec les connexions,
        la partie reste notée ; la reprise décidera. etat.json est republié tout de suite (RF-m1) : le mode jeu y
        devient « interrompu » (partie notée) ou « arrete », qui est la vérité, au lieu de rester « actif » ou « pret »."""
        self._fermer()
        self._ecrire(service=None)
        self._publier()


def restaurer(*, si_orphelin=False, run=commun.run, jeu=commun.jeu_en_cours, boot=taches.boot_id,
              maintenant=commun.maintenant, dossier=None, attendre=time.sleep):
    """Remet le bureau comme avant si le service n'est plus là pour le faire (relevé horaire, bouton de la fenêtre).
    P5 : le service vivant est toujours vérifié d'abord, avec ou sans `si_orphelin` (gardé pour la CLI) : on ne finit
    jamais une partie dans son dos ; W8-m6 : un état inconnu (délai, gestionnaire injoignable) ne touche à rien non
    plus. Puis la règle de `_reprendre`, sans écrire `service` : un jeu vu pendant les ABSENCES_FIN passages (à
    INTERVALLE_S d'écart) → rien n'est touché."""
    etat = _etat_service(run)
    if etat:
        return etat
    mode = ModeJeu(None, run=run, jeu=jeu, boot=boot, maintenant=maintenant, dossier=dossier, attendre=attendre)
    return mode._reprendre(restauration=True)


def servir(mode, *, attendre=time.sleep, continuer=lambda: True):
    """La boucle du service health-hub-modejeu : reprise d'une partie restée ouverte, puis un tour toutes les
    INTERVALLE_S secondes. Après une reprise (« continue »), le premier tour attend lui aussi INTERVALLE_S : la partie
    adoptée n'est jamais jugée sur un trou du lanceur (W10). Un tour en erreur est écrit sur stderr et la boucle
    continue ; seules les `Exception` sont attrapées : le SystemExit du SIGTERM passe, pour que la CLI suspende
    (P11)."""
    if mode.demarrer() == "continue":
        attendre(INTERVALLE_S)
    while continuer():
        try:
            mode.tour()
        except Exception as exc:
            _une_fois("tour", [f"Mode jeu : tour en erreur ({type(exc).__name__}: {exc})"])
        else:
            _une_fois("tour", [])
        attendre(INTERVALLE_S)


# --- Résumé pour etat.json (Task 6) : lu par la fenêtre, l'accueil, le widget et `modejeu etat` ---

MOIS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
PHRASES = {"interrompu": "Mode jeu interrompu : le bureau sera remis comme avant à la reprise du service.",
           "desactive": "Mode jeu désactivé.",
           "pret": "Mode jeu prêt : il s'active quand un jeu démarre.",
           "arrete": "Le service du mode jeu ne tourne pas."}


def _date(iso):
    if isinstance(iso, datetime):
        return iso
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _heure(d):
    return f"{d.hour} h {d.minute:02d}"


def _jour(d):
    """« 9 nov. », « 1er févr. »."""
    return f"{d.day}{'er' if d.day == 1 else ''} {MOIS[d.month - 1]}"


def heure_fr(iso, maintenant):
    """« 21 h 10 » le jour de `maintenant`, sinon « le 9 nov. à 21 h 10 » ; "" pour une date illisible."""
    d, m = _date(iso), _date(maintenant)
    if d is None:
        return ""
    if m is not None and d.date() == m.date():
        return _heure(d)
    return f"le {_jour(d)} à {_heure(d)}"


def phrase_derniere(derniere, maintenant):
    """P13 : la phrase de la dernière partie, reprise telle quelle par la CLI et la fenêtre. La date seulement si ce
    n'est pas aujourd'hui ; une partie à cheval sur minuit dit ses deux jours."""
    jeu = derniere.get("jeu") or "jeu inconnu"
    debut, fin, m = _date(derniere.get("debut")), _date(derniere.get("fin")), _date(maintenant)
    if debut is None:
        return f"Dernière partie : {jeu}."
    if fin is None:
        return f"Dernière partie : {jeu}, depuis {heure_fr(debut, m)}."
    if fin.date() != debut.date():
        return f"Dernière partie : {jeu}, du {_jour(debut)} à {_heure(debut)} au {_jour(fin)} à {_heure(fin)}."
    jour = "" if m is not None and debut.date() == m.date() else f"le {_jour(debut)} "
    return f"Dernière partie : {jeu}, {jour}de {_heure(debut)} à {_heure(fin)}."


def resume(dossier=None, *, vivant=taches.pid_vivant, boot=taches.boot_id, reglages=reglages, maintenant=None):
    """Le résumé du mode jeu (D14) : {"etat", "phrase", "jeu", "depuis", "actions", "avertissement", "derniere",
    "reglages"}. Le service est vivant si son pid vit et s'il date de ce démarrage du PC (un démarrage illisible n'est
    jamais le même). États : actif (partie, service vivant), interrompu (partie sans service vivant), desactive
    (interrupteur général coupé), pret (service vivant), sinon arrete. `derniere` porte sa phrase (P13)."""
    maintenant = maintenant or commun.maintenant()
    donnees = lire(dossier)
    service, partie, derniere = donnees["service"], donnees["partie"], donnees["derniere"]
    r = reglages()
    actuel = boot() if service is not None else None
    en_vie = (service is not None and actuel is not None and service.get("boot_id") == actuel
              and vivant(service.get("pid")))
    if partie is not None:
        etat = "actif" if en_vie else "interrompu"
    else:
        etat = "desactive" if not r.get("actif") else "pret" if en_vie else "arrete"
    if etat == "actif":
        depuis = heure_fr(partie.get("debut"), maintenant)
        phrase = f"Mode jeu actif depuis {depuis}" if depuis else "Mode jeu actif"
    else:
        phrase = PHRASES[etat]
    return {"etat": etat, "phrase": phrase,
            "jeu": partie.get("jeu") if partie else None,
            "depuis": partie.get("debut") if partie else None,
            "actions": (partie.get("actions") or {}) if partie else None,
            "avertissement": partie.get("avertissement") if partie else None,
            "derniere": dict(derniere, phrase=phrase_derniere(derniere, maintenant)) if derniere else None,
            "reglages": r}
