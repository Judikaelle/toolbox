import io
import json
import os
import signal
import tempfile
from datetime import datetime, timedelta
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, session

REL_AVANT = {"date": "2026-11-09T11:00:00", "image": "45.1", "paquets": {}, "flatpak": {"a.b.C": "1"}, "brew": {}}
REL_APRES = {"date": "2026-11-09T11:30:00", "image": "45.1", "paquets": {}, "flatpak": {"a.b.C": "2"}, "brew": {}}
ETAT_MAJ_INACTIF = {"ActiveState": "inactive", "SubState": "dead", "Result": "success", "ExecMainStatus": "0"}
ETAT_MAJ_EN_COURS = {"ActiveState": "active", "SubState": "running", "Result": "success", "ExecMainStatus": "0"}
ETAT_MAJ_REPORTE = {"ActiveState": "activating", "SubState": "auto-restart", "Result": "exit-code",
                    "ExecMainStatus": "75"}
PROG_OK = {"etapes": {}, "global": 100, "termine": True, "succes": True}
PROG_KO = {"etapes": {"system": {"titre": "Système", "statut": "echec", "progression": 10}},
           "global": 30, "termine": True, "succes": False}


class Fausses:
    """Dépendances factices qui enregistrent leurs appels dans `appels`."""

    def __init__(self, tmp, **sur):
        self.appels = []
        self.actifs = list(sur.pop("actifs", [None, "uupd-manual.service", None]))
        self.releves = [REL_AVANT, REL_APRES]
        self.annulations = list(sur.pop("annulations", []))
        self.t = 0
        self.horloge_notif = None
        f = {
            "uupd_actif": self._uupd_actif,
            "lancer_uupd": lambda: self._n("lancer_uupd", True),
            "lignes_uupd": lambda unite, depuis: self._n("lignes_uupd", []),
            "lire_progression": lambda lignes: PROG_OK,
            "uupd_echoue": lambda unite: False,
            "attendre": self._attendre,
            "maj_apps": lambda: self._n("maj_apps", 0),
            "maj_apps_etat": lambda: ETAT_MAJ_INACTIF,
            "ecrire_etat_leger": lambda: self._n("ecrire_etat_leger", None),
            "relever": lambda: self._n("relever", self.releves.pop(0)),
            "resumer": lambda ch: self._n("resumer", {"n": len(ch)}),
            "ecrire_etat": lambda: self._n("ecrire_etat", None),
            "notifier": self._notifier,
            "eteindre_pc": lambda: self._n("eteindre_pc", None),
            "annulation_demandee": self._annulation,
            "effacer_annulation": lambda: None,
            "jeu_en_cours": lambda: None,
            "maintenant": self._maintenant,
            "historique": tmp / "pas-d-historique.jsonl",
            "deploiements": lambda: {"en_attente": False},
        }
        f.update(sur)
        self.deps = session.Dependances(**f)

    def _maintenant(self):
        return (datetime(2026, 11, 9, 11, 0, 0) + timedelta(seconds=self.t)).isoformat()

    def _attendre(self, secondes):
        self.t += secondes

    def _notifier(self, texte):
        self.horloge_notif = self._maintenant()
        self.appels.append("notifier:" + texte)

    def _n(self, nom, val):
        self.appels.append(nom)
        return val

    def _uupd_actif(self):
        return self.actifs.pop(0) if self.actifs else None

    def _annulation(self):
        self.appels.append("annulation_demandee")
        return self.annulations.pop(0) if self.annulations else False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(commun, "ETAT", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def lancer(self, eteindre=False, **sur):
        f = Fausses(self.tmp, **sur)
        res = session.executer(eteindre, deps=f.deps)
        return f, res


class Session(Base):
    def test_ordre_des_etapes(self):
        f, res = self.lancer()
        self.assertEqual([a for a in f.appels if a != "lignes_uupd"],
                         ["relever", "lancer_uupd", "maj_apps", "relever", "resumer",
                          "ecrire_etat", "ecrire_etat"])
        self.assertEqual({k: v["statut"] for k, v in res["etapes"].items()},
                         {"uupd": "fini", "maj-apps": "fini", "notes": "fini", "resume": "fini",
                          "etat": "fini"})
        self.assertTrue(res["succes"])
        self.assertEqual(res["global"], 100)
        self.assertFalse((self.tmp / "session-en-cours.json").exists())
        fichier = self.tmp / "sessions" / "2026-11-09T11:00:00.json"
        self.assertEqual(json.loads(fichier.read_text())["succes"], True)

    def test_suit_uupd_deja_actif(self):
        f, res = self.lancer(actifs=["uupd.service", "uupd.service", None])
        self.assertNotIn("lancer_uupd", f.appels)
        self.assertEqual(res["etapes"]["uupd"]["statut"], "fini")

    def test_echec_uupd_continue(self):
        f, res = self.lancer(lire_progression=lambda l: PROG_KO)
        self.assertEqual(res["etapes"]["uupd"]["statut"], "echec")
        self.assertFalse(res["succes"])
        for a in ("maj_apps", "resumer", "ecrire_etat"):
            self.assertIn(a, f.appels)

    def test_echec_uupd_par_resultat_de_unite(self):
        f, res = self.lancer(uupd_echoue=lambda unite: True)
        self.assertEqual(res["etapes"]["uupd"]["statut"], "echec")

    def test_maj_apps_75_reporte(self):
        f, res = self.lancer(maj_apps=lambda: 75)
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "reporte")
        self.assertTrue(res["succes"])

    def test_maj_apps_autre_code_echec(self):
        f, res = self.lancer(maj_apps=lambda: 1)
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "echec")

    def test_maj_apps_deja_actif_attend(self):
        etats = [ETAT_MAJ_EN_COURS, ETAT_MAJ_EN_COURS, ETAT_MAJ_INACTIF]
        f, res = self.lancer(maj_apps_etat=lambda: etats.pop(0))
        self.assertNotIn("maj_apps", f.appels)
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "fini")
        self.assertEqual(res["etapes"]["maj-apps"]["detail"], "lancé par le timer")

    def test_maj_apps_en_cours_puis_75_reporte(self):
        etats = [ETAT_MAJ_EN_COURS, ETAT_MAJ_REPORTE]
        f, res = self.lancer(maj_apps_etat=lambda: etats.pop(0))
        self.assertNotIn("maj_apps", f.appels)
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "reporte")

    def test_maj_apps_en_attente_de_relance_est_lance_directement(self):
        f, res = self.lancer(maj_apps_etat=lambda: ETAT_MAJ_REPORTE)
        self.assertIn("maj_apps", f.appels)
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "fini")

    def test_resume_saute_si_jeu_au_moment_du_resume(self):
        f = Fausses(self.tmp, jeu_en_cours=lambda: "Jeu Exemple" if f.appels.count("relever") >= 2 else None)
        res = session.executer(False, deps=f.deps)
        self.assertEqual(res["etapes"]["resume"]["statut"], "saute")
        self.assertEqual(res["etapes"]["uupd"]["statut"], "fini")
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "fini")
        self.assertIn("maj_apps", f.appels)
        self.assertNotIn("resumer", f.appels)
        self.assertIn("ecrire_etat", f.appels)

    def test_changements_envoyes_au_resume(self):
        recu = []
        hist = self.tmp / "h.jsonl"
        hist.write_text(
            json.dumps({"date": "2026-11-09T10:00:00", "changements": [{"module": "uv", "de": "0", "vers": "1"}]}) + "\n"
            + json.dumps({"date": "2026-11-09T11:10:00", "changements": [{"module": "ollama", "de": "1", "vers": "2"}]}) + "\n")
        self.lancer(resumer=lambda ch: recu.extend(ch) or {}, historique=hist)
        self.assertEqual(sorted(c["id"] for c in recu), ["a.b.C", "ollama"])
        self.assertEqual({c["categorie"] for c in recu}, {"applications", "outils"})

    def test_eteindre_apres_echec(self):
        f, res = self.lancer(True, lire_progression=lambda l: PROG_KO)
        self.assertIn("eteindre_pc", f.appels)
        self.assertIn("notifier:Extinction dans 60 secondes — Annuler depuis Health Hub", f.appels)
        self.assertEqual(f.appels.count("annulation_demandee"), 62)   # avant, 60 s, dernier contrôle
        a = datetime.fromisoformat(f.horloge_notif) + timedelta(seconds=60)
        self.assertEqual(res["extinction"], {"a": a.isoformat()})
        self.assertIn("ecrire_etat_leger", f.appels)
        self.assertEqual(f.appels.count("ecrire_etat"), 1)
        self.assertFalse(res["succes"])

    def test_annulation_empeche_extinction(self):
        f, res = self.lancer(True, annulations=[False, False, True])
        self.assertNotIn("eteindre_pc", f.appels)
        self.assertIn("notifier:Extinction annulée", f.appels)
        self.assertEqual(f.appels.count("annulation_demandee"), 3)
        self.assertEqual(res["etapes"]["extinction"]["statut"], "saute")

    def test_annulation_pendant_les_mises_a_jour(self):
        # « Annuler l'extinction » cliqué pendant uupd : pas de compte à rebours du tout.
        f, res = self.lancer(True, annulations=[True])
        self.assertNotIn("eteindre_pc", f.appels)
        self.assertNotIn("notifier:" + session.TEXTE_COMPTE_A_REBOURS, f.appels)
        self.assertIn("notifier:Extinction annulée", f.appels)
        self.assertEqual(res["etapes"]["extinction"]["statut"], "saute")
        self.assertEqual(res["etapes"]["extinction"]["detail"], "annulée")
        self.assertTrue(res["succes"])

    def test_jeu_au_moment_d_eteindre(self):
        f = Fausses(self.tmp, jeu_en_cours=lambda: "Jeu Exemple"
                    if "notifier:" + session.TEXTE_COMPTE_A_REBOURS in f.appels else None)
        res = session.executer(True, deps=f.deps)
        self.assertNotIn("eteindre_pc", f.appels)
        self.assertIn("notifier:Extinction annulée : un jeu est en cours (Jeu Exemple)", f.appels)
        self.assertEqual(res["etapes"]["extinction"]["statut"], "saute")
        self.assertEqual(res["etapes"]["extinction"]["detail"], "un jeu est en cours (Jeu Exemple)")
        archive = json.loads((self.tmp / "sessions" / "2026-11-09T11:00:00.json").read_text())
        self.assertEqual(archive["etapes"]["extinction"]["statut"], "saute")
        self.assertIn("ecrire_etat", f.appels[f.appels.index("notifier:Extinction annulée : un jeu est en cours (Jeu Exemple)"):])

    def test_jeu_avant_le_compte_a_rebours(self):
        f = Fausses(self.tmp, jeu_en_cours=lambda: "Jeu Exemple" if f.appels.count("relever") >= 2 else None)
        res = session.executer(True, deps=f.deps)
        self.assertNotIn("eteindre_pc", f.appels)
        self.assertNotIn("notifier:" + session.TEXTE_COMPTE_A_REBOURS, f.appels)
        self.assertEqual(res["etapes"]["extinction"]["detail"], "un jeu est en cours (Jeu Exemple)")

    def test_extinction_impossible_est_signalee(self):
        f, res = self.lancer(True, eteindre_pc=lambda: "Access denied")
        self.assertEqual(res["etapes"]["extinction"]["statut"], "echec")
        self.assertIn("Access denied", res["etapes"]["extinction"]["detail"])
        self.assertIsNone(res["extinction"])
        self.assertFalse(res["succes"])
        archive = json.loads((self.tmp / "sessions" / "2026-11-09T11:00:00.json").read_text())
        self.assertEqual(archive["etapes"]["extinction"]["statut"], "echec")
        self.assertIn("notifier:Extinction impossible : Access denied", f.appels)
        self.assertEqual(f.appels.count("ecrire_etat"), 2)

    def test_annulation_au_dernier_controle_empeche_extinction(self):
        f, res = self.lancer(True, annulations=[False] * 61 + [True])
        self.assertNotIn("eteindre_pc", f.appels)
        self.assertIn("notifier:Extinction annulée", f.appels)

    def test_annulation_puis_notifier_qui_echoue_n_eteint_pas(self):
        def notifier(texte):
            if texte == "Extinction annulée":
                raise OSError("notify-send absent")
        with redirect_stderr(io.StringIO()):
            f, res = self.lancer(True, annulations=[False, True], notifier=notifier)
        self.assertNotIn("eteindre_pc", f.appels)
        self.assertEqual(res["etapes"]["extinction"]["statut"], "saute")

    def test_exception_ne_bloque_ni_archive_ni_extinction(self):
        def casse():
            raise RuntimeError("boom")
        with redirect_stderr(io.StringIO()) as err:
            f, res = self.lancer(True, relever=casse)
        self.assertIn("boom", err.getvalue())
        self.assertIn("eteindre_pc", f.appels)
        self.assertFalse((self.tmp / "session-en-cours.json").exists())
        self.assertTrue((self.tmp / "sessions" / "2026-11-09T11:00:00.json").exists())
        self.assertEqual(res["etapes"]["notes"]["statut"], "echec")
        self.assertIn("boom", res["etapes"]["notes"]["detail"])
        self.assertFalse(res["succes"])

    def test_sigterm_archive_la_session_interrompue(self):
        # Reboot, arrêt de l'unité, fermeture de session : SIGTERM ne doit pas laisser de session « en cours ».
        recus = []
        precedent = signal.signal(signal.SIGTERM, lambda *a: recus.append(a[0]))
        self.addCleanup(signal.signal, signal.SIGTERM, precedent)
        temoin = signal.getsignal(signal.SIGTERM)

        def maj_apps_tue():
            os.kill(os.getpid(), signal.SIGTERM)
            return 0
        with self.assertRaises(SystemExit) as cm:
            self.lancer(True, maj_apps=maj_apps_tue)
        self.assertEqual(cm.exception.code, 143)
        self.assertEqual(recus, [])
        self.assertIs(signal.getsignal(signal.SIGTERM), temoin)
        self.assertFalse((self.tmp / "session-en-cours.json").exists())
        archive = json.loads((self.tmp / "sessions" / "2026-11-09T11:00:00.json").read_text())
        self.assertIs(archive["succes"], False)
        self.assertEqual(archive["etapes"]["maj-apps"]["statut"], "echec")
        self.assertEqual(archive["etapes"]["maj-apps"]["detail"], "interrompue")
        self.assertEqual(archive["etapes"]["uupd"]["statut"], "fini")
        self.assertEqual(archive["etapes"]["extinction"]["statut"], "saute")

    def test_sigterm_n_eteint_pas(self):
        appels = []
        precedent = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGTERM, precedent)

        def maj_apps_tue():
            os.kill(os.getpid(), signal.SIGTERM)
            return 0
        f = Fausses(self.tmp, maj_apps=maj_apps_tue, eteindre_pc=lambda: appels.append("eteindre_pc"))
        with self.assertRaises(SystemExit):
            session.executer(True, deps=f.deps)
        self.assertEqual(appels, [])

    def test_session_perimee_archivee_au_demarrage(self):
        commun.ecrire_json(self.tmp / "session-en-cours.json", {
            "debut": "2026-11-08T22:00:00", "fin": None, "eteindre": False,
            "etapes": {"uupd": {"statut": "en_cours", "progression": 10, "detail": ""}},
            "global": 10, "succes": None, "extinction": None})
        self.lancer()
        archive = json.loads((self.tmp / "sessions" / "2026-11-08T22:00:00.json").read_text())
        self.assertIs(archive["succes"], False)
        self.assertEqual(archive["etapes"]["uupd"]["detail"], "interrompue")

    def test_exception_dans_une_etape_est_isolee(self):
        def casse():
            raise RuntimeError("kaboom")
        with redirect_stderr(io.StringIO()):
            f, res = self.lancer(maj_apps=casse, ecrire_etat=casse)
        self.assertEqual(res["etapes"]["maj-apps"]["statut"], "echec")
        self.assertIn("kaboom", res["etapes"]["maj-apps"]["detail"])
        self.assertEqual(res["etapes"]["etat"]["statut"], "echec")
        self.assertIn("kaboom", res["etapes"]["etat"]["detail"])
        self.assertTrue((self.tmp / "sessions" / "2026-11-09T11:00:00.json").exists())


def _module_uupd(nom, sortie):
    return [json.dumps({"level": "INFO", "msg": "Command output", "module": nom, "status": "running", "output": sortie}),
            json.dumps({"level": "INFO", "msg": "fin", "module": nom, "status": "finished", "exit_code": 0})]


class BilanDeSession(Base):
    def _historique(self, *resultats):
        h = self.tmp / "h.jsonl"
        h.write_text(json.dumps({"date": "2026-11-09T11:00:30", "resultats": list(resultats), "changements": []}) + "\n")
        return h

    def test_tout_a_jour(self):
        rel = {"date": "x", "image": "45.1", "paquets": {}, "flatpak": {"a.b.C": "1"}, "brew": {}}
        h = self._historique({"module": "uv", "etat": "à jour", "message": "uv 0.13.7", "details": ""})
        f = Fausses(self.tmp, historique=h,
                    lignes_uupd=lambda u, d: [*_module_uupd("system", "No upgrade available."),
                                               *_module_uupd("flatpak", "Nothing to update.")])
        f.releves = [rel, rel]
        res = session.executer(False, deps=f.deps)
        self.assertEqual(res["etapes"]["uupd"]["detail"],
                         "Système : déjà à jour\nFlatpak : rien à mettre à jour")
        self.assertEqual(res["etapes"]["maj-apps"]["detail"], "Tout est à jour (uv 0.13.7)")
        self.assertEqual(res["etapes"]["notes"]["detail"], "rien à résumer")
        self.assertEqual(res["etapes"]["resume"]["detail"], "rien à résumer")
        self.assertEqual(res["changements"], [])
        self.assertEqual(res["bilan"], "Tout était déjà à jour.")
        archive = json.loads((self.tmp / "sessions" / "2026-11-09T11:00:00.json").read_text())
        self.assertEqual(archive["bilan"], "Tout était déjà à jour.")

    def test_changements_et_resumes(self):
        h = self._historique({"module": "ollama", "etat": "mis à jour", "message": "Ollama 0.32.15 → 0.40.15", "details": ""})
        h.write_text(json.dumps({"date": "2026-11-09T11:00:30", "resultats": json.loads(h.read_text())["resultats"],
                                 "changements": [{"module": "ollama", "de": "0.32.15", "vers": "0.40.15"}]}) + "\n")
        f = Fausses(self.tmp, historique=h,
                    lignes_uupd=lambda u, d: _module_uupd("flatpak", "Updating"),
                    resumer=lambda ch: {f"{c['id']}@{c['vers']}": {"resume": "ok" if c["id"] == "a.b.C" else None,
                                                                    "notes": "n"} for c in ch})
        res = session.executer(False, deps=f.deps)
        self.assertEqual(res["etapes"]["uupd"]["detail"], "Flatpak : 1 application mise à jour")
        self.assertEqual(res["etapes"]["maj-apps"]["detail"], "Ollama 0.32.15 → 0.40.15")
        self.assertEqual(res["etapes"]["notes"]["detail"], "notes trouvées pour 2 changements")
        self.assertEqual(res["etapes"]["resume"]["detail"], "1 résumé écrit")
        self.assertEqual(sorted(c["id"] for c in res["changements"]), ["a.b.C", "ollama"])
        self.assertEqual(res["bilan"], "2 changements : 1 application, Ollama 0.40.15.")

    def test_image_en_attente(self):
        f = Fausses(self.tmp, lignes_uupd=lambda u, d: _module_uupd("system", "Staging done"),
                    deploiements=lambda: {"en_attente": True})
        res = session.executer(False, deps=f.deps)
        self.assertEqual(res["etapes"]["uupd"]["detail"], "Système : nouvelle image prête, redémarrage nécessaire")

    def test_jeu_en_cours_saute(self):
        f = Fausses(self.tmp, jeu_en_cours=lambda: "Jeu Exemple" if f.appels.count("relever") >= 2 else None)
        res = session.executer(False, deps=f.deps)
        self.assertEqual(res["etapes"]["notes"]["detail"], "sauté : un jeu tournait")
        self.assertEqual(res["etapes"]["resume"]["detail"], "sauté : un jeu tournait")
        self.assertEqual(res["bilan"], "1 changement : 1 application.")

    def test_maj_apps_reporte(self):
        f = Fausses(self.tmp, maj_apps=lambda: 75)
        res = session.executer(False, deps=f.deps)
        self.assertEqual(res["etapes"]["maj-apps"]["detail"], "reporté (jeu en cours ou GitHub injoignable)")

    def test_echec_uupd_dans_le_bilan(self):
        f = Fausses(self.tmp, lire_progression=lambda l: PROG_KO)
        res = session.executer(False, deps=f.deps)
        self.assertTrue(res["bilan"].endswith("Une étape a échoué."))

    def test_releve_impossible(self):
        def casse():
            raise RuntimeError("boom")
        with redirect_stderr(io.StringIO()):
            f, res = self.lancer(relever=casse)
        self.assertEqual(res["changements"], [])
        self.assertEqual(res["bilan"], "Changements inconnus : relevé impossible.")


class ResumerChangements(Base):
    def test_ne_refait_pas_les_resumes_en_cache(self):
        commun.ecrire_json(self.tmp / "resumes.json",
                           {"a@2": {"resume": "déjà fait", "source": "s", "lien": None, "notes": "n"}})
        recu = []
        chs = [{"categorie": "applications", "id": "a", "nom": "A", "de": "1", "vers": "2"},
               {"categorie": "applications", "id": "b", "nom": "B", "de": "1", "vers": "2"}]
        session.resumer_changements(
            chs, notes_pour=lambda c: {"source": "src", "texte": "notes de " + c["id"], "lien": "http://x"},
            resumer=lambda els: recu.extend(els) or {"b": "résumé de b"}, jeu=lambda: None)
        self.assertEqual([e["id"] for e in recu], ["b"])
        table = json.loads((self.tmp / "resumes.json").read_text())
        self.assertEqual(table["a@2"]["resume"], "déjà fait")
        self.assertEqual(table["b@2"], {"resume": "résumé de b", "source": "src",
                                        "lien": "http://x", "notes": "notes de b"})

    def test_sans_notes_pas_de_resume(self):
        recu = []
        chs = [{"categorie": "outils", "id": "node", "nom": "node", "de": "1", "vers": "2"}]
        session.resumer_changements(chs, notes_pour=lambda c: None,
                                    resumer=lambda els: recu.extend(els) or {}, jeu=lambda: None)
        self.assertEqual(recu, [])
        table = json.loads((self.tmp / "resumes.json").read_text())
        self.assertEqual(table["node@2"], {"resume": None, "source": None, "lien": None, "notes": None})

    CHS = [{"categorie": "applications", "id": "a", "nom": "A", "de": "1", "vers": "2"}]

    def resumer_a(self, heure, resumer, jeu=lambda: None):
        return session.resumer_changements(
            self.CHS, notes_pour=lambda c: {"source": "s", "texte": "notes", "lien": None},
            resumer=resumer, jeu=jeu, maintenant=lambda: heure)

    def test_echec_de_resume_retente_au_plus_une_fois_par_jour(self):
        appels = []
        rate = lambda els: appels.append(len(els)) or None
        self.resumer_a("2026-11-09T08:00:00", rate)
        table = json.loads((self.tmp / "resumes.json").read_text())
        self.assertEqual(table["a@2"]["tentative"], "2026-11-09T08:00:00")
        self.resumer_a("2026-11-09T19:00:00", rate)          # nouvelle ouverture le soir : pas d'Ollama
        self.assertEqual(appels, [1])
        self.resumer_a("2026-11-10T08:30:00", lambda els: appels.append(len(els)) or {"a": "Résumé."})
        self.assertEqual(appels, [1, 1])
        table = json.loads((self.tmp / "resumes.json").read_text())
        self.assertEqual(table["a@2"]["resume"], "Résumé.")
        self.assertNotIn("tentative", table["a@2"])

    def test_un_jeu_n_est_pas_une_tentative(self):
        appels = []
        self.resumer_a("2026-11-09T08:00:00", lambda els: appels.append(1), jeu=lambda: "Jeu Exemple")
        self.assertEqual(appels, [])
        self.assertNotIn("tentative", json.loads((self.tmp / "resumes.json").read_text())["a@2"])
        jeux = iter([None])        # le jeu démarre pendant le résumé (abandonné par resume.resumer)
        self.resumer_a("2026-11-09T08:00:00", lambda els: None, jeu=lambda: next(jeux, "Jeu Exemple"))
        self.assertNotIn("tentative", json.loads((self.tmp / "resumes.json").read_text())["a@2"])


class Cli(Base):
    def appeler(self, argv, **kw):
        sortie, erreur = io.StringIO(), io.StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = cli.main(argv, **kw)
        return code, sortie.getvalue() + erreur.getvalue()

    def test_cli_maj_deja_en_cours(self):
        appels = []

        def faux_run(cmd, **kw):
            appels.append(cmd)
            return 1, "Failed to start transient service unit: Unit centre-bazzite-maj.service was already loaded or has a fragment file."
        code, texte = self.appeler(["maj", "--eteindre"], run=faux_run, jeu=lambda: None)
        self.assertEqual(code, 0)
        self.assertIn("Une mise à jour est déjà en cours.", texte)
        cmd = appels[0]
        self.assertEqual(cmd[:5], ["systemd-run", "--user", "--unit=centre-bazzite-maj", "--collect",
                                   "--property=Type=exec"])
        self.assertEqual(cmd[-2:], ["_session", "--eteindre"])

    def test_cli_maj_refuse_si_un_jeu_tourne(self):
        appels, leger = [], []
        code, texte = self.appeler(["maj"], run=lambda cmd, **kw: appels.append(cmd) or (0, ""),
                                   jeu=lambda: "Jeu Exemple", ecrire_leger=lambda: leger.append(1))
        self.assertEqual(code, cli.CODE_JEU)
        self.assertIn("Un jeu tourne (Jeu Exemple) : mise à jour non lancée.", texte)
        self.assertEqual(appels, [])
        self.assertEqual(leger, [1])      # l'état montre le jeu tout de suite aux interfaces

    def test_cli_maj_meme_si_jeu(self):
        appels = []
        code, texte = self.appeler(["maj", "--eteindre", "--meme-si-jeu"],
                                   run=lambda cmd, **kw: appels.append(cmd) or (0, ""),
                                   jeu=lambda: "Jeu Exemple", ecrire_leger=lambda: None)
        self.assertEqual(code, 0)
        self.assertEqual(appels[0][-2:], ["_session", "--eteindre"])

    def test_cli_maj_sans_jeu(self):
        appels = []
        code, _ = self.appeler(["maj"], run=lambda cmd, **kw: appels.append(cmd) or (0, ""),
                               jeu=lambda: None, ecrire_leger=lambda: None)
        self.assertEqual(code, 0)
        self.assertEqual(appels[0][-1], "_session")

    def test_cli_resumer_ne_refait_pas_les_resumes_en_cache(self):
        chs = [{"categorie": "applications", "id": "a", "nom": "A", "de": "1", "vers": "2"},
               {"categorie": "applications", "id": "b", "nom": "B", "de": "1", "vers": "2"}]
        commun.ecrire_json(self.tmp / "etat.json", {"depuis_visite": {"chronologie": [{"changements": chs}]}})
        commun.ecrire_json(self.tmp / "resumes.json", {"a@2": {"resume": "fait", "source": None, "lien": None, "notes": "n"}})
        recu, ecrit = [], []
        code, _ = self.appeler(
            ["resumer"], notes_pour=lambda c: {"source": "s", "texte": "t " + c["id"], "lien": None},
            resumer=lambda els: recu.extend(els) or {"b": "rb"}, ecrire_etat=lambda: ecrit.append(1),
            jeu=lambda: None)
        self.assertEqual(code, 0)
        self.assertEqual([e["id"] for e in recu], ["b"])
        self.assertEqual(ecrit, [1])

    def test_cli_annuler_extinction(self):
        code, _ = self.appeler(["annuler-extinction"])
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "annuler-extinction").exists())


if __name__ == "__main__":
    unittest.main()


class Notification(unittest.TestCase):
    def test_nom_d_application_health_hub(self):
        with mock.patch.object(commun, "run", return_value=(0, "")) as run:
            session._notifier("Bonjour")
        run.assert_called_once_with(["notify-send", "-a", "Health Hub", "Bonjour"])
