"""Durée du démarrage, ralentisseurs, historique. Sorties de systemd-analyze injectées (tests/echantillons/demarrage/),
dossier temporaire : jamais le vrai systemd ni le vrai dossier d'état."""
import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from centre_bazzite import cli, commun, demarrage as D

ECH = Path(__file__).parent / "echantillons" / "demarrage"
VIDE = {"lancement": lambda: {"entrees": [], "ignorees": 0}, "systeme": lambda blame: []}


def lire(nom):
    return (ECH / nom).read_text(encoding="utf-8")


def fausse_commande(time="time.txt", blame="blame.txt", chaine="critical-chain.txt", session="", codes=None):
    """`systemd-analyze` : `time`, `blame`, `critical-chain`, et `--user blame` (clé « session »)."""
    codes = codes or {}
    textes = {"time": time, "blame": blame, "critical-chain": chaine, "session": session}
    appels = []

    def run(cmd, timeout=120, entree=None):
        appels.append((list(cmd), timeout))
        sous = "session" if cmd[3] == "--user" else cmd[3]
        return codes.get(sous, 0), lire(textes[sous]) if textes[sous].endswith(".txt") else textes[sous]
    run.appels = appels
    return run


def historique(*totaux, debut=0):
    return [{"boot_id": f"b{debut + i}", "debut": f"2026-11-{1 + i:02d}T08:00:00+00:00", "total": t}
            for i, t in enumerate(totaux)]


class Durees(unittest.TestCase):
    def test_duree_s_formes(self):
        for texte, attendu in (("1h 2min 3.456s", 3723.456), ("2min 5s", 125.0), ("14.848s", 14.848),
                               ("865ms", 0.865), ("250us", 0.00025), ("12µs", 0.000012)):
            with self.subTest(texte=texte):
                self.assertAlmostEqual(D.duree_s(texte), attendu, places=6)
        self.assertIsNone(D.duree_s("abc"))
        self.assertIsNone(D.duree_s(""))

    def test_duree_lisible(self):
        self.assertEqual(D.duree_lisible(4.58), "4,6 s")
        self.assertEqual(D.duree_lisible(0.9), "0,9 s")
        self.assertEqual(D.duree_lisible(14.85), "15 s")
        self.assertEqual(D.duree_lisible(65.2), "1 min 5 s")


class Lectures(unittest.TestCase):
    def test_lire_time_cinq_phases(self):
        t = D.lire_time(lire("time.txt"))
        self.assertAlmostEqual(t["total"], 40.246, delta=0.001)
        self.assertEqual(list(t["phases"]), ["firmware", "loader", "kernel", "initrd", "userspace"])
        self.assertAlmostEqual(t["phases"]["firmware"], 14.848, delta=0.001)

    def test_lire_time_sans_uefi(self):
        t = D.lire_time(lire("time-sans-uefi.txt"))
        self.assertNotIn("firmware", t["phases"])
        self.assertNotIn("loader", t["phases"])
        self.assertAlmostEqual(t["total"], 21.73, delta=0.001)

    def test_demarrage_pas_fini(self):
        """Comme en vrai (I-3) : tant que le démarrage n'est pas fini, `time` et `critical-chain` refusent (code 1,
        « Bootup is not yet finished »), et `blame` peut refuser aussi. Ce n'est pas une erreur ; critical-chain n'est
        même pas lancé, et rien n'est classé : sans la chaîne, « en arrière-plan, sans retarder le bureau » serait
        faux."""
        self.assertIsNone(D.lire_time(lire("time-pas-fini.txt")))
        self.assertIsNone(D.lire_time("n'importe quoi"))
        with tempfile.TemporaryDirectory() as d:
            run = fausse_commande(time="time-pas-fini.txt", blame="time-pas-fini.txt", chaine="time-pas-fini.txt",
                                  codes={"time": 1, "blame": 1, "critical-chain": 1})
            res = D.construire(run=run, boot=lambda: "b1", btime=lambda: "2026-11-10T08:00:00+00:00", dossier=Path(d),
                               **VIDE)
            self.assertIsNone(res["duree"])
            self.assertEqual(res["erreurs"], [])
            self.assertEqual((res["ralentisseurs"], res["arriere_plan"]), ([], []))
            self.assertEqual([c[2:4] for c, _ in run.appels], [["systemd-analyze", "time"], ["systemd-analyze", "blame"]])
            D.ecrire(dossier=Path(d), run=run, boot=lambda: "b1", btime=lambda: "2026-11-10T08:00:00+00:00", **VIDE)
            self.assertTrue((Path(d) / "demarrage.json").exists())
            self.assertEqual(commun.lire_json(Path(d) / "demarrages.json", []), [])

    def test_demarrage_pas_fini_blame_partiel(self):
        """`blame` qui répond pendant un démarrage pas fini (liste partielle) trie seulement l'onglet Système : aucune
        unité n'est classée « retarde le bureau » ni « en arrière-plan »."""
        vus = []
        run = fausse_commande(time="time-pas-fini.txt", chaine="time-pas-fini.txt",
                              codes={"time": 1, "critical-chain": 1})
        with tempfile.TemporaryDirectory() as d:
            res = D.construire(run=run, boot=lambda: "b1", btime=lambda: None, dossier=Path(d),
                               lancement=VIDE["lancement"], systeme=lambda blame: vus.append(blame) or [])
        self.assertEqual((res["ralentisseurs"], res["arriere_plan"], res["erreurs"]), ([], [], []))
        self.assertEqual(vus[0][0][0], "maj-auto.service")

    def test_chaine_pas_finie_apres_time_fini(self):
        """Un démarrage qui finit entre `time` et `critical-chain` : la chaîne refuse encore, sans bandeau d'erreur et
        sans classement faux."""
        run = fausse_commande(chaine="time-pas-fini.txt", codes={"critical-chain": 1})
        with tempfile.TemporaryDirectory() as d:
            res = D.construire(run=run, boot=lambda: "b1", btime=lambda: None, dossier=Path(d), **VIDE)
        self.assertEqual(res["erreurs"], [])
        self.assertEqual(res["arriere_plan"], [])
        self.assertFalse([r for r in res["ralentisseurs"] if r["type"] == "fond"])

    def test_lire_blame_sans_device(self):
        b = D.lire_blame(lire("blame.txt"))
        noms = [u for u, _ in b]
        self.assertEqual(noms[0], "maj-auto.service")
        self.assertAlmostEqual(b[0][1], 65.123, delta=0.001)
        self.assertFalse([n for n in noms if n.endswith(".device")])
        self.assertIn(("systemd-udev-trigger.service", 0.612), [(u, round(s, 3)) for u, s in b])
        self.assertEqual(len(b), 8)

    def test_lire_chaine_temps_propres(self):
        c = D.lire_chaine(lire("critical-chain.txt"))
        self.assertAlmostEqual(c["NetworkManager-wait-online.service"], 4.58, delta=0.001)
        self.assertAlmostEqual(c["greenboot-healthcheck.service"], 0.239, delta=0.001)
        self.assertNotIn("graphical.target", c)        # pas de « + » : pas de temps propre
        self.assertNotIn("network-online.target", c)

    def test_lire_chaine_prefixes_unicode(self):
        c = D.lire_chaine("graphical.target @5s\n└─a.service @3s +1.5s\n  │ ├─b.service @1s +200ms\n")
        self.assertEqual(set(c), {"a.service", "b.service"})


class Ralentisseurs(unittest.TestCase):
    def preparer(self):
        t = D.lire_time(lire("time.txt"))
        duree = {"total": t["total"], "phases": [
            {"cle": k, "nom": D.NOMS_PHASES[k], "secondes": v, "duree": D.duree_lisible(v), "lent": v > D.SEUILS_PHASES[k]}
            for k, v in t["phases"].items()]}
        return duree, D.lire_blame(lire("blame.txt")), D.lire_chaine(lire("critical-chain.txt"))

    def test_ralentisseurs_classes(self):
        liste, fond = D.ralentisseurs(*self.preparer())
        self.assertLessEqual(len(liste), 5)
        self.assertEqual(liste[0]["id"], "phase:firmware")
        self.assertEqual(liste[0]["type"], "phase")
        self.assertTrue(liste[0]["lent"])
        par = {r["id"]: r for r in liste}
        self.assertEqual(par["unite:NetworkManager-wait-online.service"]["type"], "bureau")
        self.assertEqual(par["unite:dracut-pre-udev.service"]["type"], "initrd")
        self.assertNotIn("unite:maj-auto.service", par)
        self.assertEqual([r["id"] for r in fond], ["unite:maj-auto.service"])
        self.assertEqual(fond[0]["type"], "fond")
        self.assertEqual(fond[0]["duree"], "1 min 5 s")
        self.assertEqual({r["portee"] for r in liste + fond}, {"systeme"})
        secondes = [r["secondes"] for r in liste]
        self.assertEqual(secondes, sorted(secondes, reverse=True))
        self.assertIn("greenboot", par["unite:NetworkManager-wait-online.service"]["explication"])

    def test_cinq_au_plus_et_trois_en_fond(self):
        blame = [(f"s{i}.service", 20.0 - i) for i in range(8)] + [(f"f{i}.service", 9.0 - i) for i in range(5)]
        chaine = {f"s{i}.service": 1.0 for i in range(8)}
        liste, fond = D.ralentisseurs(None, blame, chaine)
        self.assertEqual(len(liste), 5)
        self.assertEqual(len(fond), 3)
        self.assertEqual([r["id"] for r in fond], ["unite:f0.service", "unite:f1.service", "unite:f2.service"])

    def test_explication_repli(self):
        liste, _ = D.ralentisseurs(None, [("inconnu.service", 3.0)], {"inconnu.service": 3.0})
        self.assertEqual(liste[0]["explication"],
                         "inconnu.service a pris 3,0 s au démarrage. S'il tourne en parallèle des autres, il ne retarde "
                         "pas forcément l'arrivée au bureau.")

    def test_explications_de_plus(self):
        """Idées reprises de « Bilan Santé » (verifs_demarrage.py) : trois services courants de plus, expliqués."""
        self.assertEqual(D.EXPLICATIONS["ModemManager.service"],
                         "Gère les modems 3G/4G. Sans modem, il ne sert à rien, mais il ne retarde pas le bureau.")
        self.assertEqual(D.EXPLICATIONS["lvm2-monitor.service"],
                         "Surveille les volumes LVM. Inutile si tu n'utilises pas LVM.")
        self.assertEqual(D.EXPLICATIONS["systemd-binfmt.service"],
                         "Enregistre les formats d'exécutables (Wine, AppImage…). Rarement gênant.")
        _, fond = D.ralentisseurs(None, [("ModemManager.service", 6.0)], {})
        self.assertEqual(fond[0]["explication"], D.EXPLICATIONS["ModemManager.service"])

    def test_arriere_plan_avec_la_session(self):
        """Les unités de ta session (`systemd-analyze --user blame`) d'au moins 5 s, hors .device, rejoignent
        « en arrière-plan » : 3 au plus en tout, triées par durée, avec leur portée. Jamais dans « ce qui ralentit »."""
        session = D.lire_blame(lire("blame-session.txt")) + [("exemple.device", 30.0)]
        liste, fond = D.ralentisseurs(*self.preparer(), session=session)
        self.assertEqual([(r["id"], r["portee"]) for r in fond],
                         [("unite:maj-auto.service", "systeme"), ("unite:synchro.service", "session"),
                          ("unite:lanceur.service", "session")])
        self.assertEqual({r["type"] for r in fond}, {"fond"})
        self.assertEqual(fond[1]["duree"], "12 s")
        self.assertEqual({r["portee"] for r in liste}, {"systeme"})
        self.assertFalse([r for r in liste if r["nom"] in dict(session)])
        _, fond = D.ralentisseurs(None, [], {}, session=[("lanceur.service", 7.2), ("outil-perso.service", 4.9)])
        self.assertEqual([r["id"] for r in fond], ["unite:lanceur.service"])           # sous 5 s : rien


class Historique(unittest.TestCase):
    def test_historique_un_seul_ajout_par_demarrage(self):
        h = D.noter([], "b1", "2026-11-10T08:00:00+00:00", 40.0)
        h = D.noter(h, "b1", "2026-11-10T08:00:00+00:00", 41.0)
        self.assertEqual(h, [{"boot_id": "b1", "debut": "2026-11-10T08:00:00+00:00", "total": 40.0}])
        h = D.noter(h, "b2", "2026-11-11T08:00:00+00:00", 39.0)
        self.assertEqual([e["boot_id"] for e in h], ["b1", "b2"])

    def test_historique_garde_30(self):
        h = []
        for i in range(35):
            h = D.noter(h, f"b{i}", "2026-11-10T08:00:00+00:00", 40.0 + i)
        self.assertEqual(len(h), 30)
        self.assertEqual(h[0]["boot_id"], "b5")
        self.assertEqual(h[-1]["boot_id"], "b34")

    def test_habituel_mediane_des_10_precedents(self):
        h = historique(*range(100, 112))        # b0..b11
        mediane, totaux = D.habituel(h, "b11")
        self.assertEqual(totaux, [float(x) for x in range(110, 100, -1)])      # 10 avant b11, récent d'abord
        self.assertEqual(mediane, 105.5)
        mediane, totaux = D.habituel(h, "inconnu")              # pas encore dans l'historique : tous
        self.assertEqual(totaux[0], 111.0)
        self.assertEqual(len(totaux), 10)

    def test_habituel_moins_de_3_none(self):
        self.assertEqual(D.habituel(historique(40, 41, 42), "b2")[0], None)
        self.assertEqual(D.habituel(historique(40, 41, 42), "b2")[1], [41.0, 40.0])
        self.assertEqual(D.habituel(historique(40, 41, 42), "b3")[0], 41.0)

    def test_lent_trois_de_suite(self):
        h = historique(*([40] * 6), 58, 60, 57)
        self.assertEqual(D.lent(h), {"total": 57.0, "reference": 40.0})

    def test_lent_pas_si_un_seul(self):
        self.assertIsNone(D.lent(historique(*([40] * 6), 40, 41, 57)))
        self.assertIsNone(D.lent(historique(*([40] * 6), 58, 40, 57)))
        self.assertIsNone(D.lent(historique(40, 40, 58, 60, 57)))      # moins de 5 de référence

    def test_lent_pas_sous_5_s_d_ecart(self):
        self.assertIsNone(D.lent(historique(*([10] * 6), 13, 14, 14)))


class Resume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_resume_phrases(self):
        self.assertIsNone(D.resume(self.dossier))
        commun.ecrire_json(self.dossier / "demarrage.json",
                           {"duree": {"total": 40.246, "phases": []}, "habituel": None})
        self.assertEqual(D.resume(self.dossier), {"total": 40.246, "habituel": None, "lent": None,
                                                  "phrase": "Démarré en 40 s"})
        commun.ecrire_json(self.dossier / "demarrage.json",
                           {"duree": {"total": 40.246, "phases": []}, "habituel": 38.0})
        self.assertEqual(D.resume(self.dossier)["phrase"], "Démarré en 40 s · habituel : 38 s")
        commun.ecrire_json(self.dossier / "demarrage.json", {"duree": None, "habituel": None})
        r = D.resume(self.dossier)
        self.assertEqual(r["phrase"], "Démarrage en cours de relevé.")
        self.assertIsNone(r["total"])

    def test_resume_lent_depuis_l_historique(self):
        commun.ecrire_json(self.dossier / "demarrage.json", {"duree": {"total": 57.0, "phases": []}, "habituel": 40.0})
        commun.ecrire_json(self.dossier / "demarrages.json", historique(*([40] * 6), 58, 60, 57))
        self.assertEqual(D.resume(self.dossier)["lent"], {"total": 57.0, "reference": 40.0})

    def test_resume_ne_lance_aucune_commande(self):
        commun.ecrire_json(self.dossier / "demarrage.json", {"duree": None})
        import unittest.mock as m
        with m.patch.object(commun, "run", side_effect=AssertionError("commande lancée")):
            D.resume(self.dossier)


class Construire(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def construire(self, run=None, **kw):
        kw = {**VIDE, **kw}
        return D.construire(run=run or fausse_commande(), boot=lambda: "b9",
                            btime=lambda: "2026-11-10T08:00:00+00:00", dossier=self.dossier, **kw)

    def test_construire_complet(self):
        run = fausse_commande()
        d = self.construire(run)
        self.assertEqual((d["boot_id"], d["debut"]), ("b9", "2026-11-10T08:00:00+00:00"))
        self.assertAlmostEqual(d["duree"]["total"], 40.246, delta=0.001)
        self.assertEqual([p["cle"] for p in d["duree"]["phases"]],
                         ["firmware", "loader", "kernel", "initrd", "userspace"])
        self.assertTrue(d["duree"]["phases"][0]["lent"])
        self.assertFalse(d["duree"]["phases"][2]["lent"])
        self.assertEqual(d["erreurs"], [])
        self.assertEqual(d["lancement"], {"entrees": [], "ignorees": 0})
        self.assertEqual(d["systeme"], [])
        self.assertEqual(d["habituel"], None)
        self.assertEqual(run.appels[0], (["env", "LC_ALL=C", "systemd-analyze", "time"], 30))
        self.assertEqual(run.appels[1], (["env", "LC_ALL=C", "systemd-analyze", "blame", "--no-pager"], 30))
        self.assertEqual(run.appels[2], (["env", "LC_ALL=C", "systemd-analyze", "critical-chain", "--no-pager"], 30))
        self.assertEqual(run.appels[3], (["env", "LC_ALL=C", "systemd-analyze", "--user", "blame", "--no-pager"], 30))
        self.assertEqual(len(run.appels), 4)

    def test_construire_arriere_plan_de_la_session(self):
        """`--user blame` ajoute les unités de ta session à « en arrière-plan » ; en échec, il est ignoré sans erreur."""
        d = self.construire(fausse_commande(session="blame-session.txt"))
        self.assertEqual([(r["nom"], r["portee"]) for r in d["arriere_plan"]],
                         [("maj-auto.service", "systeme"), ("synchro.service", "session"),
                          ("lanceur.service", "session")])
        self.assertEqual(d["erreurs"], [])
        d = self.construire(fausse_commande(session="Failed to connect to bus", codes={"session": 1}))
        self.assertEqual([r["nom"] for r in d["arriere_plan"]], ["maj-auto.service"])
        self.assertEqual(d["erreurs"], [])

    def test_commande_en_echec_ecrite_dans_erreurs(self):
        run = fausse_commande(blame="Échec de la connexion au bus", codes={"blame": 1})
        d = self.construire(run)
        self.assertEqual(len(d["erreurs"]), 1)
        self.assertIn("blame", d["erreurs"][0])
        self.assertAlmostEqual(d["duree"]["total"], 40.246, delta=0.001)     # le reste est gardé
        run = fausse_commande(time="Echec du bus", codes={"time": 1})
        d = self.construire(run)
        self.assertIsNone(d["duree"])
        self.assertIn("Durée illisible", d["erreurs"][0])

    def test_ecrire_et_habituel(self):
        commun.ecrire_json(self.dossier / "demarrages.json", historique(38, 39, 37, 40))
        chemin = D.ecrire(dossier=self.dossier, run=fausse_commande(), boot=lambda: "b9",
                          btime=lambda: "2026-11-10T08:00:00+00:00", **VIDE)
        self.assertEqual(chemin, self.dossier / "demarrage.json")
        d = commun.lire_json(chemin, None)
        self.assertEqual(d["habituel"], 38.5)
        self.assertEqual(d["precedents"][0], 40.0)
        h = commun.lire_json(self.dossier / "demarrages.json", [])
        self.assertEqual(h[-1]["boot_id"], "b9")
        D.ecrire(dossier=self.dossier, run=fausse_commande(), boot=lambda: "b9",
                 btime=lambda: "2026-11-10T08:00:00+00:00", **VIDE)
        self.assertEqual(len(commun.lire_json(self.dossier / "demarrages.json", [])), 5)
        self.assertEqual(commun.lire_json(chemin, None)["habituel"], 38.5)


    def test_construire_branche_lancement_et_systeme(self):
        """Sans `lancement` ni `systeme`, construire relève ce qui se lance tout seul et les services système avec la
        même commande `run` ; le blame va aux services système."""
        run = fausse_commande()
        with mock.patch.object(D, "au_lancement", return_value={"entrees": ["e"], "ignorees": 2}) as lanc, \
                mock.patch.object(D, "services_systeme", return_value=["s"]) as syst:
            d = D.construire(run=run, boot=lambda: "b9", btime=lambda: None, dossier=self.dossier)
        self.assertEqual(d["lancement"], {"entrees": ["e"], "ignorees": 2})
        self.assertEqual(d["systeme"], ["s"])
        lanc.assert_called_once_with(run=run, dossier=self.dossier)
        self.assertIs(syst.call_args.kwargs["run"], run)
        self.assertEqual(syst.call_args.kwargs["blame"][0][0], "maj-auto.service")

    def test_construire_lancement_illisible_dans_erreurs(self):
        def casse(*a, **k):
            raise D.LectureImpossible("systemctl --user list-unit-files : Failed to connect to bus")
        d = self.construire(lancement=casse, systeme=lambda blame: casse())
        self.assertEqual(d["lancement"], {"entrees": [], "ignorees": 0})
        self.assertEqual(d["systeme"], [])
        self.assertEqual(d["erreurs"], [
            "Ce qui se lance tout seul illisible (systemctl --user list-unit-files : Failed to connect to bus)",
            "Services système illisibles (systemctl --user list-unit-files : Failed to connect to bus)"])


# --- Task 2 : ce qui se lance tout seul, services système, régler et remettre ---

MESSAGERIE = (
    "[Desktop Entry]\n"
    "# Lancée au démarrage de la session\n"
    "Type=Application\n"
    "Name=Messaging\n"
    "Name[fr]=Messagerie\n"
    "Comment=Instant messages\n"
    "Comment[fr]=Messages instantanés\n"
    "Exec=messagerie --tray\n"
    "Icon=messagerie\n"
    "\n"
    "[Desktop Action Nouveau]\n"
    "Name=Nouveau message\n"
    "Hidden=false\n"
    "Exec=messagerie --nouveau\n")
MESSAGERIE_MASQUEE = MESSAGERIE.replace("Icon=messagerie\n", "Icon=messagerie\nHidden=true\n")
INDEXATION = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Indexation\n"
    "Comment=Indexe les fichiers\n"
    "Exec=sh -c \"indexation --une-fois\"\n"
    "Terminal=false\n"
    "Icon=indexation\n"
    "Categories=Utility;\n")
# Un override écrit avant Health Hub : une partie de l'entrée système, puis Hidden=true (pas la copie exacte).
INDEXATION_OVERRIDE = (
    "[Desktop Entry]\r\n"
    "Type=Application\r\n"
    "Name=Indexation\r\n"
    "# masqué à la main\r\n"
    "Exec=sh -c \"indexation --une-fois\"\r\n"
    "Hidden = true\r\n")
PLASMA = "[Desktop Entry]\nExec=/usr/bin/plasmashell\nName=Plasma\nOnlyShowIn=KDE;\nX-systemd-skip=true\n"
MAINTENANT = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
MONOTONE = 24 * 3600 + 2 * 3600 + 6 * 60 + 26.0     # horloge monotone (depuis l'allumage) à MAINTENANT


def desktop(nom, *lignes):
    return "[Desktop Entry]\nType=Application\n" + f"Name={nom}\n" + "".join(l + "\n" for l in lignes) + \
        f"Exec={nom.lower()}\n"


class FauxSystemctl:
    """`run` qui répond aux lectures de systemctl à partir des échantillons et note chaque commande ; enable/disable
    changent l'état relu ensuite (UnitFileState, et ActiveState avec --now)."""

    def __init__(self, racine):
        self.racine = str(racine)
        self.appels = []
        self.etats, self.actifs = {}, {}
        self.echec = None
        self.echec_show = None          # (code, texte) : `systemctl --user show` en échec

    def __call__(self, cmd, timeout=120, entree=None):
        cmd = [str(c) for c in cmd]
        self.appels.append(cmd)
        if "list-unit-files" in cmd:
            nom = "list-unit-files-user.txt" if "--user" in cmd else "list-unit-files-system.txt"
            return 0, self._liste(lire(nom))
        if "show" in cmd:
            if "--user" in cmd and self.echec_show:
                return self.echec_show
            if "--user" in cmd:
                return 0, self._show(lire("show-user.txt").replace("/home/exemple/.config/systemd/user",
                                                                     self.racine))
            return 0, lire("show-system.txt")
        if cmd[:2] == ["systemctl", "--user"] and cmd[2] in ("enable", "disable"):
            if self.echec:
                return self.echec
            unite, oui = cmd[-1], cmd[2] == "enable"
            self.etats[unite] = "enabled" if oui else "disabled"
            if "--now" in cmd:
                self.actifs[unite] = "active" if oui else "inactive"
            return 0, ""
        raise AssertionError(f"commande inattendue : {cmd}")

    def _liste(self, texte):
        lignes = []
        for ligne in texte.splitlines():
            champs = ligne.split()
            if champs and champs[0] in self.etats:
                ligne = f"{champs[0]} {self.etats[champs[0]]} {champs[2]}"
            lignes.append(ligne)
        return "\n".join(lignes) + "\n"

    def _show(self, texte):
        blocs = []
        for bloc in texte.split("\n\n"):
            ident = next((l[3:] for l in bloc.splitlines() if l.startswith("Id=")), None)
            if ident in self.actifs:
                bloc = "\n".join(f"ActiveState={self.actifs[ident]}" if l.startswith("ActiveState=") else l
                                 for l in bloc.splitlines())
            blocs.append(bloc)
        return "\n\n".join(blocs)

    def bascules(self):
        return [c for c in self.appels if c[:2] == ["systemctl", "--user"] and c[2] in ("enable", "disable")]


class BaseLancement(unittest.TestCase):
    """Dossiers autostart, racines systemd et dossier d'état temporaires ; `run` faux."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.systeme, self.utilisateur = base / "xdg-autostart", base / "config" / "autostart"
        self.racine, self.globale = base / "config" / "systemd" / "user", base / "etc-systemd-user"
        self.dossier = base / "etat"
        self.systeme.mkdir(parents=True)
        for racine, liens in ((self.racine, {"timers.target.wants": ("sauvegarde-notes.timer",
                                                                     "centre-bazzite-releve.timer", "maj-apps.timer"),
                                             "graphical-session.target.wants": ("lanceur.service",
                                                                                "health-hub-modejeu.service")}),
                              (self.globale, {"default.target.wants": ("bazzite-exemple.service",),
                                              "sockets.target.wants": ("pipewire.socket", "dbus.socket"),
                                              "timers.target.wants": ("systemd-tmpfiles-clean.timer",),
                                              "graphical-session-pre.target.wants": ("xdg-user-dirs.service",)})):
            for wants, unites in liens.items():
                (racine / wants).mkdir(parents=True)
                for u in unites:
                    os.symlink(f"/nulle-part/{u}", racine / wants / u)
        self.run = FauxSystemctl(self.racine)

    def kw(self):
        return {"run": self.run, "dossier": self.dossier, "systeme": self.systeme, "utilisateur": self.utilisateur,
                "racine_utilisateur": self.racine, "racines_globales": (self.globale, self.globale / "absente"),
                "existe": lambda p: f"/usr/bin/{p}"}

    def poser(self, ou, nom, texte):
        ou.mkdir(parents=True, exist_ok=True)
        (ou / nom).write_bytes(texte.encode("utf-8"))

    def contenu(self, ou, nom):
        chemin = ou / nom
        return chemin.read_bytes().decode("utf-8") if chemin.exists() else None

    def journal(self):
        return commun.lire_json(self.dossier / "demarrage-journal.json", {})

    def applis(self, **kw):
        return D.applis(systeme=self.systeme, utilisateur=self.utilisateur,
                        existe=kw.pop("existe", lambda p: f"/usr/bin/{p}"), **kw)

    def unites(self, **kw):
        return {e["id"]: e for e in D.unites_utilisateur(run=self.run, racine_utilisateur=self.racine,
                                                         racines_globales=(self.globale, self.globale / "absente"),
                                                         maintenant=MAINTENANT, monotone=lambda: MONOTONE, **kw)}


class LireDesktop(unittest.TestCase):
    def test_lire_desktop_fr_d_abord(self):
        d = D.lire_desktop(MESSAGERIE)
        self.assertEqual(d["Name"], "Messagerie")
        self.assertEqual(d["Comment"], "Messages instantanés")
        self.assertEqual(d["Exec"], "messagerie --tray")
        self.assertNotIn("Hidden", d)           # la clé de [Desktop Action Nouveau] ne compte pas
        self.assertEqual(D.lire_desktop("[Desktop Entry]\r\nName = Indexation\r\nHidden = true\r\n"),
                         {"Name": "Indexation", "Hidden": "true"})
        self.assertEqual(D.lire_desktop("Name=hors section\n"), {})


class Applis(BaseLancement):
    def test_applis_override_utilisateur_gagne(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.poser(self.utilisateur, "messagerie.desktop",
                   MESSAGERIE_MASQUEE.replace("Name[fr]=Messagerie", "Name[fr]=Messagerie perso"))
        self.poser(self.utilisateur, "outil.desktop", desktop("Outil"))
        self.poser(self.utilisateur, "vieux.desktop.bak", desktop("Vieux"))
        entrees, ignorees = self.applis()
        self.assertEqual(ignorees, 0)
        par = {e["id"]: e for e in entrees}
        self.assertEqual(set(par), {"autostart:messagerie.desktop", "autostart:outil.desktop"})
        m = par["autostart:messagerie.desktop"]
        self.assertEqual((m["nom"], m["description"], m["actif"]), ("Messagerie perso", "Messages instantanés", False))
        self.assertEqual((m["type"], m["groupe"], m["modifiable"], m["raison"]), ("appli", "toi", True, None))
        self.assertEqual((m["quand"], m["avertissement"], m["modifie"]), ("À l'ouverture de session", None, None))
        self.assertTrue(par["autostart:outil.desktop"]["actif"])

    def test_applis_ignorees_autres_bureaux_et_tryexec(self):
        for nom, lignes in (("gnome", ("OnlyShowIn=GNOME;Unity;",)), ("pas-kde", ("NotShowIn=KDE;",)),
                            ("kde-et-gnome", ("OnlyShowIn=KDE;GNOME;",)), ("sans-programme", ("TryExec=absent",)),
                            ("avec-programme", ("TryExec=present",)), ("pas-gnome", ("NotShowIn=GNOME;",))):
            self.poser(self.systeme, f"{nom}.desktop", desktop(nom, *lignes))
        entrees, ignorees = self.applis(existe=lambda p: "/usr/bin/present" if p == "present" else None)
        self.assertEqual(sorted(e["id"] for e in entrees),
                         ["autostart:avec-programme.desktop", "autostart:kde-et-gnome.desktop",
                          "autostart:pas-gnome.desktop"])
        self.assertEqual(ignorees, 3)

    def test_applis_hidden_et_gnome_enabled(self):
        for nom, ligne in (("cachee", "Hidden=true"), ("cachee-maj", "Hidden=True"), ("gnome-non",
                           "X-GNOME-Autostart-enabled=false"), ("visible", "Hidden=false"),
                           ("gnome-oui", "X-GNOME-Autostart-enabled=true")):
            self.poser(self.systeme, f"{nom}.desktop", desktop(nom, ligne))
        actifs = {e["id"].split(":")[1]: e["actif"] for e in self.applis()[0]}
        self.assertEqual(actifs, {"cachee.desktop": False, "cachee-maj.desktop": False, "gnome-non.desktop": False,
                                  "visible.desktop": True, "gnome-oui.desktop": True})

    def test_applis_x_systemd_skip_verrouillee(self):
        self.poser(self.systeme, "agent.desktop", desktop("Agent", "X-systemd-skip=true"))
        e = self.applis()[0][0]
        self.assertEqual((e["groupe"], e["modifiable"], e["raison"]), ("essentiel", False, "Lancé par un service de Plasma."))

    def test_applis_essentielles_verrouillees(self):
        self.assertEqual(D.ESSENTIELS_AUTOSTART, (
            "org.kde.plasmashell.desktop", "polkit-kde-authentication-agent-1.desktop", "pam_kwallet_init.desktop",
            "at-spi-dbus-bus.desktop", "xdg-user-dirs.desktop", "powerdevil.desktop", "kaccess.desktop",
            "xembedsniproxy.desktop", "gmenudbusmenuproxy.desktop", "org.kde.plasma-fallback-session-restore.desktop"))
        self.assertEqual(D.ESSENTIELS_UTILISATEUR, (
            "pipewire", "wireplumber", "dbus", "xdg-", "plasma-", "kde", "org.kde.", "at-spi", "systemd-",
            "gpg-agent", "p11-kit", "gvfs", "grub-boot-success"))
        self.assertEqual(D.ESSENTIELS_SYSTEME, (
            "systemd-", "dbus", "NetworkManager.service", "polkit", "sddm", "plasmalogin", "gdm", "display-manager",
            "nvidia-", "bootc-", "rpm-ostree", "ostree-", "greenboot-", "tuned", "power-profiles", "upower",
            "udisks2", "rtkit", "firewalld", "auditd", "chronyd", "uupd"))
        self.assertEqual(D.HEALTH_HUB, {
            "centre-bazzite-releve.timer": "Health Hub ne se mettra plus à jour tout seul : ses pages montreront "
                                           "des données anciennes.",
            "health-hub-modejeu.service": "Le mode jeu automatique ne s'activera plus.",
            "maj-apps.timer": "Vicinae, Ollama, uv et distrobox ne seront plus mis à jour la nuit.",
            "bazzite-health.timer": "Plus de bilan de la semaine le lundi."})
        self.poser(self.systeme, "org.kde.plasmashell.desktop", PLASMA)
        self.poser(self.systeme, "kaccess.desktop", desktop("Accessibilité", "OnlyShowIn=KDE"))
        par = {e["id"]: e for e in self.applis()[0]}
        for id_ in ("autostart:org.kde.plasmashell.desktop", "autostart:kaccess.desktop"):
            self.assertEqual((par[id_]["groupe"], par[id_]["modifiable"], par[id_]["raison"]),
                             ("essentiel", False, "Essentiel au bureau."))

    def test_applis_fichier_non_utf8_ignore(self):
        (self.systeme / "latin1.desktop").write_bytes(b"[Desktop Entry]\nName=\xe9t\xe9\nExec=x\n")
        os.symlink("/nulle-part/casse.desktop", self.systeme / "casse.desktop")
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.poser(self.systeme, "sans-section.desktop", "Name=Rien\n")
        entrees, ignorees = self.applis()
        self.assertEqual([e["id"] for e in entrees], ["autostart:messagerie.desktop"])
        self.assertEqual(ignorees, 3)

    def test_applis_modifie_depuis_le_journal(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        journal = {"autostart:messagerie.desktop": {"date": "2026-11-10T20:00:00",
                                                    "avant": {"actif": True, "fichier": None},
                                                    "apres": {"actif": False, "fichier": "x"}}}
        e = self.applis(journal=journal)[0][0]
        self.assertEqual(e["modifie"], {"date": "2026-11-10T20:00:00", "avant": True})


class Unites(BaseLancement):
    def test_unites_groupes(self):
        par = self.unites()
        self.assertEqual(sorted(par), [
            "unite:bazzite-exemple.service", "unite:bazzite-health.timer", "unite:centre-bazzite-releve.timer",
            "unite:dbus-broker.service", "unite:dbus.socket", "unite:health-hub-modejeu.service",
            "unite:lanceur.service", "unite:maj-apps.timer", "unite:outil-perso.service", "unite:pipewire.socket",
            "unite:sauvegarde-notes.timer", "unite:synchro.timer", "unite:systemd-tmpfiles-clean.timer",
            "unite:xdg-user-dirs.service"])
        t = par["unite:sauvegarde-notes.timer"]
        self.assertEqual((t["nom"], t["description"], t["type"], t["actif"], t["groupe"], t["modifiable"]),
                         ("sauvegarde-notes.timer", "Sauvegarde des notes", "minuteur", True, "toi", True))
        s = par["unite:lanceur.service"]
        self.assertEqual((s["type"], s["actif"], s["groupe"], s["quand"], s["raison"]),
                         ("service", True, "toi", "À l'ouverture de session", None))
        o = par["unite:outil-perso.service"]        # désactivée, son fichier est dans ~/.config/systemd/user
        self.assertEqual((o["actif"], o["groupe"], o["modifiable"], o["quand"]), (False, "toi", True, "À la demande"))
        h = par["unite:health-hub-modejeu.service"]
        self.assertEqual((h["groupe"], h["modifiable"], h["avertissement"]),
                         ("healthhub", True, "Le mode jeu automatique ne s'activera plus."))
        self.assertEqual(par["unite:bazzite-health.timer"]["groupe"], "healthhub")
        self.assertFalse(par["unite:bazzite-health.timer"]["actif"])
        b = par["unite:bazzite-exemple.service"]
        self.assertEqual((b["groupe"], b["modifiable"], b["raison"]),
                         ("bazzite", False, "Activé par Bazzite pour tous les comptes."))
        p = par["unite:pipewire.socket"]
        self.assertEqual((p["type"], p["groupe"], p["modifiable"], p["raison"], p["quand"]),
                         ("socket", "essentiel", False, "Essentiel au bureau.", "À la demande"))
        self.assertEqual(par["unite:xdg-user-dirs.service"]["groupe"], "essentiel")
        self.assertNotIn("unite:sauvegarde-notes.service", par)     # static
        self.assertNotIn("unite:synchro.service", par)              # déclenchée par synchro.timer
        self.assertNotIn("unite:obex.service", par)                 # fournisseur, désactivée
        self.assertNotIn("unite:lecteur@.service", par)             # modèle sans instance
        lister, montrer = self.run.appels
        self.assertEqual(lister, ["env", "LC_ALL=C", "systemctl", "--user", "list-unit-files",
                                  "--type=service,timer,socket", "--no-legend", "--no-pager"])
        self.assertEqual(montrer[:15], ["env", "LC_ALL=C", "systemctl", "--user", "show", "--timestamp=unix", "-p",
                                        "Id", "-p", "Description", "-p", "FragmentPath", "-p", "ActiveState", "-p"])
        self.assertEqual(montrer[15:18], ["NextElapseUSecRealtime", "-p", "NextElapseUSecMonotonic"])
        for absente in ("sauvegarde-notes.service", "lecteur@.service", "dbus.service", "synchro.service"):
            self.assertNotIn(absente, montrer)
        self.assertIn("outil-perso.service", montrer)

    def test_unites_quand_minuteur(self):
        par = self.unites()
        self.assertEqual(par["unite:sauvegarde-notes.timer"]["quand"], "Prochaine : aujourd'hui à 22 h 30")
        self.assertEqual(par["unite:maj-apps.timer"]["quand"], "Prochaine : demain à 04 h 45")
        self.assertEqual(par["unite:centre-bazzite-releve.timer"]["quand"], "Prochaine : le 16 nov. à 10 h 06")
        self.assertEqual(par["unite:synchro.timer"]["quand"], "Arrêté")
        self.assertEqual(par["unite:bazzite-health.timer"]["quand"], "Arrêté")
        # minuteur monotone (OnBootSec, OnUnitActiveSec) : 1 j 2 h 9 min 3 s depuis l'allumage, il en est à
        # 1 j 2 h 6 min 26 s -> dans 2 min 37 s
        self.assertEqual(par["unite:systemd-tmpfiles-clean.timer"]["quand"], "Prochaine : aujourd'hui à 20 h 02")
        self.assertEqual(D.quand_minuteur("", "active", MAINTENANT, "infinity", lambda: MONOTONE),
                         "Sans prochaine échéance")
        self.assertEqual(D.quand_minuteur("@1794372300", "active", MAINTENANT, "1d 2h 9min 3s", lambda: MONOTONE),
                         "Prochaine : aujourd'hui à 20 h 02")      # le plus tôt des deux
        self.assertEqual(D.quand_minuteur("@1794372300", "active", MAINTENANT, "0", lambda: MONOTONE),
                         "Prochaine : demain à 04 h 45")
        self.assertEqual(D.quand_minuteur("@1794902400", "active", datetime(2026, 11, 30, 9, 0, tzinfo=timezone.utc)),
                         "Prochaine : le 17 nov. à 08 h 00")
        self.assertEqual(D.quand_minuteur("@1794902400", "active", datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)),
                         "Prochaine : le 17 nov. à 08 h 00")

    def test_unites_desactivee_par_health_hub_reste_visible(self):
        """Une unité du fournisseur activée par un lien de l'utilisateur, coupée par Health Hub, reste montrée tant que
        le journal la garde : sinon « Remettre comme avant » disparaîtrait avec elle."""
        self.run.etats["obex.service"] = "disabled"
        journal = {"unite:obex.service": {"date": "2026-11-10T20:00:00", "avant": {"actif": True, "fichier": None},
                                          "apres": {"actif": False, "fichier": None}}}
        o = self.unites(journal=journal)["unite:obex.service"]
        self.assertEqual((o["groupe"], o["modifiable"], o["actif"]), ("toi", True, False))
        self.assertEqual(o["modifie"], {"date": "2026-11-10T20:00:00", "avant": True})

    def test_unites_show_en_echec(self):
        """`show` en échec : l'état des unités est illisible (pas des minuteurs tous « Arrêté », sans description)."""
        self.run.echec_show = (1, "Failed to connect to bus: No medium found\n")
        with self.assertRaises(D.LectureImpossible) as ctx:
            self.unites()
        self.assertIn("Failed to connect to bus", str(ctx.exception))
        self.assertIn("show", str(ctx.exception))

    def test_unites_systemctl_en_echec(self):
        def run(cmd, timeout=120, entree=None):
            return 1, "Failed to connect to bus: No medium found\n"
        with self.assertRaises(D.LectureImpossible) as ctx:
            D.unites_utilisateur(run=run, racine_utilisateur=self.racine, racines_globales=(self.globale,))
        self.assertIn("Failed to connect to bus", str(ctx.exception))


class ServicesSysteme(unittest.TestCase):
    def test_services_systeme_tri_et_commandes(self):
        run = FauxSystemctl("/nulle-part")
        blame = [("exemple-impression.service", 1.2), ("NetworkManager-wait-online.service", 4.58),
                 ("systemd-journald.service", 0.3), ("autre.service", 9.0)]
        res = D.services_systeme(run=run, blame=blame)
        self.assertEqual([s["unite"] for s in res], [
            "NetworkManager-wait-online.service", "exemple-impression.service", "systemd-journald.service",
            "fstrim.timer", "lecteur-empreintes.service", "NetworkManager.service", "uupd.timer"])
        par = {s["unite"]: s for s in res}
        nm = par["NetworkManager-wait-online.service"]
        self.assertEqual((nm["description"], nm["secondes"], nm["duree"], nm["essentiel"], nm["commande"]),
                         ("Network Manager Wait Online", 4.58, "4,6 s", False,
                          "sudo systemctl disable NetworkManager-wait-online.service"))
        self.assertIn("greenboot", nm["explication"])
        j = par["systemd-journald.service"]
        self.assertEqual((j["essentiel"], j["commande"]), (True, None))
        self.assertEqual(par["fstrim.timer"]["commande"], "sudo systemctl disable --now fstrim.timer")
        self.assertEqual((par["fstrim.timer"]["secondes"], par["fstrim.timer"]["duree"]), (None, None))
        self.assertIsNone(par["exemple-impression.service"]["explication"])
        self.assertTrue(par["uupd.timer"]["essentiel"])
        self.assertTrue(par["NetworkManager.service"]["essentiel"])
        self.assertEqual(run.appels[0], ["env", "LC_ALL=C", "systemctl", "list-unit-files", "--type=service,timer",
                                         "--state=enabled", "--no-legend", "--no-pager"])
        self.assertEqual(run.appels[1][:8], ["env", "LC_ALL=C", "systemctl", "show", "-p", "Id", "-p", "Description"])
        self.assertNotIn("getty@.service", run.appels[1])        # un modèle ferait échouer tout `show`
        self.assertEqual(len(run.appels), 2)


class Regler(BaseLancement):
    def test_desactiver_appli_systeme_ecrit_copie_masquee(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        code, phrase = D.regler("autostart:messagerie.desktop", False, **self.kw())
        self.assertEqual((code, phrase), (0, "« Messagerie » ne se lancera plus à l'ouverture de session."))
        self.assertEqual(self.contenu(self.utilisateur, "messagerie.desktop"), MESSAGERIE_MASQUEE)
        self.assertEqual(self.contenu(self.systeme, "messagerie.desktop"), MESSAGERIE)
        self.assertEqual(sorted(p.name for p in self.utilisateur.iterdir()), ["messagerie.desktop"])  # pas de .tmp
        j = self.journal()["autostart:messagerie.desktop"]
        self.assertEqual(j["avant"], {"actif": True, "fichier": None})
        self.assertEqual(j["apres"], {"actif": False, "fichier": MESSAGERIE_MASQUEE})
        self.assertIn("date", j)
        self.assertEqual(self.run.appels, [])

    def test_activer_copie_masquee_supprime_le_fichier(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.poser(self.utilisateur, "messagerie.desktop", MESSAGERIE_MASQUEE)
        code, phrase = D.regler("autostart:messagerie.desktop", True, **self.kw())
        self.assertEqual((code, phrase), (0, "« Messagerie » se lancera à la prochaine ouverture de session."))
        self.assertFalse((self.utilisateur / "messagerie.desktop").exists())
        self.assertEqual(self.journal()["autostart:messagerie.desktop"]["apres"], {"actif": True, "fichier": None})

    def test_activer_override_preexistant_garde_le_fichier(self):
        self.poser(self.systeme, "indexation.desktop", INDEXATION)
        self.poser(self.utilisateur, "indexation.desktop", INDEXATION_OVERRIDE)
        code, _ = D.regler("autostart:indexation.desktop", True, **self.kw())
        self.assertEqual(code, 0)
        self.assertEqual(self.contenu(self.utilisateur, "indexation.desktop"),
                         INDEXATION_OVERRIDE.replace("Hidden = true\r\n", "Hidden=false\r\n"))
        e = {e["id"]: e for e in self.applis()[0]}["autostart:indexation.desktop"]
        self.assertTrue(e["actif"])

    def test_activer_masque_minimal_supprime_le_fichier(self):
        """I-2 : un masque minimal (« [Desktop Entry] » et « Hidden=true », sans Exec) remplace le fichier du système.
        Y écrire Hidden=false laisserait une entrée sans programme, affichée « Activé » mais jamais lancée : il est
        supprimé et le fichier du système revient. Le journal garde le masque exact, que « Remettre » rend."""
        masque = "[Desktop Entry]\nHidden=true\n"
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.poser(self.utilisateur, "messagerie.desktop", masque)
        e = self.applis()[0][0]
        self.assertEqual((e["id"], e["nom"], e["actif"], e["modifiable"]),
                         ("autostart:messagerie.desktop", "Messagerie", False, True))
        self.assertEqual(D.regler("autostart:messagerie.desktop", True, **self.kw()),
                         (0, "« Messagerie » se lancera à la prochaine ouverture de session."))
        self.assertFalse((self.utilisateur / "messagerie.desktop").exists())
        j = self.journal()["autostart:messagerie.desktop"]
        self.assertEqual((j["avant"], j["apres"]), ({"actif": False, "fichier": masque}, {"actif": True, "fichier": None}))
        self.assertTrue(self.applis()[0][0]["actif"])
        self.assertEqual(D.remettre("autostart:messagerie.desktop", **self.kw()),
                         (0, "« Messagerie » est revenu comme avant."))
        self.assertEqual(self.contenu(self.utilisateur, "messagerie.desktop"), masque)
        self.assertEqual(self.journal(), {})

    def test_desactiver_fichier_sans_fin_de_ligne(self):
        self.poser(self.systeme, "outil.desktop", "[Desktop Entry]\nName=Outil\nExec=outil")
        self.assertEqual(D.regler("autostart:outil.desktop", False, **self.kw())[0], 0)
        self.assertEqual(self.contenu(self.utilisateur, "outil.desktop"),
                         "[Desktop Entry]\nName=Outil\nExec=outil\nHidden=true\n")
        self.assertEqual(D.regler("autostart:outil.desktop", True, **self.kw())[0], 0)
        self.assertFalse((self.utilisateur / "outil.desktop").exists())     # la copie masquée exacte s'en va

    def test_activer_entree_masquee_par_le_systeme(self):
        """Entrée coupée dans /etc (Hidden=true) : la copie utilisateur dit Hidden=false, rien n'est supprimé."""
        self.poser(self.systeme, "outil.desktop", desktop("Outil", "Hidden=true"))
        self.assertEqual(D.regler("autostart:outil.desktop", True, **self.kw())[0], 0)
        self.assertEqual(self.contenu(self.utilisateur, "outil.desktop"), desktop("Outil", "Hidden=false"))
        self.assertEqual(self.contenu(self.systeme, "outil.desktop"), desktop("Outil", "Hidden=true"))

    def test_activer_entree_coupee_par_gnome_enabled(self):
        self.poser(self.utilisateur, "outil.desktop", desktop("Outil", "X-GNOME-Autostart-enabled=false"))
        self.assertEqual(D.regler("autostart:outil.desktop", True, **self.kw())[0], 0)
        self.assertEqual(self.contenu(self.utilisateur, "outil.desktop"),
                         desktop("Outil", "X-GNOME-Autostart-enabled=true").replace("Exec=outil\n",
                                                                                    "Exec=outil\nHidden=false\n"))

    def test_desactiver_minuteur_commande(self):
        code, phrase = D.regler("unite:sauvegarde-notes.timer", False, **self.kw())
        self.assertEqual((code, phrase), (0, "Minuteur « sauvegarde-notes.timer » arrêté."))
        self.assertEqual(self.run.bascules(), [["systemctl", "--user", "disable", "--now", "sauvegarde-notes.timer"]])
        j = self.journal()["unite:sauvegarde-notes.timer"]
        self.assertEqual((j["avant"], j["apres"]), ({"actif": True, "fichier": None}, {"actif": False, "fichier": None}))
        code, phrase = D.regler("unite:synchro.timer", True, **self.kw())
        self.assertEqual((code, phrase), (0, "Minuteur « synchro.timer » remis en route."))
        self.assertEqual(self.run.bascules()[-1], ["systemctl", "--user", "enable", "--now", "synchro.timer"])

    def test_desactiver_service_sans_now(self):
        code, phrase = D.regler("unite:lanceur.service", False, **self.kw())
        self.assertEqual((code, phrase), (0, "« lanceur.service » ne se lancera plus à l'ouverture de session."))
        self.assertEqual(self.run.bascules(), [["systemctl", "--user", "disable", "lanceur.service"]])
        code, phrase = D.regler("unite:outil-perso.service", True, **self.kw())
        self.assertEqual((code, phrase), (0, "« outil-perso.service » se lancera à la prochaine ouverture de session."))
        self.assertEqual(self.run.bascules()[-1], ["systemctl", "--user", "enable", "outil-perso.service"])

    def test_journal_ecrit_avant_systemctl(self):
        vu = {}

        def run(cmd, timeout=120, entree=None):
            if "disable" in cmd:
                vu["journal"] = self.journal()
            return self.run(cmd, timeout, entree)
        D.regler("unite:lanceur.service", False, **{**self.kw(), "run": run})
        self.assertIn("unite:lanceur.service", vu["journal"])

    def test_echec_systemctl_retire_le_journal(self):
        self.run.echec = (1, "Failed to disable unit: Access denied\n")
        code, phrase = D.regler("unite:lanceur.service", False, **self.kw())
        self.assertEqual((code, phrase), (1, "Échec : Failed to disable unit: Access denied"))
        self.assertNotIn("unite:lanceur.service", self.journal())
        # une ligne déjà là garde son « avant » d'origine
        ancienne = {"date": "2026-11-09T08:00:00", "avant": {"actif": False, "fichier": None},
                    "apres": {"actif": True, "fichier": None}}
        commun.ecrire_json(self.dossier / "demarrage-journal.json", {"unite:lanceur.service": ancienne})
        self.assertEqual(D.regler("unite:lanceur.service", False, **self.kw())[0], 1)
        self.assertEqual(self.journal(), {"unite:lanceur.service": ancienne})

    def test_deux_bascules_gardent_l_avant_d_origine(self):
        self.poser(self.systeme, "indexation.desktop", INDEXATION)
        self.poser(self.utilisateur, "indexation.desktop", INDEXATION_OVERRIDE)
        self.assertEqual(D.regler("autostart:indexation.desktop", True, **self.kw())[0], 0)
        date = self.journal()["autostart:indexation.desktop"]["date"]
        self.assertEqual(D.regler("autostart:indexation.desktop", False, **self.kw())[0], 0)
        j = self.journal()["autostart:indexation.desktop"]
        self.assertEqual(j["avant"], {"actif": False, "fichier": INDEXATION_OVERRIDE})
        self.assertEqual(j["apres"]["actif"], False)
        self.assertEqual(j["apres"]["fichier"], self.contenu(self.utilisateur, "indexation.desktop"))
        self.assertGreaterEqual(j["date"], date)
        # rendu par « Remettre » octet pour octet : « Hidden = true » d'origine, pas le « Hidden=true » réécrit
        self.assertEqual(D.remettre("autostart:indexation.desktop", **self.kw())[0], 0)
        self.assertEqual(self.contenu(self.utilisateur, "indexation.desktop"), INDEXATION_OVERRIDE)

    def test_deuxieme_bascule_apres_modification_ailleurs_repart_de_l_etat_lu(self):
        """I-1 : Health Hub coupe l'appli ; tu la réactives dans les réglages de KDE et changes ses options ; Health Hub
        la recoupe. L'« avant » est alors ton fichier relu, pas l'absence de fichier d'il y a deux bascules : « Remettre »
        le rend au lieu de le supprimer (et tes options avec)."""
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.assertEqual(D.regler("autostart:messagerie.desktop", False, **self.kw())[0], 0)
        perso = MESSAGERIE.replace("Exec=messagerie --tray", "Exec=messagerie --tray --mes-options")
        self.poser(self.utilisateur, "messagerie.desktop", perso)          # réglages de KDE, après Health Hub
        self.assertEqual(D.regler("autostart:messagerie.desktop", False, **self.kw()),
                         (0, "« Messagerie » ne se lancera plus à l'ouverture de session."))
        j = self.journal()["autostart:messagerie.desktop"]
        self.assertEqual(j["avant"], {"actif": True, "fichier": perso})
        self.assertEqual(j["apres"], {"actif": False, "fichier": D._poser(perso, {"Hidden": "true"})})
        self.assertEqual(D.remettre("autostart:messagerie.desktop", **self.kw()),
                         (0, "« Messagerie » est revenu comme avant."))
        self.assertEqual(self.contenu(self.utilisateur, "messagerie.desktop"), perso)
        self.assertEqual(self.journal(), {})

    def test_retour_a_l_origine_retire_la_ligne(self):
        """T2 n° 58 : une bascule qui ramène l'entrée exactement à son « avant » (même état, même fichier) retire la
        ligne du journal : plus de badge « Modifié par Health Hub » ni de « Remettre comme avant »."""
        self.assertEqual(D.regler("unite:lanceur.service", False, **self.kw())[0], 0)
        self.assertIn("unite:lanceur.service", self.journal())
        self.assertEqual(D.regler("unite:lanceur.service", True, **self.kw()),
                         (0, "« lanceur.service » se lancera à la prochaine ouverture de session."))
        self.assertNotIn("unite:lanceur.service", self.journal())
        self.assertIsNone(self.unites(journal=self.journal())["unite:lanceur.service"]["modifie"])
        self.assertEqual(D.regler("unite:sauvegarde-notes.timer", False, **self.kw())[0], 0)
        self.assertEqual(D.regler("unite:sauvegarde-notes.timer", True, **self.kw())[0], 0)
        self.assertEqual(self.journal(), {})
        # appli : la copie masquée écrite, puis supprimée -> plus de fichier, comme avant
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.assertEqual(D.regler("autostart:messagerie.desktop", False, **self.kw())[0], 0)
        self.assertEqual(D.regler("autostart:messagerie.desktop", True, **self.kw())[0], 0)
        self.assertFalse((self.utilisateur / "messagerie.desktop").exists())
        self.assertEqual(self.journal(), {})
        self.assertIsNone(self.applis(journal=self.journal())[0][0]["modifie"])

    def assertRefus(self, id_, actif, phrase, commandes=None):
        avant = sorted(str(p) for p in Path(self.tmp.name).rglob("*"))
        self.assertEqual(D.regler(id_, actif, **self.kw()), (2, phrase))
        self.assertEqual(sorted(str(p) for p in Path(self.tmp.name).rglob("*")), avant)   # rien d'écrit
        self.assertEqual(self.run.bascules(), [])
        if commandes is not None:
            self.assertEqual(self.run.appels, commandes)

    def test_regler_refuse_essentiel(self):
        self.poser(self.systeme, "org.kde.plasmashell.desktop", PLASMA)
        self.poser(self.systeme, "agent.desktop", desktop("Agent", "X-systemd-skip=true"))
        self.assertRefus("autostart:org.kde.plasmashell.desktop", False,
                         "« Plasma » est verrouillé : Health Hub n'y touche pas.")
        self.assertRefus("autostart:agent.desktop", False, "« Agent » est verrouillé : Health Hub n'y touche pas.")
        self.assertRefus("unite:pipewire.socket", False,
                         "« pipewire.socket » est verrouillé : Health Hub n'y touche pas.")
        self.assertRefus("unite:systemd-tmpfiles-clean.timer", False,
                         "« systemd-tmpfiles-clean.timer » est verrouillé : Health Hub n'y touche pas.")

    def test_regler_refuse_bazzite(self):
        self.assertRefus("unite:bazzite-exemple.service", False,
                         "« bazzite-exemple.service » est verrouillé : Health Hub n'y touche pas.")

    def test_regler_refuse_id_inconnu_ou_chemin(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        for id_ in ("autostart:../x.desktop", "autostart:..desktop", "autostart:messagerie.desktop/../x.desktop",
                    "unite:../../x.service", "unite:x.service;reboot", "unite:-now.service", "unite:x.target",
                    "messagerie.desktop", "autostart:messagerie", "", "unite:a/b.timer"):
            with self.subTest(id_=id_):
                self.assertRefus(id_, False, f"Entrée inconnue : {id_}.", commandes=[])
        for id_ in ("unite:sshd.service", "unite:sauvegarde-notes.service", "unite:obex.service",
                    "autostart:inconnu.desktop"):
            with self.subTest(id_=id_):
                self.assertRefus(id_, False, f"Entrée inconnue : {id_}.")

    def test_deja_dans_cet_etat(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        self.assertEqual(D.regler("autostart:messagerie.desktop", True, **self.kw()),
                         (0, "« Messagerie » est déjà dans cet état."))
        self.assertEqual(D.regler("unite:lanceur.service", True, **self.kw()),
                         (0, "« lanceur.service » est déjà dans cet état."))
        self.assertFalse(self.utilisateur.exists())
        self.assertEqual(self.journal(), {})
        self.assertEqual(self.run.bascules(), [])


class Remettre(BaseLancement):
    def test_remettre_rend_le_fichier_exact(self):
        self.poser(self.systeme, "indexation.desktop", INDEXATION)
        self.poser(self.utilisateur, "indexation.desktop", INDEXATION_OVERRIDE)
        D.regler("autostart:indexation.desktop", True, **self.kw())
        self.assertEqual(D.remettre("autostart:indexation.desktop", **self.kw()),
                         (0, "« Indexation » est revenu comme avant."))
        self.assertEqual((self.utilisateur / "indexation.desktop").read_bytes(), INDEXATION_OVERRIDE.encode("utf-8"))
        self.assertEqual(self.journal(), {})
        # avant : pas de fichier utilisateur -> remettre le supprime
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        D.regler("autostart:messagerie.desktop", False, **self.kw())
        self.assertTrue((self.utilisateur / "messagerie.desktop").exists())
        self.assertEqual(D.remettre("autostart:messagerie.desktop", **self.kw())[0], 0)
        self.assertFalse((self.utilisateur / "messagerie.desktop").exists())

    def test_remettre_unite(self):
        D.regler("unite:sauvegarde-notes.timer", False, **self.kw())
        self.assertEqual(D.remettre("unite:sauvegarde-notes.timer", **self.kw()),
                         (0, "« sauvegarde-notes.timer » est revenu comme avant."))
        self.assertEqual(self.run.bascules()[-1], ["systemctl", "--user", "enable", "--now", "sauvegarde-notes.timer"])
        self.assertEqual(self.journal(), {})
        D.regler("unite:lanceur.service", False, **self.kw())
        self.assertEqual(D.remettre("unite:lanceur.service", **self.kw())[0], 0)
        self.assertEqual(self.run.bascules()[-1], ["systemctl", "--user", "enable", "lanceur.service"])
        self.assertEqual(D.remettre("unite:lanceur.service", **self.kw()),
                         (2, "Rien à remettre pour unite:lanceur.service."))

    def test_remettre_echec_systemctl_garde_la_ligne(self):
        D.regler("unite:lanceur.service", False, **self.kw())
        self.run.echec = (1, "Failed to enable unit: Access denied\n")
        self.assertEqual(D.remettre("unite:lanceur.service", **self.kw()),
                         (1, "Échec : Failed to enable unit: Access denied"))
        self.assertIn("unite:lanceur.service", self.journal())

    def test_remettre_refuse_si_modifie_ailleurs(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        D.regler("autostart:messagerie.desktop", False, **self.kw())
        change = MESSAGERIE_MASQUEE + "X-KDE-Change=1\n"
        self.poser(self.utilisateur, "messagerie.desktop", change)       # réglages de KDE, après Health Hub
        self.assertEqual(D.remettre("autostart:messagerie.desktop", **self.kw()),
                         (2, "« Messagerie » a changé depuis : rien n'est touché."))
        self.assertEqual(self.contenu(self.utilisateur, "messagerie.desktop"), change)
        self.assertEqual(self.journal(), {})
        # minuteur relancé à la main après Health Hub
        D.regler("unite:sauvegarde-notes.timer", False, **self.kw())
        self.run.actifs["sauvegarde-notes.timer"] = "active"
        n = len(self.run.bascules())
        self.assertEqual(D.remettre("unite:sauvegarde-notes.timer", **self.kw()),
                         (2, "« sauvegarde-notes.timer » a changé depuis : rien n'est touché."))
        self.assertEqual(len(self.run.bascules()), n)
        self.assertEqual(self.journal(), {})
        # service réactivé ailleurs
        D.regler("unite:lanceur.service", False, **self.kw())
        self.run.etats["lanceur.service"] = "enabled"
        self.assertEqual(D.remettre("unite:lanceur.service", **self.kw())[0], 2)
        self.assertEqual(self.journal(), {})

    def test_remettre_journal_impossible_a_ecrire(self):
        """A-2 : un journal qu'on ne peut plus réécrire donne « Échec : … » (code 1), jamais une trace, que la remise ait
        eu lieu ou que l'entrée ait changé depuis."""
        D.regler("unite:lanceur.service", False, **self.kw())
        with mock.patch.object(commun, "ecrire_json", side_effect=OSError("disque plein")):
            code, phrase = D.remettre("unite:lanceur.service", **self.kw())
            self.assertEqual(code, 1)
            self.assertTrue(phrase.startswith("Échec : "), phrase)
            self.assertIn("revenu comme avant", phrase)
            self.assertIn("disque plein", phrase)
            self.assertEqual(self.run.bascules()[-1], ["systemctl", "--user", "enable", "lanceur.service"])
            # la ligne est restée ; l'entrée n'est plus dans l'état « après » : la ligne à retirer ne s'écrit pas
            code, phrase = D.remettre("unite:lanceur.service", **self.kw())
            self.assertEqual(code, 1)
            self.assertTrue(phrase.startswith("Échec : "), phrase)
            self.assertIn("disque plein", phrase)
        self.assertEqual(D.remettre("unite:lanceur.service", **self.kw()),
                         (2, "« lanceur.service » a changé depuis : rien n'est touché."))
        self.assertEqual(self.journal(), {})

    def test_remettre_show_en_echec_garde_la_ligne(self):
        """Mineur 1 de la revue finale : `systemctl --user show` qui échoue rend l'état illisible (code 1) ; la ligne du
        minuteur reste, rien n'est lancé."""
        D.regler("unite:sauvegarde-notes.timer", False, **self.kw())
        n = len(self.run.bascules())
        self.run.echec_show = (1, "Failed to connect to bus: No medium found\n")
        code, phrase = D.remettre("unite:sauvegarde-notes.timer", **self.kw())
        self.assertEqual(code, 1)
        self.assertTrue(phrase.startswith("Échec : "), phrase)
        self.assertIn("Failed to connect to bus", phrase)
        self.assertIn("unite:sauvegarde-notes.timer", self.journal())
        self.assertEqual(len(self.run.bascules()), n)
        self.run.echec_show = None
        self.assertEqual(D.remettre("unite:sauvegarde-notes.timer", **self.kw())[0], 0)

    def test_remettre_refuse_id_forge(self):
        self.assertEqual(D.remettre("autostart:../x.desktop", **self.kw()), (2, "Entrée inconnue : autostart:../x.desktop."))
        self.assertEqual(D.remettre("autostart:messagerie.desktop", **self.kw()),
                         (2, "Rien à remettre pour autostart:messagerie.desktop."))
        self.assertEqual(self.run.appels, [])


class AuLancement(BaseLancement):
    def test_au_lancement_applis_puis_unites(self):
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        (self.systeme / "latin1.desktop").write_bytes(b"[Desktop Entry]\nName=\xe9t\xe9\n")
        commun.ecrire_json(self.dossier / "demarrage-journal.json", {
            "unite:lanceur.service": {"date": "2026-11-10T20:00:00", "avant": {"actif": True, "fichier": None},
                                      "apres": {"actif": True, "fichier": None}}})
        kw = self.kw()
        res = D.au_lancement(run=kw["run"], dossier=kw["dossier"], systeme=kw["systeme"],
                             utilisateur=kw["utilisateur"], racine_utilisateur=kw["racine_utilisateur"],
                             racines_globales=kw["racines_globales"], existe=kw["existe"], maintenant=MAINTENANT)
        self.assertEqual(res["ignorees"], 1)
        self.assertEqual(res["entrees"][0]["id"], "autostart:messagerie.desktop")
        par = {e["id"]: e for e in res["entrees"]}
        self.assertEqual(par["unite:lanceur.service"]["modifie"], {"date": "2026-11-10T20:00:00", "avant": True})
        self.assertIsNone(par["unite:maj-apps.timer"]["modifie"])
        self.assertIsNone(res["illisible"])

    def test_au_lancement_garde_les_applis_si_systemd_ne_repond_pas(self):
        """Re-revue : les applis ne dépendent pas de systemd. `systemctl --user show` ou `list-unit-files` en échec
        laisse les applis (et leur « Remettre comme avant »), sans unité ; le message va dans `illisible`, puis dans
        les erreurs du relevé."""
        self.poser(self.systeme, "messagerie.desktop", MESSAGERIE)
        commun.ecrire_json(self.dossier / "demarrage-journal.json", {
            "autostart:messagerie.desktop": {"date": "2026-11-10T20:00:00", "avant": {"actif": False, "fichier": "x"},
                                             "apres": {"actif": True, "fichier": None}}})
        kw = {k: v for k, v in self.kw().items() if k != "run"}

        def liste_en_panne(cmd, timeout=120, entree=None):
            if "list-unit-files" in cmd and "--user" in cmd:
                return 1, "Failed to connect to bus: No medium found\n"
            return self.run(cmd, timeout, entree)
        self.run.echec_show = (1, "Failed to connect to bus: No medium found\n")
        for panne, run in (("show", self.run), ("list-unit-files", liste_en_panne)):
            with self.subTest(panne=panne):
                res = D.au_lancement(run=run, maintenant=MAINTENANT, **kw)
                self.assertEqual([e["id"] for e in res["entrees"]], ["autostart:messagerie.desktop"])
                self.assertEqual(res["entrees"][0]["modifie"], {"date": "2026-11-10T20:00:00", "avant": False})
                self.assertEqual(res["illisible"], f"systemctl --user {panne} : Failed to connect to bus: No medium found")
                analyse = fausse_commande()

                def tout(cmd, timeout=120, entree=None, run=run):
                    return analyse(cmd, timeout) if "systemd-analyze" in cmd else run(cmd, timeout, entree)
                d = D.construire(run=tout, boot=lambda: "b1", btime=lambda: None, dossier=self.dossier,
                                 lancement=lambda: D.au_lancement(run=tout, maintenant=MAINTENANT, **kw),
                                 systeme=lambda blame: [])
                self.assertEqual([e["id"] for e in d["lancement"]["entrees"]], ["autostart:messagerie.desktop"])
                self.assertEqual(d["erreurs"], [f"Tes services et minuteurs illisibles (systemctl --user {panne} : "
                                                "Failed to connect to bus: No medium found)"])
        # remettre garde sa règle (point 9) : l'état d'un minuteur illisible -> code 1, ligne gardée
        self.run.echec_show = None
        D.regler("unite:sauvegarde-notes.timer", False, **self.kw())
        self.run.echec_show = (1, "Failed to connect to bus: No medium found\n")
        self.assertEqual(D.remettre("unite:sauvegarde-notes.timer", **self.kw())[0], 1)
        self.assertIn("unite:sauvegarde-notes.timer", self.journal())


class Cli(unittest.TestCase):
    def lancer(self, argv, **kw):
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = cli.main(argv, **kw)
        return code, sortie.getvalue(), erreur.getvalue()

    def test_cli_demarrage_releve_ecrit_et_republie(self):
        """A-5 : le relevé écrit avec le `run` injecté ; sans action, pas de retour (il efface celui d'avant)."""
        run = mock.Mock()
        ordre = []
        with mock.patch.object(D, "ecrire", side_effect=lambda **k: ordre.append("ecrire")) as ecrire, \
                mock.patch.object(D, "resume", return_value={"phrase": "Démarré en 40 s · habituel : 38 s"}):
            for argv in (["demarrage"], ["demarrage", "releve"]):
                ordre.clear()
                code, sortie, erreur = self.lancer(argv, run=run, ecrire_leger=lambda: ordre.append("leger"))
                self.assertEqual(code, 0)
                self.assertEqual(ordre, ["ecrire", "leger"])
                self.assertEqual(sortie, "Démarré en 40 s · habituel : 38 s\n")
                self.assertEqual(erreur, "")
        self.assertEqual(ecrire.call_args, mock.call(run=run))

    def test_cli_demarrage_regler_code_et_phrase(self):
        """I-4 et A-5 : l'écriture qui suit l'action reçoit le `run` injecté et le retour de l'action (id, code, phrase,
        date), que la fenêtre montre."""
        run = mock.Mock()
        ordre = []
        with mock.patch.object(D, "regler", side_effect=lambda *a, **k: ordre.append("regler") or (0, "Fait.")) as regler, \
                mock.patch.object(D, "ecrire", side_effect=lambda **k: ordre.append("ecrire")) as ecrire, \
                mock.patch.object(commun, "maintenant", return_value="2026-11-10T21:00:00"):
            code, sortie, erreur = self.lancer(["demarrage", "regler", "unite:x.timer", "non"], run=run,
                                               ecrire_leger=mock.Mock())
        self.assertEqual((code, sortie, erreur), (0, "Fait.\n", ""))
        self.assertEqual(ordre, ["regler", "ecrire"])
        regler.assert_called_once_with("unite:x.timer", False, run=run)
        ecrire.assert_called_once_with(run=run, retour={"id": "unite:x.timer", "code": 0, "phrase": "Fait.",
                                                        "date": "2026-11-10T21:00:00"})
        with mock.patch.object(D, "regler", return_value=(2, "« x » est verrouillé : Health Hub n'y touche pas.")), \
                mock.patch.object(D, "ecrire") as ecrire, \
                mock.patch.object(commun, "maintenant", return_value="2026-11-10T21:00:05"):
            code, sortie, erreur = self.lancer(["demarrage", "regler", "unite:x.timer", "oui"], run=run,
                                               ecrire_leger=mock.Mock())
        self.assertEqual((code, sortie, erreur), (2, "", "« x » est verrouillé : Health Hub n'y touche pas.\n"))
        ecrire.assert_called_once_with(run=run, retour={
            "id": "unite:x.timer", "code": 2, "phrase": "« x » est verrouillé : Health Hub n'y touche pas.",
            "date": "2026-11-10T21:00:05"})
        with mock.patch.object(D, "regler", return_value=(1, "Échec : non")), \
                mock.patch.object(D, "ecrire", side_effect=OSError("disque plein")):
            code, sortie, erreur = self.lancer(["demarrage", "regler", "unite:x.timer", "oui"], ecrire_leger=mock.Mock())
        self.assertEqual(code, 1)
        self.assertTrue(erreur.endswith("Échec : non\n"))
        for argv in (["demarrage", "regler", "unite:x.timer"], ["demarrage", "regler", "unite:x.timer", "peut-etre"]):
            with mock.patch.object(D, "regler") as regler, mock.patch.object(D, "ecrire") as ecrire:
                code, sortie, erreur = self.lancer(argv, ecrire_leger=mock.Mock())
            self.assertEqual(code, 2)
            regler.assert_not_called()
            ecrire.assert_not_called()
            self.assertIn("Usage", erreur)

    def test_cli_demarrage_remettre(self):
        run = mock.Mock()
        with mock.patch.object(D, "remettre", return_value=(0, "« x » est revenu comme avant.")) as remettre, \
                mock.patch.object(D, "ecrire") as ecrire, \
                mock.patch.object(commun, "maintenant", return_value="2026-11-10T21:00:00"):
            code, sortie, erreur = self.lancer(["demarrage", "remettre", "unite:x.timer"], run=run,
                                               ecrire_leger=mock.Mock())
        self.assertEqual((code, sortie, erreur), (0, "« x » est revenu comme avant.\n", ""))
        remettre.assert_called_once_with("unite:x.timer", run=run)
        ecrire.assert_called_once_with(run=run, retour={"id": "unite:x.timer", "code": 0,
                                                        "phrase": "« x » est revenu comme avant.",
                                                        "date": "2026-11-10T21:00:00"})
        with mock.patch.object(D, "remettre", return_value=(2, "« x » a changé depuis : rien n'est touché.")), \
                mock.patch.object(D, "ecrire") as ecrire:
            code, sortie, erreur = self.lancer(["demarrage", "remettre", "unite:x.timer"], ecrire_leger=mock.Mock())
        self.assertEqual((code, sortie, erreur), (2, "", "« x » a changé depuis : rien n'est touché.\n"))
        self.assertEqual(ecrire.call_args.kwargs["retour"]["code"], 2)
        self.assertEqual(ecrire.call_args.kwargs["retour"]["phrase"], "« x » a changé depuis : rien n'est touché.")

    def test_cli_retour_ecrit_dans_demarrage_json(self):
        """De bout en bout, avec un faux systemctl et des dossiers temporaires : le retour de l'action est dans
        demarrage.json ; le relevé suivant l'efface."""
        base = BaseLancement("setUp")
        base.setUp()
        self.addCleanup(base.doCleanups)
        kw = base.kw()
        reglages = {k: kw[k] for k in ("dossier", "systeme", "utilisateur", "racine_utilisateur", "racines_globales",
                                       "existe")}
        ecrire_vrai = D.ecrire

        def ecrire(**k):
            return ecrire_vrai(boot=lambda: "b1", btime=lambda: None, dossier=reglages["dossier"],
                               lancement=lambda: D.au_lancement(run=k["run"], **reglages),
                               systeme=lambda blame: [], **k)

        def run(cmd, timeout=120, entree=None):
            if cmd[:3] == ["env", "LC_ALL=C", "systemd-analyze"]:
                return fausse_commande()(cmd, timeout)
            return base.run(cmd, timeout, entree)
        regler_vrai, remettre_vrai = D.regler, D.remettre
        with mock.patch.object(D, "ecrire", side_effect=ecrire), \
                mock.patch.object(D, "regler", side_effect=lambda id_, actif, run: regler_vrai(
                    id_, actif, run=run, **reglages)), \
                mock.patch.object(D, "remettre", side_effect=lambda id_, run: remettre_vrai(id_, run=run, **reglages)), \
                mock.patch.object(D, "resume", return_value=None):
            code, _, _ = self.lancer(["demarrage", "regler", "unite:lanceur.service", "non"], run=run,
                                     ecrire_leger=mock.Mock())
            self.assertEqual(code, 0)
            d = commun.lire_json(reglages["dossier"] / "demarrage.json", None)
            self.assertEqual({k: d["retour"][k] for k in ("id", "code", "phrase")},
                             {"id": "unite:lanceur.service", "code": 0,
                              "phrase": "« lanceur.service » ne se lancera plus à l'ouverture de session."})
            self.assertTrue(d["retour"]["date"])
            lanceur = next(e for e in d["lancement"]["entrees"] if e["id"] == "unite:lanceur.service")
            self.assertEqual((lanceur["actif"], bool(lanceur["modifie"])), (False, True))
            base.run.etats["lanceur.service"] = "enabled"          # réactivé ailleurs
            code, _, erreur = self.lancer(["demarrage", "remettre", "unite:lanceur.service"], run=run,
                                          ecrire_leger=mock.Mock())
            self.assertEqual(code, 2)
            d = commun.lire_json(reglages["dossier"] / "demarrage.json", None)
            self.assertEqual((d["retour"]["code"], d["retour"]["phrase"]),
                             (2, "« lanceur.service » a changé depuis : rien n'est touché."))
            self.assertEqual(self.lancer(["demarrage"], run=run, ecrire_leger=mock.Mock())[0], 0)
            self.assertIsNone(commun.lire_json(reglages["dossier"] / "demarrage.json", None)["retour"])
        with mock.patch.object(D, "remettre") as remettre:
            self.assertEqual(self.lancer(["demarrage", "remettre"], ecrire_leger=mock.Mock())[0], 2)
        remettre.assert_not_called()

    def test_releve_horaire_lance_demarrage(self):
        unite = Path(__file__).resolve().parent.parent / "systemd" / "centre-bazzite-releve.service"
        lignes = unite.read_text(encoding="utf-8").splitlines()
        mien = "ExecStart=-%h/.local/bin/centre-bazzite demarrage"
        releve = "ExecStart=%h/.local/bin/centre-bazzite releve"
        controles = "ExecStart=-%h/.local/bin/centre-bazzite controles --si-perime"
        self.assertIn(mien, lignes)
        self.assertLess(lignes.index(releve), lignes.index(mien))
        self.assertLess(lignes.index(mien), lignes.index(controles))
        self.assertTrue(lignes[lignes.index(mien) - 1].startswith("#"))
        self.assertNotIn("demarrage", cli.LOURDES)       # D9 : léger, jamais reporté pendant un jeu


if __name__ == "__main__":
    unittest.main()
