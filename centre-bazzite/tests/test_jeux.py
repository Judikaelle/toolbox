"""Bibliothèques de jeux : Steam, Heroic, Lutris, émulateurs. Home temporaire et sources injectées, jamais les vraies
bibliothèques ; les échantillons sont génériques (tests/echantillons/jeux/)."""
import contextlib
import io
import json
import os
import sqlite3
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, config, jeux
from centre_bazzite.config import Volume

from tests import configuration
from tests.test_steam import ECH, Base as BaseSteam, ecrire_manifeste, gabarit

VOLUMES = [Volume("Système", "/var", False, False), Volume("Home", "/var/home", False, False),
           Volume("Données", "/var/mnt/DONNEES", True, False), Volume("Externe", "/var/mnt/EXTERNE", False, True)]


@contextlib.contextmanager
def fuseau(valeur="CET-1"):
    """Heure locale fixée (UTC+1, sans heure d'été) : les dates ISO attendues ne dépendent pas du PC."""
    with mock.patch.dict(os.environ, {"TZ": valeur}):
        time.tzset()
        try:
            yield
        finally:
            pass
    time.tzset()


def sfo(**entrees):
    """Un fichier param.sfo (format PSF) : texte (0x0204) ou entier (0x0404)."""
    cles, donnees, index = b"", b"", b""
    for cle, valeur in entrees.items():
        brut = struct.pack("<I", valeur) if isinstance(valeur, int) else valeur.encode() + b"\0"
        index += struct.pack("<HHIII", len(cles), 0x0404 if isinstance(valeur, int) else 0x0204,
                             len(brut), len(brut), len(donnees))
        cles += cle.encode() + b"\0"
        donnees += brut
    debut_cles = 20 + len(index)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, debut_cles, debut_cles + len(cles), len(entrees)) \
        + index + cles + donnees


class TestNomSteam(unittest.TestCase):
    def test_volume_au_plus_long_prefixe(self):
        self.assertEqual(jeux.nom_steam(Path("/var/mnt/DONNEES/SteamLibrary"), VOLUMES), "Steam (Données)")
        self.assertEqual(jeux.nom_steam(Path("/var/home/exemple/.local/share/Steam"), VOLUMES), "Steam (Home)")

    def test_compare_des_composants_de_chemin(self):
        # « /var/mnt/DONNEES2 » n'est pas dans « /var/mnt/DONNEES » (même début de texte, autre dossier)
        self.assertEqual(jeux.nom_steam(Path("/var/mnt/DONNEES2/Bib"), VOLUMES), "Steam (/var/mnt/DONNEES2/Bib)")

    def test_systeme_ignore_pour_un_disque_non_configure(self):
        self.assertEqual(jeux.nom_steam(Path("/var/mnt/AUTRE/Bib"), VOLUMES), "Steam (/var/mnt/AUTRE/Bib)")
        self.assertEqual(jeux.nom_steam(Path("/run/media/exemple/Bib"), VOLUMES), "Steam (/run/media/exemple/Bib)")

    def test_systeme_garde_pour_un_autre_chemin_de_var(self):
        self.assertEqual(jeux.nom_steam(Path("/var/lib/Bib"), VOLUMES), "Steam (Système)")

    def test_chemin_hors_volumes(self):
        self.assertEqual(jeux.nom_steam(Path("/opt/Bib"), VOLUMES), "Steam (/opt/Bib)")


class TestTailleHeroic(unittest.TestCase):
    def test_taille_heroic(self):
        self.assertEqual(jeux.taille_heroic("7.01 GiB"), 7526930186)
        self.assertEqual(jeux.taille_heroic("512 MiB"), 536870912)
        self.assertEqual(jeux.taille_heroic("2 TiB"), 2 * 1024 ** 4)
        self.assertEqual(jeux.taille_heroic("10 KiB"), 10240)
        self.assertEqual(jeux.taille_heroic("99 B"), 99)
        self.assertEqual(jeux.taille_heroic("1.5 GB"), 1500000000)
        self.assertIsNone(jeux.taille_heroic("?"))
        self.assertIsNone(jeux.taille_heroic(None))


class TestSteamJeux(BaseSteam):
    def test_steam_jeux_et_bibliotheques(self):
        volumes = VOLUMES + [Volume("Test", str(self.tmp), False, False)]
        ecrire_manifeste(self.racine, "101", "Jeu de course", partie=1794300000)
        ecrire_manifeste(self.bib1, "202", "Aventure")
        ecrire_manifeste(self.bib1, "228980", "Proton Experimental")
        with fuseau():
            bibs, liste = jeux.steam([self.racine, self.bib1], volumes)
        self.assertEqual([b["nom"] for b in bibs], ["Steam (Test)", "Steam (Test)"])
        self.assertEqual([b["id"] for b in bibs], [f"steam:{self.racine}", f"steam:{self.bib1}"])
        self.assertEqual([(b["type"], b["nombre"], b["absente"], b["chemin"]) for b in bibs],
                         [("steam", 1, False, str(self.racine)), ("steam", 1, False, str(self.bib1))])
        self.assertEqual([b["octets"] for b in bibs], [1073741824] * 2)
        self.assertEqual(bibs[0]["taille"], "1,0 Go")
        self.assertEqual([j["titre"] for j in liste], ["Jeu de course", "Aventure"])    # l'outil n'est pas un jeu
        course = liste[0]
        self.assertEqual(course, {"id": f"steam:{self.racine}:101", "titre": "Jeu de course",
                                  "bibliotheque": f"steam:{self.racine}", "type": "steam", "octets": 1073741824,
                                  "taille": "1,0 Go", "derniere_partie": "2026-11-10T09:40:00",
                                  "chemin": str(self.racine / "steamapps" / "common" / "Jeu de course")})
        self.assertIsNone(liste[1]["derniere_partie"])

    def test_noms_des_volumes(self):
        volumes = [Volume("Home", str(self.home), False, False), Volume("Données", str(self.tmp), False, False)]
        bibs, _ = jeux.steam([self.racine, self.bib1], volumes)
        self.assertEqual([b["nom"] for b in bibs], ["Steam (Home)", "Steam (Données)"])

    def test_bibliotheque_vide_listee(self):
        bibs, liste = jeux.steam([self.bib1], VOLUMES)
        self.assertEqual((bibs[0]["nombre"], bibs[0]["octets"], bibs[0]["taille"], liste), (0, 0, "0 Mo", []))


class BaseHeroic(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.home = Path(d.name)
        self.heroic = self.home / ".config" / "heroic"
        (self.heroic / "store_cache").mkdir(parents=True)
        (self.heroic / "store").mkdir()

    def installer(self, nom, fixture, **valeurs):
        (self.heroic / nom).write_text(gabarit(fixture, INSTALL="/chemin/jeux", **valeurs), encoding="utf-8")


class TestHeroic(BaseHeroic):
    def test_heroic_installes_seulement(self):
        self.installer("store_cache/legendary_library.json", "heroic-legendary_library.json")
        self.installer("store_cache/gog_library.json", "heroic-gog_library.json")
        self.installer("store/timestamp.json", "heroic-timestamp.json")
        with fuseau():
            bibs, liste = jeux.heroic(self.home)
        # le DLC et le jeu non installé sont écartés ; GOG n'a aucun jeu retenu, donc n'est pas listé
        self.assertEqual([(b["id"], b["nom"], b["nombre"]) for b in bibs], [("heroic:legendary", "Heroic (Epic)", 1)])
        self.assertEqual(len(liste), 1)
        self.assertEqual(liste[0], {
            "id": "heroic:legendary:aaa1", "titre": "Énigmes", "bibliotheque": "heroic:legendary", "type": "heroic",
            "octets": jeux.taille_heroic("7.01 GiB"), "taille": "7,0 Go", "derniere_partie": "2026-01-02T12:00:00",
            "chemin": "/chemin/jeux/Enigmes"})
        self.assertEqual((bibs[0]["type"], bibs[0]["absente"], bibs[0]["octets"]), ("heroic", False, liste[0]["octets"]))

    def test_gog_installe_donne_sa_bibliotheque(self):
        self.installer("store_cache/legendary_library.json", "heroic-legendary_library.json")
        gog = json.loads(gabarit("heroic-gog_library.json"))
        gog["games"][0].update(is_installed=True, install={"install_path": "/chemin/jeux/Aventure", "is_dlc": False})
        (self.heroic / "store_cache" / "gog_library.json").write_text(json.dumps(gog), encoding="utf-8")
        bibs, liste = jeux.heroic(self.home)
        self.assertEqual([b["id"] for b in bibs], ["heroic:gog", "heroic:legendary"])
        gog_jeu = next(j for j in liste if j["bibliotheque"] == "heroic:gog")
        self.assertEqual((gog_jeu["titre"], gog_jeu["octets"], gog_jeu["taille"], gog_jeu["derniere_partie"]),
                         ("Aventure", None, "Inconnue", None))

    def test_flatpak_et_sans_doublon(self):
        flatpak = self.home / ".var/app/com.heroicgameslauncher.hgl/config/heroic/store_cache"
        flatpak.mkdir(parents=True)
        texte = gabarit("heroic-legendary_library.json", INSTALL="/chemin/jeux")
        (flatpak / "legendary_library.json").write_text(texte, encoding="utf-8")
        self.installer("store_cache/legendary_library.json", "heroic-legendary_library.json")
        _, liste = jeux.heroic(self.home)
        self.assertEqual([j["id"] for j in liste], ["heroic:legendary:aaa1"])

    def test_fichier_illisible_ignore(self):
        (self.heroic / "store_cache" / "legendary_library.json").write_text("{pas du json", encoding="utf-8")
        (self.heroic / "store_cache" / "gog_library.json").write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(jeux.heroic(self.home), ([], []))

    def test_date_extreme_ne_fait_pas_perdre_la_source(self):
        self.installer("store_cache/legendary_library.json", "heroic-legendary_library.json")
        (self.heroic / "store").mkdir(exist_ok=True)
        (self.heroic / "store" / "timestamp.json").write_text(
            '{"aaa1": {"lastPlayed": "0001-01-01T00:00:00.000+23:59"}}', encoding="utf-8")
        with fuseau("UTC+9"):
            bibs, liste = jeux.heroic(self.home)
        self.assertEqual([j["titre"] for j in liste], ["Énigmes"])
        self.assertIsNone(liste[0]["derniere_partie"])

    def test_sans_heroic(self):
        self.assertEqual(jeux.heroic(self.home / "vide"), ([], []))


class TestLutris(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.home = Path(d.name)
        self.base = self.home / ".local" / "share" / "lutris" / "pga.db"
        self.base.parent.mkdir(parents=True)
        self.dossier = self.home / "Jeux" / "Plateformes"
        self.dossier.mkdir(parents=True)
        (self.dossier / "donnees.bin").write_bytes(b"x" * 8192)
        c = sqlite3.connect(self.base)
        c.execute("create table games (id integer primary key, name text, directory text, installed integer, "
                  "lastplayed integer)")
        c.executemany("insert into games (name, directory, installed, lastplayed) values (?, ?, ?, ?)", [
            ("Plateformes", str(self.dossier), 1, 1794300000),
            ("Énigmes", str(self.home / "absent"), 0, 0),
            ("Aventure", None, 1, 0)])
        c.commit()
        c.close()

    def test_lutris_lecture_seule(self):
        avant = {p.name: p.stat().st_mtime_ns for p in self.base.parent.iterdir()}
        with fuseau():
            bibs, liste = jeux.lutris(self.home)
        apres = {p.name: p.stat().st_mtime_ns for p in self.base.parent.iterdir()}
        self.assertEqual(apres, avant)                      # pas de -journal, pas de -wal, base non modifiée
        self.assertEqual([(b["id"], b["nom"], b["type"], b["nombre"]) for b in bibs],
                         [("lutris", "Lutris", "lutris", 2)])
        titres = {j["titre"]: j for j in liste}
        self.assertEqual(set(titres), {"Plateformes", "Aventure"})         # installed = 0 écarté
        plateformes = titres["Plateformes"]
        self.assertGreaterEqual(plateformes["octets"], 8192)
        self.assertEqual((plateformes["id"], plateformes["chemin"], plateformes["derniere_partie"]),
                         (f"lutris:Plateformes:{self.dossier}", str(self.dossier), "2026-11-10T09:40:00"))
        aventure = titres["Aventure"]
        self.assertEqual((aventure["octets"], aventure["taille"], aventure["chemin"], aventure["derniere_partie"]),
                         (None, "Inconnue", None, None))

    def test_chemin_avec_caracteres_speciaux_reste_en_lecture_seule(self):
        special = self.home / "a?b#c%d" / "lutris"
        special.mkdir(parents=True)
        base = special / "pga.db"
        base.write_bytes(self.base.read_bytes())
        modele = "~/" + str(base.relative_to(self.home))
        with mock.patch.object(jeux, "LUTRIS", (modele,)), fuseau():
            bibs, liste = jeux.lutris(self.home)
        self.assertEqual(sorted(j["titre"] for j in liste), ["Aventure", "Plateformes"])
        self.assertEqual(sorted(p.name for p in special.iterdir()), ["pga.db"])

    def test_base_illisible_ignoree(self):
        self.base.write_bytes(b"pas une base sqlite" * 50)
        self.assertEqual(jeux.lutris(self.home), ([], []))

    def test_sans_lutris(self):
        self.assertEqual(jeux.lutris(self.home / "vide"), ([], []))


class TestEmulateurs(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = Path(d.name) / "Console"
        self.dossier.mkdir()

    def emulateur(self, **autres):
        return [{"nom": "Console", "dossier": self.dossier, "extensions": None, **autres}]

    def test_emulateur_titres(self):
        ps = self.dossier / "CODE00001"
        (ps / "sce_sys").mkdir(parents=True)
        (ps / "sce_sys" / "param.json").write_bytes((ECH / "param.json").read_bytes())
        (ps / "eboot.bin").write_bytes(b"x" * 4096)
        ps2 = self.dossier / "CODE00002"
        (ps2 / "sce_sys").mkdir(parents=True)
        (ps2 / "sce_sys" / "param.sfo").write_bytes(sfo(TITLE="Jeu de plateforme", CATEGORY="gd"))
        (self.dossier / "Jeu Exemple [0100ABCD][v0].nup").write_bytes(b"x" * 10000)
        (self.dossier / "Autre jeu (Europe) (Rev 1).iso").write_bytes(b"x")
        (self.dossier / "icone.png").write_bytes(b"x")
        (self.dossier / ".cache").mkdir()
        (self.dossier / "lien.iso").symlink_to(self.dossier / "Jeu Exemple [0100ABCD][v0].nup")
        bibs, liste = jeux.emulateurs(self.emulateur())
        self.assertEqual(sorted(j["titre"] for j in liste),
                         ["Autre jeu", "Jeu Exemple", "Jeu d'aventure", "Jeu de plateforme"])
        self.assertEqual([(b["id"], b["nom"], b["type"], b["absente"], b["nombre"], b["chemin"]) for b in bibs],
                         [("emulateur:Console", "Console", "emulateur", False, 4, str(self.dossier))])
        par_titre = {j["titre"]: j for j in liste}
        aventure = par_titre["Jeu d'aventure"]
        self.assertEqual((aventure["id"], aventure["bibliotheque"], aventure["type"], aventure["derniere_partie"],
                          aventure["chemin"]),
                         ("emulateur:Console:CODE00001", "emulateur:Console", "emulateur", None, str(ps)))
        self.assertEqual(aventure["octets"], jeux.sante.taille_dossier(ps))
        fichier = par_titre["Jeu Exemple"]
        self.assertEqual(fichier["octets"], (self.dossier / "Jeu Exemple [0100ABCD][v0].nup").stat().st_blocks * 512)
        self.assertEqual(bibs[0]["octets"], sum(j["octets"] for j in liste))

    def test_emulateur_extensions(self):
        (self.dossier / "Aventure.iso").write_bytes(b"x")
        (self.dossier / "Énigmes.ISO").write_bytes(b"x")
        (self.dossier / "Plateformes.nup").write_bytes(b"x")
        (self.dossier / "Dossier").mkdir()
        _, liste = jeux.emulateurs(self.emulateur(extensions=(".iso",)))
        self.assertEqual(sorted(j["titre"] for j in liste), ["Aventure", "Dossier", "Énigmes"])

    def test_emulateur_dossier_absent(self):
        bibs, liste = jeux.emulateurs([{"nom": "Console", "dossier": self.dossier / "absent", "extensions": None}])
        self.assertEqual(liste, [])
        self.assertEqual([(b["id"], b["absente"], b["nombre"], b["octets"], b["taille"]) for b in bibs],
                         [("emulateur:Console", True, 0, 0, "0 Mo")])

    def test_titre_sfo_invalide_retombe_sur_le_nom(self):
        dossier = self.dossier / "Jeu invalide"
        (dossier / "sce_sys").mkdir(parents=True)
        (dossier / "sce_sys" / "param.sfo").write_bytes(b"pas un sfo")
        (dossier / "sce_sys" / "param.json").write_text("{pas du json", encoding="utf-8")
        self.assertEqual(jeux.titre_emulateur(dossier), "Jeu invalide")

    def test_lire_sfo(self):
        self.assertEqual(jeux.lire_sfo(sfo(TITLE="Jeu d'énigmes", APP_VER=7)), {"TITLE": "Jeu d'énigmes", "APP_VER": 7})
        self.assertEqual(jeux.lire_sfo(b""), {})
        self.assertEqual(jeux.lire_sfo(b"\0PSF" + b"\xff" * 30), {})
        self.assertEqual(jeux.lire_sfo(sfo(TITLE="Jeu")[:-3]).get("TITLE"), None)

    def test_titre_param_json_fr_puis_defaut_puis_titlename(self):
        def titre(contenu):
            dossier = self.dossier / f"j{abs(hash(json.dumps(contenu)))}"
            (dossier / "sce_sys").mkdir(parents=True)
            (dossier / "sce_sys" / "param.json").write_text(json.dumps(contenu), encoding="utf-8")
            return jeux.titre_emulateur(dossier)
        self.assertEqual(titre({"localizedParameters": {"defaultLanguage": "en-US", "en-US": {"titleName": "Anglais"}}}),
                         "Anglais")
        self.assertEqual(titre({"titleName": "Direct"}), "Direct")


GIO = 1024 ** 3


def jeu_fictif(id_, titre, bibliotheque, octets):
    return {"id": id_, "titre": titre, "bibliotheque": bibliotheque, "type": "steam", "octets": octets,
            "taille": "", "derniere_partie": None, "chemin": None}


class TestCleTitre(unittest.TestCase):
    def test_cle_titre(self):
        self.assertEqual(jeux.cle_titre("Jeu de Course\u2122 (\u00c9dition GOTY)"), "jeu de course")
        self.assertEqual(jeux.cle_titre("Aventure: Le Retour"), "aventure le retour")
        self.assertEqual(jeux.cle_titre("\u00c9nigmes [v1.2] \u00ae\u00a9"), "enigmes")
        self.assertEqual(jeux.cle_titre("  "), "")


class TestDoublons(unittest.TestCase):
    def test_doublons_deux_bibliotheques(self):
        liste = [jeu_fictif("steam:/a:101", "Aventure", "steam:/a", 40 * GIO),
                 jeu_fictif("heroic:gog:x", "AVENTURE\u2122", "heroic:gog", 38 * GIO),
                 jeu_fictif("steam:/a:202", "Plateformes", "steam:/a", GIO)]
        res = jeux.doublons(liste)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], {"titre": "Aventure", "jeux": ["steam:/a:101", "heroic:gog:x"], "octets": 78 * GIO,
                                  "en_trop": 38 * GIO, "taille_en_trop": "38 Go"})

    def test_meme_bibliotheque_pas_un_doublon(self):
        liste = [jeu_fictif("steam:/a:101", "Aventure", "steam:/a", GIO),
                 jeu_fictif("steam:/a:102", "Aventure", "steam:/a", GIO)]
        self.assertEqual(jeux.doublons(liste), [])

    def test_tailles_inconnues_et_tri(self):
        liste = [jeu_fictif("a1", "Petit", "a", GIO), jeu_fictif("b1", "Petit", "b", None),
                 jeu_fictif("a2", "Gros", "a", 5 * GIO), jeu_fictif("b2", "Gros", "b", 4 * GIO)]
        res = jeux.doublons(liste)
        self.assertEqual([(d["titre"], d["en_trop"]) for d in res], [("Gros", 4 * GIO), ("Petit", 0)])


class TestPrefixes(BaseSteam):
    def test_prefixes_orphelins_seulement_listes(self):
        compat = self.bib1 / "steamapps" / "compatdata"
        for nom in ("101", "303", "3000000001", "101.copie"):
            (compat / nom).mkdir(parents=True)
            (compat / nom / "donnees").write_bytes(b"x" * 8192)
        (compat / "lien").symlink_to(self.tmp)
        avant = sorted(str(p) for p in compat.rglob("*"))
        res = jeux.prefixes([self.bib1], {"101"}, {str(self.bib1): "Steam (Test)"})
        self.assertEqual(sorted(e["nature"] for e in res["elements"]), ["desinstalle", "inhabituel", "non_steam"])
        par_nature = {e["nature"]: e for e in res["elements"]}
        self.assertEqual(par_nature["desinstalle"]["libelle"], "Jeu Steam 303 (désinstallé)")
        self.assertEqual(par_nature["non_steam"]["libelle"], "Raccourci non-Steam 3000000001")
        self.assertEqual(par_nature["inhabituel"]["libelle"], "101.copie (nom inhabituel : copie ou sauvegarde ?)")
        self.assertEqual(par_nature["desinstalle"]["cible"], str(compat / "303"))
        self.assertEqual(par_nature["desinstalle"]["bibliotheque"], "Steam (Test)")
        self.assertGreaterEqual(res["octets"], 3 * 8192)
        self.assertEqual(res["octets"], sum(e["octets"] for e in res["elements"]))
        self.assertEqual(res["taille"], jeux.commun.taille(res["octets"]))
        self.assertEqual(sorted(str(p) for p in compat.rglob("*")), avant)          # rien n'a été supprimé

    def test_tri_par_taille_et_bibliotheque_sans_compatdata(self):
        compat = self.bib1 / "steamapps" / "compatdata"
        (compat / "303").mkdir(parents=True)
        (compat / "404").mkdir()
        (compat / "404" / "x").write_bytes(b"x" * 100000)
        res = jeux.prefixes([self.bib1, self.racine], set(), {})
        self.assertEqual([Path(e["cible"]).name for e in res["elements"]], ["404", "303"])
        self.assertEqual(res["elements"][0]["bibliotheque"], f"Steam ({self.bib1})")


class TestGels(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = Path(d.name) / "freeze-jeu"
        self.dossier.mkdir()

    def ecrire(self, nom, texte="x"):
        (self.dossier / nom).write_text(texte, encoding="utf-8")

    def test_gels(self):
        self.ecrire("20260102-030405-GEL-JeuDeCourse.ex.txt", "### Gel automatique\n### Declencheur : anomalie : GPU=1%\n")
        self.ecrire("20260105-101010-Aventure.exe.txt", "capture manuelle")
        self.ecrire(".ring", "x")
        self.ecrire("watch.log", "x")
        self.ecrire("notes.txt", "x")
        res = jeux.gels(self.dossier)
        self.assertEqual((res["nombre"], res["automatiques"], res["dernier"]), (2, 1, "2026-01-05T10:10:10"))
        self.assertEqual(res["dossier"], str(self.dossier))
        self.assertEqual([g["jeu"] for g in res["liste"]], ["Aventure", "JeuDeCourse"])
        self.assertEqual(res["liste"][1]["declencheur"], "anomalie : GPU=1%")
        self.assertIsNone(res["liste"][0]["declencheur"])
        self.assertEqual((res["liste"][0]["automatique"], res["liste"][1]["automatique"]), (False, True))
        self.assertEqual(res["liste"][1]["date"], "2026-01-02T03:04:05")
        self.assertEqual(res["liste"][0]["fichier"], str(self.dossier / "20260105-101010-Aventure.exe.txt"))
        self.assertEqual(res["liste"][0]["octets"], len("capture manuelle"))

    def test_limite_et_comptes_totaux(self):
        for i in range(1, 6):
            self.ecrire(f"2026010{i}-100000-GEL-Jeu.exe.txt")
        res = jeux.gels(self.dossier, limite=2)
        self.assertEqual((res["nombre"], res["automatiques"], len(res["liste"])), (5, 5, 2))
        self.assertEqual(res["liste"][0]["date"], "2026-01-05T10:00:00")

    def test_date_impossible_ecartee(self):
        self.ecrire("20269999-999999-Jeu.txt")
        self.assertEqual(jeux.gels(self.dossier)["nombre"], 0)

    def test_gels_dossier_absent(self):
        res = jeux.gels(self.dossier / "absent")
        self.assertEqual((res["nombre"], res["automatiques"], res["dernier"], res["liste"]), (0, 0, None, []))

    def test_dossier_par_defaut_contre_le_home(self):
        home = self.dossier.parent / "home"
        (home / ".local" / "share" / "freeze-jeu").mkdir(parents=True)
        (home / ".local" / "share" / "freeze-jeu" / "20260105-101010-Aventure.exe.txt").write_text("x")
        self.assertEqual(jeux.gels(home=home)["nombre"], 1)


SANS_REGLAGES = lambda: {"steam": [], "emulateurs": []}      # noqa: E731


class TestConstruire(BaseSteam):
    def setUp(self):
        super().setUp()
        # un libraryfolders.vdf lisible mais sans bibliothèque (sans lui, la racine Steam est « non vérifiable »)
        (self.racine / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n}\n', encoding="utf-8")

    def construire(self, **kw):
        kw.setdefault("reglages", SANS_REGLAGES)
        return jeux.construire(home=self.home, volumes=lambda: VOLUMES, gels_dossier=self.tmp / "sans-gels", **kw)

    def test_construire_ecrit_jeux_json(self):
        ecrire_manifeste(self.racine, "101", "Aventure")
        ecrire_manifeste(self.bib1, "202", "Plateformes")
        self.vdf()
        (self.bib1 / "steamapps" / "compatdata" / "909").mkdir(parents=True)
        res = self.construire()
        self.assertEqual(set(res), {"genere", "bibliotheques", "jeux", "doublons", "prefixes", "gels", "erreurs"})
        self.assertEqual(res["erreurs"], [])
        self.assertEqual(sorted(j["titre"] for j in res["jeux"]), ["Aventure", "Plateformes"])
        absentes = [b for b in res["bibliotheques"] if b["absente"]]
        self.assertEqual([(b["id"], b["type"], b["nombre"]) for b in absentes], [(f"steam:{self.bib2}", "steam", 0)])
        self.assertEqual([e["libelle"] for e in res["prefixes"]["elements"]], ["Jeu Steam 909 (désinstallé)"])
        self.assertEqual(res["gels"]["nombre"], 0)
        self.assertEqual(res["prefixes"]["elements"][0]["bibliotheque"], f"Steam ({self.bib1})")
        with tempfile.TemporaryDirectory() as dossier:
            chemin = jeux.ecrire(dossier, home=self.home, reglages=SANS_REGLAGES, volumes=lambda: VOLUMES,
                                 gels_dossier=self.tmp / "sans-gels")
            self.assertEqual(chemin, Path(dossier) / "jeux.json")
            self.assertEqual(json.loads(chemin.read_text(encoding="utf-8"))["erreurs"], [])

    def test_fichier_suit_commun_etat(self):
        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(commun, "ETAT", Path(dossier)):
            self.assertEqual(jeux.fichier(), Path(dossier) / "jeux.json")

    def test_prefixe_d_un_jeu_installe_ailleurs_n_est_pas_orphelin(self):
        self.vdf()                                          # 303 est dans le bloc apps de la bibliothèque absente
        (self.bib1 / "steamapps" / "compatdata" / "303").mkdir(parents=True)
        self.assertEqual(self.construire()["prefixes"]["elements"], [])

    def test_une_bibliotheque_cassee_n_empeche_pas_les_autres(self):
        ecrire_manifeste(self.racine, "101", "Aventure")
        heroic = self.home / ".config" / "heroic" / "store_cache"
        heroic.mkdir(parents=True)
        (heroic / "legendary_library.json").write_text("{pas du json", encoding="utf-8")
        lutris = self.home / ".local" / "share" / "lutris"
        lutris.mkdir(parents=True)
        (lutris / "pga.db").write_bytes(b"octets quelconques" * 100)
        res = self.construire()
        self.assertEqual([j["titre"] for j in res["jeux"]], ["Aventure"])
        self.assertEqual(len(res["erreurs"]), 2)
        self.assertTrue(res["erreurs"][0].startswith("Heroic : illisible ("), res["erreurs"])
        self.assertTrue(res["erreurs"][1].startswith("Lutris : illisible ("), res["erreurs"])

    def test_vdf_illisible_note_une_erreur_steam_et_ne_liste_aucun_prefixe(self):
        vdf = self.racine / "steamapps" / "libraryfolders.vdf"
        vdf.unlink()
        vdf.mkdir()
        (self.racine / "steamapps" / "compatdata" / "909").mkdir(parents=True)
        res = self.construire()
        self.assertEqual(res["erreurs"], ["Steam : illisible (bibliothèques non vérifiables)"])
        self.assertEqual(res["prefixes"]["elements"], [])

    def test_appids_qui_levent_une_seule_erreur(self):
        """RF-m6 : une exception de la lecture des appids installés est notée une fois (« Préfixes : illisible ») ; la
        phrase des bibliothèques non vérifiables reste réservée à l'incertitude (None)."""
        (self.racine / "steamapps" / "compatdata" / "909").mkdir(parents=True)
        with mock.patch.object(jeux.steam_, "appids_installes", side_effect=RuntimeError("boum")):
            res = self.construire()
        self.assertEqual(res["erreurs"], ["Préfixes : illisible (RuntimeError)"])
        self.assertEqual(res["prefixes"]["elements"], [])
        self.assertEqual(jeux.STEAM_NON_VERIFIABLE, "Steam : illisible (bibliothèques non vérifiables)")

    def test_une_source_qui_plante_devient_une_erreur(self):
        ecrire_manifeste(self.racine, "101", "Aventure")
        with mock.patch.object(jeux, "heroic", side_effect=RuntimeError("boum")):
            res = self.construire()
        self.assertEqual(res["erreurs"], ["Heroic : illisible (RuntimeError)"])
        self.assertEqual([j["titre"] for j in res["jeux"]], ["Aventure"])

    def test_noms_non_utf8_ecartes(self):
        console = self.tmp / "Console"
        console.mkdir()
        (console / "Aventure.iso").write_bytes(b"x")
        (console / os.fsdecode(b"\xff.iso")).write_bytes(b"x")
        res = self.construire(reglages=lambda: {"steam": [], "emulateurs": [
            {"nom": "Console", "dossier": console, "extensions": None}]})
        self.assertEqual([j["titre"] for j in res["jeux"]], ["Aventure"])
        json.dumps(res, ensure_ascii=False).encode("utf-8")
        self.assertEqual([b["nombre"] for b in res["bibliotheques"] if b["type"] == "emulateur"], [1])

    def test_prefixe_non_utf8_ecarte(self):
        compat = self.racine / "steamapps" / "compatdata"
        (compat / "303").mkdir(parents=True)
        (compat / os.fsdecode(b"\xff.copie")).mkdir()
        res = self.construire()
        self.assertEqual([e["libelle"] for e in res["prefixes"]["elements"]], ["Jeu Steam 303 (désinstallé)"])
        json.dumps(res, ensure_ascii=False).encode("utf-8")

    def test_emulateur_et_doublon(self):
        ecrire_manifeste(self.racine, "101", "Aventure", taille=3 * GIO)
        console = self.tmp / "Console"
        (console / "Aventure").mkdir(parents=True)
        (console / "Aventure" / "x").write_bytes(b"x" * 100000)
        res = self.construire(reglages=lambda: {"steam": [], "emulateurs": [
            {"nom": "Console", "dossier": console, "extensions": None}]})
        self.assertEqual([d["titre"] for d in res["doublons"]], ["Aventure"])
        self.assertEqual(len(res["doublons"][0]["jeux"]), 2)


class TestCliJeux(unittest.TestCase):
    def test_cli_jeux(self):
        faux = mock.Mock(return_value=Path("/tmp/jeux.json"))
        with mock.patch("builtins.print") as impression:
            code = cli.main(["jeux"], ecrire_jeux=faux)
        self.assertEqual(code, 0)
        faux.assert_called_once_with()
        impression.assert_called_once_with(Path("/tmp/jeux.json"))

    def test_releve_lance_jeux(self):
        unite = (Path(__file__).resolve().parent.parent / "systemd" / "centre-bazzite-releve.service")
        lignes = unite.read_text(encoding="utf-8").splitlines()
        stockage, mien = "ExecStart=-%h/.local/bin/centre-bazzite stockage", "ExecStart=-%h/.local/bin/centre-bazzite jeux"
        self.assertIn(mien, lignes)
        self.assertEqual(lignes.index(mien), lignes.index(stockage) + 1)


class TestConfigJeux(unittest.TestCase):
    def test_config_jeux(self):
        texte = """
[jeux]
steam = ["/var/mnt/DONNEES/SteamLibrary", "~/Jeux/Steam"]

[[jeux.emulateurs]]
nom = "Console"
dossier = "/var/mnt/DONNEES/Console"
extensions = [".ISO", "nup"]

[[jeux.emulateurs]]
nom = "Portable"
dossier = "~/Jeux/Portable"

[[jeux.emulateurs]]
nom = "Sans dossier"

[[jeux.emulateurs]]
nom = "Relatif"
dossier = "Jeux/Relatif"
"""
        err = io.StringIO()
        with configuration(texte), contextlib.redirect_stderr(err):
            res = config.jeux()
        self.assertEqual(res["steam"], [Path("/var/mnt/DONNEES/SteamLibrary"), Path.home() / "Jeux" / "Steam"])
        self.assertEqual(res["emulateurs"], [
            {"nom": "Console", "dossier": Path("/var/mnt/DONNEES/Console"), "extensions": (".iso", ".nup")},
            {"nom": "Portable", "dossier": Path.home() / "Jeux" / "Portable", "extensions": None}])
        self.assertEqual(err.getvalue().count("Health Hub, configuration"), 2)         # les deux mal formées

    def test_config_jeux_par_defaut(self):
        with configuration(""):
            self.assertEqual(config.jeux(), {"steam": [], "emulateurs": []})

    def test_config_jeux_steam_mal_forme(self):
        err = io.StringIO()
        with configuration('[jeux]\nsteam = "pas une liste"'), contextlib.redirect_stderr(err):
            self.assertEqual(config.jeux()["steam"], [])
        self.assertIn("liste", err.getvalue())


if __name__ == "__main__":
    unittest.main()
