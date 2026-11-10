"""Mode jeu automatique : réglages, partie, restauration après un faux plantage (Task 4) ; boucle du service, CLI,
report des relevés, unités et install.sh (Task 5). Tout est injecté : faux systemctl (FauxRun), faux /api/ps, faux
bureau (tests/faux_bureau.py), dossier d'état temporaire, configuration temporaire. Filet (P2) : setUpModule remplace
subprocess.run par un enregistreur, et tearDownModule exige qu'aucune commande réelle n'ait été tentée (commun.run
avale les exceptions : un oubli d'injection passerait inaperçu). install.sh et les unités ne sont lus qu'en texte."""
import contextlib
import io
import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, config, inventaire, modejeu, sante, stockage, taches
from tests import configuration
from tests.faux_bureau import FauxBureau, FauxSysteme

COMMANDES_REELLES = []
_VRAI_RUN = []


def setUpModule():
    _VRAI_RUN.append(commun.subprocess.run)

    def filet(cmd, *args, **kwargs):
        COMMANDES_REELLES.append([str(c) for c in cmd])
        raise OSError("filet des tests : aucune commande réelle")
    commun.subprocess.run = filet


def tearDownModule():
    commun.subprocess.run = _VRAI_RUN.pop()
    if COMMANDES_REELLES:
        raise AssertionError(f"commandes réelles tentées pendant les tests : {COMMANDES_REELLES}")


OLLAMA = "ollama.service"
SERVICE = "health-hub-modejeu.service"
JEU = "Jeu de course"
BOOT = "boot-1"
HEURE = "2026-11-10T21:10:00"
TOUT = dict.fromkeys(("actif", "ollama", "ne_pas_deranger", "profil", "taches"), True)
RAISON = "Health Hub : mode jeu (Jeu de course)"


def action(statut, detail):
    return {"statut": statut, "detail": detail}


class FauxRun:
    """Faux `systemctl --user` : is-active selon `actifs`, stop et start changent l'état ; chaque commande est gardée.
    `au_stop` : fonctions appelées quand stop arrive (avant son effet) ; `refuse_stop` : l'unité reste active."""

    def __init__(self, *, ollama=True, service=False):
        self.actifs = {OLLAMA: ollama, SERVICE: service}
        self.refuse_stop = False
        self.au_stop = []
        self.appels = []

    def __call__(self, cmd, timeout=120, entree=None):
        cmd = [str(c) for c in cmd]
        self.appels.append(cmd)
        if cmd[:2] != ["systemctl", "--user"] or len(cmd) != 4:
            return 1, f"commande inattendue : {cmd}"
        verbe, unite = cmd[2], cmd[3]
        if verbe == "is-active":
            return (0, "active\n") if self.actifs.get(unite) else (3, "inactive\n")
        if verbe == "stop":
            for f in self.au_stop:
                f()
            if not self.refuse_stop:
                self.actifs[unite] = False
            return 0, ""
        if verbe == "start":
            self.actifs[unite] = True
            return 0, ""
        return 1, f"verbe inattendu : {verbe}"

    def ordres(self, unite=OLLAMA):
        """Les stop et start reçus pour `unite`, dans l'ordre."""
        return [c[2] for c in self.appels if c[2] in ("stop", "start") and c[3] == unite]


def faux_ouvrir(*modeles):
    """Faux urlopen de /api/ps : les modèles chargés ; `ouvrir.urls` garde (url, timeout)."""
    def ouvrir(url, timeout=None):
        ouvrir.urls.append((url, timeout))
        return io.BytesIO(json.dumps({"models": [{"name": m} for m in modeles]}).encode())
    ouvrir.urls = []
    return ouvrir


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = Path(d.name) / "etat"
        self.config = self.enterContext(configuration(""))
        self.systeme = FauxSysteme()
        self.run = FauxRun()
        self.jeu = JEU
        self.boot = BOOT
        self.publications = []
        self.attentes = []
        self.enterContext(mock.patch.object(modejeu, "_DEJA_ECRIT", {}))

    def mode(self, bureau=None, **kw):
        options = dict(run=self.run, ouvrir=faux_ouvrir(), jeu=lambda: self.jeu, boot=lambda: self.boot,
                       maintenant=lambda: HEURE, dossier=self.dossier,
                       publier=lambda: self.publications.append(1), attendre=self.attentes.append)
        options.update(kw)
        return modejeu.ModeJeu(bureau or FauxBureau(self.systeme), **options)

    def restaurer(self, **kw):
        options = dict(run=self.run, jeu=lambda: self.jeu, boot=lambda: self.boot, maintenant=lambda: HEURE,
                       dossier=self.dossier, attendre=self.attentes.append)
        options.update(kw)
        return modejeu.restaurer(**options)

    def lire(self):
        return modejeu.lire(self.dossier)

    def finir_par_absences(self, mode):
        self.jeu = None
        mode.tour()
        mode.tour()

    def assertSystemeVide(self):
        self.assertEqual((self.systeme.notifications, self.systeme.profils), ({}, {}))


class Filet(unittest.TestCase):
    def test_le_filet_arrete_toute_commande_reelle(self):
        self.assertEqual(commun.run(["true"])[0], -1)
        self.assertEqual(COMMANDES_REELLES.pop(), ["true"])


class Reglages(Base):
    def test_reglages_par_defaut_tout_coche(self):
        self.assertEqual(modejeu.CLES, ("actif", "ollama", "ne_pas_deranger", "profil", "taches"))
        self.assertEqual(modejeu.ACTIONS, modejeu.CLES[1:])
        self.assertEqual(config.modejeu(), TOUT)
        self.assertEqual(modejeu.reglages(), TOUT)

    def test_reglages_config_puis_fenetre(self):
        with configuration("[modejeu]\nollama = false\n") as chemin:
            self.assertEqual(config.modejeu(), {**TOUT, "ollama": False})
            self.assertFalse(modejeu.reglages()["ollama"])
            modejeu.regler("ollama", True)
            self.assertTrue(modejeu.reglages()["ollama"])
            self.assertEqual(modejeu.fichier_reglages(), chemin.with_name("modejeu.json"))
            modejeu.regler("profil", False)         # les autres clés sont gardées
            self.assertEqual(json.loads(modejeu.fichier_reglages().read_text(encoding="utf-8")),
                             {"ollama": True, "profil": False})
            self.assertEqual(modejeu.reglages(), {**TOUT, "profil": False})

    def test_regler_cle_inconnue(self):
        with self.assertRaises(ValueError):
            modejeu.regler("turbo", True)
        self.assertFalse(modejeu.fichier_reglages().exists())

    def test_reglages_jamais_dans_les_echantillons(self):
        echantillon = Path(__file__).resolve().parent / "echantillons" / "modejeu.json"
        with configuration(""):
            modejeu.regler("taches", False)
        self.assertFalse(echantillon.exists())

    def test_valeurs_non_booleennes_ignorees(self):
        err = io.StringIO()
        with configuration('[modejeu]\nprofil = "non"\nollama = false\nturbo = true\n'), \
                contextlib.redirect_stderr(err):
            self.assertEqual(config.modejeu(), {**TOUT, "ollama": False})
        self.assertIn("modejeu.profil", err.getvalue())
        self.assertIn("modejeu.turbo", err.getvalue())
        # réglages de la fenêtre : clés inconnues ou valeurs non booléennes ignorées
        modejeu.fichier_reglages().write_text('{"actif": "oui", "turbo": true, "taches": false}', encoding="utf-8")
        self.assertEqual(modejeu.reglages(), {**TOUT, "taches": False})
        modejeu.fichier_reglages().write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(modejeu.reglages(), TOUT)

    def test_exemple_documente_modejeu(self):
        exemple = Path(__file__).resolve().parent.parent / "config.exemple.toml"
        texte = exemple.read_text(encoding="utf-8")
        self.assertIn("\n# [modejeu]\n", texte)
        for cle in modejeu.CLES:
            self.assertIn(f"\n# {cle} = true\n", texte)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(config.modejeu(exemple), TOUT)
        self.assertEqual(err.getvalue(), "")


class Pause(Base):
    def test_taches_en_pause(self):
        cas = [(TOUT, JEU, JEU), ({**TOUT, "taches": False}, JEU, None), ({**TOUT, "actif": False}, JEU, None),
               (TOUT, None, None)]
        for reglages, jeu, attendu in cas:
            with self.subTest(reglages=reglages, jeu=jeu):
                self.assertEqual(modejeu.taches_en_pause(jeu=lambda: jeu, reglages=lambda: reglages), attendu)


class Partie(Base):
    def test_etat_ecrit_avant_toute_action(self):
        vus = []
        self.run.au_stop.append(lambda: vus.append(("stop", self.lire()["partie"]["avant"])))
        self.systeme.temoin = lambda nom: vus.append((nom, (self.lire()["partie"] or {}).get("avant")))
        self.mode(ouvrir=faux_ouvrir("modele:7b")).tour()
        avant = {"ollama": True, "modeles": ["modele:7b"]}
        self.assertEqual(vus, [("stop", avant), ("inhiber_notifications", avant), ("tenir_profil", avant)])

    def test_partie_complete(self):
        bureau = FauxBureau(self.systeme)
        mode = self.mode(bureau)
        mode.tour()
        partie = self.lire()["partie"]
        self.assertEqual((partie["jeu"], partie["debut"], partie["boot_id"], partie["reglages"]),
                         (JEU, HEURE, BOOT, TOUT))
        self.assertEqual(partie["avant"], {"ollama": True, "modeles": []})
        self.assertIsNone(partie["avertissement"])
        self.assertEqual(partie["actions"], {
            "ollama": action("fait", "Ollama arrêté, mémoire vidéo rendue."),
            "ne_pas_deranger": action("fait", "Ne pas déranger activé."),
            "profil": action("fait", "Profil « performance » tenu pendant la partie."),
            "taches": action("fait", "Relevés de Health Hub en pause pendant la partie.")})
        self.assertEqual(bureau.appels, [("inhiber_notifications", RAISON), ("tenir_profil", "performance", RAISON)])
        self.assertEqual((len(self.systeme.notifications), len(self.systeme.profils)), (1, 1))
        self.assertEqual(self.publications, [1])            # P6 : une fois, à la fin du début de partie
        self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        self.assertSystemeVide()
        self.assertEqual(bureau.appels[-1], ("fermer",))   # P1 : toujours fermé à la fin
        donnees = self.lire()
        self.assertIsNone(donnees["partie"])
        derniere = donnees["derniere"]
        self.assertEqual((derniere["jeu"], derniere["debut"], derniere["fin"], derniere["fin_par"]),
                         (JEU, HEURE, HEURE, "fin"))
        self.assertEqual(derniere["actions"], partie["actions"])
        self.assertEqual(derniere["retour"], {
            "profil": action("fait", "Profil d'avant rétabli."),
            "ne_pas_deranger": action("fait", "Ne pas déranger levé."),
            "ollama": action("fait", "Ollama relancé.")})
        self.assertEqual(self.publications, [1, 1])         # P6 : une fois à la fin de la partie

    def test_fin_apres_deux_absences(self):
        mode = self.mode()
        mode.tour()
        self.jeu = None
        mode.tour()
        self.assertIsNotNone(self.lire()["partie"])
        self.jeu = JEU                                      # le lanceur relance le jeu : le compte repart de zéro
        mode.tour()
        self.jeu = None
        mode.tour()
        self.assertIsNotNone(self.lire()["partie"])
        self.assertEqual(self.run.ordres(), ["stop"])
        mode.tour()
        self.assertIsNone(self.lire()["partie"])
        self.assertEqual(self.run.ordres(), ["stop", "start"])

    def test_rien_sans_jeu_ni_mode_jeu_coupe(self):
        bureau = FauxBureau(self.systeme)
        self.jeu = None
        self.mode(bureau).tour()
        self.jeu = JEU
        self.mode(bureau, reglages=lambda: {**TOUT, "actif": False}).tour()
        self.assertEqual((self.run.appels, bureau.appels, self.publications), ([], [], []))
        self.assertIsNone(self.lire()["partie"])

    def test_detection_en_erreur_compte_comme_absence(self):
        """W7 : une détection qui lève à chaque tour ne fige jamais le bureau : fin après ABSENCES_FIN tours."""
        mode = self.mode()
        mode.tour()

        def casse():
            raise UnicodeDecodeError("utf-8", b"\xc3", 0, 1, "invalid continuation byte")
        mode.jeu = casse
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mode.tour()
            self.assertIsNotNone(self.lire()["partie"])
            mode.tour()
            self.assertIsNone(self.lire()["partie"])
            mode.tour()                                      # sans partie : rien ne lève, rien ne commence
        self.assertIsNone(self.lire()["partie"])
        self.assertSystemeVide()
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        self.assertEqual(err.getvalue().count("détection du jeu en erreur"), 1)

    def test_avertissements_ecrits_une_seule_fois(self):
        """W8-m7 : la boucle relit les réglages toutes les 5 s ; chaque message distinct n'est écrit qu'une fois."""
        self.jeu = None
        for texte, message in (('[modejeu]\nprofil = "non"\n', "modejeu.profil"), ("[modejeu\n", "illisible")):
            with self.subTest(message=message), configuration(texte):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    mode = self.mode()
                    for _ in range(3):
                        mode.tour()
                self.assertEqual(err.getvalue().count(message), 1, err.getvalue())

    def test_message_reecrit_apres_disparition(self):
        """W10 : un message disparu (la cause est réglée) est oublié ; s'il revient, il est réécrit une fois."""
        mode = self.mode()
        self.jeu = None
        reponses = iter([OSError("proc illisible"), OSError("proc illisible"), None, OSError("proc illisible")])

        def jeu():
            reponse = next(reponses)
            if reponse is not None:
                raise reponse
        mode.jeu = jeu
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(4):
                mode.tour()
        self.assertEqual(err.getvalue().count("proc illisible"), 2)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with configuration('[modejeu]\nprofil = "non"\n'):
                modejeu.reglages()
                modejeu.reglages()
            modejeu.reglages()                               # configuration corrigée
            with configuration('[modejeu]\nprofil = "non"\n'):
                modejeu.reglages()
        self.assertEqual(err.getvalue().count("modejeu.profil"), 2)

    def test_publier_en_echec_ne_coupe_rien(self):
        def publier():
            raise RuntimeError("etat.json illisible")
        mode = self.mode(publier=publier)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mode.tour()
            self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        self.assertSystemeVide()
        self.assertIsNone(self.lire()["partie"])
        self.assertIn("etat.json illisible", err.getvalue())


class Restauration(Base):
    def plantage_en_pleine_partie(self):
        """A démarre, une partie commence, puis A meurt sans rien finir : le bus lève ses maintiens."""
        bureau = FauxBureau(self.systeme)
        a = self.mode(bureau)
        a.demarrer()
        a.tour()
        self.assertEqual((len(self.systeme.notifications), len(self.systeme.profils)), (1, 1))
        self.systeme.perdre(bureau)
        return a

    def test_faux_plantage_puis_reprise_relance_ollama(self):
        self.plantage_en_pleine_partie()
        self.assertSystemeVide()                             # le profil n'est plus tenu
        self.assertIsNotNone(self.lire()["partie"])
        self.jeu = None
        b = self.mode()
        self.assertEqual(b.demarrer(), "continue")           # W8-m3, W10 : partie adoptée, aucune absence comptée
        self.assertEqual(self.run.ordres(), ["stop"])
        self.assertSystemeVide()                             # aucun maintien repris sans jeu
        b.tour()
        self.assertEqual(self.run.ordres(), ["stop"])
        b.tour()                                             # deuxième absence : fin de partie
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        donnees = self.lire()
        self.assertIsNone(donnees["partie"])
        self.assertEqual(donnees["derniere"]["fin_par"], "reprise")
        self.assertEqual(donnees["derniere"]["retour"]["ollama"], action("fait", "Ollama relancé."))
        self.assertEqual(donnees["service"], {"pid": os.getpid(), "boot_id": BOOT, "depuis": HEURE})

    def test_redemarrage_du_pc_ne_relance_pas_ollama(self):
        self.plantage_en_pleine_partie()
        self.boot = "boot-2"
        self.jeu = None
        self.assertEqual(self.mode().demarrer(), "redemarrage")
        self.assertEqual(self.run.ordres(), ["stop"])
        derniere = self.lire()["derniere"]
        self.assertEqual(derniere["fin_par"], "redemarrage")
        self.assertEqual(derniere["retour"]["ollama"], action("rien", "Le PC a redémarré : Ollama n'est pas relancé."))

    def test_demarrage_illisible_compte_comme_un_autre(self):
        """P4 : boot() à None (démarrage illisible) n'est jamais « le même démarrage »."""
        self.plantage_en_pleine_partie()
        self.boot = None
        self.jeu = None
        self.assertEqual(self.mode().demarrer(), "redemarrage")
        self.assertEqual(self.run.ordres(), ["stop"])

    def test_reprise_en_pleine_partie_reprend_les_maintiens(self):
        self.plantage_en_pleine_partie()
        bureau_b = FauxBureau(self.systeme)
        b = self.mode(bureau_b)
        self.assertEqual(b.demarrer(), "continue")
        self.assertEqual(bureau_b.appels, [("inhiber_notifications", RAISON), ("tenir_profil", "performance", RAISON)])
        self.assertEqual(set(self.systeme.notifications.values()) | set(self.systeme.profils.values()), {bureau_b})
        self.assertEqual(self.run.ordres(), ["stop"])          # Ollama n'est pas touché à la reprise
        self.assertEqual(self.lire()["partie"]["avant"]["ollama"], True)
        self.finir_par_absences(b)
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        self.assertSystemeVide()
        self.assertEqual(self.lire()["derniere"]["fin_par"], "fin")

    def test_reprise_pendant_un_trou_du_lanceur_ne_relance_pas_ollama(self):
        """W8-m3 : le service redémarre pendant la seconde où le lanceur relance le jeu."""
        self.plantage_en_pleine_partie()
        self.jeu = None
        bureau_b = FauxBureau(self.systeme)
        b = self.mode(bureau_b)
        self.assertEqual(b.demarrer(), "continue")
        self.assertEqual(bureau_b.appels, [])
        self.jeu = JEU
        b.tour()                                             # le jeu est revenu : maintiens repris
        self.assertEqual(bureau_b.maintiens(), ["inhiber_notifications", "tenir_profil"])
        self.assertEqual(self.run.ordres(), ["stop"])        # Ollama jamais relancé pendant la partie
        self.finir_par_absences(b)
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        self.assertSystemeVide()
        self.assertEqual(self.lire()["derniere"]["fin_par"], "fin")

    def test_reprise_par_servir_pendant_un_trou_du_lanceur(self):
        """W10 : le service redémarre pendant que le lanceur relance le jeu (trou de 0,5 à 4 s) ; la vraie boucle,
        une horloge factice avancée par `attendre` : Ollama n'est jamais relancé. L'attente avant le premier tour laisse
        même 7 s au lanceur (tours à 5 et 10 s). Sans retour du jeu : fin au tour de 10 s."""
        racine = self.dossier
        for trou, ordres in ((0.5, ["stop"]), (1, ["stop"]), (4, ["stop"]), (7, ["stop"]), (None, ["stop", "start"])):
            with self.subTest(trou=trou):
                self.dossier, self.systeme, self.run = racine / f"trou-{trou}", FauxSysteme(), FauxRun()
                self.plantage_en_pleine_partie()
                horloge = [0.0]

                def attendre(secondes):
                    horloge[0] += secondes

                def jeu_b(trou=trou):
                    return JEU if trou is not None and horloge[0] >= trou else None
                bureau_b = FauxBureau(self.systeme)
                b = self.mode(bureau_b, jeu=jeu_b, attendre=attendre)
                reste = iter([True] * 3 + [False])
                modejeu.servir(b, attendre=attendre, continuer=lambda: next(reste))
                self.assertEqual(self.run.ordres(), ordres)
                if trou is None:
                    self.assertEqual(self.lire()["derniere"]["fin_par"], "reprise")
                    self.assertSystemeVide()
                else:
                    self.assertIsNotNone(self.lire()["partie"])
                    self.assertEqual(set(self.systeme.notifications.values()) | set(self.systeme.profils.values()),
                                     {bureau_b})

    def test_raison_sans_nom_de_jeu(self):
        """W10 : une partie dont le nom est illisible ne donne jamais « (None) » dans la raison D-Bus."""
        commun.ecrire_json(modejeu.fichier(self.dossier), {"partie": {
            "jeu": 3, "debut": HEURE, "boot_id": BOOT, "reglages": TOUT, "avant": {"ollama": False, "modeles": []},
            "actions": {}, "avertissement": None}})
        bureau = FauxBureau(self.systeme)
        self.assertEqual(self.mode(bureau).demarrer(), "continue")
        self.assertEqual(bureau.appels, [("inhiber_notifications", "Health Hub : mode jeu"),
                                         ("tenir_profil", "performance", "Health Hub : mode jeu")])

    def test_reprise_mode_jeu_coupe_finit_aussitot(self):
        """W8-m5 : mode jeu coupé pendant que le service était mort, jeu toujours lancé : aucun maintien repris."""
        self.plantage_en_pleine_partie()
        modejeu.regler("actif", False)
        bureau_b = FauxBureau(self.systeme)
        self.assertEqual(self.mode(bureau_b).demarrer(), "restaure")
        self.assertEqual(bureau_b.maintiens(), [])
        self.assertEqual(self.lire()["derniere"]["fin_par"], "desactive")
        self.assertEqual(self.run.ordres(), ["stop", "start"])  # P3

    def test_restaurer_mode_jeu_coupe_finit_aussitot(self):
        self.plantage_en_pleine_partie()
        modejeu.regler("actif", False)
        self.assertEqual(self.restaurer(), "restaure")
        self.assertEqual(self.lire()["derniere"]["fin_par"], "desactive")
        self.assertEqual(self.run.ordres(), ["stop", "start"])

    def test_reprise_ne_reprend_que_les_maintiens_coches(self):
        bureau_a = FauxBureau(self.systeme)
        a = self.mode(bureau_a, reglages=lambda: {**TOUT, "profil": False})
        a.tour()
        self.systeme.perdre(bureau_a)
        bureau_b = FauxBureau(self.systeme)
        self.assertEqual(self.mode(bureau_b).demarrer(), "continue")      # la partie garde ses propres réglages
        self.assertEqual(bureau_b.appels, [("inhiber_notifications", RAISON)])

    def test_suspendre_lache_les_maintiens_et_garde_la_partie(self):
        a = self.mode()
        a.demarrer()
        a.tour()
        a.suspendre()
        self.assertSystemeVide()
        donnees = self.lire()
        self.assertIsNotNone(donnees["partie"])
        self.assertIsNone(donnees["service"])
        self.assertEqual(self.run.ordres(), ["stop"])

    def test_suspendre_republie_l_etat_interrompu(self):
        """RF-m1 : les maintiens tombent avec le service ; etat.json le dit tout de suite (« interrompu »), sans
        attendre le relevé suivant."""
        a = self.mode()
        a.demarrer()
        a.tour()
        self.publications.clear()
        a.suspendre()
        self.assertEqual(self.publications, [1])
        resume = modejeu.resume(self.dossier, vivant=lambda pid: True, boot=lambda: BOOT, reglages=lambda: dict(TOUT))
        self.assertEqual(resume["etat"], "interrompu")

    def test_demarrer_sans_partie_publie_l_etat_pret(self):
        """Essai réel (T10) : après une remise faite service arrêté, etat.json disait « Le service du mode jeu ne tourne
        pas » ; le service relancé sans partie doit le republier aussitôt (« pret »)."""
        self.jeu = None
        a = self.mode()
        a.demarrer()
        self.assertEqual(self.publications, [1])
        resume = modejeu.resume(self.dossier, vivant=lambda pid: True, boot=lambda: BOOT, reglages=lambda: dict(TOUT))
        self.assertEqual(resume["etat"], "pret")

    def test_suspendre_sans_partie_publie_l_etat_arrete_et_publication_en_echec_sans_effet(self):
        self.jeu = None
        a = self.mode()
        a.demarrer()
        self.publications.clear()
        a.suspendre()
        self.assertEqual(self.publications, [1])
        resume = modejeu.resume(self.dossier, vivant=lambda pid: True, boot=lambda: BOOT, reglages=lambda: dict(TOUT))
        self.assertEqual(resume["etat"], "arrete")
        self.jeu = JEU

        def en_panne():
            raise OSError("disque plein")
        b = self.mode(publier=en_panne)
        with mock.patch("sys.stderr"):
            b.demarrer()
            b.tour()
            b.suspendre()                                    # P6 : une publication en échec ne lève jamais
        self.assertIsNone(self.lire()["service"])
        self.assertIsNotNone(self.lire()["partie"])

    def test_desactiver_pendant_une_partie_restaure_aussitot(self):
        reglages = dict(TOUT)
        mode = self.mode(reglages=lambda: reglages)
        mode.tour()
        reglages["actif"] = False
        mode.tour()                                          # le jeu tourne toujours
        self.assertSystemeVide()
        self.assertIsNone(self.lire()["partie"])
        self.assertEqual(self.lire()["derniere"]["fin_par"], "desactive")
        self.assertEqual(self.run.ordres(), ["stop", "start"])   # P3 : Ollama relancé aussi

    def test_restaurer_si_orphelin_service_actif(self):
        self.plantage_en_pleine_partie()
        self.jeu = None
        self.run.actifs[SERVICE] = True
        avant = self.lire()
        self.assertEqual(self.restaurer(si_orphelin=True), "service_actif")
        self.assertEqual(self.restaurer(), "service_actif")       # P5 : vérifié même sans l'option
        self.assertEqual(self.lire(), avant)
        self.assertEqual(self.run.ordres(), ["stop"])
        self.assertIn(["systemctl", "--user", "is-active", SERVICE], self.run.appels)

    def test_restaurer_sans_jeu_relance_ollama(self):
        self.plantage_en_pleine_partie()
        service = self.lire()["service"]
        self.jeu = None
        self.assertEqual(self.restaurer(si_orphelin=True), "restaure")
        self.assertEqual(self.attentes, [modejeu.INTERVALLE_S] * (modejeu.ABSENCES_FIN - 1))     # W8-m3
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        donnees = self.lire()
        self.assertIsNone(donnees["partie"])
        self.assertEqual(donnees["derniere"]["fin_par"], "reprise")
        self.assertEqual(donnees["service"], service)          # restaurer n'écrit pas `service`
        self.assertEqual(self.restaurer(), "rien")

    def test_restaurer_apres_redemarrage(self):
        self.plantage_en_pleine_partie()
        self.boot = "boot-2"
        self.assertEqual(self.restaurer(), "redemarrage")
        self.assertEqual(self.run.ordres(), ["stop"])
        self.assertIsNone(self.lire()["partie"])

    def test_restaurer_pendant_un_trou_du_lanceur_attend(self):
        """W8-m3 : un seul passage sans jeu ne suffit pas, comme pour le service."""
        self.plantage_en_pleine_partie()
        avant = self.lire()
        vus = iter([None, JEU])
        self.assertEqual(self.restaurer(jeu=lambda: next(vus)), "jeu_en_cours")
        self.assertEqual(self.lire(), avant)
        self.assertEqual(self.run.ordres(), ["stop"])

    def test_restaurer_etat_du_service_inconnu(self):
        """W8-m6 : is-active en échec (délai, exception, gestionnaire injoignable) : le service vit peut-être."""
        self.plantage_en_pleine_partie()
        self.jeu = None
        avant = self.lire()
        for code in (-1, 1):
            def run(cmd, timeout=120, entree=None, code=code):
                if cmd[2:] == ["is-active", SERVICE]:
                    return code, "délai dépassé"
                return self.run(cmd, timeout, entree)
            with self.subTest(code=code):
                self.assertEqual(self.restaurer(run=run), "inconnu")
        self.assertEqual(self.lire(), avant)
        self.assertEqual(self.run.ordres(), ["stop"])

    def test_restaurer_reverifie_le_service_apres_l_attente(self):
        """W10 : le service redémarre pendant les 5 s d'attente de restaurer : il s'en occupe, rien n'est touché."""
        self.plantage_en_pleine_partie()
        self.jeu = None
        avant = self.lire()

        def attendre(secondes):
            self.attentes.append(secondes)
            self.run.actifs[SERVICE] = True
        self.assertEqual(self.restaurer(attendre=attendre), "service_actif")
        self.assertEqual(self.attentes, [modejeu.INTERVALLE_S])
        self.assertEqual(self.lire(), avant)
        self.assertEqual(self.run.ordres(), ["stop"])

    def test_restaurer_pendant_un_jeu_attend(self):
        self.plantage_en_pleine_partie()
        avant = self.lire()
        self.assertEqual(self.restaurer(si_orphelin=True), "jeu_en_cours")
        self.assertEqual(self.lire(), avant)
        self.assertEqual(self.run.ordres(), ["stop"])


class Ollama(Base):
    def test_ollama_jamais_relance_s_il_etait_arrete(self):
        self.run.actifs[OLLAMA] = False
        ouvrir = faux_ouvrir()
        mode = self.mode(ouvrir=ouvrir)
        mode.tour()
        self.assertEqual(self.lire()["partie"]["actions"]["ollama"], action("rien", "Ollama était déjà arrêté."))
        self.assertEqual(ouvrir.urls, [])                    # rien à demander à un Ollama arrêté
        self.finir_par_absences(mode)
        self.assertEqual(self.lire()["derniere"]["retour"]["ollama"],
                         action("rien", "Ollama n'est pas relancé : il était arrêté avant la partie."))
        # ni à la reprise après un plantage
        self.jeu = JEU
        bureau = FauxBureau(self.systeme)
        self.mode(bureau).tour()
        self.systeme.perdre(bureau)
        self.jeu = None
        b = self.mode()
        self.assertEqual(b.demarrer(), "continue")
        b.tour()
        b.tour()
        self.assertEqual(self.lire()["derniere"]["fin_par"], "reprise")
        self.assertEqual(self.run.ordres(), [])

    def test_ollama_relance_par_toi_pendant_la_partie_pas_touche(self):
        mode = self.mode()
        mode.tour()
        self.run.actifs[OLLAMA] = True                       # ia-on pendant la partie
        self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), ["stop"])
        self.assertEqual(self.lire()["derniere"]["retour"]["ollama"], action("rien", "Ollama tourne déjà."))

    def test_modele_charge_arrete_quand_meme_et_avertit(self):
        ouvrir = faux_ouvrir("modele:7b")
        mode = self.mode(ouvrir=ouvrir)
        mode.tour()
        self.assertEqual(self.run.ordres(), ["stop"])
        partie = self.lire()["partie"]
        self.assertEqual(ouvrir.urls, [(sante.OLLAMA_PS, 3)])
        self.assertEqual(partie["avant"]["modeles"], ["modele:7b"])
        self.assertEqual(partie["actions"]["ollama"]["statut"], "fait")
        self.assertEqual(partie["avertissement"], modejeu.AVERTISSEMENT_MODELE.format(modeles="modele:7b"))
        self.assertEqual(partie["avertissement"],
                         "Ollama répondait avec modele:7b : arrêté quand même, le jeu passe d'abord.")
        self.finir_par_absences(mode)
        self.assertEqual(self.lire()["derniere"]["avertissement"], partie["avertissement"])

    def test_ollama_refuse_de_s_arreter(self):
        self.run.refuse_stop = True
        mode = self.mode()
        mode.tour()
        actions = self.lire()["partie"]["actions"]
        self.assertEqual(actions["ollama"], action("echec", "Ollama refuse de s'arrêter."))
        self.assertEqual(self.attentes, [1] * modejeu.ATTENTE_OLLAMA_S)
        self.assertEqual((actions["ne_pas_deranger"]["statut"], actions["profil"]["statut"]), ("fait", "fait"))
        self.assertIsNone(self.lire()["partie"]["avertissement"])
        self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), ["stop"])
        self.assertEqual(self.lire()["derniere"]["retour"]["ollama"], action("rien", "Ollama tourne déjà."))

    def test_demarrage_illisible_ollama_pas_touche(self):
        """RF-m7 : sans boot_id, Ollama ne pourrait jamais être relancé (P4) : il n'est pas arrêté ; le reste du mode
        jeu agit, et la fin ne prétend pas que le PC a redémarré."""
        self.boot = None
        mode = self.mode()
        mode.tour()
        partie = self.lire()["partie"]
        self.assertEqual(self.run.ordres(), [])
        self.assertEqual(partie["actions"]["ollama"], action("rien", "Démarrage illisible : Ollama n'est pas touché."))
        self.assertEqual((partie["actions"]["ne_pas_deranger"]["statut"], partie["actions"]["profil"]["statut"]),
                         ("fait", "fait"))
        self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), [])
        self.assertEqual(self.lire()["derniere"]["retour"]["ollama"],
                         action("rien", "Démarrage illisible : Ollama n'est pas relancé."))

    def test_ollama_decoche_jamais_relance(self):
        """P4 : réglage décoché, Ollama laissé tel quel ; tu l'arrêtes pendant la partie : la fin ne le relance pas."""
        mode = self.mode(reglages=lambda: {**TOUT, "ollama": False})
        mode.tour()
        self.assertEqual(self.lire()["partie"]["avant"]["ollama"], True)
        self.run.actifs[OLLAMA] = False                      # ia-off pendant la partie
        self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), [])
        self.assertEqual(self.lire()["derniere"]["retour"]["ollama"],
                         action("desactive", "Désactivé dans les réglages."))


class Normalisation(Base):
    PARTIE = {"jeu": JEU, "debut": HEURE, "boot_id": BOOT, "reglages": TOUT,
              "avant": {"ollama": True, "modeles": []}, "actions": {}, "avertissement": None}

    def test_partie_mal_formee_jamais_de_plantage(self):
        """W8-m4 : une partie abîmée dans modejeu.json est close sans plantage ; dans le doute, Ollama n'est pas
        relancé (réglages ou état d'avant illisibles, démarrage illisible)."""
        self.jeu = None
        cas = (({"reglages": "tout"}, False), ({"reglages": {"ollama": "oui"}}, False), ({"avant": ["ollama"]}, False),
               ({"actions": ["fait"]}, True), ({"boot_id": 7}, False), ({"jeu": 3, "avertissement": 5}, True),
               ({"avant": {"ollama": True, "modeles": "modele:7b"}}, True))
        for champs, relance in cas:
            for chemin in ("restaurer", "service"):
                with self.subTest(champs=champs, chemin=chemin):
                    self.run = FauxRun(ollama=False)
                    commun.ecrire_json(modejeu.fichier(self.dossier),
                                       {"service": None, "partie": {**self.PARTIE, **champs}, "derniere": None})
                    if chemin == "restaurer":
                        self.assertIn(self.restaurer(), ("restaure", "redemarrage"))
                    else:
                        mode = self.mode()
                        mode.demarrer()
                        mode.tour()
                        mode.tour()
                    self.assertIsNone(self.lire()["partie"])
                    self.assertEqual(self.run.ordres(), ["start"] if relance else [])

    def test_lire_normalise_la_partie(self):
        commun.ecrire_json(modejeu.fichier(self.dossier), {"partie": {
            "jeu": 3, "reglages": {"ollama": "oui", "profil": True}, "avant": {"ollama": 1, "modeles": [1, "m"]},
            "actions": {"ollama": {"statut": "fait", "detail": "x"}, "turbo": {}, "profil": "fait"}}, "service": []})
        donnees = self.lire()
        self.assertIsNone(donnees["service"])
        self.assertEqual(donnees["partie"], {
            "jeu": None, "debut": None, "boot_id": None, "avertissement": None,
            "reglages": {**dict.fromkeys(modejeu.CLES, False), "profil": True},
            "avant": {"ollama": False, "modeles": ["m"]},
            "actions": {"ollama": {"statut": "fait", "detail": "x"}}})


class Echecs(Base):
    def test_jamais_en_profil_performance_apres_la_partie(self):
        bureau = FauxBureau(self.systeme, echecs={"relacher_profil"})
        mode = self.mode(bureau)
        mode.tour()
        self.finir_par_absences(mode)
        self.assertIn(("fermer",), bureau.appels)
        self.assertEqual(self.systeme.profils, {})
        self.assertEqual(self.run.ordres(), ["stop", "start"])
        retour = self.lire()["derniere"]["retour"]
        self.assertEqual(retour["profil"], action("echec", "Impossible : indisponible"))
        self.assertEqual(retour["ollama"], action("fait", "Ollama relancé."))

    def test_maintien_obtenu_sans_reponse_leve_a_la_fin(self):
        """P1 : la réponse de HoldProfile s'est perdue, mais le démon tient le profil ; fermer la connexion le lève."""
        bureau = FauxBureau(self.systeme, sans_reponse={"tenir_profil"})
        mode = self.mode(bureau)
        mode.tour()
        self.assertEqual(self.lire()["partie"]["actions"]["profil"], action("echec", "Impossible : indisponible"))
        self.assertEqual(len(self.systeme.profils), 1)
        self.finir_par_absences(mode)
        self.assertSystemeVide()

    def test_echec_d_une_action_n_empeche_pas_les_autres(self):
        mode = self.mode(FauxBureau(self.systeme, echecs={"inhiber_notifications"}))
        mode.tour()
        actions = self.lire()["partie"]["actions"]
        self.assertEqual(actions["ne_pas_deranger"], action("echec", "Impossible : indisponible"))
        self.assertEqual((actions["profil"]["statut"], actions["ollama"]["statut"], actions["taches"]["statut"]),
                         ("fait", "fait", "fait"))

    def test_reglages_decoches_ne_touchent_a_rien(self):
        bureau = FauxBureau(self.systeme)
        mode = self.mode(bureau, reglages=lambda: {**TOUT, "ollama": False, "ne_pas_deranger": False,
                                                   "profil": False, "taches": False})
        mode.tour()
        desactive = action("desactive", "Désactivé dans les réglages.")
        self.assertEqual(self.lire()["partie"]["actions"], dict.fromkeys(modejeu.ACTIONS, desactive))
        self.finir_par_absences(mode)
        self.assertEqual(self.run.ordres(), [])
        self.assertEqual(bureau.maintiens(), [])             # aucun maintien pris ni levé (fermer seul, P1)
        self.assertEqual(self.lire()["derniere"]["retour"], {"ollama": desactive})



# --- Task 5 : boucle du service, CLI, report des relevés, unités ---

ICI = Path(__file__).resolve().parent
SYSTEMD = ICI.parent / "systemd"
INSTALL = ICI.parent / "install.sh"
UNITE_MODEJEU = """[Unit]
Description=Health Hub : mode jeu automatique
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=exec
ExecStart=%h/.local/bin/centre-bazzite modejeu service
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=graphical-session.target
"""
RELEVE = {"HEALTH_HUB_RELEVE": "1"}


class Boucle(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(modejeu, "_DEJA_ECRIT", {}))

    def servir(self, mode, tours):
        attentes = []
        reste = iter([True] * tours + [False])
        modejeu.servir(mode, attendre=attentes.append, continuer=lambda: next(reste))
        return attentes

    def test_servir_reprend_puis_tourne(self):
        mode = mock.Mock()
        self.assertEqual(self.servir(mode, 3), [5, 5, 5])
        self.assertEqual(mode.method_calls, [mock.call.demarrer(), mock.call.tour(), mock.call.tour(), mock.call.tour()])

    def test_servir_survit_a_un_tour_en_erreur(self):
        mode = mock.Mock()
        mode.tour.side_effect = [RuntimeError("boum"), RuntimeError("boum"), None, RuntimeError("boum")]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.servir(mode, 4), [5, 5, 5, 5])
        self.assertEqual(mode.tour.call_count, 4)
        self.assertEqual(err.getvalue().count("boum"), 2)   # W8-m7 : une fois de suite ; W10 : réécrit s'il revient

    def test_servir_attend_avant_le_premier_tour_d_une_reprise(self):
        """W10 : après une reprise (« continue »), le premier tour attend INTERVALLE_S, comme les suivants."""
        mode = mock.Mock()
        mode.demarrer.return_value = "continue"
        self.assertEqual(self.servir(mode, 2), [5, 5, 5])
        self.assertEqual(mode.tour.call_count, 2)

    def test_servir_laisse_passer_systemexit(self):
        """P11 : le SIGTERM devient un SystemExit qui doit atteindre le `finally` de la CLI (suspendre)."""
        mode = mock.Mock()
        mode.tour.side_effect = SystemExit(0)
        with self.assertRaises(SystemExit):
            self.servir(mode, 3)
        self.assertEqual(mode.tour.call_count, 1)


class BaseCli(Base):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(commun, "ETAT", self.dossier))
        self.legers = []

    def cli(self, *argv, **kw):
        kw.setdefault("ecrire_leger", lambda: self.legers.append(1))
        kw.setdefault("run", self.run)
        kw.setdefault("jeu", lambda: self.jeu)
        kw.setdefault("environ", {})
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = cli.main(list(argv), **kw)
        return code, sortie.getvalue(), erreur.getvalue()

    def plantage_en_pleine_partie(self):
        bureau = FauxBureau(self.systeme)
        self.mode(bureau).tour()
        self.systeme.perdre(bureau)


class Cli(BaseCli):
    def test_cli_service_sigterm_suspend(self):
        ancien = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, ancien)
        self.run.actifs[OLLAMA] = False          # la CLI n'injecte pas `ouvrir` : aucun /api/ps à demander
        bureaux = []

        def fabrique():
            bureaux.append(FauxBureau(self.systeme))
            return bureaux[-1]

        def faux_servir(mode):
            mode.demarrer()
            mode.tour()                          # une partie commence…
            self.assertEqual((len(self.systeme.notifications), len(self.systeme.profils)), (1, 1))
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)      # …puis la session se ferme
        with mock.patch.object(modejeu, "servir", faux_servir), self.assertRaises(SystemExit) as fin:
            self.cli("modejeu", "service", bureau=fabrique)
        self.assertEqual(fin.exception.code, 0)
        self.assertEqual(len(bureaux), 1)
        self.assertSystemeVide()
        donnees = modejeu.lire()
        self.assertEqual(donnees["partie"]["jeu"], JEU)          # D7 : la partie reste notée
        self.assertIsNone(donnees["service"])
        self.assertEqual(self.run.ordres(), [])
        # publié par `ecrire_leger` au lancement du service (« pret »), au début de la partie, puis à la suspension
        # (RF-m1 : le mode jeu devient « interrompu » tout de suite)
        self.assertEqual(self.legers, [1, 1, 1])

    def test_cli_regler(self):
        with configuration("") as chemin:
            self.assertEqual(self.cli("modejeu", "regler", "ollama", "non")[0], 0)
            self.assertFalse(modejeu.reglages()["ollama"])
            self.assertTrue(chemin.with_name("modejeu.json").exists())
            self.assertEqual(self.cli("modejeu", "regler", "ollama", "oui")[0], 0)
            self.assertTrue(modejeu.reglages()["ollama"])
        self.assertEqual(self.legers, [1, 1])

    def test_cli_regler_inconnu(self):
        code, _, erreur = self.cli("modejeu", "regler", "turbo", "oui")
        self.assertEqual(code, 2)
        self.assertEqual(erreur.strip(), "Réglage inconnu : turbo (actif, ollama, ne_pas_deranger, profil, taches).")
        for argv in (("regler", "ollama", "peut-être"), ("regler", "ollama"), ("regler",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli("modejeu", *argv)[0], 2)
        self.assertFalse(modejeu.fichier_reglages().exists())
        self.assertEqual(self.legers, [])

    def test_cli_restaurer_si_orphelin_service_actif(self):
        self.plantage_en_pleine_partie()
        self.jeu = None
        self.run.actifs[SERVICE] = True
        code, sortie, _ = self.cli("modejeu", "restaurer", "--si-orphelin")
        self.assertEqual((code, sortie), (0, "Le service du mode jeu s'en occupe.\n"))
        self.assertEqual(self.run.ordres(), ["stop"])
        self.assertIsNotNone(modejeu.lire()["partie"])
        self.assertEqual(self.legers, [])                    # W8-m8 : rien de changé, rien à republier

    def test_cli_restaurer_phrases(self):
        phrases = {"rien": "Aucune partie à restaurer.",
                   "service_actif": "Le service du mode jeu s'en occupe.",
                   "jeu_en_cours": "Un jeu tourne encore : restauration à la fin de la partie.",
                   "restaure": "Mode jeu : bureau remis comme avant.",
                   "redemarrage": "Le PC a redémarré depuis : rien à remettre.",
                   "inconnu": "État du service du mode jeu inconnu : rien n'est touché."}
        for resultat, phrase in phrases.items():
            with self.subTest(resultat=resultat), \
                    mock.patch.object(modejeu, "restaurer", return_value=resultat) as restaurer:
                self.legers.clear()
                self.assertEqual(self.cli("modejeu", "restaurer")[:2], (0, phrase + "\n"))
                restaurer.assert_called_once_with(si_orphelin=False, run=self.run, jeu=mock.ANY)
                self.assertEqual(self.legers, [1] if resultat in ("restaure", "redemarrage") else [])

    def test_cli_restaurer_tache_pour_la_fenetre(self):
        """UI-m2 : lancée par la fenêtre (sans --si-orphelin), la remise du bureau est une tâche du panneau Activité qui
        porte la phrase de la fin (la fenêtre y lit la fin et la phrase) ; le relevé horaire (--si-orphelin) n'en crée
        pas."""
        for resultat, statut in (("restaure", "fini"), ("redemarrage", "fini"), ("rien", "fini"),
                                 ("jeu_en_cours", "interrompu"), ("service_actif", "interrompu"),
                                 ("inconnu", "echec")):
            with self.subTest(resultat=resultat), mock.patch.object(modejeu, "restaurer", return_value=resultat):
                self.cli("modejeu", "restaurer")
                faites = [x for x in taches.lister() if x["id"] == "modejeu:restaurer"]
                self.assertEqual([(x["titre"], x["statut"], x["detail"]) for x in faites],
                                 [("Remettre le bureau comme avant", statut, cli.RESTAURER[resultat])])
                self.assertEqual(faites[0]["pid"], os.getpid())
        taches.effacer_terminees()
        with mock.patch.object(modejeu, "restaurer", return_value="restaure"):
            self.cli("modejeu", "restaurer", "--si-orphelin")
        self.assertEqual(taches.lister(), [])

    def test_cli_restaurer_en_echec_ne_laisse_pas_la_tache_en_cours(self):
        with mock.patch.object(modejeu, "restaurer", side_effect=RuntimeError("boum")):
            code, _, erreur = self.cli("modejeu", "restaurer")
        self.assertEqual(code, 1)
        self.assertEqual([(x["statut"], x["detail"]) for x in taches.lister()],
                         [("echec", "La remise du bureau a échoué : RuntimeError: boum")])
        self.assertIn("boum", erreur)

    def test_cli_restaurer_sans_pouvoir_ecrire_la_tache_remet_quand_meme(self):
        """Disque plein : la tâche du panneau Activité ne s'écrit pas, mais la remise du bureau a lieu."""
        with mock.patch.object(taches, "debuter", side_effect=OSError(28, "No space left on device")), \
                mock.patch.object(modejeu, "restaurer", return_value="restaure") as restaurer:
            code, sortie, erreur = self.cli("modejeu", "restaurer")
        restaurer.assert_called_once()
        self.assertEqual((code, sortie), (0, "Mode jeu : bureau remis comme avant.\n"))
        self.assertIn("No space left", erreur)

    def test_cli_restaurer_sans_pouvoir_finir_la_tache_reussit(self):
        with mock.patch.object(taches, "terminer", side_effect=OSError(28, "No space left on device")), \
                mock.patch.object(modejeu, "restaurer", return_value="restaure"):
            code, sortie, _ = self.cli("modejeu", "restaurer")
        self.assertEqual((code, sortie), (0, "Mode jeu : bureau remis comme avant.\n"))

    def test_cli_restaurer_sans_partie(self):
        self.assertEqual(self.cli("modejeu", "restaurer", "--si-orphelin")[:2], (0, "Aucune partie à restaurer.\n"))

    def test_cli_modejeu_etat(self):
        """Task 6 : `modejeu` et `modejeu etat` disent la phrase du résumé, puis la dernière partie (P13 : la phrase de
        `derniere`, telle quelle) ; rien n'est publié. Le service noté est ce processus, dans ce démarrage du PC (lus
        seulement : /proc et un signal 0 à soi-même)."""
        commun.ecrire_json(modejeu.fichier(), {
            "service": {"pid": os.getpid(), "boot_id": taches.boot_id(), "depuis": "2026-11-10T18:00:00"},
            "partie": None,
            "derniere": {"jeu": JEU, "debut": "2026-11-10T21:10:00", "fin": "2026-11-10T23:02:00", "fin_par": "fin",
                         "actions": {}, "retour": {}, "avertissement": None}})
        derniere = "Dernière partie : Jeu de course, de 21 h 10 à 23 h 02.\n"
        with mock.patch.object(commun, "maintenant", return_value="2026-11-10T23:30:00"):
            for argv in (("modejeu",), ("modejeu", "etat")):
                with self.subTest(argv=argv):
                    self.assertEqual(self.cli(*argv)[:2],
                                     (0, "Mode jeu prêt : il s'active quand un jeu démarre.\n" + derniere))
            self.plantage_en_pleine_partie()
            donnees = modejeu.lire()
            commun.ecrire_json(modejeu.fichier(), dict(donnees, service=None))     # partie ouverte, service mort
            code, sortie, _ = self.cli("modejeu", "etat")
        self.assertEqual((code, sortie), (0, "Mode jeu interrompu : le bureau sera remis comme avant à la reprise du "
                                             "service.\n" + derniere))
        self.assertEqual(self.legers, [])               # `etat` ne publie rien

    def test_report_si_les_reglages_levent(self):
        with mock.patch.object(modejeu, "taches_en_pause", side_effect=RuntimeError("réglages illisibles")), \
                mock.patch.object(stockage, "ecrire", return_value=Path("stockage.json")) as ecrire:
            code, _, erreur = self.cli("stockage", environ=RELEVE)
        self.assertEqual(code, 0)
        ecrire.assert_called_once_with()                         # rien n'est reporté : la commande tourne
        self.assertIn("réglages illisibles", erreur)


class Report(BaseCli):
    def test_releve_reporte_pendant_un_jeu_si_coche(self):
        with mock.patch.object(stockage, "ecrire") as ecrire:
            code, sortie, _ = self.cli("stockage", environ=RELEVE)
        self.assertEqual((code, sortie), (0, "Mode jeu : stockage reportée pendant Jeu de course.\n"))
        ecrire.assert_not_called()

    def test_les_commandes_lourdes(self):
        self.assertEqual(cli.LOURDES, ("releve", "controles", "stockage", "jeux", "analyser"))
        with mock.patch.object(inventaire, "relever") as relever, \
                mock.patch.object(sante, "ecrire_controles") as controles, \
                mock.patch.object(cli, "_analyser") as analyser:
            for argv in (["releve"], ["controles", "--si-perime"], ["analyser", "--si-perime"]):
                with self.subTest(argv=argv):
                    code, sortie, _ = self.cli(*argv, environ=RELEVE)
                    self.assertEqual((code, sortie), (0, f"Mode jeu : {argv[0]} reportée pendant Jeu de course.\n"))
        for faux in (relever, controles, analyser):
            faux.assert_not_called()
        self.assertEqual(self.legers, [])

    def test_hors_releve_jamais_reporte(self):
        for environ in ({}, {"HEALTH_HUB_RELEVE": "0"}):
            with self.subTest(environ=environ), mock.patch.object(stockage, "ecrire", return_value=Path("s")) as ecrire:
                self.assertEqual(self.cli("stockage", environ=environ)[0], 0)
                ecrire.assert_called_once_with()

    def test_releve_pas_reporte_sans_jeu_ni_si_decoche(self):
        for jeu, cle in ((None, None), (JEU, "taches"), (JEU, "actif")):
            with self.subTest(jeu=jeu, cle=cle), configuration(""), \
                    mock.patch.object(stockage, "ecrire", return_value=Path("s")) as ecrire:
                self.jeu = jeu
                if cle:
                    modejeu.regler(cle, False)
                self.assertEqual(self.cli("stockage", environ=RELEVE)[0], 0)
                ecrire.assert_called_once_with()

    def test_rafraichir_devient_leger_pendant_la_pause(self):
        complets = []
        self.assertEqual(self.cli("rafraichir", environ=RELEVE, ecrire_etat=lambda: complets.append(1))[0], 0)
        self.assertEqual((complets, self.legers), ([], [1]))
        self.cli("rafraichir", environ={}, ecrire_etat=lambda: complets.append(1))
        self.assertEqual((complets, self.legers), ([1], [1]))


class Unites(unittest.TestCase):
    def test_unite_modejeu(self):
        self.assertEqual((SYSTEMD / "health-hub-modejeu.service").read_text(encoding="utf-8"), UNITE_MODEJEU)

    def test_releve_restaure_puis_reporte(self):
        lignes = (SYSTEMD / "centre-bazzite-releve.service").read_text(encoding="utf-8").splitlines()
        service = lignes[lignes.index("[Service]"):]
        self.assertIn("Environment=HEALTH_HUB_RELEVE=1", service)
        execs = [l for l in service if l.startswith("ExecStart=")]
        self.assertEqual(execs[:2], ["ExecStart=-%h/.local/bin/centre-bazzite modejeu restaurer --si-orphelin",
                                     "ExecStart=%h/.local/bin/centre-bazzite releve"])

    def test_install_sh_installe_le_mode_jeu(self):
        """P11 : lu en texte seulement, jamais exécuté (systemctl --user joindrait le vrai gestionnaire)."""
        bloc = INSTALL.read_text(encoding="utf-8").split("# debut-modejeu\n")[1].split("# fin-modejeu")[0]
        lignes = [l.strip() for l in bloc.splitlines() if l.strip() and not l.strip().startswith("#")]
        self.assertEqual(lignes, ['cp -f "$ici/systemd/health-hub-modejeu.service" "$unites/"',
                                  "systemctl --user daemon-reload",
                                  "systemctl --user try-restart health-hub-modejeu.service",     # P12, W6
                                  "systemctl --user enable --now health-hub-modejeu.service",
                                  'echo "mode jeu : health-hub-modejeu actif"'])


# --- Task 6 : le résumé du mode jeu (etat.json) ---

class Resume(Base):
    """Le résumé lu par la fenêtre, l'accueil et le widget : son état, sa phrase exacte, la dernière partie dite en
    Python (P13 : une seule phrase, reprise telle quelle par la CLI et la fenêtre, passage de minuit compris). Tout est
    injecté : pid vivant, démarrage du PC, réglages, heure."""
    MAINTENANT = "2026-11-10T22:30:00"
    SERVICE = {"pid": 4242, "boot_id": BOOT, "depuis": "2026-11-10T18:00:00"}
    ACTIONS = {"ollama": action("fait", "Ollama arrêté, mémoire vidéo rendue."),
               "ne_pas_deranger": action("fait", "Ne pas déranger activé."),
               "profil": action("echec", "Impossible : refusé"),
               "taches": action("fait", "Relevés de Health Hub en pause pendant la partie.")}
    PARTIE = {"jeu": JEU, "debut": HEURE, "boot_id": BOOT, "reglages": TOUT,
              "avant": {"ollama": True, "modeles": ["modele:7b"]}, "actions": ACTIONS,
              "avertissement": "Ollama répondait avec modele:7b : arrêté quand même, le jeu passe d'abord."}

    def ecrire(self, **donnees):
        commun.ecrire_json(modejeu.fichier(self.dossier), {"service": None, "partie": None, "derniere": None,
                                                           **donnees})

    def resume(self, *, vivant=True, boot=BOOT, reglages=TOUT, maintenant=MAINTENANT):
        self.pids = []

        def est_vivant(pid):
            self.pids.append(pid)
            return vivant
        return modejeu.resume(self.dossier, vivant=est_vivant, boot=lambda: boot, reglages=lambda: dict(reglages),
                              maintenant=maintenant)

    def test_mois_et_heure_fr(self):
        self.assertEqual(modejeu.MOIS, ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.",
                                        "oct.", "nov.", "déc."))
        self.assertEqual(modejeu.heure_fr("2026-11-10T21:10:00", self.MAINTENANT), "21 h 10")
        self.assertEqual(modejeu.heure_fr("2026-11-10T09:05:00", self.MAINTENANT), "9 h 05")
        self.assertEqual(modejeu.heure_fr("2026-11-09T23:50:00", self.MAINTENANT), "le 9 nov. à 23 h 50")
        self.assertEqual(modejeu.heure_fr("2026-02-01T00:00:00", self.MAINTENANT), "le 1er févr. à 0 h 00")
        self.assertEqual(modejeu.heure_fr("2026-11-02T21:10:00", self.MAINTENANT), "le 2 nov. à 21 h 10")
        self.assertEqual(modejeu.heure_fr("pas une date", self.MAINTENANT), "")
        self.assertEqual(modejeu.heure_fr(None, self.MAINTENANT), "")

    def test_resume_actif_phrase(self):
        self.ecrire(service=self.SERVICE, partie=self.PARTIE)
        r = self.resume()
        self.assertEqual((r["etat"], r["phrase"]), ("actif", "Mode jeu actif depuis 21 h 10"))
        self.assertEqual((r["jeu"], r["depuis"], r["actions"]), (JEU, HEURE, self.ACTIONS))
        self.assertEqual(r["avertissement"], self.PARTIE["avertissement"])
        self.assertEqual((r["derniere"], r["reglages"]), (None, TOUT))
        self.assertEqual(self.pids, [4242])                  # le pid du service, et lui seul

    def test_resume_actif_depuis_hier(self):
        self.ecrire(service=self.SERVICE, partie=dict(self.PARTIE, debut="2026-11-09T23:50:00"))
        self.assertEqual(self.resume()["phrase"], "Mode jeu actif depuis le 9 nov. à 23 h 50")

    def test_resume_service_mort_interrompu(self):
        interrompu = "Mode jeu interrompu : le bureau sera remis comme avant à la reprise du service."
        for service in (self.SERVICE, None):
            with self.subTest(service=service):
                self.ecrire(service=service, partie=self.PARTIE)
                r = self.resume(vivant=False)
                self.assertEqual((r["etat"], r["phrase"]), ("interrompu", interrompu))
                self.assertEqual((r["jeu"], r["depuis"], r["actions"]), (JEU, HEURE, self.ACTIONS))

    def test_resume_redemarrage_interrompu(self):
        """Un pid vivant d'un autre démarrage du PC n'est pas le service (pid repris) ; un démarrage illisible non plus."""
        self.ecrire(service=self.SERVICE, partie=self.PARTIE)
        for boot in ("boot-2", None):
            with self.subTest(boot=boot):
                self.assertEqual(self.resume(boot=boot)["etat"], "interrompu")
        self.ecrire(service=dict(self.SERVICE, boot_id=None), partie=self.PARTIE)
        self.assertEqual(self.resume(boot=None)["etat"], "interrompu")

    def test_resume_pret(self):
        derniere = {"jeu": JEU, "debut": "2026-11-10T21:10:00", "fin": "2026-11-10T22:02:00", "fin_par": "fin",
                    "actions": self.ACTIONS, "retour": {"ollama": action("fait", "Ollama relancé.")},
                    "avertissement": None}
        self.ecrire(service=self.SERVICE, derniere=derniere)
        r = self.resume()
        self.assertEqual((r["etat"], r["phrase"]), ("pret", "Mode jeu prêt : il s'active quand un jeu démarre."))
        self.assertEqual((r["jeu"], r["depuis"], r["actions"], r["avertissement"]), (None, None, None, None))
        self.assertEqual(r["derniere"], dict(derniere, phrase="Dernière partie : Jeu de course, de 21 h 10 à 22 h 02."))

    def test_resume_desactive(self):
        self.ecrire(service=self.SERVICE)
        for vivant in (True, False):
            with self.subTest(vivant=vivant):
                r = self.resume(vivant=vivant, reglages={**TOUT, "actif": False})
                self.assertEqual((r["etat"], r["phrase"]), ("desactive", "Mode jeu désactivé."))
                self.assertFalse(r["reglages"]["actif"])

    def test_resume_arrete(self):
        arrete = ("arrete", "Le service du mode jeu ne tourne pas.")
        r = self.resume()                                   # pas de modejeu.json
        self.assertEqual((r["etat"], r["phrase"]), arrete)
        self.assertEqual(self.pids, [])
        self.ecrire(service=self.SERVICE)
        self.assertEqual((self.resume(vivant=False)["etat"], self.resume(vivant=False)["phrase"]), arrete)
        self.assertEqual(self.resume(boot="boot-2")["etat"], "arrete")

    def test_derniere_partie_dite_en_python(self):
        """P13 : la même phrase pour la CLI et la fenêtre ; la date seulement si ce n'est pas aujourd'hui ; une partie
        à cheval sur minuit dit ses deux jours."""
        cas = [("2026-11-10T21:10:00", "2026-11-10T22:02:00", "Dernière partie : Jeu de course, de 21 h 10 à 22 h 02."),
               ("2026-11-09T21:10:00", "2026-11-09T23:02:00",
                "Dernière partie : Jeu de course, le 9 nov. de 21 h 10 à 23 h 02."),
               ("2026-11-09T23:50:00", "2026-11-10T00:40:00",
                "Dernière partie : Jeu de course, du 9 nov. à 23 h 50 au 10 nov. à 0 h 40."),
               ("2026-10-31T23:50:00", "2026-11-01T00:40:00",
                "Dernière partie : Jeu de course, du 31 oct. à 23 h 50 au 1er nov. à 0 h 40."),
               ("2026-11-01T21:10:00", "2026-11-01T22:02:00",
                "Dernière partie : Jeu de course, le 1er nov. de 21 h 10 à 22 h 02."),
               ("2026-11-10T21:10:00", None, "Dernière partie : Jeu de course, depuis 21 h 10."),
               (None, None, "Dernière partie : Jeu de course.")]
        for debut, fin, phrase in cas:
            with self.subTest(debut=debut, fin=fin):
                self.ecrire(service=self.SERVICE, derniere={"jeu": JEU, "debut": debut, "fin": fin, "fin_par": "fin",
                                                            "actions": {}, "retour": {}, "avertissement": None})
                self.assertEqual(self.resume()["derniere"]["phrase"], phrase)
        self.ecrire(service=self.SERVICE, derniere={"jeu": None, "debut": None, "fin": None})
        self.assertEqual(self.resume()["derniere"]["phrase"], "Dernière partie : jeu inconnu.")

    def test_resume_suit_commun_etat_et_l_heure(self):
        with mock.patch.object(commun, "ETAT", self.dossier), \
                mock.patch.object(commun, "maintenant", return_value="2026-11-11T08:00:00"):
            self.ecrire(service=self.SERVICE, partie=self.PARTIE)
            r = modejeu.resume(vivant=lambda pid: True, boot=lambda: BOOT, reglages=lambda: TOUT)
        self.assertEqual(r["phrase"], "Mode jeu actif depuis le 10 nov. à 21 h 10")


if __name__ == "__main__":
    unittest.main()
