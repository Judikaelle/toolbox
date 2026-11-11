"""Page Démarrage : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen), avec le dossier de fixture
« demarrage » (etat.json + demarrage.json ; noms génériques seulement). Aucune vraie commande : QProcess.startDetached
est remplacé. Trois onglets, « Durée », « Au lancement » et « Système » ; seul l'onglet ouvert existe, et la fenêtre le
garde (ongletDemarrage)."""
import re
import unittest
from unittest import mock

from PySide6.QtCore import QProcess

from centre_bazzite import demarrage
from tests.test_jeuxpage import Base as BaseJeux
from tests.test_menu import attendre
from tests.test_stockagepage import TOLERANCE_ECRAN, nettoyer_emballages

OUVERTURE = [["centre-bazzite", "demarrage"]]
PHASES = ["firmware", "loader", "kernel", "initrd", "userspace"]
COMMANDE_RESEAU = "sudo systemctl disable NetworkManager-wait-online.service"


class PressePapiers:
    texte = None

    def setText(self, t):
        PressePapiers.texte = t


class Base(BaseJeux):
    dossier = "demarrage"
    page = "demarrage"

    def ouvrir_onglet(self, cle):
        self.clic("onglet-" + cle)
        self.assertEqual(self.f.objet("demarrage-onglets").property("courant"), cle)

    def assertReleveLance(self):
        self.assertEqual(self.appels, OUVERTURE)

    def tient_sur_un_ecran(self, cle):
        self.assertEqual((self.fenetre().property("width"), self.fenetre().property("height")), (1100, 720))
        page = self.f.objet("page-demarrage")
        self.assertLessEqual(page.property("contentHeight"), page.property("height") + TOLERANCE_ECRAN, cle)

    def remplacer_demarrage(self, **champs):
        """Comme une relecture de demarrage.json par le pont."""
        self.f.pont._demarrage = dict(self.f.pont.demarrage, **champs)
        self.f.pont.demarrageChange.emit()
        attendre(150)
        nettoyer_emballages()


class Ouverture(Base):
    def test_ouverture_rafraichit(self):
        """La page relance le relevé du démarrage, et rien d'autre."""
        self.assertReleveLance()
        self.assertIsNotNone(self.f.objet("page-demarrage"))
        self.assertEqual(self.f.objet("demarrage-onglets").property("courant"), "duree")

    def test_titre_et_phrase_du_resume(self):
        self.assertEqual(self.propriete("demarrage-phrase", "text"), "Démarré en 40 s · habituel : 38 s")

    def test_onglets(self):
        self.assertEqual(self.js("demarrage-onglets", "modele.map(o => o.cle)"), ["duree", "lancement", "systeme"])
        self.assertEqual(self.js("demarrage-onglets", "modele.map(o => o.libelle)"), ["Durée", "Au lancement", "Système"])

    def test_aucun_bouton_principal_sur_la_page(self):
        principaux = [o for o in self.f.objets("") if o.metaObject().className().startswith("BoutonPrincipal")
                      and o.property("visible")]
        self.assertEqual([o.objectName() for o in principaux], ["menu-tout-mettre-a-jour"])

    def test_onglet_garde_quand_on_revient_sur_la_page(self):
        self.ouvrir_onglet("systeme")
        self.f.racines[0].setProperty("page", "accueil")
        attendre(150)
        nettoyer_emballages()
        self.f.racines[0].setProperty("page", "demarrage")
        attendre(300)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("demarrage-onglets").property("courant"), "systeme")

    def test_onglet_inconnu_montre_la_duree(self):
        self.f.racines[0].setProperty("ongletDemarrage", "nulle-part")
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("demarrage-onglets").property("courant"), "duree")
        self.assertIsNotNone(self.f.objet("demarrage-duree"))


class Duree(Base):
    def test_phases_et_total(self):
        """Un segment par phase, de largeur proportionnelle aux secondes ; le total en toutes lettres."""
        self.assertEqual(self.propriete("demarrage-total", "text"), "40 s")
        segments = {c: self.f.objet("phase-" + c) for c in PHASES}
        self.assertEqual(len(self.f.objets("phase-")), 5)
        largeurs = {c: o.property("width") for c, o in segments.items()}
        segments = None
        secondes = {"firmware": 15.0, "loader": 3.7, "kernel": 6.5, "initrd": 6.7, "userspace": 8.5}
        ordre = sorted(PHASES, key=lambda c: secondes[c])
        for petit, grand in zip(ordre, ordre[1:]):
            self.assertLess(largeurs[petit], largeurs[grand], f"{petit} < {grand}")
        barre = self.f.objet("barre-phases").property("width")
        self.assertAlmostEqual(sum(largeurs.values()) / barre, 1.0, delta=0.05)
        self.assertEqual(self.propriete("legende-firmware", "text"), "Firmware (BIOS/UEFI) 15 s")
        self.assertEqual(self.propriete("legende-loader", "text"), "Chargeur de démarrage 3,7 s")

    def test_habitude(self):
        self.assertEqual(self.propriete("duree-habituel", "text"), "Habituel : 38 s (10 démarrages précédents)")
        self.remplacer_demarrage(habituel=None, precedents=[38.0, 37.0])
        self.assertEqual(self.propriete("duree-habituel", "text"),
                         "Pas encore d'habitude : il faut quelques démarrages.")

    def test_ralentisseurs_badges(self):
        attendu = {"phase:firmware": ("Lent", "attention"),
                   "unite:dracut-initqueue.service": ("Pendant l'initrd", "neutre"),
                   "unite:NetworkManager-wait-online.service": ("Retarde le bureau", "attention")}
        for id_, mots in attendu.items():
            self.assertIsNotNone(self.f.objet("ralentisseur-" + id_), id_)
            self.assertEqual((self.propriete("badge-ralentisseur-" + id_, "texte"),
                              self.propriete("badge-ralentisseur-" + id_, "etat")), mots, id_)
        self.assertEqual(len(self.f.objets("ralentisseur-")), 3)
        self.assertEqual(self.propriete("duree-ralentisseur-phase:firmware", "text"), "15 s")
        self.assertIn("Fast Boot", self.propriete("explication-ralentisseur-phase:firmware", "text"))
        self.assertIn("attend que le réseau", self.propriete("explication-ralentisseur-unite:NetworkManager-wait-online.service", "text"))

    def test_phase_normale_badge_normal(self):
        ral = [dict(r, lent=False) if r["type"] == "phase" else r for r in self.f.pont.demarrage["ralentisseurs"]]
        self.remplacer_demarrage(ralentisseurs=ral)
        self.assertEqual((self.propriete("badge-ralentisseur-phase:firmware", "texte"),
                          self.propriete("badge-ralentisseur-phase:firmware", "etat")), ("Normal", "ok"))

    def test_arriere_plan_affiche(self):
        self.assertEqual(self.propriete("arriere-plan-titre", "text"), "En arrière-plan, sans retarder le bureau")
        self.assertIsNotNone(self.f.objet("arriere-plan-unite:uupd.service"))
        self.assertEqual(self.propriete("fond-nom-unite:uupd.service", "text"), "uupd.service")
        self.assertEqual(self.propriete("fond-duree-unite:uupd.service", "text"), "12 s")

    def test_arriere_plan_unite_de_session(self):
        """Une unité de ta session (`--user blame`) porte « (session) » après son nom ; celles du système, rien."""
        self.assertEqual(self.propriete("fond-nom-unite:lanceur.service", "text"), "lanceur.service (session)")
        self.assertEqual(self.propriete("fond-nom-unite:uupd.service", "text"), "uupd.service")
        self.remplacer_demarrage(arriere_plan=[dict(r, portee="systeme") for r in self.f.pont.demarrage["arriere_plan"]])
        self.assertEqual(self.propriete("fond-nom-unite:lanceur.service", "text"), "lanceur.service")

    def test_arriere_plan_vide_masque_le_titre(self):
        self.remplacer_demarrage(arriere_plan=[])
        self.assertFalse(self.propriete("arriere-plan-titre", "visible"))

    def test_point_lent_en_tete(self):
        ligne = self.f.objet("a-regarder-ligne-demarrage:lent")
        self.assertIsNotNone(ligne)
        ligne = None
        self.assertEqual(self.propriete("badge-point-demarrage:lent", "texte"), "Attention")

    def test_sans_point_pas_de_a_regarder(self):
        self.f.pont._etat = dict(self.f.pont.etat, points=[])
        self.f.pont.etatChange.emit()
        attendre(150)
        nettoyer_emballages()
        self.assertIsNone(self.f.objet("a-regarder-ligne-demarrage:lent"))

    def test_erreurs_en_message(self):
        self.assertFalse(self.propriete("demarrage-erreurs", "visible"))
        self.remplacer_demarrage(erreurs=["Services système illisibles (OSError)"])
        self.assertTrue(self.propriete("demarrage-erreurs", "visible"))
        self.assertEqual(self.propriete("demarrage-erreurs", "text"), "Services système illisibles (OSError)")

    def test_aucune_commande_en_dehors_du_releve(self):
        self.assertReleveLance()


class PasFini(Base):
    dossier = "demarrage-pas-fini"

    def test_pas_fini_etat_vide(self):
        vide = self.f.objet("duree-pas-finie")
        self.assertIsNotNone(vide)
        self.assertTrue(vide.property("visible"))
        self.assertEqual(vide.property("texte"),
                         "Le démarrage n'est pas encore fini : sa durée sera relevée au prochain passage.")
        vide = None
        barre = self.f.objet("barre-phases")
        self.assertTrue(barre is None or not barre.property("visible"))
        self.assertEqual(self.f.objets("ralentisseur-"), [])
        self.assertEqual(self.propriete("demarrage-phrase", "text"), "Démarrage en cours de relevé.")
        # I-3 : pas de bandeau d'erreur, rien « en arrière-plan, sans retarder le bureau »
        self.assertFalse(self.propriete("demarrage-erreurs", "visible"))
        self.assertFalse(self.propriete("arriere-plan-titre", "visible"))
        self.assertEqual([o.objectName() for o in self.f.objets("arriere-plan-")], ["arriere-plan-titre"])


class Vide(Base):
    dossier = "demarrage-vide"

    def test_demarrage_vide_etat_vide(self):
        vide = self.f.objet("demarrage-vide")
        self.assertIsNotNone(vide)
        self.assertEqual(vide.property("texte"),
                         "Pas encore de relevé du démarrage : il se fait à l'ouverture de la page.")
        vide = None
        self.assertFalse(self.propriete("demarrage-onglets", "visible"))
        self.assertIsNone(self.f.objet("barre-phases"))
        self.assertReleveLance()


class Systeme(Base):
    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("systeme")

    def test_phrase_d_en_tete(self):
        self.assertEqual(self.propriete("systeme-phrase", "text"),
                         "Ces services démarrent avec le système, pour tous les comptes. Health Hub ne les change pas : "
                         "chaque ligne donne la commande à copier dans un terminal.")

    def test_une_ligne_par_service(self):
        self.assertEqual(len(self.f.objets("service-")), 6)
        u = "NetworkManager-wait-online.service"
        self.assertEqual(self.propriete("systeme-unite-" + u, "text"), u)
        self.assertEqual(self.propriete("systeme-description-" + u, "text"), "Attente du réseau au démarrage")
        self.assertEqual(self.propriete("systeme-duree-" + u, "text"), "4,6 s")
        self.assertEqual(self.propriete("systeme-duree-exemple-bluetooth.service", "text"), "—")
        self.assertIn("attend que le réseau", self.propriete("systeme-explication-" + u, "text"))
        self.assertEqual(self.propriete("systeme-commande-" + u, "text"), COMMANDE_RESEAU)

    def test_systeme_copier_la_commande(self):
        self.f.pont._presse_papiers = PressePapiers()
        PressePapiers.texte = None
        bouton = self.f.objet("copier-NetworkManager-wait-online.service")
        self.assertEqual(bouton.property("text"), "Copier la commande")
        bouton = None
        self.clic("copier-NetworkManager-wait-online.service")
        self.assertEqual(PressePapiers.texte, COMMANDE_RESEAU)
        self.clic("copier-exemple-sauvegarde.timer")
        self.assertEqual(PressePapiers.texte, "sudo systemctl disable --now exemple-sauvegarde.timer")
        self.assertEqual(self.appels, OUVERTURE)                     # rien n'est lancé : on copie seulement

    def test_systeme_essentiel_sans_commande(self):
        self.assertIsNotNone(self.f.objet("service-uupd.timer"))
        self.assertEqual((self.propriete("systeme-essentiel-uupd.timer", "texte"),
                          self.propriete("systeme-essentiel-uupd.timer", "etat")), ("Essentiel", "neutre"))
        self.assertIsNone(self.f.objet("copier-uupd.timer"))
        self.assertIsNone(self.f.objet("systeme-commande-uupd.timer"))
        self.assertEqual(len(self.f.objets("copier-")), 4)
        self.assertEqual(len([o for o in self.f.objets("systeme-essentiel-") if o.property("visible")]), 2)

    def test_aucun_bouton_de_bascule(self):
        """Les services système sont en lecture seule : seulement « Copier la commande »."""
        for o in self.f.objets(""):
            if o.objectName().startswith(("basculer", "reglage", "remettre")):
                self.fail(o.objectName())


def sain(id_):
    """Le suffixe d'objectName d'une entrée : tout caractère hors [A-Za-z0-9] devient « _ »."""
    return re.sub(r"[^A-Za-z0-9]", "_", id_)


MESSAGERIE = "autostart:messagerie.desktop"
INDEXATION = "autostart:indexation.desktop"
SAUVEGARDE = "unite:sauvegarde-notes.timer"
OUTIL = "unite:outil-perso.service"
LANCEUR = "unite:lanceur.service"
MAJ_APPS = "unite:maj-apps.timer"
BAZZITE = "unite:bazzite-exemple.service"
PIPEWIRE = "unite:pipewire.socket"
PLASMA = "autostart:org.kde.plasmashell.desktop"


class Lancement(Base):
    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("lancement")
        self.appels.clear()

    def lignes(self):
        return sorted(o.objectName()[len("entree-"):] for o in self.f.objets("entree-"))

    def dlg(self, code):
        return self.js("lancement-carte", code)

    def reglages(self):
        return [a for a in self.appels if a[:2] == ["centre-bazzite", "demarrage"]]

    def ouvrir_confirmation(self, id_):
        self.clic("basculer-" + sain(id_))
        attendre(1500, lambda: self.dlg("dialogue.opened"))
        self.assertTrue(self.dlg("dialogue.opened"))

    def deplier(self, cle):
        self.clic("section-" + cle)
        self.assertTrue(self.propriete("section-" + cle, "ouverte"))

    def test_sections_et_comptes(self):
        self.assertEqual(self.propriete("section-appli-titre", "text"), "Applis au démarrage de la session")
        self.assertEqual(self.propriete("section-unites-titre", "text"), "Tes services et minuteurs")
        self.assertEqual(self.propriete("section-bazzite-titre", "text"), "Activés par Bazzite (lecture seule) · 1")
        self.assertEqual(self.propriete("section-essentiel-titre", "text"), "Essentiels du bureau (verrouillés) · 2")
        sections = {s: [o.objectName() for o in self.f.objets("entree-") if o.property("section") == s]
                    for s in ("appli", "unites", "bazzite", "essentiel")}
        self.assertEqual(sorted(sections["appli"]), sorted("entree-" + sain(i) for i in (MESSAGERIE, INDEXATION)))
        self.assertEqual(sorted(sections["unites"]),
                         sorted("entree-" + sain(i) for i in (SAUVEGARDE, "unite:synchro.timer", OUTIL, LANCEUR, MAJ_APPS)))
        # Les deux dernières sont repliées : leurs lignes n'existent pas encore.
        self.assertEqual((sections["bazzite"], sections["essentiel"]), ([], []))
        self.assertFalse(self.propriete("section-bazzite", "ouverte"))
        self.assertFalse(self.propriete("section-essentiel", "ouverte"))
        self.deplier("bazzite")
        self.deplier("essentiel")
        self.assertEqual(sorted(o.objectName() for o in self.f.objets("entree-") if o.property("section") == "bazzite"),
                         ["entree-" + sain(BAZZITE)])
        self.assertEqual(sorted(o.objectName() for o in self.f.objets("entree-") if o.property("section") == "essentiel"),
                         sorted("entree-" + sain(i) for i in (PIPEWIRE, PLASMA)))
        self.clic("section-bazzite")
        self.assertIsNone(self.f.objet("entree-" + sain(BAZZITE)))

    def test_contenu_d_une_ligne(self):
        self.assertEqual(self.propriete("nom-" + sain(MESSAGERIE), "text"), "Messagerie")
        self.assertEqual(self.propriete("description-" + sain(MESSAGERIE), "text"), "Client de messagerie.")
        self.assertEqual((self.propriete("etat-" + sain(MESSAGERIE), "texte"),
                          self.propriete("etat-" + sain(MESSAGERIE), "etat")), ("Activé", "ok"))
        self.assertEqual((self.propriete("etat-" + sain(INDEXATION), "texte"),
                          self.propriete("etat-" + sain(INDEXATION), "etat")), ("Désactivé", "neutre"))
        self.assertEqual(self.propriete("basculer-" + sain(MESSAGERIE), "text"), "Désactiver")
        self.assertEqual(self.propriete("basculer-" + sain(INDEXATION), "text"), "Activer")
        self.assertEqual(self.propriete("quand-" + sain(SAUVEGARDE), "text"), "Prochaine : demain à 04 h 45")

    def test_bascule_ouvre_la_confirmation_sans_rien_lancer(self):
        self.assertFalse(self.dlg("dialogue.opened"))
        self.ouvrir_confirmation(MESSAGERIE)
        self.assertEqual(self.dlg("dialogue.title"), "Ne plus lancer « Messagerie » à l'ouverture de session ?")
        self.assertEqual(self.dlg("confirmer.text"), "Désactiver")
        self.assertEqual(self.dlg("annuler.text"), "Annuler")
        self.assertEqual(self.appels, [])

    def test_confirmer_lance_regler(self):
        self.ouvrir_confirmation(MESSAGERIE)
        self.dlg("confirmer.clicked()")
        attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.assertEqual(self.appels, [["centre-bazzite", "demarrage", "regler", MESSAGERIE, "non"]])
        self.appels.clear()
        self.ouvrir_confirmation(INDEXATION)
        self.assertEqual(self.dlg("confirmer.text"), "Activer")
        self.dlg("confirmer.clicked()")
        attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.assertEqual(self.appels, [["centre-bazzite", "demarrage", "regler", INDEXATION, "oui"]])

    def test_confirmer_une_seule_commande_par_ouverture(self):
        """A-3 : un double clic sur « Désactiver » ne lance qu'une commande, même si la première n'a pas pu partir (le
        pont ne tient alors pas la ligne occupée : seule la garde du dialogue joue)."""
        with mock.patch.object(QProcess, "startDetached",
                               lambda prog, args: self.appels.append([prog] + list(args)) or (False, 0)):
            self.ouvrir_confirmation(MESSAGERIE)
            self.dlg("confirmer.clicked(); confirmer.clicked(); onglet.confirmer()")
            attendre(1500, lambda: not self.dlg("dialogue.opened"))
            self.assertEqual(self.appels, [["centre-bazzite", "demarrage", "regler", MESSAGERIE, "non"]])
            self.ouvrir_confirmation(MESSAGERIE)          # une nouvelle ouverture : une nouvelle commande
            self.dlg("confirmer.clicked()")
            attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.assertEqual(len(self.appels), 2)

    def test_ligne_occupee_pendant_la_commande(self):
        """I-4 : de la confirmation à la réponse de la CLI (demarrage.json réécrit avec son retour), la ligne dit
        « En cours… » et ses boutons sont grisés ; les autres lignes restent libres."""
        self.assertFalse(self.propriete("en-cours-" + sain(MESSAGERIE), "visible"))
        self.ouvrir_confirmation(MESSAGERIE)
        self.dlg("confirmer.clicked()")
        attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.assertEqual(self.f.pont.demarrageOccupes, [MESSAGERIE])
        self.assertTrue(self.propriete("en-cours-" + sain(MESSAGERIE), "visible"))
        self.assertEqual(self.propriete("en-cours-" + sain(MESSAGERIE), "text"), "En cours…")
        self.assertFalse(self.propriete("basculer-" + sain(MESSAGERIE), "enabled"))
        self.assertTrue(self.propriete("basculer-" + sain(INDEXATION), "enabled"))
        self.clic("remettre-" + sain(INDEXATION))
        self.assertFalse(self.propriete("remettre-" + sain(INDEXATION), "enabled"))
        self.assertFalse(self.propriete("basculer-" + sain(INDEXATION), "enabled"))
        self.assertTrue(self.propriete("en-cours-" + sain(INDEXATION), "visible"))
        self.assertEqual(self.reglages(), [["centre-bazzite", "demarrage", "regler", MESSAGERIE, "non"],
                                           ["centre-bazzite", "demarrage", "remettre", INDEXATION]])
        entrees = [dict(e, actif=False) if e["id"] == MESSAGERIE else e
                   for e in self.f.pont.demarrage["lancement"]["entrees"]]
        self.remplacer_demarrage(genere="2026-11-10T21:00:05+00:00",
                                 lancement=dict(self.f.pont.demarrage["lancement"], entrees=entrees),
                                 retour={"id": MESSAGERIE, "code": 0, "date": "2026-11-10T21:00:05",
                                         "phrase": "« Messagerie » ne se lancera plus à l'ouverture de session."})
        self.assertEqual(self.f.pont.demarrageOccupes, [INDEXATION])
        self.assertFalse(self.propriete("en-cours-" + sain(MESSAGERIE), "visible"))
        self.assertTrue(self.propriete("basculer-" + sain(MESSAGERIE), "enabled"))
        self.assertEqual(self.propriete("basculer-" + sain(MESSAGERIE), "text"), "Activer")
        self.assertTrue(self.propriete("en-cours-" + sain(INDEXATION), "visible"))

    def test_retour_de_la_cli_en_message(self):
        """I-4 : la phrase de la CLI s'affiche dans l'onglet : positive pour une réussite, avertissement pour un échec ou
        un refus. On peut la fermer ; le retour suivant revient, et le relevé suivant l'efface."""
        self.assertIsNone(self.f.objet("lancement-retour"))
        positif = self.js("page-demarrage", "Kirigami.MessageType.Positive")
        attention = self.js("page-demarrage", "Kirigami.MessageType.Warning")
        for i, (code, phrase, type_) in enumerate((
                (0, "« Messagerie » ne se lancera plus à l'ouverture de session.", positif),
                (1, "Échec : Failed to disable unit: Access denied", attention),
                (2, "« Indexation » a changé depuis : rien n'est touché.", attention))):
            with self.subTest(code=code):
                self.remplacer_demarrage(retour={"id": MESSAGERIE, "code": code, "phrase": phrase,
                                                 "date": f"2026-11-10T21:00:0{i}"})
                self.assertTrue(self.propriete("lancement-retour", "visible"))
                self.assertEqual(self.propriete("lancement-retour", "text"), phrase)
                self.assertEqual(self.propriete("lancement-retour", "type"), type_)
                self.assertTrue(self.propriete("lancement-retour", "showCloseButton"))
        self.tient_sur_un_ecran("lancement avec un retour")
        self.f.objet("lancement-retour").setProperty("visible", False)        # ce que fait la croix de Kirigami
        attendre(150)
        nettoyer_emballages()
        self.assertIsNone(self.f.objet("lancement-retour"))
        self.remplacer_demarrage(retour={"id": INDEXATION, "code": 0, "phrase": "« Indexation » est revenu comme avant.",
                                         "date": "2026-11-10T21:01:00"})
        self.assertEqual(self.propriete("lancement-retour", "text"), "« Indexation » est revenu comme avant.")
        self.remplacer_demarrage(retour=None)                                   # le relevé suivant
        self.assertIsNone(self.f.objet("lancement-retour"))

    def test_annuler_ne_lance_rien(self):
        self.ouvrir_confirmation(SAUVEGARDE)
        self.dlg("annuler.clicked()")
        attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.assertEqual(self.appels, [])

    def test_textes_de_confirmation_par_type(self):
        attendu = {
            (MESSAGERIE, "Messagerie"): (
                "Ne plus lancer « Messagerie » à l'ouverture de session ?",
                "Elle ne se lancera plus à ta prochaine ouverture de session. Si elle tourne déjà, elle reste ouverte. "
                "Tu pourras la remettre d'un clic."),
            (INDEXATION, "Indexation"): (
                "Lancer « Indexation » à l'ouverture de session ?",
                "Elle se lancera à ta prochaine ouverture de session."),
            (LANCEUR, None): None,
            ("unite:synchro.timer", "synchro.timer"): (
                "Arrêter le minuteur « synchro.timer » ?",
                "Il ne se déclenchera plus, même après un redémarrage. Tu pourras le remettre d'un clic."),
            (OUTIL, "outil-perso.service"): (
                "Démarrer « outil-perso.service » avec ta session ?",
                "Il démarrera à ta prochaine ouverture de session."),
        }
        for (id_, _nom), textes in attendu.items():
            if textes is None:
                continue
            with self.subTest(id=id_):
                self.ouvrir_confirmation(id_)
                self.assertEqual((self.dlg("dialogue.title"), self.dlg("dialogue.subtitle")), textes)
                self.dlg("annuler.clicked()")
                attendre(1500, lambda: not self.dlg("dialogue.opened"))
        # Le sens inverse de chaque type : on change l'état noté dans le relevé.
        entrees = self.f.pont.demarrage["lancement"]["entrees"]
        retournees = [dict(e, actif=not e["actif"]) if e["id"] in (SAUVEGARDE, OUTIL, "autostart:messagerie.desktop") else e
                      for e in entrees]
        self.remplacer_demarrage(lancement=dict(self.f.pont.demarrage["lancement"], entrees=retournees))
        inverses = {
            SAUVEGARDE: ("Remettre en route le minuteur « sauvegarde-notes.timer » ?",
                         "Il se déclenchera de nouveau, dès maintenant."),
            OUTIL: ("Ne plus démarrer « outil-perso.service » avec ta session ?",
                    "Il ne démarrera plus à ta prochaine ouverture de session. S'il tourne déjà, il continue jusque-là. "
                    "Tu pourras le remettre d'un clic."),
            MESSAGERIE: ("Lancer « Messagerie » à l'ouverture de session ?",
                         "Elle se lancera à ta prochaine ouverture de session."),
        }
        for id_, textes in inverses.items():
            with self.subTest(inverse=id_):
                self.ouvrir_confirmation(id_)
                self.assertEqual((self.dlg("dialogue.title"), self.dlg("dialogue.subtitle")), textes)
                self.dlg("annuler.clicked()")
                attendre(1500, lambda: not self.dlg("dialogue.opened"))

    def test_socket_comme_un_service(self):
        entrees = self.f.pont.demarrage["lancement"]["entrees"]
        socket = dict(next(e for e in entrees if e["id"] == OUTIL), id="unite:exemple.socket", nom="exemple.socket",
                      type="socket", actif=True)
        self.remplacer_demarrage(lancement=dict(self.f.pont.demarrage["lancement"], entrees=entrees + [socket]))
        self.ouvrir_confirmation("unite:exemple.socket")
        self.assertEqual(self.dlg("dialogue.title"), "Ne plus démarrer « exemple.socket » avec ta session ?")

    def test_avertissement_healthhub_dans_la_confirmation(self):
        self.assertIsNotNone(self.f.objet("avertissement-" + sain(MAJ_APPS)))
        self.assertEqual(self.js("avertissement-" + sain(MAJ_APPS), "Accessible.name"),
                         "Les outils (Vicinae, Ollama, uv, distrobox) ne se mettront plus à jour tout seuls.")
        self.assertIsNone(self.f.objet("avertissement-" + sain(MESSAGERIE)))
        self.ouvrir_confirmation(MAJ_APPS)
        self.assertEqual(self.dlg("dialogue.title"), "Arrêter le minuteur « maj-apps.timer » ?")
        self.assertTrue(self.dlg("avertissement.visible"))
        self.assertEqual(self.dlg("avertissement.text"),
                         "Les outils (Vicinae, Ollama, uv, distrobox) ne se mettront plus à jour tout seuls.")
        self.assertEqual(self.dlg("avertissement.type"), self.js("page-demarrage", "Kirigami.MessageType.Warning"))
        self.dlg("annuler.clicked()")
        attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.ouvrir_confirmation(MESSAGERIE)
        self.assertFalse(self.dlg("avertissement.visible"))

    def test_remettre_comme_avant(self):
        self.assertEqual((self.propriete("modifie-" + sain(INDEXATION), "texte"),
                          self.propriete("modifie-" + sain(INDEXATION), "etat")), ("Modifié par Health Hub", "info"))
        self.assertEqual(self.propriete("remettre-" + sain(INDEXATION), "text"), "Remettre comme avant")
        self.assertIsNone(self.f.objet("remettre-" + sain(MESSAGERIE)))
        self.assertIsNone(self.f.objet("modifie-" + sain(MESSAGERIE)))
        self.clic("remettre-" + sain(INDEXATION))
        self.assertEqual(self.appels, [["centre-bazzite", "demarrage", "remettre", INDEXATION]])
        self.assertFalse(self.dlg("dialogue.opened"))

    def test_lecture_seule_sans_bouton(self):
        self.deplier("bazzite")
        self.deplier("essentiel")
        for id_, raison in ((BAZZITE, "Activé par Bazzite pour tous les comptes."), (PIPEWIRE, "Essentiel au bureau."),
                            (PLASMA, "Essentiel au bureau."),
                            (LANCEUR, "Nom de fichier inhabituel : Health Hub n'y touche pas.")):
            with self.subTest(id=id_):
                self.assertIsNotNone(self.f.objet("entree-" + sain(id_)))
                self.assertEqual(self.propriete("raison-" + sain(id_), "text"), raison)
                self.assertIsNone(self.f.objet("basculer-" + sain(id_)))
                self.assertIsNone(self.f.objet("remettre-" + sain(id_)))
        self.assertEqual(len(self.f.objets("basculer-")), 6)           # les 6 lignes modifiables, pas une de plus

    def test_unites_illisibles_le_disent(self):
        """systemd ne répond pas : les applis restent, et la section des services et minuteurs dit pourquoi elle est
        vide au lieu de « Aucun. »."""
        self.assertEqual(self.propriete("unites-aucun", "visible"), False)
        applis = [e for e in self.f.pont.demarrage["lancement"]["entrees"] if e["type"] == "appli"]
        self.remplacer_demarrage(lancement=dict(self.f.pont.demarrage["lancement"], entrees=applis,
                                                illisible="systemctl --user show : Failed to connect to bus"))
        self.assertIsNotNone(self.f.objet("entree-" + sain(MESSAGERIE)))
        self.assertIsNotNone(self.f.objet("remettre-" + sain(INDEXATION)))
        self.assertTrue(self.propriete("unites-aucun", "visible"))
        self.assertEqual(self.propriete("unites-aucun", "text"),
                         "Illisibles pour l'instant : systemd ne répond pas. Le prochain relevé réessaiera.")
        self.remplacer_demarrage(lancement=dict(self.f.pont.demarrage["lancement"], illisible=None))
        self.assertEqual(self.propriete("unites-aucun", "text"), "Aucun.")

    def test_ignorees_phrase(self):
        self.assertEqual(self.propriete("lancement-ignorees", "text"),
                         "2 entrées prévues pour d'autres bureaux ou des programmes absents ne sont pas montrées.")
        self.remplacer_demarrage(lancement=dict(self.f.pont.demarrage["lancement"], ignorees=0))
        self.assertFalse(self.propriete("lancement-ignorees", "visible"))

    def test_changement_du_releve_ferme_la_confirmation(self):
        self.ouvrir_confirmation(MESSAGERIE)
        entrees = [dict(e, actif=False) if e["id"] == MESSAGERIE else e
                   for e in self.f.pont.demarrage["lancement"]["entrees"]]
        self.remplacer_demarrage(lancement=dict(self.f.pont.demarrage["lancement"], entrees=entrees))
        attendre(1500, lambda: not self.dlg("dialogue.opened"))
        self.assertFalse(self.dlg("dialogue.opened"))
        self.assertEqual(self.appels, [])

    def test_lancement_tient_sur_un_ecran(self):
        self.tient_sur_un_ecran("lancement")
        liste = self.f.objet("lancement-liste")
        self.assertIsNotNone(liste)
        self.assertGreaterEqual(liste.property("height"), 100)


class Formats(Base):
    def test_duree_lisible_comme_le_moteur(self):
        """Style.dureeLisible est la seule copie de demarrage.duree_lisible (testée contre le moteur)."""
        for secondes in (0, 0.04, 4.6, 9.94, 9.95, 10, 14.5, 40.4, 59.4, 59.6, 60, 65, 125.2, 3600, 3725, 7384.7):
            with self.subTest(secondes=secondes):
                self.assertEqual(self.js("page-demarrage", f"Style.dureeLisible({secondes})"),
                                 demarrage.duree_lisible(secondes))


class Ecran(Base):
    def test_onglets_tiennent_sur_un_ecran(self):
        for cle in ("duree", "lancement", "systeme"):
            with self.subTest(onglet=cle):
                self.ouvrir_onglet(cle)
                self.tient_sur_un_ecran(cle)


if __name__ == "__main__":
    unittest.main()
