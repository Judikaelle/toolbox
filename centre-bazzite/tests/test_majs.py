"""Page Mises à jour : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen), avec des fixtures
(etat.json + sessions/). Les éléments testés portent un objectName ; on lit leurs propriétés QML."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "fenetre"))

from PySide6.QtCore import QElapsedTimer, QEventLoop, QProcess, QThread, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

import pont  # noqa: E402

from tests.appli_qt import APP, arreter_pont  # noqa: E402
ETATS = ICI / "echantillons" / "etats"


def attendre(ms):
    chrono = QElapsedTimer()
    chrono.start()
    while chrono.elapsed() < ms:
        APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        QThread.msleep(5)


class Fenetre:
    def __init__(self, dossier):
        self.pont = pont.Pont(ETATS / dossier / "etat.json")
        self.moteur = QQmlApplicationEngine()
        self.moteur.rootContext().setContextProperty("pont", self.pont)
        self.moteur.rootContext().setContextProperty("pageInitiale", "majs")
        self.moteur.load(QUrl.fromLocalFile(str(ICI.parent / "fenetre" / "qml" / "Main.qml")))
        self.racines = self.moteur.rootObjects()
        attendre(300)

    def tout(self):
        a_voir, vus = [self.racines[0].contentItem()], []
        while a_voir:
            x = a_voir.pop()
            vus.append(x)
            a_voir.extend(x.childItems())
        return vus

    def objet(self, nom):
        return next((o for o in self.tout() if o.objectName() == nom), None)

    def objets(self, prefixe, visibles=True):
        return [o for o in self.tout() if (o.objectName() or "").startswith(prefixe)
                and (not visibles or o.property("visible"))]

    def choisir(self, cle):
        self.objet("page-majs").setProperty("choix", cle)
        attendre(100)

    def mots(self, prefixe):
        """{nom sans préfixe: (mot, état)} des badges visibles dont l'objectName commence par prefixe."""
        return {o.objectName()[len(prefixe):]: (o.property("texte"), o.property("etat"))
                for o in self.objets(prefixe)}

    def fermer(self):
        arreter_pont(self.pont)             # UI-m1 : le pont d'un test fini ne lance plus rien
        self.racines[0].close()
        self.moteur.deleteLater()
        self.pont.deleteLater()


class Base(unittest.TestCase):
    dossier = "majs"

    def setUp(self):
        self.f = Fenetre(self.dossier)
        self.addCleanup(self.f.fermer)
        self.assertTrue(self.f.racines, "Main.qml ne s'est pas chargé")
        self.assertIsNotNone(self.f.objet("page-majs"), "page Mises à jour absente")


class ListeDesSessions(Base):
    def test_issue_de_chaque_session_en_toutes_lettres(self):
        self.assertEqual(self.f.mots("badge-entree-s:"), {
            "2026-11-09T04:45:00": ("Réussie", "ok"),
            "2026-11-08T18:10:00": ("Échec", "echec"),
            "2026-11-07T21:00:00": ("Interrompue", "attention"),
        })

    def test_session_en_cours_en_haut(self):
        self.assertEqual(self.f.objet("badge-entree-cours").property("texte"), "En cours, 9 %")
        self.assertEqual(self.f.objet("badge-entree-cours").property("etat"), "en_cours")

    def test_pas_d_etat_vide_quand_il_y_a_des_sessions(self):
        self.assertIsNone(next(iter(self.f.objets("vide-sessions")), None))


class DetailDUneSession(Base):
    def test_session_en_cours_une_progression_pour_l_etape_active(self):
        self.assertEqual(self.f.mots("badge-etape-"), {
            "uupd": ("En cours", "en_cours"), "maj-apps": ("En attente", "neutre"),
            "notes": ("En attente", "neutre"), "resume": ("En attente", "neutre"),
            "etat": ("En attente", "neutre")})
        progressions = self.f.objets("progression-etape-")
        self.assertEqual([p.objectName() for p in progressions], ["progression-etape-uupd"])
        self.assertAlmostEqual(progressions[0].property("valeur"), 0.45)

    def test_session_reussie(self):
        self.f.choisir("s:2026-11-09T04:45:00")
        self.assertEqual(self.f.objet("badge-resultat").property("texte"), "Réussie")
        self.assertEqual(self.f.objet("badge-resultat").property("etat"), "ok")
        self.assertEqual(set(self.f.mots("badge-etape-").values()), {("Terminée", "ok")})
        self.assertEqual(self.f.objets("progression-etape-"), [])

    def test_session_en_echec_tous_les_statuts(self):
        self.f.choisir("s:2026-11-08T18:10:00")
        self.assertEqual(self.f.objet("badge-resultat").property("texte"), "Échec")
        self.assertEqual(self.f.mots("badge-etape-"), {
            "uupd": ("Terminée", "ok"), "maj-apps": ("Échec", "echec"),
            "notes": ("Reportée", "attention"), "resume": ("Sautée", "neutre"),
            "etat": ("Terminée", "ok")})

    def test_session_interrompue(self):
        self.f.choisir("s:2026-11-07T21:00:00")
        self.assertEqual(self.f.objet("badge-resultat").property("texte"), "Interrompue")
        self.assertEqual(self.f.objet("badge-resultat").property("etat"), "attention")

    def test_changements_de_la_visite_en_filets(self):
        self.f.choisir("visite")
        self.assertEqual(self.f.objets("vide-visite"), [])


class SourceOfficielle(Base):
    """Task 6 (v2c) : la ligne dépliée d'un changement dit en toutes lettres ce qu'il y a (ou pas) comme notes."""
    dossier = "majs-officielles"

    def deplier(self, ident):
        self.f.choisir("visite")
        self.f.objet("page-majs").setProperty("changementOuvert", ident)
        attendre(100)

    def visible(self, nom):
        return self.f.objet(nom) is not None and self.f.objet(nom).property("visible")

    def test_source_en_echec_phrase_et_lien(self):
        self.deplier("nvidia-driver")
        self.assertEqual(self.f.objet("resume-nvidia-driver").property("text"),
                         "Notes officielles non récupérées pour l'instant : ouvre-les sur le site.")
        self.assertTrue(self.visible("source-nvidia-driver"))
        self.assertTrue(self.visible("ouvrir-notes-nvidia-driver"))
        self.assertFalse(self.visible("notes-origine-nvidia-driver"))

    def test_resume_officiel_affiche(self):
        self.deplier("plasma-workspace")
        self.assertEqual(self.f.objet("resume-plasma-workspace").property("text"),
                         "Plasma corrige des plantages du bureau et améliore les notifications.")
        self.assertTrue(self.visible("ouvrir-notes-plasma-workspace"))
        self.assertTrue(self.visible("notes-origine-plasma-workspace"))

    def test_notes_sans_resume_phrase_inchangee(self):
        self.deplier("kernel")
        self.assertEqual(self.f.objet("resume-kernel").property("text"),
                         "Pas de résumé : pas de notes de version trouvées.")
        self.assertTrue(self.visible("notes-origine-kernel"))
        self.assertTrue(self.visible("ouvrir-notes-kernel"))


class TitreDuRedemarrage(unittest.TestCase):
    """Task 9 : la colonne de droite est étroite, à côté de deux boutons ; le titre du redémarrage, long, ne dépasse pas
    deux lignes à 1100 px (le reste est abrégé)."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        dossier = Path(d.name) / "majs-redemarrage"
        shutil.copytree(ETATS / "majs", dossier)
        e = json.loads((dossier / "etat.json").read_text(encoding="utf-8"))
        e["redemarrage"] = True
        e["points"].append({
            "id": "redemarrage:45.20261109", "gravite": "attention", "rubrique": "majs", "domaine": "systeme",
            "titre": "Bazzite 45.20261109 attend un redémarrage pour finir de s'installer, avec ses nouveaux "
                     "composants du système, du noyau et des pilotes graphiques, avant toute autre mise à jour",
            "detail": "La mise à jour est installée mais ne sera active qu'après un redémarrage.", "mesure": 0.0,
            "cran": 1.0, "action": {"libelle": "Redémarrer", "commande": ["systemctl", "reboot"]},
            "en_sourdine": False})
        e["compteurs"]["majs"] = e["compteurs"].get("majs", 0) + 1
        (dossier / "etat.json").write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
        self.f = Fenetre(dossier)
        self.addCleanup(self.f.fermer)
        self.f.racines[0].setProperty("width", 1100)
        self.f.racines[0].setProperty("height", 720)
        attendre(300)

    def test_titre_redemarrage_deux_lignes_au_plus(self):
        ligne = self.f.objet("a-regarder-ligne-redemarrage:45.20261109")
        self.assertIsNotNone(ligne, "ligne du redémarrage absente de la colonne de droite")
        titres, a_voir = [], [ligne]
        while a_voir:
            x = a_voir.pop()
            a_voir.extend(x.childItems())
            if str(x.property("text") or "").startswith("Bazzite 45.2"):
                titres.append(x)
        self.assertEqual(len(titres), 1)
        self.assertGreaterEqual(titres[0].property("lineCount"), 1)
        self.assertLessEqual(titres[0].property("lineCount"), 2)


class SansRien(Base):
    dossier = "vide"

    def test_etats_vides_encadres(self):
        self.assertEqual([o.property("texte") for o in self.f.objets("vide-sessions")],
                         ["Aucune mise à jour lancée depuis Health Hub pour l'instant."])
        self.assertEqual([o.property("texte") for o in self.f.objets("vide-visite")],
                         ["Rien de nouveau depuis ta dernière visite."])


class FenetreFermee(unittest.TestCase):
    def test_fermer_arrete_le_pont(self):
        """UI-m1 : une mise à jour en cours fait tourner le suivi du pont (toutes les 5 s) dès l'ouverture. Une fenêtre
        fermée l'arrête : le pont d'un test fini ne lance plus rien (deleteLater n'agit pas sans boucle d'événements, et
        le faux startDetached d'un test suivant recevrait ses commandes)."""
        appels = []

        def faux(prog, args):
            appels.append([prog] + list(args))
            return True, 1
        with mock.patch.object(QProcess, "startDetached", faux):
            f = Fenetre("majs")
            self.assertTrue(f.pont._minuteur.isActive())
            f.fermer()
            self.assertEqual([t for t in f.pont.findChildren(QTimer) if t.isActive()], [])
            veilleur = f.pont._veilleur
            self.assertEqual(veilleur.files() + veilleur.directories(), [])         # plus rien ne le réveille
            f.pont._suivre()                    # réveillé quand même : rien ne part
            f.pont.restaurerModeJeu()
        self.assertEqual(appels, [])


if __name__ == "__main__":
    unittest.main()
