"""Modèle de tâches du panneau Activité : fichiers JSON dans <état>/taches/ (dossier temporaire partout)."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, taches


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.d = self.racine / "taches"


class Cycle(Base):
    def test_debuter_avancer_terminer(self):
        id_ = taches.debuter("analyse", "/var/mnt/DONNEES", "Analyse de Données",
                             unite="health-hub-analyse.service", dossier=self.d)
        self.assertEqual(id_, "analyse:/var/mnt/DONNEES")
        taches.avancer(id_, progression=40, ligne="12 000 fichiers vus", dossier=self.d)
        taches.terminer(id_, "fini", "644 Go analysés", dossier=self.d)
        t = taches.lister(self.d)[0]
        self.assertEqual(t["statut"], "fini")
        self.assertEqual(t["progression"], 100)
        self.assertEqual(t["detail"], "644 Go analysés")
        self.assertEqual(t["journal"], ["12 000 fichiers vus"])
        self.assertIsNotNone(t["fin"])
        self.assertEqual(t["type"], "analyse")
        self.assertEqual(t["unite"], "health-hub-analyse.service")

    def test_nom_de_fichier_assaini(self):
        taches.debuter("analyse", "/var/mnt/DONNEES", "Analyse", dossier=self.d)
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        self.assertEqual(sorted(p.name for p in self.d.glob("*.json")),
                         ["analyse__var_mnt_DONNEES.json", "menage_caches.json"])

    def test_progression_indeterminee_au_depart(self):
        id_ = taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        self.assertEqual(taches.lister(self.d)[0]["progression"], -1)
        taches.avancer(id_, progression=10, dossier=self.d)
        self.assertEqual(taches.lister(self.d)[0]["progression"], 10)
        taches.avancer(id_, detail="Suppression…", dossier=self.d)
        t = taches.lister(self.d)[0]
        self.assertEqual((t["progression"], t["detail"]), (10, "Suppression…"))

    def test_debuter_remplace_une_tache_de_meme_id(self):
        taches.debuter("analyse", "x", "Première", dossier=self.d)
        id_ = taches.debuter("analyse", "x", "Seconde", dossier=self.d)
        liste = taches.lister(self.d)
        self.assertEqual([t["titre"] for t in liste], ["Seconde"])
        self.assertEqual(liste[0]["id"], id_)
        self.assertEqual(liste[0]["statut"], "en_cours")

    def test_terminer_en_echec_garde_la_progression(self):
        id_ = taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        taches.avancer(id_, progression=30, dossier=self.d)
        taches.terminer(id_, "echec", "Permission refusée", dossier=self.d)
        t = taches.lister(self.d)[0]
        self.assertEqual((t["statut"], t["progression"], t["detail"]), ("echec", 30, "Permission refusée"))

    def test_tache_inconnue_ignoree(self):
        taches.avancer("x:y", progression=1, dossier=self.d)
        taches.terminer("x:y", "fini", dossier=self.d)
        self.assertEqual(taches.lister(self.d), [])

    def test_journal_limite_a_200_lignes(self):
        id_ = taches.debuter("analyse", "x", "Analyse", dossier=self.d)
        for i in range(250):
            taches.avancer(id_, ligne=f"ligne {i}", dossier=self.d)
        journal = taches.lister(self.d)[0]["journal"]
        self.assertEqual(len(journal), 200)
        self.assertEqual(journal[-1], "ligne 249")
        self.assertEqual(journal[0], "ligne 50")

    def test_lister_plus_recentes_d_abord(self):
        with mock.patch.object(commun, "maintenant", return_value="2026-11-09T10:00:00"):
            taches.debuter("a", "1", "Ancienne", dossier=self.d)
        with mock.patch.object(commun, "maintenant", return_value="2026-11-09T11:00:00"):
            taches.debuter("a", "2", "Récente", dossier=self.d)
        self.assertEqual([t["titre"] for t in taches.lister(self.d)], ["Récente", "Ancienne"])

    def test_fichier_corrompu_ignore(self):
        taches.debuter("analyse", "x", "Analyse", dossier=self.d)
        (self.d / "casse.json").write_text("{ pas du json", encoding="utf-8")
        (self.d / "liste.json").write_text("[1, 2]", encoding="utf-8")
        taches.effacer_terminees(dossier=self.d, sessions=self.racine / "sessions")   # écrit vues.json
        self.assertEqual([t["titre"] for t in taches.lister(self.d)], ["Analyse"])

    def test_dossier_resolu_a_l_appel(self):
        with mock.patch.object(commun, "ETAT", self.racine):
            taches.debuter("analyse", "x", "Analyse")
            self.assertEqual(len(taches.lister()), 1)
        self.assertTrue((self.racine / "taches" / "analyse_x.json").exists())


class Orphelines(Base):
    def test_tache_orpheline_interrompue(self):
        taches.debuter("analyse", "x", "Analyse", unite="health-hub-analyse.service", dossier=self.d)
        self.assertEqual(taches.reparer_orphelines(active=lambda u: False, dossier=self.d), 1)
        t = taches.lister(self.d)[0]
        self.assertEqual(t["statut"], "interrompu")
        self.assertEqual(t["detail"], "Interrompue : la tâche s'est arrêtée sans finir.")
        self.assertIsNotNone(t["fin"])

    def test_tache_dont_l_unite_tourne_reste_en_cours(self):
        taches.debuter("analyse", "x", "Analyse", unite="health-hub-analyse.service", dossier=self.d)
        vues = []
        self.assertEqual(taches.reparer_orphelines(active=lambda u: vues.append(u) or True, dossier=self.d), 0)
        self.assertEqual(vues, ["health-hub-analyse.service"])
        self.assertEqual(taches.lister(self.d)[0]["statut"], "en_cours")

    def test_tache_sans_unite_et_pid_vivant_reste_en_cours(self):
        import os
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        self.assertEqual(taches.lister(self.d)[0]["pid"], os.getpid())
        # Sans unité, systemd n'a rien à dire : active() ne doit pas être consulté.
        self.assertEqual(taches.reparer_orphelines(active=lambda u: self.fail("consulté"), dossier=self.d), 0)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "en_cours")

    def test_tache_sans_unite_et_pid_mort_interrompue(self):
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        fini = subprocess.Popen(["true"])
        fini.wait()
        fichier = self.d / "menage_caches.json"
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
        donnees["pid"] = fini.pid
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
        self.assertEqual(taches.reparer_orphelines(active=lambda u: self.fail("consulté"), dossier=self.d), 1)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "interrompu")

    def demarrage(self, identifiant):
        """Un faux /proc/sys/kernel/random/boot_id qui vaut `identifiant`."""
        f = self.racine / "boot_id"
        f.write_text(identifiant + "\n", encoding="ascii")
        p = mock.patch.object(taches, "BOOT_ID", f)
        p.start()
        self.addCleanup(p.stop)

    def test_tache_sans_unite_note_le_demarrage(self):
        self.demarrage("aaaa-1111")
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        t = taches.lister(self.d)[0]
        self.assertEqual(t["boot"], "aaaa-1111")
        taches.debuter("analyse", "x", "Analyse", unite="u.service", dossier=self.d)
        self.assertIsNone(next(t for t in taches.lister(self.d) if t["id"] == "analyse:x")["boot"])  # systemd répond

    def test_tache_sans_unite_d_un_autre_demarrage_interrompue(self):
        """Revue finale M6 : après un redémarrage, le pid noté a pu être repris par un autre processus vivant."""
        self.demarrage("aaaa-1111")
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        self.demarrage("bbbb-2222")
        self.assertEqual(taches.reparer_orphelines(vivant=lambda pid: True, dossier=self.d), 1)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "interrompu")

    def test_meme_demarrage_pid_vivant_reste_en_cours(self):
        self.demarrage("aaaa-1111")
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        self.assertEqual(taches.reparer_orphelines(vivant=lambda pid: True, dossier=self.d), 0)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "en_cours")

    def test_demarrage_illisible_le_pid_seul_decide(self):
        self.demarrage("aaaa-1111")
        taches.debuter("menage", "caches", "Ménage", dossier=self.d)
        with mock.patch.object(taches, "BOOT_ID", self.racine / "absent"):
            self.assertIsNone(taches.boot_id())
            self.assertEqual(taches.reparer_orphelines(vivant=lambda pid: True, dossier=self.d), 0)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "en_cours")

    def test_vrai_boot_id_lu(self):
        self.assertEqual(taches.BOOT_ID, Path("/proc/sys/kernel/random/boot_id"))
        self.assertRegex(taches.boot_id() or "", r"^[0-9a-f-]{36}$")

    def test_tache_finie_pendant_la_verification_reste_finie(self):
        id_ = taches.debuter("analyse", "x", "Analyse", unite="u.service", dossier=self.d)

        def active(unite):
            taches.terminer(id_, "fini", "ok", dossier=self.d)     # le travailleur finit pendant la vérification
            return False
        self.assertEqual(taches.reparer_orphelines(active=active, dossier=self.d), 0)
        t = taches.lister(self.d)[0]
        self.assertEqual((t["statut"], t["detail"]), ("fini", "ok"))

    def test_tache_sans_unite_finie_pendant_la_verification_reste_finie(self):
        id_ = taches.debuter("menage", "caches", "Ménage", dossier=self.d)

        def vivant(pid):
            taches.terminer(id_, "fini", "ok", dossier=self.d)
            return False
        self.assertEqual(taches.reparer_orphelines(vivant=vivant, dossier=self.d), 0)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "fini")

    def test_taches_finies_intactes(self):
        id_ = taches.debuter("analyse", "x", "Analyse", unite="u.service", dossier=self.d)
        taches.terminer(id_, "fini", "ok", dossier=self.d)
        self.assertEqual(taches.reparer_orphelines(active=lambda u: False, dossier=self.d), 0)
        self.assertEqual(taches.lister(self.d)[0]["statut"], "fini")

    def test_unite_active_interroge_systemctl(self):
        class R:
            returncode = 0
        with mock.patch.object(subprocess, "run", return_value=R()) as run:
            self.assertTrue(taches.unite_active("u.service"))
        self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "is-active", "--quiet", "u.service"])
        R.returncode = 3
        with mock.patch.object(subprocess, "run", return_value=R()):
            self.assertFalse(taches.unite_active("u.service"))


class Effacer(Base):
    def sessions(self, *debuts):
        dossier = self.racine / "sessions"
        dossier.mkdir(exist_ok=True)
        for debut in debuts:
            (dossier / f"{debut}.json").write_text(json.dumps({"debut": debut, "fin": debut, "succes": True}),
                                                   encoding="utf-8")
        return dossier

    def test_effacer_terminees_garde_les_taches_en_cours(self):
        sessions = self.sessions("2026-11-08T04:45:00", "2026-11-09T04:45:00")
        encours = taches.debuter("analyse", "x", "En cours", unite="u.service", dossier=self.d)
        fini = taches.debuter("menage", "caches", "Finie", dossier=self.d)
        taches.terminer(fini, "fini", dossier=self.d)
        echec = taches.debuter("menage", "journal", "Ratée", dossier=self.d)
        taches.terminer(echec, "echec", dossier=self.d)
        self.assertEqual(taches.effacer_terminees(dossier=self.d, sessions=sessions), 2)
        self.assertEqual([t["id"] for t in taches.lister(self.d)], [encours])
        self.assertEqual(taches.vue_session(self.d), "2026-11-09T04:45:00")

    def test_vue_session_sans_rien(self):
        self.assertIsNone(taches.vue_session(self.d))
        taches.effacer_terminees(dossier=self.d, sessions=self.racine / "sessions")
        self.assertIsNone(taches.vue_session(self.d))

    def test_cli_taches_effacer(self):
        with mock.patch.object(commun, "ETAT", self.racine):
            fini = taches.debuter("menage", "caches", "Finie")
            taches.terminer(fini, "fini")
            (self.racine / "sessions").mkdir()
            (self.racine / "sessions" / "2026-11-09T04:45:00.json").write_text(
                json.dumps({"debut": "2026-11-09T04:45:00", "fin": "2026-11-09T05:00:00"}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as sortie:
                self.assertEqual(cli.main(["taches", "--effacer"]), 0)
            self.assertIn("1 tâche", sortie.getvalue())
            self.assertEqual(taches.lister(), [])
        self.assertFalse((self.d / "menage_caches.json").exists())
        self.assertTrue((self.d / "vues.json").exists())
        self.assertEqual(json.loads((self.d / "vues.json").read_text()), {"session": "2026-11-09T04:45:00"})

    def test_cli_taches_json(self):
        with mock.patch.object(commun, "ETAT", self.racine):
            taches.debuter("menage", "caches", "Ménage")
            with contextlib.redirect_stdout(io.StringIO()) as sortie:
                self.assertEqual(cli.main(["taches", "--json"]), 0)
        self.assertEqual(json.loads(sortie.getvalue())[0]["id"], "menage:caches")


class Reparation(Base):
    def test_ecrire_et_ecrire_leger_reparent_les_orphelines(self):
        from centre_bazzite import etat, session
        with mock.patch.object(commun, "ETAT", self.racine), \
                mock.patch.object(taches, "reparer_orphelines") as reparer, \
                mock.patch.object(etat, "construire", return_value={"couleur": "vert"}):
            etat.ecrire()
            session._ecrire_leger()
        self.assertEqual(reparer.call_count, 2)


if __name__ == "__main__":
    unittest.main()
