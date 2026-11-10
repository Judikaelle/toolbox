import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from centre_bazzite import resume
from tests import configuration

ELEMENTS = [
    {"id": "org.libreoffice.LibreOffice", "nom": "LibreOffice", "de": "1.0.168", "vers": "1.0.171",
     "notes": "Correctif du partage d'écran sous Wayland."},
    {"id": "kernel", "nom": "Noyau", "de": "7.2.14", "vers": "7.2.15", "notes": "Pilote NVIDIA mis à jour."},
]


class Service:
    def __init__(self, actif=False):
        self.actif = actif
        self.journal = []

    def etait_actif(self):
        return self.actif

    def demarrer(self):
        self.journal.append("demarrer")
        self.actif = True

    def arreter(self):
        self.journal.append("arreter")
        self.actif = False

    def decharger(self):
        self.journal.append("decharger")


def jamais(corps):
    raise AssertionError("appeler ne doit pas être appelé")


class Prompt(unittest.TestCase):
    def test_prompt_contient_regles(self):
        p = resume.construire_prompt(ELEMENTS)
        self.assertIn("uniquement à partir des notes fournies", p)
        self.assertIn("en français", p.replace("écris en français", "en français"))
        self.assertIn("une ou deux phrases", p)
        self.assertIn("org.libreoffice.LibreOffice", p)
        self.assertIn("kernel", p)
        self.assertIn("1.0.168 → 1.0.171", p)
        self.assertIn("JSON", p)
        self.assertIn("{id: résumé}", p)

    def test_le_lecteur_vient_de_la_configuration(self):
        with configuration('[resume]\ncontexte = "Camille, qui joue sous Bazzite"\n'):
            p = resume.construire_prompt(ELEMENTS)
        self.assertTrue(p.startswith("Tu résumes des notes de version pour Camille, qui joue sous Bazzite.\nRègles : "))
        with configuration(""):
            p = resume.construire_prompt(ELEMENTS)
        self.assertTrue(p.startswith("Tu résumes des notes de version pour l'utilisateur, sous Bazzite "
                                     "(KDE Plasma, Wayland).\nRègles : "))

    def test_notes_tronquees(self):
        el = [{"id": "x", "nom": "X", "de": None, "vers": "1", "notes": "a" * 5000}]
        p = resume.construire_prompt(el)
        self.assertIn("a" * 3000, p)
        self.assertNotIn("a" * 3001, p)


class Lecture(unittest.TestCase):
    def test_lire_reponse_json_entoure_de_texte(self):
        texte = 'Voici :\n```json\n{"kernel": "Mise à jour du noyau.", "x": "Ok."}\n```\nVoilà.'
        self.assertEqual(resume.lire_reponse(texte), {"kernel": "Mise à jour du noyau.", "x": "Ok."})

    def test_lire_reponse_objet_nu(self):
        self.assertEqual(resume.lire_reponse('blabla {"a": "b"} fin'), {"a": "b"})

    def test_lire_reponse_invalide_vide(self):
        for t in ("", "pas du json", "{cassé", "[1, 2]", '"texte"'):
            self.assertEqual(resume.lire_reponse(t), {}, t)


class Resumer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(resume.commun, "CACHE", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_resume_saute_si_jeu(self):
        svc = Service()
        r = resume.resumer(ELEMENTS, jeu=lambda: "JeuDeCourse", appeler=jamais, service=svc)
        self.assertIsNone(r)
        self.assertEqual(svc.journal, [])

    def test_service_remis_dans_son_etat(self):
        svc = Service(actif=False)
        vus = []

        def appeler(corps):
            vus.append(svc.actif)
            return json.dumps({"kernel": "Noyau à jour.", "org.libreoffice.LibreOffice": "Partage corrigé."})

        r = resume.resumer(ELEMENTS, jeu=lambda: None, appeler=appeler, service=svc)
        self.assertEqual(vus, [True])
        self.assertFalse(svc.actif)
        self.assertEqual(r["kernel"], "Noyau à jour.")

    def test_service_remis_meme_si_exception(self):
        svc = Service(actif=False)

        def appeler(corps):
            raise RuntimeError("boum")

        self.assertIsNone(resume.resumer(ELEMENTS, jeu=lambda: None, appeler=appeler, service=svc))
        self.assertFalse(svc.actif)
        self.assertEqual(svc.journal, ["demarrer", "arreter"])

    def test_service_deja_actif_laisse_actif(self):
        svc = Service(actif=True)
        resume.resumer(ELEMENTS, jeu=lambda: None, appeler=lambda c: '{"kernel": "ok"}', service=svc)
        self.assertTrue(svc.actif)
        self.assertEqual(svc.journal, [])

    def test_keep_alive_zero(self):
        corps = []

        def appeler(c):
            corps.append(c)
            return "{}"

        resume.resumer(ELEMENTS, jeu=lambda: None, appeler=appeler, service=Service())
        c = corps[0]
        self.assertEqual(c["keep_alive"], 0)
        self.assertIs(c["stream"], False)
        self.assertEqual(c["format"], "json")
        self.assertEqual(c["model"], resume.MODELE_RESUME)
        self.assertIn("kernel", c["prompt"])

    def test_cache_evite_un_second_appel(self):
        rep = '{"kernel": "Noyau.", "org.libreoffice.LibreOffice": "LibreOffice."}'
        resume.resumer(ELEMENTS, jeu=lambda: None, appeler=lambda c: rep, service=Service())
        svc = Service()
        r = resume.resumer(ELEMENTS, jeu=lambda: None, appeler=jamais, service=svc)
        self.assertEqual(r, {"kernel": "Noyau.", "org.libreoffice.LibreOffice": "LibreOffice."})
        self.assertEqual(svc.journal, [])

    def test_reponse_inutilisable_donne_none(self):
        r = resume.resumer(ELEMENTS, jeu=lambda: None, appeler=lambda c: "bof", service=Service())
        self.assertIsNone(r)

    def appel_bloque(self):
        coupe = threading.Event()

        def appeler(corps):
            if not coupe.wait(5):
                raise AssertionError("l'appel n'a pas été coupé")
            raise OSError("connexion coupée")
        return coupe, appeler

    def test_jeu_lance_pendant_l_appel_coupe_et_arrete_le_service(self):
        coupe, appeler = self.appel_bloque()
        jeux = iter([None, None, None])         # avant, après le démarrage, premier tour de garde
        svc = Service(actif=False)
        r = resume.resumer(ELEMENTS, jeu=lambda: next(jeux, "Jeu Exemple"), appeler=appeler, service=svc,
                           couper=coupe.set, intervalle=0.01)
        self.assertIsNone(r)
        self.assertTrue(coupe.is_set())
        self.assertEqual(svc.journal, ["demarrer", "arreter"])
        self.assertEqual(list(Path(self.tmp.name).rglob("*.json")), [])

    def test_jeu_lance_pendant_l_appel_decharge_si_ollama_tournait_deja(self):
        coupe, appeler = self.appel_bloque()
        jeux = iter([None, None])
        svc = Service(actif=True)
        r = resume.resumer(ELEMENTS, jeu=lambda: next(jeux, "Jeu Exemple"), appeler=appeler, service=svc,
                           couper=coupe.set, intervalle=0.01)
        self.assertIsNone(r)
        self.assertEqual(svc.journal, ["decharger"])
        self.assertTrue(svc.actif)

    def test_jeu_lance_pendant_le_demarrage(self):
        jeux, appels = iter([None]), []
        svc = Service(actif=False)
        r = resume.resumer(ELEMENTS, jeu=lambda: next(jeux, "Jeu Exemple"),
                           appeler=lambda c: appels.append(c) or '{"kernel": "ok"}', service=svc)
        self.assertIsNone(r)
        self.assertEqual(appels, [])
        self.assertEqual(svc.journal, ["demarrer", "arreter"])

    def test_liste_vide(self):
        self.assertEqual(resume.resumer([], jeu=lambda: None, appeler=jamais, service=Service()), {})


class FauxOllama(BaseHTTPRequestHandler):
    lent = threading.Event()

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if FauxOllama.lent.is_set():
            time.sleep(5)
        corps = json.dumps({"response": '{"kernel": "ok"}'}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *a):
        pass


class AppelReel(unittest.TestCase):
    """L'appel HTTP réel, contre un faux serveur local (jamais le vrai Ollama)."""

    def setUp(self):
        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
        self.serveur.daemon_threads = True
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.addCleanup(self.serveur.server_close)
        self.addCleanup(self.serveur.shutdown)
        p = mock.patch.object(resume, "URL", f"http://127.0.0.1:{self.serveur.server_address[1]}")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(FauxOllama.lent.clear)

    def test_reponse(self):
        self.assertEqual(resume._appeler_ollama({"model": "m"}), '{"kernel": "ok"}')

    def test_couper_interrompt_l_appel(self):
        FauxOllama.lent.set()
        erreurs = []

        def appel():
            try:
                resume._appeler_ollama({"model": "m"})
            except Exception as exc:
                erreurs.append(exc)
        fil = threading.Thread(target=appel)
        debut = time.monotonic()
        fil.start()
        time.sleep(0.2)
        resume._couper_appel()
        fil.join(3)
        self.assertFalse(fil.is_alive())
        self.assertLess(time.monotonic() - debut, 3)
        self.assertEqual(len(erreurs), 1)


if __name__ == "__main__":
    unittest.main()
