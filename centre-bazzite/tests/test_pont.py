"""Pont QML : lecture de etat.json, rechargement, suivi d'une mise à jour, commandes de la CLI.
À lancer avec QT_QPA_PLATFORM=offscreen (le pont est un QObject, aucun QML n'est chargé)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fenetre"))

from datetime import datetime, timedelta  # noqa: E402

from PySide6.QtCore import QElapsedTimer, QEventLoop, QProcess, QThread  # noqa: E402

import pont  # noqa: E402
from centre_bazzite import menage  # noqa: E402

from tests.appli_qt import APP, arreter_pont  # noqa: E402

ETAT = {
    "couleur": "orange", "phrase": "Tout est à jour.", "phrase2": "Une chose mérite un coup d'œil.",
    "en_cours": None, "extinction": None,
    "points": [
        {"id": "ollama:inactif", "gravite": "attention", "titre": "Ollama tourne",
         "action": {"libelle": "Arrêter Ollama", "commande": ["systemctl", "--user", "stop", "ollama.service"]}},
        {"id": "volume:/var/mnt/EXTERNE", "gravite": "attention", "titre": "Externe", "action": None},
    ],
}
RAFRAICHIR = ["centre-bazzite", "rafraichir", "--leger"]


def attendre(ms, condition=lambda: False):
    """Fait tourner la boucle d'événements jusqu'à `condition()` ou `ms` millisecondes."""
    chrono = QElapsedTimer()
    chrono.start()
    while chrono.elapsed() < ms and not condition():
        APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        QThread.msleep(5)


def ecrire_atomique(chemin, donnees):
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, chemin)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = Path(tmp.name)
        self.chemin = self.dossier / "etat.json"
        self.appels = []
        faux = mock.patch.object(QProcess, "startDetached",
                                 lambda prog, args: self.appels.append([prog] + list(args)) or (True, 1))
        faux.start()
        self.addCleanup(faux.stop)

    def pont(self, etat=ETAT, **options):
        if etat is not None:
            ecrire_atomique(self.chemin, etat)
        p = pont.Pont(self.chemin, **options)
        self.addCleanup(arreter_pont, p)
        return p


class Lecture(Base):
    def test_pont_lit_etat(self):
        p = self.pont()
        self.assertEqual(p.etat["phrase"], "Tout est à jour.")
        self.assertEqual(p.property("etat")["phrase2"], "Une chose mérite un coup d'œil.")

    def test_etat_absent_ou_illisible_donne_un_etat_vide(self):
        self.assertEqual(self.pont(etat=None).etat, {})
        self.chemin.write_text("{ pas du json", encoding="utf-8")
        self.assertEqual(pont.Pont(self.chemin).etat, {})

    def test_recharge_apres_remplacement_atomique(self):
        p = self.pont()
        signaux = []
        p.etatChange.connect(lambda: signaux.append(p.etat.get("phrase")))
        for phrase in ("Des mises à jour t'attendent.", "Mise à jour en cours…"):
            ecrire_atomique(self.chemin, dict(ETAT, phrase=phrase))
            attendre(3000, lambda: p.etat["phrase"] == phrase)
            self.assertEqual(p.etat["phrase"], phrase)
        self.assertEqual(signaux, ["Des mises à jour t'attendent.", "Mise à jour en cours…"])

    def test_fichier_illisible_garde_l_etat_precedent(self):
        p = self.pont()
        self.chemin.write_text("{ coupé", encoding="utf-8")
        p.recharger()
        self.assertEqual(p.etat["phrase"], "Tout est à jour.")


class Commandes(Base):
    def test_commandes(self):
        p = self.pont()
        p.toutMettreAJour()
        p.mettreAJourEtEteindre()
        p.annulerExtinction()
        p.redemarrer()
        p.sourdine("volume:/var/mnt/EXTERNE")
        p.sansSourdine("volume:/var/mnt/EXTERNE")
        p.rafraichir()
        p.marquerVu()
        p.resumer()
        self.assertEqual(self.appels, [
            ["centre-bazzite", "maj"],
            ["centre-bazzite", "maj", "--eteindre"],
            ["centre-bazzite", "annuler-extinction"],
            ["centre-bazzite", "redemarrer"],
            ["centre-bazzite", "sourdine", "volume:/var/mnt/EXTERNE"],
            ["centre-bazzite", "sans-sourdine", "volume:/var/mnt/EXTERNE"],
            RAFRAICHIR,
            ["centre-bazzite", "vu"],
            ["centre-bazzite", "resumer"],
        ])

    def test_verifier_lance_un_rafraichissement_complet(self):
        p = self.pont()
        p.verifier()
        self.assertEqual(self.appels, [["centre-bazzite", "rafraichir"]])
        self.assertTrue(p._minuteur.isActive())     # le suivi démarre

    def test_lancer_meme_si_un_jeu_tourne(self):
        p = self.pont()
        p.toutMettreAJour(True)
        p.mettreAJourEtEteindre(True)
        p.toutMettreAJour(False)
        self.assertEqual(self.appels, [
            ["centre-bazzite", "maj", "--meme-si-jeu"],
            ["centre-bazzite", "maj", "--eteindre", "--meme-si-jeu"],
            ["centre-bazzite", "maj"],
        ])

    def test_creer_le_pont_ne_lance_rien(self):
        self.pont()
        self.assertEqual(self.appels, [])

    def test_agir_lance_l_action_du_point(self):
        p = self.pont()
        p.agir("ollama:inactif")
        p.agir("volume:/var/mnt/EXTERNE")   # point sans action
        p.agir("inconnu")
        self.assertEqual(self.appels, [["systemctl", "--user", "stop", "ollama.service"]])


class Sessions(Base):
    def ecrire_session(self, nom, contenu="auto"):
        dossier = self.dossier / "sessions"
        dossier.mkdir(exist_ok=True)
        if contenu == "auto":
            contenu = json.dumps({"debut": nom, "fin": nom, "succes": True, "etapes": {}})
        (dossier / f"{nom}.json").write_text(contenu, encoding="utf-8")

    def test_sessions_triees(self):
        for jour in range(1, 36):
            self.ecrire_session(f"2026-10-{jour:02d}T04:45:00")
        self.ecrire_session("2026-10-99T00:00:00", "{ corrompu")
        self.ecrire_session("2026-10-98T00:00:00", "[1, 2]")
        sessions = self.pont().sessions
        self.assertEqual(len(sessions), 30)
        debuts = [s["debut"] for s in sessions]
        self.assertEqual(debuts, sorted(debuts, reverse=True))
        self.assertEqual(debuts[0], "2026-10-35T04:45:00")

    def test_sans_dossier_de_sessions(self):
        self.assertEqual(self.pont().sessions, [])

    def test_arreter_ollama_lance_systemctl(self):
        self.pont().arreterOllama()
        self.assertEqual(self.appels, [["systemctl", "--user", "stop", "ollama.service"]])


class Suivi(Base):
    def test_suivi_pendant_une_mise_a_jour(self):
        self.pont(dict(ETAT, en_cours={"global": 40, "etapes": {}}), intervalle_ms=20)
        attendre(2000, lambda: RAFRAICHIR in self.appels)
        self.assertIn(RAFRAICHIR, self.appels)

    def test_suivi_pendant_le_compte_a_rebours(self):
        self.pont(dict(ETAT, extinction={"a": "2026-11-09T23:00:00"}), intervalle_ms=20)
        attendre(2000, lambda: RAFRAICHIR in self.appels)
        self.assertIn(RAFRAICHIR, self.appels)

    def test_pas_de_suivi_sans_mise_a_jour(self):
        self.pont(intervalle_ms=20)
        attendre(200)
        self.assertNotIn(RAFRAICHIR, self.appels)

    def test_suivi_juste_apres_un_lancement(self):
        p = self.pont(intervalle_ms=20)
        p.toutMettreAJour()
        attendre(2000, lambda: RAFRAICHIR in self.appels)
        self.assertIn(RAFRAICHIR, self.appels)

    def test_rafraichit_apres_arreter_ollama(self):
        p = self.pont(intervalle_ms=20)
        p.arreterOllama()
        attendre(2000, lambda: RAFRAICHIR in self.appels)
        self.assertEqual(self.appels[0], ["systemctl", "--user", "stop", "ollama.service"])
        self.assertIn(RAFRAICHIR, self.appels)

    def test_rafraichit_apres_l_action_d_un_point(self):
        p = self.pont(intervalle_ms=20)
        p.agir("ollama:inactif")
        attendre(2000, lambda: RAFRAICHIR in self.appels)
        self.assertIn(RAFRAICHIR, self.appels)

    def test_suivi_s_arrete_a_la_fin_de_la_mise_a_jour(self):
        p = self.pont(dict(ETAT, en_cours={"global": 40, "etapes": {}}), intervalle_ms=20)
        attendre(2000, lambda: RAFRAICHIR in self.appels)
        ecrire_atomique(self.chemin, ETAT)
        attendre(3000, lambda: p.etat["en_cours"] is None)
        attendre(100)
        self.appels.clear()
        attendre(200)
        self.assertNotIn(RAFRAICHIR, self.appels)


MAINTENANT = datetime(2026, 11, 9, 16, 0, 0)


def session_finie(debut, fin, succes=True, bilan="Tout est à jour."):
    return {"debut": debut, "fin": fin, "succes": succes, "bilan": bilan, "etapes": {}}


class Filet(unittest.TestCase):
    def test_aucune_vraie_commande_sans_faux(self):
        """UI-m1 : hors du faux d'un test, QProcess.startDetached est le filet des tests : un pont oublié (son suivi de
        5 s) ne lance jamais une vraie commande."""
        from tests import appli_qt
        self.assertIs(QProcess.startDetached, appli_qt.sans_commande)
        with mock.patch("sys.stderr"):
            self.assertEqual(QProcess.startDetached("centre-bazzite", ["rafraichir", "--leger"]), (False, 0))


class TachesAffichees(unittest.TestCase):
    def test_taches_session_en_cours(self):
        en_cours = {"debut": "2026-11-09T14:52:00", "global": 40,
                    "etapes": {"uupd": {"statut": "fini"},
                               "maj-apps": {"statut": "en_cours", "detail": "Ollama 0.40"}}}
        t = pont.taches_affichees({"en_cours": en_cours}, [], [], None, MAINTENANT)[0]
        self.assertEqual(t["id"], "maj:2026-11-09T14:52:00")
        self.assertEqual(t["statut"], "en_cours")
        self.assertEqual(t["progression"], 40)
        self.assertEqual(t["titre"], "Tout mettre à jour")
        self.assertEqual(t["detail"], "Mise à jour des outils : Ollama 0.40")
        self.assertEqual([e["titre"] for e in t["etapes"]], ["Mise à jour du système", "Mise à jour des outils"])

    def test_etapes_dans_l_ordre_du_moteur(self):
        etapes = {n: {"statut": "attente"} for n in ("extinction", "etat", "resume", "notes", "maj-apps", "uupd")}
        t = pont.taches_affichees({"en_cours": {"debut": "d", "global": 0, "etapes": etapes}}, [], [], None, MAINTENANT)[0]
        self.assertEqual([e["titre"] for e in t["etapes"]],
                         ["Mise à jour du système", "Mise à jour des outils", "Notes de version",
                          "Résumé des nouveautés", "Bilan de santé", "Extinction"])

    def test_taches_uupd_seul(self):
        t = pont.taches_affichees({"en_cours": {"unite": "uupd.service"}}, [], [], None, MAINTENANT)[0]
        self.assertEqual(t["id"], "maj:uupd")
        self.assertEqual(t["progression"], -1)
        self.assertEqual(t["titre"], "Mise à jour du système")
        self.assertEqual(t["statut"], "en_cours")

    def test_session_finie_recente_puis_vue(self):
        fin = (MAINTENANT - timedelta(hours=1)).isoformat()
        s = session_finie("2026-11-09T14:50:00", fin, succes=False, bilan="Une étape a échoué.")
        t = pont.taches_affichees({}, [s], [], None, MAINTENANT)
        self.assertEqual([(x["statut"], x["detail"]) for x in t], [("echec", "Une étape a échoué.")])
        self.assertEqual(pont.taches_affichees({}, [s], [], s["debut"], MAINTENANT), [])
        vieille = session_finie("2026-11-08T14:00:00", (MAINTENANT - timedelta(hours=25)).isoformat())
        self.assertEqual(pont.taches_affichees({}, [vieille], [], None, MAINTENANT), [])

    def test_session_reussie_est_terminee_et_seule_la_derniere_compte(self):
        recente = session_finie("2026-11-09T14:50:00", "2026-11-09T15:10:00")
        avant = session_finie("2026-11-09T04:45:00", "2026-11-09T05:00:00")
        t = pont.taches_affichees({}, [recente, avant], [], None, MAINTENANT)
        self.assertEqual([(x["statut"], x["progression"]) for x in t], [("fini", 100)])

    def test_session_vue_masque_les_anterieures_mais_pas_une_plus_recente(self):
        vue = session_finie("2026-11-09T04:45:00", "2026-11-09T05:00:00")
        nouvelle = session_finie("2026-11-09T14:50:00", "2026-11-09T15:10:00")
        t = pont.taches_affichees({}, [nouvelle], [], vue["debut"], MAINTENANT)
        self.assertEqual(len(t), 1)

    def test_session_vivante_n_est_pas_dupliquee(self):
        en_cours = {"debut": "2026-11-09T14:52:00", "global": 10, "etapes": {}}
        archive = session_finie("2026-11-09T14:52:00", "2026-11-09T15:00:00")
        t = pont.taches_affichees({"en_cours": en_cours}, [archive], [], None, MAINTENANT)
        self.assertEqual([x["statut"] for x in t], ["en_cours"])

    def test_taches_triees_en_cours_d_abord(self):
        def tache(id_, statut, debut):
            return {"id": id_, "statut": statut, "debut": debut, "titre": id_}
        fichiers = [tache("a", "fini", "2026-11-09T15:00:00"), tache("b", "en_cours", "2026-11-09T09:00:00"),
                    tache("c", "echec", "2026-11-09T12:00:00"), tache("d", "en_cours", "2026-11-09T10:00:00")]
        t = pont.taches_affichees({}, [], fichiers, None, MAINTENANT)
        self.assertEqual([x["id"] for x in t], ["d", "b", "a", "c"])

    def test_vingt_taches_au_plus(self):
        fichiers = [{"id": str(i), "statut": "fini", "debut": f"2026-11-09T10:{i:02d}:00"} for i in range(30)]
        t = pont.taches_affichees({}, [], fichiers, None, MAINTENANT)
        self.assertEqual(len(t), 20)
        self.assertEqual(t[0]["id"], "29")


class Taches(Base):
    def ecrire_tache(self, nom, **champs):
        dossier = self.dossier / "taches"
        dossier.mkdir(exist_ok=True)
        t = {"id": nom, "type": "menage", "titre": nom, "statut": "en_cours", "progression": -1, "detail": "",
             "debut": "2026-11-09T15:00:00", "fin": None, "unite": None, "etapes": [], "journal": []}
        t.update(champs)
        ecrire_atomique(dossier / f"{nom}.json", t)

    def test_effacer_terminees_lance_la_cli(self):
        self.pont().effacerTerminees()
        self.assertEqual(self.appels, [["centre-bazzite", "taches", "--effacer"]])

    def test_taches_rechargees_quand_le_dossier_change(self):
        p = self.pont()
        self.assertEqual(p.taches, [])
        signaux = []
        p.tachesChange.connect(lambda: signaux.append(1))
        self.ecrire_tache("menage_caches")
        attendre(2000, lambda: p.taches)
        self.assertEqual([t["id"] for t in p.taches], ["menage_caches"])
        self.assertTrue(signaux)
        self.ecrire_tache("menage_caches", statut="fini", fin="2026-11-09T15:05:00")     # le fichier est remplacé
        attendre(2000, lambda: p.taches[0]["statut"] == "fini")
        self.assertEqual(p.taches[0]["statut"], "fini")

    def test_taches_lues_au_demarrage_avec_la_session_et_la_vue(self):
        self.ecrire_tache("menage_caches", debut="2026-11-09T14:00:00")
        p = self.pont(dict(ETAT, en_cours={"debut": "2026-11-09T14:52:00", "global": 5, "etapes": {}}))
        self.assertEqual([t["id"] for t in p.taches], ["maj:2026-11-09T14:52:00", "menage_caches"])

    def test_vues_json_n_est_pas_une_tache(self):
        self.ecrire_tache("menage_caches")
        ecrire_atomique(self.dossier / "taches" / "vues.json", {"session": "2026-11-09T04:45:00"})
        self.assertEqual([t["id"] for t in self.pont().taches], ["menage_caches"])

    def test_pont_lit_stockage(self):
        stock = {"genere": "2026-11-09T16:00:00", "disques": [{"id": "nvme0n1", "volumes": []}]}
        ecrire_atomique(self.dossier / "stockage.json", stock)
        p = self.pont()
        self.assertEqual(p.stockage["disques"][0]["id"], "nvme0n1")
        signaux = []
        p.stockageChange.connect(lambda: signaux.append(1))
        ecrire_atomique(self.dossier / "stockage.json", dict(stock, disques=[]))
        attendre(3000, lambda: p.stockage["disques"] == [])
        self.assertEqual(p.stockage["disques"], [])
        self.assertTrue(signaux)

    def test_stockage_absent_ou_illisible_donne_un_dict_vide(self):
        p = self.pont()
        self.assertEqual(p.stockage, {})
        (self.dossier / "stockage.json").write_text("{ coupé", encoding="utf-8")
        p.recharger()
        self.assertEqual(p.stockage, {})

    def test_rafraichir_stockage_lance_la_cli(self):
        self.pont().rafraichirStockage()
        self.assertEqual(self.appels, [["centre-bazzite", "stockage"]])

    def test_rafraichir_jeux_lance_trois_commandes(self):
        """Ouverture de la page Jeux : le relevé des jeux, celui du stockage (ménage des jeux), puis l'état (mode jeu)."""
        self.pont().rafraichirJeux()
        self.assertEqual(self.appels, [["centre-bazzite", "jeux"], ["centre-bazzite", "stockage"], RAFRAICHIR])

    def test_rafraichir_jeux_pendant_une_partie_seulement_leger(self):
        """RF-m3 : pendant une partie (un jeu dans l'état, ou le mode jeu actif), l'ouverture de la page Jeux ne lance
        pas les relevés lourds (jeux, stockage) ; seulement l'état."""
        for etat in (dict(ETAT, jeu="Jeu de course"), dict(ETAT, jeu=None, modejeu={"etat": "actif"})):
            with self.subTest(etat=etat):
                self.appels.clear()
                self.pont(etat).rafraichirJeux()
                self.assertEqual(self.appels, [RAFRAICHIR])
        for modejeu in ({"etat": "interrompu"}, {"etat": "pret"}, None):
            with self.subTest(modejeu=modejeu):
                self.appels.clear()
                self.pont(dict(ETAT, jeu=None, modejeu=modejeu)).rafraichirJeux()
                self.assertEqual(self.appels, [["centre-bazzite", "jeux"], ["centre-bazzite", "stockage"], RAFRAICHIR])

    def test_rafraichir_demarrage_lance_la_cli(self):
        """Ouverture de la page Démarrage : un seul relevé, `centre-bazzite demarrage` (il republie l'état lui-même)."""
        self.pont().rafraichirDemarrage()
        self.assertEqual(self.appels, [["centre-bazzite", "demarrage"]])

    def test_regler_et_remettre_demarrage_commandes(self):
        p = self.pont()
        p.reglerDemarrage("autostart:messagerie.desktop", False)
        p.reglerDemarrage("unite:synchro.timer", True)
        p.remettreDemarrage("autostart:indexation.desktop")
        self.assertEqual(self.appels, [["centre-bazzite", "demarrage", "regler", "autostart:messagerie.desktop", "non"],
                                       ["centre-bazzite", "demarrage", "regler", "unite:synchro.timer", "oui"],
                                       ["centre-bazzite", "demarrage", "remettre", "autostart:indexation.desktop"]])

    def test_demarrage_occupe_jusqu_a_la_reponse_de_la_cli(self):
        """I-4 : une bascule ou une remise lancée par la fenêtre rend sa ligne « occupée » jusqu'à la réponse de sa
        commande (demarrage.json réécrit, `genere` changé, avec le retour de cette entrée). Un second clic sur la même
        ligne ne relance rien ; un relevé qui finit entre-temps ne la libère pas."""
        ecrire_atomique(self.dossier / "demarrage.json", {"genere": "2026-11-10T21:00:00", "retour": None})
        p = self.pont()
        changements = []
        p.demarrageOccupeChange.connect(lambda: changements.append(list(p.demarrageOccupes)))
        self.assertEqual(p.demarrageOccupes, [])
        p.reglerDemarrage("unite:synchro.timer", False)
        p.reglerDemarrage("unite:synchro.timer", False)                 # double clic
        p.remettreDemarrage("unite:synchro.timer")                      # même ligne, déjà occupée
        self.assertEqual(self.appels, [["centre-bazzite", "demarrage", "regler", "unite:synchro.timer", "non"]])
        p.remettreDemarrage("autostart:messagerie.desktop")             # une autre ligne
        self.assertEqual(p.property("demarrageOccupes"), ["unite:synchro.timer", "autostart:messagerie.desktop"])
        ecrire_atomique(self.dossier / "demarrage.json", {"genere": "2026-11-10T21:00:01", "retour": None})
        attendre(3000, lambda: p.demarrage.get("genere") == "2026-11-10T21:00:01")
        self.assertEqual(p.demarrageOccupes, ["unite:synchro.timer", "autostart:messagerie.desktop"])
        retour = {"id": "unite:synchro.timer", "code": 0, "phrase": "Minuteur « synchro.timer » arrêté.",
                  "date": "2026-11-10T21:00:02"}
        ecrire_atomique(self.dossier / "demarrage.json", {"genere": "2026-11-10T21:00:02", "retour": retour})
        attendre(3000, lambda: "unite:synchro.timer" not in p.demarrageOccupes)
        self.assertEqual(p.demarrageOccupes, ["autostart:messagerie.desktop"])
        p.reglerDemarrage("unite:synchro.timer", True)                  # libre : elle repart
        self.assertEqual(self.appels[-1], ["centre-bazzite", "demarrage", "regler", "unite:synchro.timer", "oui"])
        self.assertEqual(p.demarrageOccupes, ["autostart:messagerie.desktop", "unite:synchro.timer"])
        self.assertEqual(changements[:2], [["unite:synchro.timer"],
                                           ["unite:synchro.timer", "autostart:messagerie.desktop"]])

    def test_demarrage_occupe_rendu_apres_le_delai(self):
        """Sans réponse (CLI absente, demarrage.json impossible à écrire), la ligne revient au bout de 30 s."""
        self.assertEqual(pont.ATTENTE_DEMARRAGE_MS, 30000)
        p = self.pont()
        p._delai_demarrage.setInterval(50)
        p.reglerDemarrage("unite:synchro.timer", False)
        self.assertEqual(p.demarrageOccupes, ["unite:synchro.timer"])
        attendre(2000, lambda: not p.demarrageOccupes)
        self.assertEqual(p.demarrageOccupes, [])

    def test_demarrage_pas_occupe_si_rien_n_est_parti(self):
        """La CLI qui ne part pas (startDetached en échec) n'occupe pas la ligne : on peut recliquer."""
        with mock.patch.object(QProcess, "startDetached",
                               lambda prog, args: self.appels.append([prog] + list(args)) or (False, 0)):
            p = self.pont()
            p.reglerDemarrage("unite:synchro.timer", False)
            self.assertEqual(p.demarrageOccupes, [])
            p.reglerDemarrage("unite:synchro.timer", False)
        self.assertEqual(len(self.appels), 2)

    def test_demarrage_lu_depuis_le_dossier(self):
        p = self.pont()
        self.assertEqual(p.demarrage, {})                               # pas encore de relevé
        releve = {"genere": "2026-11-10T09:00:00+00:00", "duree": {"total": 40.4, "phases": []}, "erreurs": []}
        signaux = []
        p.demarrageChange.connect(lambda: signaux.append(1))
        ecrire_atomique(self.dossier / "demarrage.json", releve)
        attendre(3000, lambda: p.demarrage)
        self.assertEqual(p.property("demarrage")["duree"]["total"], 40.4)
        self.assertTrue(signaux)
        (self.dossier / "demarrage.json").write_text("{ coupé", encoding="utf-8")
        p.recharger()
        self.assertEqual(p.demarrage, releve)                           # illisible : le relevé précédent reste
        ecrire_atomique(self.dossier / "demarrage.json", dict(releve, erreurs=["Durée illisible (systemd-analyze : x)"]))
        attendre(3000, lambda: p.demarrage.get("erreurs"))
        self.assertEqual(p.demarrage["erreurs"], ["Durée illisible (systemd-analyze : x)"])

    def test_jeux_lu_depuis_le_dossier(self):
        p = self.pont()
        self.assertEqual(p.jeux, {})                                    # pas encore de relevé
        jeux = {"genere": "2026-11-10T09:00:00", "bibliotheques": [{"id": "lutris", "nom": "Lutris"}], "erreurs": []}
        signaux = []
        p.jeuxChange.connect(lambda: signaux.append(1))
        ecrire_atomique(self.dossier / "jeux.json", jeux)
        attendre(3000, lambda: p.jeux)
        self.assertEqual(p.property("jeux")["bibliotheques"][0]["nom"], "Lutris")
        self.assertEqual(signaux, [1])
        (self.dossier / "jeux.json").write_text("{ coupé", encoding="utf-8")
        p.recharger()
        self.assertEqual(p.jeux, jeux)                                  # illisible : le relevé précédent reste
        ecrire_atomique(self.dossier / "jeux.json", dict(jeux, erreurs=["Lutris : illisible (OSError)"]))
        attendre(3000, lambda: p.jeux.get("erreurs"))
        self.assertEqual(p.jeux["erreurs"], ["Lutris : illisible (OSError)"])

    JEUX = {"gels": {"dossier": "/home/x/g", "nombre": 2, "liste": [
        {"fichier": "/home/x/g/20260921-203718-GEL-Jeu.txt", "date": "2026-09-21T20:37:18"},
        {"fichier": "/etc/passwd", "date": "2026-09-20T10:00:00"}]}}       # hors du dossier : jamais ouvert

    def test_ouvrir_gel(self):
        ecrire_atomique(self.dossier / "jeux.json", self.JEUX)
        self.pont().ouvrirGel("20260921-203718-GEL-Jeu.txt")
        self.assertEqual(self.appels, [["xdg-open", "/home/x/g/20260921-203718-GEL-Jeu.txt"]])

    def test_ouvrir_gel_garde(self):
        """Seulement un nom de la liste des gels, sans « / », dans le dossier des gels."""
        ecrire_atomique(self.dossier / "jeux.json", self.JEUX)
        p = self.pont()
        for nom in ("inconnu.txt", "../x", "", "/home/x/g/20260921-203718-GEL-Jeu.txt", "g/20260921-203718-GEL-Jeu.txt",
                    "passwd", ".", ".."):
            p.ouvrirGel(nom)
        self.assertEqual(self.appels, [])

    def test_ouvrir_dossier_gels(self):
        ecrire_atomique(self.dossier / "jeux.json", self.JEUX)
        self.pont().ouvrirDossierGels()
        self.assertEqual(self.appels, [["xdg-open", "/home/x/g"]])

    def test_sans_dossier_de_gels_rien(self):
        p = self.pont()
        p.ouvrirDossierGels()
        p.ouvrirGel("20260921-203718-GEL-Jeu.txt")
        ecrire_atomique(self.dossier / "jeux.json", {"gels": {"dossier": "", "liste": []}})
        p.recharger()
        p.ouvrirDossierGels()
        self.assertEqual(self.appels, [])

    def test_regler_mode_jeu(self):
        p = self.pont()
        p.reglerModeJeu("ollama", False)
        p.reglerModeJeu("actif", True)
        self.assertEqual(self.appels, [["centre-bazzite", "modejeu", "regler", "ollama", "non"],
                                       ["centre-bazzite", "modejeu", "regler", "actif", "oui"]])
        self.assertTrue(p._minuteur.isActive())             # l'état suit quelques secondes

    def test_regler_mode_jeu_garde(self):
        """Seulement une clé de modejeu.CLES ; sous état forcé, rien (test d'état forcé)."""
        p = self.pont()
        for cle in ("turbo", "", "actif --x", "ACTIF"):
            p.reglerModeJeu(cle, True)
        self.assertEqual(self.appels, [])
        self.assertFalse(p._minuteur.isActive())

    def test_restaurer_mode_jeu(self):
        """P5 : passe par `modejeu restaurer`, qui vérifie toujours que le service n'est pas là."""
        p = self.pont()
        p.restaurerModeJeu()
        self.assertEqual(self.appels, [["centre-bazzite", "modejeu", "restaurer"]])

    RESTAURER = ["centre-bazzite", "modejeu", "restaurer"]

    def tache_restaurer(self, **champs):
        """Ce que la CLI écrit (UI-m2) : la tâche « modejeu:restaurer » du panneau Activité."""
        dossier = self.dossier / "taches"
        dossier.mkdir(exist_ok=True)
        t = {"id": "modejeu:restaurer", "type": "modejeu", "titre": "Remettre le bureau comme avant",
             "statut": "en_cours", "progression": -1, "detail": "", "debut": "2026-11-10T21:30:00", "fin": None,
             "unite": None, "pid": 4242, "boot": "b", "etapes": [], "journal": []}
        t.update(champs)
        ecrire_atomique(dossier / "modejeu_restaurer.json", t)

    def test_restaurer_un_seul_a_la_fois_puis_la_phrase_de_la_cli(self):
        """UI-m2 : pendant la remise, le pont refuse un second lancement (double clic) ; à la fin de la tâche que la CLI
        écrit, il dit sa phrase, et un nouveau clic relance."""
        (self.dossier / "taches").mkdir()
        p = self.pont()
        changements = []
        p.restaurationChange.connect(lambda: changements.append((p.restaurationEnCours, p.retourRestauration)))
        self.assertEqual((p.restaurationEnCours, p.retourRestauration), (False, ""))
        p.restaurerModeJeu()
        p.restaurerModeJeu()                                   # double clic
        self.assertEqual(self.appels, [self.RESTAURER])
        self.assertTrue(p.restaurationEnCours)
        self.tache_restaurer()                                 # la CLI commence
        attendre(2000, lambda: p.taches)
        self.assertTrue(p.restaurationEnCours)
        phrase = "Un jeu tourne encore : restauration à la fin de la partie."
        self.tache_restaurer(statut="fini", detail=phrase, fin="2026-11-10T21:30:10")
        attendre(3000, lambda: not p.restaurationEnCours)
        self.assertEqual((p.restaurationEnCours, p.retourRestauration), (False, phrase))
        self.assertEqual(changements, [(True, ""), (False, phrase)])
        p.restaurerModeJeu()
        self.assertEqual(self.appels, [self.RESTAURER, self.RESTAURER])
        self.assertEqual((p.restaurationEnCours, p.retourRestauration), (True, ""))

    def test_retour_de_restauration_efface_quand_une_partie_commence(self):
        """La phrase de la dernière remise ne reste pas affichée pendant la partie suivante."""
        phrase = "Mode jeu : bureau remis comme avant."
        p = self.pont()
        p.restaurerModeJeu()
        self.tache_restaurer(statut="fini", detail=phrase, fin="2026-11-10T21:30:10")
        attendre(3000, lambda: not p.restaurationEnCours)
        self.assertEqual(p.retourRestauration, phrase)
        ecrire_atomique(self.chemin, dict(ETAT, modejeu={"etat": "pret", "phrase": "Mode jeu prêt."}))
        p.recharger()
        self.assertEqual(p.retourRestauration, phrase)
        ecrire_atomique(self.chemin, dict(ETAT, modejeu={"etat": "actif", "phrase": "Mode jeu actif."}))
        p.recharger()
        self.assertEqual(p.retourRestauration, "")

    def test_restaurer_ne_confond_pas_une_ancienne_tache(self):
        """Une remise finie d'avant le clic (même identifiant) ne met pas fin à la nouvelle."""
        phrase = "Mode jeu : bureau remis comme avant."
        self.tache_restaurer(statut="fini", detail="Aucune partie à restaurer.", fin="2026-11-10T20:00:10",
                             debut="2026-11-10T20:00:00", pid=111)
        p = self.pont()
        p.restaurerModeJeu()
        p.recharger()
        self.assertTrue(p.restaurationEnCours)
        self.tache_restaurer(statut="fini", detail=phrase, pid=222, fin="2026-11-10T21:30:10")
        attendre(3000, lambda: not p.restaurationEnCours)
        self.assertEqual(p.retourRestauration, phrase)

    def test_restaurer_sans_nouvelles_rend_le_bouton(self):
        """Sans tâche finie (CLI absente, plantée avant d'écrire), le bouton revient après un délai, et le dit."""
        p = self.pont()
        p._delai_restauration.setInterval(50)
        p.restaurerModeJeu()
        attendre(2000, lambda: not p.restaurationEnCours)
        self.assertFalse(p.restaurationEnCours)
        self.assertEqual(p.retourRestauration, pont.SANS_NOUVELLES)

    def pont_avec_analyse(self, commande="/home/x/.local/bin/linstat", **options):
        stock = {"disques": [{"id": "nvme0n1", "volumes": [{"nom": "Données", "chemin": "/var/mnt/DONNEES"}]}],
                 "linstat": {"moteur": True, "commande": commande}, "analyses": {}}
        ecrire_atomique(self.dossier / "stockage.json", stock)
        return self.pont(**options)

    def test_analyser_lance_la_cli(self):
        self.pont_avec_analyse().analyser("/var/mnt/DONNEES")
        self.assertEqual(self.appels, [["centre-bazzite", "analyser", "/var/mnt/DONNEES"]])

    def test_carte_detaillee_lance_linstat(self):
        self.pont_avec_analyse().carteDetaillee("/var/mnt/DONNEES")
        self.assertEqual(self.appels, [["/home/x/.local/bin/linstat", "/var/mnt/DONNEES"]])

    def test_chemin_inconnu_ne_lance_rien(self):
        p = self.pont_avec_analyse()
        p.analyser("/etc")
        p.carteDetaillee("/etc")
        p.analyser("")
        self.assertEqual(self.appels, [])

    def test_sans_commande_linstat_rien(self):
        p = self.pont_avec_analyse(commande=None)
        p.carteDetaillee("/var/mnt/DONNEES")
        self.assertEqual(self.appels, [])
        p.analyser("/var/mnt/DONNEES")          # l'analyse passe par la CLI, pas par la commande
        self.assertEqual(self.appels, [["centre-bazzite", "analyser", "/var/mnt/DONNEES"]])

    def test_arreter_analyse_lance_la_cli(self):
        self.pont_avec_analyse().arreterAnalyse()
        self.assertEqual(self.appels, [["centre-bazzite", "analyser", "--arreter"]])

    def test_pont_sur_etat_force_ne_lance_aucune_commande(self):
        """Sous --etat (captures), rien ne part vers la CLI : ni relevé, ni vérification, ni action d'un point."""
        ecrire_atomique(self.chemin, ETAT)
        p = pont.Pont(self.chemin, etat_force=True)
        self.addCleanup(arreter_pont, p)
        p.rafraichirStockage()
        p.rafraichirJeux()          # P10 : chaque action de la page Jeux passe aussi par _demarrer
        p.verifier()
        p.rafraichir()
        p.toutMettreAJour()
        p.arreterOllama()
        p.agir("ollama:inactif")
        ecrire_atomique(self.dossier / "stockage.json",
                        {"disques": [{"id": "d", "volumes": [{"chemin": "/var/mnt/DONNEES"}]}],
                         "linstat": {"moteur": True, "commande": "/home/x/.local/bin/linstat"},
                         "recommandations": [{"id": "caches", "mode": "supprimer"}]})
        p.recharger()
        # Sans cela, appels == [] serait vrai aussi si stockage.json n'était pas chargé.
        self.assertEqual(p.stockage["disques"][0]["volumes"][0]["chemin"], "/var/mnt/DONNEES")
        self.assertEqual(p.stockage["linstat"]["commande"], "/home/x/.local/bin/linstat")
        self.assertEqual(p.stockage["recommandations"][0]["id"], "caches")
        p.analyser("/var/mnt/DONNEES")
        p.carteDetaillee("/var/mnt/DONNEES")
        p.menage("caches", [{"cible": "/x", "libelle": "x", "octets": 1}])
        p.arreterAnalyse()
        ecrire_atomique(self.dossier / "jeux.json", self.JEUX)
        p.recharger()
        self.assertEqual(p.jeux["gels"]["dossier"], "/home/x/g")         # chargé : le gel serait ouvert sans la garde
        p.ouvrirGel("20260921-203718-GEL-Jeu.txt")
        p.ouvrirDossierGels()
        p.reglerModeJeu("ollama", False)
        p.restaurerModeJeu()
        ecrire_atomique(self.dossier / "demarrage.json", {"lancement": {"entrees": [{"id": "unite:synchro.timer"}]}})
        p.recharger()
        self.assertEqual(p.demarrage["lancement"]["entrees"][0]["id"], "unite:synchro.timer")   # chargé, puis rien ne part
        p.rafraichirDemarrage()
        p.reglerDemarrage("unite:synchro.timer", False)
        p.remettreDemarrage("unite:synchro.timer")
        self.assertEqual(self.appels, [])
        self.assertFalse(p.restaurationEnCours)              # rien n'est parti : rien n'est attendu
        self.assertEqual(p.demarrageOccupes, [])

    CACHES = [{"cible": "/a", "libelle": "a", "octets": 10, "taille": "0 Mo"},
              {"cible": "/b", "libelle": "b", "octets": 20, "taille": "0 Mo"}]

    def pont_avec_menage(self):
        stock = {"disques": [], "recommandations": [
            {"id": "caches", "mode": "supprimer", "elements": self.CACHES},
            {"id": "journal", "mode": "copier", "elements": [{"cible": "journal"}]}]}
        ecrire_atomique(self.dossier / "stockage.json", stock)
        return self.pont()

    def test_menage_slot_garde(self):
        p = self.pont_avec_menage()
        p.menage("caches", self.CACHES)
        attendu = ["centre-bazzite", "menage", "caches", "--empreinte", menage.empreinte(self.CACHES)]
        self.assertEqual(self.appels, [attendu])
        p.menage("proton", self.CACHES)             # absent de stockage.json : rien
        p.menage("", self.CACHES)
        self.assertEqual(self.appels, [attendu])

    def test_menage_empreinte_des_elements_montres(self):
        """La fenêtre passe les éléments qu'elle a montrés : leur empreinte part avec la commande (la CLI refuse si
        stockage.json ne propose plus exactement cette liste, tailles comprises)."""
        montres = [dict(self.CACHES[0], octets=999)]
        self.pont_avec_menage().menage("caches", montres)
        self.assertEqual(self.appels, [["centre-bazzite", "menage", "caches", "--empreinte", menage.empreinte(montres)]])

    def test_menage_sans_liste_montree_impossible(self):
        """Ruling V60 : plus de voie sans la liste montrée."""
        p = self.pont_avec_menage()
        with self.assertRaises(TypeError):
            p.menage("caches")
        self.assertEqual(self.appels, [])

    def test_menage_jamais_pour_une_commande_a_copier(self):
        self.pont_avec_menage().menage("journal", [{"cible": "journal"}])
        self.assertEqual(self.appels, [])

    def test_copier_met_le_texte_dans_le_presse_papiers(self):
        class Faux:
            texte = None

            def setText(self, texte):
                self.texte = texte
        faux = Faux()
        self.pont(presse_papiers=faux).copier("abc")
        self.assertEqual(faux.texte, "abc")

    def test_copier_resout_le_presse_papiers_a_l_appel(self):
        # Résolu à l'appel, pas à la création : le pont se crée aussi sans presse-papiers.
        with mock.patch.object(pont.QGuiApplication, "clipboard") as clipboard:
            p = self.pont()
            clipboard.assert_not_called()
            p.copier("x")
        clipboard.return_value.setText.assert_called_once_with("x")


if __name__ == "__main__":
    unittest.main()
