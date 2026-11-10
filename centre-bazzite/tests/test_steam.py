"""Bibliothèques Steam : libraryfolders.vdf, appmanifests, appids installés. Home temporaire, jamais le vrai Steam ;
les échantillons sont écrits à la main (tests/echantillons/jeux/)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import steam

ECH = Path(__file__).resolve().parent / "echantillons" / "jeux"


def gabarit(nom, **valeurs):
    texte = (ECH / nom).read_text(encoding="utf-8")
    for cle, valeur in valeurs.items():
        texte = texte.replace(f"@{cle}@", str(valeur))
    return texte


def ecrire_manifeste(bib, appid, nom, taille=1073741824, partie=0, suffixe=".acf"):
    dossier = Path(bib) / "steamapps"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"appmanifest_{appid}{suffixe}").write_text(
        gabarit("appmanifest.acf", APPID=appid, NOM=nom, TAILLE=taille, PARTIE=partie), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = Path(d.name).resolve()
        self.home = self.tmp / "home"
        self.racine = self.home / ".local" / "share" / "Steam"
        (self.racine / "steamapps").mkdir(parents=True)
        self.bib1 = self.tmp / "Bib1"
        (self.bib1 / "steamapps").mkdir(parents=True)
        self.bib2 = self.tmp / "Bib2"                      # n'existe pas : un disque débranché

    def vdf(self, bib1=None, bib2=None):
        (self.racine / "steamapps" / "libraryfolders.vdf").write_text(
            gabarit("libraryfolders.vdf", BIB1=bib1 or self.bib1, BIB2=bib2 or self.bib2), encoding="utf-8")


class TestVdf(Base):
    def test_lire_vdf_libraryfolders(self):
        d = steam.lire_vdf(gabarit("libraryfolders.vdf", BIB1="/chemin/un", BIB2="/chemin/deux"))
        dossiers = d["libraryfolders"]
        self.assertEqual([dossiers["0"]["path"], dossiers["1"]["path"]], ["/chemin/un", "/chemin/deux"])
        self.assertEqual(set(dossiers["0"]["apps"]), {"101", "202", "228980"})


class TestBibliotheques(Base):
    def test_bibliotheques_dedoublonnees_et_absentes(self):
        self.vdf()
        presentes, absentes = steam.bibliotheques(self.home, en_plus=[self.bib1])
        self.assertEqual(presentes, [self.racine, self.bib1])
        self.assertEqual(absentes, [str(self.bib2)])

    def test_sans_steam_rien_et_pas_d_exception(self):
        self.assertEqual(steam.bibliotheques(self.tmp / "vide"), ([], []))

    def test_vdf_illisible_ignore(self):
        (self.racine / "steamapps" / "libraryfolders.vdf").write_bytes(b"\xff\xfe\x00{{")
        presentes, absentes = steam.bibliotheques(self.home)
        self.assertEqual((presentes, absentes), ([self.racine], []))

    def test_bibliotheque_mnt_resolue_vers_var_mnt(self):
        reel = self.tmp / "var" / "mnt" / "X"
        (reel / "steamapps").mkdir(parents=True)
        self.vdf(bib1=f"{self.tmp}/mnt/X")                 # Steam écrit /mnt, le disque est monté sous /var/mnt
        corrections = ((f"{self.tmp}/mnt/", f"{self.tmp}/var/mnt/"),)
        presentes, absentes = steam.bibliotheques(self.home, corrections=corrections)
        self.assertEqual(presentes, [self.racine, reel])
        self.assertEqual(absentes, [str(self.bib2)])

    def test_lien_symbolique_resolu(self):
        self.vdf()
        lien = self.tmp / "lien"
        lien.symlink_to(self.bib1)
        presentes, _ = steam.bibliotheques(self.home, en_plus=[lien])
        self.assertEqual(presentes, [self.racine, self.bib1])

    def test_deux_racines_une_sans_vdf(self):
        """RF-m5 : une racine Steam sans libraryfolders.vdf lisible (un reste de Steam Flatpak) ne cache plus les
        bibliothèques lues dans l'autre ; les appids installés, eux, restent incertains (mode fermé W5)."""
        self.vdf()
        flatpak = self.home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
        (flatpak / "steamapps").mkdir(parents=True)
        presentes, absentes = steam.bibliotheques(self.home)
        self.assertEqual(presentes, [self.racine, flatpak, self.bib1])
        self.assertEqual(absentes, [str(self.bib2)])
        self.assertIsNone(steam.appids_installes(presentes, home=self.home))


class TestManifestes(Base):
    def test_manifestes(self):
        ecrire_manifeste(self.bib1, "101", "Jeu de course", partie=1794300000)
        ecrire_manifeste(self.bib1, "202", "Aventure", partie=0)
        ecrire_manifeste(self.bib1, "228980", "Proton Experimental", taille=5)
        res = {m["appid"]: m for m in steam.manifestes(self.bib1)}
        self.assertEqual(set(res), {"101", "202", "228980"})
        self.assertEqual(res["101"], {"appid": "101", "nom": "Jeu de course", "installdir": "Jeu de course",
                                      "octets": 1073741824, "derniere_partie": 1794300000, "outil": False})
        self.assertIsNone(res["202"]["derniere_partie"])
        self.assertTrue(res["228980"]["outil"])

    def test_manifeste_tronque_ignore(self):
        ecrire_manifeste(self.bib1, "101", "Jeu de course")
        ecrire_manifeste(self.bib1, "202", "Aventure")
        ecrire_manifeste(self.bib1, "303", "Plateformes")
        coupe = self.bib1 / "steamapps" / "appmanifest_202.acf"
        texte = coupe.read_text(encoding="utf-8")
        coupe.write_text(texte[:texte.index('"name"') + 4], encoding="utf-8")      # coupé au milieu du nom
        tronque_tard = self.bib1 / "steamapps" / "appmanifest_303.acf"
        texte = tronque_tard.read_text(encoding="utf-8")
        tronque_tard.write_text(texte[:texte.index('"InstalledDepots"')], encoding="utf-8")   # nom lu, fin perdue
        self.assertEqual([m["appid"] for m in steam.manifestes(self.bib1)], ["101"])

    def test_manifeste_sans_appid_ignore_et_tmp_non_lu(self):
        ecrire_manifeste(self.bib1, "101", "Jeu de course")
        ecrire_manifeste(self.bib1, "404", "Énigmes", suffixe=".acf.123.tmp")
        sans = self.bib1 / "steamapps" / "appmanifest_505.acf"
        sans.write_text('"AppState"\n{\n\t"name"\t\t"Aventure"\n}\n', encoding="utf-8")
        self.assertEqual([m["appid"] for m in steam.manifestes(self.bib1)], ["101"])

    def test_bibliotheque_sans_steamapps(self):
        self.assertEqual(steam.manifestes(self.tmp / "vide"), [])


class TestNomDuJeu(Base):
    """RF-I1 : le nom d'un jeu Steam qui tourne, lu dans son appmanifest (bibliothèques présentes)."""

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.dict(steam._NOMS, clear=True))

    def test_nom_du_jeu(self):
        self.vdf()
        ecrire_manifeste(self.bib1, "202", "Aventure")
        self.assertEqual(steam.nom_du_jeu("202", self.home), "Aventure")
        self.assertIsNone(steam.nom_du_jeu("303", self.home))         # sur la bibliothèque débranchée
        for appid in ("0", "0101", "abc", "3000000000", "", None):     # pas un jeu Steam : rien n'est lu ni gardé
            self.assertIsNone(steam.nom_du_jeu(appid, self.home), appid)
        self.assertEqual(set(steam._NOMS), {(str(self.home), "202"), (str(self.home), "303")})

    def test_manifeste_d_un_autre_appid_ignore(self):
        ecrire_manifeste(self.racine, "404", "Énigmes")
        (self.racine / "steamapps" / "appmanifest_404.acf").rename(self.racine / "steamapps" / "appmanifest_505.acf")
        self.assertIsNone(steam.nom_du_jeu("505", self.home))


class TestAppidsInstalles(Base):
    def test_compte_tmp_et_downloading(self):
        ecrire_manifeste(self.bib1, "101", "Jeu de course")
        ecrire_manifeste(self.bib1, "404", "Énigmes", suffixe=".acf.123.tmp")
        (self.bib1 / "steamapps" / "downloading" / "505").mkdir(parents=True)
        (self.bib1 / "steamapps" / "downloading" / "pas-un-appid").mkdir()
        self.assertEqual(steam.appids_installes([self.bib1]), {"101", "404", "505"})

    def test_apps_du_vdf_comptent_meme_pour_une_bibliotheque_absente(self):
        self.vdf()                                          # bib1 : 101, 202, 228980 ; bib2 (absente) : 303, 606
        ecrire_manifeste(self.bib1, "707", "Plateformes")
        res = steam.appids_installes([self.racine, self.bib1], home=self.home)
        self.assertEqual(res, {"101", "202", "228980", "303", "606", "707"})

    def test_incertain_rend_none(self):
        """Mode fermé (Ruling W5) : un vdf manquant, illisible, coupé ou sans bloc, ou un steamapps illisible."""
        vdf = self.racine / "steamapps" / "libraryfolders.vdf"
        ecrire_manifeste(self.bib1, "101", "Jeu de course")
        self.assertIsNone(steam.appids_installes([self.bib1], home=self.home))      # racine sans vdf
        vdf.mkdir()
        self.assertIsNone(steam.appids_installes([self.bib1], home=self.home))      # un dossier à sa place
        vdf.rmdir()
        self.vdf()
        self.assertEqual(steam.appids_installes([self.bib1], home=self.home), {"101", "202", "228980", "303", "606"})
        texte = vdf.read_text(encoding="utf-8")
        vdf.write_text(texte[:len(texte) // 2], encoding="utf-8")                  # coupé en deux
        self.assertIsNone(steam.appids_installes([self.bib1], home=self.home))
        vdf.write_text('"autre"\n{\n}\n', encoding="utf-8")                        # sans bloc libraryfolders
        self.assertIsNone(steam.appids_installes([self.bib1], home=self.home))

    def test_vdf_coupe_apres_la_premiere_bibliotheque_rend_none(self):
        """Coupé juste après la `}` de la bibliothèque 0 : le texte finit par `}` mais les accolades ne sont pas fermées."""
        self.vdf()
        vdf = self.racine / "steamapps" / "libraryfolders.vdf"
        texte = vdf.read_text(encoding="utf-8")
        vdf.write_text(texte[:texte.index('\t"1"')], encoding="utf-8")
        self.assertTrue(vdf.read_text(encoding="utf-8").rstrip().endswith("}"))
        self.assertIsNone(steam.appids_installes([self.bib1], home=self.home))

    def test_steamapps_illisible_rend_none(self):
        self.vdf()
        with mock.patch("os.listdir", side_effect=PermissionError("non")):
            self.assertIsNone(steam.appids_installes([self.bib1], home=self.home))

    def test_sans_racine_steam_pas_d_incertitude(self):
        self.assertEqual(steam.appids_installes([self.bib1], home=self.tmp / "vide"), set())

    def test_sans_home_pas_de_vdf(self):
        self.vdf()
        self.assertEqual(steam.appids_installes([self.bib1]), set())


if __name__ == "__main__":
    unittest.main()
