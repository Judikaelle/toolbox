import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import commun, etat, modejeu, points

SANTE_OK = {"ssd": [], "volumes": [], "services_en_echec": [], "ollama": None,
            "erreurs_journal": [], "plantages": []}
DEP = {"courant": {"version": "45.1"}, "en_attente": None, "precedent": None}


def ch(cat, id_, de, vers, nom=None):
    return {"categorie": cat, "id": id_, "nom": nom or id_, "de": de, "vers": vers}


class Chronologie(unittest.TestCase):
    def test_chronologie_attribution(self):
        changements = [ch("applications", "org.libreoffice.LibreOffice", "1", "2", "LibreOffice"),
                       ch("applications", "org.mozilla.firefox", "1", "2", "Firefox"),
                       ch("outils", "ollama", "0.32", "0.40.15", "Ollama"),
                       ch("outils", "uv", "0.1", "0.2", "uv"),
                       ch("outils", "node", "1", "2", "node")]
        ex = {"uupd": {"debut": "2026-11-09T11:20:00", "fin": "2026-11-09T11:30:00", "succes": True},
              "maj_apps": {"ollama": "2026-11-09T11:24:40", "uv": "2026-11-09T11:24:40"}}
        res = etat.chronologie("2026-11-09T08:00:00", changements, ex)
        vus = {e["titre"]: e for e in res}
        self.assertEqual(set(vus), {"2 applications", "Ollama 0.40.15", "uv 0.2", "1 outil Homebrew"})
        self.assertEqual(vus["Ollama 0.40.15"]["heure"], "2026-11-09T11:24:40")
        self.assertEqual(vus["Ollama 0.40.15"]["categorie"], "outils")
        self.assertEqual(len(vus["Ollama 0.40.15"]["changements"]), 1)
        self.assertEqual(vus["2 applications"]["heure"], "2026-11-09T11:30:00")
        self.assertEqual(vus["2 applications"]["categorie"], "applications")
        self.assertEqual(vus["1 outil Homebrew"]["categorie"], "outils")
        self.assertEqual([e["heure"] for e in res], sorted(e["heure"] for e in res))

    def test_paquets_systeme_sans_image(self):
        ex = {"uupd": {"debut": None, "fin": "2026-11-09T11:30:00", "succes": True}, "maj_apps": {}}
        res = etat.chronologie("2026-11-09T08:00:00", [ch("systeme", "kernel", "1", "2")], ex)
        self.assertEqual(res[0]["titre"], "Paquets système")

    def test_titre_bazzite_si_image_changee(self):
        c = [ch("systeme", "image", "45.1", "45.2", "Bazzite"), ch("systeme", "kernel", "1", "2")]
        ex = {"uupd": {"debut": None, "fin": "2026-11-09T11:30:00", "succes": True}, "maj_apps": {}}
        res = etat.chronologie("2026-11-09T08:00:00", c, ex)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["titre"], "Bazzite 45.2")
        self.assertEqual(res[0]["categorie"], "systeme")
        self.assertEqual(len(res[0]["changements"]), 2)

    def test_sans_execution_heure_du_releve_apres(self):
        ex = {"uupd": None, "maj_apps": {}, "apres": "2026-11-09T12:00:00"}
        res = etat.chronologie("2026-11-09T08:00:00", [ch("outils", "node", "1", "2")], ex)
        self.assertEqual(res[0]["heure"], "2026-11-09T12:00:00")
        self.assertEqual(res[0]["titre"], "1 outil Homebrew")


class Phrases(unittest.TestCase):
    def test_phrases(self):
        self.assertEqual(etat.phrases("vert", [], 0), ("Tout est à jour.", "Rien à signaler."))
        self.assertEqual(etat.phrases("en_cours", [], 0),
                         ("Mise à jour en cours…", "Tu peux continuer à utiliser ton PC."))
        un = [{"id": "volume:x", "gravite": "attention", "en_sourdine": False}]
        self.assertEqual(etat.phrases("orange", un, 0), ("Tout est à jour.", "Une chose mérite un coup d'œil."))
        deux = un + [{"id": "service:y", "gravite": "attention", "en_sourdine": False}]
        self.assertEqual(etat.phrases("rouge", deux, 0)[1], "2 choses méritent un coup d'œil.")
        attente = [{"id": "redemarrage:45.2", "gravite": "attention", "en_sourdine": False}]
        self.assertEqual(etat.phrases("orange", attente, 0)[0], "Des mises à jour t'attendent.")
        self.assertEqual(etat.phrases("vert", [], 0, premier=True),
                         ("Premier passage : rien à comparer pour l'instant.", "Rien à signaler."))


    def test_phrase_mises_a_jour_disponibles(self):
        dispo = {"id": "maj:dispo:flatpak", "gravite": "info", "en_sourdine": False}
        # maj:dispo: est une information : la couleur reste verte
        self.assertEqual(etat.phrases("vert", [dispo], 0), ("Des mises à jour sont disponibles.", "Rien à signaler."))
        volume = {"id": "volume:x", "gravite": "attention", "en_sourdine": False}
        self.assertEqual(etat.phrases("orange", [dispo, volume], 0),
                         ("Des mises à jour sont disponibles.", "Une chose mérite un coup d'œil."))
        attente = {"id": "redemarrage:45.2", "gravite": "attention", "en_sourdine": False}
        self.assertEqual(etat.phrases("orange", [dispo, attente], 0)[0], "Des mises à jour sont disponibles.")
        echec = {"id": "stockage:non-monte:/var/mnt/DONNEES", "gravite": "echec", "en_sourdine": False}
        self.assertEqual(etat.phrases("rouge", [dispo, echec], 0)[0], "Un problème demande ton attention.")
        muet = dict(dispo, en_sourdine=True)
        self.assertEqual(etat.phrases("vert", [muet], 0)[0], "Tout est à jour.")
        self.assertEqual(etat.phrases("vert", [dispo], 0, premier=True)[0],
                         "Premier passage : rien à comparer pour l'instant.")

    def test_titre_quand_c_est_rouge(self):
        echec = {"id": "maj:echec:uupd:2026-11-09T04:10:00", "gravite": "echec", "en_sourdine": False}
        attente = {"id": "redemarrage:45.2", "gravite": "attention", "en_sourdine": False}
        self.assertEqual(etat.phrases("rouge", [echec, attente], 0),
                         ("Une mise à jour a échoué.", "2 choses méritent un coup d'œil."))
        ssd = {"id": "ssd:X:critique:erreurs-media", "gravite": "echec", "en_sourdine": False}
        self.assertEqual(etat.phrases("rouge", [ssd], 0)[0], "Un problème demande ton attention.")


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.etat = self.dir / "etat"
        self.etat.mkdir()
        p = mock.patch.object(commun, "ETAT", self.etat)
        p.start()
        self.addCleanup(p.stop)
        import centre_bazzite.inventaire as inv
        p = mock.patch.object(inv, "ETAT", self.etat)
        p.start()
        self.addCleanup(p.stop)
        self.histo = self.dir / "historique.jsonl"

    def construire(self, **kw):
        args = dict(collecter=lambda: SANTE_OK, deploiements=lambda: DEP,
                    unite_active=lambda: None, executions=lambda depuis: [],
                    historique=self.histo, session_active=lambda: True, jeu=lambda: None,
                    ollama=lambda: None, controles=lambda: None)
        args.update(kw)
        return etat.construire(**args)


class Construire(Base):
    def test_etat_premier_lancement(self):
        e = self.construire()
        self.assertEqual(e["couleur"], "vert")
        self.assertEqual(e["phrase"], "Premier passage : rien à comparer pour l'instant.")
        self.assertEqual(e["depuis_visite"], {"depuis": None, "nombre": 0, "chronologie": []})
        self.assertIsNone(e["en_cours"])
        self.assertEqual((e["resumes"], e["notes"]), ({}, {}))
        for k in ("genere", "phrase2", "extinction", "redemarrage", "sante", "points"):
            self.assertIn(k, e)

    def test_etat_contient_les_compteurs(self):
        self.assertEqual(set(self.construire()["compteurs"]), {"majs", "sante", "stockage"})

    def test_chaque_point_porte_sa_rubrique(self):
        """Revue finale I3 : les listes « À regarder » des pages filtrent sur ce champ, calculé par points.rubrique,
        la règle même des compteurs du menu."""
        c = {"date": "2026-11-09T10:00:00", "image": {"disponible": "45.20261110"}, "flatpak": None,
             "runtimes": None, "telechargements": [{"nom": "x.iso", "octets": 1, "present": 40}], "caches": None,
             "boot": None}
        s = dict(SANTE_OK, services_en_echec=["foo.service"], controles=c)      # relevé complet : la santé les porte
        e = self.construire(collecter=lambda: s)
        rubriques = {p["id"]: p["rubrique"] for p in e["points"]}
        self.assertEqual(rubriques["maj:dispo:image:45.20261110"], "majs")
        self.assertEqual(rubriques["menage:telechargements-incomplets"], "stockage")
        self.assertEqual(rubriques["service:foo.service"], "sante")
        self.assertEqual(rubriques, {p["id"]: points.rubrique(p["id"]) for p in e["points"]})

    def test_chaque_point_porte_son_domaine(self):
        """Task 19 : les onglets de la page Santé lisent ce champ (pire gravité de leur domaine), calculé par
        points.domaine comme la rubrique l'est par points.rubrique."""
        c = {"date": "2026-11-09T10:00:00", "image": {"disponible": "45.20261110"}, "flatpak": None,
             "runtimes": None, "telechargements": [{"nom": "x.iso", "octets": 1, "present": 40}], "caches": None,
             "boot": None}
        s = dict(SANTE_OK, services_en_echec=["foo.service"], controles=c)
        e = self.construire(collecter=lambda: s)
        domaines = {p["id"]: p["domaine"] for p in e["points"]}
        self.assertEqual(domaines["maj:dispo:image:45.20261110"], "controles")
        self.assertEqual(domaines["menage:telechargements-incomplets"], "controles")
        self.assertEqual(domaines["service:foo.service"], "systeme")
        self.assertEqual(domaines, {p["id"]: points.domaine(p["id"]) for p in e["points"]})

    def test_premier_lancement_orange(self):
        s = dict(SANTE_OK, services_en_echec=["foo.service"])
        e = self.construire(collecter=lambda: s)
        self.assertEqual(e["couleur"], "orange")

    def test_depuis_visite_avec_historique_et_resumes(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00", "releve": "x"})
        avant = {"date": "2026-11-09T07:00:00", "image": "1", "paquets": {}, "flatpak": {}, "brew": {"node": "1"}}
        apres = {"date": "2026-11-09T12:00:00", "image": "1", "paquets": {}, "flatpak": {}, "brew": {"node": "2"}}
        commun.ecrire_json(self.etat / "releves" / "a.json", avant)
        commun.ecrire_json(self.etat / "releves" / "b.json", apres)
        commun.ecrire_json(self.etat / "resumes.json", {
            "node@2": {"resume": "Un résumé.", "source": "GitHub", "lien": "http://x", "notes": "n"},
            "ollama@0.40": {"resume": None, "source": "maj-apps", "lien": None, "notes": "n"}})
        self.histo.write_text(
            json.dumps({"date": "2026-11-09T07:30:00", "changements": [
                {"module": "uv", "de": "0.1", "vers": "0.2"}]}) + "\n"
            + json.dumps({"date": "2026-11-09T11:24:40", "changements": [
                {"module": "ollama", "de": "0.32", "vers": "0.40"}]}) + "\n"
            + json.dumps({"date": "2026-11-09T11:50:00", "resultats": []}) + "\n")
        e = self.construire(executions=lambda d: [{"unite": "uupd.service", "debut": "2026-11-09T11:00:00",
                                                  "fin": "2026-11-09T11:30:00", "succes": True}])
        dv = e["depuis_visite"]
        self.assertEqual(dv["nombre"], 2)
        self.assertEqual(dv["depuis"], "2026-11-09T08:00:00")
        heures = {c["heure"]: c for c in dv["chronologie"]}
        self.assertEqual(set(heures), {"2026-11-09T11:24:40", "2026-11-09T11:30:00"})
        self.assertEqual(heures["2026-11-09T11:24:40"]["titre"], "Ollama 0.40")
        self.assertEqual(heures["2026-11-09T11:24:40"]["changements"][0]["nom"], "Ollama")
        self.assertEqual(e["resumes"], {"node": "Un résumé."})
        self.assertEqual(e["notes"]["node"], {"source": "GitHub", "lien": "http://x", "texte": "n"})
        self.assertEqual(e["notes"]["ollama"], {"source": "maj-apps", "lien": None, "texte": "n"})
        self.assertEqual(e["couleur"], "vert")

    def test_diff_depuis_le_releve_de_reference_de_la_visite(self):
        commun.ecrire_json(self.etat / "visites.json",
                           {"derniere": "2026-11-09T08:00:00", "releve": "2026-11-09T06:00:00"})
        for date, node in (("2026-11-09T06:00:00", "1"), ("2026-11-09T07:30:00", "1.5"),
                           ("2026-11-09T12:00:00", "2")):
            commun.ecrire_json(self.etat / "releves" / f"{date}.json",
                               {"date": date, "image": "1", "paquets": {}, "flatpak": {}, "brew": {"node": node}})
        e = self.construire()
        c = e["depuis_visite"]["chronologie"][0]["changements"][0]
        self.assertEqual((c["de"], c["vers"]), ("1", "2"))

    def test_notes_d_origine_dans_l_etat(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        commun.ecrire_json(self.etat / "resumes.json", {
            "ollama@0.40": {"resume": None, "source": "GitHub", "lien": "http://x", "notes": "a" * 5000},
            "uv@0.2": {"resume": None, "source": None, "lien": None, "notes": None}})
        self.histo.write_text(
            json.dumps({"date": "2026-11-09T11:24:40", "changements": [
                {"module": "ollama", "de": "0.32", "vers": "0.40"},
                {"module": "uv", "de": "0.1", "vers": "0.2"}]}) + "\n")
        e = self.construire()
        n = e["notes"]["ollama"]
        self.assertEqual(len(n["texte"]), 4000)
        self.assertEqual((n["source"], n["lien"]), ("GitHub", "http://x"))
        self.assertNotIn("uv", e["notes"])

    def test_maj_apps_deux_lignes_meme_module(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        self.histo.write_text(
            json.dumps({"date": "2026-11-09T10:00:00", "changements": [
                {"module": "ollama", "de": "0.32", "vers": "0.35"}]}) + "\n"
            + json.dumps({"date": "2026-11-09T11:24:00", "changements": [
                {"module": "ollama", "de": "0.35", "vers": "0.40"}]}) + "\n")
        e = self.construire()
        chrono = e["depuis_visite"]["chronologie"]
        self.assertEqual([(c["heure"], c["titre"]) for c in chrono],
                         [("2026-11-09T10:00:00", "Ollama 0.35"), ("2026-11-09T11:24:00", "Ollama 0.40")])

    def _session(self, debut, fin, bilan="Tout était déjà à jour.", eteindre=False, succes=True):
        s = {"debut": debut, "fin": fin, "eteindre": eteindre, "etapes": {}, "global": 100,
             "succes": succes, "extinction": None}
        if bilan:
            s["bilan"] = bilan
        commun.ecrire_json(self.etat / "sessions" / f"{debut}.json", s)

    def test_chaque_session_depuis_la_visite_dans_la_chronologie(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        self._session("2026-11-09T07:00:00", "2026-11-09T07:01:00")       # avant la visite : absente
        self._session("2026-11-09T14:52:27", "2026-11-09T14:52:56")
        self._session("2026-11-09T15:10:00", "2026-11-09T15:10:40", bilan="3 changements : 3 applications.",
                      eteindre=True)
        e = self.construire()
        chrono = e["depuis_visite"]["chronologie"]
        self.assertEqual([(c["heure"], c["titre"], c.get("ligne")) for c in chrono],
                         [("2026-11-09T14:52:56", "Mise à jour vérifiée", "Tout était déjà à jour."),
                          ("2026-11-09T15:10:40", "Mise à jour et extinction", "3 changements : 3 applications.")])
        self.assertEqual(chrono[0]["changements"], [])
        self.assertEqual(e["depuis_visite"]["nombre"], 0)
        self.assertEqual(e["derniere_maj"], {"heure": "2026-11-09T15:10:40",
                                             "bilan": "3 changements : 3 applications."})

    def test_session_ancienne_sans_bilan(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        self._session("2026-11-09T14:52:27", "2026-11-09T14:52:56", bilan=None)
        e = self.construire()
        self.assertEqual(e["depuis_visite"]["chronologie"][0]["ligne"], "Détails non enregistrés pour cette session.")

    def test_session_echouee_ou_interrompue(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        self._session("2026-11-09T14:52:27", "2026-11-09T14:52:56", bilan=None, succes=False)
        c = self.construire()["depuis_visite"]["chronologie"][0]
        self.assertEqual(c["titre"], "Mise à jour incomplète")

    def test_sans_session_depuis_la_visite(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        e = self.construire()
        self.assertIsNone(e["derniere_maj"])
        self.assertEqual(e["depuis_visite"]["chronologie"], [])

    def test_en_cours_et_extinction(self):
        commun.ecrire_json(self.etat / "session-en-cours.json", {
            "debut": "d", "fin": None, "eteindre": True, "etapes": {}, "global": 10,
            "succes": None, "extinction": {"a": "2026-11-09T13:00:00"}})
        e = self.construire()
        self.assertEqual(e["couleur"], "en_cours")
        self.assertEqual(e["extinction"], {"a": "2026-11-09T13:00:00"})
        self.assertEqual(e["phrase"], "Mise à jour en cours…")

    def ecrire_session_en_cours(self):
        commun.ecrire_json(self.etat / "session-en-cours.json", {
            "debut": "2026-11-09T22:00:00", "fin": None, "eteindre": True,
            "etapes": {"uupd": {"statut": "fini", "progression": 100, "detail": ""},
                       "maj-apps": {"statut": "en_cours", "progression": 40, "detail": ""},
                       "notes": {"statut": "attente", "progression": 0, "detail": ""},
                       "extinction": {"statut": "attente", "progression": 0, "detail": ""}},
            "global": 40, "succes": None, "extinction": {"a": "2026-11-09T22:30:00"}})

    def test_session_perimee_archivee_comme_interrompue(self):
        # Reboot pendant une session : le fichier est resté, mais l'unité ne tourne plus.
        self.ecrire_session_en_cours()
        with mock.patch.object(commun, "maintenant", return_value="2026-11-10T08:00:00"):
            e = self.construire(session_active=lambda: False)
        self.assertIsNone(e["en_cours"])
        self.assertIsNone(e["extinction"])
        self.assertNotEqual(e["couleur"], "en_cours")
        self.assertNotEqual(e["phrase"], "Mise à jour en cours…")
        self.assertFalse((self.etat / "session-en-cours.json").exists())
        archive = json.loads((self.etat / "sessions" / "2026-11-09T22:00:00.json").read_text())
        self.assertIs(archive["succes"], False)
        self.assertEqual(archive["fin"], "2026-11-10T08:00:00")
        self.assertEqual(archive["etapes"]["maj-apps"]["statut"], "echec")
        self.assertEqual(archive["etapes"]["maj-apps"]["detail"], "interrompue")
        self.assertEqual(archive["etapes"]["uupd"]["statut"], "fini")
        self.assertEqual(archive["etapes"]["notes"]["statut"], "saute")
        self.assertIsNone(archive["extinction"])

    def test_session_perimee_n_ecrase_pas_une_archive_existante(self):
        # La session a eu le temps de s'archiver elle-même : son archive fait foi.
        self.ecrire_session_en_cours()
        commun.ecrire_json(self.etat / "sessions" / "2026-11-09T22:00:00.json",
                           {"debut": "2026-11-09T22:00:00", "fin": "2026-11-09T22:40:00", "succes": True})
        self.construire(session_active=lambda: False)
        archive = json.loads((self.etat / "sessions" / "2026-11-09T22:00:00.json").read_text())
        self.assertIs(archive["succes"], True)
        self.assertFalse((self.etat / "session-en-cours.json").exists())

    def test_extinction_annulee_pendant_la_session(self):
        self.ecrire_session_en_cours()
        e = self.construire()
        self.assertIs(e["en_cours"]["eteindre"], True)
        self.assertIs(e["extinction_annulee"], False)
        (self.etat / "annuler-extinction").touch()
        self.assertIs(self.construire()["extinction_annulee"], True)

    def test_session_vivante_gardee(self):
        self.ecrire_session_en_cours()
        e = self.construire(session_active=lambda: True)
        self.assertEqual(e["couleur"], "en_cours")
        self.assertTrue((self.etat / "session-en-cours.json").exists())
        self.assertFalse((self.etat / "sessions").exists())

    def test_jeu_en_cours_dans_l_etat(self):
        self.assertIsNone(self.construire()["jeu"])
        self.assertEqual(self.construire(jeu=lambda: "Jeu Exemple")["jeu"], "Jeu Exemple")

    def test_etat_contient_modejeu(self):
        """Task 6 : le résumé du mode jeu, en complet comme en léger (D14) ; en panne, None."""
        import inspect
        self.assertIs(inspect.signature(etat.construire).parameters["modejeu"].default, modejeu.resume)
        resume = {"etat": "pret", "phrase": "Mode jeu prêt : il s'active quand un jeu démarre."}
        for complet in (True, False):
            with self.subTest(complet=complet):
                self.assertEqual(self.construire(complet=complet, modejeu=lambda: resume)["modejeu"], resume)

        def panne():
            raise ValueError("modejeu.json abîmé")
        self.assertIsNone(self.construire(modejeu=panne)["modejeu"])

    def test_modejeu_par_defaut_lu_dans_commun_etat(self):
        """Sans injection : modejeu.json du dossier d'état (absent ici), donc le service ne tourne pas."""
        self.assertEqual(self.construire()["modejeu"]["etat"], "arrete")

    def test_unite_active_donne_en_cours(self):
        e = self.construire(unite_active=lambda: "uupd.service")
        self.assertEqual(e["en_cours"], {"unite": "uupd.service"})
        self.assertEqual(e["couleur"], "en_cours")

    def session(self, nom, etape_ko=None):
        etapes = {n: {"statut": "fini", "progression": 100, "detail": ""} for n in ("uupd", "maj-apps", "resume")}
        if etape_ko:
            etapes[etape_ko] = {"statut": "echec", "progression": 0, "detail": "boum"}
        commun.ecrire_json(self.etat / "sessions" / f"{nom}.json",
                           {"debut": nom, "fin": nom, "succes": etape_ko is None, "etapes": etapes})

    def test_session_echouee_rend_rouge(self):
        self.session("2026-11-08T22:00:00")
        self.session("2026-11-09T22:00:00", "uupd")
        e = self.construire()
        self.assertEqual(e["couleur"], "rouge")

    def test_echec_du_resume_seul_ne_rend_pas_rouge(self):
        self.session("2026-11-09T22:00:00", "resume")
        e = self.construire()
        self.assertEqual(e["couleur"], "vert")
        self.assertIn("session:echec:2026-11-09T22:00:00", [p["id"] for p in e["points"]])

    def test_echec_uupd_avant_la_visite_reste_jusqu_a_une_reussite(self):
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        lus = []
        ko = {"unite": "uupd.service", "debut": "2026-11-08T04:00:00", "fin": "2026-11-08T04:10:00", "succes": False}
        ok = {"unite": "uupd.service", "debut": "2026-11-09T09:00:00", "fin": "2026-11-09T09:10:00", "succes": True}
        e = self.construire(executions=lambda depuis: lus.append(depuis) or [ko])
        self.assertLessEqual(lus[0], "2026-11-08T04:00:00")
        self.assertEqual(e["couleur"], "rouge")
        self.assertIn("maj:echec:uupd:2026-11-08T04:10:00", [p["id"] for p in e["points"]])
        self.assertEqual(e["depuis_visite"]["chronologie"], [])
        e = self.construire(executions=lambda depuis: [ko, ok])
        self.assertEqual(e["couleur"], "vert")

    def test_complet_faux_reprend_la_sante(self):
        commun.ecrire_json(self.etat / "etat.json", {"sante": {"ssd": [], "volumes": [], "marque": 1}})
        appels = []
        e = self.construire(complet=False, collecter=lambda: appels.append(1))
        self.assertEqual(appels, [])
        self.assertEqual(e["sante"]["marque"], 1)

    def test_leger_relit_ollama(self):
        # « Arrêter Ollama » : le rafraîchissement léger qui suit doit voir le service arrêté.
        actif = {"actif": True, "depuis": "2026-11-09T01:00:00", "modeles_charges": []}
        commun.ecrire_json(self.etat / "etat.json", {"sante": dict(SANTE_OK, ollama=actif)})
        arrete = {"actif": False, "depuis": None, "modeles_charges": []}
        e = self.construire(complet=False, ollama=lambda: arrete)
        self.assertEqual(e["sante"]["ollama"], arrete)
        self.assertNotIn("ollama:inactif", [p["id"] for p in e["points"]])

    def test_leger_relit_les_controles(self):
        # Ruling V5 : « centre-bazzite controles » se voit dès le rafraîchissement léger qui suit.
        commun.ecrire_json(self.etat / "etat.json", {"sante": dict(SANTE_OK, controles=None)})
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        c = {"date": "2026-11-09T10:00:00", "image": {"disponible": "45.20261110"}, "flatpak": None,
             "runtimes": None, "telechargements": None, "caches": None, "boot": None}
        e = self.construire(complet=False, controles=lambda: c)
        self.assertEqual(e["sante"]["controles"], c)
        self.assertIn("maj:dispo:image:45.20261110", [p["id"] for p in e["points"]])
        self.assertEqual(e["phrase"], "Des mises à jour sont disponibles.")
        self.assertEqual(e["compteurs"]["majs"], 1)

    def test_leger_controles_illisibles_garde_la_sante(self):
        commun.ecrire_json(self.etat / "etat.json", {"sante": dict(SANTE_OK, marque=1)})

        def panne():
            raise OSError("boum")
        e = self.construire(complet=False, controles=panne)
        self.assertEqual(e["sante"]["marque"], 1)

    def test_leger_sans_sante_lisible_collecte_et_garde_les_sourdines(self):
        # etat.json illisible : un rafraîchissement léger ne doit ni effacer la santé ni les sourdines.
        (self.etat / "etat.json").write_text("{ coupé", encoding="utf-8")
        commun.ecrire_json(self.etat / "sourdines.json", {"volume:/var/mnt/EXTERNE": 90.5})
        externe = {"nom": "Externe", "chemin": "/var/mnt/EXTERNE", "total_go": 3600.0,
                   "libre_go": 342.0, "pourcent_utilise": 90.5}
        e = self.construire(complet=False, collecter=lambda: dict(SANTE_OK, volumes=[externe]))
        self.assertEqual(e["sante"]["volumes"], [externe])
        self.assertEqual(json.loads((self.etat / "sourdines.json").read_text()),
                         {"volume:/var/mnt/EXTERNE": 90.5})
        pt = {p["id"]: p for p in e["points"]}["volume:/var/mnt/EXTERNE"]
        self.assertTrue(pt["en_sourdine"])

    def test_source_non_collectee_garde_sa_sourdine(self):
        commun.ecrire_json(self.etat / "sourdines.json", {"volume:/var/mnt/EXTERNE": 90.5})
        self.construire(collecter=lambda: dict(SANTE_OK, volumes=None))
        self.assertEqual(json.loads((self.etat / "sourdines.json").read_text()),
                         {"volume:/var/mnt/EXTERNE": 90.5})

    def test_redemarrage(self):
        dep = {"courant": {"version": "45.1"}, "en_attente": {"version": "45.2"}, "precedent": None}
        commun.ecrire_json(self.etat / "visites.json", {"derniere": "2026-11-09T08:00:00"})
        e = self.construire(deploiements=lambda: dep)
        self.assertEqual(e["redemarrage"], True)
        self.assertEqual(e["phrase"], "Des mises à jour t'attendent.")


class Ecriture(Base):
    def test_ecrire(self):
        with mock.patch.object(etat, "construire", return_value={"couleur": "vert"}):
            chemin = etat.ecrire()
        self.assertEqual(chemin, self.etat / "etat.json")
        self.assertEqual(json.loads(chemin.read_text()), {"couleur": "vert"})

    def test_marquer_vu(self):
        commun.ecrire_json(self.etat / "releves" / "b.json", {"date": "2026-11-09T12:00:00", "image": "1"})
        with mock.patch.object(commun, "maintenant", return_value="2026-11-09T13:00:00"):
            etat.marquer_vu()
        self.assertEqual(json.loads((self.etat / "visites.json").read_text()),
                         {"derniere": "2026-11-09T13:00:00", "releve": "2026-11-09T12:00:00"})


if __name__ == "__main__":
    unittest.main()
