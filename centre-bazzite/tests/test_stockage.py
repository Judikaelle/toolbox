"""Stockage : disques physiques et leurs volumes (lsblk -> stockage.json). Aucun vrai lsblk, aucun disque mesuré :
chaque source est injectée ; seul l'échantillon lsblk.json (au format réel de lsblk, noms d'exemple) est lu."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from centre_bazzite import commun, points, sante, stockage
from tests import configuration

ICI = Path(__file__).resolve().parent
ECHANTILLON = (ICI / "echantillons" / "lsblk.json").read_text(encoding="utf-8")
GIO = 1024 ** 3


def vol(nom, chemin, libre, total):
    return {"nom": nom, "chemin": chemin, "libre_go": libre, "total_go": total,
            "pourcent_utilise": round(100 * (total - libre) / total, 1)}


VOLUMES = [vol("Système", "/var", 40.0, 70.0), vol("Home", "/var/home", 300.0, 905.0),
           vol("Données", "/var/mnt/DONNEES", 400.0, 886.0), vol("Externe", "/var/mnt/EXTERNE", 2000.0, 3725.0)]
# Ni vrai LinStat ni vrai cache d'analyse (V24) : ces sources sont injectées partout.
# Ni vrai parcours du home ni vrai flatpak pour le ménage (V24) : les recommandations sont injectées aussi.
SANS_ANALYSE = {"analyses": lambda chemin: None, "linstat": lambda: {"moteur": False, "commande": None},
                "recommandations": lambda: [],
                "optimiser": lambda disques: {"options": [], "recommandation": "", "idee": ""}}


def utilisation(libre_go, total_go):
    return SimpleNamespace(free=int(libre_go * GIO), total=int(total_go * GIO), used=0)


def disque_usb(label, montage, fs="exfat", modele="Clé"):
    """Un disque USB d'une partition, lu comme le ferait lire_lsblk."""
    brut = {"name": "sdb", "type": "disk", "size": 32 * GIO, "tran": "usb", "model": modele, "rm": True,
            "children": [{"name": "sdb1", "type": "part", "start": 2048, "size": 32 * GIO, "fstype": fs,
                          "label": label, "mountpoints": [montage]}]}
    return stockage.lire_lsblk(json.dumps({"blockdevices": [brut]}))[0]


class Lecture(unittest.TestCase):
    def test_zram_et_loop_exclus(self):
        noms = [d["nom"] for d in stockage.lire_lsblk(ECHANTILLON)]
        self.assertEqual(sorted(noms), ["nvme0n1", "sda"])

    def test_montages_des_descendants_remontes_a_la_partition(self):
        nvme = next(d for d in stockage.lire_lsblk(ECHANTILLON) if d["nom"] == "nvme0n1")
        systeme = next(p for p in nvme["partitions"] if p["nom"] == "nvme0n1p6")
        self.assertIn("/var", systeme["montages"])
        self.assertEqual((systeme["fs"], systeme["debut"]), ("ext4", 1861359616))

    def test_montage_d_un_descendant_remonte(self):
        brut = json.dumps({"blockdevices": [{"name": "sdc", "type": "disk", "size": 1, "tran": "sata", "model": "X",
                                             "children": [{"name": "sdc1", "type": "part", "start": 2048, "size": 1,
                                                           "fstype": "crypto_LUKS", "mountpoints": [],
                                                           "children": [{"name": "luks", "type": "crypt", "start": None,
                                                                         "size": 1, "fstype": "ext4",
                                                                         "mountpoints": ["/var/mnt/COFFRE"]}]}]}]})
        part = stockage.lire_lsblk(brut)[0]["partitions"][0]
        self.assertEqual(part["montages"], ["/var/mnt/COFFRE"])


class Disques(unittest.TestCase):
    def disques(self, lsblk=None, volumes=None, **kw):
        lsblk = stockage.lire_lsblk(ECHANTILLON) if lsblk is None else lsblk
        return stockage.disques(lsblk, VOLUMES if volumes is None else volumes, **kw)

    def test_deux_disques_physiques(self):
        d = self.disques()
        self.assertEqual(len(d), 2)
        self.assertEqual(d[0]["titre"], "Disque interne (NVMe 2 To)")
        self.assertEqual(d[0]["id"], "nvme0n1")
        self.assertTrue(d[0]["interne"])
        self.assertEqual([v["nom"] for v in d[0]["volumes"]], ["Données", "Système", "Home"])
        self.assertEqual([v["position"] for v in d[0]["volumes"]], ["debut", "milieu", "fin"])
        self.assertEqual([v["fs"] for v in d[0]["volumes"]], ["btrfs", "ext4", "ext4"])
        self.assertEqual([v["chemin"] for v in d[0]["volumes"]], ["/var/mnt/DONNEES", "/var", "/var/home"])
        self.assertEqual(d[1]["titre"], "Disque externe (SSD USB)")
        self.assertFalse(d[1]["interne"])
        self.assertEqual([v["nom"] for v in d[1]["volumes"]], ["Externe"])
        self.assertEqual(d[1]["volumes"][0]["fs"], "exfat")

    def test_mesures_reprises_des_volumes_de_la_sante(self):
        jeux = self.disques()[0]["volumes"][0]
        self.assertEqual((jeux["libre_go"], jeux["total_go"], jeux["pourcent_utilise"]), (400.0, 886.0, 54.9))

    def test_boot_et_efi_ignores(self):
        chemins = [v["chemin"] for d in self.disques() for v in d["volumes"]]
        self.assertNotIn("/boot", chemins)
        self.assertNotIn("/boot/efi", chemins)
        self.assertNotIn("[SWAP]", chemins)
        self.assertEqual(len(chemins), 4)

    def test_disque_usb_debranche_absent_sans_alerte(self):
        """Externe débranché : lsblk ne le voit plus, la santé ne le mesure plus (aucune alerte, aucun point)."""
        sans_sda = [d for d in stockage.lire_lsblk(ECHANTILLON) if d["nom"] != "sda"]
        with mock.patch.object(sante.shutil, "disk_usage", lambda chemin: utilisation(100, 200)):
            mesures = sante.volumes(est_monte=lambda c: c != "/var/mnt/EXTERNE")
            non_montes = sante.non_montes(est_monte=lambda c: c != "/var/mnt/EXTERNE")
        self.assertEqual([v["nom"] for v in mesures], ["Système", "Home", "Données"])
        d = stockage.disques(sans_sda, mesures)
        self.assertEqual(len(d), 1)
        pts = points.points({"volumes": mesures, "non_montes": non_montes}, {})
        self.assertFalse([p for p in pts if "Externe" in p["id"] or "Externe" in p["titre"]])
        self.assertEqual(pts, [])

    def test_volume_inconnu_nomme_par_label(self):
        d = self.disques([disque_usb("CLE", "/run/media/bazzite/CLE")], [],
                         mesurer=lambda chemin: utilisation(10, 32))
        self.assertEqual([v["nom"] for v in d[0]["volumes"]], ["CLE"])
        self.assertEqual(d[0]["volumes"][0]["libre_go"], 10.0)
        self.assertEqual(d[0]["titre"], "Disque externe (USB)")

    def test_volume_configure_nomme_par_la_configuration(self):
        """Un volume de la configuration garde son nom, même monté hors de /var/mnt et /run/media."""
        conf = ('[[volumes]]\nnom = "Ma clé"\nchemin = "/run/media/bazzite/CLE"\n'
                '[[volumes]]\nnom = "Atelier"\nchemin = "/srv/atelier"\n')
        with configuration(conf):
            cle = self.disques([disque_usb("CLE", "/run/media/bazzite/CLE")], [], mesurer=lambda c: utilisation(10, 32))
            atelier = self.disques([disque_usb("X", "/srv/atelier")], [], mesurer=lambda c: utilisation(5, 32))
        self.assertEqual(cle[0]["volumes"][0]["nom"], "Ma clé")
        self.assertEqual([(v["nom"], v["chemin"]) for v in atelier[0]["volumes"]], [("Atelier", "/srv/atelier")])
        with configuration(""):
            self.assertEqual(self.disques([disque_usb("X", "/srv/atelier")], [], mesurer=lambda c: utilisation(5, 32)),
                             [])

    def test_volume_inconnu_sans_label_nomme_par_dossier(self):
        d = self.disques([disque_usb(None, "/var/mnt/ARCHIVES")], [], mesurer=lambda chemin: utilisation(5, 32))
        self.assertEqual(d[0]["volumes"][0]["nom"], "ARCHIVES")

    def test_partition_montee_ailleurs_ignoree(self):
        d = self.disques([disque_usb("X", "/mnt/autre")], [], mesurer=lambda chemin: utilisation(5, 32))
        self.assertEqual(d, [])

    def test_etat_du_volume(self):
        def etat(libre, alertes=frozenset()):
            vols = [vol("Système", "/var", libre, 100.0), vol("Home", "/var/home", 50.0, 100.0),
                    vol("Données", "/var/mnt/DONNEES", 50.0, 100.0), vol("Externe", "/var/mnt/EXTERNE", 50.0, 100.0)]
            d = self.disques(volumes=vols, alertes=alertes)
            return {v["chemin"]: v["etat"] for x in d for v in x["volumes"]}
        self.assertEqual(etat(4.0)["/var"], "echec")
        self.assertEqual(etat(5.0)["/var"], "ok")             # le seuil rouge est strictement sous 5 %
        self.assertEqual(etat(50.0)["/var"], "ok")
        self.assertEqual(etat(4.0, frozenset({"volume:/var"}))["/var"], "echec")
        a = etat(50.0, frozenset({"volume:/var/mnt/EXTERNE"}))
        self.assertEqual(a["/var/mnt/EXTERNE"], "attention")
        self.assertEqual(a["/var"], "ok")

    def test_position_selon_le_rang_des_grosses_partitions(self):
        grosses = [{"nom": f"p{i}", "debut": i * 10, "taille": 100 * GIO, "fs": "ext4", "label": None,
                    "montages": [f"/var/mnt/V{i}"]} for i in range(1, 5)]
        petite = {"nom": "pe", "debut": 5, "taille": GIO, "fs": "vfat", "label": None, "montages": ["/var/mnt/PETIT"]}
        disque = {"nom": "sdz", "taille": 400 * GIO, "transport": "sata", "modele": "X", "amovible": False,
                  "partitions": [petite] + grosses}
        d = stockage.disques([disque], [], mesurer=lambda chemin: utilisation(50, 100))
        pos = {v["nom"]: v["position"] for v in d[0]["volumes"]}
        self.assertEqual(pos, {"V1": "debut", "V2": "milieu", "V3": "milieu", "V4": "fin", "PETIT": None})
        self.assertEqual(d[0]["titre"], "Disque interne (SATA 0,4 To)")

    def test_une_seule_grosse_partition_sans_position(self):
        d = self.disques()
        self.assertIsNone(d[1]["volumes"][0]["position"])


class Construire(unittest.TestCase):
    def test_construire_avec_sources_injectees(self):
        s = stockage.construire(lsblk=lambda: ECHANTILLON, volumes=lambda: VOLUMES, **SANS_ANALYSE,
                                etat={"points": [{"id": "volume:/var/mnt/EXTERNE", "gravite": "attention"},
                                                 {"id": "volume:/var", "gravite": "attention", "en_sourdine": True}]})
        self.assertEqual(set(s), {"genere", "disques", "linstat", "analyses", "recommandations", "optimiser"})
        self.assertEqual(set(s["optimiser"]), {"options", "recommandation", "idee"})
        self.assertEqual(s["recommandations"], [])
        self.assertEqual(s["linstat"], {"moteur": False, "commande": None})
        self.assertEqual(s["analyses"], {"/var/mnt/DONNEES": None, "/var": None, "/var/home": None,
                                         "/var/mnt/EXTERNE": None})
        etats = {v["chemin"]: v["etat"] for d in s["disques"] for v in d["volumes"]}
        self.assertEqual(etats["/var/mnt/EXTERNE"], "attention")
        self.assertEqual(etats["/var"], "ok")             # un point en sourdine n'est pas actif

    def test_recommandations_de_menage_injectees(self):
        recos = [{"id": "caches", "titre": "Caches régénérables", "elements": [{"cible": "/x"}]}]
        s = stockage.construire(lsblk=lambda: ECHANTILLON, volumes=lambda: VOLUMES, etat={},
                                **dict(SANS_ANALYSE, recommandations=lambda: recos))
        self.assertEqual(s["recommandations"], recos)

    def test_recommandations_lisent_les_controles_du_dossier(self):
        """Par défaut, les recommandations reçoivent controles.json du dossier donné (V47), sans rien lancer ici."""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(stockage.menage, "recommandations",
                                                                   return_value=[]) as recos:
            commun.ecrire_json(Path(d) / "controles.json", {"caches": {"journal": 5}})
            stockage.construire(d, lsblk=lambda: ECHANTILLON, volumes=lambda: VOLUMES, etat={},
                                analyses=lambda chemin: None, linstat=lambda: {"moteur": False, "commande": None},
                                optimiser=SANS_ANALYSE["optimiser"])
        recos.assert_called_once_with(controles={"caches": {"journal": 5}})

    def test_ecrire_lit_et_ecrit_dans_le_meme_dossier(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as autre, \
                mock.patch.object(commun, "ETAT", Path(autre)):
            (Path(d) / "etat.json").write_text(json.dumps(
                {"points": [{"id": "volume:/var/mnt/EXTERNE", "gravite": "attention"}]}), encoding="utf-8")
            chemin = stockage.ecrire(d, lsblk=lambda: ECHANTILLON, volumes=lambda: VOLUMES, **SANS_ANALYSE)
            donnees = json.loads(chemin.read_text(encoding="utf-8"))
            self.assertEqual(chemin, Path(d) / "stockage.json")
            self.assertFalse((Path(autre) / "stockage.json").exists())
        etats = {v["chemin"]: v["etat"] for x in donnees["disques"] for v in x["volumes"]}
        self.assertEqual(etats["/var/mnt/EXTERNE"], "attention")

    def test_espace_est_public(self):
        self.assertEqual(sante.espace("X", "/x", utilisation(10, 40))["libre_go"], 10.0)

    def test_ecrire_stockage_json(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(commun, "ETAT", Path(d)):
            chemin = stockage.ecrire(lsblk=lambda: ECHANTILLON, volumes=lambda: VOLUMES, **SANS_ANALYSE)
            self.assertEqual(chemin, Path(d) / "stockage.json")
            donnees = json.loads(chemin.read_text(encoding="utf-8"))
        self.assertEqual(len(donnees["disques"]), 2)
        self.assertIn("genere", donnees)


class Cli(unittest.TestCase):
    def test_commande_stockage_ecrit_stockage_json(self):
        from centre_bazzite import cli
        with mock.patch.object(stockage, "ecrire", return_value=Path("/tmp/x/stockage.json")) as ecrire, \
                mock.patch("builtins.print"):
            self.assertEqual(cli.main(["stockage"]), 0)
        ecrire.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
