"""Page Santé : chargée pour de vrai dans Main.qml (QT_QPA_PLATFORM=offscreen). Chaque ligne porte un badge nommé ; on lit
son mot et son état. Task 19 : la page a des onglets (Résumé, Disques, GPU et jeux, Système, Sécurité, Contrôles, Journal) ; seul
l'onglet ouvert existe. Un test qui regarde un onglet l'ouvre d'abord, comme l'utilisateur."""
import gc
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent, QMetaObject, QProcess, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression

from centre_bazzite import commun
from tests.test_accueil import APP, ETATS, Fenetre
from tests.test_menu import attendre

ONGLETS = [("resume", "Résumé"), ("disques", "Disques"), ("gpu", "GPU et jeux"), ("systeme", "Système"),
           ("securite", "Sécurité"), ("controles", "Contrôles"), ("journal", "Journal")]
# Objectif « un écran » (Task 19) : contentHeight ≤ hauteur visible + cette tolérance, soit la marge du bas de la page
# (Style.margePage) : seul ce vide peut passer sous le bord, jamais du contenu.
TOLERANCE_ECRAN = 24


def nettoyer_emballages():
    """Un onglet fermé détruit ses éléments : un emballage Python resté sur l'un d'eux fait planter PySide quand son
    adresse est réutilisée. On les ramasse avant de chercher dans l'onglet suivant."""
    gc.collect()
    APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def variante(test, dossier, **champs):
    """Copie temporaire de etat.json du dossier, avec ces champs de « sante » ou de la racine remplacés."""
    d = tempfile.TemporaryDirectory()
    test.addCleanup(d.cleanup)
    e = json.loads((ETATS / dossier / "etat.json").read_text(encoding="utf-8"))
    for cle, valeur in champs.items():
        if cle in e.get("sante", {}) or cle in ("bilan_hebdo",):
            e["sante"][cle] = valeur
        else:
            e[cle] = valeur
    (Path(d.name) / "etat.json").write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    return Path(d.name)


class Base(unittest.TestCase):
    dossier = "controles"

    def setUp(self):
        self.addCleanup(nettoyer_emballages)
        self.f = Fenetre(self.dossier, "sante")
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())
        self.assertTrue(self.f.racines, "Main.qml ne s'est pas chargé")

    def badge(self, nom):
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        self.assertTrue(o.property("visible"), nom)
        return o.property("texte"), o.property("etat")

    def absent(self, nom):
        """Une ligne conditionnelle : sans objet, ou cachée."""
        o = self.f.objet(nom)
        return o is None or not o.property("visible")

    def cliquer(self, nom):
        o = self.f.objet(nom)
        self.assertIsNotNone(o, nom)
        QMetaObject.invokeMethod(o, "clicked", Qt.DirectConnection)
        o = None
        attendre(150)
        nettoyer_emballages()

    def ouvrir_onglet(self, cle):
        """Clic sur l'onglet `cle`, comme l'utilisateur."""
        self.cliquer("onglet-" + cle)
        self.assertEqual(self.f.objet("sante-onglets").property("courant"), cle)

    def hauteurs(self):
        page = self.f.objet("page-sante")
        return page.property("contentHeight"), page.property("height")


class Controles(Base):
    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("controles")

    def test_date_de_verification(self):
        self.assertTrue(self.f.objet("controles-date").property("text").startswith("Vérifié le 9 nov"))
        self.assertFalse(self.f.objet("controles-vide").property("visible"))

    def test_badges_des_controles(self):
        self.assertEqual(self.badge("controle-image"), ("1 à mettre à jour", "info"))
        self.assertEqual(self.badge("controle-flatpak"), ("2 à mettre à jour", "info"))
        self.assertEqual(self.badge("controle-runtimes"), ("3 inutilisés", "attention"))
        self.assertEqual(self.badge("controle-telechargements"), ("1 incomplet", "attention"))
        self.assertEqual(self.badge("controle-caches"), ("Journal à réduire", "attention"))
        self.assertEqual(self.badge("controle-boot"), ("OK", "ok"))


class StockageSain(Base):
    def test_stockage_sain(self):
        self.ouvrir_onglet("disques")
        self.assertEqual(self.badge("stockage-erreurs"), ("3 erreurs", "attention"))
        self.assertEqual(self.badge("stockage-attendus"), ("Non monté", "echec"))
        self.assertEqual(self.f.objet("stockage-attendus-libelle").property("text"), "Disque Données")


class VolumesAttendus(unittest.TestCase):
    """La ligne des volumes attendus suit sante.attendus (la configuration locale) : aucun chemin écrit en dur."""

    def ouvrir(self, **champs):
        self.addCleanup(nettoyer_emballages)
        self.f = Fenetre(variante(self, "controles", **champs), "sante")
        self.addCleanup(self.f.fermer)
        QMetaObject.invokeMethod(self.f.objet("onglet-disques"), "clicked", Qt.DirectConnection)
        attendre(150)
        nettoyer_emballages()

    def ligne(self):
        badge = self.f.objet("stockage-attendus")
        return (badge.property("visible"), badge.property("texte"), badge.property("etat"),
                self.f.objet("stockage-attendus-detail").property("text"),
                self.f.objet("stockage-attendus-libelle").property("text"))

    def test_monte_ecrit_le_chemin_attendu(self):
        self.ouvrir(non_montes=[], attendus=[{"nom": "Atelier", "chemin": "/var/mnt/ATELIER"}])
        self.assertEqual(self.ligne(), (True, "Monté", "ok", "/var/mnt/ATELIER", "Disque Atelier"))

    def test_plusieurs_volumes_attendus(self):
        self.ouvrir(non_montes=["/var/mnt/B"], attendus=[{"nom": "A", "chemin": "/var/mnt/A"},
                                                          {"nom": "B", "chemin": "/var/mnt/B"}])
        self.assertEqual(self.ligne()[:3], (True, "Non monté", "echec"))
        self.assertEqual(self.ligne()[4], "Volumes attendus")
        self.ouvrir(non_montes=[], attendus=[{"nom": "A", "chemin": "/var/mnt/A"},
                                             {"nom": "B", "chemin": "/var/mnt/B"}])
        self.assertEqual(self.ligne()[1:4], ("Monté", "ok", "/var/mnt/A, /var/mnt/B"))

    def test_aucun_volume_attendu_pas_de_ligne(self):
        self.ouvrir(non_montes=[], attendus=[], erreurs_disque={"nombre": 0, "exemples": []})
        self.assertFalse(self.ligne()[0])
        self.assertEqual(self.f.objet("carte-stockage").property("titre"), "Stockage sain")


class TailleQml(Base):
    def test_taille_qml_suit_commun_taille(self):
        """La seule copie JS de commun.taille, Style.taille (UI-I1 : Santé et Jeux l'appellent), donne le même texte,
        bornes comprises (Ruling V43)."""
        page = self.f.objet("page-sante")
        self.assertIsNotNone(page)
        gio, mio = 1024 ** 3, 1024 ** 2
        for octets in (0, 500 * mio, round(1023.4 * mio), round(1023.6 * mio), round(1.2 * gio),
                       round(2.25 * gio), round(9.94 * gio), round(9.96 * gio), round(12.5 * gio), 239 * gio,
                       round(1023.4 * gio), round(1023.5 * gio), round(1023.7 * gio), round(3.3 * 1024 ** 4)):
            e = QQmlExpression(QQmlEngine.contextForObject(page), page, f"Style.taille({octets})")
            texte, _indefini = e.evaluate()
            self.assertFalse(e.hasError(), e.error().toString())
            self.assertEqual(texte, commun.taille(octets), octets)
        e = page = None

    def test_aucune_autre_copie_de_taille(self):
        """UI-I1 : plus de copie de taille() ni d'arrondi() hors de Style.qml (une copie non testée divergerait)."""
        qml = Path(__file__).resolve().parent.parent / "fenetre" / "qml"
        copies = [f.name for f in sorted(qml.glob("*.qml")) if f.name != "Style.qml"
                  and ("function taille(" in f.read_text(encoding="utf-8")
                       or "function arrondi(" in f.read_text(encoding="utf-8"))]
        self.assertEqual(copies, [])


class HorsLigne(unittest.TestCase):
    """Contrôles en échec (hors ligne) : « Vérification impossible » en neutre, jamais en orange."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.addCleanup(nettoyer_emballages)
        e = json.loads((ETATS / "controles" / "etat.json").read_text(encoding="utf-8"))
        c = e["sante"]["controles"]
        c.update(image=None, flatpak=None, runtimes=None, telechargements=[],
                 caches={"miniatures": 0, "corbeille": 0, "journal": None})
        e["sante"].update(erreurs_disque={"nombre": 0, "exemples": []}, non_montes=[])
        e["points"] = []
        (Path(d.name) / "etat.json").write_text(json.dumps(e), encoding="utf-8")
        self.f = Fenetre(Path(d.name), "sante")
        self.addCleanup(self.f.fermer)

    def mot(self, nom):
        o = self.f.objet(nom)
        return o.property("texte"), o.property("etat")

    def detail(self, nom):
        return self.f.objet(nom + "-detail").property("text")

    def ouvrir_onglet(self, cle):
        QMetaObject.invokeMethod(self.f.objet("onglet-" + cle), "clicked", Qt.DirectConnection)
        attendre(150)
        nettoyer_emballages()

    def test_verification_impossible_en_neutre(self):
        self.ouvrir_onglet("controles")
        for nom in ("controle-image", "controle-flatpak", "controle-runtimes", "controle-caches"):
            self.assertEqual(self.mot(nom), ("Vérification impossible", "neutre"), nom)
        # Ruling V41 : la carte promet un nouvel essai au prochain relevé, que --si-perime tient désormais
        for nom in ("controle-image", "controle-flatpak", "controle-runtimes"):
            self.assertIn("nouvel essai au prochain relevé", self.detail(nom), nom)
        self.assertEqual(self.mot("controle-telechargements"), ("OK", "ok"))
        self.ouvrir_onglet("disques")
        self.assertEqual(self.mot("stockage-erreurs"), ("Aucune", "ok"))
        self.assertEqual(self.mot("stockage-attendus"), ("Monté", "ok"))
        self.assertEqual(self.detail("stockage-attendus"), "/var/mnt/DONNEES")

    def test_resume_sans_controle_possible(self):
        self.assertEqual(self.f.objet("resume-phrase-controles").property("text"), "Image non vérifiée")


class BilanSemaine(unittest.TestCase):
    def setUp(self):
        self.addCleanup(nettoyer_emballages)
        bilan = {"date": "2026-11-16T10:00:00", "points": [{"niveau": "attention", "titre": "Caches", "details": ""}],
                 "semaine": {"du": "2026-11-09T10:00:00", "au": "2026-11-16T10:00:00",
                             "changements": 4, "sessions": 2, "echecs": 1}}
        self.f = Fenetre(variante(self, "controles", bilan_hebdo=bilan), "sante")
        self.addCleanup(self.f.fermer)

    def test_synthese_de_la_semaine_dans_l_onglet_systeme(self):
        QMetaObject.invokeMethod(self.f.objet("onglet-systeme"), "clicked", Qt.DirectConnection)
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("bilan-titre").property("text"), "Bilan de la semaine du 9 nov.")
        self.assertEqual(self.f.objet("bilan-synthese").property("text"), "4 mises à jour, 2 sessions (1 en échec).")

    def test_ligne_du_bilan_dans_le_resume(self):
        self.assertEqual(self.f.objet("resume-phrase-bilan").property("text"), "4 mises à jour, 2 sessions (1 en échec).")
        self.assertEqual(self.f.objet("resume-date-bilan").property("text"), "Semaine du 9 nov.")


class SansControles(Base):
    dossier = "vide"

    def test_etat_vide(self):
        self.ouvrir_onglet("controles")
        self.assertTrue(self.f.objet("controles-vide").property("visible"))
        self.assertFalse(self.f.objet("carte-controles").property("visible"))

    def test_resume_sans_rien(self):
        self.assertEqual(self.f.objet("resume-phrase-controles").property("text"), "Contrôles pas encore faits")
        self.assertEqual(self.f.objet("resume-phrase-disques").property("text"), "Disques pas encore mesurés")
        self.assertEqual(self.f.objet("resume-phrase-bilan").property("text"), "Pas encore de bilan hebdomadaire.")
        self.assertEqual(self.badge("resume-badge-systeme"), ("OK", "ok"))


class Onglets(Base):
    """Fixture « complet » : un état complet (maj-apps en échec, son service aussi, 15 erreurs du journal, 23 plantages,
    Externe en sourdine)."""
    dossier = "complet"

    def fenetre(self):
        return self.f.racines[0]

    def onglets(self):
        boutons = sorted(self.f.objets("onglet-"), key=lambda o: o.property("x"))
        return [(o.objectName()[len("onglet-"):], o.property("text")) for o in boutons]

    def test_sept_onglets_resume_d_abord(self):
        self.assertEqual(self.onglets(), ONGLETS)
        self.assertEqual(self.f.objet("sante-onglets").property("courant"), "resume")
        self.assertEqual(self.fenetre().property("ongletSante"), "resume")
        self.assertIsNotNone(self.f.objet("sante-onglet-resume"))

    def test_etat_d_un_onglet_pire_gravite_active_de_son_domaine(self):
        """Seuls les points de la rubrique « sante » comptent (Ruling V68) : service:maj-apps.service (attention) →
        Système ; journal:erreurs et plantages (info) → Journal. maj:echec:maj-apps (échec) est de la rubrique majs : il
        reste à la page Mises à jour et ne colore aucun onglet de la santé."""
        etats = {cle: self.f.objet("onglet-" + cle).property("etat") for cle, _ in ONGLETS}
        self.assertEqual(etats, {"resume": "", "disques": "", "gpu": "", "systeme": "attention", "securite": "",
                                 "controles": "", "journal": "info"})
        self.assertEqual(self.f.objet("onglet-systeme").property("motEtat"), "Attention")

    def test_aucun_badge_sante_en_echec_a_cause_d_une_autre_rubrique(self):
        """Ruling V68 : l'état complet n'a qu'une alerte de santé, « Attention » ; l'échec de maj-apps
        (rubrique majs) ne fait passer ni un onglet ni une ligne du résumé en « Échec »."""
        e = json.loads((ETATS / "complet" / "etat.json").read_text(encoding="utf-8"))
        self.assertIn(("maj:echec:maj-apps:2026-11-10T09:40:22", "echec", "majs"),
                      [(p["id"], p["gravite"], p["rubrique"]) for p in e["points"]])
        for cle, _ in ONGLETS:
            self.assertNotEqual(self.f.objet("onglet-" + cle).property("etat"), "echec", cle)
        for domaine in ("disques", "gpu", "systeme", "securite", "controles", "journal"):
            self.assertNotEqual(self.badge("resume-badge-" + domaine)[1], "echec", domaine)
        self.assertEqual(self.badge("resume-badge-systeme"), ("Attention", "attention"))

    def test_clic_sur_une_ligne_du_resume_ouvre_son_onglet(self):
        for domaine in ("disques", "gpu", "systeme", "securite", "controles", "journal"):
            self.ouvrir_onglet("resume")
            self.cliquer("resume-ligne-" + domaine)
            self.assertEqual(self.fenetre().property("ongletSante"), domaine)
            self.assertIsNotNone(self.f.objet("sante-onglet-" + domaine), domaine)
            self.assertIsNone(self.f.objet("sante-onglet-resume"), domaine)

    def test_la_ligne_du_bilan_ouvre_l_onglet_systeme(self):
        self.cliquer("resume-ligne-bilan")
        self.assertEqual(self.fenetre().property("ongletSante"), "systeme")
        self.assertIsNotNone(self.f.objet("bilan-titre"))

    def test_onglet_garde_quand_on_revient_sur_la_page(self):
        self.ouvrir_onglet("journal")
        self.fenetre().setProperty("page", "accueil")
        attendre(200)
        nettoyer_emballages()
        self.assertIsNone(self.f.objet("page-sante"))
        self.fenetre().setProperty("page", "sante")
        attendre(300)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("sante-onglets").property("courant"), "journal")
        self.assertIsNotNone(self.f.objet("sante-onglet-journal"))

    def test_onglet_inconnu_montre_le_resume(self):
        self.fenetre().setProperty("ongletSante", "nulle-part")
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("sante-onglets").property("courant"), "resume")
        self.assertIsNotNone(self.f.objet("sante-onglet-resume"))

    def test_un_onglet_ne_montre_que_son_contenu(self):
        self.assertIsNone(self.f.objet("carte-controles"))
        self.assertIsNone(self.f.objet("carte-stockage"))
        self.ouvrir_onglet("controles")
        self.assertIsNotNone(self.f.objet("carte-controles"))
        for nom in ("carte-stockage", "resume-domaines", "bilan-titre", "journal-erreurs", "gpu-carte"):
            self.assertIsNone(self.f.objet(nom), nom)

    def test_resume_tient_sur_un_ecran_a_1100x720(self):
        self.assertEqual((self.fenetre().property("width"), self.fenetre().property("height")), (1100, 720))
        contenu, hauteur = self.hauteurs()
        self.assertLessEqual(contenu, hauteur + TOLERANCE_ECRAN)

    def test_chaque_onglet_tient_sur_un_ecran(self):
        """Journal compris : 10 erreurs et 23 plantages, côte à côte."""
        for cle in ("disques", "gpu", "systeme", "securite", "controles", "journal"):
            self.ouvrir_onglet(cle)
            contenu, hauteur = self.hauteurs()
            self.assertLessEqual(contenu, hauteur + TOLERANCE_ECRAN, cle)


class UnEcranAvecDesProblemes(Base):
    """Un onglet chargé de problèmes tient encore sur un écran (rien n'est retiré, les détails se resserrent)."""
    dossier = "complet"

    def setUp(self):
        self.addCleanup(nettoyer_emballages)
        e = json.loads((ETATS / "complet" / "etat.json").read_text(encoding="utf-8"))
        sec, noyau = e["sante"]["securite"], e["sante"]["noyau"]
        chemin = "/home/u/.config/autostart/outil.desktop"
        sec["ports"]["inconnus"] = [{"prog": "serveur-dev", "ports": [3000, 3001]}, {"prog": "serveur-test", "ports": [8080]}]
        sec["demarrage"]["trouves"] = [
            {"chemin": chemin, "role": "démarrage automatique", "gravite": "echec",
             "quoi": "télécharge et exécute un script", "numero": 4, "ligne": "Exec=sh -c x"},
            {"chemin": "/home/u/.config/systemd/user/outil.service", "role": "service systemd personnel",
             "gravite": "attention", "quoi": "lance un shell", "numero": 7, "ligne": "ExecStart=/bin/sh -c y"}]
        sec["ld_preload"] = ["/usr/lib/outil.so"]
        sec["temporaires"] = {"nombre": 2, "exemples": ["/tmp/a", "/tmp/b"], "examines": 40, "plafond_atteint": False}
        noyau["usb"] = {"nombre": 3, "exemples": ["usb 1-2: disconnect", "usb 1-3: reset", "usb 1-4: erreur"]}
        noyau["materiel"] = {"nombre": 2, "exemples": ["mce: erreur matérielle", "EDAC: erreur corrigée"]}
        noyau["plantages"] = {"nombre": 2, "exemples": ["outil[42]: segfault", "outil[43]: segfault"]}
        e["sante"]["memoire"]["attente"] = 30.0

        def point(id_, gravite, domaine):
            return {"id": id_, "gravite": gravite, "titre": "t", "detail": "d", "mesure": 1.0, "cran": 1.0, "action": None,
                    "en_sourdine": False, "rubrique": "sante", "domaine": domaine}
        e["points"] += [point("securite:port:serveur-dev", "attention", "securite"),
                        point("securite:port:serveur-test", "attention", "securite"),
                        point("securite:demarrage:" + chemin, "echec", "securite"),
                        point("securite:ld-preload", "echec", "securite"),
                        point("securite:temporaires", "attention", "securite"),
                        point("memoire:pression", "echec", "systeme"), point("noyau:usb", "info", "systeme"),
                        point("noyau:materiel", "attention", "systeme")]
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        (Path(self.d.name) / "etat.json").write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
        self.f = Fenetre(Path(self.d.name), "sante")
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())

    def test_chaque_onglet_tient_sur_un_ecran_avec_des_problemes(self):
        for cle in ("securite", "systeme", "journal"):
            self.cliquer("onglet-" + cle)
            self.assertEqual(self.f.objet("sante-onglets").property("courant"), cle)
            page = self.f.objet("page-sante")
            if cle == "journal":
                self.assertTrue(self.f.objet("journal-plantages-noyau").property("visible"))
            self.assertLessEqual(page.property("contentHeight"), page.property("height") + TOLERANCE_ECRAN, cle)


class Securite(Base):
    """Onglet Sécurité (Task 8) : quatre cartes ; l'état d'une ligne vient du point `securite:*` (jamais d'un seuil
    recalculé par le QML), sinon « ok » ; une mesure illisible (null) vaut « Vérification impossible »."""
    dossier = "complet"

    def setUp(self):
        self.addCleanup(nettoyer_emballages)       # la fenêtre s'ouvre dans ouvrir(), avec la sécurité voulue

    def securite(self):
        e = json.loads((ETATS / "complet" / "etat.json").read_text(encoding="utf-8"))
        return e["sante"]["securite"], e["points"]

    def ouvrir(self, **sec):
        """Rouvre la fenêtre sur « complet » dont `sante.securite` a ces champs remplacés (`points` : ajoutés)."""
        points = sec.pop("points", [])
        s, pts = self.securite()
        if s is not None:
            s.update(sec)
        self.f = Fenetre(variante(self, "complet", securite=s, points=pts + points), "sante")
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())

    @staticmethod
    def point(id_, gravite, titre="t"):
        return {"id": id_, "gravite": gravite, "titre": titre, "detail": "d", "mesure": 1.0, "cran": 1.0, "action": None,
                "en_sourdine": False, "rubrique": "sante", "domaine": "securite"}

    def problemes(self):
        self.ouvrir(
            ports={"inconnus": [{"prog": "serveur-dev", "ports": [3000, 3001]}], "connus": [], "systeme": []},
            demarrage={"lus": 31, "incomplet": False, "trouves": [
                {"chemin": "/home/u/.config/autostart/outil.desktop", "role": "démarrage automatique",
                 "gravite": "echec", "quoi": "télécharge et exécute un script", "numero": 4, "ligne": "Exec=sh -c x"}]},
            temporaires={"nombre": 2, "exemples": ["/tmp/a", "/tmp/b"], "examines": 40, "plafond_atteint": False},
            points=[self.point("securite:port:serveur-dev", "attention"),
                    self.point("securite:demarrage:/home/u/.config/autostart/outil.desktop", "echec"),
                    self.point("securite:temporaires", "attention")])
        self.ouvrir_onglet("securite")

    def test_securite_tout_va_bien(self):
        self.ouvrir()
        self.ouvrir_onglet("securite")
        self.assertIsNotNone(self.f.objet("sante-onglet-securite"))
        for carte in ("pare-feu", "ports", "demarrage", "temporaires"):
            self.assertIsNotNone(self.f.objet("securite-" + carte), carte)
        self.assertEqual(self.badge("ligne-pare-feu"), ("Actif", "ok"))
        detail = self.f.objet("ligne-pare-feu-detail").property("text")
        self.assertIn("FedoraWorkstation", detail)
        self.assertIn("1024", detail)
        self.assertTrue(self.absent("ports-aucun"), "ports-aucun")
        self.assertEqual(self.badge("ports-autres")[1], "info")
        self.assertRegex(self.badge("ports-autres")[0], r"^\d+ (programmes?|ports?)$")
        self.assertEqual(self.badge("demarrage-ok"), ("Rien de suspect", "ok"))
        self.assertIn("31 fichiers lus", self.f.objet("demarrage-ok-detail").property("text"))
        self.assertEqual(self.badge("ligne-temporaires")[1], "ok")
        self.assertEqual(self.badge("ligne-cache")[1], "info")
        self.assertIn("uv", self.f.objet("ligne-cache-detail").property("text"))
        self.assertEqual(self.f.objet("onglet-securite").property("etat"), "")

    def test_securite_autres_ports_ne_somme_pas_programmes_et_ports(self):
        self.ouvrir(ports={"inconnus": [], "connus": [{"prog": "outil", "ports": [1234]}], "systeme": [5000, 5001]})
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("ports-autres"), ("1 programme", "info"))

    def test_securite_aucun_port_expose(self):
        self.ouvrir(ports={"inconnus": [], "connus": [], "systeme": []})
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("ports-aucun"), ("Aucun", "ok"))
        self.assertTrue(self.absent("ports-autres"), "ports-autres")

    def test_securite_pare_feu_arrete(self):
        self.ouvrir(pare_feu={"actif": False, "zone": None, "ports": [], "services": [], "ouvre_hauts": False},
                    points=[self.point("securite:pare-feu", "attention")])
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("ligne-pare-feu"), ("Arrêté", "attention"))

    def test_securite_ld_preload_ligne_en_plus(self):
        self.ouvrir(ld_preload=["/usr/lib/outil.so"], points=[self.point("securite:ld-preload", "echec")])
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("demarrage-ld-preload")[1], "echec")
        self.assertEqual(self.badge("demarrage-ok"), ("Rien de suspect", "ok"))

    def test_securite_problemes(self):
        self.problemes()
        self.assertEqual(self.badge("port-0"), ("Attention", "attention"))
        self.assertIn("3000", self.f.objet("port-0-detail").property("text"))
        self.assertEqual(self.badge("demarrage-0"), ("Échec", "echec"))
        self.assertTrue(self.absent("demarrage-ok"), "demarrage-ok")
        self.assertEqual(self.badge("ligne-temporaires"), ("2 programmes", "attention"))
        self.assertEqual(self.f.objet("onglet-securite").property("etat"), "echec")
        self.ouvrir_onglet("resume")
        self.assertEqual(self.badge("resume-badge-securite"), ("Échec", "echec"))

    def test_securite_sous_mesure_illisible(self):
        self.ouvrir(ports=None)
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("ports-impossible"), ("Vérification impossible", "neutre"))
        self.assertTrue(self.absent("ports-aucun"), "ports-aucun")
        self.assertEqual(self.badge("ligne-pare-feu"), ("Actif", "ok"))
        self.assertEqual(self.badge("demarrage-ok"), ("Rien de suspect", "ok"))
        self.assertEqual(self.badge("ligne-temporaires")[1], "ok")

    def test_securite_toute_mesure_illisible(self):
        self.ouvrir(pare_feu=None, ports=None, demarrage=None, temporaires=None, cache=None)
        self.ouvrir_onglet("securite")
        for nom in ("ligne-pare-feu", "ports-impossible", "demarrage-impossible", "ligne-temporaires", "ligne-cache"):
            self.assertEqual(self.badge(nom), ("Vérification impossible", "neutre"), nom)

    def sourdine(self, id_, gravite="attention"):
        p = self.point(id_, gravite)
        p["en_sourdine"] = True
        return p

    def test_temporaires_en_sourdine_ligne_neutre(self):
        """Ruling 9 : un point en sourdine n'est plus signalé, mais la ligne ne dit pas « OK » ; le détail reste."""
        self.ouvrir(temporaires={"nombre": 2, "exemples": ["/tmp/a", "/tmp/b"], "examines": 40, "plafond_atteint": False},
                    points=[self.sourdine("securite:temporaires")])
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("ligne-temporaires"), ("En sourdine", "neutre"))
        self.assertIn("/tmp/a", self.f.objet("ligne-temporaires-detail").property("text"))
        self.assertEqual(self.f.objet("onglet-securite").property("etat"), "")

    def test_port_en_sourdine_ligne_neutre(self):
        self.ouvrir(ports={"inconnus": [{"prog": "serveur-dev", "ports": [3000]}], "connus": [], "systeme": []},
                    points=[self.sourdine("securite:port:serveur-dev")])
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("port-0"), ("En sourdine", "neutre"))
        self.assertIn("3000", self.f.objet("port-0-detail").property("text"))
        self.assertEqual(self.f.objet("onglet-securite").property("etat"), "")

    def test_port_au_nom_voisin_n_herite_pas_du_point(self):
        """Le point est celui de l'id exact : `serveur` n'hérite pas de `securite:port:serveur-dev`."""
        self.ouvrir(ports={"inconnus": [{"prog": "serveur", "ports": [3000]}, {"prog": "serveur-dev", "ports": [3001]}],
                           "connus": [], "systeme": []},
                    points=[self.point("securite:port:serveur-dev", "attention")])
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("port-0"), ("OK", "ok"))
        self.assertEqual(self.badge("port-1"), ("Attention", "attention"))

    def test_securite_absente_quatre_cartes_impossibles(self):
        self.f = Fenetre(variante(self, "complet", securite=None), "sante")
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())
        self.ouvrir_onglet("securite")
        for nom in ("ligne-pare-feu", "ports-impossible", "demarrage-impossible", "ligne-temporaires"):
            self.assertEqual(self.badge(nom), ("Vérification impossible", "neutre"), nom)
        self.assertEqual(self.f.objet("onglet-securite").property("etat"), "")

    def test_resume_phrase_securite(self):
        self.ouvrir()
        self.assertEqual(self.f.objet("resume-phrase-securite").property("text"),
                         "Pare-feu actif · aucun serveur inconnu · rien de suspect au démarrage")
        self.assertEqual(self.badge("resume-badge-securite"), ("OK", "ok"))

    def test_resume_phrase_securite_avec_problemes(self):
        self.problemes()
        self.ouvrir_onglet("resume")
        phrase = self.f.objet("resume-phrase-securite").property("text")
        self.assertIn("1 serveur inconnu ouvert au réseau", phrase)
        self.assertIn("2 programmes dans les dossiers temporaires", phrase)
        self.assertIn("1 fichier suspect au démarrage", phrase)

    def test_resume_phrase_demarrage_lu_en_partie(self):
        """Démarrage incomplet sans trouvaille : on ne promet pas « rien de suspect »."""
        self.ouvrir(demarrage={"lus": 12, "incomplet": True, "trouves": []})
        phrase = self.f.objet("resume-phrase-securite").property("text")
        self.assertIn("démarrage lu en partie", phrase)
        self.assertNotIn("rien de suspect", phrase)

    def test_resume_phrase_demarrage_incomplet_avec_trouvaille(self):
        self.ouvrir(demarrage={"lus": 12, "incomplet": True, "trouves": [
            {"chemin": "/home/u/.config/autostart/outil.desktop", "role": "démarrage automatique",
             "gravite": "echec", "quoi": "télécharge et exécute un script", "numero": 4, "ligne": "Exec=sh -c x"}]},
            points=[self.point("securite:demarrage:/home/u/.config/autostart/outil.desktop", "echec")])
        self.assertIn("1 fichier suspect au démarrage", self.f.objet("resume-phrase-securite").property("text"))
        self.ouvrir_onglet("securite")
        self.assertEqual(self.badge("demarrage-0"), ("Échec", "echec"))


class NoyauEtMemoire(Base):
    """Task 9 : le noyau et la mémoire dans GPU et jeux, Système, Journal et le Résumé. L'état d'une ligne vient du point
    `noyau:*` ou `memoire:*` (jamais d'un seuil recalculé par le QML), sinon « ok »."""
    dossier = "complet"

    def setUp(self):
        self.addCleanup(nettoyer_emballages)

    def ouvrir(self, onglet=None, points=(), **sante):
        """Rouvre « complet » dont ces champs de `sante` sont remplacés (`noyau` et `memoire` : fusionnés champ à champ)."""
        e = json.loads((ETATS / "complet" / "etat.json").read_text(encoding="utf-8"))
        for cle, valeur in sante.items():
            if isinstance(valeur, dict) and isinstance(e["sante"].get(cle), dict):
                e["sante"][cle].update(valeur)
            else:
                e["sante"][cle] = valeur
        self.f = Fenetre(variante(self, "complet", **{k: e["sante"][k] for k in sante}, points=e["points"] + list(points)),
                         "sante")
        self.addCleanup(self.f.fermer)
        self.addCleanup(lambda: self.f.pont._minuteur.stop())
        if onglet:
            self.cliquer("onglet-" + onglet)

    @staticmethod
    def point(id_, gravite, domaine):
        return {"id": id_, "gravite": gravite, "titre": "t", "detail": "d", "mesure": 1.0, "cran": 1.0, "action": None,
                "en_sourdine": False, "rubrique": "sante", "domaine": domaine}

    def texte(self, nom):
        return self.f.objet(nom).property("text")

    def test_gpu_noyau(self):
        self.ouvrir("gpu")
        self.assertEqual(self.badge("gpu-noyau"), ("Aucune", "ok"))
        self.assertIn("Erreurs du pilote (noyau)", self.texte("gpu-noyau-libelle"))

    def test_gpu_noyau_erreurs_d_application(self):
        self.ouvrir("gpu", noyau={"gpu": {"nombre": 2, "graves": 0, "chute": False, "exemples": ["Xid 13"]}},
                    points=[self.point("noyau:gpu", "info", "gpu")])
        self.assertEqual(self.badge("gpu-noyau"), ("2 erreurs", "info"))
        self.assertIn("causées par une application", self.texte("gpu-noyau-detail"))

    def test_gpu_noyau_graves(self):
        self.ouvrir("gpu", noyau={"gpu": {"nombre": 2, "graves": 1, "chute": False, "exemples": ["Xid 31 sur pci:0000"]}},
                    points=[self.point("noyau:gpu", "attention", "gpu")])
        self.assertEqual(self.badge("gpu-noyau"), ("2 erreurs", "attention"))
        self.assertIn("Xid 31 sur pci:0000", self.texte("gpu-noyau-detail"))

    def test_gpu_noyau_illisible(self):
        self.ouvrir("gpu", noyau=None)
        self.assertEqual(self.badge("gpu-noyau"), ("Vérification impossible", "neutre"))

    def test_systeme_memoire(self):
        self.ouvrir("systeme")
        self.assertEqual(self.badge("ligne-memoire")[1], "ok")
        detail = self.texte("ligne-memoire-detail")
        for mot in ("disponibles", "attente", "zram"):
            self.assertIn(mot, detail)

    def test_systeme_memoire_swap_rempli_est_normal_avec_zram(self):
        self.ouvrir("systeme", memoire={"swap_utilise": 5153960755, "attente": None})
        self.assertEqual(self.badge("ligne-memoire")[1], "ok")
        self.assertIn("normal avec zram", self.texte("ligne-memoire-detail"))

    def test_systeme_memoire_juste(self):
        self.ouvrir("systeme", memoire={"attente": 6.5}, points=[self.point("memoire:pression", "attention", "systeme")])
        self.assertEqual(self.badge("ligne-memoire"), ("Juste", "attention"))

    def test_systeme_memoire_saturee(self):
        self.ouvrir("systeme", memoire={"attente": 30.0}, points=[self.point("memoire:pression", "echec", "systeme")])
        self.assertEqual(self.badge("ligne-memoire"), ("Saturée", "echec"))

    def test_systeme_memoire_pression_et_sans_swap_le_pire(self):
        self.ouvrir("systeme", memoire={"swap_total": 0, "swap_utilise": 0, "zram": [], "attente": 30.0},
                    points=[self.point("memoire:pression", "echec", "systeme"),
                            self.point("memoire:sans-swap", "attention", "systeme")])
        self.assertEqual(self.badge("ligne-memoire"), ("Saturée", "echec"))
        self.assertIn("swap", self.texte("ligne-memoire-detail"))

    def test_systeme_memoire_pression_attention_et_sans_swap(self):
        self.ouvrir("systeme", memoire={"swap_total": 0, "swap_utilise": 0, "zram": [], "attente": 6.5},
                    points=[self.point("memoire:pression", "attention", "systeme"),
                            self.point("memoire:sans-swap", "attention", "systeme")])
        self.assertEqual(self.badge("ligne-memoire"), ("Juste", "attention"))
        self.assertIn("swap", self.texte("ligne-memoire-detail"))

    def test_systeme_memoire_sourdine_de_la_pression_garde_sans_swap(self):
        pression = self.point("memoire:pression", "echec", "systeme")
        pression["en_sourdine"] = True
        self.ouvrir("systeme", memoire={"swap_total": 0, "swap_utilise": 0, "zram": []},
                    points=[pression, self.point("memoire:sans-swap", "attention", "systeme")])
        self.assertEqual(self.badge("ligne-memoire"), ("Sans swap", "attention"))

    def test_systeme_memoire_en_sourdine(self):
        p = self.point("memoire:pression", "attention", "systeme")
        p["en_sourdine"] = True
        self.ouvrir("systeme", memoire={"attente": 6.5}, points=[p])
        self.assertEqual(self.badge("ligne-memoire"), ("En sourdine", "neutre"))
        self.assertIn("disponibles", self.texte("ligne-memoire-detail"))

    def test_systeme_usb_en_sourdine(self):
        p = self.point("noyau:usb", "info", "systeme")
        p["en_sourdine"] = True
        self.ouvrir("systeme", noyau={"usb": {"nombre": 3, "exemples": ["usb 1-2: disconnect"]}}, points=[p])
        self.assertEqual(self.badge("ligne-usb"), ("En sourdine", "neutre"))
        self.assertIn("usb 1-2: disconnect", self.texte("ligne-usb-detail"))

    def test_systeme_memoire_sans_swap(self):
        self.ouvrir("systeme", memoire={"swap_total": 0, "swap_utilise": 0, "zram": []},
                    points=[self.point("memoire:sans-swap", "attention", "systeme")])
        self.assertEqual(self.badge("ligne-memoire")[1], "attention")

    def test_systeme_memoire_illisible(self):
        self.ouvrir("systeme", memoire=None)
        self.assertEqual(self.badge("ligne-memoire"), ("Vérification impossible", "neutre"))

    def test_systeme_materiel(self):
        self.ouvrir("systeme")
        self.assertEqual(self.badge("ligne-mce"), ("Aucune", "ok"))
        self.assertEqual(self.badge("ligne-usb"), ("Aucune", "ok"))
        self.assertIn("Processeur et mémoire (MCE/EDAC)", self.texte("ligne-mce-libelle"))
        self.assertEqual(self.texte("ligne-usb-libelle"), "USB")

    def test_systeme_materiel_usb(self):
        self.ouvrir("systeme", noyau={"usb": {"nombre": 3, "exemples": ["usb 1-2: disconnect"]}},
                    points=[self.point("noyau:usb", "info", "systeme")])
        self.assertEqual(self.badge("ligne-usb"), ("3 erreurs", "info"))
        self.assertIn("usb 1-2: disconnect", self.texte("ligne-usb-detail"))
        self.assertEqual(self.badge("ligne-mce"), ("Aucune", "ok"))

    def test_systeme_materiel_illisible(self):
        self.ouvrir("systeme", noyau=None)
        for nom in ("ligne-mce", "ligne-usb"):
            self.assertEqual(self.badge(nom), ("Vérification impossible", "neutre"), nom)

    def test_memoire_et_materiel_cote_a_cote(self):
        self.ouvrir("systeme")
        page = self.f.objet("page-sante")
        m = self.f.objet("systeme-memoire").mapToItem(page, 0, 0)
        h = self.f.objet("systeme-materiel").mapToItem(page, 0, 0)
        self.assertGreater(h.x(), m.x() + 200)
        self.assertAlmostEqual(h.y(), m.y(), delta=2)

    def test_journal_plantages_du_noyau(self):
        self.ouvrir("journal", noyau={"plantages": {"nombre": 2, "exemples": ["outil[42]: segfault"]}})
        self.assertEqual(self.texte("journal-plantages-noyau"), "2 plantages vus par le noyau")
        self.assertTrue(self.f.objet("journal-plantages-noyau").property("visible"))

    def test_journal_sans_plantage_du_noyau(self):
        self.ouvrir("journal")
        self.assertTrue(self.absent("journal-plantages-noyau"))

    def test_resume_phrases(self):
        self.ouvrir()
        self.assertEqual(self.texte("resume-phrase-systeme"),
                         "1 service en échec : maj-apps.service · mémoire : 24 Go libres")
        self.assertNotIn("Xid", self.texte("resume-phrase-gpu"))
        disques = self.texte("resume-phrase-disques")
        self.ouvrir(noyau={"gpu": {"nombre": 2, "graves": 0, "chute": False, "exemples": []}})
        self.assertIn("2 erreurs du pilote graphique", self.texte("resume-phrase-gpu"))
        self.assertEqual(self.texte("resume-phrase-disques"), disques)

    def test_resume_phrases_sans_memoire(self):
        self.ouvrir(memoire=None)
        self.assertNotIn("mémoire", self.texte("resume-phrase-systeme"))


class Resume(Base):
    dossier = "complet"

    def phrase(self, domaine):
        return self.f.objet("resume-phrase-" + domaine).property("text")

    def test_a_regarder_de_la_sante_en_tete(self):
        liste = self.f.objet("a-regarder-sante")
        self.assertTrue(liste.property("visible"))
        lignes = [o.objectName()[len("a-regarder-ligne-"):] for o in self.f.objets("a-regarder-ligne-")]
        self.assertEqual(lignes, ["service:maj-apps.service"])
        page = self.f.objet("page-sante")
        domaines = self.f.objet("resume-domaines")
        self.assertLess(liste.mapToItem(page, 0, liste.property("height")).y(), domaines.mapToItem(page, 0, 0).y())

    def test_une_phrase_par_domaine_avec_sa_mesure_cle(self):
        self.assertEqual(self.phrase("disques"), "NVMe Exemple Z1 usé à 1 %, 35 °C")
        self.assertEqual(self.phrase("gpu"), "NVIDIA GeForce RTX 4070, 38 °C · Ollama arrêté · 9 gels")
        self.assertEqual(self.phrase("systeme"), "1 service en échec : maj-apps.service · mémoire : 24 Go libres")
        self.assertEqual(self.phrase("controles"), "Image à jour · 0 runtime inutilisé")
        self.assertEqual(self.phrase("journal"), "15 erreurs · 23 plantages")

    def test_etat_de_chaque_domaine_ecrit(self):
        attendu = {"disques": ("OK", "ok"), "gpu": ("OK", "ok"), "systeme": ("Attention", "attention"),
                   "controles": ("OK", "ok"), "journal": ("Info", "info")}
        for domaine, badge in attendu.items():
            self.assertEqual(self.badge("resume-badge-" + domaine), badge, domaine)

    def test_bilan_de_la_semaine(self):
        self.assertEqual(self.phrase("bilan"), "19 mises à jour, 2 sessions (0 en échec).")
        self.assertEqual(self.f.objet("resume-date-bilan").property("text"), "Semaine du 3 nov.")

    def test_pas_de_ligne_de_sourdines_sans_sourdine_de_la_sante(self):
        """Externe est en sourdine, mais c'est un point de Stockage : la santé n'en a aucun."""
        self.assertFalse(self.f.objet("resume-ligne-sourdines").property("visible"))


class ResumeControles(Base):
    """Fixture « controles » : Données non monté, 3 erreurs d'E/S, une image et deux Flatpak disponibles, 3 runtimes."""

    def test_phrases(self):
        self.assertEqual(self.f.objet("resume-phrase-disques").property("text"),
                         "NVMe Exemple Z1 usé à 1 %, 38 °C · 3 erreurs d'E/S")
        self.assertEqual(self.f.objet("resume-phrase-controles").property("text"),
                         "Bazzite 45.20261110 disponible · 2 Flatpak à mettre à jour · 3 runtimes inutilisés")
        self.assertEqual(self.f.objet("resume-phrase-systeme").property("text"),
                         "Aucun service en échec · mémoire : 24 Go libres")
        self.assertEqual(self.f.objet("resume-phrase-gpu").property("text").count("Xid"), 0)

    def test_resume_disques_coherent_avec_son_badge(self):
        """Task 9 : la phrase ne cite que ce que compte son badge. « Non monté » est un point de Stockage : il reste
        dans Stockage et son compteur, pas dans cette ligne, dont le badge dit « OK »."""
        phrase = self.f.objet("resume-phrase-disques").property("text")
        self.assertNotIn("non monté", phrase)
        self.assertNotIn("/var/mnt/DONNEES", phrase)
        self.assertEqual(self.badge("resume-badge-disques"), ("OK", "ok"))

    def test_badges_seulement_de_la_rubrique_sante(self):
        """Ruling V68 : Données non monté, les erreurs d'E/S, le ménage et les mises à jour disponibles sont des points de
        Stockage et de Mises à jour : ils restent sur leur page (la carte « Stockage » de l'onglet Disques les écrit
        toujours) et ne colorent aucun badge de la santé."""
        for domaine in ("disques", "gpu", "systeme", "controles", "journal"):
            self.assertEqual(self.badge("resume-badge-" + domaine), ("OK", "ok"), domaine)
            self.assertEqual(self.f.objet("onglet-" + domaine).property("etat"), "", domaine)


class AutresRubriques(Base):
    """Fixture « a-regarder » : Données non monté et Externe (échec, Stockage), un redémarrage (Mises à jour), et un seul point
    de santé, deploiements:trop (attention, Contrôles)."""
    dossier = "a-regarder"

    def test_seul_le_point_de_sante_colore_son_onglet(self):
        etats = {cle: self.f.objet("onglet-" + cle).property("etat") for cle, _ in ONGLETS}
        self.assertEqual(etats, {"resume": "", "disques": "", "gpu": "", "systeme": "", "securite": "",
                                 "controles": "attention", "journal": ""})
        self.assertEqual(self.badge("resume-badge-controles"), ("Attention", "attention"))
        self.assertEqual(self.badge("resume-badge-disques"), ("OK", "ok"))
        self.assertEqual(self.badge("resume-badge-systeme"), ("OK", "ok"))


class LigneDesSourdines(Base):
    """Ruling V68 : les points de santé en sourdine se voient depuis le résumé ; un clic ouvre l'onglet Journal, où ils
    ont « Signaler à nouveau »."""

    def setUp(self):
        self.addCleanup(nettoyer_emballages)
        e = json.loads((ETATS / "a-regarder" / "etat.json").read_text(encoding="utf-8"))
        points = [dict(p, en_sourdine=True) if p["id"] == "deploiements:trop" else p for p in e["points"]]
        self.f = Fenetre(variante(self, "a-regarder", points=points), "sante")
        self.addCleanup(self.f.fermer)

    def test_une_ligne_n_en_sourdine(self):
        ligne = self.f.objet("resume-ligne-sourdines")
        self.assertTrue(ligne.property("visible"))
        ligne = None
        # menage:journal est aussi en sourdine, mais c'est un point de Stockage : il n'est pas compté.
        self.assertEqual(self.f.objet("resume-nom-sourdines").property("text"), "1 en sourdine")
        self.assertEqual(self.f.objet("resume-phrase-sourdines").property("text"),
                         "3 déploiements sont conservés")
        self.assertEqual(self.badge("resume-badge-controles"), ("OK", "ok"))     # la sourdine ne colore plus rien

    def test_clic_ouvre_l_onglet_journal(self):
        self.cliquer("resume-ligne-sourdines")
        self.assertEqual(self.f.racines[0].property("ongletSante"), "journal")
        self.assertTrue(self.f.objet("sourdine-deploiements:trop").property("visible"))


class Journal(Base):
    dossier = "complet"

    def setUp(self):
        super().setUp()
        self.ouvrir_onglet("journal")

    def test_erreurs_et_plantages_cote_a_cote(self):
        page = self.f.objet("page-sante")
        erreurs = self.f.objet("journal-erreurs").mapToItem(page, 0, 0)
        plantages = self.f.objet("journal-plantages").mapToItem(page, 0, 0)
        self.assertGreater(plantages.x(), erreurs.x() + 200)
        self.assertAlmostEqual(plantages.y(), erreurs.y(), delta=2)
        self.assertEqual(len(self.f.objets("journal-erreur-")), 10)
        self.assertEqual(len(self.f.objets("journal-plantage-")), 23)

    def test_plantages_les_plus_recents_d_abord(self):
        lignes = sorted(self.f.objets("journal-plantage-"), key=lambda o: o.property("y"))
        self.assertEqual(lignes[0].objectName(), "journal-plantage-0")
        e = json.loads((ETATS / "complet" / "etat.json").read_text(encoding="utf-8"))
        dernier = max(e["sante"]["plantages"], key=lambda p: p["date"])
        self.assertEqual(self.f.objet("journal-exe-0").property("text"), dernier["exe"])

    def test_pour_information(self):
        self.assertTrue(self.f.objet("journal-pour-information").property("visible"))


class SourdinesDeLaSante(Base):
    """Les points de santé mis en sourdine vivent dans l'onglet Journal, avec « Signaler à nouveau » ; pas ceux de
    Stockage (leur page les montre)."""

    def setUp(self):
        self.addCleanup(nettoyer_emballages)
        e = json.loads((ETATS / "a-regarder" / "etat.json").read_text(encoding="utf-8"))
        points = [dict(p, en_sourdine=True) if p["id"] == "deploiements:trop" else p for p in e["points"]]
        self.f = Fenetre(variante(self, "a-regarder", points=points), "sante")
        self.addCleanup(self.f.fermer)

    def test_dans_l_onglet_journal(self):
        self.assertIsNone(self.f.objet("sourdine-deploiements:trop"))
        self.ouvrir_onglet("journal")
        self.assertTrue(self.f.objet("sourdine-deploiements:trop").property("visible"))
        self.assertIsNone(self.f.objet("sourdine-menage:journal"))


class GelsRenvoyesVersJeux(Base):
    """Task 7 : le détail des gels vit dans la page Jeux (D16) ; l'onglet GPU et jeux garde leur compte et y renvoie.
    Fixture « complet » : 9 gels."""
    dossier = "complet"

    def setUp(self):
        self.appels = []
        faux = mock.patch.object(QProcess, "startDetached",
                                 lambda prog, args: self.appels.append([prog] + list(args)) or (True, 1))
        faux.start()
        self.addCleanup(faux.stop)
        super().setUp()
        self.ouvrir_onglet("gpu")

    def test_ligne_des_gels_garde_le_compte_et_le_badge(self):
        self.assertEqual(self.f.objet("gels-sante").property("text"), "9 captures de gel")
        self.assertEqual(self.badge("gels-sante-badge"), ("9 gels", "attention"))
        self.assertEqual(self.f.objet("voir-gels").property("text"), "Voir dans Jeux")

    def test_sante_gpu_renvoie_vers_jeux(self):
        self.cliquer("voir-gels")
        fenetre = self.f.racines[0]
        self.assertEqual((fenetre.property("page"), fenetre.property("ongletJeux")), ("jeux", "gels"))
        attendre(300)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("jeux-onglets").property("courant"), "gels")
        self.assertIn(["centre-bazzite", "jeux"], self.appels)          # remplacé : rien n'est lancé pour de bon


class SansGels(unittest.TestCase):
    def test_aucune_capture(self):
        self.addCleanup(nettoyer_emballages)
        self.f = Fenetre(variante(self, "controles", gels={"nombre": 0, "dernier": None}), "sante")
        self.addCleanup(self.f.fermer)
        QMetaObject.invokeMethod(self.f.objet("onglet-gpu"), "clicked", Qt.DirectConnection)
        attendre(150)
        nettoyer_emballages()
        self.assertEqual(self.f.objet("gels-sante").property("text"), "Aucune capture de gel")
        badge = self.f.objet("gels-sante-badge")
        self.assertEqual((badge.property("visible"), badge.property("texte"), badge.property("etat")),
                         (True, "Aucun gel", "ok"))
        badge = None
        self.assertEqual(self.f.objet("voir-gels").property("text"), "Voir dans Jeux")


if __name__ == "__main__":
    unittest.main()
