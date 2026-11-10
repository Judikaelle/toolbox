import json
import tempfile
import threading
import unittest
from pathlib import Path

from centre_bazzite import commun


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
