"""Page Accueil : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen), avec un etat.json de fixture.
Les éléments testés portent un objectName ; on lit leurs propriétés QML."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "fenetre"))

from PySide6.QtCore import QElapsedTimer, QEventLoop, QThread, QUrl  # noqa: E402
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
        arreter_pont(self.pont)             # UI-m1 : le pont d'un test fini ne lance plus rien
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


class AccueilModeJeu(Base):
    """Task 6 : le mode jeu se voit dans le bandeau d'accueil, seulement quand il agit (actif) ou qu'il attend de remettre
    le bureau (interrompu) ; la phrase vient telle quelle de etat.json."""
    dossier = "jeux-actif"

    def badge(self):
        b = self.f.objet("badge-modejeu")
        self.assertIsNotNone(b)
        return b.property("visible"), b.property("texte"), b.property("etat")

    def test_accueil_badge_mode_jeu(self):
        self.assertEqual(self.badge(), (True, "Mode jeu actif depuis 21 h 10", "info"))
        # le badge est dans le bandeau d'accueil
        parent = self.f.objet("badge-modejeu")
        while parent is not None and parent.objectName() != "bandeau-accueil":
            parent = parent.parentItem()
        self.assertIsNotNone(parent)

    def test_interrompu_en_attention_et_rien_sinon(self):
        phrase = "Mode jeu interrompu : le bureau sera remis comme avant à la reprise du service."
        attendu = {"interrompu": (True, phrase, "attention")}
        for etat in ("interrompu", "pret", "desactive", "arrete"):
            with self.subTest(etat=etat):
                self.f.pont._etat = dict(self.f.pont.etat, modejeu={"etat": etat, "phrase": phrase})
                self.f.pont.etatChange.emit()
                visible, texte, couleur = self.badge()
                self.assertEqual((visible, texte, couleur) if visible else visible, attendu.get(etat, False))


    def test_phrase_du_mode_jeu_jamais_hors_du_bandeau(self):
        """UI-m7 : à 800×600, la phrase du mode jeu reste dans le bandeau ; trop longue pour la ligne, elle passe à la
        ligne au lieu de déborder. Le badge d'état, lui, garde sa pilule d'une ligne."""
        fenetre = self.f.racines[0]
        fenetre.setProperty("width", 800)
        fenetre.setProperty("height", 600)
        interrompu = "Mode jeu interrompu : le bureau sera remis comme avant à la reprise du service."
        for phrase in (interrompu, interrompu + " " + interrompu):
            with self.subTest(phrase=phrase):
                self.f.pont._etat = dict(self.f.pont.etat, modejeu={"etat": "interrompu", "phrase": phrase})
                self.f.pont.etatChange.emit()
                attendre(300)
                b = self.f.objet("badge-modejeu")
                self.assertEqual(b.property("texte"), phrase)
                self.assertLessEqual(b.property("x") + b.property("width"), b.parentItem().property("width"))
        etat = self.f.objet("badge-etat")
        self.assertGreater(b.property("height"), etat.property("height"))         # plusieurs lignes, contre une
        self.assertEqual(etat.property("radius"), etat.property("height") / 2)
        b = etat = fenetre = None


class AccueilSansModeJeu(Base):
    def test_accueil_badge_mode_jeu(self):
        """Fixture « accueil » : etat.json d'avant le mode jeu, aucun badge."""
        self.assertFalse(self.f.objet("badge-modejeu").property("visible"))


class AccueilSante(Base):
    """Un point de la rubrique santé en plus (securite:temporaires) : la tuile de l'accueil le compte, la liste « À regarder »
    de la santé le montre."""

    def ouvrir(self, plus, page="accueil"):
        e = json.loads((ETATS / "complet" / "etat.json").read_text(encoding="utf-8"))
        if plus:
            e["points"].append({"id": "securite:temporaires", "gravite": "attention", "titre": "Des programmes dans /tmp",
                                "detail": "d", "mesure": 2.0, "cran": 1.0, "action": None, "en_sourdine": False,
                                "rubrique": "sante", "domaine": "securite"})
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        (Path(d.name) / "etat.json").write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
        f = Fenetre(Path(d.name), page)
        self.addCleanup(f.fermer)
        self.addCleanup(lambda: f.pont._minuteur.stop())
        return f

    def test_tuile_sante_compte_le_point_de_securite(self):
        avant = self.ouvrir(False).objet("tuile-etat").property("valeur")
        apres = self.ouvrir(True).objet("tuile-etat").property("valeur")
        self.assertEqual(int(apres.split()[0]), int(avant.split()[0]) + 1, (avant, apres))

    def test_liste_a_regarder_de_la_sante_montre_le_point(self):
        f = self.ouvrir(True, "sante")
        self.assertIsNotNone(f.objet("a-regarder-ligne-securite:temporaires"))


if __name__ == "__main__":
    unittest.main()
