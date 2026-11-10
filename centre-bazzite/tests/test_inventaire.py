import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from centre_bazzite import commun, inventaire

ECH = Path(__file__).parent / "echantillons"


class Parseurs(unittest.TestCase):
    def test_lire_flatpak(self):
        f = inventaire.lire_flatpak((ECH / "flatpak-list.txt").read_text())
        self.assertEqual(f["org.mozilla.Thunderbird"], "1.24.1b")
        self.assertEqual(f["org.darktable.Darktable"], "5.2")

    def test_lire_flatpak_version_vide_prend_la_branche(self):
        f = inventaire.lire_flatpak("org.exemple.App\t\tstable\tsystem\n")
        self.assertEqual(f, {"org.exemple.App": "stable"})

    def test_lire_brew(self):
        b = inventaire.lire_brew((ECH / "brew-versions.txt").read_text())
        self.assertEqual(b["alsa-lib"], "1.2.16.1_1")
        self.assertEqual(inventaire.lire_brew("node 25.0.0 26.1.0\n"), {"node": "26.1.0"})

    def test_lire_rpm_double_arch(self):
        texte = (ECH / "rpm-q.txt").read_text() + "mesa-dri-drivers 26.2.5\n"
        r = inventaire.lire_rpm(texte)
        self.assertEqual(r["kernel"], "7.2.15")
        self.assertEqual(r["mesa-dri-drivers"], "26.2.6")
        self.assertEqual(len(r), 4)


def releve(date="2026-11-09T11:20:00", image="45.1", paquets=None, flatpak=None, brew=None):
    return {"date": date, "image": image,
            "paquets": paquets if paquets is not None else {},
            "flatpak": flatpak or {}, "brew": brew or {}}


class Differences(unittest.TestCase):
    def test_differences(self):
        avant = releve(paquets={"kernel": "7.2.14", "mesa-dri-drivers": "26.2.6"},
                       flatpak={"a.A": "1", "b.B": "2", "c.C": "3", "d.D": "4"},
                       brew={"node": "25", "gh": "2.1"})
        apres = releve(paquets={"kernel": "7.2.15", "mesa-dri-drivers": "26.2.6"},
                       flatpak={"a.A": "2", "b.B": "2", "c.C": "3", "e.E": "1"},
                       brew={"node": "26", "gh": "2.1"})
        ch = {(c["categorie"], c["id"]): c for c in inventaire.differences(avant, apres)}
        self.assertEqual(set(ch), {("systeme", "kernel"), ("applications", "a.A"),
                                   ("applications", "d.D"), ("applications", "e.E"),
                                   ("outils", "node")})
        self.assertEqual(ch[("applications", "a.A")]["de"], "1")
        self.assertEqual(ch[("applications", "a.A")]["vers"], "2")
        self.assertIsNone(ch[("applications", "e.E")]["de"])
        self.assertIsNone(ch[("applications", "d.D")]["vers"])
        self.assertEqual(ch[("systeme", "kernel")]["nom"], "Noyau")
        self.assertEqual(ch[("outils", "node")]["nom"], "node")

    def test_source_absente_d_un_cote_est_ignoree(self):
        # flatpak list en échec d'un côté : pas de « 40 applications retirées » puis « nouvelles ».
        avant = releve(image=None, flatpak={"a.A": "1"}, brew={"node": "25"})
        avant["paquets"] = None
        apres = releve(image="45.2", paquets={"kernel": "7.2.15"}, brew={"node": "26"})
        apres["flatpak"] = None
        ch = inventaire.differences(avant, apres)
        self.assertEqual([(c["categorie"], c["id"]) for c in ch], [("outils", "node")])
        self.assertEqual(inventaire.differences(apres, avant), [{"categorie": "outils", "id": "node", "nom": "node",
                                                                  "de": "26", "vers": "25"}])

    def test_changement_d_image(self):
        ch = inventaire.differences(releve(image="45.1"), releve(image="45.2"))
        self.assertEqual(ch, [{"categorie": "systeme", "id": "image", "nom": "Bazzite",
                               "de": "45.1", "vers": "45.2"}])


class Stockage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patch = mock.patch.object(inventaire, "ETAT", Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_releve_avant(self):
        for d in ("2026-11-01T10:00:00", "2026-11-05T10:00:00", "2026-11-09T10:00:00"):
            inventaire.enregistrer(releve(date=d))
        self.assertEqual(inventaire.releve_avant("2026-11-06T00:00:00")["date"], "2026-11-05T10:00:00")
        self.assertEqual(inventaire.releve_avant("2026-11-05T10:00:00")["date"], "2026-11-05T10:00:00")
        self.assertIsNone(inventaire.releve_avant("2026-10-01T00:00:00"))
        self.assertEqual(inventaire.dernier_releve()["date"], "2026-11-09T10:00:00")

    def test_aucun_releve(self):
        self.assertIsNone(inventaire.dernier_releve())

    def dates(self):
        return sorted(p.stem for p in (Path(self.tmp.name) / "releves").glob("*.json"))

    def test_conservation_48h_puis_un_par_jour_60_jours(self):
        maintenant = datetime(2026, 11, 9, 12, 0, 0)
        heures = [maintenant - timedelta(hours=h) for h in range(1, 24 * 5)]   # 5 jours, toutes les heures
        anciens = [datetime(2026, 10, 1, h, 0, 0) for h in (8, 14, 20)] + [datetime(2026, 8, 1, 10, 0, 0)]
        for d in sorted(heures + anciens):
            commun.ecrire_json(Path(self.tmp.name) / "releves" / f"{d.isoformat()}.json", releve(date=d.isoformat()))
        inventaire.enregistrer(releve(date=maintenant.isoformat()))
        dates = self.dates()
        limite = (maintenant - timedelta(hours=48)).isoformat()
        recents = [d for d in dates if d >= limite]
        self.assertEqual(len(recents), 49)                       # les 48 dernières heures, plus celui-ci
        plus_vieux = [d for d in dates if d < limite]
        jours = [d[:10] for d in plus_vieux]
        self.assertEqual(len(jours), len(set(jours)))            # au-delà : un seul par jour…
        self.assertIn("2026-10-01T20:00:00", plus_vieux)         # … le dernier de la journée
        self.assertNotIn("2026-10-01T08:00:00", dates)
        self.assertNotIn("2026-08-01T10:00:00", dates)           # plus de 60 jours : supprimé

    def test_le_releve_de_la_derniere_visite_est_toujours_garde(self):
        for ref in ("2026-08-01T10:00:00", "2026-10-01T08:00:00"):
            for d in ("2026-08-01T10:00:00", "2026-10-01T08:00:00", "2026-10-01T20:00:00"):
                commun.ecrire_json(Path(self.tmp.name) / "releves" / f"{d}.json", releve(date=d))
            commun.ecrire_json(Path(self.tmp.name) / "visites.json", {"derniere": "x", "releve": ref})
            inventaire.enregistrer(releve(date="2026-11-09T12:00:00"))
            self.assertIn(ref, self.dates())
        self.assertEqual(inventaire.releve_du("2026-10-01T08:00:00")["date"], "2026-10-01T08:00:00")
        self.assertIsNone(inventaire.releve_du("2026-10-02T08:00:00"))
        self.assertIsNone(inventaire.releve_du(None))


class Relever(unittest.TestCase):
    def test_relever(self):
        sorties = {"flatpak": "x.X\t1.0\tstable\tsystem\n", "brew": "gh 2.0\n",
                   "rpm": "kernel 7.2.15\n"}

        def faux_run(cmd, timeout=120, entree=None):
            return 0, sorties[Path(cmd[0]).name]

        with mock.patch.object(inventaire.commun, "run", faux_run), \
             mock.patch.object(inventaire.rpmostree, "etat_deploiements",
                               return_value={"courant": {"version": "45.9"}}):
            r = inventaire.relever()
        self.assertEqual(r["image"], "45.9")
        self.assertEqual(r["flatpak"], {"x.X": "1.0"})
        self.assertEqual(r["brew"], {"gh": "2.0"})
        self.assertEqual(r["paquets"], {"kernel": "7.2.15"})

    def test_relever_rpm_paquet_manquant_garde_les_autres(self):
        def faux_run(cmd, timeout=120, entree=None):
            if Path(cmd[0]).name == "rpm":
                return 1, "kernel 7.2.15\npackage nvidia-driver is not installed\n"
            return 1, ""

        with mock.patch.object(inventaire.commun, "run", faux_run), \
             mock.patch.object(inventaire.rpmostree, "etat_deploiements",
                               return_value={"courant": None}):
            r = inventaire.relever()
        self.assertEqual(r["paquets"], {"kernel": "7.2.15"})

    def test_relever_sans_deploiement_courant(self):
        with mock.patch.object(inventaire.commun, "run", lambda *a, **k: (1, "")), \
             mock.patch.object(inventaire.rpmostree, "etat_deploiements",
                               return_value={"courant": None}):
            r = inventaire.relever()
        self.assertIsNone(r["image"])
        self.assertIsNone(r["flatpak"])
        self.assertIsNone(r["brew"])
        self.assertIsNone(r["paquets"])

    def test_source_en_echec_vaut_none(self):
        sorties = {"flatpak": (1, "error: bus"), "brew": (0, "gh 2.0\n"), "rpm": (0, "kernel 7.2.15\n")}
        with mock.patch.object(inventaire.commun, "run", lambda cmd, **kw: sorties[Path(cmd[0]).name]), \
             mock.patch.object(inventaire.rpmostree, "etat_deploiements",
                               return_value={"courant": {"version": "45.9"}}):
            r = inventaire.relever()
        self.assertIsNone(r["flatpak"])
        self.assertEqual(r["brew"], {"gh": "2.0"})


if __name__ == "__main__":
    unittest.main()
