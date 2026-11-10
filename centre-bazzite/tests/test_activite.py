"""Panneau Activité : Main.qml chargé pour de vrai (QT_QPA_PLATFORM=offscreen), avec l'état de fixture « activite »
ou un dossier temporaire quand l'état doit changer en cours de test."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent / "fenetre"))

from tests.test_menu import Base as BaseMenu, attendre  # noqa: E402


class Base(BaseMenu):
    dossier = "activite"
    largeur = 1100

    def ouvrir(self):
        self.fenetre.setProperty("activiteOuverte", True)
        attendre(500)

    def cartes(self):
        return self.f.objets("tache-carte-")


class Panneau(Base):
    def test_panneau_ferme_au_depart(self):
        self.assertFalse(self.fenetre.property("activiteOuverte"))
        self.assertFalse(self.visible("activite-panneau"))

    def test_bascule_du_menu_ouvre_et_ferme_le_panneau(self):
        self.cliquer("menu-activite")
        self.assertTrue(self.fenetre.property("activiteOuverte"))
        attendre(500)
        self.assertTrue(self.visible("activite-panneau"))
        self.cliquer("menu-activite")
        attendre(500)
        self.assertFalse(self.visible("activite-panneau"))

    def test_bouton_de_fermeture(self):
        self.ouvrir()
        self.cliquer("activite-fermer")
        self.assertFalse(self.fenetre.property("activiteOuverte"))

    def test_badge_du_menu_compte_les_taches_en_cours(self):
        # La session « Tout mettre à jour » et l'analyse : deux tâches en cours ; le ménage est en échec.
        self.assertEqual(self.f.objet("menu-activite-badge").property("texte"), "2 en cours")

    def test_badge_du_menu_a_cote_du_mot_sans_le_chevaucher(self):
        bouton, badge = self.f.objet("menu-activite"), self.f.objet("menu-activite-badge")
        self.assertTrue(badge.property("visible"))
        self.assertGreaterEqual(badge.x(), bouton.x() + bouton.width())      # le badge commence après le bouton
        self.assertLessEqual(badge.x() + badge.width(), self.f.objet("menu-lateral").width())

    def test_cartes_des_taches_du_fixture(self):
        self.ouvrir()
        self.assertEqual(len(self.cartes()), 3)
        carte = self.f.objet("tache-carte-maj:2026-11-09T14:52:00")
        self.assertEqual(carte.property("tache")["titre"], "Tout mettre à jour")

    def test_badges_de_statut_en_toutes_lettres(self):
        self.ouvrir()
        mots = {c.property("tache")["id"]: self.f.objet("tache-statut-" + c.property("tache")["id"]).property("texte")
                for c in self.cartes()}
        self.assertEqual(mots, {"maj:2026-11-09T14:52:00": "En cours", "analyse:/var/mnt/DONNEES": "En cours",
                                "menage:caches": "Échec"})

    def test_progression_indeterminee_pour_l_analyse(self):
        self.ouvrir()
        self.assertLess(self.f.objet("tache-progression-analyse:/var/mnt/DONNEES").property("valeur"), 0)
        self.assertAlmostEqual(self.f.objet("tache-progression-maj:2026-11-09T14:52:00").property("valeur"), 0.4)

    def test_arreter_l_analyse_depuis_sa_carte(self):
        """Task 16b : un bouton plat « Arrêter l'analyse » sur la carte d'une analyse en cours, et seulement là."""
        self.ouvrir()
        bouton = self.f.objet("tache-arreter-analyse:/var/mnt/DONNEES")
        self.assertIsNotNone(bouton)
        self.assertTrue(bouton.property("visible"))
        self.assertEqual(bouton.property("text"), "Arrêter l'analyse")
        self.assertTrue(bouton.property("flat"))
        for autre in ("menage:caches", "maj:2026-11-09T14:52:00"):
            self.assertIsNotNone(self.f.objet("tache-arreter-" + autre), autre)
            self.assertFalse(self.visible("tache-arreter-" + autre), autre)
        self.cliquer("tache-arreter-analyse:/var/mnt/DONNEES")
        self.assertIn(["centre-bazzite", "analyser", "--arreter"], self.appels)

    def test_pas_d_arret_pour_une_analyse_finie(self):
        self.f.pont._taches = [dict(t, statut="fini") if t["id"].startswith("analyse:") else t
                               for t in self.f.pont.taches]
        self.f.pont.tachesChange.emit()
        self.ouvrir()
        self.assertIsNotNone(self.f.objet("tache-arreter-analyse:/var/mnt/DONNEES"))
        self.assertFalse(self.visible("tache-arreter-analyse:/var/mnt/DONNEES"))

    def test_replier_une_carte_cache_les_etapes_et_le_journal(self):
        self.ouvrir()
        self.assertFalse(self.visible("tache-details-menage:caches"))
        self.cliquer("tache-bascule-menage:caches")
        self.assertTrue(self.visible("tache-details-menage:caches"))
        self.assertTrue(self.visible("tache-copier-menage:caches"))

    def test_copier_le_journal(self):
        copies = []
        self.f.pont._presse_papiers = type("P", (), {"setText": lambda s, t: copies.append(t)})()
        self.ouvrir()
        self.cliquer("tache-bascule-menage:caches")
        self.cliquer("tache-copier-menage:caches")
        self.assertEqual(copies, ["Suppression des miniatures : 120 Mo libérés\nSuppression de ~/.cache/vieux\n"
                                  "Erreur : permission refusée"])

    def test_effacer_terminees_lance_la_cli(self):
        self.ouvrir()
        self.cliquer("activite-effacer")
        self.assertIn(["centre-bazzite", "taches", "--effacer"], self.appels)

    def test_menu_se_replie_en_rail_sous_le_panneau(self):
        self.assertTrue(self.fenetre.property("menuDeplie"))      # 1100 px sans panneau : assez large
        self.ouvrir()
        self.assertFalse(self.fenetre.property("menuDeplie"))


class Rail(Base):
    largeur = 800

    def test_pastille_du_rail_reste_dans_le_bouton(self):
        bouton, pastille = self.f.objet("menu-activite"), self.f.objet("menu-activite-pastille")
        self.assertTrue(pastille.property("visible"))
        self.assertLessEqual(pastille.x() + pastille.width(), bouton.width())
        self.assertGreaterEqual(pastille.y(), 0)


class Journal(Base):
    def test_le_journal_affiche_les_douze_dernieres_lignes(self):
        self.f.pont._taches = [dict(self.f.pont.taches[0], id="x:y", statut="fini",
                                    journal=[f"ligne {i}" for i in range(30)], etapes=[])]
        self.f.pont.tachesChange.emit()
        self.ouvrir()
        self.cliquer("tache-bascule-x:y")
        texte = self.f.objet("tache-journal-x:y").property("text")
        self.assertEqual(texte.split("\n"), [f"ligne {i}" for i in range(18, 30)])


class Vide(Base):
    dossier = "vide"

    def test_etat_vide_sans_tache(self):
        self.ouvrir()
        self.assertEqual(self.cartes(), [])
        self.assertTrue(self.visible("activite-vide"))
        self.assertEqual(self.f.objet("activite-vide").property("texte"), "Aucune tâche en cours.")
        self.assertFalse(self.visible("menu-activite-badge"))


class Dynamique(BaseMenu):
    """L'état vit dans un dossier temporaire : on y écrit des tâches pendant que la fenêtre est ouverte."""
    largeur = 1100

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        shutil.copy(Path(__file__).parent / "echantillons" / "etats" / "vide" / "etat.json", self.tmp / "etat.json")
        (self.tmp / "taches").mkdir()
        self.dossier = str(self.tmp)
        super().setUp()

    def ecrire(self, nom, **champs):
        t = {"id": nom, "type": "menage", "titre": "Ménage des caches", "statut": "en_cours", "progression": -1,
             "detail": "", "debut": "2026-11-09T15:00:00", "fin": None, "unite": None, "etapes": [], "journal": []}
        t.update(champs)
        fichier = self.tmp / "taches" / (nom.replace(":", "_") + ".json")
        tmp = fichier.with_suffix(".tmp")
        tmp.write_text(json.dumps(t), encoding="utf-8")
        os.replace(tmp, fichier)

    def test_echec_recent_ouvre_le_panneau_et_deplie_la_tache(self):
        self.ecrire("menage:caches", statut="echec", fin="2999-01-01T00:00:00", detail="Permission refusée",
                     journal=["Erreur : permission refusée"])
        attendre(3000, lambda: self.fenetre.property("activiteOuverte"))
        self.assertTrue(self.fenetre.property("activiteOuverte"))
        attendre(300)
        self.assertTrue(self.visible("tache-details-menage:caches"))

    def test_echec_anterieur_a_l_ouverture_n_ouvre_rien(self):
        self.ecrire("menage:caches", statut="echec", fin="2000-01-01T00:00:00")
        attendre(1500, lambda: len(self.f.pont.taches) == 1)
        self.assertFalse(self.fenetre.property("activiteOuverte"))

    def test_notification_quand_une_tache_suivie_finit(self):
        self.ecrire("menage:caches", detail="en route")
        attendre(3000, lambda: self.visible("menu-activite-badge"))
        self.assertEqual(self.fenetre.property("derniereNotification"), "")
        self.ecrire("menage:caches", statut="fini", progression=100, fin="2999-01-01T00:00:00")
        attendre(3000, lambda: self.fenetre.property("derniereNotification") != "")
        self.assertEqual(self.fenetre.property("derniereNotification"), "✔ Ménage des caches : terminé")

    def test_pas_de_notification_pour_une_tache_deja_finie(self):
        self.ecrire("menage:caches", statut="fini", progression=100, fin="2026-11-09T15:05:00")
        attendre(1500, lambda: len(self.f.pont.taches) == 1)
        self.assertEqual(self.fenetre.property("derniereNotification"), "")


if __name__ == "__main__":
    unittest.main()
