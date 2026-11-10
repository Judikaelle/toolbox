import json
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import uupd

ECH = Path(__file__).parent / "echantillons"


def lignes():
    return (ECH / "uupd.jsonl").read_text().splitlines()


class Progression(unittest.TestCase):
    def test_progression_complete(self):
        p = uupd.lire_progression(lignes())
        for module in ("brew", "flatpak", "system"):
            self.assertEqual(p["etapes"][module]["statut"], "fini", module)
        self.assertEqual(p["etapes"]["flatpak"]["titre"], "Flatpak")
        self.assertEqual(p["global"], 100)
        self.assertTrue(p["termine"])
        self.assertIs(p["succes"], True)

    def test_progression_partielle(self):
        ls = lignes()
        i = next(n for n, l in enumerate(ls) if '"Flatpak module is starting."' in l)
        p = uupd.lire_progression(ls[:i + 1])
        self.assertEqual(p["etapes"]["flatpak"]["statut"], "en_cours")
        self.assertEqual(p["etapes"]["brew"]["statut"], "fini")
        self.assertEqual(p["global"], 50)
        self.assertFalse(p["termine"])
        self.assertIsNone(p["succes"])

    def test_ligne_non_json_ignoree(self):
        p = uupd.lire_progression(["Starting uupd.service", "system: Pulled appstream", "{cassé", "42"]
                                  + lignes())
        self.assertTrue(p["termine"])
        self.assertEqual(uupd.lire_progression(["rien"])["etapes"], {})

    def test_module_en_echec(self):
        ligne = json.dumps({"level": "INFO", "msg": "Brew module has completed.", "module": "brew",
                            "status": "finished", "exit_code": 1})
        p = uupd.lire_progression(lignes()[:2] + [ligne])
        self.assertEqual(p["etapes"]["brew"]["statut"], "echec")
        self.assertFalse(p["termine"])


class Systemd(unittest.TestCase):
    def test_lancer(self):
        with mock.patch("centre_bazzite.commun.run", return_value=(0, "")) as r:
            self.assertTrue(uupd.lancer())
        r.assert_called_once_with(["systemctl", "start", "--no-block", "uupd-manual.service"])
        with mock.patch("centre_bazzite.commun.run", return_value=(1, "")):
            self.assertFalse(uupd.lancer())

    def test_unite_active(self):
        def faux(cmd, **kw):
            return (0, "active\n") if cmd[-1] == "uupd-manual.service" else (3, "inactive\n")
        with mock.patch("centre_bazzite.commun.run", side_effect=faux):
            self.assertEqual(uupd.unite_active(), "uupd-manual.service")
        with mock.patch("centre_bazzite.commun.run", return_value=(3, "inactive\n")):
            self.assertIsNone(uupd.unite_active())

    def test_lignes_depuis(self):
        with mock.patch("centre_bazzite.commun.run", return_value=(0, "a\nb\n")) as r:
            self.assertEqual(uupd.lignes_depuis("uupd.service", "2026-11-09"), ["a", "b"])
        self.assertEqual(r.call_args[0][0][:4], ["journalctl", "-u", "uupd.service", "-o"])

    def test_executions_depuis(self):
        def ev(unite, t, mid, res=None):
            d = {"UNIT": unite, "_SYSTEMD_UNIT": "init.scope", "MESSAGE_ID": mid,
                 "__REALTIME_TIMESTAMP": str(t * 1000000)}
            if res:
                d["JOB_RESULT"] = res
            return json.dumps(d)
        texte = "\n".join([ev("uupd.service", 1794120751, uupd.ID_DEBUT),
                           ev("uupd.service", 1794120794, uupd.ID_FIN, "done"),
                           ev("uupd-manual.service", 1794141804, uupd.ID_DEBUT),
                           ev("uupd-manual.service", 1794141836, uupd.ID_FIN, "failed"),
                           "pas du json"])
        with mock.patch("centre_bazzite.commun.run", return_value=(0, texte)):
            r = uupd.executions_depuis("2026-11-01")
        self.assertEqual([(x["unite"], x["succes"]) for x in r],
                         [("uupd.service", True), ("uupd-manual.service", False)])
        self.assertLess(r[0]["debut"], r[0]["fin"])

    def test_executions_depuis_non_terminee(self):
        texte = json.dumps({"UNIT": "uupd-manual.service", "_SYSTEMD_UNIT": "init.scope",
                            "MESSAGE_ID": uupd.ID_DEBUT, "__REALTIME_TIMESTAMP": "1794141804000000"})
        with mock.patch("centre_bazzite.commun.run", return_value=(0, texte)):
            r = uupd.executions_depuis("2026-11-01")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["unite"], "uupd-manual.service")
        self.assertTrue(r[0]["debut"])
        self.assertIsNone(r[0]["fin"])
        self.assertIsNone(r[0]["succes"])
