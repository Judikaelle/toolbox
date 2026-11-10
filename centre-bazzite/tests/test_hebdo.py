import contextlib
import io
import subprocess
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, etat, hebdo, inventaire, points, sante

MAINTENANT = datetime(2026, 11, 16, 10, 0, 0)
Usage = namedtuple("Usage", "total used free")


def un_point(id_, gravite, titre, en_sourdine=False):
    return {"id": id_, "gravite": gravite, "titre": titre, "detail": "", "mesure": 0.0, "cran": 1.0,
            "action": None, "en_sourdine": en_sourdine}


class RapportJson(unittest.TestCase):
    def test_rapport_json(self):
        resultats = [("ok", "Image système à jour", ""),
                     ("attention", "Caches", "journaux 1.2G")]
        self.assertEqual(
            hebdo.rapport_json(resultats, "2026-11-09T10:00:00"),
            {"date": "2026-11-09T10:00:00",
             "points": [{"niveau": "ok", "titre": "Image système à jour", "details": ""},
                        {"niveau": "attention", "titre": "Caches", "details": "journaux 1.2G"}]})


class Semaine(unittest.TestCase):
    def test_semaine_compte_les_changements_et_sessions(self):
        lignes = [{"date": "2026-11-12T04:45:00", "changements": [{"module": "uv", "de": "1", "vers": "2"}]},
                  {"date": "2026-11-01T04:45:00", "changements": [{"module": "ollama", "de": "1", "vers": "2"}]}]
        sessions = [{"debut": "2026-11-10T09:00:00", "succes": True},
                    {"debut": "2026-11-14T09:00:00", "succes": False},
                    {"debut": "2026-11-02T09:00:00", "succes": False}]
        systeme = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        s = hebdo.semaine(MAINTENANT, sessions=sessions, lignes_maj_apps=lignes, changements_systeme=systeme)
        self.assertEqual((s["changements"], s["sessions"], s["echecs"]), (4, 2, 1))
        self.assertEqual((s["du"], s["au"]), ("2026-11-09T10:00:00", "2026-11-16T10:00:00"))


    def test_outil_present_dans_brew_et_maj_apps_compte_une_fois(self):
        systeme = [{"categorie": "outils", "id": "uv", "de": "1", "vers": "2"}, {"categorie": "applications", "id": "x"}]
        lignes = [{"date": "2026-11-12T04:45:00", "changements": [
            {"module": "uv", "de": "1", "vers": "2"}, {"module": "ollama", "de": "1", "vers": "2"}]}]
        s = hebdo.semaine(MAINTENANT, sessions=[], lignes_maj_apps=lignes, changements_systeme=systeme)
        self.assertEqual(s["changements"], 3)

    def test_seules_les_sessions_finies_en_echec_comptent(self):
        sessions = [{"debut": "2026-11-10T09:00:00", "succes": None},
                    {"debut": "2026-11-11T09:00:00"},
                    {"debut": "2026-11-12T09:00:00", "succes": False},
                    {"debut": "2026-11-13T09:00:00", "succes": True}]
        s = hebdo.semaine(MAINTENANT, sessions=sessions, lignes_maj_apps=[], changements_systeme=[])
        self.assertEqual((s["sessions"], s["echecs"]), (4, 1))


class Resultats(unittest.TestCase):
    def test_resultats_depuis_points(self):
        pts = [un_point("a", "echec", "Disque plein"), un_point("b", "attention", "Caches"),
               un_point("c", "info", "Erreurs"), un_point("d", "attention", "Muet", en_sourdine=True)]
        self.assertEqual(hebdo.resultats_depuis_points(pts),
                         [("alerte", "Disque plein", ""), ("attention", "Caches", "")])


def bilan_de(resultats, changements=3):
    return hebdo.rapport_json(resultats, "2026-11-16T10:00:00") | {
        "semaine": {"du": "x", "au": "y", "changements": changements, "sessions": 0, "echecs": 0}}


class Notification(unittest.TestCase):
    def test_notification_sans_souci(self):
        self.assertEqual(hebdo.texte_notification(bilan_de([])),
                         ("Health Hub : bonne semaine", "Tout va bien. 3 mises à jour appliquées cette semaine.", "low"))

    def test_notification_avec_soucis(self):
        r = [("attention", f"Souci {i}", "") for i in range(5)]
        titre, corps, urgence = hebdo.texte_notification(bilan_de(r))
        self.assertEqual(titre, "Health Hub : 5 point(s) à regarder")
        self.assertEqual(corps, "• Souci 0\n• Souci 1\n• Souci 2")
        self.assertEqual(urgence, "normal")
        self.assertEqual(hebdo.texte_notification(bilan_de(r + [("alerte", "Grave", "")]))[2], "critical")

    def test_clic_ouvre_health_hub(self):
        appels = []

        def run(cmd, **kw):
            appels.append((cmd, kw))
            return 0, "default\n"
        self.assertTrue(hebdo.notifier(bilan_de([("attention", "Caches", "")]), run=run))
        premiere, seconde = appels[0][0], appels[1][0]
        for morceau in ("--wait", "-A", "default=Ouvrir Health Hub"):
            self.assertIn(morceau, premiere)
        self.assertEqual(premiere[premiere.index("-a") + 1], "Health Hub")
        self.assertEqual(appels[0][1].get("timeout"), 3600)
        self.assertEqual(seconde, ["systemd-run", "--user", "--collect", "--quiet", str(hebdo.HEALTH_HUB)])

    def test_notification_fermee_sans_clic(self):
        appels = []

        def run(cmd, **kw):
            appels.append(cmd)
            return 0, ""
        self.assertFalse(hebdo.notifier(bilan_de([]), run=run))
        self.assertEqual(len(appels), 1)


class HorsLigne(unittest.TestCase):
    def test_bilan_hors_ligne_reste_calme(self):
        with tempfile.TemporaryDirectory() as d:
            c = sante.controles(run=lambda *a, **k: (1, "Impossible de se connecter"), home=Path(d),
                                mesurer=lambda chemin: Usage(1 << 30, 3 << 28, 7 << 28))
        pts = points.points({"controles": c}, None)
        self.assertEqual(hebdo.resultats_depuis_points(pts), [])
        self.assertEqual(hebdo.texte_notification(bilan_de([]))[0], "Health Hub : bonne semaine")


class Redaction(unittest.TestCase):
    def test_rediger(self):
        b = bilan_de([("ok", "Rien", ""), ("alerte", "Grave", "détail")], changements=2)
        b["date"] = "2026-11-16T10:00:00"
        b["semaine"]["sessions"], b["semaine"]["echecs"] = 3, 1
        texte = hebdo.rediger(b)
        self.assertTrue(texte.startswith("Bilan de la semaine — Health Hub — "))
        self.assertIn("[·] Rien", texte)
        self.assertIn("[!!] Grave", texte)
        self.assertIn("Cette semaine : 2 mises à jour, 3 sessions (1 en échec).", texte)


def releve(date, flatpak):
    return {"date": date, "image": "45.1", "paquets": {}, "flatpak": flatpak, "brew": {}}


class Construire(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = Path(d.name)
        for cible, valeur in ((commun, "ETAT"), (inventaire, "ETAT")):
            p = mock.patch.object(cible, valeur, self.dossier)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(etat, "HISTORIQUE_MAJ_APPS", self.dossier / "absent.jsonl")
        p.start()
        self.addCleanup(p.stop)
        (self.dossier / "releves").mkdir()
        (self.dossier / "sessions").mkdir()
        commun.ecrire_json(self.dossier / "etat.json", {"points": [
            un_point("a", "attention", "Caches"), un_point("b", "info", "Erreurs")]})

    def releves(self, *rr):
        for r in rr:
            commun.ecrire_json(self.dossier / "releves" / f"{r['date']}.json", r)

    def test_construire_lit_etat_sessions_et_releves(self):
        self.releves(releve("2026-11-08T10:00:00", {"a": "1"}), releve("2026-11-15T10:00:00", {"a": "2"}))
        commun.ecrire_json(self.dossier / "sessions" / "s1.json", {"debut": "2026-11-12T09:00:00", "succes": False})
        commun.ecrire_json(self.dossier / "sessions" / "s0.json", {"debut": "2026-10-01T09:00:00", "succes": False})
        b = hebdo.construire(maintenant=MAINTENANT)
        self.assertEqual(b["date"], "2026-11-16T10:00:00")
        self.assertEqual(b["points"], [{"niveau": "attention", "titre": "Caches", "details": ""}])
        self.assertEqual(b["semaine"], {"du": "2026-11-09T10:00:00", "au": "2026-11-16T10:00:00",
                                        "changements": 1, "sessions": 1, "echecs": 1})

    def test_repli_sur_le_plus_ancien_releve_de_la_fenetre(self):
        self.releves(releve("2026-11-09T11:00:00", {"a": "1"}), releve("2026-11-15T10:00:00", {"a": "2"}))
        self.assertEqual(hebdo.construire(maintenant=MAINTENANT)["semaine"]["changements"], 1)

    def test_ecrire_json_et_texte(self):
        b = bilan_de([("attention", "Caches", "")])
        b["date"] = "2026-11-16T10:00:00"
        hebdo.ecrire(b)
        self.assertEqual(commun.lire_json(self.dossier / "bilan-hebdo.json", None), b)
        texte = (self.dossier / "bilan-hebdo.txt").read_text(encoding="utf-8")
        self.assertEqual(texte, hebdo.rediger(b) + "\n")


class Cli(unittest.TestCase):
    def test_cli_bilan_report_n_recalcule_pas(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "bilan-hebdo.txt").write_text("Bilan écrit\n", encoding="utf-8")
            sortie = io.StringIO()
            with mock.patch.object(commun, "ETAT", Path(d)), \
                    mock.patch.object(hebdo, "construire", side_effect=AssertionError("recalculé")), \
                    contextlib.redirect_stdout(sortie):
                self.assertEqual(cli.main(["bilan", "--report"]), 0)
        self.assertIn("Bilan écrit", sortie.getvalue())


INSTALL = Path(__file__).resolve().parent.parent / "install.sh"


class Installation(unittest.TestCase):
    """Le bloc d'install.sh qui remplace le script bazzite-health par un lien (HOME temporaire)."""

    def lancer(self, bin_):
        texte = INSTALL.read_text(encoding="utf-8")
        bloc = texte.split("# debut-lien-bazzite-health\n")[1].split("# fin-lien-bazzite-health")[0]
        r = subprocess.run(["bash", "-c", f'set -euo pipefail; bin="{bin_}"; ici=/depot; {bloc}'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_ne_jamais_ecraser_un_fichier_ordinaire(self):
        with tempfile.TemporaryDirectory() as d:
            bin_ = Path(d)
            (bin_ / "bazzite-health.avant-health-hub").write_text("ancienne sauvegarde")
            (bin_ / "bazzite-health").write_text("restauré à la main")
            sortie = self.lancer(bin_)
            self.assertTrue((bin_ / "bazzite-health").is_symlink())
            self.assertEqual((bin_ / "bazzite-health.avant-health-hub").read_text(), "ancienne sauvegarde")
            autres = [f for f in bin_.glob("bazzite-health.avant-health-hub-*")]
            self.assertEqual(len(autres), 1)
            self.assertEqual(autres[0].read_text(), "restauré à la main")
            self.assertIn(f"conservé : {autres[0]}", sortie)

    def test_relance_sans_rien_deplacer(self):
        with tempfile.TemporaryDirectory() as d:
            bin_ = Path(d)
            (bin_ / "bazzite-health").write_text("ancien")
            self.lancer(bin_)
            self.lancer(bin_)
            self.assertEqual([f.name for f in bin_.iterdir() if "avant" in f.name], ["bazzite-health.avant-health-hub"])


if __name__ == "__main__":
    unittest.main()
