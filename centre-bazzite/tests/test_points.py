import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from centre_bazzite import commun, points as P
from tests import configuration

MAINTENANT = datetime(2026, 11, 9, 12, 0, 0)


def sante(**kw):
    base = {"ssd": [], "volumes": [], "services_en_echec": [], "ollama": None,
            "erreurs_journal": [], "plantages": []}
    base.update(kw)
    return base


def vol(chemin, nom, pct, total=1000.0):
    return {"nom": nom, "chemin": chemin, "total_go": total,
            "libre_go": total * (100 - pct) / 100, "pourcent_utilise": pct}


def calculer(s, dep=None, maj=None, session=None, **kw):
    return P.points(s, dep or {"courant": None, "en_attente": None, "precedent": None},
                    maj, session, maintenant=MAINTENANT, **kw)


def par_id(liste):
    return {p["id"]: p for p in liste}


def ssd(**kw):
    h = {"usure": 1, "reserve": 100, "seuil_reserve": 10, "temperature": 40,
         "erreurs_media": 0, "arrets_brutaux": 0, "heures": 5, "ecrit_to": 1,
         "avertissements": []}
    h.update(kw)
    return sante(ssd=[{"modele": "X", "bus": "nvme", "sante": h}])


UUPD_OK_7 = {"unite": "uupd.service", "debut": "2026-11-07T04:00:00", "fin": "2026-11-07T04:10:00", "succes": True}
UUPD_KO_8 = {"unite": "uupd.service", "debut": "2026-11-08T04:00:00", "fin": "2026-11-08T04:10:00", "succes": False}
UUPD_OK_9 = {"unite": "uupd.service", "debut": "2026-11-09T04:00:00", "fin": "2026-11-09T04:10:00", "succes": True}
MAJ_KO = {"date": "2026-11-08T04:45:00", "resultats": [{"module": "ollama", "etat": "échec", "message": "m"}]}
MAJ_OK_9 = {"date": "2026-11-09T04:45:00", "resultats": [{"module": "ollama", "etat": "à jour", "message": "m"}]}


def session_ko(etape):
    etapes = {n: {"statut": "fini", "progression": 100, "detail": ""} for n in ("uupd", "maj-apps", "notes", "resume", "etat")}
    etapes[etape] = {"statut": "echec", "progression": 10, "detail": "boum"}
    return {"debut": "2026-11-08T22:00:00", "fin": "2026-11-08T23:00:00", "succes": False, "etapes": etapes}


class Regles(unittest.TestCase):
    def test_externe_91_attention(self):
        p = par_id(calculer(sante(volumes=[vol("/var/mnt/EXTERNE", "Externe", 91.0)])))
        pt = p["volume:/var/mnt/EXTERNE"]
        self.assertEqual(pt["gravite"], "attention")
        self.assertEqual(pt["titre"], "Externe : plus que 90 Go libres")
        self.assertEqual(pt["detail"], "Il reste 90 Go libres sur 1 000 Go. "
                         "Libère de la place avant que les mises à jour ou les jeux échouent.")
        self.assertNotIn("%", pt["titre"] + pt["detail"])
        self.assertEqual((pt["mesure"], pt["cran"], pt["en_sourdine"]), (91.0, 3.0, False))

    def test_petit_volume_ok_et_gros_volume_peu_libre(self):
        self.assertEqual(calculer(sante(volumes=[vol("/a", "A", 80.0)])), [])
        # 1000 Go total, 14 Go libres (98,6 %) -> déjà > 90 ; test avec 200 Go, 14 libres
        v = {"nom": "G", "chemin": "/g", "total_go": 200.0, "libre_go": 14.0, "pourcent_utilise": 93.0}
        self.assertIn("volume:/g", par_id(calculer(sante(volumes=[v]))))
        v2 = {"nom": "G", "chemin": "/g", "total_go": 200.0, "libre_go": 20.0, "pourcent_utilise": 90.0}
        self.assertNotIn("volume:/g", par_id(calculer(sante(volumes=[v2]))))
        v3 = {"nom": "G", "chemin": "/g", "total_go": 50.0, "libre_go": 10.0, "pourcent_utilise": 80.0}
        self.assertNotIn("volume:/g", par_id(calculer(sante(volumes=[v3]))))

    def test_redemarrage_id_par_version(self):
        dep = {"courant": None, "en_attente": {"version": "45.20261108"}, "precedent": None}
        pt = par_id(calculer(sante(), dep))["redemarrage:45.20261108"]
        self.assertEqual(pt["gravite"], "attention")
        self.assertIn("Bazzite 45.20261108 attend un redémarrage", pt["titre"])
        s = {"redemarrage:45.1": 1.0}
        liste = P.appliquer_sourdines(
            calculer(sante(), {"en_attente": {"version": "45.1"}}) +
            calculer(sante(), {"en_attente": {"version": "45.2"}}), s)
        d = par_id(liste)
        self.assertTrue(d["redemarrage:45.1"]["en_sourdine"])
        self.assertFalse(d["redemarrage:45.2"]["en_sourdine"])

    def test_services_et_journal(self):
        s = sante(services_en_echec=["foo.service"], erreurs_journal=[{"message": "x", "source": "s", "nombre": 3}],
                  plantages=[{"x": 1}])
        p = par_id(calculer(s))
        self.assertEqual(p["service:foo.service"]["gravite"], "attention")
        self.assertEqual(p["journal:erreurs"]["gravite"], "info")
        self.assertEqual(p["plantages"]["gravite"], "info")

    def test_ssd(self):
        self.assertEqual(calculer(ssd()), [])
        self.assertEqual(par_id(calculer(ssd(erreurs_media=2)))["ssd:X:critique:erreurs-media"]["gravite"], "echec")
        self.assertEqual(par_id(calculer(ssd(avertissements=["spare"])))["ssd:X:critique:spare"]["gravite"], "echec")
        u = par_id(calculer(ssd(usure=80)))["ssd:X:usure"]
        self.assertEqual((u["gravite"], u["mesure"], u["cran"]), ("attention", 80.0, 5.0))
        r = par_id(calculer(ssd(reserve=5, seuil_reserve=10)))
        self.assertNotIn("ssd:X:usure", r)
        self.assertNotIn("None", r["ssd:X:reserve"]["titre"])
        self.assertEqual(r["ssd:X:reserve"]["mesure"], 95.0)
        c = par_id(calculer(ssd(temperature=70)))["ssd:X:chaleur"]
        self.assertEqual((c["mesure"], c["cran"]), (70.0, 5.0))
        self.assertNotIn("ssd:X:chaleur", par_id(calculer(ssd(temperature=69))))
        self.assertEqual(calculer(sante(ssd=[{"modele": "Y", "bus": "sata", "sante": None}])), [])

    def test_ollama(self):
        o = lambda depuis, m=(): sante(ollama={"actif": True, "depuis": depuis, "modeles_charges": list(m)})
        self.assertIn("ollama:inactif", par_id(calculer(o("Mon 2026-11-09 08:00:00 CET"))))
        self.assertIn("ollama:inactif", par_id(calculer(o("2026-11-09T08:00:00"))))
        self.assertNotIn("ollama:inactif", par_id(calculer(o("Mon 2026-11-09 11:00:00 CET"))))
        self.assertNotIn("ollama:inactif", par_id(calculer(o("2026-11-09T08:00:00", ["m"]))))
        self.assertNotIn("ollama:inactif", par_id(calculer(o("n'importe quoi"))))
        self.assertNotIn("ollama:inactif", par_id(calculer(sante(ollama={"actif": False, "depuis": None, "modeles_charges": []}))))

    def test_echec_uupd_porte_sa_date(self):
        pt = par_id(calculer(sante(), uupd=[UUPD_OK_7, UUPD_KO_8]))["maj:echec:uupd:2026-11-08T04:10:00"]
        self.assertEqual(pt["gravite"], "echec")
        self.assertIn("le 8 novembre à 4 h 10", pt["detail"])
        self.assertIn("journalctl -u uupd.service", pt["detail"])
        self.assertNotIn("page Mises à jour", pt["detail"])     # passage de nuit : pas une session du Centre
        self.assertEqual([p["id"] for p in calculer(sante(), uupd=[UUPD_KO_8, UUPD_OK_9])], [])

    def test_echec_maj_apps(self):
        pt = par_id(calculer(sante(), maj=MAJ_KO))["maj:echec:maj-apps:2026-11-08T04:45:00"]
        self.assertEqual(pt["gravite"], "echec")
        self.assertIn("ollama", pt["detail"])
        self.assertIn("maj-apps --report", pt["detail"])
        self.assertEqual(calculer(sante(), maj={"date": "2026-11-09T04:45:00", "resultats": [{"etat": "à jour"}]}), [])

    def test_echec_de_session_efface_par_une_reussite_plus_recente(self):
        s = session_ko("uupd")
        pt = par_id(calculer(sante(), session=s))["maj:echec:uupd:2026-11-08T23:00:00"]
        self.assertIn("Pendant « Tout mettre à jour » : boum", pt["detail"])
        self.assertIn("page Mises à jour", pt["detail"])
        self.assertEqual(calculer(sante(), session=s, uupd=[UUPD_OK_9]), [])
        s = session_ko("maj-apps")
        self.assertIn("maj:echec:maj-apps:2026-11-08T23:00:00", par_id(calculer(sante(), session=s)))
        self.assertEqual(calculer(sante(), session=s, maj=MAJ_OK_9), [])

    def test_echecs_hors_mise_a_jour_sont_une_information(self):
        s = session_ko("resume")
        pts = calculer(sante(), session=s)
        self.assertEqual([(p["id"], p["gravite"]) for p in pts], [("session:echec:2026-11-08T22:00:00", "info")])
        self.assertEqual(P.couleur(pts, False), "vert")

    def test_nouvel_echec_n_est_pas_en_sourdine(self):
        sourdines = {"maj:echec:uupd:2026-11-08T04:10:00": 0.0}
        nouveau = dict(UUPD_KO_8, debut="2026-11-09T04:00:00", fin="2026-11-09T04:10:00")
        pts = P.appliquer_sourdines(calculer(sante(), uupd=[UUPD_KO_8, nouveau]), sourdines)
        self.assertEqual([(p["id"], p["en_sourdine"]) for p in pts], [("maj:echec:uupd:2026-11-09T04:10:00", False)])

    def test_ssd_critique_cite_le_vrai_disque(self):
        s = ssd(erreurs_media=1)
        s["ssd"][0]["peripherique"] = "/dev/nvme0n1"
        detail = calculer(s)[0]["detail"]
        self.assertIn("sudo smartctl -a /dev/nvme0n1", detail)
        self.assertNotIn("/dev/disque", detail)
        self.assertNotIn("/dev/disque", calculer(ssd(erreurs_media=1))[0]["detail"])

    def test_ssd_change_d_identite_quand_l_alerte_change_de_nature(self):
        sourdines = {"ssd:X:critique:erreurs-media": 2.0}
        pts = P.appliquer_sourdines(calculer(ssd(erreurs_media=2, avertissements=["spare"])), sourdines)
        self.assertEqual([(p["id"], p["en_sourdine"]) for p in pts], [("ssd:X:critique:erreurs-media+spare", False)])

    def test_tolere_none(self):
        s = {k: None for k in ("ssd", "volumes", "services_en_echec", "ollama", "erreurs_journal", "plantages")}
        self.assertEqual(calculer(s), [])
        self.assertEqual(calculer(None), [])


GIO = 1024 ** 3


def controles(**kw):
    """Contrôles de bazzite-health sans rien à signaler, modifiés par kw."""
    c = {"date": "2026-11-09T10:00:00", "image": {"disponible": None}, "flatpak": {"a_mettre_a_jour": []},
         "runtimes": {"inutilises": [], "gl_obsoletes": []}, "telechargements": [],
         "caches": {"miniatures": 0, "corbeille": 0, "journal": 200 * 1024 ** 2},
         "boot": {"nom": "Démarrage", "chemin": "/boot", "libre_go": 0.64, "total_go": 0.95,
                  "pourcent_utilise": 32.9}}
    c.update(kw)
    return c


DEP_COURANT = {"courant": {"version": "45.20261105"}, "en_attente": None, "precedent": None, "nombre": 2}


class Controles(unittest.TestCase):
    def test_rien_a_signaler(self):
        self.assertEqual(calculer(sante(controles=controles()), DEP_COURANT), [])
        self.assertEqual(calculer(sante(controles=None), DEP_COURANT), [])

    def test_image_disponible_info_et_comptee(self):
        pts = calculer(sante(controles=controles(image={"disponible": "45.20261110"})), DEP_COURANT)
        pt = par_id(pts)["maj:dispo:image:45.20261110"]
        self.assertEqual((pt["gravite"], pt["mesure"], pt["cran"]), ("info", 0.0, 1.0))
        self.assertIn("45.20261110", pt["titre"])
        self.assertEqual(P.compteurs(pts)["majs"], 1)
        self.assertEqual(P.couleur(pts, False), "vert")

    def test_image_deja_deployee_ignoree(self):
        c = sante(controles=controles(image={"disponible": "45.20261110"}))
        attente = dict(DEP_COURANT, en_attente={"version": "45.20261110"})
        self.assertNotIn("maj:dispo:image:45.20261110", par_id(calculer(c, attente)))
        courant = dict(DEP_COURANT, courant={"version": "45.20261110"})
        self.assertNotIn("maj:dispo:image:45.20261110", par_id(calculer(c, courant)))

    def test_image_plus_ancienne_que_la_courante_ignoree(self):
        # le cache a vu 45.20261110 ; une image plus récente est déjà installée et démarrée
        c = sante(controles=controles(image={"disponible": "45.20261110"}))
        plus_recente = dict(DEP_COURANT, courant={"version": "45.20261112"})
        self.assertEqual(calculer(c, plus_recente), [])
        # … ou installée et en attente du redémarrage : seul « attend un redémarrage » reste
        attente = dict(DEP_COURANT, en_attente={"version": "45.20261112"})
        self.assertEqual([p["id"] for p in calculer(c, attente)], ["redemarrage:45.20261112"])

    def test_image_caduque_apres_uupd(self):
        uupd_11h = [{"unite": "uupd.service", "debut": "2026-11-09T10:50:00", "fin": "2026-11-09T11:00:00",
                     "succes": True}]
        a_10h = sante(controles=controles(date="2026-11-09T10:00:00", image={"disponible": "45.20261110"}))
        self.assertEqual(calculer(a_10h, DEP_COURANT, uupd=uupd_11h), [])
        a_12h = sante(controles=controles(date="2026-11-09T12:00:00", image={"disponible": "45.20261110"}))
        self.assertIn("maj:dispo:image:45.20261110", par_id(calculer(a_12h, DEP_COURANT, uupd=uupd_11h)))
        # la session « Tout mettre à jour » compte comme une passe de uupd
        s = session_ko("resume")
        s.update(debut="2026-11-09T10:30:00", fin="2026-11-09T11:00:00")
        self.assertNotIn("maj:dispo:image:45.20261110", par_id(calculer(a_10h, DEP_COURANT, session=s)))

    def test_flatpak_dispo_perime_apres_uupd(self):
        apps = {"a_mettre_a_jour": ["org.mozilla.Thunderbird", "org.libreoffice.LibreOffice"]}
        uupd_11h = [{"unite": "uupd.service", "debut": "2026-11-09T10:50:00", "fin": "2026-11-09T11:00:00",
                     "succes": True}]
        a_10h = sante(controles=controles(date="2026-11-09T10:00:00", flatpak=apps))
        self.assertEqual(calculer(a_10h, DEP_COURANT, uupd=uupd_11h), [])
        a_12h = sante(controles=controles(date="2026-11-09T12:00:00", flatpak=apps))
        pt = par_id(calculer(a_12h, DEP_COURANT, uupd=uupd_11h))["maj:dispo:flatpak"]
        self.assertEqual((pt["gravite"], pt["mesure"], pt["cran"]), ("info", 2.0, 1.0))
        self.assertIn("org.mozilla.Thunderbird", pt["detail"])
        # sans réussite connue de uupd, la liste vaut
        self.assertIn("maj:dispo:flatpak", par_id(calculer(a_10h, DEP_COURANT)))
        # un uupd en échec ne rend pas la liste caduque
        ko = [dict(uupd_11h[0], succes=False)]
        self.assertIn("maj:dispo:flatpak", par_id(calculer(a_10h, DEP_COURANT, uupd=ko)))

    def test_menage_points(self):
        c = controles(runtimes={"inutilises": ["org.kde.Platform", "org.gnome.Platform"],
                                "gl_obsoletes": ["runtime/org.freedesktop.Platform.GL.nvidia-580-95-05/x86_64/1.4"]},
                      telechargements=[{"nom": "jeu.iso.part", "octets": 60 * 1024 ** 2, "present": 0}],
                      caches={"miniatures": 0, "corbeille": 0, "journal": round(1.5 * GIO)})
        p = par_id(calculer(sante(controles=c), DEP_COURANT))
        r = p["menage:runtimes"]
        self.assertEqual((r["gravite"], r["mesure"], r["cran"]), ("attention", 3.0, 1.0))
        self.assertIn("flatpak uninstall --unused", r["detail"])
        self.assertIn("flatpak pin --remove", r["detail"])
        t = p["menage:telechargements-incomplets"]
        self.assertEqual((t["gravite"], t["mesure"]), ("attention", 1.0))
        self.assertIn("jeu.iso.part", t["detail"])
        j = p["menage:journal"]
        self.assertEqual((j["gravite"], j["mesure"], j["cran"]), ("attention", 1.5, 1.0))
        self.assertIn("sudo journalctl --vacuum-size=500M", j["detail"])
        self.assertIn("1,5 Go", j["titre"])
        self.assertEqual(P.compteurs(list(p.values())), {"majs": 0, "sante": 0, "stockage": 3})

    def test_journal_sous_un_gio_rien(self):
        c = controles(caches={"miniatures": 0, "corbeille": 0, "journal": GIO - 1})
        self.assertNotIn("menage:journal", par_id(calculer(sante(controles=c), DEP_COURANT)))
        c = controles(caches={"miniatures": 0, "corbeille": 0, "journal": None})
        self.assertEqual(calculer(sante(controles=c), DEP_COURANT), [])

    def test_donnees_non_monte_echec_externe_debranche_rien(self):
        p = par_id(calculer(sante(non_montes=["/var/mnt/DONNEES"]), DEP_COURANT))
        pt = p["stockage:non-monte:/var/mnt/DONNEES"]
        self.assertEqual((pt["gravite"], pt["mesure"], pt["cran"]), ("echec", 0.0, 1.0))
        self.assertIn("Données", pt["titre"])
        self.assertEqual(P.couleur(list(p.values()), False), "rouge")
        # Externe débranché : absent des volumes, rien d'attendu, aucune alerte
        s = sante(non_montes=[], volumes=[vol("/var/mnt/DONNEES", "Données", 50.0)])
        self.assertEqual(calculer(s, DEP_COURANT), [])

    def test_non_monte_nomme_par_la_configuration(self):
        with configuration('[[volumes]]\nnom = "Atelier"\nchemin = "/var/mnt/ATELIER"\nattendu = true\n'):
            p = par_id(calculer(sante(non_montes=["/var/mnt/ATELIER"]), DEP_COURANT))
        self.assertEqual(p["stockage:non-monte:/var/mnt/ATELIER"]["titre"], "Atelier n'est pas monté")

    def test_erreurs_es(self):
        p = par_id(calculer(sante(erreurs_disque={"nombre": 3, "exemples": ["I/O error, dev sda"]}), DEP_COURANT))
        pt = p["stockage:erreurs-es"]
        self.assertEqual((pt["gravite"], pt["mesure"], pt["cran"]), ("attention", 3.0, 1.0))
        self.assertIn("I/O error, dev sda", pt["detail"])
        pt = par_id(calculer(sante(erreurs_disque={"nombre": 6, "exemples": []}), DEP_COURANT))["stockage:erreurs-es"]
        self.assertEqual(pt["gravite"], "echec")
        self.assertEqual(calculer(sante(erreurs_disque={"nombre": 0, "exemples": []}), DEP_COURANT), [])

    def test_deploiements_trop(self):
        dep = dict(DEP_COURANT, nombre=3, epingles=[{"position": 2, "version": "45.20261020"}])
        pt = par_id(calculer(sante(), dep))["deploiements:trop"]
        self.assertEqual((pt["gravite"], pt["mesure"], pt["cran"]), ("attention", 3.0, 1.0))
        # Ruling V42 : déploiements épinglés nommés, commande à copier (jamais exécutée : pas d'action)
        self.assertIn("45.20261020", pt["detail"])
        self.assertIn("sudo ostree admin pin --unpin 2", pt["detail"])
        self.assertNotIn("cleanup -p", pt["detail"])
        self.assertIsNone(pt["action"])
        sans_detail = par_id(calculer(sante(), dict(DEP_COURANT, nombre=3)))["deploiements:trop"]
        self.assertIn("sudo ostree admin pin --unpin <n>", sans_detail["detail"])
        self.assertEqual(calculer(sante(), DEP_COURANT), [])
        self.assertEqual(calculer(sante(), {"courant": None, "en_attente": None, "precedent": None}), [])

    def test_deploiement_en_attente_n_est_pas_en_trop(self):
        # mise à jour installée, redémarrage attendu : 3 déploiements, c'est l'état normal
        dep = dict(DEP_COURANT, en_attente={"version": "45.20261110"}, nombre=3)
        self.assertEqual([p["id"] for p in calculer(sante(), dep)], ["redemarrage:45.20261110"])

    def test_boot_presque_plein(self):
        boot = {"nom": "Démarrage", "chemin": "/boot", "libre_go": 0.07, "total_go": 0.95, "pourcent_utilise": 92.6}
        pt = par_id(calculer(sante(controles=controles(boot=boot)), DEP_COURANT))["volume:/boot"]
        self.assertEqual((pt["gravite"], pt["mesure"], pt["cran"]), ("attention", 92.6, 3.0))
        self.assertIn("Démarrage", pt["titre"])
        self.assertIn("72 Mo", pt["titre"])            # pas « 0 Go »
        self.assertNotIn("0 Go", pt["titre"])

    def test_releve_controles(self):
        self.assertFalse(P.releve("maj:dispo:flatpak", {"controles": None}))
        self.assertTrue(P.releve("maj:dispo:flatpak", {"controles": controles()}))
        self.assertFalse(P.releve("maj:dispo:flatpak", {"controles": controles(flatpak=None)}))
        self.assertTrue(P.releve("maj:dispo:image:45.2", {"controles": controles()}))
        self.assertFalse(P.releve("menage:runtimes", {"controles": controles(runtimes=None)}))
        self.assertTrue(P.releve("menage:runtimes", {"controles": controles()}))
        self.assertFalse(P.releve("menage:journal", {"controles": controles(caches={"journal": None})}))
        self.assertFalse(P.releve("menage:telechargements-incomplets", {}))
        self.assertFalse(P.releve("volume:/boot", {"controles": controles(boot=None)}))
        self.assertTrue(P.releve("volume:/boot", {"controles": controles()}))
        self.assertFalse(P.releve("volume:/boot", {"controles": None, "volumes": [vol("/boot", "x", 1)]}))
        self.assertFalse(P.releve("stockage:erreurs-es", {"erreurs_disque": None}))
        self.assertTrue(P.releve("stockage:erreurs-es", {"erreurs_disque": {"nombre": 0, "exemples": []}}))
        self.assertFalse(P.releve("stockage:non-monte:/var/mnt/DONNEES", {"non_montes": None}))
        self.assertTrue(P.releve("stockage:non-monte:/var/mnt/DONNEES", {"non_montes": []}))

    def test_sourdine_gardee_hors_ligne(self):
        sourdines = {"menage:runtimes": 3.0}
        P.appliquer_sourdines([], sourdines, sante={"controles": controles(runtimes=None)})
        self.assertEqual(sourdines, {"menage:runtimes": 3.0})


class Rubriques(unittest.TestCase):
    def test_rubrique(self):
        self.assertEqual(P.rubrique("maj:echec:uupd:2026-11-09T04:00:00"), "majs")
        self.assertEqual(P.rubrique("redemarrage:45.2"), "majs")
        self.assertEqual(P.rubrique("session:echec:x"), "majs")
        self.assertEqual(P.rubrique("volume:/var/mnt/EXTERNE"), "stockage")
        self.assertEqual(P.rubrique("ssd:X:usure"), "sante")

    def test_rubrique_stockage(self):
        for id_ in ("volume:/var/mnt/EXTERNE", "volume:/boot", "menage:runtimes", "menage:journal",
                    "stockage:erreurs-es", "stockage:non-monte:/var/mnt/DONNEES"):
            self.assertEqual(P.rubrique(id_), "stockage", id_)
        self.assertEqual(P.rubrique("deploiements:trop"), "sante")

    def test_domaine_de_chaque_point(self):
        """Task 19 : l'onglet de la page Santé où se range chaque point (son « domaine »), pour les points que
        points.points produit vraiment, et un défaut « systeme »."""
        table = {
            "ssd:NVMe Exemple Z1 with Radiateur 2TB:usure": "disques",
            "ssd:X:critique:erreurs-media+0x04": "disques",
            "ssd:X:reserve": "disques", "ssd:X:chaleur": "disques",
            "stockage:erreurs-es": "disques",
            "stockage:non-monte:/var/mnt/DONNEES": "disques",
            "volume:/var": "disques", "volume:/var/mnt/EXTERNE": "disques",
            "volume:/boot": "controles",
            "deploiements:trop": "controles",
            "menage:runtimes": "controles", "menage:telechargements-incomplets": "controles",
            "menage:journal": "controles",
            "maj:dispo:image:45.20261110": "controles", "maj:dispo:flatpak": "controles",
            "ollama:inactif": "gpu",
            "service:maj-apps.service": "systeme",
            "redemarrage:45.20261109": "systeme",
            "session:echec:2026-11-09T09:30:00": "systeme",
            "maj:echec:uupd:2026-11-09T04:00:00": "systeme",
            "journal:erreurs": "journal",
            "plantages": "journal",
            "inconnu:x": "systeme",
        }
        for id_, domaine in table.items():
            self.assertEqual(P.domaine(id_), domaine, id_)

    def test_tout_point_produit_a_un_des_cinq_domaines(self):
        sante = {"ssd": [{"modele": "M", "sante": {"usure": 90, "reserve": 5, "seuil_reserve": 10, "temperature": 75,
                                                   "erreurs_media": 1, "avertissements": []}}],
                 "non_montes": ["/var/mnt/DONNEES"], "erreurs_disque": {"nombre": 2, "exemples": []},
                 "volumes": [{"nom": "Système", "chemin": "/var", "libre_go": 1, "total_go": 70}],
                 "services_en_echec": ["x.service"], "erreurs_journal": [{"message": "m", "source": "s", "nombre": 1}],
                 "plantages": [{"exe": "e", "signal": 6, "date": "2026-11-09T10:00:00"}],
                 "controles": {"date": "2026-11-09T10:00:00", "image": None, "flatpak": None,
                               "runtimes": {"inutilises": ["r"], "gl_obsoletes": []}, "telechargements": [],
                               "caches": {"miniatures": 0, "corbeille": 0, "journal": 2 * 1024 ** 3},
                               "boot": {"nom": "Démarrage", "chemin": "/boot", "libre_go": 0.01, "total_go": 1,
                                        "pourcent_utilise": 99}}}
        pts = P.points(sante, {"en_attente": {"version": "45.2"}, "nombre": 4}, maintenant=datetime(2026, 11, 9, 12))
        self.assertGreater(len(pts), 10)
        for p in pts:
            self.assertIn(P.domaine(p["id"]), {"disques", "gpu", "systeme", "controles", "journal"}, p["id"])

    def test_compteurs_ignorent_info_et_sourdine(self):
        pts = [P._point("volume:/var/mnt/EXTERNE", "attention", "t", "d"),
               P._point("maj:echec:uupd:x", "echec", "t", "d"),
               P._point("journal:erreurs", "info", "t", "d"),
               dict(P._point("service:x", "attention", "t", "d"), en_sourdine=True)]
        self.assertEqual(P.compteurs(pts), {"majs": 1, "sante": 0, "stockage": 1})

    def test_compteurs_comptent_les_mises_a_jour_disponibles(self):
        pts = [P._point("maj:dispo:flatpak", "info", "t", "d")]
        self.assertEqual(P.compteurs(pts)["majs"], 1)


class Sourdine(unittest.TestCase):
    def pt(self, m):
        return calculer(sante(volumes=[vol("/var/mnt/EXTERNE", "Externe", m)]))

    def test_sourdine_masque_puis_revient(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sourdines.json"
            P.mettre_en_sourdine("volume:/var/mnt/EXTERNE", self.pt(91.0), f)
            self.assertEqual(commun.lire_json(f, None), {"volume:/var/mnt/EXTERNE": 91.0})
            for m, attendu in ((91.0, True), (93.0, True)):
                s = commun.lire_json(f, {})
                self.assertEqual(P.appliquer_sourdines(self.pt(m), s, f)[0]["en_sourdine"], attendu)
            s = commun.lire_json(f, {})
            self.assertFalse(P.appliquer_sourdines(self.pt(94.0), s, f)[0]["en_sourdine"])
            self.assertEqual(commun.lire_json(f, None), {})

    def test_defaut_et_lever(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(commun, "ETAT", Path(d)):
                P.mettre_en_sourdine("volume:/var/mnt/EXTERNE", self.pt(91.0))
                self.assertIn("volume:/var/mnt/EXTERNE", commun.lire_json(Path(d) / "sourdines.json", {}))
                self.assertTrue(P.points_avec_sourdines(self.pt(92.0))[0]["en_sourdine"])
                P.lever_sourdine("volume:/var/mnt/EXTERNE")
                self.assertEqual(commun.lire_json(Path(d) / "sourdines.json", None), {})
                self.assertFalse(P.points_avec_sourdines(self.pt(92.0))[0]["en_sourdine"])


class Disparition(unittest.TestCase):
    def test_sourdine_supprimee_si_point_disparu(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sourdines.json"
            commun.ecrire_json(f, {"maj:echec": 0.0})
            P.appliquer_sourdines(calculer(sante()), commun.lire_json(f, {}), f)
            self.assertEqual(commun.lire_json(f, None), {})

    def test_echec_revient_apres_disparition(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sourdines.json"
            echec = lambda: calculer(sante(), session=session_ko("uupd"))
            P.mettre_en_sourdine("maj:echec:uupd:2026-11-08T23:00:00", echec(), f)
            self.assertTrue(P.appliquer_sourdines(echec(), commun.lire_json(f, {}), f)[0]["en_sourdine"])
            P.appliquer_sourdines(calculer(sante()), commun.lire_json(f, {}), f)
            pts = P.appliquer_sourdines(echec(), commun.lire_json(f, {}), f)
            self.assertFalse(pts[0]["en_sourdine"])


class Collecte(unittest.TestCase):
    """Une sourdine n'est retirée que si la source de son point a vraiment été relevée."""
    SOURDINES = {"volume:/var/mnt/EXTERNE": 90.5, "service:a.service": 0.0,
                 "ssd:X:usure": 80.0, "ollama:inactif": 3.0, "maj:echec:uupd:2026-11-08T04:00:00": 0.0}

    def appliquer(self, s):
        sourdines = dict(self.SOURDINES)
        P.appliquer_sourdines(calculer(s), sourdines, sante=s)
        return sourdines

    def test_sources_absentes_gardent_leurs_sourdines(self):
        s = {"ssd": [{"modele": "X", "bus": "nvme", "sante": None}], "volumes": None,
             "services_en_echec": None, "ollama": None, "erreurs_journal": None, "plantages": None}
        self.assertEqual(set(self.appliquer(s)), set(self.SOURDINES) - {"maj:echec:uupd:2026-11-08T04:00:00"})
        self.assertEqual(set(self.appliquer(None)), set(self.SOURDINES) - {"maj:echec:uupd:2026-11-08T04:00:00"})

    def test_volume_demonte_garde_sa_sourdine(self):
        self.assertIn("volume:/var/mnt/EXTERNE", self.appliquer(sante(volumes=[vol("/var", "Système", 50.0)])))

    def test_sources_relevees_sans_le_point_retirent_la_sourdine(self):
        h = {"usure": 1, "reserve": 100, "seuil_reserve": 10, "temperature": 40, "erreurs_media": 0,
             "avertissements": []}
        s = sante(ssd=[{"modele": "X", "bus": "nvme", "sante": h}],
                  volumes=[vol("/var/mnt/EXTERNE", "Externe", 50.0)],
                  ollama={"actif": False, "depuis": None, "modeles_charges": []})
        self.assertEqual(self.appliquer(s), {})


class Couleur(unittest.TestCase):
    def test_info_ne_colore_pas(self):
        pts = calculer(sante(erreurs_journal=[{"message": "x", "source": "s", "nombre": 1}]))
        self.assertEqual([p["id"] for p in pts], ["journal:erreurs"])
        self.assertEqual(P.couleur(pts, False), "vert")

    def test_rouge_prime(self):
        pts = calculer(sante(services_en_echec=["a.service"]), session=session_ko("uupd"))
        self.assertEqual(P.couleur(pts, False), "rouge")
        self.assertEqual(P.couleur(calculer(sante(services_en_echec=["a.service"])), False), "orange")

    def test_en_cours_prime(self):
        pts = calculer(sante(), session=session_ko("uupd"))
        self.assertEqual(P.couleur(pts, True), "en_cours")

    def test_sourdine_ne_colore_pas(self):
        pts = calculer(sante(services_en_echec=["a.service"]))
        pts = P.appliquer_sourdines(pts, {"service:a.service": 0.0})
        self.assertEqual(P.couleur(pts, False), "vert")


if __name__ == "__main__":
    unittest.main()


class MisesAJourReportees(unittest.TestCase):
    """Ce que maj-apps a mis de côté (appli ouverte, AppImage qui tourne) reste visible comme « disponible »."""

    DISTROBOX = {"module": "distrobox", "etat": "reporté", "message": "Distrobox : 1 conteneur(s) reporté(s)",
                 "details": "messagerie : reporté, Messagerie est ouvert (mis à jour à la prochaine passe "
                            "où il sera fermé)\nnon mis à jour : boite-stable (gardée stable)"}

    def maj(self, *resultats):
        return {"date": "2026-11-10T12:33:26", "resultats": list(resultats)}

    def test_un_point_disponible_par_module_reporte(self):
        res = par_id(calculer(sante(), maj=self.maj(self.DISTROBOX, {"module": "uv", "etat": "à jour"})))
        p = res["maj:dispo:majapps:distrobox"]
        self.assertEqual(p["gravite"], "info")
        self.assertEqual(p["titre"], "Distrobox : 1 conteneur(s) reporté(s)")
        self.assertIn("messagerie : reporté, Messagerie est ouvert", p["detail"])
        self.assertNotIn("non mis à jour", p["detail"])
        self.assertIn("sera fermé). Elle se fera", p["detail"])
        self.assertIn("Tout mettre à jour", p["detail"])
        self.assertEqual([i for i in res if i.startswith("maj:")], ["maj:dispo:majapps:distrobox"])

    def test_rien_quand_tout_est_a_jour(self):
        res = par_id(calculer(sante(), maj=self.maj({"module": "distrobox", "etat": "à jour"})))
        self.assertFalse([i for i in res if i.startswith("maj:dispo:majapps:")])

    def test_compte_dans_les_mises_a_jour_sans_changer_la_couleur(self):
        pts = calculer(sante(), maj=self.maj(self.DISTROBOX))
        self.assertEqual(P.compteurs(pts)["majs"], 1)
        self.assertEqual(P.rubrique("maj:dispo:majapps:distrobox"), "majs")
        self.assertEqual(P.couleur(pts, False), "vert")
