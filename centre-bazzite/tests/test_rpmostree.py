import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import rpmostree

ECH = Path(__file__).parent / "echantillons"


class Status(unittest.TestCase):
    def setUp(self):
        self.texte = (ECH / "rpmostree-status.json").read_text()

    def test_lire_status_sans_attente(self):
        s = rpmostree.lire_status(self.texte)
        self.assertEqual(s["courant"]["version"], "45.20261105")
        self.assertTrue(s["courant"]["horodatage"])
        self.assertIsNone(s["en_attente"])
        self.assertEqual(s["precedent"], {"version": "45.20261105"})

    def test_lire_status_avec_attente(self):
        donnees = json.loads(self.texte)
        boote = next(d for d in donnees["deployments"] if d["booted"])
        nouveau = dict(boote, booted=False, staged=True, version="45.20261112",
                       checksum="f" * 64, timestamp=boote["timestamp"] + 604800)
        donnees["deployments"].insert(0, nouveau)
        s = rpmostree.lire_status(json.dumps(donnees))
        self.assertEqual(s["courant"]["version"], "45.20261105")
        self.assertEqual(s["en_attente"], {"version": "45.20261112"})
        self.assertIsNotNone(s["precedent"])
        self.assertEqual(s["nombre"], 3)

    def test_lire_status_nombre(self):
        nombre = len(json.loads(self.texte)["deployments"])
        self.assertEqual(rpmostree.lire_status(self.texte)["nombre"], nombre)
        # aussi quand aucun déploiement n'est booté
        sans_boot = json.dumps({"deployments": [{"version": "45.1", "booted": False},
                                                {"version": "45.2", "booted": False}]})
        s = rpmostree.lire_status(sans_boot)
        self.assertIsNone(s["courant"])
        self.assertEqual(s["nombre"], 2)

    def test_lire_status_epingles(self):
        donnees = json.loads(self.texte)
        self.assertEqual(rpmostree.lire_status(self.texte)["epingles"], [])
        ancien = dict(donnees["deployments"][-1], version="45.20261020", pinned=True)
        donnees["deployments"].append(ancien)
        s = rpmostree.lire_status(json.dumps(donnees))
        self.assertEqual(s["epingles"], [{"position": 2, "version": "45.20261020"}])


class DbDiff(unittest.TestCase):
    def test_lire_db_diff_retires(self):
        d = rpmostree.lire_db_diff((ECH / "dbdiff.txt").read_text())
        self.assertEqual(len(d["retires"]), 12)
        self.assertIn("docker-cli-29.9.2-2.fc45.x86_64", d["retires"])
        self.assertEqual(d["ajoutes"], [])
        self.assertEqual(d["mis_a_jour"], [])

    def test_lire_db_diff_mis_a_jour(self):
        texte = ("ostree diff commit from: a\nostree diff commit to:   b\nUpgraded:\n"
                 "  kernel 7.2.15-ogc1.1.fc45 -> 7.3.3-ogc1.1.fc45\nAdded:\n  foo-1.0-1.fc45.noarch\n")
        d = rpmostree.lire_db_diff(texte)
        self.assertEqual(d["mis_a_jour"], [("kernel", "7.2.15-ogc1.1.fc45", "7.3.3-ogc1.1.fc45")])
        self.assertEqual(d["ajoutes"], ["foo-1.0-1.fc45.noarch"])


def _status(attente_checksum=None, boote_checksum="a" * 64):
    deps = [{"version": "45.20261105", "booted": True, "staged": False,
             "checksum": boote_checksum, "timestamp": 1000}]
    if attente_checksum:
        deps.insert(0, {"version": "45.20261105", "booted": False, "staged": True,
                        "checksum": attente_checksum, "timestamp": 2000})
    return json.dumps({"deployments": deps})


class DiffEnAttente(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        p = mock.patch.object(rpmostree.commun, "CACHE", self.cache)
        p.start()
        self.addCleanup(p.stop)
        self.appels = []
        self.statut = _status("b" * 64)

    def faux_run(self, cmd, timeout=120, entree=None):
        self.appels.append(list(cmd))
        if cmd[:2] == ["rpm-ostree", "status"]:
            return 0, self.statut
        return 0, "Added:\n  foo-1.0-1.fc45.noarch\n"

    def diff(self):
        with mock.patch.object(rpmostree.commun, "run", self.faux_run):
            return rpmostree.diff_en_attente()

    def nb_db_diff(self):
        return sum(1 for c in self.appels if c[:3] == ["rpm-ostree", "db", "diff"])

    def test_diff_en_attente_utilise_le_cache(self):
        self.assertEqual(self.diff()["ajoutes"], ["foo-1.0-1.fc45.noarch"])
        self.assertEqual(self.diff()["ajoutes"], ["foo-1.0-1.fc45.noarch"])
        self.assertEqual(self.nb_db_diff(), 1)
        self.assertEqual(self.appels[1][3:], ["a" * 64, "b" * 64])

    def test_diff_en_attente_cle_par_checksum(self):
        self.diff()
        self.statut = _status("c" * 64)
        self.diff()
        self.assertEqual(self.nb_db_diff(), 2)
        self.assertEqual(len(list(self.cache.glob("dbdiff-*.json"))), 2)

    def test_diff_en_attente_sans_attente_none(self):
        self.statut = _status()
        self.assertIsNone(self.diff())
        self.assertEqual(self.nb_db_diff(), 0)


if __name__ == "__main__":
    unittest.main()
