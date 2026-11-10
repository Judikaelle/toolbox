"""« À regarder » en tête des pages Stockage et Mises à jour, et tuile « Mises à jour » de l'accueil (revue finale I3) :
chaque page montre ce que son compteur du menu compte. Fixture « a-regarder » : Données non monté, deux volumes serrés, un
téléchargement incomplet, une image et trois Flatpak disponibles, un redémarrage en attente, un point de santé et une
sourdine. Aucune vraie commande : QProcess.startDetached est remplacé ; le dialogue n'est lu qu'en JavaScript."""
import gc
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent, QMetaObject, QProcess, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression

from tests.test_accueil import APP, ETATS, Fenetre
from tests.test_menu import attendre

FIXTURE = ETATS / "a-regarder"
ETAT = json.loads((FIXTURE / "etat.json").read_text(encoding="utf-8"))
REDEMARRAGE = "redemarrage:45.20261109"


def en_sourdine(prefixes):
    return [dict(p, en_sourdine=True) if p["id"].startswith(prefixes) else p for p in ETAT["points"]]


class Base(unittest.TestCase):
    dossier = "a-regarder"
    page = "stockage"
    champs = None           # variante : ces champs d'etat.json remplacés, dans une copie temporaire de la fixture

    def setUp(self):
        self.appels = []
        faux = mock.patch.object(QProcess, "startDetached",
                                 lambda prog, args: self.appels.append([prog] + list(args)) or (True, 1))
        faux.start()
        self.addCleanup(faux.stop)
        self.f = Fenetre(self.variante() if self.champs is not None else self.dossier, self.page)
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())
        self.assertTrue(self.f.racines, "Main.qml ne s'est pas chargé")

    def variante(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dossier = Path(tmp.name) / "a-regarder"
        shutil.copytree(FIXTURE, dossier)
        (dossier / "etat.json").write_text(json.dumps(dict(ETAT, **self.champs), ensure_ascii=False), encoding="utf-8")
        return str(dossier)         # absolu : ETATS / dossier le garde tel quel

    def lignes(self):
        """Les points de la liste « À regarder », de haut en bas."""
        lignes = sorted(self.f.objets("a-regarder-ligne-"), key=lambda o: o.property("y"))
        return [o.objectName()[len("a-regarder-ligne-"):] for o in lignes]

    def badge(self, id_):
        b = self.f.objet("badge-point-" + id_)
        self.assertIsNotNone(b, id_)
        return b.property("texte"), b.property("etat")

    def clic(self, nom):
        bouton = self.f.objet(nom)
        self.assertIsNotNone(bouton, nom)
        QMetaObject.invokeMethod(bouton, "clicked", Qt.DirectConnection)
        attendre(100)


class StockageARegarder(Base):
    def test_la_page_montre_ce_que_son_compteur_compte(self):
        self.assertEqual(self.lignes(), ["stockage:non-monte:/var/mnt/DONNEES", "volume:/var", "volume:/var/mnt/EXTERNE",
                                         "menage:telechargements-incomplets"])
        self.assertEqual(len(self.lignes()), ETAT["compteurs"]["stockage"])
        self.assertTrue(self.f.objet("a-regarder-stockage").property("visible"))

    def test_en_tete_de_la_page(self):
        """En tête de la vue d'ensemble, au-dessus des disques (Task 19 : ils ne sont plus frères dans la mise en page)."""
        page = self.f.objet("page-stockage")
        liste = self.f.objet("a-regarder-stockage")
        disque = self.f.objet("stockage-disque-nvme0n1")
        self.assertLess(liste.mapToItem(page, 0, liste.property("height")).y(), disque.mapToItem(page, 0, 0).y())

    def test_etat_de_chaque_point_ecrit(self):
        self.assertEqual(self.badge("stockage:non-monte:/var/mnt/DONNEES"), ("Échec", "echec"))
        self.assertEqual(self.badge("menage:telechargements-incomplets"), ("Attention", "attention"))

    def test_ni_sourdine_ni_autre_rubrique(self):
        self.assertIsNone(self.f.objet("a-regarder-ligne-menage:journal"))
        self.assertIsNone(self.f.objet("a-regarder-ligne-deploiements:trop"))
        self.assertIsNone(self.f.objet("a-regarder-ligne-maj:dispo:flatpak"))
        self.assertIsNotNone(self.f.objet("sourdine-menage:journal"))         # toujours en bas, grisé

    def test_ne_plus_signaler(self):
        self.clic("point-sourdine-menage:telechargements-incomplets")
        self.assertIn(["centre-bazzite", "sourdine", "menage:telechargements-incomplets"], self.appels)
        self.assertNotIn("menage:telechargements-incomplets", self.lignes())


class StockageRienARegarder(Base):
    champs = {"points": en_sourdine(("volume:", "menage:", "stockage:"))}

    def test_pas_de_liste_vide(self):
        self.assertEqual(self.lignes(), [])
        self.assertFalse(self.f.objet("a-regarder-stockage").property("visible"))


class MisesAJourARegarder(Base):
    page = "majs"

    def setUp(self):
        super().setUp()
        self.addCleanup(self.nettoyer)
        # Les id d'ARegarder.qml vivent dans le contexte de ses éléments internes (comme pour MenageSection).
        self.interne = self.f.objet("a-regarder-liste-majs")
        self.assertIsNotNone(self.interne)

    def nettoyer(self):
        self.interne = None
        gc.collect()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()

    def js(self, code):
        e = QQmlExpression(QQmlEngine.contextForObject(self.interne), self.interne, code)
        valeur, _indefinie = e.evaluate()
        self.assertFalse(e.hasError(), e.error().toString())
        return valeur

    def test_la_page_montre_ce_que_son_compteur_compte(self):
        self.assertEqual(self.lignes(), [REDEMARRAGE, "maj:dispo:image:45.20261115", "maj:dispo:flatpak"])
        self.assertEqual(len(self.lignes()), ETAT["compteurs"]["majs"])

    def test_mises_a_jour_disponibles_ecrites(self):
        self.assertEqual(self.badge("maj:dispo:image:45.20261115"), ("Disponible", "info"))
        self.assertEqual(self.badge("maj:dispo:flatpak"), ("Disponible", "info"))
        self.assertEqual(self.badge(REDEMARRAGE), ("Attention", "attention"))

    def test_redemarrer_demande_confirmation(self):
        self.assertEqual(self.f.objet("point-action-" + REDEMARRAGE).property("text"), "Redémarrer")
        self.clic("point-action-" + REDEMARRAGE)
        attendre(1500, lambda: self.js("confirmationRedemarrage.opened"))
        self.assertTrue(self.js("confirmationRedemarrage.opened"))
        self.assertEqual(self.appels, [])                           # rien n'est lancé sans confirmation
        self.js("confirmationRedemarrage.customFooterActions[0].trigger()")
        attendre(100)
        self.assertEqual(self.appels, [["centre-bazzite", "redemarrer"]])


class MisesAJourPendantUneMiseAJour(Base):
    page = "majs"
    champs = {"en_cours": {"debut": "2026-11-09T10:00:00", "global": 10, "etapes": {}}}

    def test_pas_de_redemarrage_pendant_une_mise_a_jour(self):
        self.assertIn(REDEMARRAGE, self.lignes())
        self.assertFalse(self.f.objet("point-action-" + REDEMARRAGE).property("visible"))


class MisesAJourRienARegarder(Base):
    page = "majs"
    dossier = "majs"

    def test_pas_de_liste_vide(self):
        self.assertFalse(self.f.objet("a-regarder-majs").property("visible"))


class TuileDisponibles(Base):
    page = "accueil"

    def test_mises_a_jour_disponibles_sans_changement(self):
        t = self.f.objet("tuile-majs")
        self.assertEqual((t.property("valeur"), t.property("legende")), ("4", "à installer"))
        self.assertEqual((t.property("etat"), t.property("motEtat")), ("info", "Disponibles"))


class TuileChangementsEtDisponibles(Base):
    page = "accueil"
    champs = {"depuis_visite": {"depuis": "2026-11-09T08:00:00", "nombre": 2, "chronologie": []}}

    def test_les_changements_d_abord_et_le_badge(self):
        t = self.f.objet("tuile-majs")
        self.assertEqual((t.property("valeur"), t.property("legende")), ("2", "depuis ta dernière visite"))
        self.assertEqual((t.property("etat"), t.property("motEtat")), ("info", "Disponibles"))


class TuileDisponiblesEnSourdine(Base):
    page = "accueil"
    champs = {"points": en_sourdine(("maj:dispo:",))}

    def test_a_jour_sans_badge(self):
        t = self.f.objet("tuile-majs")
        self.assertEqual((t.property("valeur"), t.property("etat")), ("À jour", ""))


if __name__ == "__main__":
    unittest.main()
