import json
import unittest
from pathlib import Path

from centre_bazzite import bilan

ECH = Path(__file__).parent / "echantillons"


def _lignes(*objets):
    return [json.dumps(o) for o in objets]


def _module(nom, *sorties, code=0, niveau="INFO"):
    res = [{"level": "INFO", "msg": "Command output", "module": nom, "status": "running", "output": s}
           for s in sorties]
    res.append({"level": niveau, "msg": f"{nom} module has completed.", "module": nom,
                "status": "finished", "exit_code": code, "output": "fin"})
    return res


class DetailUupd(unittest.TestCase):
    def test_echantillon_reel_rien_a_faire(self):
        lignes = (ECH / "uupd-rien-a-faire.jsonl").read_text().splitlines()
        self.assertEqual(bilan.detail_uupd(lignes, [], False).splitlines(),
                         ["Système : déjà à jour", "Homebrew : déjà à jour",
                          "Flatpak : rien à mettre à jour"])

    def test_nombre_de_changements_par_categorie(self):
        lignes = _lignes(*_module("flatpak", "Updating x"), *_module("brew", "==> Upgrading 1"))
        diff = [{"categorie": "applications", "id": i, "nom": i, "de": "1", "vers": "2"} for i in "abc"]
        diff += [{"categorie": "outils", "id": "node", "nom": "node", "de": "1", "vers": "2"}]
        self.assertEqual(bilan.detail_uupd(lignes, diff, False).splitlines(),
                         ["Flatpak : 3 applications mises à jour", "Homebrew : 1 outil mis à jour"])

    def test_un_seul_flatpak(self):
        lignes = _lignes(*_module("flatpak", "x"))
        diff = [{"categorie": "applications", "id": "a", "nom": "a", "de": "1", "vers": "2"}]
        self.assertEqual(bilan.detail_uupd(lignes, diff, False), "Flatpak : 1 application mise à jour")

    def test_nouvelle_image_en_attente(self):
        lignes = _lignes(*_module("system", "Staging deployment...done"))
        self.assertEqual(bilan.detail_uupd(lignes, [], True),
                         "Système : nouvelle image prête, redémarrage nécessaire")

    def test_systeme_a_jour_malgre_un_deploiement_deja_en_attente(self):
        lignes = _lignes(*_module("system", "No upgrade available."))
        self.assertEqual(bilan.detail_uupd(lignes, [], True), "Système : déjà à jour")

    def test_module_en_echec(self):
        lignes = _lignes(*_module("flatpak", "", "error: pas de réseau", "", code=1, niveau="ERROR"))
        self.assertEqual(bilan.detail_uupd(lignes, [], False), "Flatpak : échec (error: pas de réseau)")

    def test_aucune_ligne(self):
        self.assertEqual(bilan.detail_uupd([], [], False), "")

    def test_lignes_illisibles_ignorees(self):
        self.assertEqual(bilan.detail_uupd(["pas du json", "[1]", "Starting x"], [], False), "")


def _h(date, resultats, changements=None):
    return {"date": date, "resultats": resultats, "changements": changements}


def _r(module, etat, message):
    return {"module": module, "etat": etat, "message": message, "details": ""}


TOUT_A_JOUR = [_r("vicinae", "à jour", "Vicinae 0.30.0"), _r("ollama", "à jour", "Ollama 0.40.15"),
               _r("uv", "à jour", "uv 0.13.7"), _r("distrobox", "à jour", "Distrobox à jour : messagerie"),
               _r("godot", "à jour", "Godot 4.7.2")]


class DetailMajApps(unittest.TestCase):
    def test_tout_a_jour(self):
        self.assertEqual(bilan.detail_maj_apps([_h("2026-11-09T14:52:56", TOUT_A_JOUR)], "2026-11-09T14:52:27"),
                         "Tout est à jour (Vicinae 0.30.0, Ollama 0.40.15, uv 0.13.7)")

    def test_mis_a_jour(self):
        res = [_r("ollama", "mis à jour", "Ollama 0.32.15 → 0.40.15")] + TOUT_A_JOUR[:1]
        self.assertEqual(bilan.detail_maj_apps([_h("2026-11-09T14:52:56", res)], "2026-11-09T14:52:27"),
                         "Ollama 0.32.15 → 0.40.15")

    def test_echec_et_action_manuelle(self):
        res = [_r("uv", "échec", "uv : réseau coupé"), _r("vicinae", "à faire", "Vicinae : à installer à la main")]
        self.assertEqual(bilan.detail_maj_apps([_h("2026-11-09T14:52:56", res)], "2026-11-09T14:52:27"),
                         "échec : uv : réseau coupé ; à faire : Vicinae : à installer à la main")

    def test_ignore_les_lignes_anterieures_a_la_session(self):
        self.assertIsNone(bilan.detail_maj_apps([_h("2026-11-09T11:24:40", TOUT_A_JOUR)], "2026-11-09T14:52:27"))

    def test_derniere_ligne_de_la_session(self):
        res = [_r("ollama", "mis à jour", "Ollama 0.32.15 → 0.40.15")]
        lignes = [_h("2026-11-09T14:53:00", res), _h("2026-11-09T14:52:56", TOUT_A_JOUR)]
        self.assertEqual(bilan.detail_maj_apps(lignes, "2026-11-09T14:52:27"), "Ollama 0.32.15 → 0.40.15")

    def test_historique_sans_resultats(self):
        self.assertIsNone(bilan.detail_maj_apps([{"date": "2026-11-09T14:52:56"}], "2026-11-09T14:52:27"))


class Phrase(unittest.TestCase):
    def test_rien(self):
        self.assertEqual(bilan.phrase([]), "Tout était déjà à jour.")

    def test_echec_sans_changement(self):
        self.assertEqual(bilan.phrase([], echec=True), "Aucun changement, mais une étape a échoué.")

    def test_inconnu(self):
        self.assertEqual(bilan.phrase([], inconnu=True), "Changements inconnus : relevé impossible.")

    def test_changements_groupes(self):
        ch = [{"categorie": "applications", "id": i, "nom": i, "de": "1", "vers": "2"} for i in "abc"]
        ch.append({"categorie": "outils", "id": "ollama", "nom": "Ollama", "de": "0.32.15",
                   "vers": "0.40.15", "heure": "2026-11-09T14:52:56"})
        self.assertEqual(bilan.phrase(ch), "4 changements : 3 applications, Ollama 0.40.15.")

    def test_un_changement_avec_echec(self):
        ch = [{"categorie": "systeme", "id": "image", "nom": "Bazzite", "de": "45.1", "vers": "45.2"}]
        self.assertEqual(bilan.phrase(ch, echec=True),
                         "1 changement : Bazzite 45.2. Une étape a échoué.")


if __name__ == "__main__":
    unittest.main()
