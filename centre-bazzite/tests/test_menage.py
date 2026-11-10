"""Ménage de la page Stockage : recommandations et exécution sûre. Tout se passe dans un home temporaire avec un faux
`run` : jamais de vrai `gio trash`, jamais de vrai `flatpak uninstall`, jamais de suppression hors du dossier
temporaire. Les faux qui « jettent » un fichier vérifient d'abord qu'il est dans ce dossier. Les détecteurs (jeu,
mise à jour en cours, Steam ouvert) sont des faux aussi."""
import json
import os
import shutil
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, menage, stockage, taches

ICI = Path(__file__).resolve().parent
CONFIG_VDF = (ICI / "echantillons" / "steam-config.vdf").read_text(encoding="utf-8")
# L'âge d'un téléchargement est max(mtime, ctime), et le ctime ne se pose pas : c'est l'heure réelle de création du
# fichier de test. MAINTENANT est donc dans un an : ce ctime y paraît vieux, et seul le mtime posé par os.utime décide
# (tous les âges des tests restent sous 365 jours).
MAINTENANT = datetime.now().replace(microsecond=0) + timedelta(days=365)
KIO = 1024
NON = lambda: None  # noqa: E731

# `env LC_ALL=C flatpak uninstall --unused` (réponse « n ») : org.kde.Platform 6.10 et org.gnome.Platform 49.
UNUSED = ("\n        ID                         Branch       Op\n"
          " 1.\t   \torg.kde.Platform\t6.10\tr\n"
          " 2.\t   \torg.gnome.Platform\t49\tr\n\n"
          "Proceed with these changes to the system installation? [Y/n]: n\n")
# `env LC_ALL=C flatpak list --runtime --columns=ref,installation,size` : espace insécable avant l'unité.
LISTE_RUNTIMES = ("org.kde.Platform/x86_64/6.10\tsystem\t974.3 MB\n"
                  "org.kde.Platform/x86_64/6.11\tsystem\t1.1 GB\n"
                  "org.gnome.Platform/x86_64/49\tsystem\t1.1 GB\n"
                  "org.gnome.Platform/x86_64/50\tsystem\t1.1 GB\n"
                  "org.freedesktop.Sdk/x86_64/25.08\tsystem\t1.7 GB\n"
                  "org.freedesktop.Platform.GL.nvidia-580-95-05/x86_64/1.4\tsystem\t957.7 MB\n")
GL_580 = "runtime/org.freedesktop.Platform.GL.nvidia-580-95-05/x86_64/1.4"
CONTROLES_RUNTIMES = {"runtimes": {"inutilises": ["org.kde.Platform", "org.gnome.Platform"], "gl_obsoletes": [GL_580]}}
UNUSED_CMD = ("env", "LC_ALL=C", "flatpak", "uninstall", "--unused")
LISTE_CMD = ("env", "LC_ALL=C", "flatpak", "list")
ARCH_CMD = ("flatpak", "--default-arch")


def flatpak(unused=UNUSED, liste=LISTE_RUNTIMES, autres=None):
    return FauxRun({UNUSED_CMD: (1, unused), LISTE_CMD: (0, liste), ARCH_CMD: (0, "x86_64\n"), **(autres or {})})


class FauxRun:
    """Faux commun.run : la réponse de la plus longue clé (début de commande) qui correspond ; chaque appel est noté.
    Une réponse peut être une fonction de la commande."""

    def __init__(self, reponses=None):
        self.reponses = dict(reponses or {})
        self.appels = []

    def __call__(self, cmd, timeout=120, entree=None):
        cmd = [str(c) for c in cmd]
        self.appels.append((cmd, entree))
        for cle in sorted(self.reponses, key=len, reverse=True):
            if tuple(cmd[:len(cle)]) == cle:
                rep = self.reponses[cle]
                return rep(cmd) if callable(rep) else rep
        return 1, "commande inattendue"

    def commandes(self):
        return [c for c, _ in self.appels]


def vieillir(chemin, jours, maintenant=MAINTENANT):
    t = maintenant.timestamp() - jours * 86400
    os.utime(chemin, (t, t), follow_symlinks=False)


def fichier(chemin, octets=0, age=None):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(b"x" * octets)
    if age is not None:
        vieillir(chemin, age)
    return chemin


def par_id(recos):
    return {r["id"]: r for r in recos}


def cibles(reco):
    return [e["cible"] for e in reco["elements"]]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)

    def recos(self, run=None, controles=None, steam=NON, **kw):
        return menage.recommandations(home=self.home, maintenant=kw.pop("maintenant", MAINTENANT), run=run or FauxRun(),
                                      controles={} if controles is None else controles, steam=steam, **kw)

    def executer(self, id_, recos, run=None, jeu=NON, maj=lambda: False, steam=NON, maintenant=MAINTENANT,
                 bibliotheques=None):
        return menage.executer(id_, recos, home=self.home, maintenant=maintenant, run=run or FauxRun(), jeu=jeu,
                               maj=maj, steam=steam, bibliotheques=bibliotheques)

    def jeter(self, cmd):
        """Faux `gio trash -- <chemins>` : retire les chemins, seulement s'ils sont dans le home temporaire."""
        self.assertEqual(cmd[:3], ["gio", "trash", "--"])
        for c in cmd[3:]:
            self.assertTrue(Path(c).is_relative_to(self.home), c)
            p = Path(c)
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
        return 0, ""

    def vdf_vide(self):
        """Un libraryfolders.vdf lisible sans bibliothèque : la racine Steam du home temporaire est « vérifiable »."""
        vdf = self.home / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf"
        vdf.parent.mkdir(parents=True, exist_ok=True)
        vdf.write_text('"libraryfolders"\n{\n}\n', encoding="utf-8")

    def steam_config(self):
        self.vdf_vide()
        fichier(self.home / ".local" / "share" / "Steam" / "config" / "config.vdf").write_text(CONFIG_VDF, encoding="utf-8")

    def protons(self, octets=KIO):
        self.vdf_vide()
        compat = self.home / ".local" / "share" / "Steam" / "compatibilitytools.d"
        for nom in ("GE-Proton9-20", "GE-Proton10-25", "GE-Proton10-26"):
            fichier(compat / nom / "proton", octets)
        self.steam_config()
        return compat


class Recommandations(Base):
    def test_caches_regenerables_listes_avec_leur_taille(self):
        fichier(self.home / ".cache" / "pip" / "x", 10 * KIO)
        r = par_id(self.recos())["caches"]
        self.assertEqual((r["titre"], r["mode"]), ("Caches régénérables", "supprimer"))
        self.assertEqual(r["explication"], "Supprimés définitivement : les programmes les recréent au besoin.")
        self.assertGreaterEqual(r["octets"], 10240)
        self.assertEqual(r["taille"], commun.taille(r["octets"]))
        self.assertEqual([e["libelle"] for e in r["elements"]], ["pip"])
        self.assertEqual(r["elements"][0]["cible"], str(self.home / ".cache" / "pip"))
        self.assertIsNone(r["a_copier"])

    def test_playwright_n_est_pas_un_cache_regenerable(self):
        """Ses navigateurs ne reviennent pas seuls (il faut `npx playwright install`) : il n'est pas proposé."""
        fichier(self.home / ".cache" / "ms-playwright" / "chromium" / "chrome", 50 * KIO)
        self.assertNotIn("Playwright", [n for n, _ in menage.CACHES_REGENERABLES])
        self.assertEqual(self.recos(), [])

    def test_seules_les_recommandations_avec_des_elements(self):
        (self.home / ".cache" / "pip").mkdir(parents=True)        # vide : rien à libérer
        self.assertEqual(self.recos(), [])

    def test_cache_qui_est_un_lien_jamais_liste(self):
        with tempfile.TemporaryDirectory() as dehors:
            fichier(Path(dehors) / "gros", 50 * KIO)
            (self.home / ".cache").mkdir()
            os.symlink(dehors, self.home / ".cache" / "pip")
            self.assertNotIn("caches", par_id(self.recos()))

    def test_telechargements_anciens_seulement(self):
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", 4 * KIO, age=100)
        fichier(tel / "recent.zip", 4 * KIO, age=10)
        fichier(tel / "vieux-dossier" / "recent.txt", KIO, age=10)
        vieillir(tel / "vieux-dossier", 100)
        fichier(tel / ".directory", 10, age=200)                  # fichier caché de Dolphin : jamais proposé
        r = par_id(self.recos())["telechargements"]
        self.assertEqual((r["titre"], r["mode"]), ("Téléchargements de plus de 90 jours", "corbeille"))
        self.assertEqual(r["explication"], "Envoyés à la corbeille : tu peux encore les récupérer.")
        self.assertEqual(cibles(r), [str(vieux)])
        self.assertEqual(r["elements"][0]["libelle"], "vieux.zip")
        self.assertIsNone(r["remarque"])

    def test_age_compte_aussi_le_ctime(self):
        """Une archive extraite ou une copie qui garde ses dates paraît vieille par son mtime : son ctime, lui, dit
        qu'elle est arrivée aujourd'hui. Elle n'est pas proposée."""
        maintenant = datetime.now()
        copie = fichier(self.home / "Téléchargements" / "copie.iso", KIO)
        vieillir(copie, 400, maintenant)
        self.assertLess(os.stat(copie).st_mtime, maintenant.timestamp() - 300 * 86400)
        self.assertNotIn("telechargements", par_id(self.recos(maintenant=maintenant)))

    def test_sauvegardes_de_jeux_probables_laissees_de_cote(self):
        """V54 : ni les fichiers qui ressemblent à des sauvegardes de jeux, ni les dossiers qui en contiennent ; la
        carte dit combien sont laissés de côté."""
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", KIO, age=100)
        for nom in ("SAVE0000.co2", "SAVE0000.co2.bak", "SAVE0000.sl2", "Aventure.SRM"):
            fichier(tel / nom, KIO, age=200)
        fichier(tel / "Sauvegardes" / "slot1.sav", KIO, age=200)
        vieillir(tel / "Sauvegardes", 200)
        fichier(tel / "recent.state", KIO, age=5)                 # récente : ni proposée ni comptée
        r = par_id(self.recos())["telechargements"]
        self.assertEqual(cibles(r), [str(vieux)])
        self.assertEqual(r["remarque"], "5 sauvegardes de jeux probables sont laissées de côté.")

    def test_une_seule_sauvegarde_au_singulier(self):
        tel = self.home / "Downloads"
        fichier(tel / "vieux.zip", KIO, age=100)
        fichier(tel / "Fallout4.fos", KIO, age=100)
        r = par_id(self.recos())["telechargements"]
        self.assertEqual(r["remarque"], "Une sauvegarde de jeu probable est laissée de côté.")

    def test_est_une_sauvegarde(self):
        for nom in ("SAVE0000.co2", "save0000.CO2.bak", "x.sl2", "a.sav", "a.save", "a.srm", "a.state", "a.ess", "a.fos",
                    "a.sav.bak"):
            self.assertTrue(menage.est_sauvegarde(nom), nom)
        for nom in ("a.zip", "a.bak", "save.txt", "co2.pdf", "a.savegame.zip"):
            self.assertFalse(menage.est_sauvegarde(nom), nom)

    def illisible(self, chemin):
        """Rend un dossier illisible pour le temps du test (rétabli au nettoyage)."""
        chemin.chmod(0o000)
        self.addCleanup(chemin.chmod, 0o700)

    def test_sous_dossier_illisible_non_verifiable(self):
        """Ruling V60 : une sauvegarde cachée dans un sous-dossier illisible ne doit pas faire partir le dossier."""
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", KIO, age=100)
        fichier(tel / "Jeu" / "prive" / "SAVE0000.sl2", KIO, age=200)
        fichier(tel / "Jeu" / "lisible.txt", KIO, age=200)
        self.illisible(tel / "Jeu" / "prive")
        vieillir(tel / "Jeu", 200)
        r = par_id(self.recos())["telechargements"]
        self.assertEqual(cibles(r), [str(vieux)])
        self.assertEqual(r["remarque"], "Un élément qui ne peut pas être vérifié est laissé de côté.")

    def test_remarque_sauvegardes_et_non_verifiables(self):
        tel = self.home / "Téléchargements"
        fichier(tel / "vieux.zip", KIO, age=100)
        for nom in ("a.sl2", "b.sav"):
            fichier(tel / nom, KIO, age=100)
        for nom in ("D1", "D2"):
            fichier(tel / nom / "x" / "y", KIO, age=100)
            self.illisible(tel / nom / "x")
            vieillir(tel / nom, 100)
        r = par_id(self.recos())["telechargements"]
        self.assertEqual(r["remarque"], "2 sauvegardes de jeux probables sont laissées de côté. "
                                        "2 éléments qui ne peuvent pas être vérifiés sont laissés de côté.")

    def test_nom_non_utf8_ecarte_et_stockage_toujours_ecrivable(self):
        """Ruling V60 (h1) : un nom en octets invalides n'est jamais proposé (on ne saurait ni l'afficher ni le
        confirmer), et stockage.json s'écrit toujours."""
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", KIO, age=100)
        bizarre = os.path.join(os.fsencode(tel), b"ancien-\xff\xfe.zip")
        with open(bizarre, "wb") as f:
            f.write(b"x" * KIO)
        t = MAINTENANT.timestamp() - 200 * 86400
        os.utime(bizarre, (t, t))
        recos = self.recos()
        r = par_id(recos)["telechargements"]
        self.assertEqual(cibles(r), [str(vieux)])
        self.assertEqual(r["remarque"], "Un élément qui ne peut pas être vérifié est laissé de côté.")
        with tempfile.TemporaryDirectory() as d:
            from tests.test_stockage import ECHANTILLON, VOLUMES
            stockage.ecrire(d, lsblk=lambda: ECHANTILLON, volumes=lambda: VOLUMES, etat={},
                            analyses=lambda chemin: None, linstat=lambda: {"moteur": False, "commande": None},
                            recommandations=lambda: recos)
            self.assertEqual(commun.lire_json(Path(d) / "stockage.json", {})["recommandations"], recos)

    def test_proton_nom_non_utf8_jamais_propose(self):
        compat = self.protons()
        bizarre = os.path.join(os.fsencode(compat), b"GE-Proton9-1\xff")
        os.mkdir(bizarre)
        r = par_id(self.recos())["proton"]
        self.assertEqual([e["libelle"] for e in r["elements"]], ["GE-Proton10-25"])
        self.assertEqual(r["remarque"], "Un élément qui ne peut pas être vérifié est laissé de côté.")
        commun.ecrire_json(self.home / "essai.json", r)

    def test_vieux_dossier_entier_propose(self):
        tel = self.home / "Downloads"
        fichier(tel / "jeu" / "a.bin", 8 * KIO, age=120)
        vieillir(tel / "jeu", 120)
        r = par_id(self.recos())["telechargements"]
        self.assertEqual([e["libelle"] for e in r["elements"]], ["jeu"])
        self.assertGreaterEqual(r["octets"], 8 * KIO)

    def test_lien_dans_les_telechargements_jamais_liste(self):
        with tempfile.TemporaryDirectory() as dehors:
            cible = fichier(Path(dehors) / "ancien.iso", KIO, age=300)
            (self.home / "Téléchargements").mkdir()
            lien = self.home / "Téléchargements" / "ancien.iso"
            os.symlink(cible, lien)
            vieillir(lien, 300)
            self.assertNotIn("telechargements", par_id(self.recos()))

    def test_proton_inutilise(self):
        dossier = self.home / "compat"
        for nom in ("GE-Proton9-20", "GE-Proton10-25", "GE-Proton10-26"):
            fichier(dossier / nom / "proton", KIO)
        self.assertEqual(menage.proton_inutilises(dossier, CONFIG_VDF), [dossier / "GE-Proton10-25"])

    def test_proton_sans_compattoolmapping_rien_n_est_propose(self):
        dossier = self.home / "compat"
        for nom in ("GE-Proton9-20", "GE-Proton10-25", "GE-Proton10-26"):
            fichier(dossier / nom / "proton", KIO)
        self.assertEqual(menage.proton_inutilises(dossier, ""), [])
        self.assertEqual(menage.proton_inutilises(dossier, '"InstallConfigStore" { "Software" { } }'), [])

    def test_proton_nom_interne_utilise(self):
        """Steam associe les jeux au nom interne déclaré dans compatibilitytool.vdf, pas forcément au nom du dossier."""
        dossier = self.home / "compat"
        fichier(dossier / "GE-Proton9-20-x86_64" / "compatibilitytool.vdf").write_text(
            '"compatibilitytools" { "compat_tools" { "GE-Proton9-20" // nom interne\n { "install_path" "." } } }',
            encoding="utf-8")
        fichier(dossier / "GE-Proton10-26" / "proton", KIO)
        self.assertEqual(menage.proton_inutilises(dossier, CONFIG_VDF), [])

    def test_recommandation_proton(self):
        self.protons(3 * KIO)
        r = par_id(self.recos())["proton"]
        self.assertEqual((r["titre"], r["mode"]), ("Versions de Proton inutilisées", "supprimer"))
        self.assertEqual(r["explication"], "Supprimées définitivement ; ProtonPlus peut les réinstaller.")
        self.assertEqual([e["libelle"] for e in r["elements"]], ["GE-Proton10-25"])

    def test_proton_cite_par_heroic_garde(self):
        """Revue finale M5 : Heroic (ici en Flatpak) peut viser compatibilitytools.d."""
        self.protons()
        heroic = self.home / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic"
        fichier(heroic / "GamesConfig" / "Allium.json").write_text(json.dumps({"Allium": {"wineVersion": {
            "bin": str(self.home / ".steam/steam/compatibilitytools.d/GE-Proton10-25/proton"),
            "name": "Proton - GE-Proton10-25", "type": "proton"}}}), encoding="utf-8")
        self.assertNotIn("proton", par_id(self.recos()))

    def test_proton_cite_par_heroic_natif_garde(self):
        self.protons()
        fichier(self.home / ".config" / "heroic" / "config.json").write_text(
            '{"defaultSettings": {"wineVersion": {"name": "Proton - GE-Proton10-25"}}}', encoding="utf-8")
        self.assertNotIn("proton", par_id(self.recos()))

    def test_proton_cite_par_lutris_garde(self):
        for dossier in (self.home / ".config" / "lutris" / "games",
                        self.home / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris" / "games"):
            with self.subTest(dossier=dossier):
                compat = self.protons()
                jeu = fichier(dossier / "exemple.yml")
                jeu.write_text("game:\n  exe: Exemple.exe\nwine:\n  version: GE-Proton10-25\n", encoding="utf-8")
                self.assertNotIn("proton", par_id(self.recos()))
                jeu.unlink()
                self.assertEqual(cibles(par_id(self.recos())["proton"]), [str(compat / "GE-Proton10-25")])

    def test_proton_non_cite_par_heroic_propose(self):
        compat = self.protons()
        fichier(self.home / ".config" / "heroic" / "GamesConfig" / "Allium.json").write_text(
            '{"Allium": {"wineVersion": {"name": "GE-Proton-latest"}}}', encoding="utf-8")
        self.assertEqual(cibles(par_id(self.recos())["proton"]), [str(compat / "GE-Proton10-25")])

    def test_config_de_lanceur_illisible_garde_tout(self):
        """Une config illisible pourrait citer n'importe quelle version : aucune n'est proposée."""
        self.protons()
        (self.home / ".config" / "lutris" / "games" / "bizarre.yml").mkdir(parents=True)     # un dossier : illisible
        self.assertNotIn("proton", par_id(self.recos()))

    def test_proton_pas_propose_steam_ouvert(self):
        """Steam n'écrit config.vdf qu'à certains moments : tant qu'il tourne, un outil choisi peut sembler inutilisé."""
        self.protons()
        self.assertNotIn("proton", par_id(self.recos(steam=lambda: "steam")))

    def test_steam_ouvert_lu_dans_proc(self):
        with tempfile.TemporaryDirectory() as proc:
            for pid, nom in (("1", "systemd"), ("42", "steamwebhelper"), ("self", "python3")):
                fichier(Path(proc) / pid / "comm").write_text(nom + "\n", encoding="utf-8")
            self.assertEqual(menage.steam_ouvert(Path(proc)), "steamwebhelper")
            (Path(proc) / "42" / "comm").write_text("steam-runtime-launcher\n", encoding="utf-8")
            self.assertIsNone(menage.steam_ouvert(Path(proc)))
            (Path(proc) / "42" / "comm").write_text("steam\n", encoding="utf-8")
            self.assertEqual(menage.steam_ouvert(Path(proc)), "steam")

    def test_steam_ouvert_nom_non_utf8(self):
        """RF-m2 : comm est coupé à 15 octets, parfois au milieu d'un caractère : jamais d'exception (comme W7)."""
        with tempfile.TemporaryDirectory() as proc:
            fichier(Path(proc) / "7" / "comm").write_bytes(b"\xff\xfeoutil \xc3\n")
            fichier(Path(proc) / "42" / "comm").write_text("konsole\n", encoding="utf-8")
            self.assertIsNone(menage.steam_ouvert(Path(proc)))
            (Path(proc) / "42" / "comm").write_text("steam\n", encoding="utf-8")
            self.assertEqual(menage.steam_ouvert(Path(proc)), "steam")

    def test_prefixes_proton_jamais_proposes(self):
        self.vdf_vide()
        compatdata = self.home / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
        fichier(compatdata / "123" / "pfx" / "user.reg", 10 * KIO, age=300)
        vieillir(compatdata / "123", 300)
        toutes = [c for r in self.recos() for c in cibles(r)]
        self.assertFalse([c for c in toutes if "compatdata" in c])

    def test_journal_commande_a_copier(self):
        r = par_id(self.recos(controles={"caches": {"journal": int(1.5 * 1024 ** 3)}}))["journal"]
        self.assertEqual((r["titre"], r["mode"]), ("Journal système", "copier"))
        self.assertEqual(r["a_copier"], "sudo journalctl --vacuum-size=500M")
        self.assertEqual(r["explication"],
                         "Commande à lancer toi-même dans un terminal (elle demande ton mot de passe).")
        self.assertEqual(r["octets"], int(1.5 * 1024 ** 3) - 500 * 1024 ** 2)   # ce que garde --vacuum-size=500M

    def test_petit_journal_pas_de_recommandation(self):
        self.assertNotIn("journal", par_id(self.recos(controles={"caches": {"journal": 561197875}})))

    def test_runtimes_depuis_les_controles(self):
        faux = flatpak()
        r = par_id(self.recos(run=faux, controles=CONTROLES_RUNTIMES))["runtimes"]
        self.assertEqual((r["titre"], r["mode"]), ("Runtimes Flatpak inutilisés", "commande"))
        self.assertEqual(r["explication"], "Désinstallés : seulement ceux listés ici, s'ils sont toujours inutilisés.")
        # La branche et l'arch viennent des listes réelles : 6.11 et 50, installés aussi, ne sont jamais proposés.
        self.assertEqual(cibles(r), ["runtime/org.gnome.Platform/x86_64/49", "runtime/org.kde.Platform/x86_64/6.10"])
        self.assertEqual([e["libelle"] for e in r["elements"]], ["org.gnome.Platform 49 (x86_64)", "org.kde.Platform 6.10 (x86_64)"])
        self.assertEqual([e["octets"] for e in r["elements"]], [1_100_000_000, 974_300_000])
        self.assertEqual(r["octets"], 2_074_300_000)
        # Le pilote GL épinglé n'est pas désinstallé par Health Hub : sa commande est à copier.
        self.assertEqual(r["a_copier"], "flatpak uninstall " + GL_580)
        self.assertIn((list(UNUSED_CMD), "n\n"), faux.appels)
        self.assertEqual([c for c in faux.commandes() if "flatpak" in c],
                         [list(UNUSED_CMD), ["flatpak", "--default-arch"],
                          ["env", "LC_ALL=C", "flatpak", "list", "--runtime", "--columns=ref,installation,size"]])

    def test_runtimes_arch_de_la_liste_par_defaut(self):
        """Sans colonne Arch, flatpak ne liste que l'arch par défaut : la même branche en i386 n'est pas prise."""
        liste = LISTE_RUNTIMES + "org.kde.Platform/i386/6.10\tsystem\t500.0 MB\n"
        r = par_id(self.recos(run=flatpak(liste=liste), controles=CONTROLES_RUNTIMES))["runtimes"]
        self.assertNotIn("runtime/org.kde.Platform/i386/6.10", cibles(r))
        self.assertIn("runtime/org.kde.Platform/x86_64/6.10", cibles(r))

    def test_runtimes_colonne_arch(self):
        unused = ("\n        ID                     Arch      Branch       Op\n"
                  " 1.\t   \torg.kde.Platform\ti386\t6.10\tr\n\n"
                  "Proceed with these changes to the system installation? [Y/n]: n\n")
        liste = LISTE_RUNTIMES + "org.kde.Platform/i386/6.10\tsystem\t500.0 MB\n"
        faux = flatpak(unused=unused, liste=liste)
        r = par_id(self.recos(run=faux, controles=CONTROLES_RUNTIMES))["runtimes"]
        self.assertEqual(cibles(r), ["runtime/org.kde.Platform/i386/6.10"])
        self.assertEqual(r["elements"][0]["libelle"], "org.kde.Platform 6.10 (i386)")
        self.assertNotIn(["flatpak", "--default-arch"], faux.commandes())

    def test_runtime_installe_deux_fois_pas_propose(self):
        """La même ref dans l'installation système et dans celle de l'utilisateur : on ne sait pas laquelle est
        inutilisée, rien n'est proposé pour elle."""
        liste = LISTE_RUNTIMES + "org.kde.Platform/x86_64/6.10\tuser\t974.3 MB\n"
        r = par_id(self.recos(run=flatpak(liste=liste), controles=CONTROLES_RUNTIMES))["runtimes"]
        self.assertEqual(cibles(r), ["runtime/org.gnome.Platform/x86_64/49"])

    def test_gl_obsolete_deja_desepingle_est_un_element(self):
        unused = UNUSED.replace(" 2.", " 3.\t   \torg.freedesktop.Platform.GL.nvidia-580-95-05\t1.4\tr\n 2.")
        r = par_id(self.recos(run=flatpak(unused=unused), controles=CONTROLES_RUNTIMES))["runtimes"]
        self.assertIn(GL_580, cibles(r))
        self.assertIsNone(r["a_copier"])

    def test_runtimes_rien_a_signaler_aucune_commande(self):
        for controles in ({"runtimes": {"inutilises": [], "gl_obsoletes": []}}, {"runtimes": None}, {}):
            faux = FauxRun()
            self.assertNotIn("runtimes", par_id(self.recos(run=faux, controles=controles)))
            self.assertFalse([c for c in faux.commandes() if "flatpak" in c], controles)

    def test_recommandations_ne_desinstallent_ni_ne_jettent_rien(self):
        faux = flatpak(autres={("gio", "trash", "--list"): (0, "trash:///a.txt\t/x/a.txt\n")})
        self.recos(run=faux, controles=CONTROLES_RUNTIMES)
        for cmd, _ in faux.appels:
            self.assertNotIn("-y", cmd)
            self.assertNotIn("--noninteractive", cmd)
            self.assertNotIn("--empty", cmd)
            if cmd[:2] == ["gio", "trash"]:
                self.assertEqual(cmd, ["gio", "trash", "--list"])

    def test_corbeille_listee_par_gio(self):
        fichier(self.home / ".local" / "share" / "Trash" / "files" / "photo.jpg", 20 * KIO)
        faux = FauxRun({("gio", "trash", "--list"): (0, "trash:///photo.jpg\t/var/home/bazzite/Images/photo.jpg\n")})
        r = par_id(self.recos(run=faux))["corbeille"]
        self.assertEqual((r["titre"], r["mode"]), ("Corbeille", "corbeille"))
        self.assertEqual(r["explication"], "Vidée définitivement, sur tous les disques.")
        self.assertEqual([(e["cible"], e["libelle"]) for e in r["elements"]],
                         [("trash:///photo.jpg", "/var/home/bazzite/Images/photo.jpg")])
        self.assertGreaterEqual(r["octets"], 20 * KIO)

    def test_corbeille_d_un_autre_disque_mesuree(self):
        """gvfs nomme un élément d'un autre disque par son chemin complet, « \\ » à la place de « / »."""
        dans_la_corbeille = fichier(self.home / "disque" / ".Trash-1000" / "files" / "jeu.iso", 12 * KIO)
        uri = "trash:///" + urllib.parse.quote(str(dans_la_corbeille).replace("/", "\\"))
        faux = FauxRun({("gio", "trash", "--list"): (0, f"{uri}\t/var/mnt/DONNEES/jeu.iso\n")})
        r = par_id(self.recos(run=faux))["corbeille"]
        self.assertGreaterEqual(r["elements"][0]["octets"], 12 * KIO)

    def test_corbeille_vide_pas_de_recommandation(self):
        self.assertNotIn("corbeille", par_id(self.recos(run=FauxRun({("gio", "trash", "--list"): (0, "")}))))

    def test_ordre_des_recommandations(self):
        fichier(self.home / ".cache" / "pip" / "x", KIO)
        fichier(self.home / "Téléchargements" / "v.zip", KIO, age=100)
        faux = FauxRun({("gio", "trash", "--list"): (0, "trash:///a\t/x/a\n")})
        ids = [r["id"] for r in self.recos(run=faux, controles={"caches": {"journal": 2 * 1024 ** 3}})]
        self.assertEqual(ids, ["caches", "corbeille", "telechargements", "journal"])

    def test_une_recommandation_en_panne_n_empeche_pas_les_autres(self):
        fichier(self.home / ".cache" / "pip" / "x", KIO)
        with mock.patch("sys.stderr"):
            ids = [r["id"] for r in self.recos(run=lambda *a, **k: 1 / 0)]
        self.assertEqual(ids, ["caches"])

    def test_empreinte_des_elements_montres(self):
        """Ruling V60 : l'empreinte porte sur la cible, le libellé et la taille de chaque élément, dans l'ordre."""
        a = {"cible": "/a", "libelle": "a", "octets": 10, "taille": "0 Mo"}
        b = {"cible": "/b", "libelle": "b", "octets": 20, "taille": "0 Mo"}
        self.assertEqual(menage.empreinte([a, b]), menage.empreinte([dict(a), dict(b)]))
        self.assertNotEqual(menage.empreinte([a, b]), menage.empreinte([a]))
        self.assertNotEqual(menage.empreinte([a, b]), menage.empreinte([b, a]))
        self.assertNotEqual(menage.empreinte([a]), menage.empreinte([dict(a, octets=11)]))
        self.assertNotEqual(menage.empreinte([a]), menage.empreinte([dict(a, libelle="autre")]))
        # La fenêtre rend les tailles en nombres JavaScript (flottants) : même empreinte.
        self.assertEqual(menage.empreinte([a]), menage.empreinte([dict(a, octets=10.0)]))
        self.assertRegex(menage.empreinte([]), r"^[0-9a-f]{16}$")


class Executer(Base):
    def test_menage_ne_touche_que_ce_qui_a_ete_montre(self):
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", KIO, age=100)
        recos = self.recos()
        self.assertEqual(cibles(par_id(recos)["telechargements"]), [str(vieux)])
        vieillir(vieux, 0)                                          # retouché depuis l'affichage
        nouveau = fichier(tel / "nouveau.zip", KIO, age=100)       # apparu depuis : jamais montré
        faux = FauxRun({("gio", "trash"): self.jeter})
        res = self.executer("telechargements", recos, run=faux)
        self.assertFalse([c for c in faux.commandes() if str(vieux) in c or str(nouveau) in c])
        self.assertEqual(res["ignores"], [{"cible": str(vieux), "raison": "modifié depuis"}])
        self.assertEqual(res["faits"], [])
        self.assertTrue(vieux.exists() and nouveau.exists())

    def test_revérification_compte_le_ctime(self):
        maintenant = datetime.now()
        copie = fichier(self.home / "Téléchargements" / "copie.iso", KIO)
        vieillir(copie, 400, maintenant)
        recos = [{"id": "telechargements", "elements": [{"cible": str(copie)}]}]
        res = self.executer("telechargements", recos, run=FauxRun({("gio", "trash"): self.jeter}), maintenant=maintenant)
        self.assertEqual(res["ignores"], [{"cible": str(copie), "raison": "modifié depuis"}])
        self.assertTrue(copie.exists())

    def test_sauvegarde_jamais_jetee_meme_si_listee(self):
        """Un stockage.json écrit avant V54 pourrait lister une sauvegarde : elle est écartée à la revérification."""
        tel = self.home / "Téléchargements"
        save = fichier(tel / "SAVE0000.co2", KIO, age=200)
        dossier = fichier(tel / "Jeu" / "slot.sl2", KIO, age=200).parent
        vieillir(dossier, 200)
        recos = [{"id": "telechargements", "elements": [{"cible": str(save)}, {"cible": str(dossier)}]}]
        faux = FauxRun({("gio", "trash"): self.jeter})
        res = self.executer("telechargements", recos, run=faux)
        self.assertEqual({i["raison"] for i in res["ignores"]}, {"sauvegarde de jeu probable"})
        self.assertEqual(faux.appels, [])
        self.assertTrue(save.exists() and dossier.exists())

    def test_revérification_non_verifiable_refusee(self):
        tel = self.home / "Téléchargements"
        jeu = fichier(tel / "Jeu" / "prive" / "a.txt", KIO, age=200).parent.parent
        fichier(tel / "Jeu" / "b.txt", KIO, age=200)
        vieillir(jeu, 200)
        recos = self.recos()
        self.assertEqual(cibles(par_id(recos)["telechargements"]), [str(jeu)])
        prive = jeu / "prive"
        prive.chmod(0o000)
        self.addCleanup(prive.chmod, 0o700)
        faux = FauxRun({("gio", "trash"): self.jeter})
        res = self.executer("telechargements", recos, run=faux)
        self.assertEqual(res["ignores"], [{"cible": str(jeu), "raison": "non vérifiable"}])
        self.assertEqual(faux.appels, [])
        self.assertTrue(jeu.exists())

    def test_nom_illisible_refuse_a_l_execution(self):
        """Un stockage.json fabriqué à la main pourrait porter un nom non UTF-8 (« \\udcff ») : jamais traité."""
        tel = self.home / "Téléchargements"
        bizarre = os.path.join(os.fsencode(tel), b"ancien-\xff.zip")
        os.makedirs(os.fsencode(tel), exist_ok=True)
        with open(bizarre, "wb") as f:
            f.write(b"x")
        t = MAINTENANT.timestamp() - 200 * 86400
        os.utime(bizarre, (t, t))
        cible = os.fsdecode(bizarre)
        faux = FauxRun({("gio", "trash"): self.jeter})
        res = self.executer("telechargements", [{"id": "telechargements", "elements": [{"cible": cible}]}], run=faux)
        self.assertEqual(res["ignores"], [{"cible": cible, "raison": "nom illisible"}])
        self.assertEqual(faux.appels, [])
        self.assertTrue(os.path.exists(bizarre))

    def test_lien_hors_racine_refuse(self):
        pip = self.home / ".cache" / "pip"
        fichier(pip / "x", 10 * KIO)
        recos = self.recos()
        with tempfile.TemporaryDirectory() as dehors:
            precieux = fichier(Path(dehors) / "precieux.txt", KIO)
            shutil.rmtree(pip)
            os.symlink(dehors, pip)
            res = self.executer("caches", recos)
            self.assertEqual(res["ignores"], [{"cible": str(pip), "raison": "lien symbolique"}])
            self.assertTrue(precieux.exists())
            self.assertEqual(res["liberes"], 0)

    def test_caches_vides_le_contenu_garde_le_dossier(self):
        pip, npm = self.home / ".cache" / "pip", self.home / ".npm" / "_cacache"
        fichier(pip / "http" / "a", 5 * KIO)
        fichier(pip / "b", 5 * KIO)
        fichier(npm / "c", 5 * KIO)
        autre = fichier(self.home / ".cache" / "autre" / "z", KIO)
        recos = self.recos()
        res = self.executer("caches", recos)
        self.assertTrue(pip.is_dir() and npm.is_dir())
        self.assertEqual((list(pip.iterdir()), list(npm.iterdir())), ([], []))
        self.assertTrue(autre.exists())
        self.assertEqual(sorted(res["faits"]), sorted([str(pip), str(npm)]))
        self.assertGreaterEqual(res["liberes"], 15 * KIO)
        self.assertIsNone(res["erreur"])

    def test_cache_en_partie_impossible_a_supprimer_est_rapporte(self):
        """Un sous-dossier protégé : ce qui a pu partir est compté, le cache est noté « suppression impossible »."""
        pip = self.home / ".cache" / "pip"
        fichier(pip / "libre" / "a", 8 * KIO)
        protege = fichier(pip / "protege" / "b", KIO).parent
        protege.chmod(0o500)
        self.addCleanup(protege.chmod, 0o700)
        res = self.executer("caches", self.recos())
        self.assertEqual(res["ignores"], [{"cible": str(pip), "raison": "suppression impossible"}])
        self.assertEqual(res["faits"], [])
        self.assertGreaterEqual(res["liberes"], 8 * KIO)
        self.assertFalse((pip / "libre").exists())
        self.assertTrue((protege / "b").exists())

    def test_dossier_parent_devenu_lien_hors_de_son_dossier(self):
        """~/.cache remplacé par un lien vers un autre dossier qui a lui aussi un pip/ : rien n'y est touché."""
        fichier(self.home / ".cache" / "pip" / "x", KIO)
        recos = self.recos()
        with tempfile.TemporaryDirectory() as dehors:
            precieux = fichier(Path(dehors) / "pip" / "precieux.txt", KIO)
            shutil.rmtree(self.home / ".cache")
            os.symlink(dehors, self.home / ".cache")
            res = self.executer("caches", recos)
            self.assertEqual(res["ignores"], [{"cible": str(self.home / ".cache" / "pip"), "raison": "hors de son dossier"}])
            self.assertTrue(precieux.exists())
            self.assertNotIn("caches", par_id(self.recos()))

    def test_vider_verifie_le_dossier_reellement_ouvert(self):
        """Dernier rempart contre un remplacement entre la revérification et l'action : le realpath est relu sur le
        descripteur ouvert, et rien n'est supprimé s'il n'est pas une racine permise."""
        with tempfile.TemporaryDirectory() as dehors:
            precieux = fichier(Path(dehors) / "pip" / "precieux.txt", KIO)
            permis = {menage._racine(self.home, "~/.cache/pip")}
            self.assertEqual(menage._vider(Path(dehors) / "pip", permis), "hors de son dossier")
            self.assertTrue(precieux.exists())

    def test_cache_vide_ne_suit_pas_un_lien_interne(self):
        pip = self.home / ".cache" / "pip"
        fichier(pip / "x", KIO)
        recos = self.recos()
        with tempfile.TemporaryDirectory() as dehors:
            precieux = fichier(Path(dehors) / "sous" / "precieux.txt", KIO)
            os.symlink(Path(dehors) / "sous", pip / "lien")
            self.executer("caches", recos)
            self.assertTrue(precieux.exists())
            self.assertEqual(list(pip.iterdir()), [])

    def corbeille(self, listes, octets=20 * KIO):
        fichier(self.home / ".local" / "share" / "Trash" / "files" / "photo.jpg", octets)
        listes = iter(listes)
        return FauxRun({("gio", "trash", "--list"): lambda cmd: (0, next(listes)),
                        ("gio", "trash", "--empty"): (0, "")})

    def test_corbeille_videe_par_gio(self):
        faux = self.corbeille(["trash:///photo.jpg\t/x/photo.jpg\n"] * 2)
        recos = self.recos(run=faux)
        res = self.executer("corbeille", recos, run=faux)
        self.assertIn(["gio", "trash", "--empty"], faux.commandes())
        self.assertEqual(res["faits"], ["trash:///photo.jpg"])
        self.assertGreaterEqual(res["liberes"], 20 * KIO)
        self.assertIsNone(res["erreur"])

    def test_corbeille_modifiee_depuis_refusee(self):
        """Ruling V10 : la corbeille relue diffère de celle montrée -> rien n'est vidé."""
        faux = self.corbeille(["trash:///photo.jpg\t/x/photo.jpg\n",
                               "trash:///photo.jpg\t/x/photo.jpg\ntrash:///rapport.pdf\t/x/rapport.pdf\n"])
        recos = self.recos(run=faux)
        res = self.executer("corbeille", recos, run=faux)
        self.assertNotIn(["gio", "trash", "--empty"], faux.commandes())
        self.assertEqual(res["ignores"], [{"cible": "trash:///photo.jpg", "raison": "modifié depuis"}])
        self.assertEqual(res["faits"], [])
        self.assertTrue(res["erreur"])

    def test_corbeille_homonyme_de_taille_differente_refusee(self):
        """Même URI, autre fichier (jeté de nouveau sous le même nom, plus gros) : rien n'est vidé."""
        faux = self.corbeille(["trash:///photo.jpg\t/x/photo.jpg\n"] * 2)
        recos = self.recos(run=faux)
        fichier(self.home / ".local" / "share" / "Trash" / "files" / "photo.jpg", 400 * KIO)
        res = self.executer("corbeille", recos, run=faux)
        self.assertNotIn(["gio", "trash", "--empty"], faux.commandes())
        self.assertEqual(res["ignores"], [{"cible": "trash:///photo.jpg", "raison": "modifié depuis"}])

    def test_corbeille_homonyme_d_une_autre_origine_refusee(self):
        faux = self.corbeille(["trash:///photo.jpg\t/x/photo.jpg\n", "trash:///photo.jpg\t/y/autre/photo.jpg\n"])
        res = self.executer("corbeille", self.recos(run=faux), run=faux)
        self.assertNotIn(["gio", "trash", "--empty"], faux.commandes())
        self.assertTrue(res["erreur"])

    def test_telechargements_envoyes_a_la_corbeille(self):
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", 4 * KIO, age=100)
        garde = fichier(tel / "recent.zip", KIO, age=5)
        faux = FauxRun({("gio", "trash"): self.jeter})
        res = self.executer("telechargements", self.recos(), run=faux)
        self.assertEqual(faux.commandes(), [["gio", "trash", "--", str(vieux)]])
        self.assertEqual(res["faits"], [str(vieux)])
        self.assertGreaterEqual(res["liberes"], 4 * KIO)
        self.assertTrue(garde.exists())

    def test_telechargement_refuse_par_la_corbeille_rapporte(self):
        vieux = fichier(self.home / "Téléchargements" / "vieux.zip", KIO, age=100)
        res = self.executer("telechargements", self.recos(), run=FauxRun({("gio", "trash"): (1, "Permission refusée")}))
        self.assertEqual(res["ignores"], [{"cible": str(vieux), "raison": "suppression impossible"}])
        self.assertTrue(res["erreur"])

    def test_element_disparu(self):
        vieux = fichier(self.home / "Téléchargements" / "vieux.zip", KIO, age=100)
        recos = self.recos()
        vieux.unlink()
        res = self.executer("telechargements", recos, run=FauxRun({("gio", "trash"): self.jeter}))
        self.assertEqual(res["ignores"], [{"cible": str(vieux), "raison": "disparu"}])

    def test_cibles_hors_de_leur_dossier_refusees(self):
        documents = fichier(self.home / "Documents" / "x.zip", KIO, age=300)
        proton = fichier(self.home / "ailleurs" / "GE-Proton1-1" / "proton", KIO).parent
        detour = self.home / "Téléchargements" / ".." / "Documents" / "x.zip"
        (self.home / "Téléchargements").mkdir()
        self.steam_config()
        recos = [{"id": "caches", "elements": [{"cible": str(self.home / "Documents")}]},
                 {"id": "telechargements", "elements": [{"cible": str(documents)}, {"cible": str(detour)}]},
                 {"id": "proton", "elements": [{"cible": str(proton)}]}]
        faux = FauxRun({("gio", "trash"): self.jeter})
        for id_ in ("caches", "telechargements", "proton"):
            res = self.executer(id_, recos, run=faux)
            self.assertTrue(res["ignores"], id_)
            self.assertEqual({i["raison"] for i in res["ignores"]}, {"hors de son dossier"}, id_)
            self.assertEqual(res["faits"], [], id_)
        self.assertEqual(faux.appels, [])
        self.assertTrue(documents.exists() and proton.exists())

    def test_lien_dans_les_telechargements_refuse(self):
        with tempfile.TemporaryDirectory() as dehors:
            cible = fichier(Path(dehors) / "ancien.iso", KIO, age=300)
            (self.home / "Téléchargements").mkdir()
            lien = self.home / "Téléchargements" / "ancien.iso"
            os.symlink(cible, lien)
            faux = FauxRun({("gio", "trash"): self.jeter})
            res = self.executer("telechargements", [{"id": "telechargements", "elements": [{"cible": str(lien)}]}],
                                run=faux)
            self.assertEqual(res["ignores"], [{"cible": str(lien), "raison": "lien symbolique"}])
            self.assertEqual(faux.appels, [])
            self.assertTrue(cible.exists())

    def test_proton_supprime(self):
        compat = self.protons(3 * KIO)
        faux = FauxRun()
        res = self.executer("proton", self.recos(), run=faux)
        self.assertFalse((compat / "GE-Proton10-25").exists())
        self.assertTrue((compat / "GE-Proton9-20").exists() and (compat / "GE-Proton10-26").exists())
        self.assertEqual(res["faits"], [str(compat / "GE-Proton10-25")])
        self.assertGreaterEqual(res["liberes"], 3 * KIO)
        self.assertEqual(faux.appels, [])

    def test_proton_refuse_steam_ouvert(self):
        compat = self.protons()
        recos = self.recos()
        res = self.executer("proton", recos, steam=lambda: "steam")
        self.assertEqual(res["erreur"], "Steam est ouvert : ferme-le pour retirer des versions de Proton.")
        self.assertTrue((compat / "GE-Proton10-25").exists())
        self.assertEqual(res["faits"], [])

    def test_steam_ouvert_n_empeche_pas_les_autres_menages(self):
        fichier(self.home / ".cache" / "pip" / "x", KIO)
        res = self.executer("caches", self.recos(), steam=lambda: "steam")
        self.assertIsNone(res["erreur"])
        self.assertTrue(res["faits"])

    def test_proton_utilise_maintenant_garde(self):
        compat = self.protons()
        config = self.home / ".local" / "share" / "Steam" / "config" / "config.vdf"
        recos = self.recos()
        config.write_text(CONFIG_VDF.replace('"name"\t\t"proton_experimental"', '"name"\t\t"GE-Proton10-25"'),
                          encoding="utf-8")
        res = self.executer("proton", recos)
        self.assertEqual(res["ignores"], [{"cible": str(compat / "GE-Proton10-25"), "raison": "utilisé maintenant"}])
        self.assertTrue((compat / "GE-Proton10-25").exists())

    def test_proton_cite_par_lutris_depuis_l_affichage_garde(self):
        """La revérification au moment d'agir voit aussi Heroic et Lutris (revue finale M5)."""
        compat = self.protons()
        recos = self.recos()
        fichier(self.home / ".config" / "lutris" / "games" / "jeu.yml").write_text("wine:\n  version: GE-Proton10-25\n",
                                                                                  encoding="utf-8")
        res = self.executer("proton", recos)
        self.assertEqual(res["ignores"], [{"cible": str(compat / "GE-Proton10-25"), "raison": "utilisé maintenant"}])
        self.assertTrue((compat / "GE-Proton10-25").exists())

    def test_proton_impossible_a_supprimer_rapporte(self):
        compat = self.protons()
        cible = compat / "GE-Proton10-25"
        recos = self.recos()
        compat.chmod(0o500)                       # le dossier parent protégé : rmtree ne peut rien retirer
        self.addCleanup(compat.chmod, 0o700)
        res = self.executer("proton", recos)
        self.assertEqual(res["ignores"], [{"cible": str(cible), "raison": "suppression impossible"}])
        self.assertTrue(cible.exists())

    def test_runtimes_seulement_ceux_montres_et_toujours_inutilises(self):
        """Ruling V11 : relit la liste « inutilisés » ; désinstalle les refs montrées qui y sont encore, jamais
        une ref apparue depuis, jamais --unused ; l'installation est précisée."""
        recos = self.recos(run=flatpak(), controles=CONTROLES_RUNTIMES)
        # Depuis : org.gnome.Platform 49 sert de nouveau, org.freedesktop.Sdk 25.08 est devenu inutilisé.
        faux2 = flatpak(unused=UNUSED.replace("org.gnome.Platform\t49", "org.freedesktop.Sdk\t25.08"),
                        autres={("flatpak", "uninstall"): (0, "")})
        res = self.executer("runtimes", recos, run=faux2)
        desinstallations = [c for c in faux2.commandes() if c[:2] == ["flatpak", "uninstall"]]
        self.assertEqual(desinstallations, [["flatpak", "uninstall", "--system", "-y", "--noninteractive",
                                             "runtime/org.kde.Platform/x86_64/6.10"]])
        self.assertEqual(res["ignores"], [{"cible": "runtime/org.gnome.Platform/x86_64/49", "raison": "utilisé maintenant"}])
        self.assertEqual(res["faits"], ["runtime/org.kde.Platform/x86_64/6.10"])
        self.assertEqual(res["liberes"], 974_300_000)
        self.assertIn((list(UNUSED_CMD), "n\n"), faux2.appels)

    def test_runtimes_par_installation(self):
        unused = UNUSED
        liste = LISTE_RUNTIMES.replace("org.gnome.Platform/x86_64/49\tsystem", "org.gnome.Platform/x86_64/49\tuser")
        recos = self.recos(run=flatpak(unused=unused, liste=liste), controles=CONTROLES_RUNTIMES)
        faux2 = flatpak(unused=unused, liste=liste, autres={("flatpak", "uninstall"): (0, "")})
        res = self.executer("runtimes", recos, run=faux2)
        desinstallations = sorted(c for c in faux2.commandes() if c[:2] == ["flatpak", "uninstall"])
        self.assertEqual(desinstallations, [
            ["flatpak", "uninstall", "--system", "-y", "--noninteractive", "runtime/org.kde.Platform/x86_64/6.10"],
            ["flatpak", "uninstall", "--user", "-y", "--noninteractive", "runtime/org.gnome.Platform/x86_64/49"]])
        self.assertEqual(sorted(res["faits"]), sorted(cibles(par_id(recos)["runtimes"])))

    def test_runtimes_arch_differente_utilisee_maintenant(self):
        recos = [{"id": "runtimes", "elements": [{"cible": "runtime/org.kde.Platform/i386/6.10"}]}]
        liste = LISTE_RUNTIMES + "org.kde.Platform/i386/6.10\tsystem\t500.0 MB\n"
        faux = flatpak(liste=liste, autres={("flatpak", "uninstall"): (0, "")})
        res = self.executer("runtimes", recos, run=faux)
        self.assertEqual(res["ignores"], [{"cible": "runtime/org.kde.Platform/i386/6.10", "raison": "utilisé maintenant"}])
        self.assertFalse([c for c in faux.commandes() if c[:2] == ["flatpak", "uninstall"]])

    def test_runtimes_liste_illisible_rien_n_est_desinstalle(self):
        recos = self.recos(run=flatpak(), controles=CONTROLES_RUNTIMES)
        faux2 = FauxRun({UNUSED_CMD: (1, "error: réseau"), ("flatpak", "uninstall"): (0, "")})
        res = self.executer("runtimes", recos, run=faux2)
        self.assertFalse([c for c in faux2.commandes() if "-y" in c])
        self.assertTrue(res["erreur"])

    def test_refus_pendant_un_jeu(self):
        x = fichier(self.home / ".cache" / "pip" / "x", KIO)
        recos = self.recos()
        faux = FauxRun()
        res = self.executer("caches", recos, run=faux, jeu=lambda: "jeu.exe")
        self.assertEqual(res["erreur"], "Un jeu tourne : ménage reporté.")
        self.assertEqual((res["faits"], res["liberes"]), ([], 0))
        self.assertTrue(x.exists())
        self.assertEqual(faux.appels, [])

    def test_refus_pendant_une_mise_a_jour(self):
        x = fichier(self.home / ".cache" / "pip" / "x", KIO)
        recos = self.recos()
        faux = FauxRun()
        res = self.executer("caches", recos, run=faux, maj=lambda: True)
        self.assertEqual(res["erreur"], "Une mise à jour est en cours : ménage reporté.")
        self.assertEqual(res["faits"], [])
        self.assertTrue(x.exists())
        self.assertEqual(faux.appels, [])

    def test_mode_copier_refuse(self):
        recos = self.recos(controles={"caches": {"journal": 2 * 1024 ** 3}})
        faux = FauxRun()
        res = self.executer("journal", recos, run=faux)
        self.assertTrue(res["erreur"])
        self.assertEqual(faux.appels, [])

    def test_recommandation_absente(self):
        res = self.executer("caches", [])
        self.assertEqual(res["erreur"], "Recommandation inconnue.")


class Shaders(Base):
    """Caches de shaders sans jeu installé (D3) : steamapps/shadercache/<appid> dans une bibliothèque Steam."""

    def setUp(self):
        super().setUp()
        self.a, self.b = self.home / "BibA", self.home / "BibB"
        for appid in ("101",):
            self.manifeste(self.a, appid)
        for appid in ("202",):
            self.manifeste(self.b, appid)
        self.manifeste(self.b, "404", ".acf.123.tmp")
        (self.b / "steamapps" / "downloading" / "505").mkdir(parents=True)
        for nom in ("101", "202", "303", "3000000001", "notes"):
            fichier(self.a / "steamapps" / "shadercache" / nom / "cache.bin", KIO)
        for nom in ("404", "505"):
            fichier(self.b / "steamapps" / "shadercache" / nom / "cache.bin", KIO)
        self.c303 = self.a / "steamapps" / "shadercache" / "303"

    def manifeste(self, bib, appid, suffixe=".acf"):
        dossier = bib / "steamapps"
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"appmanifest_{appid}{suffixe}").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"Jeu"\n}}\n', encoding="utf-8")

    def reco(self, **kw):
        return par_id(self.recos(bibliotheques=[self.a, self.b], **kw)).get("shaders")

    def vdf(self, bib=None, apps=(), texte=None):
        """Le libraryfolders.vdf de la racine Steam du home temporaire (une bibliothèque `bib` déclarant `apps`)."""
        fichier_vdf = self.home / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf"
        fichier_vdf.parent.mkdir(parents=True, exist_ok=True)
        if texte is None:
            lignes = "".join('\t\t\t"%s"\t\t"1"\n' % a for a in apps)
            texte = ('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n%s\t\t}\n\t}\n}\n'
                     % (bib or self.a, lignes))
        if fichier_vdf.is_dir():
            fichier_vdf.rmdir()
        fichier_vdf.write_text(texte, encoding="utf-8")
        return fichier_vdf

    def executer_shaders(self, recos=None, **kw):
        return self.executer("shaders", recos or [self.reco()], bibliotheques=[self.a, self.b], **kw)

    def test_shaders_sans_jeu_installe(self):
        reco = self.reco()
        self.assertEqual(cibles(reco), [str(self.c303)])
        self.assertEqual(reco["elements"][0]["libelle"], f"Jeu Steam 303 ({self.a})")
        self.assertEqual((reco["titre"], reco["mode"]), ("Caches de shaders sans jeu installé", "supprimer"))
        self.assertIn("shaders", menage.IDS_JEUX)

    def test_shaders_proposes_meme_quand_steam_est_ouvert(self):
        self.assertEqual(cibles(par_id(self.recos(bibliotheques=[self.a, self.b], steam=lambda: "steam"))["shaders"]),
                         [str(self.c303)])

    def test_shaders_jeu_en_cours_d_installation_garde(self):
        for appid in ("404", "505"):
            self.assertNotIn(appid, [Path(c).name for c in cibles(self.reco())])

    def test_shaders_raccourci_non_steam_jamais_propose(self):
        self.assertNotIn("3000000001", [Path(c).name for c in cibles(self.reco())])

    def test_shaders_reverifies_au_moment_d_agir(self):
        reco = self.reco()
        self.manifeste(self.b, "303")                         # le jeu s'installe après l'affichage
        res = self.executer_shaders([reco])
        self.assertEqual(res["ignores"], [{"cible": str(self.c303), "raison": "utilisé maintenant"}])
        self.assertEqual((res["faits"], res["liberes"]), ([], 0))
        self.assertTrue((self.c303 / "cache.bin").exists())

    def test_shaders_installation_en_cours_pendant_l_action(self):
        reco = self.reco()
        (self.b / "steamapps" / "downloading" / "303").mkdir()
        res = self.executer_shaders([reco])
        self.assertEqual([i["raison"] for i in res["ignores"]], ["utilisé maintenant"])
        self.assertTrue(self.c303.exists())

    def test_shaders_bibliotheque_absente_ignoree(self):
        vdf = self.home / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf"
        vdf.parent.mkdir(parents=True)
        vdf.write_text('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n\t\t\t"303"\t\t"1"\n'
                       '\t\t}\n\t}\n}\n' % (self.home / "Debranche"), encoding="utf-8")
        with mock.patch("sys.stderr") as err:
            recos = self.recos(bibliotheques=[self.a, self.b])
        # 303 est installé sur le disque débranché : son cache n'est pas orphelin
        self.assertNotIn("shaders", par_id(recos))
        self.assertEqual(err.write.call_args_list, [])

    def test_shaders_chemin_par_defaut_bibliotheque_absente_ignoree(self):
        """Sans bibliotheques injectées (P8) : 303 est déclaré par une bibliothèque débranchée, son cache est sur la
        racine Steam : il n'est pas proposé."""
        racine = self.home / ".local" / "share" / "Steam"
        fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO)
        self.vdf(bib=self.home / "Debranche", apps=("303",))
        self.assertNotIn("shaders", par_id(self.recos()))

    def test_shaders_vdf_remplace_par_un_dossier_rien_propose(self):
        racine = self.home / ".local" / "share" / "Steam"
        fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO)
        self.vdf(bib=racine).unlink()
        (racine / "steamapps" / "libraryfolders.vdf").mkdir()
        with mock.patch("sys.stderr") as err:
            self.assertNotIn("shaders", par_id(self.recos()))
        self.assertIn("libraryfolders", "".join(c.args[0] for c in err.write.call_args_list))
        reco = menage._shaders(self.home, menage._bibliotheques_steam(self.home, None))
        self.assertEqual(reco["elements"], [])
        self.assertIn("Steam", reco["remarque"])

    def test_shaders_vdf_absent_racine_existante_rien_propose(self):
        racine = self.home / ".local" / "share" / "Steam"
        fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO)
        with mock.patch("sys.stderr"):
            self.assertNotIn("shaders", par_id(self.recos()))

    def test_shaders_vdf_coupe_rien_propose(self):
        racine = self.home / ".local" / "share" / "Steam"
        fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO)
        texte = self.vdf(bib=racine).read_text(encoding="utf-8")
        self.vdf(texte=texte[:len(texte) // 2])
        with mock.patch("sys.stderr"):
            self.assertNotIn("shaders", par_id(self.recos()))

    def _vdf_deux_bibliotheques(self, racine):
        bloc = '\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n%s\t\t}\n\t}\n'
        return ('"libraryfolders"\n{\n' + bloc % (0, racine, "") + bloc % (1, self.a, '\t\t\t"303"\t\t"1"\n') + "}\n")

    def test_shaders_vdf_coupe_apres_la_premiere_bibliotheque_rien_propose_ni_supprime(self):
        racine = self.home / ".local" / "share" / "Steam"
        cache = fichier(racine / "steamapps" / "shadercache" / "909" / "cache.bin", KIO).parent
        texte = self._vdf_deux_bibliotheques(racine)
        coupe = texte[:texte.index('\t"1"')]                # finit par la `}` de la bibliothèque 0
        self.assertTrue(coupe.rstrip().endswith("}"))
        self.vdf(texte=coupe)
        with mock.patch("sys.stderr"):
            self.assertNotIn("shaders", par_id(self.recos()))
        self.vdf(texte=texte)                               # affichage sain, puis coupure avant l'action
        recos = self.recos()
        self.assertIn(str(cache), cibles(par_id(recos)["shaders"]))
        self.vdf(texte=coupe)
        res = menage.executer("shaders", recos, home=self.home, run=FauxRun(), jeu=NON, maj=lambda: False, steam=NON)
        self.assertEqual((res["faits"], res["liberes"]), ([], 0))
        self.assertEqual({i["raison"] for i in res["ignores"]}, {menage.NON_VERIFIABLE})
        self.assertIn(str(cache), [i["cible"] for i in res["ignores"]])
        self.assertTrue((cache / "cache.bin").exists())

    def test_shaders_vdf_devenu_illisible_avant_l_action_refuse_tout(self):
        racine = self.home / ".local" / "share" / "Steam"
        cache = fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO).parent
        self.vdf(bib=racine)
        recos = self.recos()
        self.assertEqual(cibles(par_id(recos)["shaders"]), [str(cache)])
        (racine / "steamapps" / "libraryfolders.vdf").unlink()
        (racine / "steamapps" / "libraryfolders.vdf").mkdir()
        res = menage.executer("shaders", recos, home=self.home, run=FauxRun(), jeu=NON, maj=lambda: False, steam=NON)
        self.assertEqual((res["faits"], res["liberes"]), ([], 0))
        self.assertEqual(res["ignores"], [{"cible": str(cache), "raison": menage.NON_VERIFIABLE}])
        self.assertTrue((cache / "cache.bin").exists())

    def test_shaders_deux_racines_une_sans_vdf_rien_propose_ni_supprime(self):
        """RF-m5 : l'inventaire liste désormais les bibliothèques lues dans une racine même si une autre racine n'a pas
        de libraryfolders.vdf ; le ménage, lui, reste fermé (W5) : rien n'est proposé, rien n'est supprimé."""
        racine = self.home / ".local" / "share" / "Steam"
        cache = fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO).parent
        self.vdf(bib=racine)
        recos = self.recos()
        self.assertEqual(cibles(par_id(recos)["shaders"]), [str(cache)])
        flatpak = self.home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
        (flatpak / "steamapps").mkdir(parents=True)
        with mock.patch("sys.stderr"):
            self.assertNotIn("shaders", par_id(self.recos()))
        res = menage.executer("shaders", recos, home=self.home, run=FauxRun(), jeu=NON, maj=lambda: False, steam=NON)
        self.assertEqual((res["faits"], res["liberes"]), ([], 0))
        self.assertEqual(res["ignores"], [{"cible": str(cache), "raison": menage.NON_VERIFIABLE}])
        self.assertTrue((cache / "cache.bin").exists())

    def test_shaders_par_defaut_relit_les_bibliotheques_du_home(self):
        racine = self.home / ".local" / "share" / "Steam"
        self.vdf(bib=racine)
        fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO)
        self.assertEqual(cibles(par_id(self.recos())["shaders"]), [str(racine / "steamapps" / "shadercache" / "303")])

    def test_shaders_lien_symbolique_refuse(self):
        with tempfile.TemporaryDirectory() as dehors:
            fichier(Path(dehors) / "precieux.bin", KIO)
            lien = self.a / "steamapps" / "shadercache" / "606"
            lien.symlink_to(dehors)
            self.assertNotIn(str(lien), cibles(self.reco()))
            res = self.executer_shaders([{"id": "shaders", "elements": [{"cible": str(lien)}]}])
            self.assertEqual(res["ignores"], [{"cible": str(lien), "raison": "lien symbolique"}])
            self.assertTrue((Path(dehors) / "precieux.bin").exists())

    def test_shaders_hors_de_son_dossier(self):
        autre = fichier(self.home / "autre" / "303" / "cache.bin", KIO).parent
        res = self.executer_shaders([{"id": "shaders", "elements": [{"cible": str(autre)}]}])
        self.assertEqual(res["ignores"], [{"cible": str(autre), "raison": "hors de son dossier"}])
        self.assertTrue(autre.exists())

    def test_shaders_nom_non_decimal_ou_trop_grand_refuse(self):
        notes = self.a / "steamapps" / "shadercache" / "notes"
        grand = self.a / "steamapps" / "shadercache" / "3000000001"
        res = self.executer_shaders([{"id": "shaders", "elements": [{"cible": str(notes)}, {"cible": str(grand)}]}])
        self.assertEqual([i["raison"] for i in res["ignores"]], ["hors de son dossier"] * 2)
        self.assertTrue(notes.exists() and grand.exists())

    def test_shaders_steam_ouvert(self):
        res = self.executer_shaders(steam=lambda: "steam")
        self.assertEqual(res["erreur"], menage.STEAM_SHADERS)
        self.assertEqual((res["faits"], res["ignores"]), ([], []))
        self.assertTrue(self.c303.exists())

    def test_shaders_pendant_un_jeu(self):
        res = self.executer_shaders(jeu=lambda: "jeu.exe")
        self.assertEqual(res["erreur"], menage.JEU)
        self.assertTrue(self.c303.exists())

    def test_shaders_pendant_une_mise_a_jour(self):
        res = self.executer_shaders(maj=lambda: True)
        self.assertEqual(res["erreur"], menage.MAJ)
        self.assertTrue(self.c303.exists())

    def test_shaders_supprimes_et_liberes(self):
        res = self.executer_shaders()
        self.assertEqual((res["faits"], res["ignores"], res["erreur"]), ([str(self.c303)], [], None))
        self.assertGreater(res["liberes"], 0)
        self.assertFalse(self.c303.exists())
        for reste in ("101", "202", "3000000001", "notes"):
            self.assertTrue((self.a / "steamapps" / "shadercache" / reste / "cache.bin").exists(), reste)
        for reste in ("404", "505"):
            self.assertTrue((self.b / "steamapps" / "shadercache" / reste / "cache.bin").exists(), reste)

    def test_shaders_bibliotheques_relues_par_defaut_au_moment_d_agir(self):
        racine = self.home / ".local" / "share" / "Steam"
        self.vdf(bib=racine)
        cache = fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO).parent
        res = menage.executer("shaders", self.recos(), home=self.home, run=FauxRun(), jeu=NON, maj=lambda: False,
                              steam=NON)
        self.assertEqual(res["faits"], [str(cache)])
        self.assertFalse(cache.exists())

    def test_ordre_des_recommandations(self):
        self.protons()
        self.vdf(bib=self.a)
        ids = [r["id"] for r in self.recos(bibliotheques=[self.a, self.b])]
        self.assertEqual(ids, ["shaders", "proton"])

    def test_prefixes_jamais_proposes(self):
        for nom in ("303", "3000000001", "101.copie"):
            fichier(self.a / "steamapps" / "compatdata" / nom / "pfx.bin", KIO)
        recos = self.recos(bibliotheques=[self.a, self.b])
        for reco in recos:
            for cible in cibles(reco):
                self.assertNotIn("/compatdata/", cible)
        for id_ in ("prefixes", "compatdata"):
            self.assertEqual(self.executer(id_, recos)["erreur"], menage.INCONNUE)
        self.assertTrue((self.a / "steamapps" / "compatdata" / "303" / "pfx.bin").exists())

    def test_proton_cite_par_un_runner_lutris_garde(self):
        for dossier in (self.home / ".local" / "share" / "lutris" / "runners",
                        self.home / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris" / "runners"):
            with self.subTest(dossier=dossier):
                compat = self.protons()
                runner = fichier(dossier / "wine.yml")
                runner.write_text("wine:\n  version: GE-Proton10-25\n", encoding="utf-8")
                self.assertNotIn("proton", par_id(self.recos()))
                runner.unlink()
                self.assertEqual(cibles(par_id(self.recos())["proton"]), [str(compat / "GE-Proton10-25")])


class MiseAJourEnCours(unittest.TestCase):
    """La même source que le reste du moteur : session-en-cours.json, l'unité de la session, et celles de la nuit."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(commun, "ETAT", Path(tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_fichier_de_session(self):
        commun.ecrire_json(commun.ETAT / "session-en-cours.json", {"debut": "2026-11-09T20:00:00"})
        self.assertTrue(menage.maj_en_cours(run=FauxRun()))

    def test_unite_active(self):
        faux = FauxRun({("systemctl", "--user", "is-active"): (0, "inactive\nactive\n"),
                        ("systemctl", "is-active"): (3, "inactive\ninactive\n")})
        self.assertTrue(menage.maj_en_cours(run=faux))
        self.assertIn(["systemctl", "--user", "is-active", "centre-bazzite-maj.service", "maj-apps.service"],
                      faux.commandes())
        self.assertIn(["systemctl", "is-active", "uupd.service", "uupd-manual.service"], faux.commandes())

    def test_uupd_actif(self):
        faux = FauxRun({("systemctl", "--user", "is-active"): (3, "inactive\ninactive\n"),
                        ("systemctl", "is-active"): (0, "activating\ninactive\n")})
        self.assertTrue(menage.maj_en_cours(run=faux))

    def test_rien_en_cours(self):
        faux = FauxRun({("systemctl", "--user", "is-active"): (3, "inactive\ninactive\n"),
                        ("systemctl", "is-active"): (3, "inactive\nfailed\n")})
        self.assertFalse(menage.maj_en_cours(run=faux))


class Cli(Base):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.etat = Path(tmp.name)

        class Horloge(datetime):
            @classmethod
            def now(cls, tz=None):
                return MAINTENANT
        # La CLI lit stockage.json dans commun.ETAT, agit dans Path.home() et lit l'heure : tout est faux ici. Les
        # unités systemd sont « interrogées » par le faux run (aucune n'est active).
        for p in (mock.patch.object(commun, "ETAT", self.etat), mock.patch.object(Path, "home", return_value=self.home),
                  mock.patch.object(menage, "datetime", Horloge),
                  mock.patch.object(menage, "steam_ouvert", lambda *a: None)):
            p.start()
            self.addCleanup(p.stop)

    def publier(self):
        recos = self.recos()
        commun.ecrire_json(self.etat / "stockage.json", {"recommandations": recos})
        return par_id(recos)

    def lancer(self, id_, empreinte, run=None, jeu=NON):
        with mock.patch.object(stockage, "ecrire") as ecrire, mock.patch("builtins.print"), mock.patch("sys.stderr"):
            code = cli.main(["menage", id_, "--empreinte", empreinte], run=run or FauxRun(), jeu=jeu)
        return code, ecrire

    def tache(self):
        liste = taches.lister(self.etat / "taches")
        self.assertEqual(len(liste), 1)
        return liste[0]

    def test_cli_menage_inconnu(self):
        commun.ecrire_json(self.etat / "stockage.json", {"recommandations": []})
        with mock.patch.object(stockage, "ecrire") as ecrire, mock.patch("sys.stderr") as err:
            self.assertEqual(cli.main(["menage", "caches", "--empreinte", menage.empreinte([])], run=FauxRun(), jeu=NON), 2)
        self.assertIn("Recommandation inconnue.", "".join(str(c.args[0]) for c in err.write.call_args_list))
        ecrire.assert_not_called()
        self.assertEqual(taches.lister(self.etat / "taches"), [])

    def test_cli_sans_empreinte_refuse(self):
        fichier(self.home / ".cache" / "pip" / "x", KIO)
        self.publier()
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as fin:
            cli.main(["menage", "caches"], run=FauxRun(), jeu=NON)
        self.assertEqual(fin.exception.code, 2)
        self.assertTrue((self.home / ".cache" / "pip" / "x").exists())

    def test_cli_menage_ecrit_une_tache(self):
        pip = self.home / ".cache" / "pip"
        fichier(pip / "x", 10 * KIO)
        r = self.publier()["caches"]
        code, ecrire = self.lancer("caches", menage.empreinte(r["elements"]))
        self.assertEqual(code, 0)
        t = self.tache()
        self.assertEqual((t["id"], t["type"], t["statut"]), ("menage:caches", "menage", "fini"))
        self.assertTrue(t["detail"].endswith("libérés"), t["detail"])
        self.assertEqual(t["titre"], "Caches régénérables")
        self.assertEqual(list(pip.iterdir()), [])
        ecrire.assert_called_once_with()

    def test_cli_empreinte_differente_rien_n_est_fait(self):
        """La liste de stockage.json n'est plus celle montrée dans la fenêtre : refus, et stockage.json republié."""
        x = fichier(self.home / ".cache" / "pip" / "x", KIO)
        fichier(self.home / ".npm" / "_cacache" / "y", KIO)
        r = self.publier()["caches"]
        code, ecrire = self.lancer("caches", menage.empreinte(r["elements"][:1]))
        self.assertEqual(code, 1)
        t = self.tache()
        self.assertEqual((t["statut"], t["detail"]), ("echec", "La liste a changé : rien n'a été fait."))
        self.assertTrue(x.exists())
        ecrire.assert_called_once_with()

    def test_cli_meme_cible_autre_taille_refusee(self):
        """La fenêtre a montré une taille, stockage.json en dit une autre pour la même cible : rien n'est fait."""
        x = fichier(self.home / ".cache" / "pip" / "x", KIO)
        r = self.publier()["caches"]
        montree = menage.empreinte(r["elements"])
        donnees = commun.lire_json(self.etat / "stockage.json", {})
        donnees["recommandations"][0]["elements"][0]["octets"] += 4096
        commun.ecrire_json(self.etat / "stockage.json", donnees)
        code, _ = self.lancer("caches", montree)
        self.assertEqual(code, 1)
        self.assertEqual(self.tache()["detail"], "La liste a changé : rien n'a été fait.")
        self.assertTrue(x.exists())

    def test_cli_menage_pendant_un_jeu_tache_en_echec(self):
        x = fichier(self.home / ".cache" / "pip" / "x", KIO)
        r = self.publier()["caches"]
        code, ecrire = self.lancer("caches", menage.empreinte(r["elements"]), jeu=lambda: "jeu.exe")
        self.assertNotEqual(code, 0)
        t = self.tache()
        self.assertEqual((t["statut"], t["detail"]), ("echec", "Un jeu tourne : ménage reporté."))
        self.assertTrue(x.exists())
        ecrire.assert_called_once_with()          # stockage.json republié (V10)

    def test_cli_menage_pendant_une_mise_a_jour(self):
        x = fichier(self.home / ".cache" / "pip" / "x", KIO)
        r = self.publier()["caches"]
        commun.ecrire_json(self.etat / "session-en-cours.json", {"debut": "2026-11-09T20:00:00"})
        code, _ = self.lancer("caches", menage.empreinte(r["elements"]))
        self.assertNotEqual(code, 0)
        self.assertEqual(self.tache()["detail"], "Une mise à jour est en cours : ménage reporté.")
        self.assertTrue(x.exists())

    def shaders_du_home(self):
        racine = self.home / ".local" / "share" / "Steam"
        (racine / "steamapps").mkdir(parents=True, exist_ok=True)
        (racine / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n}\n', encoding="utf-8")
        return fichier(racine / "steamapps" / "shadercache" / "303" / "cache.bin", KIO).parent

    def test_cli_menage_shaders(self):
        cache = self.shaders_du_home()
        r = self.publier()["shaders"]
        code, ecrire = self.lancer("shaders", menage.empreinte(r["elements"]))
        self.assertEqual(code, 0)
        t = self.tache()
        self.assertEqual((t["id"], t["statut"]), ("menage:shaders", "fini"))
        self.assertTrue(t["detail"].endswith("libérés"), t["detail"])
        self.assertFalse(cache.exists())
        ecrire.assert_called_once_with()

    def test_cli_menage_shaders_empreinte_changee(self):
        cache = self.shaders_du_home()
        self.publier()
        code, _ = self.lancer("shaders", "0123456789abcdef")
        self.assertEqual(code, 1)
        t = self.tache()
        self.assertEqual((t["statut"], t["detail"]), ("echec", menage.CHANGEE))
        self.assertTrue((cache / "cache.bin").exists())

    def test_cli_telechargements_dit_corbeille(self):
        fichier(self.home / "Téléchargements" / "vieux.zip", KIO, age=100)
        r = self.publier()["telechargements"]
        code, _ = self.lancer("telechargements", menage.empreinte(r["elements"]), run=FauxRun({("gio", "trash"): self.jeter}))
        self.assertEqual(code, 0)
        self.assertTrue(self.tache()["detail"].endswith("envoyés à la corbeille"), self.tache()["detail"])

    def test_cli_ignores_au_journal_de_la_tache(self):
        tel = self.home / "Téléchargements"
        vieux = fichier(tel / "vieux.zip", KIO, age=100)
        fichier(tel / "autre.zip", KIO, age=100)
        r = self.publier()["telechargements"]
        vieillir(vieux, 0)
        self.lancer("telechargements", menage.empreinte(r["elements"]), run=FauxRun({("gio", "trash"): self.jeter}))
        t = self.tache()
        self.assertEqual(t["statut"], "fini")
        self.assertIn(f"Laissé : {vieux} (modifié depuis)", t["journal"])
        self.assertIn("1 laissé de côté", t["detail"])

    def test_cli_suppression_impossible_dite_dans_le_detail(self):
        pip = self.home / ".cache" / "pip"
        fichier(pip / "libre" / "a", KIO)
        protege = fichier(pip / "protege" / "b", KIO).parent
        protege.chmod(0o500)
        self.addCleanup(protege.chmod, 0o700)
        r = self.publier()["caches"]
        self.lancer("caches", menage.empreinte(r["elements"]))
        t = self.tache()
        self.assertIn("suppression impossible", t["detail"])
        self.assertIn(f"Laissé : {pip} (suppression impossible)", t["journal"])


if __name__ == "__main__":
    unittest.main()
