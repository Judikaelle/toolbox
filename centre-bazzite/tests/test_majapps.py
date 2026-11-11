"""Tests de centre_bazzite.majapps (aucun accès réseau, rien n'est installé ; dossiers temporaires partout)."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import commun
from centre_bazzite.majapps import appimages, distrobox, doublons, linstat, outils, principal, rapport, vicinae
from tests import configuration


class DossiersTemp:
    """Dossiers temporaires effacés à la fin de chaque test."""

    def _dossier_temp(self):
        chemin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, chemin, ignore_errors=True)
        return chemin


class Versions(unittest.TestCase):
    def test_sorties_reelles(self):
        self.assertEqual(outils.version("Version v0.18.0 (commit b22ad4bda)\nBuild: GCC 15.2.0"), (0, 18, 0))
        self.assertEqual(outils.version("Warning: client version is 0.32.15"), (0, 32, 15))
        self.assertEqual(outils.version("uv 0.12.7 (x86_64-unknown-linux-gnu)"), (0, 12, 7))
        self.assertEqual(outils.version("v0.40.15"), (0, 40, 15))

    def test_version_sans_correctif(self):
        self.assertEqual(outils.version("4.8-stable"), (4, 8, 0))

    def test_pas_de_version(self):
        self.assertIsNone(outils.version("rien ici"))
        self.assertIsNone(outils.version(""))
        self.assertIsNone(outils.version(None))

    def test_ge_proton(self):
        self.assertEqual(outils.version_ge("GE-Proton11-12"), (11, 12))
        self.assertEqual(outils.version_ge("GE-Proton11-12-x86_64"), (11, 12))
        self.assertEqual(outils.version_ge("GE-Proton9-27"), (9, 27))
        self.assertIsNone(outils.version_ge("Proton-CachyOS Latest"))
        self.assertGreater(outils.version_ge("GE-Proton11-2"), outils.version_ge("GE-Proton10-30"))

    def test_godot(self):
        self.assertEqual(outils.version("Godot_v4.7.2-stable_linux.x86_64"), (4, 7, 2))
        self.assertEqual(outils.fmt((0, 30, 0)), "0.30.0")


class Releases(unittest.TestCase):
    RELEASE = {"tag_name": "v1.2.3", "assets": [
        {"name": "a.AppImage", "browser_download_url": "https://x/a", "digest": "sha256:abc"},
        {"name": "b.tar.zst", "browser_download_url": "https://x/b", "digest": None},
    ]}

    def test_asset_trouve(self):
        self.assertEqual(outils.asset(self.RELEASE, "a.AppImage"), ("https://x/a", "sha256:abc"))

    def test_asset_sans_somme(self):
        self.assertEqual(outils.asset(self.RELEASE, "b.tar.zst"), ("https://x/b", ""))

    def test_asset_absent(self):
        with self.assertRaises(RuntimeError):
            outils.asset(self.RELEASE, "c.zip")


class Telechargement(DossiersTemp, unittest.TestCase):
    def setUp(self):
        self.dossier = self._dossier_temp()
        self.source = self.dossier / "source.bin"
        self.source.write_bytes(b"contenu de test" * 1000)
        self.somme = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def test_somme_correcte(self):
        dest = outils.telecharger(self.source.as_uri(), self.dossier / "dest.bin", "sha256:" + self.somme)
        self.assertEqual(dest.read_bytes(), self.source.read_bytes())
        self.assertFalse((self.dossier / "dest.bin.part").exists())

    def test_somme_incorrecte_refusee(self):
        with self.assertRaises(RuntimeError):
            outils.telecharger(self.source.as_uri(), self.dossier / "dest.bin", "sha256:" + "0" * 64)
        self.assertFalse((self.dossier / "dest.bin").exists())
        self.assertFalse((self.dossier / "dest.bin.part").exists())

    def test_sans_somme_refuse(self):
        with self.assertRaises(RuntimeError):
            outils.telecharger(self.source.as_uri(), self.dossier / "dest.bin", "")


class DetectionJeu(unittest.TestCase):
    def test_jeu_proton(self):
        self.assertTrue(commun.est_jeu("JeuDeCourse.ex", b"HOME=/h\0SteamGameId=480\0X=1\0"))

    def test_jeu_umu(self):
        self.assertTrue(commun.est_jeu("jeu-umu.exe", b"SteamGameId=umu-exemple\0"))

    def test_processus_annexes_ignores(self):
        env = b"SteamGameId=480\0"
        for comm in ("wineserver", "steam", "steamwebhelper", "winedevice.exe", "explorer.exe", "libfoo.so"):
            self.assertFalse(commun.est_jeu(comm, env), comm)

    def test_pas_de_jeu(self):
        self.assertFalse(commun.est_jeu("konsole", b"HOME=/h\0"))
        self.assertFalse(commun.est_jeu("jeu", b"SteamGameId=0\0"))
        self.assertFalse(commun.est_jeu("jeu", b"NotSteamGameId=12\0"))


class Doublons(DossiersTemp, unittest.TestCase):
    def test_binaire_qui_masque_brew(self):
        local, brew = self._dossier_temp(), self._dossier_temp()
        for nom in ("gh", "outil-perso"):
            (local / nom).write_text("x")
            os.chmod(local / nom, 0o755)
        (brew / "gh").write_text("x")
        (brew / "node").write_text("x")
        (local / "node").symlink_to(brew / "node")  # lien vers brew : pas un doublon
        self.assertEqual(doublons.doublons_brew(local, brew), ["gh"])

    def test_scripts_pip_ignores(self):
        """Un point d'entrée pip --user est lié à son paquet Python : pas une vieille copie."""
        local, brew = self._dossier_temp(), self._dossier_temp()
        (local / "pip3").write_text("#!/usr/bin/python3\nimport sys\n"
                                    "from pip._internal.cli.main import main\n")
        (local / "yt-dlp").write_bytes(b"#!/usr/bin/env python3\nPK\x03\x04zipapp")
        for nom in ("pip3", "yt-dlp"):
            os.chmod(local / nom, 0o755)
            (brew / nom).write_text("x")
        self.assertEqual(doublons.doublons_brew(local, brew), ["yt-dlp"])


class Service(unittest.TestCase):
    def test_execstart_absolu(self):
        source = "[Service]\nExecStart=vicinae server --replace\nRestart=always\n"
        attendu = "[Service]\nExecStart=/h/.local/bin/vicinae server --replace\nRestart=always\n"
        self.assertEqual(vicinae.reecrire_service(source, "/h/.local/bin/vicinae"), attendu)


class Notification(unittest.TestCase):
    R = outils.Resultat

    def test_mise_a_jour_notifiee(self):
        res = [self.R("ollama", outils.MIS_A_JOUR, "Ollama 0.32.15 → 0.40.15", "")]
        self.assertTrue(rapport.a_notifier(res, []))

    def test_echec_notifie(self):
        res = [self.R("uv", outils.ECHEC, "uv : erreur", "")]
        self.assertTrue(rapport.a_notifier(res, []))

    def test_action_manuelle_notifiee_une_seule_fois(self):
        res = [self.R("ge-proton", outils.MANUEL, "GE-Proton11-13 disponible", "")]
        self.assertTrue(rapport.a_notifier(res, []))
        self.assertFalse(rapport.a_notifier(res, rapport.cles_manuelles(res)))

    def test_rien_a_signaler(self):
        res = [self.R("uv", outils.A_JOUR, "uv 0.13.7", "")]
        self.assertFalse(rapport.a_notifier(res, []))

ELF = b"\x7fELF" + b"\0" * 60


class AppImages(DossiersTemp, unittest.TestCase):
    """Mises à jour des AppImages : faux dépôt GitHub (fichiers file://), tout dans un dossier temporaire."""

    def setUp(self):
        self.racine = self._dossier_temp()
        self.cache = self.racine / "cache"
        self.etat = self.racine / "etat"
        self.etat.mkdir()
        self.dossier = self.racine / "apps"
        self.dossier.mkdir()
        self.proc = self.racine / "proc"
        self.proc.mkdir()
        for patch in (mock.patch.object(appimages, "CACHE", self.cache), mock.patch.object(appimages, "ETAT", self.etat)):
            patch.start()
            self.addCleanup(patch.stop)

    def fichier(self, nom, contenu, jours=0):
        f = self.dossier / nom
        f.write_bytes(contenu)
        f.chmod(0o755)
        t = 1_700_000_000 - jours * 86400
        os.utime(f, (t, t))
        return f

    def release(self, tag, nom_asset, contenu, publiee="2023-11-20T00:00:00Z", digest=None):
        src = self.racine / ("src-" + tag)
        src.write_bytes(contenu)
        somme = digest or "sha256:" + hashlib.sha256(contenu).hexdigest()
        return {"tag_name": tag, "published_at": publiee, "body": "notes " + tag,
                "assets": [{"name": nom_asset, "browser_download_url": src.as_uri(), "digest": somme}]}

    def editeur(self):
        return appimages.AppImage("editeur", "Éditeur", "exemple/editeur",
                          "editeur-linux-x86_64.AppImage", self.dossier,
                          "editeur-linux-x86_64.AppImage", [])

    def lanceur(self, desktop):
        return appimages.AppImage("lanceur", "Lanceur", "exemple/lanceur",
                          r"Lanceur-.*x86_64\.AppImage", self.dossier,
                          "Lanceur-*-x86_64.AppImage", [desktop])

    def lancer(self, app, release, simulation=False):
        with mock.patch.object(appimages, "github", return_value=release):
            return appimages.maj_appimage(app, simulation, self.proc)

    def etat_lu(self):
        return json.loads((self.etat / "appimages.json").read_text())

    def test_premier_passage_somme_egale(self):
        actuel = ELF + b"v1"
        f = self.fichier("editeur-linux-x86_64.AppImage", actuel)
        r = self.lancer(self.editeur(), self.release("v1", f.name, actuel))
        self.assertEqual(r.etat, outils.A_JOUR)
        self.assertEqual(self.etat_lu()["editeur"]["tag"], "v1")
        self.assertEqual(f.read_bytes(), actuel)

    def test_premier_passage_release_plus_ancienne_pas_de_retrogradation(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"build recent")
        r = self.lancer(self.editeur(),
                        self.release("v1", f.name, ELF + b"ancienne", publiee="2023-01-01T00:00:00Z"))
        self.assertEqual(r.etat, outils.A_JOUR)
        self.assertEqual(f.read_bytes(), ELF + b"build recent")
        self.assertFalse(f.with_name(f.name + ".ancien").exists())
        self.assertEqual(self.etat_lu()["editeur"]["tag"], "v1")

    def test_simulation_annonce_sans_rien_telecharger(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        r = self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"), simulation=True)
        self.assertEqual(r.etat, outils.A_FAIRE)
        self.assertIn("Éditeur v1 → v2", r.message)
        self.assertFalse(self.cache.exists())
        self.assertEqual(f.read_bytes(), ELF + b"v1")

    def etat_ecrit(self, d):
        (self.etat / "appimages.json").write_text(json.dumps(d))

    def test_mise_a_jour_editeur_garde_l_ancienne(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        r = self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"))
        self.assertEqual(r.etat, outils.MIS_A_JOUR)
        self.assertEqual((r.de, r.vers, r.notes), ("v1", "v2", "notes v2"))
        self.assertEqual(f.read_bytes(), ELF + b"v2")
        self.assertTrue(os.access(f, os.X_OK))
        self.assertEqual(f.with_name(f.name + ".ancien").read_bytes(), ELF + b"v1")
        self.assertEqual(self.etat_lu()["editeur"]["tag"], "v2")

    def test_une_seule_generation_ancienne(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"))
        self.lancer(self.editeur(), self.release("v3", f.name, ELF + b"v3"))
        self.assertEqual(f.with_name(f.name + ".ancien").read_bytes(), ELF + b"v2")

    def test_mise_a_jour_lanceur_ecrit_nouveau_fichier_et_desktop(self):
        ancien = self.fichier("Lanceur-0.7-x86_64.AppImage", ELF + b"0.7")
        desktop = self.racine / "lanceur.desktop"
        desktop.write_text("[Desktop Entry]\nName=Lanceur\nExec=%s\n\n[Desktop Action play]\nExec=%s --play\n"
                           % (ancien, ancien))
        self.etat_ecrit({"lanceur": {"tag": "0.7", "sha256": "x"}})
        nom = "Lanceur-0.8-x86_64.AppImage"
        r = self.lancer(self.lanceur(desktop), self.release("0.8", nom, ELF + b"0.8"))
        self.assertEqual(r.etat, outils.MIS_A_JOUR)
        nouveau = self.dossier / nom
        self.assertEqual(nouveau.read_bytes(), ELF + b"0.8")
        self.assertTrue(os.access(nouveau, os.X_OK))
        self.assertFalse(ancien.exists())
        self.assertEqual(ancien.with_name(ancien.name + ".ancien").read_bytes(), ELF + b"0.7")
        execs = [l for l in desktop.read_text().splitlines() if l.startswith("Exec=")]
        self.assertEqual(execs, ["Exec=%s" % nouveau, "Exec=%s --play" % nouveau])
        self.assertEqual(self.etat_lu()["lanceur"]["tag"], "0.8")

    def test_somme_incorrecte_rien_remplace(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        faux = self.release("v2", f.name, ELF + b"v2", digest="sha256:" + "0" * 64)
        with self.assertRaises(RuntimeError):
            self.lancer(self.editeur(), faux)
        self.assertEqual(f.read_bytes(), ELF + b"v1")
        self.assertFalse(f.with_name(f.name + ".ancien").exists())
        self.assertEqual(self.etat_lu()["editeur"]["tag"], "v1")

    def test_pas_un_elf_rien_remplace(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        with self.assertRaises(RuntimeError):
            self.lancer(self.editeur(), self.release("v2", f.name, b"<html>erreur</html>"))
        self.assertEqual(f.read_bytes(), ELF + b"v1")

    def test_module_transforme_l_erreur_en_echec(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        faux = self.release("v2", f.name, ELF + b"v2", digest="aucune")
        app = self.editeur()
        with mock.patch.object(appimages, "appimages_suivies", return_value=[app]), \
                mock.patch.object(appimages, "github", return_value=faux), \
                mock.patch.object(appimages, "PROC", self.proc):
            res = appimages.mod_appimages(False)
        self.assertEqual([r.etat for r in res], [outils.ECHEC])
        self.assertEqual(f.read_bytes(), ELF + b"v1")

    def test_appimages_suivies_lues_dans_la_configuration(self):
        conf = ("[[majapps.appimages]]\ncle = \"emulateur\"\nnom = \"Émulateur\"\ndepot = \"exemple/emulateur\"\n"
                "motif_asset = 'emu-.*x86_64\\.AppImage'\ndossier = \"~/Applications/Emulateur\"\n"
                "motif_fichier = \"emu-*-x86_64.AppImage\"\ndesktop = [\"~/.local/share/applications/emu.desktop\"]\n")
        with configuration(conf):
            self.assertEqual(appimages.appimages_suivies(), [appimages.AppImage(
                "emulateur", "Émulateur", "exemple/emulateur", r"emu-.*x86_64\.AppImage",
                Path.home() / "Applications/Emulateur", "emu-*-x86_64.AppImage",
                [Path.home() / ".local/share/applications/emu.desktop"])])

    def test_sans_configuration_aucune_appimage(self):
        with configuration(""), mock.patch.object(appimages, "github", side_effect=AssertionError("pas de réseau")):
            self.assertEqual(appimages.appimages_suivies(), [])
            self.assertEqual(appimages.mod_appimages(True), [])

    def test_appimage_en_cours_d_utilisation_reportee(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        pid = self.proc / "4242"
        pid.mkdir()
        (pid / "cmdline").write_bytes(b"/bin/sh\0" + str(f).encode() + b"\0--play\0")
        r = self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"))
        self.assertEqual(r.etat, outils.REPORTE)
        self.assertIn("en cours d'utilisation", r.details)
        self.assertEqual(f.read_bytes(), ELF + b"v1")

    def test_detection_par_exe_et_par_montage(self):
        f = self.fichier("a.AppImage", ELF)
        pid = self.proc / "1"
        pid.mkdir()
        os.symlink(f, pid / "exe")
        self.assertTrue(appimages.appimage_en_cours(f, self.proc))
        os.unlink(pid / "exe")
        self.assertFalse(appimages.appimage_en_cours(f, self.proc))
        (self.proc / "mounts").write_text("%s /tmp/.mount_aXyZ fuse.a.AppImage ro 0 0\n" % f)
        self.assertTrue(appimages.appimage_en_cours(f, self.proc))

    def bb_installe(self, desktops):
        ancien = self.fichier("Lanceur-0.7-x86_64.AppImage", ELF + b"0.7")
        for d in desktops:
            d.write_text("[Desktop Entry]\nExec=%s\n\n[Desktop Action play]\nExec=%s --play\n" % (ancien, ancien))
        self.etat_ecrit({"lanceur": {"tag": "0.7", "sha256": "x"}})
        return ancien

    def test_lanceur_une_seule_generation_ancienne(self):
        desktop = self.racine / "lanceur.desktop"
        self.bb_installe([desktop])
        app = self.lanceur(desktop)
        for v in ("0.8", "0.9"):
            self.lancer(app, self.release(v, "Lanceur-%s-x86_64.AppImage" % v, ELF + v.encode()))
        anciens = sorted(f.name for f in self.dossier.glob("*.ancien"))
        self.assertEqual(anciens, ["Lanceur-0.8-x86_64.AppImage.ancien"])

    def test_devient_utilise_pendant_le_telechargement(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        with mock.patch.object(appimages, "appimage_en_cours", side_effect=[False, True]):
            r = self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"))
        self.assertEqual(r.etat, outils.REPORTE)
        self.assertEqual(f.read_bytes(), ELF + b"v1")
        self.assertFalse(f.with_name(f.name + ".ancien").exists())
        self.assertEqual(list(self.cache.glob("*")), [])
        self.assertEqual(self.etat_lu()["editeur"]["tag"], "v1")

    def test_echec_de_l_ancien_apres_remplacement_reste_une_mise_a_jour(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        blocage = f.with_name(f.name + ".ancien")
        blocage.mkdir()
        (blocage / "x").write_text("x")
        r = self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"))
        self.assertEqual(r.etat, outils.MIS_A_JOUR)
        self.assertIn("ancien", r.details)
        self.assertEqual(f.read_bytes(), ELF + b"v2")
        self.assertEqual(self.etat_lu()["editeur"]["tag"], "v2")

    def test_echec_d_ecriture_de_l_etat_reste_une_mise_a_jour(self):
        f = self.fichier("editeur-linux-x86_64.AppImage", ELF + b"v1")
        self.etat_ecrit({"editeur": {"tag": "v1", "sha256": "x"}})
        with mock.patch.object(appimages, "noter_appimage", side_effect=OSError("disque plein")):
            r = self.lancer(self.editeur(), self.release("v2", f.name, ELF + b"v2"))
        self.assertEqual(r.etat, outils.MIS_A_JOUR)
        self.assertIn("disque plein", r.details)
        self.assertEqual(f.read_bytes(), ELF + b"v2")

    def test_desktop_non_reconnu_echec_et_rien_change(self):
        d1, d2 = self.racine / "a.desktop", self.racine / "b.desktop"
        ancien = self.bb_installe([d1])
        d2.write_text("[Desktop Entry]\nExec=sh -c '%s --play'\n" % ancien)
        avant = (d1.read_text(), d2.read_text())
        with self.assertRaises(RuntimeError):
            self.lancer(appimages.AppImage("lanceur", "Lanceur", "d/b", r"Lanceur-.*x86_64\.AppImage",
                                   self.dossier, "Lanceur-*-x86_64.AppImage", [d1, d2]),
                        self.release("0.8", "Lanceur-0.8-x86_64.AppImage", ELF + b"0.8"))
        self.assertEqual((d1.read_text(), d2.read_text()), avant)
        self.assertTrue(ancien.exists())
        self.assertFalse((self.dossier / "Lanceur-0.8-x86_64.AppImage").exists())
        self.assertFalse(ancien.with_name(ancien.name + ".ancien").exists())

    def test_retour_arriere_ne_reecrit_que_les_fichiers_modifies(self):
        d1, d2 = self.racine / "a.desktop", self.racine / "b.desktop"
        ancien = self.bb_installe([d1, d2])
        avant = (d1.read_text(), d2.read_text())
        vrai = appimages.ecrire_atomique
        ecrits = []

        def ecrire(chemin, texte):
            ecrits.append(chemin)
            if chemin == d2:
                raise OSError("écriture impossible")
            vrai(chemin, texte)

        app = appimages.AppImage("lanceur", "Lanceur", "d/b", r"Lanceur-.*x86_64\.AppImage",
                         self.dossier, "Lanceur-*-x86_64.AppImage", [d1, d2])
        with mock.patch.object(appimages, "ecrire_atomique", ecrire), self.assertRaises(OSError):
            self.lancer(app, self.release("0.8", "Lanceur-0.8-x86_64.AppImage", ELF + b"0.8"))
        self.assertEqual((d1.read_text(), d2.read_text()), avant)
        self.assertEqual(ecrits, [d1, d2, d1])
        self.assertTrue(ancien.exists())
        self.assertFalse((self.dossier / "Lanceur-0.8-x86_64.AppImage").exists())


class LinStat(unittest.TestCase):
    """mod_linstat sur un faux dépôt et un faux `run` : aucun vrai git, aucun vrai pull."""

    AVANT = "a" * 40
    APRES = "b" * 40

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.depot = Path(tmp.name) / "linstat"
        self.appels = []
        self.reponses = {}

    def installer_depot(self):
        self.depot.mkdir()

    def faux_run(self, cmd, timeout=120, cwd=None):
        cmd = [str(c) for c in cmd]
        self.appels.append((cmd, cwd))
        texte = " ".join(cmd)
        for motif, reponse in self.reponses.items():
            if motif in texte:
                return reponse
        return 0, ""

    def lancer(self, simulation):
        with mock.patch.object(linstat, "DEPOT", self.depot), \
                mock.patch.object(linstat, "run", self.faux_run):
            return linstat.mod_linstat(simulation)

    def commandes(self):
        return [" ".join(c) for c, _ in self.appels]

    def a_jour(self):
        self.reponses = {"rev-parse HEAD": (0, self.AVANT + "\n"),
                         "rev-parse @{u}": (0, self.AVANT + "\n")}

    def en_retard(self):
        self.reponses = {"rev-parse HEAD": (0, self.AVANT + "\n"),
                         "rev-parse @{u}": (0, self.APRES + "\n"),
                         "log --oneline": (0, "bbbbbbb correctif\n")}

    def test_linstat_absent_rien(self):
        self.assertIsNone(self.lancer(False))
        self.assertEqual(self.appels, [])

    def test_linstat_a_jour(self):
        self.installer_depot()
        self.a_jour()
        r = self.lancer(False)
        self.assertEqual(r.etat, outils.A_JOUR)
        self.assertEqual(r.message, "LinStat aaaaaaa à jour")
        self.assertFalse([c for c in self.commandes() if "merge --ff-only" in c or "pull" in c or "install.sh" in c])

    def test_linstat_simulation_annonce(self):
        self.installer_depot()
        self.en_retard()
        r = self.lancer(True)
        self.assertEqual(r.etat, outils.A_FAIRE)
        self.assertFalse([c for c in self.commandes() if "merge --ff-only" in c or "pull" in c or "install.sh" in c])

    def test_linstat_mis_a_jour(self):
        self.installer_depot()
        self.en_retard()
        r = self.lancer(False)
        self.assertEqual((r.etat, r.de, r.vers), (outils.MIS_A_JOUR, "aaaaaaa", "bbbbbbb"))
        self.assertIn("correctif", r.notes)
        cmds = self.commandes()
        attendu = ["fetch", "rev-parse HEAD", "rev-parse @{u}", "diff --quiet", "merge --ff-only " + self.APRES,
                   "bash install.sh"]
        position = 0
        for cmd in cmds:
            if position < len(attendu) and attendu[position] in cmd:
                position += 1
        self.assertEqual(position, len(attendu), cmds)
        install = [cwd for cmd, cwd in self.appels if cmd[-2:] == ["bash", "install.sh"]]
        self.assertEqual(install, [self.depot])

    def test_linstat_avance_jusqu_au_commit_verifie_seulement(self):
        """Revue finale I2 (trou de V48) : `git pull` referait un fetch, et HEAD pourrait dépasser le commit dont
        install.sh a été comparé ; l'avance rapide va exactement à ce commit, sans réseau."""
        self.installer_depot()
        self.en_retard()
        self.lancer(False)
        cmds = self.commandes()
        self.assertFalse([c for c in cmds if " pull" in c], cmds)
        avances = [c for c in cmds if "merge --ff-only" in c]
        self.assertEqual(len(avances), 1, cmds)
        self.assertTrue(avances[0].endswith("merge --ff-only " + self.APRES), avances[0])
        self.assertEqual([c for c in cmds if " fetch" in c], [cmds[0]])     # un seul fetch, au début
        self.assertIn("diff --quiet %s %s -- install.sh" % (self.AVANT, self.APRES), " | ".join(cmds))

    def test_linstat_git_jamais_interactif(self):
        """Revue finale M4 : la nuit, aucun git du module ne peut attendre un identifiant (dépôt devenu privé…)."""
        self.installer_depot()
        self.en_retard()
        self.lancer(False)
        gits = [c for c, _ in self.appels if "git" in c]
        self.assertEqual(len(gits), len(self.appels) - 1)          # tout, sauf bash install.sh
        for cmd in gits:
            self.assertEqual(cmd[:7], ["env", "GIT_TERMINAL_PROMPT=0", "GIT_ASKPASS=true", "git",
                                       "-c", "credential.helper=", "-C"], cmd)
            self.assertEqual(cmd[7], str(self.depot), cmd)

    def test_docstring_de_maj_apps_cite_linstat(self):
        import centre_bazzite.majapps as paquet
        self.assertIn("linstat    (linstat.py)", paquet.__doc__)

    def test_linstat_avance_rapide_refusee_echec(self):
        self.installer_depot()
        self.en_retard()
        self.reponses["merge --ff-only"] = (1, "fatal: Not possible to fast-forward")
        r = self.lancer(False)
        self.assertEqual(r.etat, outils.ECHEC)
        self.assertEqual(r.message, "LinStat : git merge --ff-only a échoué")
        self.assertFalse([c for c in self.commandes() if c.endswith("bash install.sh")])

    def test_linstat_rev_parse_en_echec(self):
        self.installer_depot()
        self.reponses = {"rev-parse HEAD": (128, "fatal: no such branch"),
                         "rev-parse @{u}": (128, "fatal: no upstream")}
        r = self.lancer(False)
        self.assertEqual((r.etat, r.message), (outils.ECHEC, "LinStat : état du dépôt illisible"))
        self.assertFalse([c for c in self.commandes() if "merge --ff-only" in c or "pull" in c or "install.sh" in c])

    def test_linstat_rev_parse_pas_un_sha(self):
        self.installer_depot()
        self.reponses = {"rev-parse HEAD": (0, self.AVANT + "\n"),
                         "rev-parse @{u}": (0, "fatal: pas un sha\n")}
        r = self.lancer(False)
        self.assertEqual(r.etat, outils.ECHEC)
        self.assertFalse([c for c in self.commandes() if "merge --ff-only" in c or "pull" in c or "install.sh" in c])

    def test_linstat_install_amont_en_echec(self):
        self.installer_depot()
        self.en_retard()
        self.reponses["bash install.sh"] = (1, "boum")
        r = self.lancer(False)
        self.assertEqual((r.etat, r.message), (outils.ECHEC, "LinStat : install.sh a échoué"))

    def test_linstat_install_change_n_avance_pas(self):
        """Task 9 : install.sh est comparé AVANT l'avance rapide. Changé : résultat manuel, HEAD n'avance pas, donc le
        rappel revient chaque nuit jusqu'à la relecture."""
        self.installer_depot()
        self.en_retard()
        self.reponses["diff --quiet"] = (1, "")
        r = self.lancer(False)
        self.assertEqual(r.etat, outils.MANUEL)
        self.assertEqual(r.message, "LinStat : install.sh a changé — relis-le, puis lance "
                                    "git -C ~/developer/linstat merge --ff-only @{u} et bash ~/developer/linstat/install.sh")
        self.assertEqual((r.de, r.vers), ("aaaaaaa", "bbbbbbb"))
        self.assertIn("correctif", r.notes)
        cmds = self.commandes()
        self.assertFalse([c for c in cmds if " merge" in c and "merge-base" not in c], cmds)
        self.assertFalse([c for c in cmds if c.endswith("bash install.sh")], cmds)
        self.assertIn("diff --quiet %s %s -- install.sh" % (self.AVANT, self.APRES), " | ".join(cmds))

    def test_linstat_en_avance_rien_a_tirer(self):
        self.installer_depot()
        self.en_retard()
        self.reponses["merge-base --is-ancestor"] = (1, "")
        for simulation in (False, True):
            r = self.lancer(simulation)
            self.assertEqual(r.etat, outils.A_JOUR)
        self.assertFalse([c for c in self.commandes() if "merge --ff-only" in c or "pull" in c or "install.sh" in c])

    def test_modules_contient_linstat(self):
        noms = [nom for nom, _ in principal.MODULES]
        self.assertEqual(noms.index("linstat") + 1, noms.index("doublons"))
        self.assertEqual(noms.index("linstat"), noms.index("appimages") + 1)


INSTALL = Path(__file__).resolve().parent.parent / "install.sh"
FAUX_GIT = """#!/bin/bash
# Faux git : « clone <url> <dossier> » crée un dépôt dont install.sh note chaque passage et pose linstat.py.
[ "$1" = clone ] || exit 2
[ -e "$HOME/clone-impossible" ] && exit 128
mkdir -p "$3/.git"
cat > "$3/install.sh" <<'FIN'
echo passage >> "$HOME/installeur-amont"
mkdir -p "$HOME/.local/share/linstat" && touch "$HOME/.local/share/linstat/linstat.py"
FIN
"""


class InstallationLinStat(unittest.TestCase):
    """Revue finale M3 : le bloc LinStat d'install.sh, dans un HOME temporaire avec un faux git (aucun réseau).
    L'installeur amont ne tourne qu'après un clone neuf ou s'il manque linstat.py : sinon, relancer install.sh
    exécuterait un install.sh amont non relu, ce que V48 évite pour maj-apps."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / "bin").mkdir()
        (self.home / "bin" / "git").write_text(FAUX_GIT, encoding="utf-8")
        (self.home / "bin" / "git").chmod(0o755)

    def lancer(self):
        texte = INSTALL.read_text(encoding="utf-8")
        bloc = texte.split("# debut-linstat\n")[1].split("# fin-linstat")[0]
        env = dict(os.environ, HOME=str(self.home), PATH=f"{self.home / 'bin'}:{os.environ['PATH']}")
        r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + bloc], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def passages(self):
        f = self.home / "installeur-amont"
        return len(f.read_text().splitlines()) if f.exists() else 0

    def test_clone_neuf_puis_installeur_amont(self):
        sortie = self.lancer()
        self.assertIn("LinStat : dépôt cloné", sortie)
        self.assertIn("LinStat : installé", sortie)
        self.assertEqual(self.passages(), 1)

    def test_relance_sans_rejouer_l_installeur_amont(self):
        self.lancer()
        sortie = self.lancer()
        self.assertEqual(self.passages(), 1)
        self.assertIn("LinStat : déjà installé", sortie)

    def test_installeur_amont_rejoue_si_linstat_manque(self):
        self.lancer()
        (self.home / ".local" / "share" / "linstat" / "linstat.py").unlink()
        sortie = self.lancer()
        self.assertEqual(self.passages(), 2)
        self.assertIn("LinStat : installé", sortie)

    def test_clone_impossible_n_arrete_rien(self):
        (self.home / "clone-impossible").touch()
        sortie = self.lancer()
        self.assertIn("installation impossible (hors ligne ?)", sortie)
        self.assertEqual(self.passages(), 0)


class Rapport(unittest.TestCase):
    def test_redaction(self):
        res = [outils.Resultat("uv", outils.A_JOUR, "uv 0.13.7 à jour", ""),
               outils.Resultat("ollama", outils.MIS_A_JOUR, "Ollama 0.32.15 → 0.40.15", "détail")]
        texte = rapport.redaction(res, simulation=False)
        self.assertIn("[·] uv 0.13.7 à jour", texte)
        self.assertIn("[+] Ollama 0.32.15 → 0.40.15", texte)
        self.assertIn("    détail", texte)


class Changements(unittest.TestCase):
    def test_resultat_a_des_champs_optionnels(self):
        r = outils.Resultat("uv", outils.A_JOUR, "uv 0.13.7", "")
        self.assertIsNone(r.de)
        self.assertIsNone(r.vers)
        self.assertIsNone(r.notes)

    def test_changements_historique(self):
        res = [outils.Resultat("ollama", outils.MIS_A_JOUR, "t", "", "0.32.15", "0.40.15", "notes"),
               outils.Resultat("uv", outils.A_JOUR, "uv 0.13.7", "")]
        self.assertEqual(rapport.changements(res),
                         [{"module": "ollama", "de": "0.32.15", "vers": "0.40.15", "notes": "notes"}])


class Distrobox(unittest.TestCase):
    """Conteneurs distrobox : erreur lisible, journal complet, Messagerie ouvert, réseau absent."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.etat = Path(tmp.name) / "etat"
        self.proc = Path(tmp.name) / "proc"
        self.proc.mkdir()
        self.appels = []

    def processus(self, comm):
        d = self.proc / str(1000 + len(list(self.proc.iterdir())))
        d.mkdir()
        (d / "comm").write_text(comm + "\n")

    def lancer(self, conteneurs, reponses):
        """conteneurs : [(nom, etat)] ; reponses : {nom: (code, sortie)} pour `distrobox upgrade nom`."""
        def faux_run(cmd, timeout=120, cwd=None):
            cmd = [str(c) for c in cmd]
            self.appels.append(cmd)
            if cmd[:2] == ["podman", "ps"]:
                return 0, "".join("%s|%s\n" % c for c in conteneurs)
            if cmd[:2] == ["distrobox", "upgrade"]:
                return reponses[cmd[2]]
            return 0, ""
        with mock.patch.object(distrobox, "run", faux_run), mock.patch.object(distrobox, "PROC", self.proc), \
                mock.patch.object(distrobox, "ETAT", self.etat):
            return distrobox.mod_distrobox(False)

    def upgrades(self):
        return [c[2] for c in self.appels if c[:2] == ["distrobox", "upgrade"]]

    def test_erreur_lisible_sans_l_en_tete_colore(self):
        # run() rend stdout puis stderr : l'en-tête coloré de distrobox (stderr) arrive en dernier.
        sortie = ("Lecture des listes de paquets...\n"
                  "E: Impossible de récupérer https://downloads.exemple.org/x.deb  Délai d'attente dépassé\n"
                  "\x1b[1;31m Upgrading boite...\n\x1b[0m")
        res = self.lancer([("boite", "running")], {"boite": (100, sortie)})
        self.assertEqual(res.etat, outils.REPORTE)       # erreur de téléchargement : on réessaiera
        self.assertIn("E: Impossible de récupérer", res.details)
        self.assertNotIn("\x1b", res.details)

    def test_vraie_erreur_reste_un_echec_avec_son_journal(self):
        sortie = "dpkg: erreur de traitement du paquet truc (--configure)\nE: Sub-process /usr/bin/dpkg returned an error code (1)\n" \
                 "\x1b[1;31m Upgrading boite...\n\x1b[0m"
        res = self.lancer([("boite", "running")], {"boite": (100, sortie)})
        self.assertEqual(res.etat, outils.ECHEC)
        self.assertIn("boite : E: Sub-process /usr/bin/dpkg returned an error code (1)", res.details)
        journal = self.etat / "distrobox-boite.log"
        self.assertEqual(journal.read_text(), sortie)
        self.assertIn(str(journal), res.details)

    def test_sans_aucune_ligne_utile(self):
        res = self.lancer([("boite", "running")], {"boite": (1, "\x1b[1;31m Upgrading boite...\n\x1b[0m")})
        self.assertEqual(res.etat, outils.ECHEC)
        self.assertIn("boite : erreur sans message (code 1)", res.details)

    def test_messagerie_ouvert_reporte_sans_mise_a_jour(self):
        self.processus("messagerie")
        res = self.lancer([("messagerie", "running"), ("boite", "exited")],
                          {"boite": (0, "ok"), "messagerie": (0, "ok")})
        self.assertEqual(self.upgrades(), ["boite"])
        self.assertEqual(res.etat, outils.REPORTE)
        self.assertIn("messagerie : reporté, Messagerie est ouvert", res.details)

    def test_messagerie_ferme_mis_a_jour(self):
        self.processus("bash")
        res = self.lancer([("messagerie", "running")], {"messagerie": (0, "ok")})
        self.assertEqual(self.upgrades(), ["messagerie"])
        self.assertEqual(res.etat, outils.A_JOUR)

    def test_exclusions_et_applis_lues_dans_la_configuration(self):
        conf = ('[majapps.distrobox]\nexclure = { stable = "gardé stable" }\n'
                'applis = { bureau = ["bureau-bin", "Appli de bureau"] }\n')
        self.processus("bureau-bin")
        with configuration(conf):
            res = self.lancer([("stable", "running"), ("bureau", "running"), ("boite", "exited")],
                              {"boite": (0, "ok"), "bureau": (0, "ok"), "stable": (0, "ok")})
        self.assertEqual(self.upgrades(), ["boite"])
        self.assertEqual(res.etat, outils.REPORTE)
        self.assertIn("bureau : reporté, Appli de bureau est ouvert", res.details)
        self.assertIn("non mis à jour : stable (gardé stable)", res.details)

    def test_sans_configuration_tout_est_mis_a_jour(self):
        self.processus("messagerie")
        with configuration(""):
            res = self.lancer([("messagerie", "running"), ("stable", "exited")],
                              {"messagerie": (0, "ok"), "stable": (0, "ok")})
        self.assertEqual(self.upgrades(), ["messagerie", "stable"])
        self.assertEqual((res.etat, res.details), (outils.A_JOUR, ""))

    def test_echec_et_report_ensemble_restent_un_echec(self):
        self.processus("messagerie")
        res = self.lancer([("messagerie", "running"), ("boite", "running")],
                          {"boite": (100, "E: Sub-process /usr/bin/dpkg returned an error code (1)\n")})
        self.assertEqual(res.etat, outils.ECHEC)
        self.assertIn("messagerie : reporté", res.details)


class Principal(unittest.TestCase):
    """main() de bout en bout, sur de faux modules et un dossier d'état temporaire."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.etat = Path(tmp.name)
        self.notifier = mock.Mock()
        sortie = contextlib.redirect_stdout(io.StringIO())
        sortie.__enter__()
        self.addCleanup(sortie.__exit__, None, None, None)
        remplacements = {
            "ETAT": self.etat, "RAPPORT": self.etat / "rapport.txt",
            "HISTORIQUE": self.etat / "historique.jsonl", "NOTIFIE": self.etat / "deja-signale.json",
            "reseau_ok": lambda: True, "jeu_en_cours": lambda: None, "notifier": self.notifier}
        for nom, valeur in remplacements.items():
            patch = mock.patch.object(principal, nom, valeur)
            patch.start()
            self.addCleanup(patch.stop)

    def modules(self, *faux):
        patch = mock.patch.object(principal, "MODULES", list(faux))
        patch.start()
        self.addCleanup(patch.stop)

    def test_main_ecrit_l_historique_comme_avant(self):
        self.modules(("uv", lambda _s: outils.Resultat("uv", outils.A_JOUR, "uv 0.13.7 à jour", "")),
                     ("ollama", lambda _s: outils.Resultat("ollama", outils.MIS_A_JOUR,
                                                           "Ollama 0.32.15 → 0.40.15", "",
                                                           "0.32.15", "0.40.15", "notes")))
        self.assertEqual(principal.main(["--quiet"]), 0)
        lignes = (self.etat / "historique.jsonl").read_text().splitlines()
        derniere = json.loads(lignes[-1])
        self.assertEqual(set(derniere), {"date", "resultats", "changements"})
        self.assertEqual(derniere["changements"],
                         [{"module": "ollama", "de": "0.32.15", "vers": "0.40.15", "notes": "notes"}])
        self.assertTrue((self.etat / "rapport.txt").exists())
        self.notifier.assert_not_called()

    def test_main_reporte_si_jeu(self):
        self.modules(("uv", lambda _s: outils.Resultat("uv", outils.A_JOUR, "uv à jour", "")))
        with mock.patch.object(principal, "jeu_en_cours", lambda: "jeu.exe"):
            self.assertEqual(principal.main([]), outils.CODE_REPORTE)
        self.assertFalse((self.etat / "historique.jsonl").exists())

    def test_module_en_exception_devient_echec(self):
        def casse(_simulation):
            raise RuntimeError("panne")

        self.modules(("uv", casse))
        self.assertEqual(principal.main(["--quiet"]), 1)
        derniere = json.loads((self.etat / "historique.jsonl").read_text().splitlines()[-1])
        self.assertEqual([r["etat"] for r in derniere["resultats"]], ["échec"])


if __name__ == "__main__":
    unittest.main()
