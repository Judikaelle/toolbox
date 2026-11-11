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
        self.assertIsNone(notes.notes_pour(self.ch(id="autre-paquet")))
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


OFF = ECH / "notes" / "officielles"
PL = "https://kde.org/announcements/changelogs/plasma/6/"
MESA = "https://docs.mesa3d.org/relnotes/"
KDIR = "https://cdn.kernel.org/pub/linux/kernel/"


class PagesOfficielles(unittest.TestCase):
    def pages(self, ident, de, vers):
        return notes.pages_officielles(ident, de, vers)

    def test_pages_plasma_un_pas(self):
        self.assertEqual(self.pages("plasma-workspace", "6.4.1", "6.4.2"), [PL + "6.4.1-6.4.2/"])

    def test_pages_plasma_saut(self):
        self.assertEqual(self.pages("plasma-workspace", "6.4.0", "6.4.2"),
                         [PL + "6.4.1-6.4.2/", PL + "6.4.0-6.4.1/"])
        # plus de 4 pas : les 4 plus récents
        self.assertEqual(self.pages("plasma-workspace", "6.4.0", "6.4.9"),
                         [PL + f"6.4.{b - 1}-6.4.{b}/" for b in (9, 8, 7, 6)])

    def test_pages_plasma_sans_de(self):
        self.assertEqual(self.pages("plasma-workspace", None, "6.4.2"), [PL + "6.4.1-6.4.2/"])
        self.assertEqual(self.pages("plasma-workspace", None, "6.4.0"),
                         ["https://kde.org/announcements/plasma/6/6.4.0/"])

    def test_pages_plasma_branche(self):
        self.assertEqual(self.pages("plasma-workspace", "6.4.5", "6.5.0"),
                         ["https://kde.org/announcements/plasma/6/6.5.0/"])
        self.assertEqual(self.pages("plasma-workspace", "6.4.5", "6.5.2"),
                         ["https://kde.org/announcements/plasma/6/6.5.0/"])

    def test_pages_mesa_saut_et_branche(self):
        self.assertEqual(self.pages("mesa-dri-drivers", "9.1.3", "9.1.4"), [MESA + "9.1.4.html"])
        self.assertEqual(self.pages("mesa-dri-drivers", "9.1.0", "9.1.3"),
                         [MESA + f"9.1.{v}.html" for v in (3, 2, 1)])
        self.assertEqual(len(self.pages("mesa-dri-drivers", "9.1.0", "9.1.20")), 4)
        self.assertEqual(self.pages("mesa-dri-drivers", None, "9.1.3"), [MESA + "9.1.3.html"])
        self.assertEqual(self.pages("mesa-dri-drivers", "9.1.3", "9.2.1"),
                         [MESA + "9.2.0.html", MESA + "9.2.1.html"])
        self.assertEqual(self.pages("mesa-dri-drivers", "9.1.3", "9.2.0"), [MESA + "9.2.0.html"])

    def test_pages_noyau_patchs_bornes_a_5(self):
        self.assertEqual(self.pages("kernel", "5.9.3", "5.9.4"), [KDIR + "v5.x/ChangeLog-5.9.4"])
        self.assertEqual(self.pages("kernel", "5.9.1", "5.9.4"),
                         [KDIR + f"v5.x/ChangeLog-5.9.{v}" for v in (4, 3, 2)])
        self.assertEqual(self.pages("kernel", "5.9.1", "5.9.30"),
                         [KDIR + f"v5.x/ChangeLog-5.9.{v}" for v in (30, 29, 28, 27, 26)])
        self.assertEqual(self.pages("kernel", None, "5.9.4"), [KDIR + "v5.x/ChangeLog-5.9.4"])
        self.assertEqual(self.pages("kernel", None, "5.9"), ["https://kernelnewbies.org/Linux_5.9"])

    def test_pages_noyau_branche_kernelnewbies(self):
        self.assertEqual(self.pages("kernel", "5.9.4", "5.10.2"), ["https://kernelnewbies.org/Linux_5.10"])

    def test_pages_version_illisible_ou_inconnue(self):
        self.assertEqual(self.pages("kernel", "5.9.4", "abc"), [])
        self.assertEqual(self.pages("nvidia-driver", "1", "2"), [])


class TexteHtml(unittest.TestCase):
    def test_texte_html_puces_titres_et_section(self):
        html = ("<h2>Un</h2><p>Du   texte\n sur plusieurs lignes.</p><ul><li><p>Premier</p></li><li>Deux</li></ul>"
                "<section id='s'><h3>Dans la section</h3><ul><li>Dedans</li></ul></section><h2>Autre</h2>")
        self.assertEqual(notes.texte_html(html),
                         "Un\nDu texte sur plusieurs lignes.\n- Premier\n- Deux\nDans la section\n- Dedans\nAutre")
        self.assertEqual(notes.texte_html(html, section="s"), "Dans la section\n- Dedans")
        # un titre : jusqu'au titre suivant de même niveau (les sous-titres restent)
        h = "<h1>A</h1><p>a</p><h1 id='x'>B</h1><p>b</p><h2>B1</h2><p>b1</p><h1>C</h1><p>c</p>"
        self.assertEqual(notes.texte_html(h, section="x"), "B\nb\nB1\nb1")
        self.assertEqual(notes.texte_html(h, section="absent"), "")

    def test_texte_html_retire_permaliens_et_commit(self):
        html = ('<h2>Titre<a class="headerlink" href="#t">¶</a></h2>'
                '<ul><li>Réparer le tri. <a href="http://c.test/1">Commit.</a> Fixes bug <a href="b">#12</a></li></ul>'
                "<script>var x = 'script';</script><style>p {}</style>")
        t = notes.texte_html(html)
        self.assertEqual(t, "Titre\n- Réparer le tri. Fixes bug #12")


class Extraire(unittest.TestCase):
    def test_extraire_plasma_changelog_et_annonce(self):
        t = notes.extraire("plasma-workspace", PL + "6.4.1-6.4.2/", (OFF / "plasma-changelog.html").read_text())
        self.assertIn("Dossier Un\n- Moteur: ne plus perdre le curseur au réveil.", t)
        self.assertIn("Fixes bug #100001", t)
        self.assertIn("Dossier Deux", t)
        for absent in ("Commit.", "Menu du site", "Pied de page", "Texte de script", "Description meta"):
            self.assertNotIn(absent, t)
        a = notes.extraire("plasma-workspace", "https://kde.org/announcements/plasma/6/6.5.0/",
                           (OFF / "plasma-annonce.html").read_text())
        self.assertIn("Les widgets se déplacent à la souris.", a)
        self.assertNotIn("Menu du site", a)
        self.assertNotIn("Pied de page", a)

    def test_extraire_mesa_sans_changes(self):
        t = notes.extraire("mesa-dri-drivers", MESA + "9.1.3.html", (OFF / "mesa.html").read_text())
        self.assertIn("Bug fixes\n- Pilote A: plantage au démarrage d'un jeu inventé", t)
        self.assertNotIn("New features", t)        # ne contient que « None » : omise
        self.assertNotIn("Changes", t)
        self.assertNotIn("commit interne", t)
        self.assertNotIn("SHA", t)
        self.assertNotIn("¶", t)

    def test_extraire_noyau_sujets_utiles_d_abord(self):
        t = notes.extraire("kernel", KDIR + "v5.x/ChangeLog-5.9.4", (OFF / "kernel-changelog.txt").read_text())
        self.assertEqual(t.splitlines(), ["- drm/exemple: corriger un écran noir inventé",
                                          "- usb: ne plus geler au branchement inventé",
                                          "- net: corriger une fuite inventée"])

    def test_extraire_kernelnewbies_prominent(self):
        t = notes.extraire("kernel", "https://kernelnewbies.org/Linux_5.10", (OFF / "kernelnewbies.html").read_text())
        self.assertIn("1. Prominent features", t)
        self.assertIn("Un ordonnanceur inventé plus rapide", t)
        self.assertIn("- Moins de latence dans les tests inventés.", t)
        self.assertNotIn("Section à ignorer", t)
        self.assertNotIn("Sommaire", t)

    def test_extraire_page_inattendue_vide(self):
        h = (OFF / "page-inattendue.html").read_text()
        self.assertEqual(notes.extraire("mesa-dri-drivers", MESA + "9.1.3.html", h), "")
        self.assertEqual(notes.extraire("kernel", "https://kernelnewbies.org/Linux_5.10", h), "")
        self.assertEqual(notes.extraire("kernel", KDIR + "v5.x/ChangeLog-5.9.4", h), "")


URL_CAT = "https://forums.developer.nvidia.com/c/148.json"
URL_FIL = "https://forums.developer.nvidia.com/t/900003.json"
LIEN_FIL = "https://forums.developer.nvidia.com/t/600-release-feedback-discussion/900003"
LIEN_REPLI = "https://www.nvidia.com/en-us/drivers/unix/"


class Faux:
    """`ouvrir` factice : rend le contenu de l'URL demandée et note les URL ; sinon OSError."""
    def __init__(self, pages):
        self.pages, self.demandees, self.requetes = dict(pages), [], []

    def __call__(self, req, timeout=None):
        self.demandees.append(req.full_url)
        self.requetes.append((req, timeout))
        contenu = self.pages.get(req.full_url)
        if contenu is None:
            raise OSError("introuvable")
        if isinstance(contenu, str):
            contenu = contenu.encode("utf-8")
        m = mock.MagicMock()
        m.__enter__.return_value.read.return_value = contenu
        return m


def pages_nvidia():
    return {URL_CAT: (OFF / "nvidia-categorie.json").read_text(), URL_FIL: (OFF / "nvidia-fil.json").read_text()}


class Nvidia(unittest.TestCase):
    def test_nvidia_section_de_la_version(self):
        r = notes.notes_nvidia("600.9.03", "600.10.01", Faux(pages_nvidia()))
        self.assertEqual(r["source"], "Forum NVIDIA (développeurs)")
        self.assertEqual(r["lien"], LIEN_FIL)
        self.assertIn("600.10.01 (x86_64 / aarch64)", r["texte"])
        self.assertIn("- Ajout d'une option inventée pour le rendu partagé.", r["texte"])
        self.assertNotIn("bêta", r["texte"])
        self.assertNotIn("600.9.03", r["texte"])

    def test_nvidia_branche_nouvelle_premier_message(self):
        r = notes.notes_nvidia("590.5.2", "600.10.07", Faux(pages_nvidia()))
        self.assertEqual(r["source"], "Forum NVIDIA (nouveautés de la branche 600)")
        self.assertIn("Correction d'un plantage inventé au réveil.", r["texte"])
        self.assertIn("bêta", r["texte"])
        self.assertNotIn("discussion à ignorer", r["texte"])
        r2 = notes.notes_nvidia(None, "600.10.07", Faux(pages_nvidia()))
        self.assertEqual(r2["source"], "Forum NVIDIA (nouveautés de la branche 600)")

    def test_nvidia_petite_version_sans_texte_garde_le_lien(self):
        r = notes.notes_nvidia("600.10.01", "600.10.02", Faux(pages_nvidia()))
        self.assertEqual(r, {"source": "Forum NVIDIA (développeurs)", "texte": None, "lien": LIEN_FIL})

    def test_nvidia_sujet_introuvable_lien_de_repli(self):
        r = notes.notes_nvidia("610.1.1", "610.20.03", Faux(pages_nvidia()))
        self.assertEqual(r["texte"], None)
        self.assertEqual(r["lien"], LIEN_REPLI)
        r = notes.notes_nvidia("600.1.1", "600.20.03", Faux({}))     # forum injoignable
        self.assertEqual((r["texte"], r["lien"]), (None, LIEN_REPLI))


class Officielles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(commun, "CACHE", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def ch(self, ident, de, vers):
        return {"categorie": "systeme", "id": ident, "nom": ident, "de": de, "vers": vers}

    def lire(self, nom):
        return (OFF / nom).read_text()

    def fichier(self, ident, vers):
        return notes._chemin_cache(ident, vers)

    def test_officielle_plasma_source_et_lien(self):
        f = Faux({PL + "6.4.1-6.4.2/": self.lire("plasma-changelog.html")})
        r = notes.notes_officielles(self.ch("plasma-workspace", "6.4.1", "6.4.2"), f)
        self.assertEqual(r["source"], "kde.org (annonces Plasma)")
        self.assertEqual(r["lien"], "https://kde.org/announcements/plasma/6/6.4.2/")
        self.assertIn("Moteur: ne plus perdre le curseur", r["texte"])
        req, delai = f.requetes[0]
        self.assertEqual(req.get_header("User-agent"), "health-hub")
        self.assertEqual(delai, notes.DELAI_OFFICIEL)

    def test_officielle_reussite_en_cache(self):
        f = Faux({MESA + "9.1.3.html": self.lire("mesa.html")})
        c = self.ch("mesa-dri-drivers", "9.1.2", "9.1.3")
        r1 = notes.notes_pour(c, f)
        self.assertEqual(r1["source"], "docs.mesa3d.org (notes de version)")
        self.assertEqual(r1["lien"], MESA + "9.1.3.html")
        self.assertIn("Pilote B", r1["texte"])
        self.assertEqual(len(f.demandees), 1)
        self.assertEqual(notes.notes_pour(c, f), r1)
        self.assertEqual(len(f.demandees), 1)               # deuxième appel : aucune URL
        self.assertEqual(json.loads(self.fichier("mesa-dri-drivers", "9.1.3").read_text())["texte"], r1["texte"])

    def test_officielle_page_inattendue_garde_le_lien(self):
        f = Faux({MESA + "9.1.3.html": self.lire("page-inattendue.html")})
        r = notes.notes_pour(self.ch("mesa-dri-drivers", "9.1.2", "9.1.3"), f, maintenant=lambda: "2030-01-01T10:00:00")
        self.assertEqual(r, {"source": "docs.mesa3d.org (notes de version)", "texte": None, "lien": MESA + "9.1.3.html"})
        ecrit = json.loads(self.fichier("mesa-dri-drivers", "9.1.3").read_text())
        self.assertEqual(ecrit, {"echec": "2030-01-01T10:00:00", "source": "docs.mesa3d.org (notes de version)",
                                 "lien": MESA + "9.1.3.html"})

    def test_officielle_echec_pas_de_reseau_avant_6_h(self):
        c = self.ch("kernel", "5.9.3", "5.9.4")
        f = Faux({})
        r1 = notes.notes_pour(c, f, maintenant=lambda: "2030-01-01T10:00:00")
        self.assertIsNone(r1["texte"])
        self.assertEqual(r1["source"], "kernel.org (ChangeLog)")
        self.assertEqual(r1["lien"], KDIR + "v5.x/ChangeLog-5.9.4")
        n = len(f.demandees)
        self.assertGreater(n, 0)
        r2 = notes.notes_pour(c, f, maintenant=lambda: "2030-01-01T15:59:00")
        self.assertEqual(r2, r1)
        self.assertEqual(len(f.demandees), n)

    def test_officielle_echec_reessaye_apres_6_h(self):
        c = self.ch("kernel", "5.9.3", "5.9.4")
        f = Faux({})
        notes.notes_pour(c, f, maintenant=lambda: "2030-01-01T10:00:00")
        n = len(f.demandees)
        f.pages[KDIR + "v5.x/ChangeLog-5.9.4"] = self.lire("kernel-changelog.txt")
        r = notes.notes_pour(c, f, maintenant=lambda: "2030-01-01T16:00:00")
        self.assertGreater(len(f.demandees), n)
        self.assertIn("drm/exemple", r["texte"])
        self.assertNotIn("echec", json.loads(self.fichier("kernel", "5.9.4").read_text()))

    def test_une_page_sur_deux_en_echec_garde_l_autre(self):
        f = Faux({PL + "6.4.1-6.4.2/": self.lire("plasma-changelog.html")})        # 6.4.0-6.4.1 absente
        r = notes.notes_officielles(self.ch("plasma-workspace", "6.4.0", "6.4.2"), f)
        self.assertEqual(len(f.demandees), 2)
        self.assertIn("Moteur: ne plus perdre le curseur", r["texte"])

    def test_plusieurs_pages_jointes_par_version(self):
        f = Faux({MESA + "9.1.3.html": self.lire("mesa.html"), MESA + "9.1.2.html": self.lire("mesa.html")})
        r = notes.notes_officielles(self.ch("mesa-dri-drivers", "9.1.1", "9.1.3"), f)
        t = r["texte"]
        self.assertTrue(t.startswith("Version 9.1.3\n"))
        self.assertIn("\n\nVersion 9.1.2\n", t)

    def test_texte_coupe_a_6000(self):
        gros = "<main><ul>" + "".join(f"<li>Ligne numéro {i} inventée</li>" for i in range(2000)) + "</ul></main>"
        f = Faux({"https://kde.org/announcements/plasma/6/6.5.0/": gros})
        r = notes.notes_officielles(self.ch("plasma-workspace", "6.4.5", "6.5.0"), f)
        self.assertEqual(len(r["texte"]), notes.TAILLE_OFFICIELLE)
        self.assertEqual(notes.TAILLE_OFFICIELLE, 6000)

    def test_officielle_noyau_branche_kernelnewbies(self):
        f = Faux({"https://kernelnewbies.org/Linux_5.10": self.lire("kernelnewbies.html")})
        r = notes.notes_officielles(self.ch("kernel", "5.9.4", "5.10.2"), f)
        self.assertEqual(r["source"], "KernelNewbies")
        self.assertEqual(r["lien"], "https://kernelnewbies.org/Linux_5.10")
        self.assertIn("Prominent features", r["texte"])

    def test_officielle_nvidia_via_notes_pour(self):
        f = Faux(pages_nvidia())
        r = notes.notes_pour(self.ch("nvidia-driver", "600.9.03", "600.10.01"), f)
        self.assertIn("rendu partagé", r["texte"])
        self.assertEqual(notes.notes_pour(self.ch("nvidia-driver", "600.9.03", "600.10.01"), Faux({})), r)

    def test_officielle_n_en_leve_jamais(self):
        def boom(*a, **k):
            raise RuntimeError("imprévu")
        with mock.patch.object(notes, "extraire", boom):
            f = Faux({MESA + "9.1.3.html": self.lire("mesa.html")})
            r = notes.notes_pour(self.ch("mesa-dri-drivers", "9.1.2", "9.1.3"), f)
        self.assertIsNone(r["texte"])
        self.assertEqual(r["lien"], MESA + "9.1.3.html")
        r = notes.notes_pour(self.ch("nvidia-driver", "600.9.03", "600.10.01"), boom)
        self.assertIsNone(r["texte"])
        self.assertEqual(r["lien"], LIEN_REPLI)

    def test_resumer_changements_garde_le_lien_sans_notes(self):
        from centre_bazzite import session
        etat = Path(self.tmp.name) / "etat"
        envoyes = []
        sans_texte = {"source": "docs.mesa3d.org (notes de version)", "texte": None, "lien": MESA + "9.1.3.html"}
        with mock.patch.object(commun, "ETAT", etat):
            res = session.resumer_changements(
                [self.ch("mesa-dri-drivers", "9.1.2", "9.1.3")],
                notes_pour=lambda c: sans_texte,
                resumer=lambda lot: envoyes.append(lot) or {},
                jeu=lambda: None, maintenant=lambda: "2030-01-01T10:00:00")
            ecrit = json.loads((etat / "resumes.json").read_text())
        e = ecrit["mesa-dri-drivers@9.1.3"]
        self.assertEqual((e["source"], e["lien"], e["notes"]), (sans_texte["source"], sans_texte["lien"], None))
        self.assertEqual(res["mesa-dri-drivers@9.1.3"], e)
        self.assertEqual(envoyes, [])


if __name__ == "__main__":
    unittest.main()
