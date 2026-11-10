"""Menu latéral et lancement des mises à jour : Main.qml chargé pour de vrai (QT_QPA_PLATFORM=offscreen).
Aucune vraie commande : QProcess.startDetached est remplacé, on lit les appels qu'il aurait faits."""
import gc
import sys
import unittest
from pathlib import Path
from unittest import mock

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "fenetre"))

from PySide6.QtCore import QEvent, QElapsedTimer, QEventLoop, QMetaObject, QProcess, QThread, Qt  # noqa: E402
from PySide6.QtCore import Q_ARG  # noqa: E402
from PySide6.QtQml import QQmlEngine, QQmlExpression  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from centre_bazzite import points  # noqa: E402
import json  # noqa: E402

from tests.test_accueil import APP, Fenetre  # noqa: E402


def attendre(ms, condition=lambda: False):
    chrono = QElapsedTimer()
    chrono.start()
    while chrono.elapsed() < ms and not condition():
        APP.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        QThread.msleep(5)


class Base(unittest.TestCase):
    dossier = "accueil"
    page = "accueil"
    largeur = None

    def setUp(self):
        self.appels = []
        faux = mock.patch.object(QProcess, "startDetached",
                                 lambda prog, args: self.appels.append([prog] + list(args)) or (True, 1))
        faux.start()
        self.addCleanup(faux.stop)
        self.addCleanup(self.nettoyer)
        self.f = Fenetre(self.dossier, self.page)
        self.addCleanup(self.f.fermer)
        # Le suivi du pont (5 s) ne doit pas déborder sur les tests suivants.
        self.addCleanup(lambda: self.f.pont._minuteur.stop())
        self.assertTrue(self.f.racines, "Main.qml ne s'est pas chargé")
        self.fenetre = self.f.racines[0]
        if self.largeur:
            self.fenetre.setProperty("width", self.largeur)
            attendre(300)

    def nettoyer(self):
        """Détruit vraiment la fenêtre : un emballage Python resté sur un objet Qt détruit fait planter PySide
        quand une adresse est réutilisée par le test suivant."""
        self.fenetre = None
        self.f.racines.clear()
        gc.collect()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()

    def visible(self, nom):
        o = self.f.objet(nom)
        return o is not None and bool(o.property("visible"))

    def cliquer(self, nom):
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        QMetaObject.invokeMethod(o, "clicked", Qt.DirectConnection)
        attendre(100)

    def appeler(self, fonction, *args):
        QMetaObject.invokeMethod(self.fenetre, fonction, Qt.DirectConnection,
                                 *[Q_ARG("QVariant", a) for a in args])
        attendre(100)

    def evaluer(self, js):
        """Évalue du JavaScript dans la portée de Main.qml (ses id). On évite findChild : l'emballage Python
        d'un dialogue détruit fait planter PySide quand son adresse est réutilisée par le test suivant."""
        e = QQmlExpression(QQmlEngine.contextForObject(self.fenetre), self.fenetre, js)
        valeur, erreur = e.evaluate()          # PySide rend (valeur, erreur ?)
        self.assertFalse(erreur, e.error().toString())
        return valeur

    def declencher(self, action):
        """Déclenche une action de pied de dialogue (comme un clic sur son bouton)."""
        dialogue = "confirmationJeu" if "-jeu-" in action else "confirmationExtinction"
        ok = self.evaluer("(function () { var l = %s.customFooterActions; "
                          "for (var i = 0; i < l.length; i++) { if (l[i].objectName === '%s') { l[i].trigger(); return true; } } "
                          "return false; })()" % (dialogue, action))
        self.assertTrue(ok, action)
        attendre(100)

    def maj(self):
        return [a for a in self.appels if a[:2] == ["centre-bazzite", "maj"]]

    def ferme(self, nom):
        """Le dialogue finit sa transition de sortie avant de devenir invisible."""
        attendre(1500, lambda: not self.ouvert(nom))
        return not self.ouvert(nom)

    def ouvert(self, nom):
        id_ = "confirmationJeu" if nom == "confirmation-jeu" else "confirmationExtinction"
        return self.evaluer(id_ + ".visible") is True


class MenuDeplie(Base):
    def test_menu_deplie_en_large(self):
        self.assertTrue(self.f.objet("menu-lateral").property("deplie"))
        self.assertTrue(self.fenetre.property("menuDeplie"))

    def test_compteurs_du_moteur(self):
        self.assertEqual(self.f.objet("compteur-stockage").property("texte"), "2")
        self.assertTrue(self.visible("compteur-stockage"))
        self.assertFalse(self.visible("compteur-majs"))       # 0 : masqué
        self.assertFalse(self.visible("compteur-sante"))

    def test_pied_dit_l_etat_et_la_derniere_verification(self):
        self.assertEqual(self.f.objet("menu-etat").property("texte"), "À regarder")
        self.assertEqual(self.f.objet("menu-etat").property("etat"), "attention")
        self.assertIn("Dernière vérification", self.f.objet("menu-verification").property("text"))

    def test_pas_de_tout_mettre_a_jour_dans_le_pied_de_l_accueil(self):
        self.assertFalse(self.visible("menu-tout-mettre-a-jour"))
        self.assertEqual(len([o for o in self.f.objets("bouton-principal") if o.property("visible")]), 1)

    def test_derniere_verification_identique_a_celle_de_l_accueil(self):
        self.cliquer("menu-bouton-accueil")
        accueil = self.f.objet("verification-accueil")
        self.assertEqual(accueil.property("text"), self.f.objet("menu-verification").property("text"))

    def test_entrees_bientot_grisees(self):
        self.assertFalse(self.f.objet("menu-demarrage").property("disponible"))
        for nom in ("accueil", "majs", "sante", "stockage", "jeux"):
            self.assertTrue(self.f.objet("menu-" + nom).property("disponible"), nom)

    def test_menu_jeux_disponible(self):
        """Task 6 : « Jeux » est une entrée du menu, juste après Stockage ; un clic ouvre la page Jeux."""
        entrees = sorted((o for o in self.f.objets("menu-") if o.property("entree") is not None
                          and o.property("disponible")), key=lambda o: o.property("y"))
        self.assertEqual([o.objectName() for o in entrees],
                         ["menu-accueil", "menu-majs", "menu-sante", "menu-stockage", "menu-jeux"])
        entrees = None
        self.cliquer("menu-bouton-jeux")
        self.assertEqual(self.fenetre.property("page"), "jeux")
        self.assertTrue(self.f.objet("menu-jeux").property("active"))
        self.assertIsNotNone(self.f.objet("page-jeux"))
        self.assertIn(["centre-bazzite", "jeux"], self.appels)

    def test_entree_stockage_ouvre_la_page_stockage(self):
        self.cliquer("menu-bouton-stockage")
        self.assertEqual(self.fenetre.property("page"), "stockage")
        self.assertTrue(self.f.objet("menu-stockage").property("active"))
        self.assertIsNotNone(self.f.objet("page-stockage"))

    def test_entree_active_et_changement_de_page(self):
        self.assertTrue(self.f.objet("menu-accueil").property("active"))
        self.cliquer("menu-bouton-sante")
        self.assertEqual(self.fenetre.property("page"), "sante")
        self.assertTrue(self.f.objet("menu-sante").property("active"))
        self.assertFalse(self.f.objet("menu-accueil").property("active"))

    def test_replier_puis_deplier(self):
        self.cliquer("menu-basculer")
        self.assertFalse(self.f.objet("menu-lateral").property("deplie"))
        self.cliquer("menu-basculer")
        self.assertTrue(self.f.objet("menu-lateral").property("deplie"))


class MenuSante(Base):
    page = "sante"

    def test_tout_mettre_a_jour_dans_le_pied(self):
        b = self.f.objet("menu-tout-mettre-a-jour")
        self.assertTrue(self.visible("menu-tout-mettre-a-jour"))
        self.assertEqual(b.property("text"), "Tout mettre à jour")

    def test_un_seul_bouton_principal_visible(self):
        principaux = [o for o in self.f.objets("") if o.metaObject().className().startswith("BoutonPrincipal")
                      and o.property("visible")]
        self.assertEqual(len(principaux), 1)

    def test_verifier_maintenant_lance_un_rafraichissement_complet(self):
        self.cliquer("menu-verifier")
        self.assertIn(["centre-bazzite", "rafraichir"], self.appels)
        self.assertTrue(self.f.objet("menu-verifier").property("occupe"))
        self.assertFalse(self.f.objet("menu-verifier").property("enabled"))


class MenuRail(Base):
    page = "sante"
    largeur = 800

    def test_rail_en_etroit(self):
        self.assertFalse(self.f.objet("menu-lateral").property("deplie"))

    def test_tout_mettre_a_jour_reste_accessible(self):
        self.assertTrue(self.visible("menu-tout-mettre-a-jour"))
        self.assertEqual(self.f.objet("menu-tout-mettre-a-jour").property("text"), "")

    def test_compteur_en_surimpression_et_nom_accessible(self):
        self.assertTrue(self.visible("compteur-stockage"))
        self.assertEqual(self.f.objet("menu-stockage").property("nomAccessible"), "Stockage : 2 à regarder")

    def test_infobulle_du_bouton_principal_dit_le_libelle_et_le_raccourci(self):
        self.assertEqual(self.f.objet("menu-tout-mettre-a-jour").property("infobulle"), "Tout mettre à jour (Ctrl+U)")

    def test_infobulles_des_entrees(self):
        self.assertEqual(self.f.objet("menu-demarrage").property("infobulle"), "Démarrage : bientôt")
        self.assertEqual(self.f.objet("menu-jeux").property("infobulle"), "Jeux")
        self.assertEqual(self.f.objet("menu-stockage").property("infobulle"), "Stockage : 2 à regarder")
        self.assertEqual(self.f.objet("menu-sante").property("infobulle"), "Santé")

    def test_deplie_a_la_demande_meme_en_etroit(self):
        self.cliquer("menu-basculer")
        self.assertTrue(self.f.objet("menu-lateral").property("deplie"))


class SecuriteDesMisesAJour(Base):
    """Ruling v1 R25 : confirmations, jeu, boutons bloqués. Rien n'est lancé pour de bon."""
    dossier = "jeu"

    def test_un_jeu_demande_confirmation_avant_toute_mise_a_jour(self):
        self.appeler("demanderMaj", False)
        self.assertTrue(self.ouvert("confirmation-jeu"))
        self.assertEqual(self.maj(), [])

    def test_meme_si_jeu_seulement_apres_confirmation(self):
        self.appeler("demanderMaj", False)
        self.assertEqual(self.maj(), [])
        self.declencher("action-jeu-lancer")
        self.assertEqual(self.maj(), [["centre-bazzite", "maj", "--meme-si-jeu"]])

    def test_attendre_ne_lance_rien(self):
        self.appeler("demanderMaj", False)
        self.declencher("action-jeu-attendre")
        self.assertTrue(self.ferme("confirmation-jeu"))
        self.assertEqual(self.maj(), [])
        self.assertFalse(self.fenetre.property("lancement"))

    def test_extinction_confirmee_puis_question_du_jeu_puis_extinction_lancee(self):
        self.appeler("demanderMaj", True)
        self.declencher("action-extinction-lancer")
        self.assertEqual(self.maj(), [])                    # le jeu doit encore être confirmé
        self.declencher("action-jeu-lancer")
        self.assertEqual(self.maj(), [["centre-bazzite", "maj", "--eteindre", "--meme-si-jeu"]])

    def test_annuler_l_extinction_ne_lance_rien(self):
        self.appeler("demanderMaj", True)
        self.declencher("action-extinction-annuler")
        self.assertTrue(self.ferme("confirmation-extinction"))
        self.assertEqual(self.maj(), [])

    def test_extinction_demande_confirmation(self):
        self.appeler("demanderMaj", True)
        self.assertTrue(self.ouvert("confirmation-extinction"))
        self.assertEqual(self.maj(), [])

    def test_extinction_avec_jeu_pose_la_question_du_jeu_aussi(self):
        self.appeler("lancerMaj", True, False)
        self.assertTrue(self.ouvert("confirmation-jeu"))
        self.assertEqual(self.fenetre.property("majDemandee"), "eteindre")
        self.assertEqual(self.maj(), [])

    def test_boutons_bloques_pendant_un_lancement(self):
        self.appeler("lancerMaj", False, True)
        self.assertTrue(self.fenetre.property("lancement"))
        self.assertTrue(self.fenetre.property("boutonsBloques"))
        self.appeler("demanderMaj", False)
        self.assertEqual(len(self.maj()), 1)
        self.assertFalse(self.f.objet("bouton-principal").property("enabled"))

    def test_le_bouton_de_l_accueil_aussi(self):
        self.cliquer("bouton-principal")
        self.assertTrue(self.ouvert("confirmation-jeu"))
        self.assertEqual(self.maj(), [])


class SecuriteDuMenu(SecuriteDesMisesAJour):
    page = "sante"

    def test_le_bouton_du_menu_passe_par_le_meme_chemin(self):
        self.cliquer("menu-tout-mettre-a-jour")
        self.assertTrue(self.ouvert("confirmation-jeu"))
        self.assertEqual(self.maj(), [])

    def test_le_bouton_du_menu_se_bloque_pendant_un_lancement(self):
        self.appeler("lancerMaj", False, True)
        self.assertFalse(self.f.objet("menu-tout-mettre-a-jour").property("enabled"))

    test_le_bouton_de_l_accueil_aussi = None
    test_boutons_bloques_pendant_un_lancement = None


class RaccourciHorsAccueil(Base):
    dossier = "jeu"
    page = "sante"

    def test_ctrl_u_hors_de_l_accueil_pose_la_question_du_jeu(self):
        self.fenetre.requestActivate()
        attendre(200)
        QTest.keyClick(self.fenetre, Qt.Key_U, Qt.ControlModifier)
        attendre(100)
        self.assertTrue(self.ouvert("confirmation-jeu"))
        self.assertEqual(self.maj(), [])


class AnnulerExtinctionDansLeMenu(Base):
    dossier = "eteindre"
    page = "sante"

    def annuler(self):
        return self.f.objet("menu-annuler-extinction")

    def test_propose_pendant_une_session_et_eteindre(self):
        self.assertTrue(self.visible("menu-annuler-extinction"))
        self.assertEqual(self.annuler().property("text"), "Annuler l'extinction")

    def test_clic_comme_dans_le_bandeau(self):
        self.cliquer("menu-annuler-extinction")
        self.assertIn(["centre-bazzite", "annuler-extinction"], self.appels)
        self.assertFalse(self.visible("menu-annuler-extinction"))
        self.assertEqual(self.fenetre.property("extinctionAnnulee"), "2026-11-09T09:30:00")

    def test_absent_sans_extinction_prevue(self):
        self.f.fermer()
        self.f = Fenetre("majs", "sante")
        self.fenetre = self.f.racines[0]
        self.addCleanup(self.f.fermer)
        self.assertFalse(self.visible("menu-annuler-extinction"))


class AnnulerExtinctionEnRail(AnnulerExtinctionDansLeMenu):
    largeur = 800

    def test_propose_pendant_une_session_et_eteindre(self):
        self.assertTrue(self.visible("menu-annuler-extinction"))

    def test_bouton_icone_avec_infobulle(self):
        self.assertEqual(self.annuler().property("text"), "")
        self.assertEqual(self.annuler().property("infobulle"), "Annuler l'extinction")


class PetiteHauteur(Base):
    page = "sante"

    def test_le_pied_reste_entier(self):
        self.fenetre.setProperty("height", 470)
        attendre(300)
        pied = self.f.objet("menu-tout-mettre-a-jour")
        menu = self.f.objet("menu-lateral")
        bas = pied.mapToItem(menu, 0, pied.property("height")).y()
        self.assertLessEqual(bas, menu.property("height"))
        defilement = self.f.objet("menu-defilement")
        self.assertGreater(defilement.property("contentHeight"), defilement.property("height"))


class Coherence(unittest.TestCase):
    def test_compteurs_de_chaque_fixture_suivent_les_points(self):
        for dossier in sorted((ICI / "echantillons" / "etats").iterdir()):
            e = json.loads((dossier / "etat.json").read_text(encoding="utf-8"))
            if "compteurs" in e:
                self.assertEqual(e["compteurs"], points.compteurs(e.get("points", [])), dossier.name)

    def test_rubrique_de_chaque_point_des_fixtures(self):
        for dossier in sorted((ICI / "echantillons" / "etats").iterdir()):
            e = json.loads((dossier / "etat.json").read_text(encoding="utf-8"))
            for p in e.get("points", []):
                if "rubrique" in p:
                    self.assertEqual(p["rubrique"], points.rubrique(p["id"]), f"{dossier.name} {p['id']}")

    def test_domaine_de_chaque_point_des_fixtures(self):
        """Task 19 : les fixtures de la page Santé portent le domaine que le moteur écrirait."""
        vus = set()
        for dossier in sorted((ICI / "echantillons" / "etats").iterdir()):
            e = json.loads((dossier / "etat.json").read_text(encoding="utf-8"))
            for p in e.get("points", []):
                if "domaine" in p:
                    vus.add(dossier.name)
                    self.assertEqual(p["domaine"], points.domaine(p["id"]), f"{dossier.name} {p['id']}")
        self.assertLessEqual({"complet", "controles", "a-regarder"}, vus)


class SansJeu(Base):
    def test_maj_simple_part_sans_question(self):
        self.appeler("demanderMaj", False)
        self.assertFalse(self.ouvert("confirmation-jeu"))
        self.assertIn(["centre-bazzite", "maj"], self.appels)


if __name__ == "__main__":
    unittest.main()
