import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from centre_bazzite import cli, points, sante
from tests import configuration

ECH = Path(__file__).parent / "echantillons"


def texte(nom):
    return (ECH / nom).read_text(encoding="utf-8")


class Lectures(unittest.TestCase):
    def test_lire_smart(self):
        s = sante.lire_smart(texte("smart-nvme.json"))
        self.assertEqual(s["usure"], 1)
        self.assertEqual(s["reserve"], 100)
        self.assertEqual(s["seuil_reserve"], 10)
        self.assertAlmostEqual(s["temperature"], 36.85, delta=0.1)
        self.assertEqual(s["erreurs_media"], 0)
        self.assertEqual(s["arrets_brutaux"], 49)
        self.assertAlmostEqual(s["ecrit_to"], 21.647739392, places=6)

    def test_lire_sensors(self):
        r = sante.lire_sensors(texte("sensors.json"))
        self.assertEqual(r["cpu"], 37.0)
        self.assertIsInstance(r["ssd"], float)

    def test_lire_sensors_tolere_les_trous(self):
        self.assertEqual(sante.lire_sensors("{}"), {"cpu": None, "ssd": None})

    def test_lire_nvidia(self):
        g = sante.lire_nvidia(texte("nvidia.csv"))
        self.assertEqual(g["nom"], "NVIDIA GeForce RTX 4070")
        self.assertEqual(g["temperature"], 47)
        self.assertEqual(g["watts"], 46.32)
        self.assertAlmostEqual(g["vram_utilisee_go"], 1232 / 1024, places=2)
        self.assertAlmostEqual(g["vram_totale_go"], 16303 / 1024, places=2)


class Volumes(unittest.TestCase):
    def test_volume_non_monte_absent(self):
        r = sante.volumes([("A", "/var"), ("B", "/nulle/part")], est_monte=lambda c: c == "/var")
        self.assertEqual([v["nom"] for v in r], ["A"])
        self.assertEqual(set(r[0]), {"nom", "chemin", "libre_go", "total_go", "pourcent_utilise"})
        self.assertGreater(r[0]["total_go"], 0)


class Journal(unittest.TestCase):
    def test_erreurs_journal_groupees(self):
        lignes = [
            {"MESSAGE": "boum", "SYSLOG_IDENTIFIER": "a"},
            {"MESSAGE": "boum", "SYSLOG_IDENTIFIER": "a"},
            {"MESSAGE": "pouf", "SYSLOG_IDENTIFIER": "b"},
            {"MESSAGE": "boum", "SYSLOG_IDENTIFIER": "a"},
        ]
        sortie = "\n".join(json.dumps(l) for l in lignes) + "\nnon json\n"
        with mock.patch("centre_bazzite.commun.run", return_value=(0, sortie)):
            r = sante.erreurs_journal()
        self.assertEqual(r[0], {"message": "boum", "source": "a", "nombre": 3})
        self.assertEqual(r[1]["nombre"], 1)

    def test_erreurs_journal_echantillon_et_limite(self):
        with mock.patch("centre_bazzite.commun.run", return_value=(0, texte("journal-err.jsonl"))):
            r = sante.erreurs_journal()
        self.assertLessEqual(len(r), 10)
        self.assertTrue(all(e["nombre"] >= 1 for e in r))

    def test_services_en_echec(self):
        sorties = [(0, "● foo.service loaded failed failed Foo\n"), (0, "")]
        with mock.patch("centre_bazzite.commun.run", side_effect=sorties) as m:
            self.assertEqual(sante.services_en_echec(), ["foo.service"])
        self.assertIn("--user", m.call_args_list[1].args[0])
        with mock.patch("centre_bazzite.commun.run", return_value=(0, texte("failed.txt"))):
            self.assertEqual(sante.services_en_echec(), [])

    def test_plantages(self):
        with mock.patch("centre_bazzite.commun.run", return_value=(0, texte("coredumps.json"))):
            r = sante.plantages()
        self.assertTrue(r)
        self.assertEqual(set(r[0]), {"exe", "signal", "date"})
        self.assertEqual(r[0]["exe"], "wine64-preloader")
        with mock.patch("centre_bazzite.commun.run", return_value=(1, "No coredumps found.")):
            self.assertEqual(sante.plantages(), [])


class Sources(unittest.TestCase):
    def test_ssd(self):
        dnvme = "/org/freedesktop/UDisks2/drives/NVMe_Exemple"
        dusb = "/org/freedesktop/UDisks2/drives/USB_Exemple"
        blocs = "/org/freedesktop/UDisks2/block_devices"
        tree = (f"/\n{blocs}/sda\n{blocs}/sda1\n{blocs}/nvme0n1\n{blocs}/nvme0n1p2\n"
                f"{blocs}/zram0\n{dnvme}\n{dusb}\n")

        def faux(cmd, **kw):
            cmd = list(cmd)
            if "tree" in cmd:
                return 0, tree
            if "org.freedesktop.UDisks2.Block" in cmd:
                disque = {f"{blocs}/nvme0n1": dnvme, f"{blocs}/sda": dusb}[cmd[4]]
                return 0, f'{{"type":"o","data":"{disque}"}}\n'
            if "SmartGetAttributes" in cmd:
                return 0, texte("smart-nvme.json")
            if "SmartPowerOnHours" in cmd:
                return 0, '{"type":"t","data":2847}'
            if "SmartCriticalWarning" in cmd:
                if cmd[4] == dusb:
                    return 1, "No such interface"
                return 0, '{"type":"as","data":["temperature"]}'
            if "Model" in cmd:
                n = "NVMe Exemple" if cmd[4] == dnvme else "USB Exemple SSD"
                b = "" if cmd[4] == dnvme else "usb"
                return 0, f'{{"type":"s","data":"{n}"}}\n{{"type":"s","data":"{b}"}}\n'
            return 1, ""

        with mock.patch("centre_bazzite.commun.run", side_effect=faux):
            r = sante.ssd()
        self.assertEqual(r[0]["modele"], "NVMe Exemple")
        self.assertEqual(r[0]["bus"], "nvme")
        self.assertEqual(r[0]["sante"]["usure"], 1)
        self.assertEqual(r[0]["sante"]["avertissements"], ["temperature"])
        self.assertEqual(r[0]["sante"]["heures"], 2847)
        self.assertEqual(r[1]["bus"], "usb")
        self.assertIsNone(r[1]["sante"])
        self.assertEqual(r[0]["peripherique"], "/dev/nvme0n1")
        self.assertEqual(r[1]["peripherique"], "/dev/sda")

    def test_ssd_un_smart_illisible_ne_perd_pas_les_autres(self):
        casse = "/org/freedesktop/UDisks2/drives/Casse"
        sain = "/org/freedesktop/UDisks2/drives/Sain"

        def faux(cmd, **kw):
            cmd = list(cmd)
            if "tree" in cmd:
                return 0, f"{casse}\n{sain}\n"
            if "SmartGetAttributes" in cmd:
                return 0, "pas du json" if cmd[4] == casse else texte("smart-nvme.json")
            if "SmartPowerOnHours" in cmd:
                return 0, '{"type":"t","data":10}'
            if "SmartCriticalWarning" in cmd:
                return 0, '{"type":"as","data":[]}'
            return 0, '{"type":"s","data":"X"}\n{"type":"s","data":""}\n'

        with mock.patch("centre_bazzite.commun.run", side_effect=faux):
            r = sante.ssd()
        self.assertEqual(len(r), 2)
        self.assertIsNone(r[0]["sante"])
        self.assertEqual(r[1]["sante"]["usure"], 1)

    def test_bilan_hebdo(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "rapport.json"
            self.assertIsNone(sante.bilan_hebdo(p))
            p.write_text('{"date": "x", "points": []}')
            self.assertEqual(sante.bilan_hebdo(p)["date"], "x")

    def test_gels(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(sante.gels(Path(t) / "absent"), {"nombre": 0, "dernier": None})
            (Path(t) / "20260101-a").mkdir()
            (Path(t) / "20260102-b").mkdir()
            (Path(t) / "watch.log").write_text("")
            (Path(t) / "20260101-c.txt").write_text("")
            self.assertEqual(sante.gels(Path(t)), {"nombre": 3, "dernier": "20260102-b"})

    def test_ollama(self):
        def faux(cmd, **kw):
            if "is-active" in cmd:
                return 0, "active\n"
            return 0, "ActiveEnterTimestamp=Mon 2026-11-09 10:00:00 CET\n"

        class Rep:
            def read(self):
                return b'{"models":[{"name":"glm-4.7-flash"}]}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        with mock.patch("centre_bazzite.commun.run", side_effect=faux):
            r = sante.ollama(ouvrir=lambda url, timeout: Rep())
        self.assertEqual(r, {"actif": True, "depuis": "Mon 2026-11-09 10:00:00 CET",
                             "modeles_charges": ["glm-4.7-flash"]})
        with mock.patch("centre_bazzite.commun.run", return_value=(3, "inactive\n")):
            r = sante.ollama(ouvrir=lambda *a, **k: self.fail("réseau"))
        self.assertEqual(r, {"actif": False, "depuis": None, "modeles_charges": []})


class Collecte(unittest.TestCase):
    def test_collecter_tolere_une_panne(self):
        rien = mock.Mock(return_value=[])
        with mock.patch.multiple(
                sante, ssd=mock.Mock(side_effect=RuntimeError("boum")), temperatures=rien,
                gpu=rien, volumes=rien, services_en_echec=rien, erreurs_journal=rien,
                plantages=rien, bilan_hebdo=rien, gels=rien, ollama=rien, lire_controles=rien,
                erreurs_disque=rien, non_montes=rien):
            r = sante.collecter()
        self.assertIsNone(r["ssd"])
        for cle in ("temperatures", "gpu", "volumes", "services_en_echec", "erreurs_journal",
                    "plantages", "bilan_hebdo", "gels", "ollama", "controles", "erreurs_disque",
                    "non_montes"):
            self.assertEqual(r[cle], [], cle)

    def test_collecter_lit_le_cache_des_controles(self):
        rien = mock.Mock(return_value=[])
        lancer = mock.Mock(side_effect=AssertionError("les contrôles ne sont jamais calculés ici"))
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "controles.json"
            cache.write_text('{"date": "2026-11-09T10:00:00", "image": null}', encoding="utf-8")
            with mock.patch.object(sante, "CONTROLES", cache), mock.patch.multiple(
                    sante, ssd=rien, temperatures=rien, gpu=rien, volumes=rien, services_en_echec=rien,
                    erreurs_journal=rien, plantages=rien, bilan_hebdo=rien, gels=rien, ollama=rien,
                    erreurs_disque=rien, non_montes=rien, controles=lancer):
                r = sante.collecter()
                self.assertEqual(r["controles"], {"date": "2026-11-09T10:00:00", "image": None})
                cache.unlink()
                self.assertIsNone(sante.collecter()["controles"])


class VolumesConfigures(unittest.TestCase):
    """Les volumes suivis et ceux qui doivent être montés viennent de la configuration locale, lue à l'appel."""
    CONF = ('[[volumes]]\nnom = "Atelier"\nchemin = "/var/mnt/ATELIER"\nattendu = true\n'
            '[[volumes]]\nnom = "Archives"\nchemin = "/var/mnt/ARCHIVES"\nattendu = true\nfacultatif = true\n')

    def test_volumes_mesures_sont_ceux_de_la_configuration(self):
        u = SimpleNamespace(free=1024 ** 3, total=2 * 1024 ** 3)
        with configuration(self.CONF), mock.patch.object(sante.shutil, "disk_usage", lambda c: u):
            self.assertEqual(sante.volumes_suivis(), [("Système", "/var"), ("Home", "/var/home"),
                                                      ("Atelier", "/var/mnt/ATELIER"), ("Archives", "/var/mnt/ARCHIVES")])
            self.assertEqual([v["nom"] for v in sante.volumes(est_monte=lambda c: c != "/var/mnt/ARCHIVES")],
                             ["Système", "Home", "Atelier"])

    def test_seuls_les_attendus_non_facultatifs_sont_signales(self):
        with configuration(self.CONF):
            self.assertEqual(sante.non_montes(est_monte=lambda c: False), ["/var/mnt/ATELIER"])
            self.assertEqual(sante.volumes_attendus(), [{"nom": "Atelier", "chemin": "/var/mnt/ATELIER"}])

    def test_sans_configuration_rien_n_est_attendu(self):
        with configuration(""):
            self.assertEqual(sante.volumes_suivis(), [("Système", "/var"), ("Home", "/var/home")])
            self.assertEqual(sante.non_montes(est_monte=lambda c: False), [])
            self.assertEqual(sante.volumes_attendus(), [])

    def test_collecter_donne_les_volumes_attendus(self):
        """La fenêtre écrit « Monté » avec leurs chemins : ils sont dans etat.json."""
        rien = mock.Mock(return_value=[])
        with configuration(self.CONF), mock.patch.multiple(
                sante, ssd=rien, temperatures=rien, gpu=rien, volumes=rien, services_en_echec=rien,
                erreurs_journal=rien, plantages=rien, bilan_hebdo=rien, gels=rien, ollama=rien, lire_controles=rien,
                erreurs_disque=rien, non_montes=rien):
            r = sante.collecter()
        self.assertEqual(r["attendus"], [{"nom": "Atelier", "chemin": "/var/mnt/ATELIER"}])


# --- Contrôles repris de bazzite-health ---

RIEN_D_INUTILISE = ("\nThese runtimes in installation 'system' are pinned and won't be removed; see flatpak-pin(1):\n"
                    "  runtime/org.freedesktop.Platform.GL.nvidia-615-78-08/x86_64/1.4\n"
                    "  runtime/org.freedesktop.Platform.GL32.nvidia-615-78-08/x86_64/1.4\n"
                    "Nothing unused to uninstall\n")   # sortie réelle du 9 novembre (code 0)


class LecturesControles(unittest.TestCase):
    def test_lire_upgrade_check(self):
        self.assertEqual(sante.lire_upgrade_check(77, ""), {"disponible": None})
        self.assertEqual(sante.lire_upgrade_check(0, texte("rpmostree-upgrade-check.txt")),
                         {"disponible": "45.20261110"})
        self.assertIsNone(sante.lire_upgrade_check(1, "error"))
        # code 0 sans « Version: » : sortie inattendue, pas un « À jour » (Ruling V43)
        self.assertIsNone(sante.lire_upgrade_check(0, "AvailableUpdate:\n         Digest: sha256:4b8f\n"))
        self.assertIsNone(sante.lire_upgrade_check(-1, "Command timed out"))

    def test_lire_remote_ls(self):
        self.assertEqual(sante.lire_remote_ls("org.mozilla.Thunderbird\norg.libreoffice.LibreOffice\n\n"),
                         ["org.mozilla.Thunderbird", "org.libreoffice.LibreOffice"])
        # un avertissement mêlé à la sortie n'est pas une application à mettre à jour
        self.assertEqual(sante.lire_remote_ls("Warning: Unable to load summary from remote flathub\n"), [])

    def test_lire_runtimes_inutilises(self):
        r = sante.lire_runtimes_inutilises(texte("flatpak-unused.txt"))
        self.assertEqual(r, ["org.kde.Platform", "org.gnome.Platform",
                             "org.freedesktop.Platform.GL.nvidia-580-95-05"])
        self.assertTrue(all(i.startswith(("org.", "com.")) for i in r))

    def test_lire_runtimes_inutilises_rien(self):
        # les runtimes épinglés listés en tête ne sont pas des runtimes inutilisés
        self.assertEqual(sante.lire_runtimes_inutilises(RIEN_D_INUTILISE), [])

    def test_gl_nvidia_obsoletes(self):
        sortie = ("org.freedesktop.Platform.GL.nvidia-580-95-05\t1.4\n"
                  "org.freedesktop.Platform.GL.nvidia-615-78-08\t1.4\n")
        self.assertEqual(sante.gl_nvidia_obsoletes("615.78.08", sortie),
                         ["runtime/org.freedesktop.Platform.GL.nvidia-580-95-05/x86_64/1.4"])
        self.assertEqual(sante.gl_nvidia_obsoletes(None, sortie), [])

    def test_gl_nvidia_obsoletes_echantillon(self):
        reel = texte("flatpak-runtimes.txt")
        self.assertEqual(sante.gl_nvidia_obsoletes("615.78.08", reel), [])
        self.assertEqual(sante.gl_nvidia_obsoletes("580.95.05", reel),
                         ["runtime/org.freedesktop.Platform.GL.nvidia-615-78-08/x86_64/1.4",
                          "runtime/org.freedesktop.Platform.GL32.nvidia-615-78-08/x86_64/1.4"])

    def test_version_pilote_nvidia(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "version"
            f.write_text("NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  615.78.08  Release Build"
                         "  (akmods@)  Mon Nov  2 09:04:12 UTC 2026\nGCC version:  gcc version 16.2.1\n")
            self.assertEqual(sante.version_pilote_nvidia(f), "615.78.08")
            self.assertIsNone(sante.version_pilote_nvidia(Path(t) / "absent"))

    def test_lire_disk_usage(self):
        self.assertEqual(sante.lire_disk_usage("Archived and active journals take up 1.2G in the file system."),
                         round(1.2 * 1024 ** 3))
        self.assertEqual(sante.lire_disk_usage("Archived and active journals take up 535.2M in the file system.\n"),
                         round(535.2 * 1024 ** 2))
        self.assertIsNone(sante.lire_disk_usage("No journal files were found."))

    def test_lire_erreurs_disque(self):
        r = sante.lire_erreurs_disque(texte("journal-noyau.txt"))
        self.assertEqual(r["nombre"], 2)
        self.assertEqual(len(r["exemples"]), 2)
        self.assertTrue(all("nvidia" not in e for e in r["exemples"]))
        beaucoup = "\n".join(f"kernel: I/O error, dev sda, sector {i}" for i in range(7))
        r = sante.lire_erreurs_disque(beaucoup)
        self.assertEqual((r["nombre"], len(r["exemples"])), (7, 3))


class MesuresControles(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)

    def test_telechargements_incomplets(self):
        dl = self.dir / "Téléchargements"
        dl.mkdir()
        with open(dl / "jeu.iso.part", "wb") as f:
            f.truncate(60 * 1024 ** 2)              # fichier creux : rien n'est encore écrit
        (dl / "petit.txt").write_bytes(b"x" * 1024 * 1024)
        r = sante.telechargements_incomplets([dl, self.dir / "Downloads"])
        self.assertEqual([t["nom"] for t in r], ["jeu.iso.part"])
        self.assertEqual(r[0]["octets"], 60 * 1024 ** 2)
        self.assertLess(r[0]["present"], 90)

    def test_telechargements_un_dossier_lie_n_est_lu_qu_une_fois(self):
        dl = self.dir / "Téléchargements"
        dl.mkdir()
        with open(dl / "a.part", "wb") as f:
            f.truncate(60 * 1024 ** 2)
        (self.dir / "Downloads").symlink_to(dl)
        self.assertEqual(len(sante.telechargements_incomplets([dl, self.dir / "Downloads"])), 1)

    def test_taille_dossier(self):
        (self.dir / "a").mkdir()
        (self.dir / "a" / "f").write_bytes(b"x" * 100_000)
        (self.dir / "lien").symlink_to("/usr")        # jamais suivi
        self.assertGreaterEqual(sante.taille_dossier(self.dir), 100_000)
        self.assertLess(sante.taille_dossier(self.dir), 1024 ** 2)
        self.assertEqual(sante.taille_dossier(self.dir / "absent"), 0)

    def test_non_montes(self):
        self.assertEqual(sante.non_montes(est_monte=lambda c: False), ["/var/mnt/DONNEES"])
        self.assertEqual(sante.non_montes(est_monte=lambda c: True), [])
        self.assertEqual(sante.volumes_attendus(), [{"nom": "Données", "chemin": "/var/mnt/DONNEES"}])

    def test_erreurs_disque(self):
        with mock.patch("centre_bazzite.commun.run", return_value=(0, texte("journal-noyau.txt"))) as m:
            self.assertEqual(sante.erreurs_disque()["nombre"], 2)
        self.assertEqual(m.call_args.args[0][:3], ["journalctl", "-k", "-b"])
        with mock.patch("centre_bazzite.commun.run", return_value=(1, "boum")):
            self.assertIsNone(sante.erreurs_disque())


def faux_disque(chemin):
    """disk_usage d'un /boot sain : 974 Mio dont 654 libres."""
    return SimpleNamespace(total=974 * 1024 ** 2, used=320 * 1024 ** 2, free=654 * 1024 ** 2)


# Contrôles dont aucune vérification réseau n'a échoué (caches et boot ne comptent pas pour le réessai).
COMPLETS = {"image": {"disponible": None}, "flatpak": {"a_mettre_a_jour": []},
            "runtimes": {"inutilises": [], "gl_obsoletes": []}, "telechargements": [], "caches": None, "boot": None}


class Controles(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.home = Path(d.name)       # home vide : ni téléchargements, ni caches
        p = mock.patch.object(sante, "PILOTE_NVIDIA", self.home / "pilote")
        p.start()
        self.addCleanup(p.stop)

    def test_controles_hors_ligne_ne_signalent_rien(self):
        """Review Focus 5 : sans réseau, aucun faux point « mise à jour disponible » ni de ménage."""
        appels = []

        def hors_ligne(cmd, **k):
            appels.append(list(cmd))
            return 1, "error: Unable to connect"
        c = sante.controles(run=hors_ligne, home=self.home, mesurer=faux_disque)
        self.assertIsNone(c["image"])
        self.assertIsNone(c["flatpak"])
        self.assertIsNone(c["runtimes"])
        self.assertTrue(c["date"])
        self.assertTrue(appels)
        self.assertNotIn("-y", [m for cmd in appels for m in cmd])
        pts = points.points({"controles": c}, {})
        ids = [p["id"] for p in pts]
        self.assertFalse([i for i in ids if i.startswith("maj:dispo:") or i.startswith("menage:runtimes")], ids)
        self.assertEqual(pts, [])
        self.assertEqual(points.couleur(pts, False), "vert")

    def test_controles_avec_les_echantillons(self):
        (self.home / "pilote").write_text("NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  615.78.08  Release\n")
        entrees = []

        def faux(cmd, timeout=120, entree=None):
            cmd = list(cmd)
            entrees.append((cmd, entree))
            if cmd[:3] == ["rpm-ostree", "upgrade", "--check"]:
                return 0, texte("rpmostree-upgrade-check.txt")
            if cmd[:3] == ["flatpak", "remote-ls", "--updates"]:
                return 0, "org.mozilla.Thunderbird\norg.libreoffice.LibreOffice\n"
            if cmd[:3] == ["flatpak", "uninstall", "--unused"]:
                return 1, texte("flatpak-unused.txt")      # réponse « n » : abandon, refs listées
            if cmd[:3] == ["flatpak", "list", "--runtime"]:
                return 0, texte("flatpak-runtimes.txt") + "org.freedesktop.Platform.GL.nvidia-580-95-05\t1.4\n"
            if cmd[:2] == ["journalctl", "--disk-usage"]:
                return 0, "Archived and active journals take up 1.5G in the file system.\n"
            return 1, "inattendu"
        c = sante.controles(run=faux, home=self.home, mesurer=faux_disque)
        self.assertEqual(c["image"], {"disponible": "45.20261110"})
        self.assertEqual(c["flatpak"], {"a_mettre_a_jour": ["org.mozilla.Thunderbird", "org.libreoffice.LibreOffice"]})
        self.assertEqual(c["runtimes"], {
            "inutilises": ["org.kde.Platform", "org.gnome.Platform"],
            "gl_obsoletes": ["runtime/org.freedesktop.Platform.GL.nvidia-580-95-05/x86_64/1.4"]})
        self.assertEqual(c["telechargements"], [])
        self.assertEqual(c["caches"], {"miniatures": 0, "corbeille": 0, "journal": round(1.5 * 1024 ** 3)})
        self.assertEqual(c["boot"], {"nom": "Démarrage", "chemin": "/boot", "libre_go": 0.64,
                                     "total_go": 0.95, "pourcent_utilise": 32.9})
        desinstaller = next(e for cmd, e in entrees if cmd[:2] == ["flatpak", "uninstall"])
        self.assertEqual(desinstaller, "n\n")
        self.assertEqual(set(c), {"date", "image", "flatpak", "runtimes", "telechargements", "caches", "boot"})

    def test_rien_d_inutilise(self):
        def faux(cmd, **k):
            if list(cmd)[:2] == ["flatpak", "uninstall"]:
                return 0, RIEN_D_INUTILISE
            return 1, "hors ligne"
        c = sante.controles(run=faux, home=self.home, mesurer=faux_disque)
        self.assertEqual(c["runtimes"], {"inutilises": [], "gl_obsoletes": []})

    def test_une_mesure_en_panne_ne_perd_pas_les_autres(self):
        def panne(chemin):
            raise OSError("boum")
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            c = sante.controles(run=lambda cmd, **k: (77, ""), home=self.home, mesurer=panne)
        self.assertIsNone(c["boot"])
        self.assertEqual(c["image"], {"disponible": None})
        # Ruling V43 : la panne laisse une trace (journal de l'unité de relevé)
        self.assertIn("boot", erreurs.getvalue())
        self.assertIn("OSError: boum", erreurs.getvalue())
        self.assertEqual(erreurs.getvalue().count("\n"), 1)

    def test_ecrire_controles(self):
        cache = self.home / "etat" / "controles.json"
        with mock.patch.object(sante, "CONTROLES", cache), \
                mock.patch.object(sante, "controles", return_value={"date": "2026-11-09T10:00:00"}):
            self.assertEqual(sante.ecrire_controles(), cache)
        self.assertEqual(json.loads(cache.read_text()), {"date": "2026-11-09T10:00:00"})

    def test_controles_perimes(self):
        cache = self.home / "controles.json"
        maintenant = datetime(2026, 11, 9, 12, 0, 0)
        self.assertTrue(sante.controles_perimes(chemin=cache, maintenant=maintenant))
        cache.write_text('{"date": "2026-11-08T15:00:00"}')          # 21 h
        self.assertTrue(sante.controles_perimes(chemin=cache, maintenant=maintenant))
        cache.write_text(json.dumps(dict(COMPLETS, date="2026-11-09T11:00:00")))      # 1 h
        self.assertFalse(sante.controles_perimes(chemin=cache, maintenant=maintenant))
        self.assertTrue(sante.controles_perimes(heures=0.5, chemin=cache, maintenant=maintenant))
        cache.write_text('{"date": "pas une date"}')
        self.assertTrue(sante.controles_perimes(chemin=cache, maintenant=maintenant))
        with mock.patch.object(sante, "CONTROLES", cache):
            cache.write_text('{"date": "%s"}' % datetime.now().isoformat(timespec="seconds"))
            self.assertFalse(sante.controles_perimes())

    def test_controles_en_echec_perimes_au_releve_suivant(self):
        """Ruling V41 : une vérification impossible (image, flatpak ou runtimes à None) est refaite
        au relevé horaire suivant, pas 20 h plus tard."""
        cache = self.home / "controles.json"
        maintenant = datetime(2026, 11, 9, 12, 0, 0)

        def perime(il_y_a, **kw):
            cache.write_text(json.dumps(dict(COMPLETS, date=(maintenant - il_y_a).isoformat(), **kw)))
            return sante.controles_perimes(chemin=cache, maintenant=maintenant)
        self.assertFalse(perime(timedelta(hours=2)))
        for cle in ("image", "flatpak", "runtimes"):
            self.assertTrue(perime(timedelta(hours=2), **{cle: None}), cle)
            self.assertFalse(perime(timedelta(minutes=30), **{cle: None}), cle)
        # le relevé suivant a lieu 1 h après le début du précédent : à quelques secondes près, il refait
        self.assertTrue(perime(timedelta(minutes=59, seconds=55), image=None))


class CliControles(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.cache = Path(d.name) / "controles.json"
        p = mock.patch.object(sante, "CONTROLES", self.cache)
        p.start()
        self.addCleanup(p.stop)
        self.ecrits, self.leger = [], []
        p = mock.patch.object(sante, "ecrire_controles", lambda: self.ecrits.append(1) or self.cache)
        p.start()
        self.addCleanup(p.stop)

    def appeler(self, argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(argv, ecrire_leger=lambda: self.leger.append(1))

    def test_cli_controles(self):
        self.cache.write_text('{"date": "%s"}' % datetime.now().isoformat(timespec="seconds"))
        self.assertEqual(self.appeler(["controles"]), 0)
        self.assertEqual((self.ecrits, self.leger), ([1], [1]))

    def test_cli_controles_si_perime(self):
        self.cache.write_text('{"date": "%s"}' % datetime.now().isoformat(timespec="seconds"))
        self.assertEqual(self.appeler(["controles", "--si-perime"]), 0)
        self.assertEqual((self.ecrits, self.leger), ([], [1]))
        self.cache.write_text('{"date": "%s"}' % (datetime.now() - timedelta(hours=21)).isoformat(timespec="seconds"))
        self.appeler(["controles", "--si-perime"])
        self.assertEqual((self.ecrits, self.leger), ([1], [1, 1]))


if __name__ == "__main__":
    unittest.main()
