"""Page Jeux : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen), avec le dossier de fixture « jeux »
(etat.json, jeux.json, stockage.json ; noms génériques seulement). Aucune vraie commande : QProcess.startDetached est
remplacé. Comme Stockage, la page a des onglets ; seul l'onglet ouvert existe, et la fenêtre le garde (ongletJeux)."""
import unittest

from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtQml import QJSValue, QQmlEngine, QQmlExpression

from centre_bazzite import jeux, menage, modejeu
from tests.test_menu import attendre
from tests.test_stockagepage import TOLERANCE_ECRAN, Base as BaseStockage, nettoyer_emballages

RELEVE = [["centre-bazzite", "jeux"], ["centre-bazzite", "stockage"], ["centre-bazzite", "rafraichir", "--leger"]]
DONNEES = "steam:/var/mnt/DONNEES/SteamLibrary"
EXTERNE = "steam:/var/mnt/EXTERNE/SteamLibrary"
GELS = "/home/exemple/.local/share/freeze-jeu"


class Base(BaseStockage):
    dossier = "jeux"
    page = "jeux"

    def fenetre(self):
        return self.f.racines[0]

    def clic(self, nom):
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        QMetaObject.invokeMethod(o, "clicked", Qt.DirectConnection)
        o = None
        attendre(150)
        nettoyer_emballages()

    def ouvrir_onglet(self, cle):
        """Clic sur l'onglet `cle`, comme l'utilisateur."""
        self.clic("onglet-" + cle)
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), cle)

    def propriete(self, nom, cle):
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        return o.property(cle)

    def remplacer_jeux(self, **champs):
        """Comme une relecture de jeux.json par le pont."""
        self.f.pont._jeux = dict(self.f.pont.jeux, **champs)
        self.f.pont.jeuxChange.emit()
        attendre(150)
        nettoyer_emballages()

    def remplacer_modejeu(self, **champs):
        """Comme une relecture de etat.json : le résumé du mode jeu change."""
        self.f.pont._etat = dict(self.f.pont.etat, modejeu=dict(self.f.pont.etat.get("modejeu") or {}, **champs))
        self.f.pont.etatChange.emit()
        attendre(150)
        nettoyer_emballages()

    def js(self, nom, code):
        """Évalue `code` dans la portée de l'objet `nom` (ses propriétés, les id de son composant)."""
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        e = QQmlExpression(QQmlEngine.contextForObject(o), o, code)
        valeur, _indefinie = e.evaluate()
        self.assertFalse(e.hasError(), e.error().toString())
        o = e = None
        return valeur.toVariant() if isinstance(valeur, QJSValue) else valeur

    def assertReleveLance(self):
        """Les trois commandes de l'ouverture, dans l'ordre, et rien d'autre : le pont d'un test fini ne lance plus rien
        (UI-m1, tests.appli_qt.arreter_pont)."""
        self.assertEqual(self.appels, RELEVE)

    def tient_sur_un_ecran(self, cle):
        self.assertEqual((self.fenetre().property("width"), self.fenetre().property("height")), (1100, 720))
        page = self.f.objet("page-jeux")
        self.assertLessEqual(page.property("contentHeight"), page.property("height") + TOLERANCE_ECRAN, cle)


class Ouverture(Base):
    def test_ouverture_rafraichit(self):
        """La page relance le relevé des jeux, celui du stockage (le ménage des jeux) et l'état (le mode jeu)."""
        self.assertReleveLance()
        self.assertIsNotNone(self.f.objet("page-jeux"))
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), "ensemble")

    def test_aucun_bouton_principal_sur_la_page(self):
        """« Tout mettre à jour » reste en pied de menu : c'est le seul bouton principal visible."""
        principaux = [o for o in self.f.objets("") if o.metaObject().className().startswith("BoutonPrincipal")
                      and o.property("visible")]
        self.assertEqual([o.objectName() for o in principaux], ["menu-tout-mettre-a-jour"])


class VueDEnsemble(Base):
    def test_lignes_de_la_vue_d_ensemble(self):
        self.assertEqual(self.propriete("modejeu-phrase", "text"), "Mode jeu prêt : il s'active quand un jeu démarre.")
        self.assertEqual((self.propriete("modejeu-badge", "texte"), self.propriete("modejeu-badge", "etat")),
                         ("Prêt", "ok"))
        self.assertEqual(self.propriete("modejeu-derniere", "text"),
                         "Dernière partie : Jeu de course, le 9 nov. de 21 h 10 à 23 h 02.")
        self.assertEqual(self.propriete("bibliotheque-nom-" + DONNEES, "text"), "Steam (Données)")
        self.assertEqual(self.propriete("bibliotheque-nombre-" + DONNEES, "text"), "4 jeux")
        self.assertEqual(self.propriete("bibliotheque-taille-" + DONNEES, "text"), "115 Go")
        self.assertEqual(self.propriete("bibliotheque-nombre-lutris", "text"), "1 jeu")
        externe = "bibliotheque-absente-steam:/var/mnt/EXTERNE/SteamLibrary"
        self.assertEqual((self.propriete(externe, "visible"), self.propriete(externe, "texte"),
                          self.propriete(externe, "etat")), (True, "Absente", "neutre"))
        self.assertFalse(self.propriete("bibliotheque-absente-" + DONNEES, "visible"))
        self.assertEqual(len(self.f.objets("bibliotheque-nom-")), 6)
        self.assertEqual(self.propriete("doublons-phrase", "text"), "1 jeu en double : 38 Go en trop")
        self.assertEqual((self.propriete("doublons-badge", "visible"), self.propriete("doublons-badge", "etat")),
                         (True, "attention"))
        # shaders (1,2 Go) + proton (1,2 Go), pas les caches (1,5 Go) : ce sont ceux de Stockage
        self.assertEqual(self.propriete("menage-phrase", "text"), "2,4 Go à libérer")
        self.assertEqual(self.propriete("prefixes-phrase", "text"), "3 préfixes orphelins (2,5 Go), seulement listés")
        self.assertEqual(self.propriete("gels-phrase", "text"), "3 captures, la dernière le 21 sept.")

    def test_lignes_vides(self):
        self.remplacer_jeux(doublons=[], gels={"dossier": "/home/exemple/g", "nombre": 0, "automatiques": 0,
                                               "dernier": None, "liste": []},
                            prefixes={"elements": [], "octets": 0, "taille": "0 Mo"})
        self.assertEqual(self.propriete("doublons-phrase", "text"), "Aucun jeu en double.")
        self.assertFalse(self.propriete("doublons-badge", "visible"))
        self.assertEqual(self.propriete("gels-phrase", "text"), "Aucun gel capturé.")
        self.assertFalse(self.propriete("prefixes-phrase", "visible"))

    def test_mode_jeu_absent_dit_service_arrete(self):
        """Un etat.json d'avant le mode jeu : l'état « arrete »."""
        self.f.pont._etat = {k: v for k, v in self.f.pont.etat.items() if k != "modejeu"}
        self.f.pont.etatChange.emit()
        attendre(150)
        self.assertEqual(self.propriete("modejeu-phrase", "text"), "Le service du mode jeu ne tourne pas.")
        self.assertEqual((self.propriete("modejeu-badge", "texte"), self.propriete("modejeu-badge", "etat")),
                         ("Service arrêté", "attention"))
        self.assertFalse(self.propriete("modejeu-derniere", "visible"))

    def test_badge_du_mode_jeu_selon_son_etat(self):
        attendu = {"actif": ("Actif", "info"), "pret": ("Prêt", "ok"), "desactive": ("Désactivé", "neutre"),
                   "arrete": ("Service arrêté", "attention"), "interrompu": ("Interrompu", "attention")}
        for etat, mots in attendu.items():
            with self.subTest(etat=etat):
                self.remplacer_modejeu(etat=etat)
                self.assertEqual((self.propriete("modejeu-badge", "texte"), self.propriete("modejeu-badge", "etat")),
                                 mots)

    def test_erreurs_de_bibliotheque_affichees(self):
        self.assertFalse(self.propriete("jeux-erreurs", "visible"))
        self.remplacer_jeux(erreurs=["Heroic : illisible (JSONDecodeError)", "Steam : illisible (bibliothèques non "
                                                                              "vérifiables)"])
        self.assertTrue(self.propriete("jeux-erreurs", "visible"))
        self.assertEqual(self.propriete("jeux-erreurs", "text"),
                         "Heroic : illisible (JSONDecodeError)\nSteam : illisible (bibliothèques non vérifiables)")
        self.assertEqual(self.propriete("jeux-erreurs", "type"), 2)          # Kirigami.MessageType.Warning

    def test_vue_d_ensemble_tient_sur_un_ecran(self):
        self.tient_sur_un_ecran("ensemble")

    def test_ensemble_tient_aussi_avec_des_erreurs(self):
        self.remplacer_jeux(erreurs=["Heroic : illisible (JSONDecodeError)", "Lutris : illisible (DatabaseError)"])
        self.tient_sur_un_ecran("ensemble")


class JeuxVide(Base):
    dossier = "jeux-vide"

    def test_jeux_vide_etat_vide(self):
        vide = self.f.objet("jeux-vide")
        self.assertIsNotNone(vide)
        self.assertTrue(vide.property("visible"))
        self.assertEqual(vide.property("texte"), "Pas encore de relevé des jeux : il se fait à l'ouverture de la page.")
        vide = None
        self.assertIsNone(self.f.objet("bibliotheque-nom-lutris"))
        self.assertEqual(self.propriete("modejeu-phrase", "text"), "Le service du mode jeu ne tourne pas.")
        self.assertReleveLance()


# --- Task 7 : Bibliothèques (filtres, tri, doublons) et Gels ---

class Bibliotheques(Base):
    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("bibliotheques")

    def titres(self):
        return self.js("liste-jeux", "model.map(j => j.titre)")

    def trier(self, cle):
        self.js("tri", f"choisir('{cle}')")
        attendre(150)
        nettoyer_emballages()

    def test_en_tete_et_toutes_les_bibliotheques(self):
        self.assertEqual(self.propriete("bibliotheques-entete", "text"), "9 jeux · 201 Go au total")
        self.assertEqual(self.propriete("liste-jeux", "count"), 9)
        self.assertEqual(self.f.racines[0].property("filtreJeux"), "")
        filtres = sorted(self.f.objets("filtre-"), key=lambda o: o.property("x"))
        self.assertEqual([o.objectName() for o in filtres][:2], ["filtre-toutes", "filtre-doublons"])
        self.assertEqual(len(filtres), 2 + 6)
        self.assertTrue(self.propriete("filtre-toutes", "checked"))

    def test_bibliotheques_filtre_par_bibliotheque(self):
        self.clic("filtre-" + DONNEES)
        self.assertEqual(self.f.racines[0].property("filtreJeux"), DONNEES)
        self.assertEqual(self.propriete("liste-jeux", "count"), 4)
        self.assertEqual(set(self.titres()), {"Aventure", "Énigmes", "Jeu de course", "Plateformes"})
        self.assertTrue(self.propriete("filtre-" + DONNEES, "checked"))
        self.assertEqual(self.propriete("bibliotheques-entete", "text"), "4 jeux · 115 Go au total")
        self.clic("filtre-toutes")
        self.assertEqual(self.propriete("liste-jeux", "count"), 9)

    def test_tri_par_taille_par_defaut(self):
        self.assertEqual(self.propriete("tri", "currentText"), "Taille")
        self.assertEqual(self.titres(), ["Jeu de course", "Aventure", "Aventure", "Stratégie", "Jeu de rôle",
                                         "Plateformes", "Rallye", "Énigmes", "Casse-tête"])

    def test_bibliotheques_tri_par_derniere_partie(self):
        self.trier("partie")
        self.assertEqual(self.propriete("tri", "currentText"), "Dernière partie")
        titres = self.titres()
        self.assertEqual(titres[:5], ["Jeu de course", "Stratégie", "Aventure", "Aventure", "Énigmes"])
        self.assertEqual(set(titres[5:]), {"Casse-tête", "Jeu de rôle", "Plateformes", "Rallye"})
        self.assertEqual(self.js("liste-jeux", "model[2].bibliotheque"), DONNEES)    # la plus récente des deux

    def test_tri_par_nom(self):
        self.trier("nom")
        self.assertEqual(self.titres(), ["Aventure", "Aventure", "Casse-tête", "Énigmes", "Jeu de course",
                                         "Jeu de rôle", "Plateformes", "Rallye", "Stratégie"])

    def test_une_ligne_de_jeu(self):
        jeu = DONNEES + ":101"
        self.assertEqual(self.propriete("jeu-titre-" + jeu, "text"), "Jeu de course")
        self.assertEqual((self.propriete("jeu-bibliotheque-" + jeu, "texte"),
                          self.propriete("jeu-bibliotheque-" + jeu, "etat")), ("Steam (Données)", "neutre"))
        self.assertEqual(self.propriete("jeu-taille-" + jeu, "text"), "60 Go")
        self.assertEqual(self.propriete("jeu-partie-" + jeu, "text"), "9 nov.")
        self.assertEqual(self.propriete("jeu-taille-emulateur:Console:Casse-tete", "text"), "Inconnue")

    def test_derniere_partie_jamais_et_inconnue(self):
        self.assertEqual(self.propriete("jeu-partie-" + DONNEES + ":303", "text"), "Jamais")          # Steam
        self.assertEqual(self.propriete("jeu-partie-lutris:jeu-de-role:/home/exemple/Jeux/jeu-de-role", "text"),
                         "Inconnue")
        self.assertEqual(self.propriete("jeu-partie-emulateur:Console:Rallye", "text"), "Inconnue")

    def test_doublons_filtre(self):
        self.clic("filtre-doublons")
        self.assertEqual(self.f.racines[0].property("filtreJeux"), "doublons")
        self.assertEqual(self.propriete("liste-jeux", "count"), 1)
        self.assertEqual(self.propriete("doublon-titre-Aventure", "text"), "Aventure")
        self.assertEqual(self.propriete("doublon-trop-Aventure", "text"), "38 Go en trop")
        copies = sorted(self.f.objets("doublon-copie-"), key=lambda o: o.property("y"))
        self.assertEqual([o.objectName() for o in copies],
                         ["doublon-copie-" + DONNEES + ":202", "doublon-copie-heroic:legendary:aventure"])
        copies = None
        self.assertEqual(self.propriete("doublon-copie-heroic:legendary:aventure", "text"), "Heroic (Epic) · 38 Go")
        self.assertEqual(self.propriete("doublon-copie-" + DONNEES + ":202", "text"), "Steam (Données) · 40 Go")

    def test_bibliotheque_absente_ecrite(self):
        absente = self.f.objet("absente-" + EXTERNE)
        self.assertIsNotNone(absente)
        self.assertTrue(absente.property("visible"))
        self.assertEqual(absente.property("text"), "Steam (Externe) : absente (disque débranché ?)")
        absente = None
        self.clic("filtre-" + EXTERNE)
        self.assertEqual(self.propriete("liste-jeux", "count"), 0)
        self.assertTrue(self.propriete("absente-" + EXTERNE, "visible"))
        self.clic("filtre-" + DONNEES)
        self.assertFalse(self.propriete("absente-" + EXTERNE, "visible"))

    def test_bibliotheques_tient_sur_un_ecran(self):
        """La page tient sur un écran ; une longue liste défile dans sa propre zone, de hauteur bornée."""
        self.tient_sur_un_ecran("bibliotheques")
        beaucoup = [dict(j, id=f"{j['id']}-{i}") for i in range(6) for j in self.f.pont.jeux["jeux"]]
        self.remplacer_jeux(jeux=beaucoup)
        self.assertEqual(self.propriete("liste-jeux", "count"), 54)
        self.tient_sur_un_ecran("bibliotheques")
        liste = self.f.objet("liste-jeux")
        self.assertGreater(liste.property("contentHeight"), liste.property("height"))
        self.assertTrue(liste.property("interactive"))
        liste = None


class LigneDeBibliotheque(Base):
    def test_ligne_de_bibliotheque_ouvre_le_filtre(self):
        """Depuis la vue d'ensemble : un clic sur une bibliothèque pose son filtre et ouvre l'onglet."""
        self.clic("ligne-bibliotheque-" + DONNEES)
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), "bibliotheques")
        self.assertEqual(self.f.racines[0].property("filtreJeux"), DONNEES)
        self.assertEqual(self.propriete("liste-jeux", "count"), 4)

    def test_ligne_des_doublons_ouvre_le_filtre_doublons(self):
        self.clic("ligne-doublons")
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), "bibliotheques")
        self.assertEqual(self.f.racines[0].property("filtreJeux"), "doublons")

    def test_ligne_des_bibliotheques_les_montre_toutes(self):
        self.f.racines[0].setProperty("filtreJeux", "doublons")
        self.clic("ligne-bibliotheques")
        self.assertEqual(self.f.racines[0].property("filtreJeux"), "")
        self.assertEqual(self.propriete("liste-jeux", "count"), 9)

    def test_badge_de_l_onglet_bibliotheques(self):
        """Attention s'il y a des erreurs ou une bibliothèque absente (la fixture a Steam (Externe) absente)."""
        modele = self.js("jeux-onglets", "modele.map(o => o.cle + ':' + (o.etat ?? ''))")
        self.assertIn("bibliotheques:attention", modele)
        self.remplacer_jeux(bibliotheques=[b for b in self.f.pont.jeux["bibliotheques"] if not b.get("absente")])
        self.assertIn("bibliotheques:", self.js("jeux-onglets", "modele.map(o => o.cle + ':' + (o.etat ?? ''))"))
        self.remplacer_jeux(erreurs=["Heroic : illisible (JSONDecodeError)"])
        self.assertIn("bibliotheques:attention",
                      self.js("jeux-onglets", "modele.map(o => o.cle + ':' + (o.etat ?? ''))"))


class Gels(Base):
    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("gels")

    def test_gels_liste_et_badges(self):
        self.assertEqual(self.propriete("gels-entete", "text"), "3 captures, dont 2 gels détectés automatiquement")
        lignes = sorted(self.f.objets("gel-date-"), key=lambda o: o.mapToScene(QPointF(0, 0)).y())
        self.assertEqual([o.property("text") for o in lignes],
                         ["21 sept. à 20 h 37", "18 sept. à 22 h 03", "3 sept. à 20 h 15"])
        lignes = None
        self.assertEqual(self.propriete("gel-jeu-0", "text"), "JeuDeCourse")
        self.assertEqual((self.propriete("gel-badge-0", "texte"), self.propriete("gel-badge-0", "etat")),
                         ("Automatique", "info"))
        self.assertEqual((self.propriete("gel-badge-1", "texte"), self.propriete("gel-badge-1", "etat")),
                         ("Manuelle", "neutre"))
        self.assertEqual(self.propriete("gel-declencheur-0", "text"),
                         "image figée depuis 8 s, processeur graphique à 100 %")
        self.assertFalse(self.propriete("gel-declencheur-1", "visible"))
        self.assertEqual(self.propriete("gel-taille-0", "text"), "0 Mo")
        self.assertTrue(self.propriete("gel-ouvrir-0", "flat"))
        self.assertEqual(self.propriete("gels-dossier", "text"), "Ouvrir le dossier")
        self.assertFalse(self.propriete("gels-dossier", "flat"))

    def ouvertures(self):
        return [a for a in self.appels if a[0] == "xdg-open"]

    def test_ouvrir_un_gel(self):
        self.clic("gel-ouvrir-0")
        self.assertEqual(self.ouvertures(), [["xdg-open", GELS + "/20260921-203718-GEL-JeuDeCourse.txt"]])

    def test_ouvrir_le_dossier_des_gels(self):
        self.clic("gels-dossier")
        self.assertEqual(self.ouvertures(), [["xdg-open", GELS]])

    def test_gels_vide(self):
        self.remplacer_jeux(gels={"dossier": GELS, "nombre": 0, "automatiques": 0, "dernier": None, "liste": []})
        vide = self.f.objet("gels-vide")
        self.assertIsNotNone(vide)
        self.assertTrue(vide.property("visible"))
        self.assertEqual(vide.property("texte"), "Aucun gel capturé.")
        vide = None
        self.assertEqual(self.f.objets("gel-date-"), [])

    def test_gels_tient_sur_un_ecran(self):
        self.tient_sur_un_ecran("gels")
        gels = self.f.pont.jeux["gels"]
        self.remplacer_jeux(gels=dict(gels, nombre=20, liste=[dict(gels["liste"][i % 3]) for i in range(20)]))
        self.tient_sur_un_ecran("gels")


class OngletsJeuxT7(Base):
    def test_onglet_garde_quand_on_revient_sur_la_page(self):
        self.ouvrir_onglet("gels")
        self.f.racines[0].setProperty("page", "accueil")
        attendre(150)
        nettoyer_emballages()
        self.f.racines[0].setProperty("page", "jeux")
        attendre(300)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), "gels")

    def test_onglet_inconnu_montre_la_vue_d_ensemble(self):
        self.f.racines[0].setProperty("ongletJeux", "nulle-part")
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), "ensemble")
        self.assertIsNotNone(self.f.objet("jeux-ensemble"))


# --- Task 8 : Ménage (shaders, Proton, préfixes seulement listés) et Mode jeu (réglages) ---

class OngletsDeLaPage(Base):
    def test_onglets_de_la_page_jeux(self):
        self.assertEqual(self.js("jeux-onglets", "modele.map(o => o.cle)"),
                         ["ensemble", "bibliotheques", "menage", "modejeu", "gels"])
        self.assertEqual(self.js("jeux-onglets", "modele.map(o => o.libelle)"),
                         ["Vue d'ensemble", "Bibliothèques", "Ménage", "Mode jeu", "Gels"])

    def etat_onglet(self, cle):
        return self.js("jeux-onglets", f"modele.find(o => o.cle === '{cle}').etat")

    def test_badge_de_l_onglet_mode_jeu(self):
        self.assertEqual(self.etat_onglet("modejeu"), "")                       # prêt
        attendu = [({"etat": "actif"}, "en_cours"), ({"etat": "interrompu"}, "attention"),
                   ({"etat": "arrete"}, "attention"), ({"etat": "desactive"}, ""),
                   ({"etat": "arrete", "reglages": dict.fromkeys(("actif", "ollama", "ne_pas_deranger", "profil",
                                                                   "taches"), False)}, "")]
        for champs, etat in attendu:
            with self.subTest(champs=champs):
                self.remplacer_modejeu(**champs)
                self.assertEqual(self.etat_onglet("modejeu"), etat)


class MenageDesJeux(Base):
    """Le ménage des jeux : les mêmes lignes, le même dialogue et la même empreinte que Stockage, limités aux
    recommandations des jeux ; les préfixes sont seulement listés."""

    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("menage")
        self.interne = self.f.objet("menage-entete")
        self.assertIsNotNone(self.interne)
        self.addCleanup(self.oublier)

    def oublier(self):
        self.interne = None
        nettoyer_emballages()

    def dialogue(self, code):
        e = QQmlExpression(QQmlEngine.contextForObject(self.interne), self.interne, code)
        valeur, _indefinie = e.evaluate()
        self.assertFalse(e.hasError(), e.error().toString())
        return valeur

    def menages(self):
        return [a for a in self.appels if a[:2] == ["centre-bazzite", "menage"]]

    def test_ids_menage_suivent_le_moteur(self):
        """UI-m5 / RF-m4 : la copie QML de menage.IDS_JEUX est liée au moteur."""
        self.assertEqual(self.js("page-jeux", "idsMenage"), list(menage.IDS_JEUX))

    def test_menage_jeux_seulement_shaders_et_proton(self):
        lignes = [o.objectName() for o in sorted(self.f.objets("menage-ligne-"), key=lambda o: o.property("y"))]
        self.assertEqual(lignes, ["menage-ligne-shaders", "menage-ligne-proton"])
        self.assertEqual(self.propriete("menage-liberer-shaders", "text"), "Libérer 1,2 Go…")

    def test_menage_jeux_dialogue_liste_complete_et_empreinte(self):
        elements = next(r for r in self.f.pont.stockage["recommandations"] if r["id"] == "shaders")["elements"]
        self.clic("menage-liberer-shaders")
        attendre(1500, lambda: self.dialogue("dialogue.opened"))
        self.assertTrue(self.dialogue("dialogue.opened"))
        self.assertEqual(self.dialogue("liste.count"), 2)
        self.assertEqual([self.dialogue(f"liste.model[{i}].libelle") for i in range(2)], [e["libelle"] for e in elements])
        self.assertEqual(self.dialogue("total.text"), "2 éléments · Total : 1,2 Go")
        self.assertEqual(self.dialogue("confirmer.text"), "Supprimer définitivement")
        self.assertEqual(self.menages(), [])
        self.dialogue("confirmer.clicked()")
        attendre(1500, lambda: not self.dialogue("dialogue.visible"))
        self.assertEqual(self.menages(),
                         [["centre-bazzite", "menage", "shaders", "--empreinte", menage.empreinte(elements)]])

    def test_prefixes_sans_bouton_de_suppression(self):
        self.assertEqual(self.propriete("prefixes-texte", "text"),
                         "Seulement listés : un préfixe peut servir à un raccourci non-Steam ou contenir des "
                         "sauvegardes. Health Hub ne les supprime jamais.")
        self.assertEqual(self.propriete("prefixes-total", "text"), "3 préfixes · 2,5 Go")
        self.assertEqual(self.propriete("liste-prefixes", "count"), 3)
        carte = self.f.objet("prefixes-carte")
        a_voir, dedans = [carte], []
        while a_voir:
            x = a_voir.pop()
            dedans.append(x.metaObject().className())
            a_voir.extend(x.childItems())
        carte = None
        self.assertFalse([c for c in dedans if c.startswith("BoutonDanger")])
        self.assertEqual(self.propriete("prefixe-libelle-0", "text"), "Raccourci non-Steam 3000000000")
        self.assertEqual(self.propriete("prefixe-bibliotheque-0", "texte"), "Steam (Home)")
        self.assertEqual(self.propriete("prefixe-taille-0", "text"), "1,5 Go")

        class PressePapiers:
            texte = None

            def setText(self, t):
                PressePapiers.texte = t
        self.f.pont._presse_papiers = PressePapiers()
        self.clic("prefixe-copier-0")
        self.assertEqual(PressePapiers.texte, "/home/exemple/.local/share/Steam/steamapps/compatdata/3000000000")
        self.assertTrue(self.propriete("prefixe-copie-0", "visible"))
        self.assertEqual([a for a in self.appels if a not in RELEVE], [])       # aucune commande

    def sans_recos(self, *ids):
        """Comme une relecture de stockage.json : ces recommandations ont disparu."""
        stock = dict(self.f.pont.stockage)
        stock["recommandations"] = [r for r in stock["recommandations"] if r["id"] not in ids]
        self.f.pont._stockage = stock
        self.f.pont.stockageChange.emit()
        attendre(150)
        nettoyer_emballages()

    def test_steam_illisible_dit_pourquoi_pas_de_shaders(self):
        """W5 : la liste des jeux installés est incertaine, aucun cache de shaders n'est proposé ; la page le dit, avec
        la phrase exacte de jeux.py (UI-m4), sans « Rien à libérer » ni coche à côté."""
        self.interne = None
        self.assertEqual(self.js("jeux-menage", "phraseSteamIncertain"), jeux.STEAM_NON_VERIFIABLE)
        self.assertFalse(self.propriete("menage-steam-illisible", "visible"))
        self.sans_recos("shaders", "proton")
        self.remplacer_jeux(erreurs=[jeux.STEAM_NON_VERIFIABLE],
                            prefixes={"elements": [], "octets": 0, "taille": "0 Mo"})
        self.assertTrue(self.propriete("menage-steam-illisible", "visible"))
        self.assertEqual(self.propriete("menage-steam-illisible", "text"),
                         "Steam : illisible (bibliothèques non vérifiables). Aucun cache de shaders n'est proposé "
                         "tant que la liste des jeux installés n'est pas lisible.")
        self.assertFalse(self.propriete("menage-jeux-vide", "visible"))

    def test_avertissement_steam_seulement_pour_la_phrase_exacte_et_sans_shaders(self):
        """UI-m4 : une autre erreur de Steam (la lecture des jeux) ne dit rien des shaders ; une reco « shaders »
        présente (stockage.json relevé à un autre moment) contredirait l'avertissement : il se tait."""
        self.remplacer_jeux(erreurs=["Steam : illisible (RuntimeError)"])
        self.assertFalse(self.propriete("menage-steam-illisible", "visible"))
        self.remplacer_jeux(erreurs=[jeux.STEAM_NON_VERIFIABLE])
        self.assertTrue(any(r["id"] == "shaders" for r in self.f.pont.stockage["recommandations"]))
        self.assertFalse(self.propriete("menage-steam-illisible", "visible"))

    def test_rien_a_liberer(self):
        stock = dict(self.f.pont.stockage)
        stock["recommandations"] = [r for r in stock["recommandations"] if r["id"] == "caches"]
        self.f.pont._stockage = stock
        self.f.pont.stockageChange.emit()
        self.remplacer_jeux(prefixes={"elements": [], "octets": 0, "taille": "0 Mo"})
        self.interne = None
        vide = self.f.objet("menage-jeux-vide")
        self.assertTrue(vide.property("visible"))
        self.assertEqual(vide.property("texte"), "Rien à libérer côté jeux.")
        vide = None
        self.assertFalse(self.propriete("prefixes-carte", "visible"))

    def test_menage_tient_sur_un_ecran(self):
        self.tient_sur_un_ecran("menage")
        prefixes = self.f.pont.jeux["prefixes"]
        beaucoup = [dict(prefixes["elements"][i % 3], cible=f"/x/{i}") for i in range(30)]
        self.remplacer_jeux(prefixes=dict(prefixes, elements=beaucoup))
        self.tient_sur_un_ecran("menage")
        liste = self.f.objet("liste-prefixes")
        self.assertGreater(liste.property("contentHeight"), liste.property("height"))
        liste = None


class ModeJeu(Base):
    CLES = list(modejeu.CLES)

    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("modejeu")

    def regler(self):
        return [a for a in self.appels if a[:2] == ["centre-bazzite", "modejeu"]]

    def basculer(self, cle):
        o = self.f.objet("reglage-" + cle)
        self.assertIsNotNone(o, cle)
        QMetaObject.invokeMethod(o, "toggle", Qt.DirectConnection)
        QMetaObject.invokeMethod(o, "toggled", Qt.DirectConnection)     # comme un clic de l'utilisateur
        o = None
        attendre(150)

    def test_en_tete_phrase_et_badge(self):
        self.assertEqual(self.propriete("modejeu-onglet-phrase", "text"),
                         "Mode jeu prêt : il s'active quand un jeu démarre.")
        self.assertEqual((self.propriete("modejeu-onglet-badge", "texte"),
                          self.propriete("modejeu-onglet-badge", "etat")), ("Prêt", "ok"))
        self.assertEqual(self.propriete("modejeu-onglet-derniere", "text"),
                         "Dernière partie : Jeu de course, le 9 nov. de 21 h 10 à 23 h 02.")
        self.assertEqual(self.propriete("modejeu-retours", "text"),
                         "Profil d'avant rétabli. Ne pas déranger levé. Ollama relancé.")
        self.assertFalse(self.propriete("modejeu-actions", "visible"))
        self.assertFalse(self.propriete("restaurer-modejeu", "visible"))

    def test_mode_jeu_reglages_coches_par_defaut(self):
        libelles = {"actif": "Mode jeu automatique", "ollama": "Arrêter Ollama et rendre la mémoire vidéo",
                    "ne_pas_deranger": "Activer Ne pas déranger",
                    "profil": "Passer en profil d'énergie « performance »",
                    "taches": "Mettre en pause les relevés de Health Hub"}
        for cle in self.CLES:
            with self.subTest(cle=cle):
                o = self.f.objet("reglage-" + cle)
                self.assertEqual((o.property("checked"), o.property("enabled"), o.property("text")),
                                 (True, True, libelles[cle]))
                self.assertIn("Switch", o.metaObject().className())
                o = None
        self.assertEqual(self.propriete("reglage-detail-ollama", "text"),
                         "Il est relancé à la fin seulement s'il tournait avant.")
        self.assertEqual(self.propriete("reglage-detail-taches", "text"),
                         "L'analyse de disque s'arrête de toute façon pendant un jeu.")
        self.assertFalse(self.propriete("reglage-detail-profil", "visible"))

    def test_mode_jeu_decocher_ollama(self):
        self.basculer("ollama")
        self.assertEqual(self.regler(), [["centre-bazzite", "modejeu", "regler", "ollama", "non"]])
        self.assertFalse(self.propriete("reglage-ollama", "checked"))       # le choix reste affiché
        self.remplacer_modejeu(reglages=dict.fromkeys(self.CLES, True))     # etat.json relu : il fait foi
        self.assertTrue(self.propriete("reglage-ollama", "checked"))

    def test_recocher_dit_oui(self):
        self.remplacer_modejeu(reglages={**dict.fromkeys(self.CLES, True), "profil": False})
        self.assertFalse(self.propriete("reglage-profil", "checked"))
        self.basculer("profil")
        self.assertEqual(self.regler(), [["centre-bazzite", "modejeu", "regler", "profil", "oui"]])

    def test_mode_jeu_actions_desactivees_si_coupe(self):
        self.remplacer_modejeu(etat="desactive", phrase="Mode jeu désactivé.",
                               reglages={**dict.fromkeys(self.CLES, True), "actif": False})
        self.assertEqual(self.propriete("reglage-actif", "enabled"), True)
        self.assertFalse(self.propriete("reglage-actif", "checked"))
        for cle in self.CLES[1:]:
            self.assertFalse(self.propriete("reglage-" + cle, "enabled"), cle)

    def test_mode_jeu_dit_ce_qui_est_detecte(self):
        self.assertEqual(self.propriete("modejeu-pied", "text"),
                         "Les changements valent dès la prochaine partie. Couper le mode jeu remet tout de suite le "
                         "bureau comme avant.")
        self.assertEqual(self.propriete("modejeu-detecte", "text"),
                         "Détecté : les jeux lancés par Steam, Heroic, Lutris ou umu.")

    def test_mode_jeu_interrompu_propose_de_restaurer(self):
        self.remplacer_modejeu(etat="interrompu", jeu="Jeu de course", depuis="2026-11-10T21:10:00",
                               phrase="Mode jeu interrompu : le bureau sera remis comme avant à la reprise du service.",
                               actions={})
        self.assertTrue(self.propriete("modejeu-interrompu", "visible"))
        self.assertEqual((self.propriete("modejeu-onglet-badge", "texte"),
                          self.propriete("modejeu-onglet-badge", "etat")), ("Interrompu", "attention"))
        bouton = self.f.objet("restaurer-modejeu")
        self.assertEqual((bouton.property("visible"), bouton.property("text")),
                         (True, "Remettre le bureau comme avant"))
        self.assertNotIn("BoutonPrincipal", bouton.metaObject().className())
        bouton = None
        self.assertEqual(self.propriete("modejeu-interrompu", "text"),
                         "Le service du mode jeu s'est arrêté pendant « Jeu de course » : Ollama n'a peut-être pas été "
                         "relancé.")
        self.clic("restaurer-modejeu")
        self.assertEqual(self.regler(), [["centre-bazzite", "modejeu", "restaurer"]])

    def test_restaurer_attend_sa_fin_puis_dit_la_phrase(self):
        """UI-m2 : pendant la remise, le bouton est grisé et le dit (un second clic ne relance rien) ; à la fin, la
        phrase de la CLI reste visible, même quand l'état n'est plus « interrompu »."""
        self.remplacer_modejeu(etat="interrompu", jeu="Jeu de course", actions={})
        self.assertFalse(self.propriete("restaurer-retour", "visible"))
        self.clic("restaurer-modejeu")
        self.assertEqual((self.propriete("restaurer-modejeu", "enabled"), self.propriete("restaurer-modejeu", "text")),
                         (False, "Remise du bureau en cours…"))
        self.clic("restaurer-modejeu")
        self.assertEqual(self.regler(), [["centre-bazzite", "modejeu", "restaurer"]])
        phrase = "Mode jeu : bureau remis comme avant."
        self.f.pont._taches = [{"id": "modejeu:restaurer", "statut": "fini", "detail": phrase, "pid": 4242}]
        self.f.pont._suivre_restauration()                   # comme une relecture du dossier des tâches
        attendre(150)
        self.assertEqual((self.propriete("restaurer-modejeu", "enabled"), self.propriete("restaurer-modejeu", "text")),
                         (True, "Remettre le bureau comme avant"))
        self.remplacer_modejeu(etat="pret", phrase="Mode jeu prêt : il s'active quand un jeu démarre.")
        self.assertFalse(self.propriete("restaurer-modejeu", "visible"))
        self.assertEqual((self.propriete("restaurer-retour", "visible"), self.propriete("restaurer-retour", "text")),
                         (True, phrase))

    def test_pied_dit_vrai_selon_l_etat(self):
        """UI-m8 : « remet tout de suite le bureau » seulement quand le service tourne."""
        base = "Les changements valent dès la prochaine partie."
        attendu = {"pret": base + " Couper le mode jeu remet tout de suite le bureau comme avant.",
                   "actif": base + " Couper le mode jeu remet tout de suite le bureau comme avant.",
                   "interrompu": base + " Couper le mode jeu remettra le bureau comme avant à la reprise du service.",
                   "arrete": base + " Le service du mode jeu ne tourne pas : rien ne change avant sa reprise.",
                   "desactive": base}
        for etat, texte in attendu.items():
            with self.subTest(etat=etat):
                self.remplacer_modejeu(etat=etat)
                self.assertEqual(self.propriete("modejeu-pied", "text"), texte)

    def test_menage_et_mode_jeu_tiennent_sur_un_ecran(self):
        self.tient_sur_un_ecran("modejeu")
        self.ouvrir_onglet("menage")
        self.tient_sur_un_ecran("menage")


class ModeJeuActif(Base):
    dossier = "jeux-actif"

    def test_ouverture_pendant_une_partie_sans_releve_lourd(self):
        """RF-m3 : un jeu tourne (etat.jeu, mode jeu actif) : l'ouverture ne relance que l'état."""
        self.assertEqual(self.appels, RELEVE[2:])

    def test_mode_jeu_actif_montre_les_actions(self):
        self.ouvrir_onglet("modejeu")
        self.assertEqual(self.propriete("modejeu-onglet-phrase", "text"), "Mode jeu actif depuis 21 h 10")
        self.assertEqual((self.propriete("modejeu-onglet-badge", "texte"),
                          self.propriete("modejeu-onglet-badge", "etat")), ("Actif", "info"))
        self.assertTrue(self.propriete("modejeu-actions", "visible"))
        self.assertEqual((self.propriete("action-statut-profil", "texte"), self.propriete("action-statut-profil", "etat")),
                         ("Échec", "echec"))
        self.assertEqual(self.propriete("action-detail-profil", "text"),
                         "Impossible : le service des profils d'énergie ne répond pas.")
        self.assertEqual(self.propriete("action-statut-ollama", "texte"), "Fait")
        self.assertEqual(self.propriete("action-nom-taches", "text"), "Relevés de Health Hub")
        avertissement = self.f.objet("modejeu-avertissement")
        self.assertEqual((avertissement.property("visible"), avertissement.property("text")),
                         (True, "Ollama répondait avec modele:7b : arrêté quand même, le jeu passe d'abord."))
        avertissement = None
        self.assertFalse(self.propriete("restaurer-modejeu", "visible"))
        self.tient_sur_un_ecran("modejeu")

    def test_statuts_ecrits_en_toutes_lettres(self):
        self.ouvrir_onglet("modejeu")
        actions = {"ollama": {"statut": "rien", "detail": "Ollama était déjà arrêté."},
                   "ne_pas_deranger": {"statut": "desactive", "detail": "Désactivé dans les réglages."},
                   "profil": {"statut": "fait", "detail": "ok"}, "taches": {"statut": "echec", "detail": "x"}}
        self.remplacer_modejeu(actions=actions)
        mots = {cle: (self.propriete("action-statut-" + cle, "texte"), self.propriete("action-statut-" + cle, "etat"))
                for cle in actions}
        self.assertEqual(mots, {"ollama": ("Rien à faire", "neutre"), "ne_pas_deranger": ("Désactivé", "neutre"),
                                "profil": ("Fait", "ok"), "taches": ("Échec", "echec")})


if __name__ == "__main__":
    unittest.main()
