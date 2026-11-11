import contextlib
import importlib.machinery
import importlib.util
import io
import os
import unittest

CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fenetre", "centre-bazzite-fenetre")
_chargeur = importlib.machinery.SourceFileLoader("centre_bazzite_fenetre", CHEMIN)
_spec = importlib.util.spec_from_loader("centre_bazzite_fenetre", _chargeur)
lanceur = importlib.util.module_from_spec(_spec)
_chargeur.exec_module(lanceur)


class Arguments(unittest.TestCase):
    def test_options_de_capture(self):
        a = lanceur._arguments(["--capture", "/tmp/a.png", "--etat", os.path.dirname(os.path.abspath(__file__)), "--taille", "800x600"])
        self.assertEqual(a.etat, os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(a.taille, (800, 600))

    def test_taille_invalide_refusee(self):
        with contextlib.redirect_stderr(io.StringIO()) as erreur, self.assertRaises(SystemExit):
            lanceur._arguments(["--taille", "800"])
        self.assertIn("LARGEURxHAUTEUR", erreur.getvalue())

    def test_etat_sans_capture_refuse(self):
        with contextlib.redirect_stderr(io.StringIO()) as erreur, self.assertRaises(SystemExit):
            lanceur._arguments(["--etat", "/tmp/e"])
        self.assertIn("--capture", erreur.getvalue())

    def test_etat_inexistant_refuse(self):
        with contextlib.redirect_stderr(io.StringIO()) as erreur, self.assertRaises(SystemExit):
            lanceur._arguments(["--capture", "/tmp/a.png", "--etat", "/nulle/part/absent"])
        self.assertIn("dossier", erreur.getvalue())

    def test_option_activite(self):
        self.assertTrue(lanceur._arguments(["--activite"]).activite)
        self.assertFalse(lanceur._arguments([]).activite)

    def test_page_stockage(self):
        self.assertEqual(lanceur._arguments(["--page", "stockage"]).page, "stockage")

    def test_sans_option(self):
        a = lanceur._arguments([])
        self.assertIsNone(a.etat)
        self.assertIsNone(a.taille)
        self.assertIsNone(a.onglet)
        self.assertEqual(a.page, "accueil")

    def test_onglet_de_la_page_demandee(self):
        """Task 19 : --onglet ouvre cet onglet de la page demandée (captures)."""
        a = lanceur._arguments(["--page", "stockage", "--onglet", "/var/mnt/DONNEES"])
        self.assertEqual(a.onglet, "/var/mnt/DONNEES")
        self.assertEqual(lanceur.ONGLETS["stockage"], "ongletStockage")

    def test_onglet_de_la_page_sante(self):
        a = lanceur._arguments(["--page", "sante", "--onglet", "controles"])
        self.assertEqual(a.onglet, "controles")
        self.assertEqual(lanceur.ONGLETS["sante"], "ongletSante")

    def test_page_jeux_et_ses_onglets(self):
        """Task 6 : la page Jeux, ses onglets gardés par ongletJeux, et l'aide qui les nomme."""
        a = lanceur._arguments(["--page", "jeux", "--onglet", "gels"])
        self.assertEqual((a.page, a.onglet), ("jeux", "gels"))
        self.assertEqual(lanceur.ONGLETS["jeux"], "ongletJeux")
        self.assertIn("jeux", lanceur.PAGES)
        with contextlib.redirect_stdout(io.StringIO()) as aide, self.assertRaises(SystemExit):
            lanceur._arguments(["--help"])
        for mot in ("jeux", "bibliotheques", "menage", "modejeu", "gels"):
            self.assertIn(mot, aide.getvalue())

    def test_lanceur_page_demarrage_et_onglet(self):
        """Task 3 : la page Démarrage, son onglet gardé par ongletDemarrage, et l'aide qui les nomme."""
        a = lanceur._arguments(["--page", "demarrage", "--onglet", "systeme"])
        self.assertEqual((a.page, a.onglet), ("demarrage", "systeme"))
        self.assertEqual(lanceur.ONGLETS["demarrage"], "ongletDemarrage")
        self.assertIn("demarrage", lanceur.PAGES)
        with contextlib.redirect_stdout(io.StringIO()) as aide, self.assertRaises(SystemExit):
            lanceur._arguments(["--help"])
        for mot in ("demarrage", "duree", "systeme"):
            self.assertIn(mot, aide.getvalue())

    def test_onglet_d_une_page_sans_onglets_refuse(self):
        with contextlib.redirect_stderr(io.StringIO()) as erreur, self.assertRaises(SystemExit):
            lanceur._arguments(["--onglet", "ensemble"])          # page accueil par défaut
        self.assertIn("--onglet", erreur.getvalue())


if __name__ == "__main__":
    unittest.main()
