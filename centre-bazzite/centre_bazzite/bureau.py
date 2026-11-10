"""Le bureau du mode jeu, par D-Bus : le seul module de Health Hub qui parle à D-Bus (spec §6.6, D6).

- Ne pas déranger : `Inhibit` de org.freedesktop.Notifications, sur le bus de session ;
- profil d'énergie : `HoldProfile` de tuned-ppd, sur le bus système (org.freedesktop.UPower.PowerProfiles, sinon
  net.hadess.PowerProfiles).

Ce ne sont que des maintiens : chacun appartient à la connexion qui l'a pris, et le bus le lève quand elle se ferme ou
que le service meurt. Les connexions sont donc privées (jamais celles, partagées, du processus), ouvertes au premier
appel et rouvertes après `fermer()`. Jamais SetActiveProfile ni tuned-adm, qui ne se restaurent pas après un plantage.

dbus-python n'est importé qu'à la construction d'un BureauDBus réel, jamais à l'import d'un module (les tests passent
un faux module `dbus`). Toute erreur D-Bus devient modejeu.BureauIndisponible."""
from .modejeu import APPLI, BureauIndisponible

__all__ = ["BureauDBus", "BureauIndisponible"]

NOTIFICATIONS = ("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications")
PROFILS = (("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
            "org.freedesktop.UPower.PowerProfiles"),
           ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles"))
# P1 : le repli vers le second nom n'a lieu que si le premier n'existe pas sur ce bus. Un refus (polkit) ou un délai
# dépassé, eux, peuvent cacher un maintien déjà pris : on ne tente pas d'en prendre un second ailleurs.
NOM_ABSENT = ("org.freedesktop.DBus.Error.ServiceUnknown", "org.freedesktop.DBus.Error.NameHasNoOwner",
              "org.freedesktop.DBus.Error.UnknownMethod")


class BureauDBus:
    def __init__(self, *, dbus=None):
        if dbus is None:
            import dbus     # dbus-python, présent sur l'hôte ; seulement ici
        self._dbus = dbus
        self._session = None
        self._systeme = None
        self._profils = None        # (nom, objet, interface) qui a répondu à HoldProfile

    def _indisponible(self, exc):
        message = exc.get_dbus_message() if hasattr(exc, "get_dbus_message") else ""
        return BureauIndisponible(message or str(exc) or type(exc).__name__)

    def _bus(self, genre):
        if genre == "session":
            if self._session is None:
                self._session = self._dbus.SessionBus(private=True)
            return self._session
        if self._systeme is None:
            self._systeme = self._dbus.SystemBus(private=True)
        return self._systeme

    def _appeler(self, genre, cible, methode, *arguments):
        """`methode(*arguments)` sur `cible` (nom, objet, interface). Sans introspection : les types D-Bus sont donnés
        par les arguments eux-mêmes (UInt32, Dictionary). Une DBusException passe telle quelle."""
        nom, objet, interface = cible
        proxy = self._bus(genre).get_object(nom, objet, introspect=False)
        return getattr(self._dbus.Interface(proxy, dbus_interface=interface), methode)(*arguments)

    def _essayer(self, genre, cible, methode, *arguments):
        try:
            return self._appeler(genre, cible, methode, *arguments)
        except self._dbus.exceptions.DBusException as exc:
            raise self._indisponible(exc) from exc

    def inhiber_notifications(self, raison):
        return int(self._essayer("session", NOTIFICATIONS, "Inhibit", APPLI, raison,
                                 self._dbus.Dictionary({}, signature="sv")))

    def lever_notifications(self, cookie):
        self._essayer("session", NOTIFICATIONS, "UnInhibit", self._dbus.UInt32(cookie))

    def tenir_profil(self, profil, raison):
        derniere = None
        for cible in PROFILS:
            try:
                cookie = self._appeler("systeme", cible, "HoldProfile", profil, raison, APPLI)
            except self._dbus.exceptions.DBusException as exc:
                if exc.get_dbus_name() in NOM_ABSENT:
                    derniere = exc
                    continue
                raise self._indisponible(exc) from exc
            self._profils = cible
            return int(cookie)
        raise self._indisponible(derniere)

    def relacher_profil(self, cookie):
        if self._profils is None:
            raise BureauIndisponible("aucun profil n'est tenu")
        self._essayer("systeme", self._profils, "ReleaseProfile", self._dbus.UInt32(cookie))

    def fermer(self):
        """Ferme les connexions ouvertes : le bus lève alors tous leurs maintiens. Idempotent ; le prochain appel
        rouvre une connexion neuve."""
        erreurs = []
        for attribut in ("_session", "_systeme"):
            connexion = getattr(self, attribut)
            setattr(self, attribut, None)
            if connexion is None:
                continue
            try:
                connexion.close()
            except Exception as exc:
                erreurs.append(f"{type(exc).__name__}: {exc}")
        if erreurs:
            raise BureauIndisponible(" ; ".join(erreurs))
