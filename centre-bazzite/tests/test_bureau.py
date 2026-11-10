"""bureau.BureauDBus, le seul module qui parle à D-Bus, testé avec un faux module `dbus` : aucun bus réel n'est joint
(tests/__init__.py pointe les deux adresses D-Bus vers un chemin inexistant). Filet (P2) : comme test_modejeu,
subprocess.run est remplacé par un enregistreur le temps du module, et aucune commande réelle n'est permise."""
import os
import subprocess
import types
import unittest
from pathlib import Path

import tests  # noqa: F401  (le filet D-Bus de tests/__init__.py, même lancé seul)
from centre_bazzite import bureau, commun, modejeu

VRAI_RUN = subprocess.run       # gardé avant le filet : seul test_aucun_dbus_a_l_import s'en sert (python3 -I, sans effet)
COMMANDES_REELLES = []
_ORIGINAL = []


def setUpModule():
    _ORIGINAL.append(commun.subprocess.run)

    def filet(cmd, *args, **kwargs):
        COMMANDES_REELLES.append([str(c) for c in cmd])
        raise OSError("filet des tests : aucune commande réelle")
    commun.subprocess.run = filet


def tearDownModule():
    commun.subprocess.run = _ORIGINAL.pop()
    if COMMANDES_REELLES:
        raise AssertionError(f"commandes réelles tentées pendant les tests : {COMMANDES_REELLES}")


NOTIFICATIONS = "org.freedesktop.Notifications"
UPOWER = "org.freedesktop.UPower.PowerProfiles"
HADESS = "net.hadess.PowerProfiles"
SERVICE_INCONNU = "org.freedesktop.DBus.Error.ServiceUnknown"
SANS_PROPRIETAIRE = "org.freedesktop.DBus.Error.NameHasNoOwner"
REFUS = "org.freedesktop.DBus.Error.AccessDenied"


class FauxDBusException(Exception):
    def __init__(self, message="", nom="org.freedesktop.DBus.Error.Failed"):
        super().__init__(message)
        self.nom = nom

    def get_dbus_name(self):
        return self.nom

    def get_dbus_message(self):
        return self.args[0] if self.args else ""


class FauxUInt32(int):
    pass


class FauxDictionary(dict):
    def __init__(self, contenu=(), signature=None):
        super().__init__(contenu)
        self.signature = signature


class FauxDBus:
    """Faux dbus-python. `reponses[(nom, methode)]` : la valeur rendue, ou l'exception levée ; `(nom, "get_object")`
    imite un nom absent du bus (dbus-python le voit dès get_object). `appels` : (bus, nom, objet, interface, méthode,
    arguments). `bus_absent` : le genre de bus qu'on ne peut pas ouvrir."""

    UInt32 = FauxUInt32
    Dictionary = FauxDictionary
    exceptions = types.SimpleNamespace(DBusException=FauxDBusException)

    def __init__(self):
        self.connexions = []
        self.objets = []
        self.appels = []
        self.reponses = {}
        self.bus_absent = None

    def SessionBus(self, private=False):
        return self._ouvrir("session", private)

    def SystemBus(self, private=False):
        return self._ouvrir("systeme", private)

    def _ouvrir(self, genre, private):
        if genre == self.bus_absent:
            raise FauxDBusException("Failed to connect to socket /nonexistent", "org.freedesktop.DBus.Error.FileNotFound")
        connexion = FauxConnexion(self, genre, private)
        self.connexions.append(connexion)
        return connexion

    def Interface(self, objet, dbus_interface):
        return FauxInterface(objet, dbus_interface)

    def methodes(self):
        return [(a[1], a[4]) for a in self.appels]


class FauxConnexion:
    def __init__(self, module, genre, private):
        self.module, self.genre, self.private = module, genre, private
        self.fermetures = 0

    def get_object(self, nom, objet, introspect=True):
        self.module.objets.append((self.genre, nom, objet, introspect))
        reponse = self.module.reponses.get((nom, "get_object"))
        if isinstance(reponse, Exception):
            raise reponse
        return types.SimpleNamespace(connexion=self, nom=nom, chemin=objet)

    def close(self):
        self.fermetures += 1


class FauxInterface:
    def __init__(self, objet, interface):
        self._objet, self._interface = objet, interface

    def __getattr__(self, methode):
        def appel(*arguments):
            o = self._objet
            o.connexion.module.appels.append((o.connexion.genre, o.nom, o.chemin, self._interface, methode, arguments))
            reponse = o.connexion.module.reponses.get((o.nom, methode), FauxUInt32(1))
            if isinstance(reponse, Exception):
                raise reponse
            return reponse
        return appel


class Base(unittest.TestCase):
    def setUp(self):
        self.dbus = FauxDBus()
        self.bureau = bureau.BureauDBus(dbus=self.dbus)


class Connexions(Base):
    def test_connexions_privees(self):
        self.assertEqual(self.dbus.connexions, [])           # rien n'est ouvert à la création
        self.bureau.inhiber_notifications("raison")
        self.bureau.tenir_profil("performance", "raison")
        self.bureau.lever_notifications(1)
        self.bureau.relacher_profil(1)
        self.assertEqual([(c.genre, c.private) for c in self.dbus.connexions], [("session", True), ("systeme", True)])

    def test_fermer_ferme_et_se_rouvre(self):
        self.bureau.inhiber_notifications("raison")
        self.bureau.tenir_profil("performance", "raison")
        self.bureau.fermer()
        self.assertEqual([c.fermetures for c in self.dbus.connexions], [1, 1])
        self.bureau.fermer()                                 # idempotent
        self.assertEqual([c.fermetures for c in self.dbus.connexions], [1, 1])
        self.bureau.inhiber_notifications("raison")
        self.assertEqual(len(self.dbus.connexions), 3)
        self.assertEqual((self.dbus.connexions[2].genre, self.dbus.connexions[2].private), ("session", True))

    def test_fermer_sans_connexion(self):
        self.bureau.fermer()
        self.assertEqual(self.dbus.connexions, [])

    def test_bus_absent_leve_bureau_indisponible(self):
        self.dbus.bus_absent = "session"
        with self.assertRaises(modejeu.BureauIndisponible) as e:
            self.bureau.inhiber_notifications("raison")
        self.assertIn("Failed to connect", str(e.exception))


class NePasDeranger(Base):
    def test_inhiber_appelle_inhibit_avec_l_appli(self):
        self.dbus.reponses[(NOTIFICATIONS, "Inhibit")] = FauxUInt32(42)
        cookie = self.bureau.inhiber_notifications("Health Hub : mode jeu (Aventure)")
        self.assertEqual(cookie, 42)
        self.assertIs(type(cookie), int)
        bus, nom, objet, interface, methode, arguments = self.dbus.appels[0]
        self.assertEqual((bus, nom, objet, interface, methode),
                         ("session", NOTIFICATIONS, "/org/freedesktop/Notifications", NOTIFICATIONS, "Inhibit"))
        self.assertEqual(arguments, ("centre-bazzite", "Health Hub : mode jeu (Aventure)", {}))
        self.assertEqual(arguments[2].signature, "sv")
        self.bureau.lever_notifications(42)
        self.assertEqual(self.dbus.appels[1][4:], ("UnInhibit", (42,)))
        self.assertIs(type(self.dbus.appels[1][5][0]), FauxUInt32)      # signature « u » sans introspection

    def test_erreur_dbus_devient_bureau_indisponible(self):
        self.dbus.reponses[(NOTIFICATIONS, "Inhibit")] = FauxDBusException("Pas de serveur de notifications", REFUS)
        with self.assertRaises(modejeu.BureauIndisponible) as e:
            self.bureau.inhiber_notifications("raison")
        self.assertIn("Pas de serveur de notifications", str(e.exception))
        self.assertIs(bureau.BureauIndisponible, modejeu.BureauIndisponible)


class Profil(Base):
    def test_profil_upower_d_abord(self):
        self.dbus.reponses[(UPOWER, "HoldProfile")] = FauxUInt32(5)
        self.assertEqual(self.bureau.tenir_profil("performance", "raison"), 5)
        self.bureau.relacher_profil(5)
        self.assertEqual(self.dbus.methodes(), [(UPOWER, "HoldProfile"), (UPOWER, "ReleaseProfile")])
        bus, nom, objet, interface, methode, arguments = self.dbus.appels[0]
        self.assertEqual((bus, objet, interface, arguments),
                         ("systeme", "/org/freedesktop/UPower/PowerProfiles", UPOWER,
                          ("performance", "raison", "centre-bazzite")))

    def test_profil_upower_puis_hadess(self):
        self.dbus.reponses[(UPOWER, "get_object")] = FauxDBusException("introuvable", SERVICE_INCONNU)
        self.dbus.reponses[(HADESS, "HoldProfile")] = FauxUInt32(7)
        self.assertEqual(self.bureau.tenir_profil("performance", "raison"), 7)
        self.bureau.relacher_profil(7)
        self.assertEqual(self.dbus.methodes(), [(HADESS, "HoldProfile"), (HADESS, "ReleaseProfile")])
        self.assertEqual(self.dbus.appels[0][2:4], ("/net/hadess/PowerProfiles", HADESS))
        self.assertEqual(self.dbus.appels[1][5], (7,))
        self.assertIs(type(self.dbus.appels[1][5][0]), FauxUInt32)

    def test_profil_pas_de_repli_sur_une_autre_erreur(self):
        """P1 : un refus (polkit) ou un délai dépassé ne sont pas « nom absent » : pas de second maintien ailleurs."""
        self.dbus.reponses[(UPOWER, "HoldProfile")] = FauxDBusException("refusé", REFUS)
        with self.assertRaises(modejeu.BureauIndisponible):
            self.bureau.tenir_profil("performance", "raison")
        self.assertEqual(self.dbus.methodes(), [(UPOWER, "HoldProfile")])
        self.assertNotIn(HADESS, [o[1] for o in self.dbus.objets])

    def test_profil_indisponible_leve_bureau_indisponible(self):
        self.dbus.reponses[(UPOWER, "get_object")] = FauxDBusException("introuvable", SERVICE_INCONNU)
        self.dbus.reponses[(HADESS, "get_object")] = FauxDBusException("sans propriétaire", SANS_PROPRIETAIRE)
        with self.assertRaises(modejeu.BureauIndisponible):
            self.bureau.tenir_profil("performance", "raison")
        with self.assertRaises(modejeu.BureauIndisponible):
            self.bureau.relacher_profil(3)                   # aucun nom n'a répondu : rien à relâcher
        self.assertEqual(self.dbus.appels, [])


class Isolation(unittest.TestCase):
    def test_aucun_dbus_a_l_import(self):
        racine = Path(__file__).resolve().parent.parent
        code = (f"import sys; sys.path.insert(0, {str(racine)!r}); "
                "import centre_bazzite.cli, centre_bazzite.modejeu, centre_bazzite.bureau; print('dbus' in sys.modules)")
        r = VRAI_RUN(["python3", "-I", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "False"), r.stderr)

    def test_les_tests_ne_joignent_pas_le_vrai_bus(self):
        for variable in ("DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS"):
            self.assertTrue(os.environ.get(variable, "").startswith("unix:path=/nonexistent"), variable)


if __name__ == "__main__":
    unittest.main()
