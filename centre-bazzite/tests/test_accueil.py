"""Page Accueil : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen), avec un etat.json de fixture.
Les éléments testés portent un objectName ; on lit leurs propriétés QML."""
import os
import sys
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "fenetre"))

from PySide6.QtCore import QElapsedTimer, QEventLoop, QThread, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

import pont  # noqa: E402

from tests.appli_qt import APP  # noqa: E402
ETATS = ICI / "echantillons" / "etats"


class Fenetre:
    """Moteur QML + fenêtre ouverte sur l'accueil avec l'état du dossier donné."""

    def __init__(self, dossier, page="accueil"):
        self.pont = pont.Pont(ETATS / dossier / "etat.json")
        self.moteur = QQmlApplicationEngine()
        self.moteur.rootContext().setContextProperty("pont", self.pont)
        self.moteur.rootContext().setContextProperty("pageInitiale", page)
        self.moteur.load(QUrl.fromLocalFile(str(ICI.parent / "fenetre" / "qml" / "Main.qml")))
        self.racines = self.moteur.rootObjects()
        chrono = QElapsedTimer()
        chrono.start()
        while chrono.elapsed() < 300:
            APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            QThread.msleep(5)

    def tout(self):
        """Tous les éléments visuels de la fenêtre (les délégués d'un Repeater n'ont pas la fenêtre pour parent QObject)."""
        a_voir, vus = [self.racines[0].contentItem()], []
        while a_voir:
            x = a_voir.pop()
            vus.append(x)
            # Les entrailles d'un BusyIndicator (style KDE) font planter PySide quand on les emballe.
            if not x.metaObject().className().startswith("BusyIndicator"):
                a_voir.extend(x.childItems())
        return vus

    def objet(self, nom):
        return next((o for o in self.tout() if o.objectName() == nom), None)

    def objets(self, prefixe):
        return [o for o in self.tout() if (o.objectName() or "").startswith(prefixe)]

    def fermer(self):
        self.racines[0].close()
        self.moteur.deleteLater()
        self.pont.deleteLater()


class Base(unittest.TestCase):
    dossier = "accueil"

    def setUp(self):
        self.f = Fenetre(self.dossier)
        self.addCleanup(self.f.fermer)
        self.assertTrue(self.f.racines, "Main.qml ne s'est pas chargé")


class AccueilRempli(Base):
    def test_bandeau_dit_le_mot_d_etat(self):
        self.assertEqual(self.f.objet("badge-etat").property("texte"), "À regarder")
        self.assertEqual(self.f.objet("badge-etat").property("etat"), "attention")

    def test_un_seul_bouton_principal_visible(self):
        boutons = [o for o in self.f.objets("bouton-principal") if o.property("visible")]
        self.assertEqual(len(boutons), 1)
        self.assertEqual(boutons[0].property("text"), "Tout mettre à jour")

    def test_quatre_tuiles_avec_les_vraies_valeurs(self):
        t = {n: self.f.objet("tuile-" + n) for n in ("majs", "espace", "temperatures", "etat")}
        self.assertTrue(all(t.values()), t)
        self.assertEqual(t["majs"].property("valeur"), "3")
        self.assertEqual(t["majs"].property("legende"), "depuis ta dernière visite")
        # Plus faible pourcentage libre : Externe (120 / 3725,9 Go).
        self.assertEqual(t["espace"].property("valeur"), "120 Go")
        self.assertEqual(t["espace"].property("legende"), "libres sur Externe")
        self.assertEqual(t["espace"].property("etat"), "echec")
        self.assertEqual(t["temperatures"].property("valeur"), "46 °C")
        self.assertEqual(t["temperatures"].property("legende"), "GPU 46 °C · CPU 41 °C")
        self.assertEqual(t["etat"].property("valeur"), "2 points")

    def test_jauges_etat_selon_la_regle(self):
        etats = {j.property("nom"): j.property("etat") for j in self.f.objets("jauge-")}
        self.assertEqual(etats, {"Système": "attention", "Home": "ok", "Données": "ok", "Externe": "echec"})

    def test_jauge_montre_l_espace_libre(self):
        j = self.f.objet("jauge-/var/home")
        self.assertIn("561", j.property("libre"))
        self.assertIn("Go libres", j.property("libre"))
        self.assertAlmostEqual(j.property("partLibre"), 561.1 / 890.2, places=3)

    def test_points_avec_badge_de_gravite(self):
        textes = sorted(o.property("texte") for o in self.f.objets("badge-point-"))
        self.assertEqual(textes, ["Attention", "Échec"])

    def test_pas_d_etat_vide(self):
        self.assertEqual([o for o in self.f.objets("vide-") if o.property("visible")], [])

    def test_tuiles_sur_quatre_colonnes_en_large(self):
        self.assertEqual(self.f.objet("grille-tuiles").property("columns"), 4)


class AccueilEtroit(Base):
    def setUp(self):
        super().setUp()
        self.f.racines[0].setProperty("width", 800)
        chrono = QElapsedTimer()
        chrono.start()
        while chrono.elapsed() < 200:
            APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            QThread.msleep(5)

    def test_tuiles_sur_deux_colonnes_en_etroit(self):
        self.assertEqual(self.f.objet("grille-tuiles").property("columns"), 2)

    def test_mot_du_badge_dans_le_nom_accessible_de_la_tuile(self):
        # Accessible.name = légende, valeur et motEtat : on vérifie le mot qui s'y ajoute (l'attaché n'est pas lisible d'ici).
        self.assertEqual(self.f.objet("tuile-espace").property("motEtat"), "Peu d'espace libre")
        self.assertEqual(self.f.objet("tuile-majs").property("motEtat"), "")


class AccueilVide(Base):
    dossier = "vide"

    def test_etats_vides_ecrits(self):
        self.assertEqual(self.f.objet("vide-points").property("texte"), "Rien à regarder pour l'instant.")
        self.assertEqual(self.f.objet("vide-points").property("icone"), "checkmark")
        self.assertEqual(self.f.objet("vide-visite").property("texte"), "Rien de nouveau depuis ta dernière visite.")

    def test_tuiles_sans_donnees(self):
        self.assertEqual(self.f.objet("tuile-majs").property("valeur"), "À jour")
        self.assertEqual(self.f.objet("tuile-temperatures").property("valeur"), "—")
        self.assertEqual(self.f.objet("tuile-etat").property("valeur"), "Rien")


if __name__ == "__main__":
    unittest.main()
