"""« Optimiser mes disques » : options A à D avec les vrais chiffres. Aucun vrai flatpak : `run` est un faux qui
enregistre les commandes ; seul l'échantillon flatpak-systeme.txt (au format réel, applis d'exemple) est lu."""
import unittest
from pathlib import Path

from centre_bazzite import config, optimiser, stockage
from tests import configuration

ICI = Path(__file__).resolve().parent
LSBLK = (ICI / "echantillons" / "lsblk.json").read_text(encoding="utf-8")
FLATPAK = (ICI / "echantillons" / "flatpak-systeme.txt").read_text(encoding="utf-8")


def vol(nom, chemin, libre, total):
    return {"nom": nom, "chemin": chemin, "libre_go": libre, "total_go": total,
            "pourcent_utilise": round(100 * (total - libre) / total, 1)}


VOLUMES = [vol("Système", "/var", 11.0, 69.3), vol("Home", "/var/home", 300.0, 905.0),
           vol("Données", "/var/mnt/DONNEES", 400.0, 886.0), vol("Externe", "/var/mnt/EXTERNE", 2000.0, 3725.0)]
DISQUES = stockage.disques(stockage.lire_lsblk(LSBLK), VOLUMES)
APPLIS = [{"id": "org.libreoffice.LibreOffice", "nom": "LibreOffice", "origine": "flathub", "octets": 596200000,
           "taille": "596 Mo"},
          {"id": "org.exemple.Perso", "nom": "Perso", "origine": "mon-depot", "octets": 1000000, "taille": "1 Mo"}]


def par_id(liste):
    return {o["id"]: o for o in liste}


class Lecture(unittest.TestCase):
    def test_taille_flatpak(self):
        for texte, octets in (("753.1 MB", 753100000), ("753.1 MB", 753100000), ("1.4 kB", 1400),
                              ("2.0 GB", 2000000000), ("512 bytes", 512), ("?", 0)):
            self.assertEqual(optimiser.taille_flatpak(texte), octets, texte)

    def test_lire_flatpak(self):
        applis = optimiser.lire_flatpak(FLATPAK)
        self.assertGreater(len(applis), 5)
        tailles = [a["octets"] for a in applis]
        self.assertEqual(tailles, sorted(tailles, reverse=True))
        for a in applis:
            self.assertTrue(a["id"] and a["nom"] and a["origine"])
            self.assertGreater(a["octets"], 0)


class Options(unittest.TestCase):
    def test_options_vrais_chiffres(self):
        o = par_id(optimiser.options(DISQUES, APPLIS, 2_000_000_000))
        self.assertEqual(list(o), ["A", "B", "C", "D"])
        self.assertEqual(o["A"]["etat"], "fait")
        self.assertEqual(o["A"]["badge"], "En place")
        self.assertIn("2 disques physiques, 4 volumes", o["A"]["texte"])
        self.assertIn("11 Go libres", o["C"]["texte"])
        self.assertIn("au début", o["D"]["texte"])
        self.assertIn("à la fin", o["D"]["texte"])
        self.assertEqual((o["D"]["etat"], o["D"]["badge"]), ("plus_tard", "Ton idée — plus tard"))
        self.assertIn("Externe a 2000 Go libres sur 3725 Go", o["B"]["texte"])
        self.assertEqual(o["B"]["etat"], "a_decider")

    def test_options_b_et_d_suivent_la_configuration(self):
        """B : le volume à libérer, sa phrase et son conseil ; D : les deux volumes à fusionner."""
        o = par_id(optimiser.options(DISQUES, APPLIS, 0))
        self.assertEqual(o["B"]["texte"], "Ce disque ne sert plus qu'aux archives. Externe a 2000 Go libres sur 3725 Go. "
                                          "Si elles existent déjà ailleurs, ce disque peut être effacé, réaffecté ou "
                                          "débranché. Vérifie-le d'abord : Health Hub n'efface rien.")
        self.assertEqual(o["D"]["titre"], "Fusionner Données et Home en un seul volume")
        self.assertTrue(o["D"]["texte"].startswith("Impossible sur place : Données est au début du disque, Home à la fin"))

    def test_option_b_sans_phrase_ni_conseil(self):
        reglages = {"liberer": {"volume": "Externe", "phrase": "", "conseil": None}, "fusionner": None, "idee": "",
                    "recommandation": None}
        b = par_id(optimiser.options(DISQUES, APPLIS, 0, reglages))["B"]
        self.assertEqual(b["texte"], "Externe a 2000 Go libres sur 3725 Go. Si ce qu'il contient existe déjà ailleurs, "
                                     "ce disque peut être effacé, réaffecté ou débranché. Vérifie-le d'abord : "
                                     "Health Hub n'efface rien.")

    def test_sans_configuration_ni_b_ni_d(self):
        with configuration(""):
            self.assertEqual(list(par_id(optimiser.options(DISQUES, APPLIS, 0))), ["A", "C"])
            r = optimiser.construire(DISQUES, run=lambda cmd, **kw: (0, FLATPAK if "--app" in cmd else ""))
        self.assertEqual([o["id"] for o in r["options"]], ["A", "C"])
        self.assertEqual(r["recommandation"], "Recommandation : A tout de suite, puis C.")
        self.assertEqual(r["idee"], "")

    def test_recommandation_par_defaut_selon_les_options(self):
        self.assertEqual(optimiser.recommandation_par_defaut(["A", "B", "C", "D"]),
                         "Recommandation : A tout de suite, puis C ; B si ce qu'il contient existe déjà ailleurs ; "
                         "D seulement si tu y tiens vraiment.")
        self.assertEqual(optimiser.recommandation_par_defaut(["A", "C", "D"]),
                         "Recommandation : A tout de suite, puis C ; D seulement si tu y tiens vraiment.")

    def test_option_c_commandes(self):
        c = par_id(optimiser.options(DISQUES, APPLIS, 2_000_000_000))["C"]
        lignes = c["commandes"].splitlines()
        self.assertEqual(lignes[0], "flatpak remote-add --user --if-not-exists flathub "
                                    "https://dl.flathub.org/repo/flathub.flatpakrepo")
        self.assertIn("flatpak install --user -y flathub org.libreoffice.LibreOffice", lignes)
        self.assertIn("flatpak uninstall --system -y org.libreoffice.LibreOffice", lignes)
        self.assertEqual(lignes[-1], "flatpak uninstall --system --unused -y")
        self.assertNotIn("org.exemple.Perso", c["commandes"])
        self.assertIn("Perso (mon-depot)", c["texte"])
        self.assertIn("à déplacer à la main", c["texte"])
        self.assertEqual(c["etat"], "possible")
        self.assertTrue(c["badge"].startswith("Possible : "))
        self.assertEqual([a["id"] for a in c["applis"]], ["org.libreoffice.LibreOffice", "org.exemple.Perso"])

    def test_option_c_rien_a_deplacer(self):
        c = par_id(optimiser.options(DISQUES, [], 0))["C"]
        self.assertEqual((c["etat"], c["badge"]), ("fait", "Rien à déplacer"))
        self.assertIsNone(c["commandes"])

    def test_option_c_liste_illisible(self):
        c = par_id(optimiser.options(DISQUES, None, 0))["C"]
        self.assertEqual((c["etat"], c["badge"]), ("impossible", "Vérification impossible"))
        self.assertIsNone(c["commandes"])

    def test_option_c_aucune_appli_flathub(self):
        c = par_id(optimiser.options(DISQUES, APPLIS[1:], 0))["C"]
        self.assertEqual((c["etat"], c["badge"]), ("possible", "À déplacer à la main"))
        self.assertIsNone(c["commandes"])

    def test_option_b_externe_debranche(self):
        sans = [{**d, "volumes": [v for v in d["volumes"] if v["nom"] != "Externe"]} for d in DISQUES]
        b = par_id(optimiser.options(sans, APPLIS, 0))["B"]
        self.assertEqual(b["texte"], "Externe n'est pas branché : branche-le pour voir ses chiffres.")
        self.assertEqual(b["etat"], "a_decider")


class Construire(unittest.TestCase):
    def test_construire_ne_lance_que_flatpak_list(self):
        appels = []

        def faux(cmd, **kw):
            appels.append(cmd)
            return 0, FLATPAK if "--app" in cmd else "753.1 MB\n1.4 kB\n"

        r = optimiser.construire(DISQUES, run=faux)
        self.assertEqual(len(appels), 2)
        for cmd in appels:
            self.assertEqual(cmd[:2], ["env", "LC_ALL=C"])
            self.assertEqual(cmd[2:4], ["flatpak", "list"])
        self.assertEqual(set(r), {"options", "recommandation", "idee"})
        self.assertEqual(r["recommandation"], config.optimiser()["recommandation"])      # celle de la configuration
        self.assertEqual(r["idee"], "Ton idée (1er novembre) : fusionner des disques. On en reparlera.")

    def test_flatpak_en_echec_verification_impossible(self):
        """Revue finale M2 : si `flatpak list` échoue, C ne dit ni « fait / Rien à déplacer » ni « environ 0 Mo »."""
        r = optimiser.construire(DISQUES, run=lambda cmd, **kw: (1, "erreur"))
        c = par_id(r["options"])["C"]
        self.assertEqual((c["etat"], c["badge"]), ("impossible", "Vérification impossible"))
        self.assertIn("La liste des Flatpak installés pour tout le système n'a pas pu être lue", c["texte"])
        self.assertNotIn("environ", c["texte"])
        self.assertIn("11 Go libres", c["texte"])               # le goulot reste dit avec les vrais chiffres
        self.assertEqual((c["commandes"], c["applis"]), (None, []))

    def test_liste_lue_mais_tailles_illisibles(self):
        """La liste suffit : sans le total de `flatpak list --columns=size`, la somme des applis le remplace."""
        r = optimiser.construire(DISQUES, run=lambda cmd, **kw: (0, FLATPAK) if "--app" in cmd else (1, "erreur"))
        c = par_id(r["options"])["C"]
        self.assertEqual(c["etat"], "possible")
        self.assertNotIn("environ 0 Mo", c["texte"])


if __name__ == "__main__":
    unittest.main()
