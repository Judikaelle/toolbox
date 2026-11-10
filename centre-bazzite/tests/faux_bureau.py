"""Faux bureau du mode jeu : il imite le protocole de bureau.BureauDBus (Ne pas déranger, profil d'énergie) sans jamais
joindre D-Bus. FauxSysteme tient les maintiens comme le bus et ses démons : un maintien appartient à la connexion qui
l'a pris, et il disparaît avec elle (`perdre`, ce qui arrive quand le service plante ou ferme ses connexions)."""
from centre_bazzite.modejeu import BureauIndisponible


class FauxSysteme:
    """Les maintiens en cours : `notifications` et `profils` sont des dict {cookie: bureau qui le tient}.
    `temoin(nom)`, s'il est posé, est appelé avant chaque appel d'un bureau (pour vérifier ce qui précède)."""

    def __init__(self):
        self.notifications = {}
        self.profils = {}
        self.temoin = None
        self._dernier = 0

    def cookie(self):
        self._dernier += 1
        return self._dernier

    def perdre(self, bureau):
        """Ce que fait le bus quand une connexion meurt : tous les maintiens de ce bureau sont levés."""
        for maintiens in (self.notifications, self.profils):
            for cookie in [c for c, b in maintiens.items() if b is bureau]:
                del maintiens[cookie]


class FauxBureau:
    """`echecs` : méthodes qui lèvent BureauIndisponible("indisponible") sans rien faire. `sans_reponse` : méthodes
    dont l'effet a lieu mais dont la réponse se perd (délai D-Bus dépassé) : elles lèvent après coup. `appels` garde
    chaque appel, dans l'ordre : (nom, *arguments)."""

    def __init__(self, systeme, echecs=frozenset(), sans_reponse=frozenset()):
        self.systeme = systeme
        self.echecs = frozenset(echecs)
        self.sans_reponse = frozenset(sans_reponse)
        self.appels = []

    def _appel(self, nom, *arguments):
        self.appels.append((nom, *arguments))
        if self.systeme.temoin is not None:
            self.systeme.temoin(nom)
        if nom in self.echecs:
            raise BureauIndisponible("indisponible")

    def _reponse(self, nom, valeur):
        if nom in self.sans_reponse:
            raise BureauIndisponible("indisponible")
        return valeur

    def _tenir(self, maintiens):
        cookie = self.systeme.cookie()
        maintiens[cookie] = self
        return cookie

    def _lever(self, maintiens, cookie):
        if maintiens.get(cookie) is not self:       # comme tuned (check_caller) : seul celui qui tient peut lever
            raise BureauIndisponible("maintien inconnu")
        del maintiens[cookie]

    def inhiber_notifications(self, raison):
        self._appel("inhiber_notifications", raison)
        return self._reponse("inhiber_notifications", self._tenir(self.systeme.notifications))

    def lever_notifications(self, cookie):
        self._appel("lever_notifications", cookie)
        self._lever(self.systeme.notifications, cookie)

    def tenir_profil(self, profil, raison):
        self._appel("tenir_profil", profil, raison)
        return self._reponse("tenir_profil", self._tenir(self.systeme.profils))

    def relacher_profil(self, cookie):
        self._appel("relacher_profil", cookie)
        self._lever(self.systeme.profils, cookie)

    def fermer(self):
        self._appel("fermer")
        self.systeme.perdre(self)

    def maintiens(self):
        """Les noms des appels qui prennent ou lèvent un maintien (tout sauf `fermer`)."""
        return [a[0] for a in self.appels if a[0] != "fermer"]
