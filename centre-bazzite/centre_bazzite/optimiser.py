"""« Optimiser mes disques » : les options A à D écrites avec les vrais chiffres des disques, et la liste des
Flatpak installés pour tout le système, qu'on peut déplacer vers Home. A et C sont toujours là ; B (un disque externe
à libérer) et D (deux volumes à fusionner) seulement si la configuration locale ([optimiser]) les décrit, comme la
recommandation et l'idée. Ne fait que lire (`flatpak list`) : les commandes de l'option C sont affichées et copiées,
jamais lancées par Health Hub."""
from . import commun, config

LISTE_APPLIS = ["env", "LC_ALL=C", "flatpak", "list", "--system", "--app", "--columns=application,name,origin,size"]
LISTE_TAILLES = ["env", "LC_ALL=C", "flatpak", "list", "--system", "--columns=size"]
DEPOT_FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
CONSEIL_B = "Si ce qu'il contient existe déjà ailleurs, ce disque peut être effacé, réaffecté ou débranché."
POSITIONS = {"debut": "au début", "milieu": "au milieu", "fin": "à la fin"}


def taille_flatpak(texte):
    """Octets d'une taille écrite par flatpak (« 753.1 MB », unités décimales de GLib) ; illisible -> 0."""
    return commun.lire_taille(texte) or 0


def lire_flatpak(texte):
    """Les lignes `application<TAB>nom<TAB>origine<TAB>taille`, de la plus grosse appli à la plus petite."""
    res = []
    for ligne in str(texte).splitlines():
        champs = ligne.split("\t")
        if len(champs) >= 4 and champs[0].strip():
            octets = taille_flatpak(champs[3])
            res.append({"id": champs[0].strip(), "nom": champs[1].strip(), "origine": champs[2].strip(),
                        "octets": octets, "taille": commun.taille(octets)})
    res.sort(key=lambda a: -a["octets"])
    return res


def _volume(disques, nom):
    return next((v for d in disques for v in d["volumes"] if v["nom"] == nom), None)


def _go(valeur):
    """Go libres ou totaux : une décimale (virgule) seulement si elle compte, « 11 » mais « 9,6 »."""
    r = round(valeur, 1)
    return str(int(r)) if r == int(r) else str(r).replace(".", ",")


def _option_a(disques):
    n = sum(len(d["volumes"]) for d in disques)
    return {"id": "A", "titre": "Garder les volumes, mais les présenter par disque physique", "etat": "fait",
            "badge": "En place",
            "texte": f"C'est ce que tu vois ici : {len(disques)} disques physiques, {n} volumes. Sans risque.",
            "commandes": None, "applis": []}


def _option_b(disques, liberer):
    """`liberer` : {"volume", "phrase", "conseil"} de la configuration ; la phrase précède les chiffres."""
    nom = liberer["volume"]
    v = _volume(disques, nom)
    if v:
        texte = (f"{liberer['phrase'] + ' ' if liberer['phrase'] else ''}{nom} a {_go(v['libre_go'])} Go libres sur "
                 f"{_go(v['total_go'])} Go. {liberer['conseil'] or CONSEIL_B} Vérifie-le d'abord : "
                 "Health Hub n'efface rien.")
    else:
        texte = f"{nom} n'est pas branché : branche-le pour voir ses chiffres."
    return {"id": "B", "titre": "Libérer le SSD externe", "etat": "a_decider", "badge": "À décider",
            "texte": texte, "commandes": None, "applis": []}


def _commandes(a_deplacer):
    if not a_deplacer:
        return None
    lignes = [f"flatpak remote-add --user --if-not-exists flathub {DEPOT_FLATHUB}"]
    for a in a_deplacer:
        lignes += [f"flatpak install --user -y flathub {a['id']}", f"flatpak uninstall --system -y {a['id']}"]
    lignes.append("flatpak uninstall --system --unused -y")
    return "\n".join(lignes)


def _option_c(disques, applis, flatpak_systeme_octets):
    """`applis` vaut None si `flatpak list` a échoué : rien n'est affirmé (ni « Rien à déplacer » ni « 0 Mo »)."""
    systeme, home = _volume(disques, "Système"), _volume(disques, "Home")
    goulot = (f"Système n'a que {_go(systeme['libre_go']) if systeme else '?'} Go libres sur "
              f"{_go(systeme['total_go']) if systeme else '?'} Go : c'est le vrai goulot.")
    if applis is None:
        return {"id": "C", "titre": "Soulager la partition Système", "etat": "impossible",
                "badge": "Vérification impossible",
                "texte": (f"{goulot} La liste des Flatpak installés pour tout le système n'a pas pu être lue : "
                          "nouvel essai à la prochaine ouverture de cette page."),
                "commandes": None, "applis": []}
    a_deplacer = [a for a in applis if a["origine"] == "flathub"]
    autres = [a for a in applis if a["origine"] != "flathub"]
    if not applis:
        etat, badge = "fait", "Rien à déplacer"
    else:
        etat = "possible"
        badge = (f"Possible : {commun.taille(sum(a['octets'] for a in a_deplacer))} à déplacer" if a_deplacer
                 else "À déplacer à la main")
    occupe = flatpak_systeme_octets or sum(a["octets"] for a in applis)
    texte = (f"{goulot} Les applis Flatpak installées "
             f"pour tout le système occupent environ {commun.taille(occupe)} dans /var. Les réinstaller pour ton seul "
             f"utilisateur les place dans Home ({_go(home['libre_go']) if home else '?'} Go libres), appli par appli, "
             "sans repartitionner. Tes réglages (~/.var/app) ne bougent pas.")
    if autres:
        texte += (" D'une autre origine, à déplacer à la main : "
                  + ", ".join(f"{a['nom']} ({a['origine']})" for a in autres) + ".")
    return {"id": "C", "titre": "Soulager la partition Système", "etat": etat, "badge": badge, "texte": texte,
            "commandes": _commandes(a_deplacer),
            "applis": [{"id": a["id"], "nom": a["nom"], "octets": a["octets"], "taille": a["taille"]}
                       for a in applis]}


def _option_d(disques, fusionner):
    """`fusionner` : les noms des deux volumes, tirés de la configuration."""
    a, b = fusionner
    place = lambda nom: POSITIONS.get((_volume(disques, nom) or {}).get("position"), "quelque part sur le disque")
    return {"id": "D", "titre": f"Fusionner {a} et {b} en un seul volume", "etat": "plus_tard",
            "badge": "Ton idée — plus tard",
            "texte": (f"Impossible sur place : {a} est {place(a)} du disque, {b} {place(b)}, et ext4 ne "
                      "s'agrandit pas vers l'avant. Il faut sauvegarder, démarrer sur une clé USB, puis déplacer et "
                      "redimensionner avec GParted. C'est long et risqué. Health Hub ne repartitionne jamais : il "
                      "préparera un pas-à-pas quand tu le décideras."),
            "commandes": None, "applis": []}


def options(disques, applis, flatpak_systeme_octets, reglages=None):
    """Les options, avec les chiffres des `disques` (voir stockage.disques) et les `applis` (lire_flatpak ; None si la
    liste n'a pas pu être lue). `reglages` : config.optimiser() (lu à l'appel par défaut) ; B et D n'y sont que s'ils
    y sont décrits."""
    reglages = config.optimiser() if reglages is None else reglages
    res = [_option_a(disques)]
    if reglages["liberer"]:
        res.append(_option_b(disques, reglages["liberer"]))
    res.append(_option_c(disques, applis, flatpak_systeme_octets))
    if reglages["fusionner"]:
        res.append(_option_d(disques, reglages["fusionner"]))
    return res


def recommandation_par_defaut(ids):
    """La recommandation quand la configuration n'en donne pas, d'après les options présentes (`ids`)."""
    parties = ["A tout de suite, puis C"]
    if "B" in ids:
        parties.append("B si ce qu'il contient existe déjà ailleurs")
    if "D" in ids:
        parties.append("D seulement si tu y tiens vraiment")
    return "Recommandation : " + " ; ".join(parties) + "."


def construire(disques, *, run=commun.run, reglages=None):
    """{"options", "recommandation", "idee"} ; les deux seules commandes sont des `flatpak list` en lecture.
    Si flatpak ne répond pas, l'option C le dit (« Vérification impossible ») au lieu de « Rien à déplacer »."""
    reglages = config.optimiser() if reglages is None else reglages
    code, sortie = run(LISTE_APPLIS, timeout=60)
    applis = lire_flatpak(sortie) if code == 0 else None
    code, sortie = run(LISTE_TAILLES, timeout=60)
    total = sum(taille_flatpak(ligne) for ligne in sortie.splitlines()) if code == 0 else 0
    liste = options(disques, applis, total, reglages)
    return {"options": liste,
            "recommandation": reglages["recommandation"] or recommandation_par_defaut([o["id"] for o in liste]),
            "idee": reglages["idee"]}
