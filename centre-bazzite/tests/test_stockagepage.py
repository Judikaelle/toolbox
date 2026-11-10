"""Page Stockage : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen), avec le dossier de fixture
« stockage » (etat.json + stockage.json). Aucune vraie commande : QProcess.startDetached est remplacé.
Task 19 : la page a des onglets, « Vue d'ensemble » (ouverte d'abord) puis un par volume ; seul l'onglet ouvert existe.
Un test qui regarde un volume ouvre d'abord son onglet, comme l'utilisateur."""
import gc
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QMetaObject, QProcess, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from centre_bazzite import menage
from tests.test_accueil import APP, Fenetre
from tests.test_menu import attendre


VOLUMES = ["/var/mnt/DONNEES", "/var", "/var/home", "/var/mnt/EXTERNE"]      # ordre des disques, puis de la position
# Objectif « un écran » (Task 19) : contentHeight de la vue d'ensemble ≤ hauteur visible + cette tolérance, soit la
# marge du bas de la page (Style.margePage) : seul ce vide peut passer sous le bord, jamais du contenu.
TOLERANCE_ECRAN = 24


def nettoyer_emballages():
    """Un onglet fermé détruit ses éléments : un emballage Python resté sur l'un d'eux fait planter PySide quand son
    adresse est réutilisée. On les ramasse avant de chercher dans l'onglet suivant."""
    gc.collect()
    APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


class Base(unittest.TestCase):
    dossier = "stockage"
    page = "stockage"

    def setUp(self):
        self.appels = []
        faux = mock.patch.object(QProcess, "startDetached",
                                 lambda prog, args: self.appels.append([prog] + list(args)) or (True, 1))
        faux.start()
        self.addCleanup(faux.stop)
        self.addCleanup(nettoyer_emballages)
        self.f = Fenetre(self.dossier, self.page)
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())
        self.assertTrue(self.f.racines, "Main.qml ne s'est pas chargé")

    def texte(self, nom):
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        return o.property("texte")

    def ouvrir_onglet(self, cle):
        """Clic sur l'onglet `cle` (« ensemble » ou le chemin d'un volume), comme l'utilisateur."""
        onglet = self.f.objet("onglet-" + cle)
        self.assertIsNotNone(onglet, cle)
        QMetaObject.invokeMethod(onglet, "clicked", Qt.DirectConnection)
        onglet = None
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), cle)


class PageStockage(Base):
    def test_la_page_relance_la_releve_a_l_ouverture(self):
        self.assertIn(["centre-bazzite", "stockage"], self.appels)

    def test_un_bloc_par_disque_physique(self):
        self.assertIsNotNone(self.f.objet("page-stockage"))
        self.assertEqual(self.texte("stockage-disque-titre-nvme0n1"), "Disque interne (NVMe 2 To)")
        self.assertEqual(self.texte("stockage-disque-titre-sda"), "Disque externe (SSD USB)")
        self.assertEqual(self.texte("stockage-disque-modele-nvme0n1"), "NVMe Exemple Z1 with Radiateur 2TB")
        self.assertEqual(self.texte("stockage-disque-modele-sda"), "USB Exemple SSD")

    def test_volumes_sous_leur_disque(self):
        sous_nvme = [o.property("nom") for o in self.f.objets("jauge-") if o.property("nom") in ("Données", "Système", "Home")]
        self.assertEqual(sorted(sous_nvme), ["Données", "Home", "Système"])
        self.assertEqual(len(self.f.objets("jauge-")), 4)
        externe = self.f.objet("jauge-/var/mnt/EXTERNE")
        self.assertEqual(externe.property("nom"), "Externe")
        self.assertEqual(externe.property("libreGo"), 150.0)
        self.assertEqual(externe.property("totalGo"), 3725.0)

    def test_chaque_volume_dans_le_bloc_de_son_disque(self):
        for chemin, disque in (("/var/mnt/DONNEES", "nvme0n1"), ("/var", "nvme0n1"), ("/var/home", "nvme0n1"),
                               ("/var/mnt/EXTERNE", "sda")):
            jauge = self.f.objet("jauge-" + chemin)
            parent = jauge
            while parent is not None and parent.objectName() != "stockage-disque-" + disque:
                parent = parent.parentItem()
            self.assertIsNotNone(parent, f"{chemin} n'est pas sous {disque}")

    def test_etats_ecrits_en_toutes_lettres(self):
        """Une ligne par volume : son état est écrit dans son badge, au bout de la ligne (Task 19)."""
        self.assertEqual(self.f.objet("jauge-/var").property("etat"), "attention")
        self.assertEqual(self.f.objet("jauge-/var/mnt/EXTERNE").property("etat"), "echec")
        self.assertEqual(self.f.objet("jauge-/var/mnt/DONNEES").property("etat"), "ok")
        attendu = {"/var/mnt/DONNEES": ("OK", "ok"), "/var/home": ("OK", "ok"),
                   "/var": ("Peu d'espace libre", "attention"), "/var/mnt/EXTERNE": ("Peu d'espace libre", "echec")}
        for chemin, (mot, etat) in attendu.items():
            badge = self.f.objet("stockage-etat-" + chemin)
            self.assertTrue(badge.property("visible"), chemin)
            self.assertEqual((badge.property("texte"), badge.property("etat")), (mot, etat), chemin)

    def test_une_ligne_par_volume(self):
        """La ligne d'un volume tient sur une ligne : la jauge n'écrit plus son alerte en dessous."""
        for chemin in VOLUMES:
            jauge = self.f.objet("jauge-" + chemin)
            self.assertFalse(jauge.property("badgeAlerte"), chemin)
            self.assertLess(self.f.objet("stockage-ligne-" + chemin).property("height"), 48, chemin)

    def test_systeme_de_fichiers_et_position_en_petit(self):
        """Dans l'en-tête de l'onglet du volume (Task 19)."""
        attendu = {"/var/mnt/DONNEES": "btrfs · début du disque", "/var": "ext4 · milieu du disque",
                   "/var/home": "ext4 · fin du disque", "/var/mnt/EXTERNE": "exfat"}
        for chemin, texte in attendu.items():
            self.ouvrir_onglet(chemin)
            self.assertEqual(self.f.objet("stockage-detail-" + chemin).property("text"), texte, chemin)

    def test_les_go_libres_pas_l_espace_utilise(self):
        self.assertEqual(self.f.objet("jauge-/var/mnt/DONNEES").property("libre"), "400 Go libres")
        self.assertEqual(self.f.objet("jauge-/var").property("libre"), "9,0 Go libres")

    def test_sourdines_de_stockage_dans_la_page_stockage(self):
        """Repliées en une ligne « N points en sourdine », dépliable (Task 19)."""
        resume = self.f.objet("stockage-sourdines")
        self.assertTrue(resume.property("visible"))
        self.assertEqual(self.f.objet("stockage-sourdines-bouton").property("text"), "1 point en sourdine")
        self.assertIsNotNone(self.f.objet("sourdine-menage:journal"))
        self.assertFalse(self.f.objet("sourdine-menage:journal").property("visible"))
        QMetaObject.invokeMethod(self.f.objet("stockage-sourdines-bouton"), "clicked", Qt.DirectConnection)
        attendre(100)
        self.assertTrue(self.f.objet("sourdine-menage:journal").property("visible"))
        self.assertIn("Le journal pèse 1,5 Go", self.f.objet("sourdine-titre-menage:journal").property("text"))
        bouton = self.f.objet("sourdine-bouton-menage:journal")
        QMetaObject.invokeMethod(bouton, "clicked", Qt.DirectConnection)
        attendre(100)
        self.assertIn(["centre-bazzite", "sans-sourdine", "menage:journal"], self.appels)

    def test_pas_de_ligne_de_sourdines_sans_sourdine(self):
        self.f.pont._etat = dict(self.f.pont.etat, points=[dict(p, en_sourdine=False) for p in self.f.pont.etat["points"]])
        self.f.pont.etatChange.emit()
        attendre(100)
        self.assertFalse(self.f.objet("stockage-sourdines").property("visible"))

    def test_pas_de_message_vide_quand_il_y_a_des_disques(self):
        self.assertFalse(self.f.objet("stockage-vide").property("visible"))


class AnalyseParVolume(Base):
    """Fixture « stockage » : Système analysé, Données en cours d'analyse (tâche analyse:/var/mnt/DONNEES), le reste jamais analysé.
    L'analyse d'un volume vit dans son onglet (Task 19) : chaque test l'ouvre d'abord."""

    def clic(self, nom):
        bouton = self.f.objet(nom)
        self.assertIsNotNone(bouton, nom)
        QMetaObject.invokeMethod(bouton, "clicked", Qt.DirectConnection)
        attendre(100)

    def test_date_et_duree_de_l_analyse(self):
        self.ouvrir_onglet("/var")
        self.assertEqual(self.f.objet("analyse-date-/var").property("text"), "Analysé le 9 nov. à 15 h 02 (4 min)")

    def test_categories_en_lignes_barre_relative_a_la_plus_grosse(self):
        self.ouvrir_onglet("/var")
        self.assertEqual(self.f.objet("analyse-categorie-nom-/var-0").property("text"), "Programmes & système")
        self.assertEqual(self.f.objet("analyse-categorie-taille-/var-0").property("text"), "18 Go")
        self.assertEqual(self.f.objet("analyse-categorie-barre-/var-0").property("valeur"), 1.0)
        petite = self.f.objet("analyse-categorie-barre-/var-1").property("valeur")
        self.assertTrue(0 < petite < 0.05, petite)

    def test_plus_gros_dossiers_avec_categorie_en_badge_neutre(self):
        self.ouvrir_onglet("/var")
        self.assertEqual(self.f.objet("analyse-dossier-nom-/var-0").property("text"), "lib")
        self.assertEqual(self.f.objet("analyse-dossier-taille-/var-0").property("text"), "19 Go")
        self.assertEqual(self.f.objet("analyse-dossier-nom-/var-2").property("text"), "cache")
        badge = self.f.objet("analyse-dossier-categorie-/var-2")
        self.assertEqual((badge.property("texte"), badge.property("etat")), ("Caches", "neutre"))

    def test_categorie_nulle_masque_le_badge(self):
        self.ouvrir_onglet("/var")
        self.assertFalse(self.f.objet("analyse-dossier-categorie-/var-0").property("visible"))

    def test_boutons_secondaires_analyser_et_carte_detaillee(self):
        self.ouvrir_onglet("/var")
        self.assertEqual(self.f.objet("analyse-analyser-/var").property("text"), "Analyser")
        self.assertEqual(self.f.objet("analyse-carte-/var").property("text"), "Carte détaillée")
        self.clic("analyse-analyser-/var")
        self.assertIn(["centre-bazzite", "analyser", "/var"], self.appels)
        self.clic("analyse-carte-/var")
        self.assertIn(["/home/bazzite/.local/share/linstat/linstat.py", "/var"], self.appels)

    def test_systeme_dit_en_mots_ce_que_l_analyse_ne_voit_pas(self):
        self.ouvrir_onglet("/var")
        self.assertIn("réservés à root", self.f.objet("analyse-note-/var").property("text"))
        self.ouvrir_onglet("/var/home")
        self.assertFalse(self.f.objet("analyse-note-/var/home").property("visible"))

    def test_volume_en_cours_d_analyse(self):
        self.ouvrir_onglet("/var/mnt/DONNEES")
        self.assertTrue(self.f.objet("analyse-progression-/var/mnt/DONNEES").property("visible"))
        self.assertTrue(self.f.objet("analyse-progression-/var/mnt/DONNEES").property("indeterminee"))
        self.assertEqual(self.f.objet("analyse-detail-/var/mnt/DONNEES").property("text"), "12 000 fichiers, 48 Go vus")
        self.assertFalse(self.f.objet("analyse-analyser-/var/mnt/DONNEES").property("enabled"))
        self.assertFalse(self.f.objet("analyse-vide-/var/mnt/DONNEES").property("visible"))

    def test_bouton_arreter_a_cote_de_la_barre_pendant_l_analyse(self):
        """Task 16b : « Arrêter » seulement pendant l'analyse, dans la même ligne que la barre et le détail."""
        self.ouvrir_onglet("/var/mnt/DONNEES")
        bouton = self.f.objet("analyse-arreter-/var/mnt/DONNEES")
        self.assertTrue(bouton.property("visible"))
        self.assertEqual(bouton.property("text"), "Arrêter")
        ligne = "analyse-en-cours-/var/mnt/DONNEES"
        self.assertEqual(bouton.parentItem().objectName(), ligne)
        self.assertEqual(self.f.objet("analyse-progression-/var/mnt/DONNEES").parentItem().parentItem().objectName(), ligne)
        bouton = None
        for chemin in ("/var", "/var/home", "/var/mnt/EXTERNE"):        # échec, interrompue, jamais analysé
            self.ouvrir_onglet(chemin)
            self.assertIsNotNone(self.f.objet("analyse-arreter-" + chemin), chemin)
            self.assertFalse(self.f.objet("analyse-arreter-" + chemin).property("visible"), chemin)

    def test_arreter_lance_la_cli(self):
        self.ouvrir_onglet("/var/mnt/DONNEES")
        self.clic("analyse-arreter-/var/mnt/DONNEES")
        self.assertIn(["centre-bazzite", "analyser", "--arreter"], self.appels)

    def test_volume_jamais_analyse(self):
        self.ouvrir_onglet("/var/mnt/EXTERNE")
        self.assertEqual(self.f.objet("analyse-vide-/var/mnt/EXTERNE").property("texte"), "Pas encore analysé.")
        self.assertTrue(self.f.objet("analyse-vide-/var/mnt/EXTERNE").property("visible"))
        self.assertFalse(self.f.objet("analyse-date-/var/mnt/EXTERNE").property("visible"))
        self.assertFalse(self.f.objet("analyse-progression-/var/mnt/EXTERNE").property("visible"))

    def test_bouton_analyser_de_la_ligne_vide(self):
        self.ouvrir_onglet("/var/mnt/EXTERNE")
        bouton = self.f.objet("analyse-vide-analyser-/var/mnt/EXTERNE")
        self.assertEqual(bouton.property("text"), "Analyser")
        self.clic("analyse-vide-analyser-/var/mnt/EXTERNE")
        self.assertIn(["centre-bazzite", "analyser", "/var/mnt/EXTERNE"], self.appels)

    def test_carte_detaillee_pour_un_volume_jamais_analyse(self):
        """Revue finale I4 : « Carte détaillée » dès que la commande LinStat est connue, analysé ou non."""
        self.ouvrir_onglet("/var/mnt/EXTERNE")
        bouton = self.f.objet("analyse-carte-/var/mnt/EXTERNE")
        self.assertTrue(bouton.property("visible"))
        self.assertFalse(self.f.objet("analyse-analyser-/var/mnt/EXTERNE").property("visible"))   # celui de la ligne vide suffit
        self.clic("analyse-carte-/var/mnt/EXTERNE")
        self.assertIn(["/home/bazzite/.local/share/linstat/linstat.py", "/var/mnt/EXTERNE"], self.appels)

    def test_pas_encore_analyse_tient_sur_une_ligne_compacte(self):
        self.ouvrir_onglet("/var/mnt/EXTERNE")
        self.assertLess(self.f.objet("analyse-vide-/var/mnt/EXTERNE").property("height"), 90)

    def test_analyse_interrompue_ecrite_avec_son_detail(self):
        self.ouvrir_onglet("/var/home")
        ligne = self.f.objet("analyse-probleme-/var/home")
        self.assertTrue(ligne.property("visible"))
        self.assertEqual(ligne.property("text"), "Un jeu a démarré : l'analyse reprendra plus tard.")
        self.assertTrue(self.f.objet("analyse-vide-/var/home").property("visible"))

    def test_analyse_en_echec_au_dessus_de_l_ancien_resultat(self):
        self.ouvrir_onglet("/var")
        ligne = self.f.objet("analyse-probleme-/var")
        self.assertTrue(ligne.property("visible"))
        self.assertEqual(ligne.property("text"), "LinStat n'a pas pu finir l'analyse de /var.")
        self.assertLess(ligne.property("y"), self.f.objet("analyse-resultat-/var").property("y"))
        self.assertTrue(self.f.objet("analyse-date-/var").property("visible"))
        couleur_echec = ligne.property("color")
        ligne = None
        self.ouvrir_onglet("/var/home")
        self.assertNotEqual(couleur_echec, self.f.objet("analyse-probleme-/var/home").property("color"))

    def test_pas_de_ligne_de_probleme_sans_echec(self):
        for chemin in ("/var/mnt/EXTERNE", "/var/mnt/DONNEES"):
            self.ouvrir_onglet(chemin)
            self.assertFalse(self.f.objet("analyse-probleme-" + chemin).property("visible"), chemin)

    def test_aucun_espace_utilise_dans_l_analyse(self):
        for chemin in VOLUMES:
            self.ouvrir_onglet(chemin)
            textes = " ".join(str(o.property("text") or "") for o in self.f.objets("analyse-"))
            self.assertIn(chemin, " ".join(o.objectName() for o in self.f.objets("analyse-")))
            self.assertNotIn("utilisé", textes, chemin)

    def test_pas_de_message_quand_linstat_est_la(self):
        self.assertFalse(self.f.objet("stockage-sans-linstat").property("visible"))
        self.ouvrir_onglet("/var")
        self.assertFalse(self.f.objet("volume-sans-linstat-/var").property("visible"))

    def test_categories_et_dossiers_en_deux_colonnes_a_1100(self):
        """Task 19 : à 1100 px de fenêtre, les catégories et les plus gros dossiers côte à côte."""
        self.ouvrir_onglet("/var")
        self.assertTrue(self.f.objet("stockage-analyse-/var").property("deuxColonnes"))
        categorie = self.f.objet("analyse-categorie-nom-/var-0")
        dossier = self.f.objet("analyse-dossier-nom-/var-0")
        page = self.f.objet("page-stockage")
        x_categorie = categorie.mapToItem(page, 0, 0).x()
        x_dossier = dossier.mapToItem(page, 0, 0).x()
        self.assertGreater(x_dossier, x_categorie + 200)
        self.assertAlmostEqual(categorie.mapToItem(page, 0, 0).y(), dossier.mapToItem(page, 0, 0).y(), delta=2)

    def test_empilees_quand_c_est_etroit(self):
        self.f.racines[0].setProperty("width", 800)
        attendre(300)
        self.ouvrir_onglet("/var")
        self.assertFalse(self.f.objet("stockage-analyse-/var").property("deuxColonnes"))


class AnalyseSansLinstat(Base):
    dossier = "stockage-sans-linstat"

    def test_message_et_pas_de_boutons(self):
        m = self.f.objet("stockage-sans-linstat")
        self.assertTrue(m.property("visible"))
        self.assertEqual(m.property("text"), "LinStat n'est pas installé : seul l'espace libre est affiché.")
        m = None
        self.assertEqual(len(self.f.objets("jauge-")), 4)
        self.ouvrir_onglet("/var")
        self.assertFalse(self.f.objet("analyse-analyser-/var").property("visible"))
        self.assertFalse(self.f.objet("analyse-vide-/var").property("visible"))
        self.assertFalse(self.f.objet("analyse-carte-/var").property("visible"))       # pas de commande connue
        # L'onglet du volume garde l'espace libre et dit pourquoi il n'y a pas d'analyse.
        self.assertEqual(self.f.objet("volume-libre-/var").property("text"), "9,0 Go libres sur 70 Go")
        message = self.f.objet("volume-sans-linstat-/var")
        self.assertTrue(message.property("visible"))
        self.assertEqual(message.property("text"), "LinStat n'est pas installé : seul l'espace libre est affiché.")


class AnalyseLinstatChange(Base):
    """Revue finale I4 (spec §6.2) : LinStat installé mais son API a changé (moteur faux, commande connue) : la page
    montre l'espace libre et « Carte détaillée », et dit pourquoi l'analyse est en pause."""
    dossier = "stockage-linstat-change"
    COMMANDE = "/home/bazzite/.local/share/linstat/linstat.py"

    def clic(self, nom):
        QMetaObject.invokeMethod(self.f.objet(nom), "clicked", Qt.DirectConnection)
        attendre(100)

    def test_message_selon_la_cause(self):
        m = self.f.objet("stockage-sans-linstat")
        self.assertTrue(m.property("visible"))
        self.assertEqual(m.property("text"),
                         "LinStat ne répond plus comme prévu : l'analyse est en pause, la carte détaillée reste disponible.")

    def test_carte_detaillee_pour_chaque_volume(self):
        for chemin in ("/var", "/var/home", "/var/mnt/EXTERNE", "/var/mnt/DONNEES"):
            self.ouvrir_onglet(chemin)
            self.assertTrue(self.f.objet("analyse-carte-" + chemin).property("visible"), chemin)
        self.clic("analyse-carte-/var/mnt/DONNEES")
        self.assertIn([self.COMMANDE, "/var/mnt/DONNEES"], self.appels)

    def test_rien_de_l_analyse_sans_moteur(self):
        self.assertEqual(len(self.f.objets("jauge-")), 4)
        for chemin in ("/var", "/var/mnt/EXTERNE"):
            self.ouvrir_onglet(chemin)
            for nom in ("analyse-analyser-", "analyse-vide-", "analyse-date-", "analyse-probleme-", "analyse-en-cours-"):
                self.assertFalse(self.f.objet(nom + chemin).property("visible"), nom + chemin)
            self.assertTrue(self.f.objet("volume-sans-linstat-" + chemin).property("visible"), chemin)


class Menage(Base):
    """Fixture « stockage » : six recommandations (5 caches, 1 corbeille, 14 téléchargements, 1 runtime et sa commande
    GL à copier, 1 Proton, le journal). Le dialogue n'est lu qu'en JavaScript, dans la portée de MenageSection.qml :
    un emballage Python d'un élément du dialogue fait planter PySide une fois l'objet détruit.
    Task 19 : le ménage vit dans la vue d'ensemble, une ligne par recommandation ; le dialogue est le même."""
    IDS = ["caches", "corbeille", "telechargements", "runtimes", "proton", "journal"]

    def setUp(self):
        super().setUp()
        self.addCleanup(self.nettoyer)
        # Les id de MenageSection.qml vivent dans le contexte de ses éléments internes, pas dans celui de sa racine
        # (qui est le contexte de StockagePage) : on évalue dans le contexte du titre de la section.
        self.interne = self.f.objet("menage-entete")
        self.assertIsNotNone(self.interne)

    def nettoyer(self):
        self.interne = None
        gc.collect()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()

    def js(self, code):
        e = QQmlExpression(QQmlEngine.contextForObject(self.interne), self.interne, code)
        valeur, _indefinie = e.evaluate()      # le second : « la valeur est undefined » (un appel sans retour)
        self.assertFalse(e.hasError(), e.error().toString())
        return valeur

    def clic(self, nom):
        bouton = self.f.objet(nom)
        self.assertIsNotNone(bouton, nom)
        QMetaObject.invokeMethod(bouton, "clicked", Qt.DirectConnection)
        attendre(100)

    def menages(self):
        return [a for a in self.appels if a[:2] == ["centre-bazzite", "menage"]]

    def ouvrir(self, id_):
        self.clic("menage-liberer-" + id_)
        attendre(1500, lambda: self.js("dialogue.opened"))
        self.assertTrue(self.js("dialogue.opened"))

    def test_dans_la_vue_d_ensemble(self):
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), "ensemble")
        parent = self.f.objet("menage-section")
        while parent is not None and parent.objectName() != "stockage-ensemble":
            parent = parent.parentItem()
        self.assertIsNotNone(parent)

    def test_une_ligne_par_recommandation_dans_l_ordre(self):
        lignes = [o.objectName() for o in sorted(self.f.objets("menage-ligne-"), key=lambda o: o.property("y"))]
        self.assertEqual(lignes, ["menage-ligne-" + i for i in self.IDS])
        self.assertEqual(self.f.objet("menage-titre-caches").property("text"), "Caches régénérables")
        # Combien ça libère : dans le bouton « Libérer … », ou à côté du titre quand il n'y en a pas (le journal).
        self.assertIn("7,2 Go", self.f.objet("menage-liberer-caches").property("text"))
        self.assertTrue(self.f.objet("menage-liberer-caches").property("visible"))
        self.assertFalse(self.f.objet("menage-taille-caches").property("visible"))
        taille = self.f.objet("menage-taille-journal")
        self.assertEqual((taille.property("text"), taille.property("visible")), ("1,0 Go", True))
        self.assertEqual(self.f.objet("menage-explication-caches").property("text"),
                         "Supprimés définitivement : les programmes les recréent au besoin.")

    def test_bouton_secondaire_liberer(self):
        bouton = self.f.objet("menage-liberer-caches")
        self.assertEqual(bouton.property("text"), "Libérer 7,2 Go…")
        self.assertNotIn("BoutonPrincipal", bouton.metaObject().className())
        self.assertEqual(self.f.objet("menage-liberer-telechargements").property("text"), "Libérer 18 Go…")

    def remplacer(self, id_, **champs):
        """Remplace une recommandation dans le stockage du pont, comme une relecture de stockage.json."""
        stock = dict(self.f.pont.stockage)
        stock["recommandations"] = [dict(r, **champs) if r["id"] == id_ else dict(r) for r in stock["recommandations"]]
        self.f.pont._stockage = stock
        self.f.pont.stockageChange.emit()
        attendre(100)

    def test_dialogue_liste_complete_defilante(self):
        """Tout ce qui part est montré (37 éléments, comme le vrai ménage du 9 novembre), dans une liste défilante de
        hauteur bornée, avec le total."""
        elements = [{"cible": f"/h/T/f{i:02d}.zip", "libelle": f"f{i:02d}.zip", "octets": 1024 ** 2 * (40 - i),
                     "taille": f"{40 - i} Mo"} for i in range(37)]
        self.remplacer("telechargements", elements=elements, taille="666 Mo")
        self.ouvrir("telechargements")
        self.assertEqual(self.js("dialogue.title"), "Téléchargements de plus de 90 jours")
        self.assertEqual(self.js("liste.count"), 37)
        self.assertLess(self.js("liste.height"), self.js("liste.contentHeight"))       # elle défile
        self.js("liste.positionViewAtEnd()")
        attendre(100)
        self.assertEqual(self.js("liste.itemAtIndex(36).modelData.libelle"), "f36.zip")
        self.assertEqual(self.js("liste.itemAtIndex(36).modelData.taille"), "4 Mo")
        self.assertEqual(self.js("total.text"), "37 éléments · Total : 666 Mo")
        self.assertEqual(self.js("confirmer.text"), "Envoyer à la corbeille")

    def test_dialogue_ouvert_depuis_la_vue_d_ensemble_avec_toute_la_liste(self):
        """Task 19 : « Libérer… » d'une ligne compacte ouvre le même dialogue, avec tous les éléments de la recommandation."""
        elements = next(r for r in self.f.pont.stockage["recommandations"] if r["id"] == "telechargements")["elements"]
        self.assertEqual(len(elements), 14)
        self.ouvrir("telechargements")
        self.assertEqual(self.js("liste.count"), 14)
        self.assertEqual([self.js(f"liste.model[{i}].libelle") for i in range(14)], [e["libelle"] for e in elements])
        self.assertEqual(self.js("total.text"), "14 éléments · Total : 18 Go")

    def test_petite_liste_sans_defilement(self):
        self.ouvrir("caches")
        self.assertEqual(self.js("liste.count"), 5)
        self.assertEqual(self.js("total.text"), "5 éléments · Total : 7,2 Go")
        self.assertEqual(self.js("liste.itemAtIndex(0).modelData.libelle"), "npm")
        self.assertGreaterEqual(self.js("liste.height") + 1, self.js("liste.contentHeight"))

    def test_libelle_en_texte_brut(self):
        self.remplacer("caches", elements=[{"cible": "/x", "libelle": "<b>gras</b>", "octets": 1, "taille": "0 Mo"}])
        self.ouvrir("caches")
        self.assertEqual(self.js("liste.itemAtIndex(0).libelle.textFormat"), 0)        # Text.PlainText

    def test_sauvegardes_laissees_de_cote_dites_sur_la_carte(self):
        remarque = self.f.objet("menage-remarque-telechargements")
        self.assertTrue(remarque.property("visible"))
        self.assertEqual(remarque.property("text"), "2 sauvegardes de jeux probables sont laissées de côté.")
        self.assertFalse(self.f.objet("menage-remarque-caches").property("visible"))

    def test_bouton_de_confirmation_selon_le_mode(self):
        attendu = {"caches": "Supprimer définitivement", "corbeille": "Vider la corbeille définitivement",
                   "telechargements": "Envoyer à la corbeille", "runtimes": "Désinstaller",
                   "proton": "Supprimer définitivement"}
        for id_, texte in attendu.items():
            self.assertEqual(self.js(f"section.libelleConfirmer(section.reco('{id_}'))"), texte, id_)

    def test_confirmation_par_un_bouton_danger(self):
        self.ouvrir("corbeille")
        self.assertEqual(self.js("confirmer.text"), "Vider la corbeille définitivement")
        self.assertTrue(self.js("confirmer.flat && confirmer.couleur !== undefined"))     # BoutonDanger
        self.assertEqual(self.js("annuler.text"), "Annuler")

    def test_confirmer_lance_le_menage(self):
        """La commande porte l'empreinte des éléments montrés dans le dialogue (cible, libellé, taille)."""
        elements = next(r for r in self.f.pont.stockage["recommandations"] if r["id"] == "caches")["elements"]
        self.ouvrir("caches")
        self.assertEqual(self.menages(), [])
        self.js("confirmer.clicked()")
        attendre(1500, lambda: not self.js("dialogue.visible"))
        self.assertEqual(self.menages(), [["centre-bazzite", "menage", "caches", "--empreinte", menage.empreinte(elements)]])
        self.assertFalse(self.js("dialogue.visible"))

    def test_annuler_ne_lance_rien(self):
        self.ouvrir("proton")
        self.js("annuler.clicked()")
        attendre(1500, lambda: not self.js("dialogue.visible"))
        self.assertEqual(self.menages(), [])

    def test_liste_changee_pendant_le_dialogue(self):
        """stockage.json réécrit pendant que le dialogue est ouvert, avec une autre liste : le dialogue se ferme, rien
        ne part, et la page le dit."""
        self.ouvrir("caches")
        stock = dict(self.f.pont.stockage)
        recos = [dict(r) for r in stock["recommandations"]]
        recos[0]["elements"] = recos[0]["elements"][:1]
        self.f.pont._stockage = dict(stock, recommandations=recos)
        self.f.pont.stockageChange.emit()
        attendre(1500, lambda: not self.js("dialogue.visible"))
        self.assertFalse(self.js("dialogue.visible"))
        self.js("section.confirmer()")
        self.assertEqual(self.menages(), [])
        self.assertTrue(self.js("avertissement.visible"))
        self.assertIn("La liste a changé", self.js("avertissement.text"))

    def test_un_seul_element_au_singulier(self):
        self.ouvrir("corbeille")
        self.assertEqual(self.js("total.text"), "1 élément · Total : 3 Mo")

    def test_meme_cible_autre_taille_ferme_le_dialogue(self):
        """Ruling V60 : la liste montrée, c'est aussi les libellés et les tailles."""
        self.ouvrir("corbeille")
        stock = dict(self.f.pont.stockage)
        recos = [dict(r) for r in stock["recommandations"]]
        corbeille = next(r for r in recos if r["id"] == "corbeille")
        corbeille["elements"] = [dict(corbeille["elements"][0], octets=corbeille["elements"][0]["octets"] * 2)]
        self.f.pont._stockage = dict(stock, recommandations=recos)
        self.f.pont.stockageChange.emit()
        attendre(1500, lambda: not self.js("dialogue.visible"))
        self.assertFalse(self.js("dialogue.visible"))
        self.js("section.confirmer()")
        self.assertEqual(self.menages(), [])

    def test_relecture_identique_ne_ferme_pas_le_dialogue(self):
        self.ouvrir("caches")
        stock = dict(self.f.pont.stockage)
        self.f.pont._stockage = dict(stock, genere="2026-11-09T17:00:00")
        self.f.pont.stockageChange.emit()
        attendre(300)
        self.assertTrue(self.js("dialogue.visible"))

    def test_journal_copier_la_commande(self):
        class PressePapiers:
            texte = None

            def setText(self, texte):
                self.texte = texte
        faux = PressePapiers()
        self.f.pont._presse_papiers = faux
        self.assertFalse(self.f.objet("menage-liberer-journal").property("visible"))
        self.assertFalse(self.f.objet("menage-copie-journal").property("visible"))
        self.assertEqual(self.f.objet("menage-copier-journal").property("text"), "Copier la commande")
        self.clic("menage-copier-journal")
        self.assertEqual(faux.texte, "sudo journalctl --vacuum-size=500M")
        self.assertTrue(self.f.objet("menage-copie-journal").property("visible"))
        self.assertEqual(self.f.objet("menage-copie-journal").property("text"), "Commande copiée.")
        self.assertEqual(self.menages(), [])

    def test_runtimes_commande_gl_a_copier(self):
        self.assertIn("flatpak uninstall runtime/org.freedesktop.Platform.GL.nvidia-580-95-05",
                      self.f.objet("menage-a-copier-runtimes").property("text"))
        self.assertTrue(self.f.objet("menage-copier-runtimes").property("visible"))
        self.assertTrue(self.f.objet("menage-liberer-runtimes").property("visible"))
        self.assertFalse(self.f.objet("menage-copier-caches").property("visible"))
        self.assertFalse(self.f.objet("menage-a-copier-caches").property("visible"))

    def test_menage_en_cours_desactive_le_bouton(self):
        self.f.pont._taches = [{"id": "menage:caches", "type": "menage", "titre": "Caches régénérables",
                                "statut": "en_cours", "progression": -1, "detail": "", "journal": [], "etapes": []}]
        self.f.pont.tachesChange.emit()
        attendre(100)
        self.assertFalse(self.f.objet("menage-liberer-caches").property("enabled"))
        self.assertTrue(self.f.objet("menage-liberer-proton").property("enabled"))


class MenageAvecLesJeux(Base):
    """Task 8, non-régression : MenageSection sans `ids` montre toutes les recommandations, celles des jeux comprises."""
    dossier = "jeux"

    def test_la_vue_d_ensemble_de_stockage_montre_toujours_tout(self):
        lignes = [o.objectName() for o in sorted(self.f.objets("menage-ligne-"), key=lambda o: o.property("y"))]
        self.assertEqual(lignes, ["menage-ligne-caches", "menage-ligne-shaders", "menage-ligne-proton"])


class MenageAbsent(Base):
    dossier = "stockage-sans-linstat"

    def test_pas_de_section_sans_recommandation(self):
        self.assertFalse(self.f.objet("menage-section").property("visible"))


class PageStockageSansReleve(Base):
    dossier = "accueil"          # etat.json sans stockage.json

    def test_pas_encore_de_releve(self):
        self.assertTrue(self.f.objet("stockage-vide").property("visible"))
        self.assertEqual(self.f.objets("jauge-"), [])
        self.assertEqual([o.objectName() for o in self.f.objets("onglet-")], ["onglet-ensemble"])


class Onglets(Base):
    """Task 19 : « Vue d'ensemble » puis un onglet par volume, dans l'ordre des disques puis de la position."""

    def onglets(self):
        boutons = sorted(self.f.objets("onglet-"), key=lambda o: o.property("x"))
        return [(o.objectName()[len("onglet-"):], o.property("text")) for o in boutons]

    def fenetre(self):
        return self.f.racines[0]

    def test_ensemble_puis_un_onglet_par_volume(self):
        self.assertEqual(self.onglets(), [("ensemble", "Vue d'ensemble"), ("/var/mnt/DONNEES", "Données"), ("/var", "Système"),
                                          ("/var/home", "Home"), ("/var/mnt/EXTERNE", "Externe")])
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), "ensemble")
        self.assertEqual(self.fenetre().property("ongletStockage"), "ensemble")
        self.assertIsNotNone(self.f.objet("stockage-ensemble"))

    def test_etat_de_chaque_onglet(self):
        """L'état de la jauge du volume (échec, attention) ; « en cours » si une analyse y tourne ; rien sinon."""
        etats = {cle: self.f.objet("onglet-" + cle).property("etat") for cle, _ in self.onglets()}
        self.assertEqual(etats, {"ensemble": "", "/var/mnt/DONNEES": "en_cours", "/var": "attention", "/var/home": "",
                                 "/var/mnt/EXTERNE": "echec"})
        self.assertEqual(self.f.objet("onglet-/var").property("motEtat"), "Attention")
        self.assertEqual(self.f.objet("onglet-/var/mnt/DONNEES").property("motEtat"), "En cours")
        self.assertTrue(self.f.objet("point-onglet-/var").property("visible"))
        self.assertFalse(self.f.objet("point-onglet-/var/home").property("visible"))

    def test_nom_accessible(self):
        self.assertEqual(self.f.objet("onglet-/var").property("nomAccessible"), "Système, onglet 3 sur 5")
        self.assertEqual(self.f.objet("onglet-ensemble").property("nomAccessible"), "Vue d'ensemble, onglet 1 sur 5")

    def test_onglet_actif_souligne_en_accent(self):
        self.assertTrue(self.f.objet("filet-onglet-ensemble").property("visible"))
        self.assertFalse(self.f.objet("filet-onglet-/var").property("visible"))
        self.ouvrir_onglet("/var")
        self.assertTrue(self.f.objet("filet-onglet-/var").property("visible"))
        self.assertFalse(self.f.objet("filet-onglet-ensemble").property("visible"))

    def test_clic_sur_une_ligne_de_volume_ouvre_son_onglet(self):
        QMetaObject.invokeMethod(self.f.objet("stockage-ligne-/var/mnt/DONNEES"), "clicked", Qt.DirectConnection)
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.fenetre().property("ongletStockage"), "/var/mnt/DONNEES")
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), "/var/mnt/DONNEES")
        self.assertIsNotNone(self.f.objet("stockage-volume-/var/mnt/DONNEES"))
        self.assertIsNone(self.f.objet("stockage-ensemble"))

    def test_fleches_du_clavier(self):
        self.fenetre().requestActivate()
        attendre(200)
        self.f.objet("stockage-onglets").forceActiveFocus()
        attendre(50)
        QTest.keyClick(self.fenetre(), Qt.Key_Right)
        attendre(150)
        self.assertEqual(self.fenetre().property("ongletStockage"), "/var/mnt/DONNEES")
        QTest.keyClick(self.fenetre(), Qt.Key_Right)
        attendre(150)
        self.assertEqual(self.fenetre().property("ongletStockage"), "/var")
        QTest.keyClick(self.fenetre(), Qt.Key_Left)
        QTest.keyClick(self.fenetre(), Qt.Key_Left)
        QTest.keyClick(self.fenetre(), Qt.Key_Left)          # déjà au premier : on y reste
        attendre(150)
        self.assertEqual(self.fenetre().property("ongletStockage"), "ensemble")

    def test_la_vue_d_ensemble_ne_contient_aucune_analyse(self):
        self.assertEqual(self.f.objets("stockage-analyse-"), [])
        self.assertEqual(self.f.objets("analyse-"), [])
        self.assertEqual(len(self.f.objets("stockage-ligne-")), 4)

    def test_l_onglet_d_un_volume_ne_contient_que_son_analyse(self):
        self.ouvrir_onglet("/var")
        self.assertEqual([o.objectName() for o in self.f.objets("stockage-analyse-")], ["stockage-analyse-/var"])
        self.assertEqual({o.objectName().rsplit("-", 1)[0] for o in self.f.objets("analyse-categorie-nom-")},
                         {"analyse-categorie-nom-/var"})
        for nom in ("stockage-ensemble", "menage-section", "optimiser-section", "a-regarder-stockage", "stockage-sourdines"):
            self.assertIsNone(self.f.objet(nom), nom)
        self.assertEqual(self.f.objets("jauge-"), [])
        self.assertEqual(self.f.objets("stockage-ligne-"), [])

    def test_en_tete_du_volume(self):
        self.ouvrir_onglet("/var/mnt/DONNEES")
        self.assertEqual(self.f.objet("volume-nom-/var/mnt/DONNEES").property("text"), "Données")
        self.assertEqual(self.texte("volume-disque-/var/mnt/DONNEES"), "Disque interne (NVMe 2 To)")
        self.assertEqual(self.f.objet("volume-libre-/var/mnt/DONNEES").property("text"), "400 Go libres sur 886 Go")
        self.assertAlmostEqual(self.f.objet("volume-barre-/var/mnt/DONNEES").property("valeur"), 400 / 886, places=3)
        badge = self.f.objet("volume-etat-/var/mnt/DONNEES")
        self.assertEqual((badge.property("texte"), badge.property("etat")), ("OK", "ok"))
        badge = None
        self.ouvrir_onglet("/var/mnt/EXTERNE")
        badge = self.f.objet("volume-etat-/var/mnt/EXTERNE")
        self.assertEqual((badge.property("texte"), badge.property("etat")), ("Peu d'espace libre", "echec"))

    def test_onglet_garde_quand_on_revient_sur_la_page(self):
        self.ouvrir_onglet("/var")
        self.fenetre().setProperty("page", "accueil")
        attendre(200)
        nettoyer_emballages()
        self.assertIsNone(self.f.objet("page-stockage"))
        self.fenetre().setProperty("page", "stockage")
        attendre(300)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), "/var")
        self.assertIsNotNone(self.f.objet("stockage-volume-/var"))

    def test_externe_debranche_pas_d_onglet_externe(self):
        """Un onglet de volume qui disparaît ramène à la vue d'ensemble, et l'onglet gardé aussi."""
        self.ouvrir_onglet("/var/mnt/EXTERNE")
        stock = dict(self.f.pont.stockage)
        stock["disques"] = [d for d in stock["disques"] if d["id"] != "sda"]
        self.f.pont._stockage = stock
        self.f.pont.stockageChange.emit()
        attendre(200)
        nettoyer_emballages()
        self.assertEqual([c for c, _ in self.onglets()], ["ensemble", "/var/mnt/DONNEES", "/var", "/var/home"])
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), "ensemble")
        self.assertEqual(self.fenetre().property("ongletStockage"), "ensemble")
        self.assertIsNotNone(self.f.objet("stockage-ensemble"))

    def test_l_essentiel_sans_defiler_meme_avec_six_recommandations(self):
        """La fixture « stockage » est le pire cas (le premier passage du 9 novembre : 6 recommandations à la fois) : la page
        défile, mais les disques et le début du ménage (son en-tête, sa première ligne et son bouton) restent dans le
        premier écran, à 1100×720."""
        self.assertEqual((self.fenetre().property("width"), self.fenetre().property("height")), (1100, 720))
        page = self.f.objet("page-stockage")
        hauteur = page.property("height")
        for nom in ("stockage-disques", "menage-entete", "menage-ligne-caches", "menage-liberer-caches"):
            o = self.f.objet(nom)
            self.assertLessEqual(o.mapToItem(page, 0, o.property("height")).y(), hauteur, nom)

    def test_ensemble_en_deux_colonnes_a_1100(self):
        """Les disques sur toute la largeur, puis le ménage et l'optimisation côte à côte."""
        self.assertTrue(self.f.objet("stockage-ensemble").property("deuxColonnes"))
        page = self.f.objet("page-stockage")
        disques = self.f.objet("stockage-disques")
        menage = self.f.objet("menage-section").mapToItem(page, 0, 0)
        optimiser = self.f.objet("optimiser-section").mapToItem(page, 0, 0)
        self.assertGreater(optimiser.x(), menage.x() + 200)
        self.assertAlmostEqual(optimiser.y(), menage.y(), delta=2)
        self.assertGreaterEqual(menage.y(), disques.mapToItem(page, 0, disques.property("height")).y())

    def test_ensemble_empile_quand_c_est_etroit(self):
        self.fenetre().setProperty("width", 800)
        attendre(300)
        self.assertFalse(self.f.objet("stockage-ensemble").property("deuxColonnes"))


class UnEcranAvecLEtatComplet(Base):
    """Objectif de la Task 19 : à 1100×720, la vue d'ensemble tient sur un écran avec un état complet (fixture
    « complet » : 4 volumes analysés, le ménage déjà fait, les options A à D, 1 sourdine). Tolérance : TOLERANCE_ECRAN."""
    dossier = "complet"

    def test_vue_d_ensemble_tient_sur_un_ecran_a_1100x720(self):
        fenetre = self.f.racines[0]
        self.assertEqual((fenetre.property("width"), fenetre.property("height")), (1100, 720))
        page = self.f.objet("page-stockage")
        self.assertLessEqual(page.property("contentHeight"), page.property("height") + TOLERANCE_ECRAN)

    def test_chaque_onglet_de_volume_tient_sur_un_ecran(self):
        """Home a 14 catégories, le plus long des quatre volumes."""
        for chemin in VOLUMES:
            self.ouvrir_onglet(chemin)
            if chemin == "/var/home":
                self.assertEqual(len(self.f.objets("analyse-categorie-nom-/var/home-")), 14)
            page = self.f.objet("page-stockage")
            self.assertLessEqual(page.property("contentHeight"), page.property("height") + TOLERANCE_ECRAN, chemin)
            page = None


class OngletInconnu(Base):
    def test_onglet_inconnu_montre_la_vue_d_ensemble(self):
        self.f.racines[0].setProperty("ongletStockage", "/nulle/part")
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("stockage-onglets").property("courant"), "ensemble")
        self.assertIsNotNone(self.f.objet("stockage-ensemble"))


class SanteSansSourdinesDeStockage(Base):
    page = "sante"

    def test_la_page_sante_ne_montre_plus_les_sourdines_de_stockage(self):
        """Ni dans le résumé, ni dans l'onglet Journal où vivent les sourdines de la santé (Task 19)."""
        self.assertIsNone(self.f.objet("sourdine-menage:journal"))
        QMetaObject.invokeMethod(self.f.objet("onglet-journal"), "clicked", Qt.DirectConnection)
        attendre(150)
        nettoyer_emballages()
        self.assertIsNotNone(self.f.objet("sante-onglet-journal"))
        self.assertIsNone(self.f.objet("sourdine-menage:journal"))


class OptimiserSection(Base):
    """Fixture « stockage » : options A à D et applis Flatpak système (format réel, taille décimale GLib).
    Task 19 : une ligne par option, repliée ; un clic la déplie (une seule à la fois)."""

    def deplier(self, oid):
        QMetaObject.invokeMethod(self.f.objet("optimiser-ligne-" + oid), "clicked", Qt.DirectConnection)
        attendre(100)

    def test_options_a_a_d_avec_leur_badge(self):
        self.assertTrue(self.f.objet("optimiser-section").property("visible"))
        badges = {o: self.texte("optimiser-badge-" + o) for o in "ABCD"}
        self.assertEqual(badges["A"], "En place")
        self.assertEqual(badges["B"], "À décider")
        self.assertTrue(badges["C"].startswith("Possible : "))
        self.assertEqual(badges["D"], "Ton idée — plus tard")
        self.assertIn("Recommandation", self.f.objet("optimiser-recommandation").property("text"))
        self.assertIn("fusionner des disques", self.f.objet("optimiser-idee").property("text"))

    def test_options_repliees_a_l_ouverture(self):
        for oid in "ABCD":
            self.assertTrue(self.f.objet("optimiser-ligne-" + oid).property("visible"), oid)
            self.assertFalse(self.f.objet("optimiser-detail-" + oid).property("visible"), oid)
        self.assertTrue(self.f.objet("optimiser-recommandation").property("visible"))
        self.assertTrue(self.f.objet("optimiser-idee").property("visible"))

    def test_une_seule_option_depliee_a_la_fois(self):
        self.deplier("B")
        self.assertTrue(self.f.objet("optimiser-detail-B").property("visible"))
        self.assertIn("Externe a 150 Go libres", self.f.objet("optimiser-texte-B").property("text"))
        self.deplier("C")
        self.assertTrue(self.f.objet("optimiser-detail-C").property("visible"))
        self.assertFalse(self.f.objet("optimiser-detail-B").property("visible"))
        self.deplier("C")
        self.assertFalse(self.f.objet("optimiser-detail-C").property("visible"))

    def test_toutes_les_applis_au_dessus_des_commandes(self):
        self.deplier("C")
        lignes = self.f.objets("optimiser-appli-")
        self.assertEqual(len(lignes), 25)
        commandes = self.f.objet("optimiser-commandes-C")
        bas = max(o.property("y") + o.property("height") for o in lignes)
        self.assertLessEqual(bas, commandes.property("y"))
        self.assertLessEqual(commandes.property("height"), 400)        # zone défilante à hauteur bornée

    def test_liste_des_applis_et_copie_des_commandes(self):
        class PressePapiers:
            texte = None

            def setText(self, texte):
                self.texte = texte
        faux = PressePapiers()
        self.f.pont._presse_papiers = faux
        self.deplier("C")
        self.assertIsNotNone(self.f.objet("optimiser-appli-org.darktable.Darktable"))
        self.assertFalse(self.f.objet("optimiser-copie-C").property("visible"))
        self.assertFalse(self.f.objet("optimiser-copier-A").property("visible"))
        bouton = self.f.objet("optimiser-copier-C")
        QMetaObject.invokeMethod(bouton, "clicked", Qt.DirectConnection)
        attendre(100)
        self.assertIn("flatpak install --user -y flathub org.darktable.Darktable", faux.texte)
        self.assertTrue(self.f.objet("optimiser-copie-C").property("visible"))
        self.assertEqual(self.appels, [["centre-bazzite", "stockage"]])        # rien d'autre n'est lancé


if __name__ == "__main__":
    unittest.main()
