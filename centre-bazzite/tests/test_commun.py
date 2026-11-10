import contextlib
import json
import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import commun, steam

from tests.test_steam import ecrire_manifeste


@contextlib.contextmanager
def ordre_de_proc():
    """Comme le vrai /proc : les pid dans l'ordre croissant (un dossier temporaire n'a pas d'ordre garanti)."""
    vrai = Path.iterdir

    def trie(self):
        return iter(sorted(vrai(self), key=lambda p: (not p.name.isdigit(), int(p.name) if p.name.isdigit() else 0)))
    with mock.patch.object(Path, "iterdir", trie):
        yield


class DetectionJeu(unittest.TestCase):
    def test_est_jeu(self):
        self.assertTrue(commun.est_jeu("JeuDeCourse.ex", b"HOME=/h\0SteamGameId=480\0X=1\0"))
        self.assertTrue(commun.est_jeu("jeu-umu.exe", b"SteamGameId=umu-exemple\0"))
        env = b"SteamGameId=480\0"
        for comm in ("wineserver", "steam", "steamwebhelper", "winedevice.exe", "explorer.exe", "libfoo.so"):
            self.assertFalse(commun.est_jeu(comm, env), comm)
        self.assertFalse(commun.est_jeu("konsole", b"HOME=/h\0"))
        self.assertFalse(commun.est_jeu("jeu", b"SteamGameId=0\0"))
        self.assertFalse(commun.est_jeu("jeu", b"NotSteamGameId=12\0"))

    def test_jeu_en_cours_nom_non_utf8(self):
        """W7 : /proc/<pid>/comm est coupé à 15 octets, parfois au milieu d'un caractère : jamais d'exception."""
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(steam._NOMS, clear=True):
            proc, home = Path(d) / "proc", Path(d) / "home"       # home sans Steam : jamais le vrai
            proc.mkdir()

            def processus(pid, comm, environ):
                (proc / pid).mkdir()
                (proc / pid / "comm").write_bytes(comm)
                (proc / pid / "environ").write_bytes(environ)
            processus("12", b"\xff\xfeoutil\n", b"HOME=/h\0")
            processus("34", b"konsole\n", b"HOME=/h\0")
            (proc / "56").mkdir()                       # processus disparu entre-temps
            (proc / "self").mkdir()
            self.assertIsNone(commun.jeu_en_cours(proc, home=home))
            processus("78", b"Plateformes \xc3\n", b"SteamGameId=101\0")
            self.assertEqual(commun.jeu_en_cours(proc, home=home), "Plateformes \ufffd")


class NomDuJeu(unittest.TestCase):
    """RF-I1 : la présence d'un jeu ne change pas (elle décide du mode jeu) ; seul le nom montré change. D'abord le nom
    de l'appmanifest de SteamGameId, sinon le processus de jeu qui a pris le plus de temps processeur hors enveloppes
    (reaper, pressure-vessel…), sinon le premier processus de jeu. Noms inventés, home temporaire, faux /proc."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = Path(d.name)
        self.proc = self.tmp / "proc"
        self.proc.mkdir()
        self.home = self.tmp / "home"                     # sans Steam, sauf si le test en crée un
        self.racine = self.home / ".local" / "share" / "Steam"
        self.enterContext(mock.patch.dict(steam._NOMS, clear=True))
        self.enterContext(ordre_de_proc())

    def processus(self, pid, comm, cpu=(0, 0), environ=b"HOME=/h\0SteamGameId=101\0"):
        dossier = self.proc / str(pid)
        dossier.mkdir()
        (dossier / "comm").write_bytes(comm.encode() + b"\n")
        (dossier / "environ").write_bytes(environ)
        # /proc/<pid>/stat : utime et stime sont les champs 14 et 15 ; le nom entre parenthèses peut avoir des espaces.
        (dossier / "stat").write_text(f"{pid} ({comm}) S 1 1 1 0 -1 4194304 10 0 0 0 {cpu[0]} {cpu[1]} 0 0 20 0 4 0 100",
                                      encoding="ascii")

    def jeu(self):
        return commun.jeu_en_cours(self.proc, home=self.home)

    def test_reaper_avant_le_jeu(self):
        self.processus(10, "reaper", cpu=(1, 1))
        self.processus(20, "Jeu.exe", cpu=(500, 100))
        self.assertEqual(self.jeu(), "Jeu.exe")

    def test_le_plus_gourmand_hors_enveloppes(self):
        for pid, comm in enumerate(("reaper", "pv-adverb", "pressure-vessel", "srt-bwrap", "bwrap", "python3", "umu-run",
                                    "proton", "services.exe", "plugplay.exe", "svchost.exe", "rpcss.exe"), start=10):
            self.processus(pid, comm, cpu=(90000, 9000))
        self.processus(40, "Lanceur.exe", cpu=(50, 5))
        self.processus(41, "Jeu (final).exe", cpu=(900, 90))
        self.processus(42, "konsole", cpu=(99999, 0), environ=b"HOME=/h\0")      # pas un jeu
        self.assertEqual(self.jeu(), "Jeu (final).exe")

    def test_seulement_des_enveloppes_garde_le_premier(self):
        """Au lancement, seul reaper est là : le comportement d'avant."""
        self.processus(10, "reaper", cpu=(1, 1))
        self.processus(11, "pv-adverb", cpu=(5, 5))
        self.assertEqual(self.jeu(), "reaper")

    def test_nom_de_l_appmanifest(self):
        ecrire_manifeste(self.racine, "101", "Jeu de course")
        self.processus(10, "reaper", cpu=(1, 1))
        self.assertEqual(self.jeu(), "Jeu de course")
        self.processus(20, "Jeu.exe", cpu=(500, 100))
        self.assertEqual(self.jeu(), "Jeu de course")

    def test_appmanifest_d_une_bibliotheque_du_vdf(self):
        bib = self.tmp / "Bib"
        ecrire_manifeste(bib, "202", "Aventure")
        (self.racine / "steamapps").mkdir(parents=True)
        (self.racine / "steamapps" / "libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{bib}"\n\t}}\n}}\n', encoding="utf-8")
        self.processus(10, "reaper", environ=b"SteamGameId=202\0")
        self.assertEqual(self.jeu(), "Aventure")

    def test_manifeste_illisible_repli_sur_le_processeur(self):
        ecrire_manifeste(self.racine, "101", "Jeu de course")
        acf = self.racine / "steamapps" / "appmanifest_101.acf"
        texte = acf.read_text(encoding="utf-8")
        acf.write_text(texte[:texte.index('"InstalledDepots"')], encoding="utf-8")      # coupé
        self.processus(10, "reaper", cpu=(1, 1))
        self.processus(20, "Jeu.exe", cpu=(500, 100))
        self.assertEqual(self.jeu(), "Jeu.exe")
        acf.unlink()
        acf.mkdir()                                                                     # illisible
        steam._NOMS.clear()
        self.assertEqual(self.jeu(), "Jeu.exe")

    def test_appid_qui_n_est_pas_un_jeu_steam(self):
        """Raccourci non-Steam (appid >= 2^31), umu, appid illisible : le processus, sans lire de manifeste."""
        ecrire_manifeste(self.racine, "101", "Jeu de course")
        self.processus(20, "Jeu.exe", cpu=(500, 100), environ=b"SteamGameId=12345678901234567890\0")
        self.assertEqual(self.jeu(), "Jeu.exe")
        for environ in (b"SteamGameId=umu-exemple\0", b"SteamGameId=1\xff\0"):
            (self.proc / "20" / "environ").write_bytes(environ)
            self.assertEqual(self.jeu(), "Jeu.exe")
        self.assertEqual(steam._NOMS, {})

    def test_erreur_du_nom_jamais_d_exception_ni_d_effet_sur_la_presence(self):
        ecrire_manifeste(self.racine, "101", "Jeu de course")
        self.processus(10, "reaper", cpu=(1, 1))
        self.processus(20, "Jeu.exe", cpu=(500, 100))
        with mock.patch.object(steam, "nom_du_jeu", side_effect=RuntimeError("boum")):
            self.assertEqual(self.jeu(), "Jeu.exe")
            with mock.patch.object(commun, "_temps_processeur", side_effect=RuntimeError("boum")):
                self.assertEqual(self.jeu(), "reaper")
        with mock.patch.object(steam, "bibliotheques", side_effect=OSError("disque")):
            self.assertEqual(self.jeu(), "Jeu.exe")

    def test_presence_inchangee(self):
        """La présence (None, vide ou non vide) est exactement celle de la règle d'avant, quel que soit le nom trouvé :
        des /proc tirés au hasard, comparés à une copie de l'ancienne jeu_en_cours."""
        def avant(proc):
            for p in Path(proc).iterdir():
                if not p.name.isdigit():
                    continue
                try:
                    comm = (p / "comm").read_bytes().decode("utf-8", errors="replace")
                    if commun.est_jeu(comm, (p / "environ").read_bytes()):
                        return comm.strip()
                except (OSError, ValueError):
                    continue
            return None
        ecrire_manifeste(self.racine, "101", "Jeu de course")
        hasard = random.Random(7)
        noms = [b"reaper", b"Jeu.exe", b"konsole", b"pv-adverb", b"steam", b"wineserver", b"", b"  ", b"python3",
                b"\xff\xfe", b"Jeu \xc3"]
        environs = [b"SteamGameId=101\0", b"SteamGameId=202\0", b"SteamGameId=0\0", b"HOME=/h\0", None]
        for essai in range(80):
            proc = self.tmp / f"proc{essai}"
            proc.mkdir()
            for pid in hasard.sample(range(1, 40), hasard.randint(0, 6)):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / "comm").write_bytes(hasard.choice(noms) + b"\n")
                environ = hasard.choice(environs)
                if environ is not None:                    # sinon : processus disparu entre deux lectures
                    (proc / str(pid) / "environ").write_bytes(environ)
                if hasard.random() < 0.7:
                    (proc / str(pid) / "stat").write_text(f"{pid} (x) S 1 1 1 0 -1 0 0 0 0 0 {hasard.randint(0, 999)} 0",
                                                          encoding="ascii")
            attendu, obtenu = avant(proc), commun.jeu_en_cours(proc, home=self.home)
            with self.subTest(essai=essai, attendu=attendu, obtenu=obtenu):
                self.assertEqual((attendu is None, bool(attendu)), (obtenu is None, bool(obtenu)))

    def test_sans_jeu_aucun_nom_cherche(self):
        self.processus(10, "konsole", environ=b"HOME=/h\0")
        with mock.patch.object(steam, "nom_du_jeu") as nom:
            self.assertIsNone(self.jeu())
        nom.assert_not_called()

    def test_nom_garde_par_appid(self):
        """Le mode jeu demande le nom toutes les 5 s : l'appmanifest n'est lu qu'une fois par appid."""
        ecrire_manifeste(self.racine, "101", "Jeu de course")
        self.processus(10, "reaper")
        with mock.patch.object(steam, "_nom_manifeste", wraps=steam._nom_manifeste) as lecture:
            self.assertEqual([self.jeu() for _ in range(3)], ["Jeu de course"] * 3)
        self.assertEqual(lecture.call_count, 1)


class Json(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())

    def test_ecrire_lire_json_aller_retour(self):
        f = self.dossier / "a.json"
        donnees = {"nom": "été", "n": [1, 2, 3]}
        commun.ecrire_json(f, donnees)
        self.assertEqual(commun.lire_json(f, None), donnees)

    def test_lire_json_corrompu_renvoie_defaut(self):
        f = self.dossier / "b.json"
        f.write_text("{pas du json")
        self.assertEqual(commun.lire_json(f, {"x": 1}), {"x": 1})
        self.assertEqual(commun.lire_json(self.dossier / "absent.json", []), [])

    def test_ecrire_json_ne_laisse_pas_de_tmp(self):
        f = self.dossier / "c.json"
        commun.ecrire_json(f, {"a": 1})
        self.assertEqual([p.name for p in self.dossier.iterdir()], ["c.json"])

    def test_ecritures_concurrentes(self):
        """Plusieurs écrivains en même temps (plasmoïde, fenêtre, session, minuteur) : aucune
        exception, et un lecteur ne voit jamais de JSON invalide."""
        f = self.dossier / "etat.json"
        commun.ecrire_json(f, {"n": -1})
        erreurs, invalides, fini = [], [], threading.Event()

        def ecrivain(k):
            try:
                for i in range(300):
                    commun.ecrire_json(f, {"ecrivain": k, "n": i, "remplissage": "x" * 2000})
            except Exception as exc:
                erreurs.append(exc)

        def lecteur():
            while not fini.is_set():
                try:
                    json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    invalides.append(1)
                except OSError:
                    pass

        lecture = threading.Thread(target=lecteur)
        lecture.start()
        ecrivains = [threading.Thread(target=ecrivain, args=(k,)) for k in range(3)]
        for t in ecrivains:
            t.start()
        for t in ecrivains:
            t.join()
        fini.set()
        lecture.join()
        self.assertEqual(erreurs, [])
        self.assertEqual(invalides, [])
        self.assertEqual([p.name for p in self.dossier.iterdir()], ["etat.json"])


class Taille(unittest.TestCase):
    def test_taille_lisible(self):
        self.assertEqual(commun.taille(0), "0 Mo")
        self.assertEqual(commun.taille(500 * 1024 ** 2), "500 Mo")
        self.assertEqual(commun.taille(round(1.2 * 1024 ** 3)), "1,2 Go")
        self.assertEqual(commun.taille(239 * 1024 ** 3), "239 Go")
        self.assertEqual(commun.taille(round(3.3 * 1024 ** 4)), "3,3 To")

    def test_taille_bornes(self):
        """L'arrondi décide de l'unité et des décimales : jamais « 10,0 Go » ni « 1024 Go »."""
        gio = 1024 ** 3
        self.assertEqual(commun.taille(round(9.94 * gio)), "9,9 Go")
        self.assertEqual(commun.taille(round(9.96 * gio)), "10 Go")
        self.assertEqual(commun.taille(round(1023.4 * gio)), "1023 Go")
        self.assertEqual(commun.taille(round(1023.5 * gio)), "1,0 To")
        self.assertEqual(commun.taille(round(1023.7 * gio)), "1,0 To")
        self.assertEqual(commun.taille(round(1023.4 * 1024 ** 2)), "1023 Mo")
        self.assertEqual(commun.taille(round(1023.6 * 1024 ** 2)), "1,0 Go")
        # moitié vers le haut, comme Math.round dans la copie QML
        self.assertEqual(commun.taille(round(2.25 * gio)), "2,3 Go")
        self.assertEqual(commun.taille(round(12.5 * gio)), "13 Go")


class LireTaille(unittest.TestCase):
    """Tailles écrites par flatpak (unités décimales, comme g_format_size) ; Ruling V11."""

    def test_espace_insecable_entre_nombre_et_unite(self):
        self.assertEqual(commun.lire_taille("753.1 MB"), 753_100_000)
        self.assertEqual(commun.lire_taille("163.8 kB"), 163_800)
        self.assertEqual(commun.lire_taille("1.7 GB"), 1_700_000_000)
        self.assertEqual(commun.lire_taille("2.0 TB"), 2_000_000_000_000)

    def test_espace_ordinaire_octets_et_virgule(self):
        self.assertEqual(commun.lire_taille("3.6 kB"), 3_600)
        self.assertEqual(commun.lire_taille("12 bytes"), 12)
        self.assertEqual(commun.lire_taille("1 byte"), 1)
        self.assertEqual(commun.lire_taille("1,5 GB"), 1_500_000_000)

    def test_illisible(self):
        for texte in ("", "?", "MB", "12 parsecs", None, "1.2.3 MB"):
            self.assertIsNone(commun.lire_taille(texte), texte)


class Run(unittest.TestCase):
    def test_run(self):
        self.assertEqual(commun.run(["echo", "salut"]), (0, "salut\n"))
        self.assertEqual(commun.run(["cat"], entree="x")[1], "x")
        self.assertEqual(commun.run(["commande-inexistante-xyz"])[0], -1)


if __name__ == "__main__":
    unittest.main()
