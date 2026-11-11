"""Analyse de disque avec le moteur de LinStat : chargement, résumé, processus enfant, superviseur, cache, CLI et
stockage.json. Aucun vrai scan d'un vrai volume : le faux LinStat rend un arbre fixe, le superviseur reçoit de faux
lancer/jeu/tuer/attendre et la CLI un faux run. Seul test_vrai_linstat_petit_dossier lance le vrai moteur, sur un
dossier temporaire de 2 Mio ; les tests de _tuer_groupe arrêtent de vrais `sleep`."""
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from centre_bazzite import analyse, cli, commun, stockage, taches
from tests import configuration

ICI = Path(__file__).resolve().parent
FAUX = ICI / "echantillons" / "faux-linstat"
ANCIEN = ICI / "echantillons" / "faux-linstat-ancien"
ENFANT_FORKSERVER = ICI / "echantillons" / "enfant-forkserver.py"
LSBLK = (ICI / "echantillons" / "lsblk.json").read_text(encoding="utf-8")
GIO = 1024 ** 3
DONNEES = "/var/mnt/DONNEES"
EXTERNE = "/var/mnt/EXTERNE"
MONTES = [{"chemin": "/var"}, {"chemin": "/var/home"}, {"chemin": DONNEES}]          # EXTERNE débranché
VOLUMES = [{"nom": "Système", "chemin": "/var", "libre_go": 40.0, "total_go": 70.0, "pourcent_utilise": 42.9},
           {"nom": "Home", "chemin": "/var/home", "libre_go": 300.0, "total_go": 905.0, "pourcent_utilise": 66.9},
           {"nom": "Données", "chemin": DONNEES, "libre_go": 400.0, "total_go": 886.0, "pourcent_utilise": 54.9},
           {"nom": "EXTERNE", "chemin": EXTERNE, "libre_go": 2000.0, "total_go": 3725.0, "pourcent_utilise": 46.3}]
INTERROMPU = "Un jeu a démarré : l'analyse reprendra plus tard."


def oublier_linstat(dossier):
    """Ruling V7 : le faux, l'ancien et le vrai LinStat portent le même nom de module ; aucun ne doit suivre le test
    qui l'a chargé."""
    sys.modules.pop("linstat", None)
    while str(dossier) in sys.path:
        sys.path.remove(str(dossier))


def membres(pgid):
    """Processus vivants (non zombies) du groupe `pgid`, lus dans /proc."""
    n = 0
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            champs = (d / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if int(champs[2]) == pgid and champs[0] != "Z":
            n += 1
    return n


def attendre_que(condition, delai=3.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.etat = Path(tmp.name)
        p = mock.patch.object(commun, "ETAT", self.etat)
        p.start()
        self.addCleanup(p.stop)

    def charger(self, dossier):
        self.addCleanup(oublier_linstat, dossier)
        return analyse.charger_linstat(dossier)

    def tache(self, chemin):
        return next((t for t in taches.lister() if t["id"] == f"analyse:{chemin}"), None)


class Chargement(Base):
    def test_charger_linstat_absent(self):
        self.assertIsNone(self.charger(self.etat / "rien"))

    def test_charger_linstat_absent_par_defaut(self):
        with mock.patch.object(analyse, "LINSTAT_DIR", self.etat / "rien"):
            self.assertIsNone(analyse.charger_linstat())

    def test_charger_linstat_api_changee(self):
        self.assertIsNone(self.charger(ANCIEN))

    def test_charger_linstat_qui_leve(self):
        casse = self.etat / "casse"
        casse.mkdir()
        (casse / "linstat.py").write_text("raise RuntimeError('cassé')\n", encoding="utf-8")
        self.assertIsNone(self.charger(casse))

    def test_charger_le_faux_linstat(self):
        module = self.charger(FAUX)
        self.assertIsNotNone(module)
        self.assertTrue(hasattr(module, "Scanner"))
        self.assertEqual(sys.path[0], str(FAUX))       # les processus d'analyse le retrouvent

    def test_pas_de_contamination_entre_versions(self):
        """V7 : chaque chargement réimporte depuis son dossier, qui n'est inséré qu'une fois dans sys.path."""
        self.assertIsNotNone(self.charger(FAUX))
        self.assertIsNone(self.charger(ANCIEN))
        self.assertIsNotNone(self.charger(FAUX))
        self.assertEqual(sys.path.count(str(FAUX)), 1)
        self.assertEqual(sys.path.count(str(ANCIEN)), 1)


class Resume(Base):
    def test_resume_categories_et_plus_gros_dossiers(self):
        faux = self.charger(FAUX)
        scanner = faux.Scanner(DONNEES, one_fs=True, procs=2)
        a = analyse.resumer(scanner, scanner.run(), DONNEES, 12.34)
        self.assertEqual([d["nom"] for d in a["dossiers"]], ["Emulateur", "Bibliotheque", "DossierA", "DossierB"])
        self.assertEqual(a["dossiers"][0]["taille"], "388 Go")
        self.assertEqual(a["dossiers"][1], {"nom": "Bibliotheque", "chemin": "/var/mnt/DONNEES/Bibliotheque",
                                            "octets": 287 * GIO, "taille": "287 Go", "categorie": "Jeux"})
        self.assertIsNone(a["dossiers"][0]["categorie"])          # V23 : pas de règle de chemin, pas de catégorie
        self.assertEqual(a["categories"][0]["nom"], "Jeux")
        self.assertEqual(a["categories"][0], {"nom": "Jeux", "octets": 706 * GIO, "taille": "706 Go", "nombre": 18405})
        self.assertEqual((a["chemin"], a["total"], a["total_texte"]), (DONNEES, 757 * GIO, "757 Go"))
        self.assertEqual((a["fichiers"], a["erreurs"], a["duree_s"]), (22605, 3, 12.3))
        datetime.fromisoformat(a["date"])

    def test_resume_garde_les_10_plus_gros(self):
        faux = self.charger(FAUX)
        racine = faux.Dir("/x")
        for i in range(12):
            d = faux.Dir(f"d{i}")
            d.fsize, d.parent = (i + 1) * GIO, racine
            racine.dirs.append(d)
        a = analyse.resumer(faux.Scanner("/x"), racine, "/x", 1)
        self.assertEqual([d["nom"] for d in a["dossiers"]], [f"d{i}" for i in range(11, 1, -1)])
        self.assertEqual(len(a["dossiers"]), analyse.DOSSIERS_MAX)


    def test_resume_ignore_les_dossiers_vides(self):
        faux = self.charger(FAUX)
        racine = faux.Dir("/x")
        for nom, octets in (("vide", 0), ("plein", GIO), ("rien", 0)):
            d = faux.Dir(nom)
            d.fsize, d.parent = octets, racine
            racine.dirs.append(d)
        a = analyse.resumer(faux.Scanner("/x"), racine, "/x", 1)
        self.assertEqual([d["nom"] for d in a["dossiers"]], ["plein"])


class Enfant(Base):
    def test_analyser_volume_ecrit_le_cache(self):
        faux = self.charger(FAUX)
        sortie = analyse.cache(DONNEES)
        self.assertEqual(analyse.analyser_volume(DONNEES, sortie, None, linstat=faux), 0)
        a = json.loads(sortie.read_text(encoding="utf-8"))
        self.assertEqual(set(a), {"chemin", "date", "duree_s", "total", "total_texte", "fichiers", "erreurs",
                                  "categories", "dossiers"})
        self.assertEqual((a["chemin"], a["total"]), (DONNEES, 757 * GIO))
        self.assertEqual(len(a["dossiers"]), 4)

    def test_analyser_volume_sans_linstat_code_3(self):
        sortie = self.etat / "analyses" / "var.json"
        with mock.patch.object(analyse, "LINSTAT_DIR", self.etat / "rien"), redirect_stderr(io.StringIO()):
            self.assertEqual(analyse.analyser_volume("/var", sortie, None), analyse.CODE_SANS_LINSTAT)
        self.assertEqual(analyse.CODE_SANS_LINSTAT, 3)
        self.assertFalse(sortie.exists())

    def test_analyser_volume_ecrit_l_avancement(self):
        faux = self.charger(FAUX)
        id_ = taches.debuter("analyse", DONNEES, "Analyse de Données", unite="health-hub-analyse.service")
        with mock.patch.object(analyse, "AVANCEMENT_S", 0.02), mock.patch.object(faux, "PAUSE_S", 0.3):
            self.assertEqual(analyse.analyser_volume(DONNEES, self.etat / "a.json", id_, linstat=faux), 0)
        t = self.tache(DONNEES)
        self.assertEqual(t["detail"], "22 605 fichiers, 757 Go vus")
        self.assertEqual((t["statut"], t["progression"]), ("en_cours", -1))      # le superviseur la termine

    def test_volume_demonte_pendant_l_analyse_garde_le_cache(self):
        """Constat 1 : EXTERNE débranché pendant l'analyse (montage disparu ou autre st_dev) → pas de résumé écrit."""
        faux = self.charger(FAUX)
        for debut, fin in (((True, 41), (True, 42)), ((True, 41), (False, 41)), ((True, 41), (False, None))):
            commun.ecrire_json(analyse.cache(EXTERNE), {"ancien": True})
            avant = analyse.cache(EXTERNE).read_bytes()
            etats = [debut, fin]
            with redirect_stderr(io.StringIO()) as erreur:
                code = analyse.analyser_volume(EXTERNE, analyse.cache(EXTERNE), None, linstat=faux,
                                               montage=lambda chemin: etats.pop(0))
            self.assertEqual(code, analyse.CODE_DEMONTE)
            self.assertEqual(analyse.cache(EXTERNE).read_bytes(), avant)
            self.assertIn(analyse.DEMONTE, erreur.getvalue())

    def test_volume_toujours_monte_ecrit_le_cache(self):
        faux = self.charger(FAUX)
        appels = []
        code = analyse.analyser_volume(DONNEES, analyse.cache(DONNEES), None, linstat=faux,
                                       montage=lambda chemin: appels.append(chemin) or (True, 41))
        self.assertEqual((code, appels), (0, [DONNEES, DONNEES]))
        self.assertTrue(analyse.cache(DONNEES).exists())

    def test_api_linstat_changee_au_dela_des_attributs(self):
        """Constat 3 : une autre forme de categories() ou un mot-clé renommé → CODE_SANS_LINSTAT, pas une trace."""
        faux = self.charger(FAUX)

        class ScannerRenomme(faux.Scanner):
            def __init__(self, root, one_fs=True, workers=None):
                super().__init__(root, one_fs)

        changements = [mock.patch.object(faux.Scanner, "categories", lambda self: [{"name": "Jeux", "bytes": 1}]),
                       mock.patch.object(faux, "Scanner", ScannerRenomme),
                       mock.patch.object(faux.Scanner, "tree", lambda self: None),
                       mock.patch.object(faux.Dir, "path", None)]
        for changement in changements:
            with self.subTest(changement=changement), changement, redirect_stderr(io.StringIO()) as erreur:
                sortie = self.etat / "api.json"
                code = analyse.analyser_volume(DONNEES, sortie, None, linstat=faux, montage=lambda chemin: (True, 1))
                self.assertEqual(code, analyse.CODE_SANS_LINSTAT)
                self.assertFalse(sortie.exists())
                self.assertIn(analyse.SANS_LINSTAT, erreur.getvalue())
                self.assertNotIn("Traceback", erreur.getvalue())

    def test_main_lit_ses_arguments(self):
        with mock.patch.object(analyse, "analyser_volume", return_value=0) as av:
            self.assertEqual(analyse.main([DONNEES, "/tmp/x.json", "--tache", "analyse:/var/mnt/DONNEES"]), 0)
            self.assertEqual(analyse.main(["/var", "/tmp/y.json"]), 0)
        self.assertEqual(av.call_args_list, [mock.call(DONNEES, Path("/tmp/x.json"), "analyse:/var/mnt/DONNEES"),
                                             mock.call("/var", Path("/tmp/y.json"), None)])

    @unittest.skipUnless((analyse.LINSTAT_DIR / "linstat.py").exists(), "LinStat n'est pas installé")
    def test_vrai_linstat_petit_dossier(self):
        module = self.charger(analyse.LINSTAT_DIR)
        self.assertIsNotNone(module)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "film.mp4").write_bytes(b"\1" * 1024 ** 2)
            (Path(d) / "modele.gguf").write_bytes(b"\2" * 1024 ** 2)
            sortie = self.etat / "petit.json"
            with redirect_stderr(io.StringIO()):
                self.assertEqual(analyse.analyser_volume(d, sortie, None, linstat=module), 0)
        a = json.loads(sortie.read_text(encoding="utf-8"))
        noms = [c["nom"] for c in a["categories"]]
        self.assertIn("Vidéos", noms)
        self.assertIn("Modèles IA", noms)
        self.assertGreaterEqual(a["total"], 2 * 1024 ** 2)


class Cache(Base):
    def test_nom_du_cache(self):
        self.assertEqual(analyse.cache("/var"), self.etat / "analyses" / "var.json")
        self.assertEqual(analyse.cache(DONNEES), self.etat / "analyses" / "var_mnt_DONNEES.json")
        self.assertEqual(analyse.cache("/"), self.etat / "analyses" / "racine.json")

    def test_perime(self):
        maintenant = datetime(2026, 11, 9, 15, 0)
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant))
        commun.ecrire_json(analyse.cache(DONNEES), {"date": (maintenant - timedelta(days=8)).isoformat()})
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant))
        commun.ecrire_json(analyse.cache(DONNEES), {"date": (maintenant - timedelta(days=1)).isoformat()})
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant))

    def test_perime_cache_illisible(self):
        analyse.cache(DONNEES).parent.mkdir(parents=True)
        analyse.cache(DONNEES).write_text("{pas du json", encoding="utf-8")
        self.assertTrue(analyse.perime(DONNEES))

    def test_perime_apres_une_interruption(self):
        """V15 : une analyse interrompue par un jeu reprend au relevé suivant, même si un ancien cache est récent."""
        maintenant = datetime(2026, 11, 9, 15, 0)
        commun.ecrire_json(analyse.cache(DONNEES), {"date": (maintenant - timedelta(days=1)).isoformat()})
        id_ = taches.debuter("analyse", DONNEES, "Analyse de Données", unite="health-hub-analyse.service")
        taches.terminer(id_, "interrompu", INTERROMPU)
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant))
        taches.terminer(id_, "fini", "644 Go analysés en 4 min")
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant))


    def test_echec_recent_pas_perime(self):
        """Constat 2 : une analyse en échec n'est pas relancée à chaque relevé, seulement 24 h plus tard."""
        id_ = taches.debuter("analyse", DONNEES, "Analyse de Données", unite="health-hub-analyse.service")
        taches.terminer(id_, "echec", analyse.SANS_LINSTAT)
        maintenant = datetime.now()
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=2)))      # sans cache
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=25)))
        commun.ecrire_json(analyse.cache(DONNEES), {"date": (maintenant - timedelta(days=8)).isoformat()})
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=2)))      # cache vieux

    def test_echec_sans_date_de_fin_reste_perime(self):
        id_ = taches.debuter("analyse", DONNEES, "Analyse de Données", unite="health-hub-analyse.service")
        taches.terminer(id_, "echec", "x")
        fichier = next((self.etat / "taches").glob("analyse_*.json"))
        t = json.loads(fichier.read_text(encoding="utf-8"))
        t["fin"] = None
        fichier.write_text(json.dumps(t), encoding="utf-8")
        self.assertTrue(analyse.perime(DONNEES))


class FauxProc:
    """Popen factice : poll() rend les codes dans l'ordre, puis répète le dernier."""

    def __init__(self, pid, codes):
        self.pid = pid
        self.codes = list(codes)

    def poll(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]


class BaseSuperviseur(Base):
    def lanceur(self, comportements):
        """comportements : {chemin: (codes de poll, total écrit dans le cache par l'« enfant » ou None, stderr)}."""
        appels = []

        def lancer(argv, **kw):
            appels.append((argv, kw))
            codes, total, erreur = comportements[argv[8]]
            if total is not None:
                commun.ecrire_json(argv[9], {"chemin": argv[8], "total": total, "duree_s": 240.0})
            if erreur:
                kw["stderr"].write(erreur.encode())
            return FauxProc(1000 + len(appels), codes)
        return lancer, appels

    def superviser(self, chemins, **kw):
        kw.setdefault("tuer", mock.Mock())
        kw.setdefault("attendre", lambda s: None)
        kw.setdefault("est_monte", lambda chemin: True)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return analyse.superviser(chemins, **kw)


class Superviseur(BaseSuperviseur):
    def test_superviser_enchaine_les_volumes(self):
        lancer, appels = self.lanceur({"/var": ([None, 0], 12 * GIO, ""), DONNEES: ([0], 644 * GIO, "")})
        attentes, tuer = [], mock.Mock()
        res = self.superviser(["/var", DONNEES], lancer=lancer, jeu=lambda: None, tuer=tuer, attendre=attentes.append)
        self.assertEqual(len(appels), 2)
        paquet = str(Path(analyse.__file__).resolve().parent.parent)
        for argv, kw in appels:
            self.assertEqual(argv[:5], ["nice", "-n", "19", "ionice", "-c3"])
            self.assertEqual(argv[5:8], [sys.executable, "-m", "centre_bazzite.analyse"])
            self.assertTrue(kw["start_new_session"])
            self.assertEqual(kw["env"]["PYTHONPATH"].split(os.pathsep)[0], paquet)
        self.assertEqual(appels[1][0][8:], [DONNEES, str(analyse.cache(DONNEES)), "--tache", "analyse:/var/mnt/DONNEES"])
        self.assertEqual(res, {"/var": "fini", DONNEES: "fini"})
        t = self.tache(DONNEES)
        self.assertEqual((t["statut"], t["detail"], t["titre"], t["unite"]),
                         ("fini", "644 Go analysés en 4 min", "Analyse de Données", "health-hub-analyse.service"))
        self.assertEqual(self.tache("/var")["titre"], "Analyse de Système")
        self.assertEqual(set(attentes), {analyse.INTERVALLE_S})
        with configuration('[[volumes]]\nnom = "Atelier"\nchemin = "/var/mnt/ATELIER"\n'):
            self.assertEqual(analyse._titre("/var/mnt/ATELIER"), "Analyse de Atelier")
            self.assertEqual(analyse._titre(DONNEES), "Analyse de DONNEES")      # hors de la configuration : son dossier
        tuer.assert_not_called()

    def test_jeu_arrete_l_analyse_et_garde_l_ancien_cache(self):
        commun.ecrire_json(analyse.cache(DONNEES), {"ancien": True})
        avant = analyse.cache(DONNEES).read_bytes()
        lancer, appels = self.lanceur({DONNEES: ([None], None, ""), "/var": ([0], GIO, "")})
        reponses = [None, None]
        tuer = mock.Mock()
        res = self.superviser([DONNEES, "/var"], lancer=lancer, tuer=tuer,
                              jeu=lambda: reponses.pop(0) if reponses else "jeu.exe")
        tuer.assert_called_once_with(1001)
        t = self.tache(DONNEES)
        self.assertEqual((t["statut"], t["detail"]), ("interrompu", INTERROMPU))
        self.assertEqual(analyse.cache(DONNEES).read_bytes(), avant)
        self.assertEqual(len(appels), 1)                  # le second volume n'est jamais lancé
        self.assertIsNone(self.tache("/var"))
        self.assertEqual(res, {DONNEES: "interrompu"})

    def test_jeu_entre_deux_volumes(self):
        lancer, appels = self.lanceur({"/var": ([0], GIO, ""), DONNEES: ([0], GIO, "")})
        reponses = [None]               # avant /var : pas de jeu ; avant Données : un jeu a démarré
        res = self.superviser(["/var", DONNEES], lancer=lancer,
                              jeu=lambda: reponses.pop(0) if reponses else "jeu.exe")
        self.assertEqual(res, {"/var": "fini"})
        self.assertEqual(len(appels), 1)

    def test_superviser_echecs(self):
        trace = ("Traceback (most recent call last):\n  File \"linstat.py\", line 1\n"
                 "PermissionError: [Errno 13] Permission non accordée: '/var/mnt/DONNEES/x'\n\n")
        lancer, appels = self.lanceur({"/var": ([3], None, ""), DONNEES: ([1], None, trace), "/var/home": ([-9], None, ""),
                                       EXTERNE: ([4], None, "")})
        res = self.superviser(["/var", DONNEES, "/var/home", EXTERNE], lancer=lancer, jeu=lambda: None)
        self.assertEqual(res, {"/var": "echec", DONNEES: "echec", "/var/home": "echec", EXTERNE: "echec"})
        self.assertEqual(self.tache(EXTERNE)["detail"], analyse.DEMONTE)
        self.assertEqual(self.tache("/var")["detail"], "LinStat est absent ou a changé : seul l'espace libre est affiché.")
        self.assertEqual(self.tache(DONNEES)["detail"], "PermissionError: [Errno 13] Permission non accordée: '/var/mnt/DONNEES/x'")
        self.assertEqual(self.tache("/var/home")["detail"], "L'analyse s'est arrêtée (code -9).")

    def test_superviser_saute_un_volume_demonte(self):
        """Constat 1 (Review Focus 3) : EXTERNE débranché pendant la file n'est pas analysé, son cache reste."""
        commun.ecrire_json(analyse.cache(EXTERNE), {"ancien": True})
        avant = analyse.cache(EXTERNE).read_bytes()
        lancer, appels = self.lanceur({"/var": ([0], GIO, ""), EXTERNE: ([0], 0, ""), DONNEES: ([0], GIO, "")})
        verifies = []
        res = self.superviser(["/var", EXTERNE, DONNEES], lancer=lancer, jeu=lambda: None,
                              est_monte=lambda chemin: verifies.append(chemin) or chemin != EXTERNE)
        self.assertEqual(verifies, ["/var", EXTERNE, DONNEES])
        self.assertEqual([argv[8] for argv, kw in appels], ["/var", DONNEES])
        self.assertEqual(res, {"/var": "fini", DONNEES: "fini"})
        self.assertIsNone(self.tache(EXTERNE))
        self.assertEqual(analyse.cache(EXTERNE).read_bytes(), avant)

    def test_superviser_previent_apres_chaque_volume(self):
        """Revue finale M1 : `apres_volume` est appelé quand la tâche du volume est finie (réussite ou échec)."""
        lancer, _ = self.lanceur({"/var": ([0], GIO, ""), DONNEES: ([3], None, "")})
        vus = []
        self.superviser(["/var", DONNEES], lancer=lancer, jeu=lambda: None,
                        apres_volume=lambda: vus.append({c: (self.tache(c) or {}).get("statut") for c in ("/var", DONNEES)}))
        self.assertEqual(vus, [{"/var": "fini", DONNEES: None}, {"/var": "fini", DONNEES: "echec"}])

    def test_superviser_lancement_impossible(self):
        def lancer(argv, **kw):
            raise FileNotFoundError("ionice")
        res = self.superviser(["/var", DONNEES], lancer=lancer, jeu=lambda: None)
        self.assertEqual(res, {"/var": "echec", DONNEES: "echec"})
        self.assertIn("ionice", self.tache("/var")["detail"])

    def lancer_groupe(self, script):
        p = subprocess.Popen(["bash", "-c", script], start_new_session=True)

        def nettoyer():
            try:
                os.killpg(p.pid, 9)
            except ProcessLookupError:
                pass
            p.poll()
        self.addCleanup(nettoyer)
        self.assertTrue(attendre_que(lambda: membres(p.pid) >= 2))
        return p

    def groupe_parti(self, pgid):
        def parti():
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            return False
        return attendre_que(parti)

    def test_tuer_groupe_arrete_tout_le_groupe(self):
        p = self.lancer_groupe("sleep 30 & sleep 30; true")
        debut = time.monotonic()
        analyse._tuer_groupe(p.pid)
        self.assertLess(time.monotonic() - debut, 5)
        self.assertTrue(self.groupe_parti(p.pid))
        p.poll()

    def test_tuer_groupe_force_apres_le_delai(self):
        p = self.lancer_groupe("trap '' TERM; sleep 30 & sleep 30; true")
        debut = time.monotonic()
        analyse._tuer_groupe(p.pid, delai=0.5)
        self.assertGreaterEqual(time.monotonic() - debut, 0.5)
        self.assertTrue(self.groupe_parti(p.pid))
        p.poll()


    def test_tuer_groupe_arrete_un_enfant_et_son_pool_forkserver(self):
        """Constat 4 : comme LinStat, l'enfant lance un pool forkserver (forkserver, processus d'analyse,
        resource_tracker qui ignore SIGTERM) ; tout son groupe disparaît."""
        # le forkserver tué net ne retire pas son dossier pymp-* : il le crée dans un TMPDIR à nous, effacé ensuite
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = subprocess.Popen([sys.executable, str(ENFANT_FORKSERVER)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env={**os.environ, "TMPDIR": tmp.name})

        def nettoyer():
            try:
                os.killpg(p.pid, 9)
            except ProcessLookupError:
                pass
            p.poll()
        self.addCleanup(nettoyer)
        # l'enfant, le forkserver, deux processus d'analyse et le resource_tracker
        self.assertTrue(attendre_que(lambda: membres(p.pid) >= 5, delai=15))
        debut = time.monotonic()
        analyse._tuer_groupe(p.pid)
        self.assertLess(time.monotonic() - debut, 15)
        self.assertTrue(self.groupe_parti(p.pid))
        self.assertEqual(membres(p.pid), 0)
        p.poll()


class BaseCli(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(analyse, "LINSTAT_DIR", FAUX)       # --si-perime vérifie LinStat : le faux
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(oublier_linstat, FAUX)

    def appeler(self, argv, **kw):
        sortie, erreur = io.StringIO(), io.StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = cli.main(argv, **kw)
        return code, sortie.getvalue() + erreur.getvalue()

    def faux_run(self, code=0, texte="Running as unit: health-hub-analyse.service"):
        appels = []

        def run(cmd, **kw):
            appels.append(cmd)
            return code, texte
        return run, appels


class Cli(BaseCli):
    def test_cli_analyser_lance_l_unite(self):
        run, appels = self.faux_run()
        code, texte = self.appeler(["analyser"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [["systemd-run", "--user", "--unit=health-hub-analyse", "--collect",
                                   "--property=Type=exec", str(cli.BIN), "_analyser", "/var", "/var/home", DONNEES]])

    def test_cli_analyser_refuse_pendant_un_jeu(self):
        run, appels = self.faux_run()
        code, texte = self.appeler(["analyser", DONNEES], run=run, jeu=lambda: "jeu.exe", volumes=lambda: MONTES)
        self.assertEqual(code, 75)
        self.assertIn("Un jeu tourne : analyse reportée.", texte)
        self.assertEqual(appels, [])

    def test_cli_analyser_si_perime_pendant_un_jeu_ne_fait_pas_echouer_le_releve(self):
        """V4 : le relevé horaire ne passe pas en échec pendant une partie."""
        run, appels = self.faux_run()
        code, texte = self.appeler(["analyser", "--si-perime"], run=run, jeu=lambda: "jeu.exe",
                                   volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertIn("Un jeu tourne : analyse reportée.", texte)
        self.assertEqual(appels, [])

    def test_cli_analyser_deja_en_cours(self):
        run, appels = self.faux_run(1, "Failed to start transient service unit: Unit health-hub-analyse.service "
                                       "was already loaded or has a fragment file.")
        code, texte = self.appeler(["analyser"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertIn("Une analyse est déjà en cours.", texte)
        self.assertEqual(len(appels), 1)

    def test_cli_analyser_erreur_de_systemd_run(self):
        run, appels = self.faux_run(4, "Failed to connect to bus")
        code, texte = self.appeler(["analyser"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 4)
        self.assertIn("Failed to connect to bus", texte)

    def test_cli_analyser_ignore_un_volume_non_monte(self):
        """Review Focus 3 : EXTERNE débranché n'est jamais analysé, ni par défaut ni s'il est demandé."""
        run, appels = self.faux_run()
        self.appeler(["analyser"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertNotIn(EXTERNE, appels[0])
        code, texte = self.appeler(["analyser", EXTERNE, "/var"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertNotIn(EXTERNE, appels[1])
        self.assertEqual(appels[1][-2:], ["_analyser", "/var"])
        self.assertIn("n'est pas monté", texte)

    def test_cli_analyser_volume_de_la_configuration_non_monte(self):
        """Un volume de la configuration qui n'est pas parmi les montés est ignoré, sans regarder le disque."""
        run, appels = self.faux_run()
        conf = '[[volumes]]\nnom = "Atelier"\nchemin = "/var/mnt/ATELIER"\n'
        with configuration(conf), mock.patch.object(cli.os.path, "ismount", return_value=True):
            code, texte = self.appeler(["analyser", "/var/mnt/ATELIER", "/var"], run=run, jeu=lambda: None,
                                       volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertEqual(appels[0][-2:], ["_analyser", "/var"])
        self.assertIn("/var/mnt/ATELIER n'est pas monté", texte)

    def test_cli_analyser_seulement_des_volumes_non_montes(self):
        run, appels = self.faux_run()
        code, texte = self.appeler(["analyser", EXTERNE], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual((code, appels), (0, []))

    def test_cli_analyser_si_perime_rien_a_faire(self):
        for v in MONTES:
            commun.ecrire_json(analyse.cache(v["chemin"]), {"date": commun.maintenant()})
        run, appels = self.faux_run()
        code, texte = self.appeler(["analyser", "--si-perime"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [])

    def test_cli_analyser_si_perime_garde_les_perimes(self):
        commun.ecrire_json(analyse.cache("/var"), {"date": commun.maintenant()})
        run, appels = self.faux_run()
        self.appeler(["analyser", "--si-perime"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(appels[0][-3:], ["_analyser", "/var/home", DONNEES])

    def test_cli_analyser_si_perime_sans_linstat_ne_lance_rien(self):
        """Constat 2 : sans LinStat, le relevé horaire ne lance pas une analyse vouée à l'échec."""
        run, appels = self.faux_run()
        with mock.patch.object(analyse, "LINSTAT_DIR", self.etat / "rien"):
            code, texte = self.appeler(["analyser", "--si-perime"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
            self.assertEqual((code, appels), (0, []))
            self.assertIn("LinStat", texte)
            code, texte = self.appeler(["analyser", "/var"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertEqual(appels[0][-2:], ["_analyser", "/var"])     # à la demande, l'échec s'affiche dans la tâche

    def test_cli__analyser_supervise_puis_ecrit_le_stockage(self):
        ordre = []
        jeu = lambda: None
        with mock.patch.object(analyse, "superviser", side_effect=lambda *a, **k: ordre.append("superviser") or {}) \
                as sup, mock.patch.object(stockage, "ecrire", side_effect=lambda: ordre.append("ecrire") or Path("x")), \
                mock.patch.object(analyse, "poser_arret", side_effect=lambda etat: ordre.append("poser_arret")) as pose:
            code, _ = self.appeler(["_analyser", "/var", DONNEES], jeu=jeu)
        self.assertEqual(code, 0)
        etat = pose.call_args.args[0]
        sup.assert_called_once_with(["/var", DONNEES], jeu=jeu, etat=etat, apres_volume=mock.ANY)
        self.assertEqual(ordre, ["poser_arret", "superviser", "ecrire"])

    def test_releve_lance_analyser_en_dernier_sans_echec(self):
        texte = (ICI.parent / "systemd" / "centre-bazzite-releve.service").read_text(encoding="utf-8")
        lignes = [l for l in texte.splitlines() if l.startswith("ExecStart=")]
        self.assertEqual(lignes[-1], "ExecStart=-%h/.local/bin/centre-bazzite analyser --si-perime")


class Arret(BaseSuperviseur):
    """Task 16b : arrêter une analyse en cours (bouton « Arrêter », ou fin de session / extinction). Aucun vrai signal :
    le gestionnaire de SIGTERM est appelé à la place d'une attente du superviseur."""

    def arreter_pendant(self, chemins, *, manuel, appel_arret=1):
        """Superviseur sur `chemins` (premier enfant jamais fini) ; SIGTERM arrive pendant la `appel_arret`-ième
        attente. Renvoie (lancements, tuer, code de sortie)."""
        if manuel:
            analyse.marqueur_arret().parent.mkdir(parents=True, exist_ok=True)
            analyse.marqueur_arret().write_text("", encoding="utf-8")
        lancer, appels = self.lanceur({c: ([None], None, "") for c in chemins})
        tuer, etat, attentes = mock.Mock(), {}, []
        gerer = analyse.gestionnaire_arret(etat, tuer=tuer)

        def attendre(s):
            attentes.append(s)
            if len(attentes) == appel_arret:
                gerer(signal.SIGTERM, None)
        with self.assertRaises(SystemExit) as sortie:
            self.superviser(chemins, lancer=lancer, jeu=lambda: None, attendre=attendre, etat=etat)
        return appels, tuer, sortie.exception.code

    def test_arret_manuel_marque_la_tache_et_garde_le_cache(self):
        commun.ecrire_json(analyse.cache(DONNEES), {"ancien": True})
        avant = analyse.cache(DONNEES).read_bytes()
        appels, tuer, code = self.arreter_pendant([DONNEES, "/var"], manuel=True)
        self.assertEqual(code, 0)
        tuer.assert_called_once_with(1001)
        t = self.tache(DONNEES)
        self.assertEqual((t["statut"], t["detail"], t.get("arret")), ("interrompu", analyse.ARRET_MANUEL, "manuel"))
        self.assertEqual(analyse.cache(DONNEES).read_bytes(), avant)
        self.assertEqual([argv[8] for argv, kw in appels], [DONNEES])       # le second volume n'est jamais lancé
        self.assertFalse(analyse.marqueur_arret().exists())

    def test_arret_manuel_suspend_aussi_les_volumes_en_attente(self):
        """Les volumes qui attendaient leur tour sont aussi arrêtés à ta demande : le relevé suivant ne les lance pas."""
        self.arreter_pendant([DONNEES, "/var"], manuel=True)
        t = self.tache("/var")
        self.assertEqual((t["statut"], t["detail"], t.get("arret")), ("interrompu", analyse.ARRET_MANUEL, "manuel"))
        self.assertFalse(analyse.perime("/var"))

    def test_arret_systeme_sans_marqueur(self):
        commun.ecrire_json(analyse.cache(DONNEES), {"ancien": True})
        avant = analyse.cache(DONNEES).read_bytes()
        appels, tuer, code = self.arreter_pendant([DONNEES, "/var"], manuel=False)
        self.assertEqual(code, 0)
        tuer.assert_called_once_with(1001)
        t = self.tache(DONNEES)
        self.assertEqual((t["statut"], t["detail"]), ("interrompu", analyse.ARRET_SYSTEME))
        self.assertNotIn("arret", t)
        self.assertEqual(analyse.cache(DONNEES).read_bytes(), avant)
        self.assertEqual(len(appels), 1)
        self.assertIsNone(self.tache("/var"))                 # en attente : reprise normale plus tard (V15)
        self.assertTrue(analyse.perime(DONNEES))

    def test_arret_apres_la_fin_d_un_volume_ne_le_reecrit_pas(self):
        """SIGTERM entre deux volumes : la tâche finie le reste, rien n'est tué."""
        lancer, appels = self.lanceur({"/var": ([0], GIO, ""), DONNEES: ([None], None, "")})
        tuer, etat = mock.Mock(), {}
        gerer = analyse.gestionnaire_arret(etat, tuer=tuer)
        reponses = [None]

        def jeu():                  # le second appel (avant Données) reçoit l'arrêt, comme un signal entre deux volumes
            if reponses:
                return reponses.pop()
            gerer(signal.SIGTERM, None)
        with self.assertRaises(SystemExit):
            self.superviser(["/var", DONNEES], lancer=lancer, jeu=jeu, tuer=mock.Mock(), etat=etat)
        self.assertEqual(self.tache("/var")["statut"], "fini")
        tuer.assert_not_called()
        self.assertEqual(len(appels), 1)

    def test_arret_tolere_un_enfant_deja_tue(self):
        etat = {"id": "analyse:/var", "pid": 999999, "restants": []}
        taches.debuter("analyse", "/var", "Analyse de Système", unite="health-hub-analyse.service")
        analyse.arreter(etat, tuer=mock.Mock(side_effect=ProcessLookupError))
        self.assertEqual(self.tache("/var")["detail"], analyse.ARRET_SYSTEME)

    def test_marqueur_dans_le_dossier_d_etat(self):
        self.assertEqual(analyse.marqueur_arret(), self.etat / "analyses" / "arret-demande")
        self.assertEqual(analyse.marqueur_arret("/x"), Path("/x/analyses/arret-demande"))
        self.assertEqual((analyse.PAUSE_APRES_ARRET_H, analyse.ARRET_MANUEL),
                         (24, "Analyse arrêtée à ta demande."))

    def test_gestionnaire_pose_seulement_a_la_demande(self):
        """Jamais à l'import : seul le chemin `_analyser` pose le gestionnaire de SIGTERM."""
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)
        self.addCleanup(signal.signal, signal.SIGTERM, signal.SIG_DFL)
        analyse.poser_arret({})
        self.assertTrue(callable(signal.getsignal(signal.SIGTERM)))

    def test_pas_de_relance_auto_apres_arret_manuel(self):
        maintenant = datetime.now()
        id_ = taches.debuter("analyse", DONNEES, "Analyse de Données", unite="health-hub-analyse.service")
        taches.terminer(id_, "interrompu", analyse.ARRET_MANUEL, arret="manuel")
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=2)))      # sans cache
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=25)))
        commun.ecrire_json(analyse.cache(DONNEES), {"date": maintenant.isoformat()})
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=25)))     # règle habituelle
        id_ = taches.debuter("analyse", DONNEES, "Analyse de Données", unite="health-hub-analyse.service")
        taches.terminer(id_, "interrompu", analyse.ARRET_SYSTEME)         # analyse suivante, arrêtée par le système
        self.assertNotIn("arret", self.tache(DONNEES))
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=2)))      # V15


class CliArret(BaseCli):
    ACTIVE = ["systemctl", "--user", "is-active", "health-hub-analyse.service"]
    STOP = ["systemctl", "--user", "stop", "health-hub-analyse.service"]

    def faux_systemctl(self, actif, code_stop=0, texte_stop=""):
        appels, marqueur_au_stop = [], []

        def run(cmd, **kw):
            appels.append(cmd)
            if cmd == self.ACTIVE:
                return (0, "active") if actif else (3, "inactive")
            if cmd == self.STOP:
                marqueur_au_stop.append(analyse.marqueur_arret().exists())
                return code_stop, texte_stop
            return 0, ""
        return run, appels, marqueur_au_stop

    def test_cli_arreter_sans_analyse(self):
        run, appels, _ = self.faux_systemctl(actif=False)
        code, texte = self.appeler(["analyser", "--arreter"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertEqual(texte.strip(), "Aucune analyse en cours.")
        self.assertEqual(appels, [self.ACTIVE])
        self.assertFalse(analyse.marqueur_arret().exists())

    def test_cli_arreter_analyse_en_cours(self):
        run, appels, marqueur_au_stop = self.faux_systemctl(actif=True)
        code, texte = self.appeler(["analyser", "--arreter"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [self.ACTIVE, self.STOP])
        self.assertEqual(marqueur_au_stop, [True])                 # le superviseur le lit en recevant SIGTERM
        self.assertIn("Analyse arrêtée.", texte)
        self.assertFalse(analyse.marqueur_arret().exists())        # jamais laissé derrière (arrêt système suivant)

    def test_cli_arreter_echec_de_stop(self):
        run, appels, _ = self.faux_systemctl(actif=True, code_stop=1, texte_stop="Failed to stop: Access denied")
        code, texte = self.appeler(["analyser", "--arreter"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        self.assertEqual(code, 1)
        self.assertIn("Failed to stop: Access denied", texte)
        self.assertFalse(analyse.marqueur_arret().exists())


class Republication(BaseCli, BaseSuperviseur):
    """Revue finale M1 : stockage.json republié après chaque volume et à la fin, même après un arrêt, sans jamais
    lever. stockage.ecrire est remplacé : aucun relevé réel."""

    def test_cli__analyser_republie_apres_chaque_volume(self):
        """Revue finale M1 : une page ouverte voit chaque volume fini, sans attendre la fin de la file."""
        lancer, _ = self.lanceur({"/var": ([0], GIO, ""), DONNEES: ([0], GIO, "")})
        vus = []

        def ecrire():
            vus.append({c: (self.tache(c) or {}).get("statut") for c in ("/var", DONNEES)})
            return Path("stockage.json")

        vrai = analyse.superviser
        with mock.patch.object(analyse, "superviser",
                               side_effect=lambda *a, **k: vrai(*a, lancer=lancer, attendre=lambda s: None,
                                                                est_monte=lambda c: True, **k)), \
                mock.patch.object(stockage, "ecrire", side_effect=ecrire), mock.patch.object(analyse, "poser_arret"):
            code, _ = self.appeler(["_analyser", "/var", DONNEES], jeu=lambda: None)
        self.assertEqual(code, 0)
        self.assertEqual(vus[:2], [{"/var": "fini", DONNEES: None}, {"/var": "fini", DONNEES: "fini"}])

    def test_cli__analyser_republie_meme_apres_un_arret(self):
        """Revue finale M1 : « Arrêter » (SIGTERM → SystemExit) republie quand même stockage.json."""
        with mock.patch.object(analyse, "superviser", side_effect=SystemExit(0)), \
                mock.patch.object(stockage, "ecrire", return_value=Path("x")) as ecrire, \
                mock.patch.object(analyse, "poser_arret"):
            with self.assertRaises(SystemExit):
                self.appeler(["_analyser", "/var"], jeu=lambda: None)
        ecrire.assert_called_once_with()

    def test_cli__analyser_republication_qui_echoue_ne_leve_jamais(self):
        with mock.patch.object(analyse, "superviser", side_effect=lambda *a, **k: k["apres_volume"]() or {}), \
                mock.patch.object(stockage, "ecrire", side_effect=OSError("disque plein")) as ecrire, \
                mock.patch.object(analyse, "poser_arret"):
            code, texte = self.appeler(["_analyser", "/var"], jeu=lambda: None)
        self.assertEqual(code, 0)
        self.assertEqual(ecrire.call_count, 2)                  # après le volume, puis à la fin
        self.assertIn("stockage.json non republié : disque plein", texte)


class PauseHorsDesTaches(BaseCli, BaseSuperviseur):
    """Revue finale I1 : la pause de 24 h après un arrêt à ta demande (V56/V63) et le délai de 24 h après un échec (V51)
    ne vivent pas dans les fichiers de tâches : « Effacer terminées » ne les annule pas."""

    def relances(self):
        """Les volumes que le relevé horaire (`analyser --si-perime`) lancerait maintenant."""
        run, appels = self.faux_run()
        self.appeler(["analyser", "--si-perime"], run=run, jeu=lambda: None, volumes=lambda: MONTES)
        return appels[0][appels[0].index("_analyser") + 1:] if appels else []

    def arret_manuel(self, chemin, restants):
        analyse.marqueur_arret().parent.mkdir(parents=True, exist_ok=True)
        analyse.marqueur_arret().write_text("", encoding="utf-8")
        taches.debuter("analyse", chemin, "Analyse", unite="health-hub-analyse.service")
        analyse.arreter({"id": f"analyse:{chemin}", "pid": None, "restants": restants}, tuer=mock.Mock())

    def test_arret_manuel_puis_effacer_terminees_ne_relance_pas(self):
        self.arret_manuel(DONNEES, ["/var"])
        self.assertEqual(taches.effacer_terminees(), 2)
        self.assertEqual(taches.lister(), [])
        self.assertEqual(self.relances(), ["/var/home"])

    def test_echec_puis_effacer_terminees_ne_relance_pas(self):
        lancer, _ = self.lanceur({DONNEES: ([3], None, "")})
        self.superviser([DONNEES], lancer=lancer, jeu=lambda: None)
        self.assertEqual(taches.effacer_terminees(), 1)
        self.assertEqual(self.relances(), ["/var", "/var/home"])

    def test_la_pause_dure_24_h(self):
        maintenant = datetime.now()
        self.arret_manuel(DONNEES, [])
        taches.effacer_terminees()
        self.assertFalse(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=2)))
        self.assertTrue(analyse.perime(DONNEES, maintenant=maintenant + timedelta(hours=25)))
        lancer, _ = self.lanceur({"/var": ([4], None, "")})
        self.superviser(["/var"], lancer=lancer, jeu=lambda: None)
        taches.effacer_terminees()
        self.assertFalse(analyse.perime("/var", maintenant=maintenant + timedelta(hours=2)))
        self.assertTrue(analyse.perime("/var", maintenant=maintenant + timedelta(hours=25)))

    def test_une_nouvelle_analyse_leve_la_pause(self):
        """Le bouton « Analyser » relance le volume : s'il est ensuite interrompu par un jeu, il reprend au relevé
        suivant (V15) ; s'il réussit, il suit la règle habituelle des 7 jours."""
        self.arret_manuel(DONNEES, [])
        taches.effacer_terminees()
        lancer, _ = self.lanceur({DONNEES: ([None], None, "")})
        reponses = [None, None]
        self.superviser([DONNEES], lancer=lancer, jeu=lambda: reponses.pop(0) if reponses else "jeu.exe")
        self.assertEqual(self.tache(DONNEES)["statut"], "interrompu")
        self.assertFalse(analyse.pause(DONNEES).exists())
        self.assertTrue(analyse.perime(DONNEES))
        lancer, _ = self.lanceur({DONNEES: ([0], GIO, "")})
        self.superviser([DONNEES], lancer=lancer, jeu=lambda: None)
        self.assertEqual(self.tache(DONNEES)["statut"], "fini")
        commun.ecrire_json(analyse.cache(DONNEES), {"date": commun.maintenant()})     # le résumé que l'enfant date
        self.assertFalse(analyse.perime(DONNEES))

    def test_repere_de_pause_a_cote_du_cache(self):
        self.assertEqual(analyse.pause(DONNEES), self.etat / "analyses" / "var_mnt_DONNEES.pause")
        self.assertEqual(analyse.pause("/var", "/x"), Path("/x/analyses/var.pause"))
        self.arret_manuel(DONNEES, [])
        repere = json.loads(analyse.pause(DONNEES).read_text(encoding="utf-8"))
        self.assertEqual(repere["raison"], "manuel")
        self.assertIsNotNone(datetime.fromisoformat(repere["date"]))


class Stockage(Base):
    """Les recommandations de ménage sont injectées (vides) : aucun parcours du vrai home, aucun vrai `run`."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(stockage.menage, "recommandations",
                              side_effect=AssertionError("ménage réel appelé depuis un test d'analyse"))
        p.start()
        self.addCleanup(p.stop)

    def test_stockage_sans_linstat_repli(self):
        with mock.patch.object(analyse, "LINSTAT_DIR", self.etat / "rien"), \
                mock.patch.object(analyse, "LINSTAT_CMD", self.etat / "rien" / "linstat.py"):
            s = stockage.construire(lsblk=lambda: LSBLK, volumes=lambda: VOLUMES, etat={}, recommandations=lambda: [])
        self.assertFalse(s["linstat"]["moteur"])
        self.assertIsNone(s["linstat"]["commande"])
        self.assertEqual(set(s["analyses"]), {"/var", "/var/home", DONNEES, EXTERNE})
        self.assertTrue(all(a is None for a in s["analyses"].values()))
        self.assertEqual(len(s["disques"]), 2)

    def test_stockage_avec_linstat_et_une_analyse_en_cache(self):
        commande = self.etat / "linstat.py"
        commande.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        commande.chmod(0o755)
        commun.ecrire_json(analyse.cache("/var"), {"chemin": "/var", "total": 1})
        self.addCleanup(oublier_linstat, FAUX)
        with mock.patch.object(analyse, "LINSTAT_DIR", FAUX), mock.patch.object(analyse, "LINSTAT_CMD", commande):
            s = stockage.construire(lsblk=lambda: LSBLK, volumes=lambda: VOLUMES, etat={}, recommandations=lambda: [])
        self.assertEqual(s["linstat"], {"moteur": True, "commande": str(commande)})
        self.assertEqual(s["analyses"]["/var"], {"chemin": "/var", "total": 1})
        self.assertIsNone(s["analyses"][DONNEES])

    def test_commande_non_executable(self):
        commande = self.etat / "linstat.py"
        commande.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        commande.chmod(0o644)
        with mock.patch.object(analyse, "LINSTAT_DIR", self.etat / "rien"), \
                mock.patch.object(analyse, "LINSTAT_CMD", commande):
            self.assertIsNone(analyse.etat_linstat()["commande"])

    def test_stockage_lit_les_analyses_du_meme_dossier(self):
        """V47 : construire(dossier) lit etat.json et les analyses dans ce dossier, pas dans commun.ETAT."""
        with tempfile.TemporaryDirectory() as d:
            commun.ecrire_json(analyse.cache("/var", d), {"chemin": "/var", "total": 2})
            commun.ecrire_json(analyse.cache("/var"), {"chemin": "/var", "total": 1})
            s = stockage.construire(d, lsblk=lambda: LSBLK, volumes=lambda: VOLUMES, recommandations=lambda: [],
                                    linstat=lambda: {"moteur": False, "commande": None})
        self.assertEqual(s["analyses"]["/var"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
