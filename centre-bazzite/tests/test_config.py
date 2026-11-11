"""Configuration locale (~/.config/health-hub/config.toml) : chaque test passe son propre fichier temporaire. Absent ou
illisible, ce sont les valeurs neutres ; jamais d'exception."""
import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from centre_bazzite import config
from tests import configuration

COMPLET = """
[[volumes]]
nom = "Données"
chemin = "/var/mnt/DONNEES"
attendu = true

[[volumes]]
nom = "Externe"
chemin = "/var/mnt/EXTERNE/"
facultatif = true

[[volumes]]
nom = "Maison"
chemin = "/var/home"

[[majapps.appimages]]
cle = "emulateur"
nom = "Émulateur"
depot = "exemple/emulateur"
motif_asset = 'emulateur-.*x86_64\\.AppImage'
dossier = "~/Applications/Emulateur"
fichier = "emulateur.AppImage"
desktop = ["~/.local/share/applications/org.exemple.Emulateur.desktop", "/opt/autre.desktop"]

[[majapps.appimages]]
cle = "lanceur"
depot = "exemple/lanceur"
motif_asset = 'Lanceur-.*\\.AppImage'
dossier = "Jeux/Lanceur"
motif_fichier = "Lanceur-*-x86_64.AppImage"

[majapps.distrobox]
exclure = { build-stable = "chaîne de compilation, gardée stable" }
applis = { messagerie = ["messagerie", "Messagerie"] }

[optimiser]
recommandation = "Recommandation : A, puis C."
idee = "Ton idée : fusionner des disques."
fusionner = ["Données", "Maison"]

[optimiser.liberer]
volume = "Externe"
phrase = "Ce disque sert de réserve."
conseil = "S'il est copié ailleurs, il peut être effacé."

[resume]
contexte = "Camille, qui joue sous Bazzite"
"""


class Base(unittest.TestCase):
    def fichier(self, texte, nom="config.toml"):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        chemin = Path(d.name) / nom
        chemin.write_text(texte, encoding="utf-8")
        return chemin

    def absent(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name) / "config.toml"

    def lire_avec_stderr(self, fonction, chemin):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            valeur = fonction(chemin)
        return valeur, err.getvalue()


class Chemin(unittest.TestCase):
    def test_chemin_dans_la_config_de_l_utilisateur(self):
        """Le module tel qu'il est chargé hors des tests (tests/__init__.py remplace CHEMIN)."""
        spec = importlib.util.spec_from_file_location("config_isole", config.__file__)
        isole = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isole)
        self.assertEqual(isole.CHEMIN.relative_to(Path.home()), Path(".config/health-hub/config.toml"))


class Absent(Base):
    """Sans fichier : des valeurs neutres, aucune donnée personnelle, rien sur stderr."""

    def test_valeurs_neutres(self):
        chemin = self.absent()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual([(v.nom, v.chemin, v.attendu, v.facultatif) for v in config.volumes(chemin)],
                             [("Système", "/var", False, False), ("Home", "/var/home", False, False)])
            self.assertEqual(config.appimages(chemin), [])
            self.assertEqual(config.distrobox_exclus(chemin), {})
            self.assertEqual(config.distrobox_applis(chemin), {})
            self.assertEqual(config.optimiser(chemin),
                             {"liberer": None, "fusionner": None, "idee": "", "recommandation": None})
            self.assertEqual(config.contexte_resume(chemin), "l'utilisateur, sous Bazzite (KDE Plasma, Wayland)")
        self.assertEqual(err.getvalue(), "")

    def test_lu_a_l_appel(self):
        """CHEMIN est relu à chaque appel : le fichier peut apparaître ou changer sans redémarrer."""
        chemin = self.absent()
        self.assertEqual(config.contexte_resume(chemin), config.CONTEXTE_PAR_DEFAUT)
        chemin.write_text('[resume]\ncontexte = "Alex"\n', encoding="utf-8")
        self.assertEqual(config.contexte_resume(chemin), "Alex")

    def test_chemin_par_defaut_lu_a_l_appel(self):
        chemin = self.fichier('[resume]\ncontexte = "Alex"\n')
        ancien = config.CHEMIN
        config.CHEMIN = chemin
        self.addCleanup(setattr, config, "CHEMIN", ancien)
        self.assertEqual(config.contexte_resume(), "Alex")


class Illisible(Base):
    def test_toml_invalide_valeurs_neutres_et_avertissement(self):
        chemin = self.fichier("[[volumes]\nnom = ")
        volumes, err = self.lire_avec_stderr(config.volumes, chemin)
        self.assertEqual([v.chemin for v in volumes], ["/var", "/var/home"])
        self.assertIn(str(chemin), err)
        self.assertIn("illisible", err)

    def test_dossier_au_lieu_d_un_fichier(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        resultat, err = self.lire_avec_stderr(config.optimiser, Path(d.name))
        self.assertIsNone(resultat["liberer"])
        self.assertIn("illisible", err)

    def test_pas_de_l_utf8(self):
        chemin = self.absent()
        chemin.write_bytes(b'[resume]\ncontexte = "\xff"\n')
        resultat, err = self.lire_avec_stderr(config.contexte_resume, chemin)
        self.assertEqual(resultat, config.CONTEXTE_PAR_DEFAUT)
        self.assertIn("illisible", err)

    def test_entrees_de_mauvais_type_ignorees(self):
        """Une entrée mal formée est ignorée avec un avertissement ; les autres restent."""
        chemin = self.fichier("""
volumes = [{ nom = "Sans chemin" }, { nom = "Relatif", chemin = "mnt/x" }, "texte",
           { nom = "Bon", chemin = "/var/mnt/BON", attendu = "oui" }]
[majapps]
appimages = [{ cle = "incomplete" }, 3]
[majapps.distrobox]
exclure = { a = 1, b = "raison" }
applis = { c = "seul", d = ["p"], e = ["proc", "Nom"] }
[optimiser]
fusionner = ["Un seul"]
liberer = "Externe"
idee = 4
[resume]
contexte = ""
""")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual([(v.nom, v.chemin, v.attendu) for v in config.volumes(chemin)],
                             [("Système", "/var", False), ("Home", "/var/home", False),
                              ("Bon", "/var/mnt/BON", False)])
            self.assertEqual(config.appimages(chemin), [])
            self.assertEqual(config.distrobox_exclus(chemin), {"b": "raison"})
            self.assertEqual(config.distrobox_applis(chemin), {"e": ("proc", "Nom")})
            self.assertEqual(config.optimiser(chemin),
                             {"liberer": None, "fusionner": None, "idee": "", "recommandation": None})
            self.assertEqual(config.contexte_resume(chemin), config.CONTEXTE_PAR_DEFAUT)
        self.assertIn("ignoré", err.getvalue())

    def test_sections_d_un_autre_type(self):
        chemin = self.fichier('volumes = "x"\nmajapps = 3\noptimiser = []\nresume = "x"\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(len(config.volumes(chemin)), 2)
            self.assertEqual(config.appimages(chemin), [])
            self.assertEqual(config.distrobox_exclus(chemin), {})
            self.assertIsNone(config.optimiser(chemin)["liberer"])
            self.assertEqual(config.contexte_resume(chemin), config.CONTEXTE_PAR_DEFAUT)


class Complet(Base):
    def setUp(self):
        self.chemin = self.fichier(COMPLET)

    def test_volumes_par_defaut_puis_ceux_du_fichier(self):
        """Système et Home restent en tête ; une entrée de même chemin remplace celle par défaut (nom, drapeaux)."""
        self.assertEqual([tuple(v) for v in config.volumes(self.chemin)],
                         [("Système", "/var", False, False), ("Maison", "/var/home", False, False),
                          ("Données", "/var/mnt/DONNEES", True, False),
                          ("Externe", "/var/mnt/EXTERNE", False, True)])

    def test_appimages(self):
        a, b = config.appimages(self.chemin)
        self.assertEqual(a, {"cle": "emulateur", "nom": "Émulateur", "depot": "exemple/emulateur",
                             "motif_asset": r"emulateur-.*x86_64\.AppImage",
                             "dossier": Path.home() / "Applications/Emulateur", "fichier": "emulateur.AppImage",
                             "desktop": [Path.home() / ".local/share/applications/org.exemple.Emulateur.desktop",
                                         Path("/opt/autre.desktop")]})
        # nom par défaut : la clé ; dossier relatif : dans Home ; motif_fichier : un glob ; pas de .desktop
        self.assertEqual(b, {"cle": "lanceur", "nom": "lanceur", "depot": "exemple/lanceur",
                             "motif_asset": r"Lanceur-.*\.AppImage", "dossier": Path.home() / "Jeux/Lanceur",
                             "fichier": "Lanceur-*-x86_64.AppImage", "desktop": []})

    def test_distrobox(self):
        self.assertEqual(config.distrobox_exclus(self.chemin), {"build-stable": "chaîne de compilation, gardée stable"})
        self.assertEqual(config.distrobox_applis(self.chemin), {"messagerie": ("messagerie", "Messagerie")})

    def test_optimiser(self):
        self.assertEqual(config.optimiser(self.chemin), {
            "liberer": {"volume": "Externe", "phrase": "Ce disque sert de réserve.",
                        "conseil": "S'il est copié ailleurs, il peut être effacé."},
            "fusionner": ("Données", "Maison"), "idee": "Ton idée : fusionner des disques.",
            "recommandation": "Recommandation : A, puis C."})

    def test_optimiser_liberer_sans_phrase(self):
        chemin = self.fichier('[optimiser.liberer]\nvolume = "Externe"\n')
        self.assertEqual(config.optimiser(chemin)["liberer"], {"volume": "Externe", "phrase": "", "conseil": None})

    def test_contexte_resume(self):
        self.assertEqual(config.contexte_resume(self.chemin), "Camille, qui joue sous Bazzite")


class Securite(unittest.TestCase):
    """[securite] : dossiers temporaires ignorés (chemins absolus) et serveurs connus (noms de programmes)."""

    def lire(self, texte):
        err = io.StringIO()
        with configuration(texte), contextlib.redirect_stderr(err):
            return config.securite(), err.getvalue()

    def test_securite_absente_valeurs_neutres(self):
        res, err = self.lire("")
        self.assertEqual(res, {"temporaires_ignores": [], "serveurs_connus": []})
        self.assertEqual(err, "")

    def test_securite_lue(self):
        res, err = self.lire('[securite]\ntemporaires_ignores = ["/tmp/exemple", "~/x"]\n'
                             'serveurs_connus = ["serveur-exemple"]\n')
        self.assertEqual(res["temporaires_ignores"], [Path("/tmp/exemple"), Path.home() / "x"])
        self.assertEqual(res["serveurs_connus"], ["serveur-exemple"])
        self.assertEqual(err, "")

    def test_securite_entrees_mal_formees_ignorees(self):
        res, err = self.lire('[securite]\ntemporaires_ignores = ["relatif", 3]\nserveurs_connus = [""]\n')
        self.assertEqual(res, {"temporaires_ignores": [], "serveurs_connus": []})
        self.assertEqual(len([l for l in err.splitlines() if l.strip()]), 3)


class Exemple(unittest.TestCase):
    """config.exemple.toml (versionné) se lit sans avertissement et ne contient que des exemples génériques."""

    EXEMPLE = Path(__file__).resolve().parent.parent / "config.exemple.toml"

    def test_exemple_lisible(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            volumes = config.volumes(self.EXEMPLE)
            appimages = config.appimages(self.EXEMPLE)
            config.distrobox_exclus(self.EXEMPLE)
            config.distrobox_applis(self.EXEMPLE)
            config.optimiser(self.EXEMPLE)
            config.contexte_resume(self.EXEMPLE)
            config.securite(self.EXEMPLE)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual([v.chemin for v in volumes[:2]], ["/var", "/var/home"])
        self.assertEqual(appimages, [])         # rien n'est suivi tant qu'on ne l'a pas décommenté


if __name__ == "__main__":
    unittest.main()


INSTALL = Path(__file__).resolve().parent.parent / "install.sh"


class Installation(unittest.TestCase):
    """Le bloc d'install.sh qui pose config.exemple.toml en ~/.config/health-hub/config.toml (HOME temporaire)."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.home = Path(d.name)
        self.config = self.home / ".config" / "health-hub" / "config.toml"

    def lancer(self):
        texte = INSTALL.read_text(encoding="utf-8")
        bloc = texte.split("# debut-config\n")[1].split("# fin-config")[0]
        r = subprocess.run(["bash", "-c", f'set -euo pipefail; ici="{INSTALL.parent}"; {bloc}'],
                           capture_output=True, text=True, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_copie_l_exemple_s_il_n_y_a_pas_de_configuration(self):
        sortie = self.lancer()
        self.assertEqual(self.config.read_text(encoding="utf-8"),
                         (INSTALL.parent / "config.exemple.toml").read_text(encoding="utf-8"))
        self.assertIn(str(self.config), sortie)

    def test_jamais_d_ecrasement(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text("# la mienne\n", encoding="utf-8")
        sortie = self.lancer()
        self.assertEqual(self.config.read_text(encoding="utf-8"), "# la mienne\n")
        self.assertIn("gardée", sortie)
