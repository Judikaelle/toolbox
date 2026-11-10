import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import commun, notes

ECH = Path(__file__).parent / "echantillons"

XML_EXEMPLE = """<components><component type="desktop-application">
<id>com.exemple.App</id><name>Exemple</name><name xml:lang="fr">Exemple FR</name>
<releases>
<release version="1.0.171"><description><p>Correctif C</p></description></release>
<release version="1.0.170"><description><p>Nouveauté B</p></description></release>
<release version="1.0.168"><description><p>Ancienne A</p></description></release>
</releases></component></components>"""


class Appstream(unittest.TestCase):
    def test_appstream_plage(self):
        r = notes.notes_appstream(XML_EXEMPLE, "com.exemple.App", "1.0.168", "1.0.171")
        self.assertEqual(r["source"], "Flathub (appstream)")
        self.assertEqual(r["nom"], "Exemple")
        self.assertIn("Correctif C", r["texte"])
        self.assertIn("Nouveauté B", r["texte"])
        self.assertNotIn("Ancienne A", r["texte"])

    def test_appstream_echantillon_reel(self):
        xml = (ECH / "appstream-extrait.xml").read_text()
        r = notes.notes_appstream(xml, "app.drey.Biblioteca", "1.5", "1.7")
        self.assertIn("Update to GNOME 49", r["texte"])
        self.assertIn("Update to GNOME 48", r["texte"])
        self.assertNotIn("GNOME 51", r["texte"])
        self.assertNotIn("GNOME 47", r["texte"])

    def test_appstream_sans_de_prend_seulement_vers(self):
        # Appli nouvellement installée : pas tout l'historique, seulement la version installée.
        r = notes.notes_appstream(XML_EXEMPLE, "com.exemple.App", None, "1.0.170")
        self.assertIn("Nouveauté B", r["texte"])
        self.assertNotIn("Correctif C", r["texte"])
        self.assertNotIn("Ancienne A", r["texte"])

    def test_appstream_plus_recent_d_abord(self):
        # Le résumé tronque les notes : les plus récentes doivent passer en premier.
        r = notes.notes_appstream(XML_EXEMPLE, "com.exemple.App", "1.0.100", "1.0.171")
        t = r["texte"]
        self.assertLess(t.index("Correctif C"), t.index("Nouveauté B"))
        self.assertLess(t.index("Nouveauté B"), t.index("Ancienne A"))

    def test_appstream_app_absente_none(self):
        self.assertIsNone(notes.notes_appstream(XML_EXEMPLE, "org.absent.App", "1", "2"))

    def test_appstream_sans_description_none(self):
        xml = ("<components><component><id>a.b.C</id><name>C</name><releases>"
               '<release version="2"/></releases></component></components>')
        self.assertIsNone(notes.notes_appstream(xml, "a.b.C", "1", "2"))


class Versions(unittest.TestCase):
    def test_comparer_versions(self):
        self.assertEqual(notes.comparer_versions("1.0.9", "1.0.10"), -1)
        self.assertEqual(notes.comparer_versions("1.0.10", "1.0.9"), 1)
        self.assertEqual(notes.comparer_versions("6.8.2", "6.8.2"), 0)


class Bazzite(unittest.TestCase):
    def liste(self):
        return [
            {"tag_name": "testing-45.20261108", "body": "test", "html_url": "u1"},
            {"tag_name": "stable-45.20261108", "body": "corps", "html_url": "u2"},
            {"tag_name": "unstable-45.20261108", "body": "inst", "html_url": "u3"},
        ]

    def ouvrir(self, donnees):
        def f(req, timeout=None):
            m = mock.MagicMock()
            m.__enter__.return_value.read.return_value = json.dumps(donnees).encode()
            return m
        return f

    def test_bazzite_tag(self):
        r = notes.notes_bazzite("45.20261108", ouvrir=self.ouvrir(self.liste()))
        self.assertEqual(r, {"source": "GitHub ublue-os/bazzite", "texte": "corps", "lien": "u2"})

    def test_bazzite_tag_sans_prefixe(self):
        donnees = json.loads((ECH / "bazzite-release.json").read_text())
        r = notes.notes_bazzite("45.20261105", ouvrir=self.ouvrir(donnees))
        self.assertIn("45.20261105", r["lien"])
        self.assertIsNone(notes.notes_bazzite("45.20261109", ouvrir=self.ouvrir(donnees)))

    def test_bazzite_testing_ecarte(self):
        liste = [d for d in self.liste() if d["tag_name"].startswith("testing")]
        self.assertIsNone(notes.notes_bazzite("45.20261108", ouvrir=self.ouvrir(liste)))


class MajApps(unittest.TestCase):
    def test_notes_maj_apps(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "historique.jsonl"
            h.write_text("\n".join([
                json.dumps({"date": "x"}),
                "pas du json",
                json.dumps({"changements": [{"module": "ollama", "de": "1", "vers": "2", "notes": "ancien"}]}),
                json.dumps({"changements": [{"module": "ollama", "de": "1", "vers": "2", "notes": "récent"}]}),
            ]))
            r = notes.notes_maj_apps("ollama", "2", historique=h)
            self.assertEqual(r, {"source": "GitHub (via maj-apps)", "texte": "récent", "lien": None})
            self.assertIsNone(notes.notes_maj_apps("uv", "2", historique=h))
            self.assertIsNone(notes.notes_maj_apps("ollama", "3", historique=h))


class Pour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(commun, "CACHE", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def ch(self, **kw):
        base = {"categorie": "systeme", "id": "image", "nom": "Bazzite", "de": "45.1", "vers": "45.20261108"}
        base.update(kw)
        return base

    def test_echec_reseau_renvoie_none_et_ne_cache_pas(self):
        def boom(*a, **k):
            raise OSError("hors ligne")
        self.assertIsNone(notes.notes_pour(self.ch(), ouvrir=boom))
        dossier = Path(self.tmp.name) / "notes"
        self.assertEqual(list(dossier.glob("*")) if dossier.exists() else [], [])

    def test_succes_mis_en_cache_puis_relu(self):
        liste = [{"tag_name": "stable-45.20261108", "body": "corps", "html_url": "u"}]
        ouvrir = Bazzite().ouvrir(liste)
        r1 = notes.notes_pour(self.ch(), ouvrir=ouvrir)
        self.assertEqual(r1["texte"], "corps")

        def boom(*a, **k):
            raise AssertionError("réseau interdit")
        self.assertEqual(notes.notes_pour(self.ch(), ouvrir=boom), r1)

    def test_routage_inconnu_none(self):
        self.assertIsNone(notes.notes_pour(self.ch(categorie="outils", id="node")))
        self.assertIsNone(notes.notes_pour(self.ch(id="kernel")))
        self.assertIsNone(notes.notes_pour(self.ch(vers=None)))

    def test_routage_applications_appstream(self):
        ch = self.ch(categorie="applications", id="com.exemple.App", de="1.0.168", vers="1.0.171")
        with mock.patch.object(notes, "_lire_appstream", return_value=XML_EXEMPLE):
            r = notes.notes_pour(ch)
        self.assertIn("Correctif C", r["texte"])

    def test_routage_maj_apps(self):
        ch = self.ch(categorie="outils", id="ollama", vers="2")
        with mock.patch.object(notes, "notes_maj_apps", return_value={"source": "s", "texte": "t", "lien": None}):
            self.assertEqual(notes.notes_pour(ch)["texte"], "t")


if __name__ == "__main__":
    unittest.main()
