"""Ménage de la page Stockage : les recommandations (ce qui peut partir, combien ça libère) et leur exécution sûre.

C'est la seule partie de Health Hub qui supprime. Rien ne part sans un clic de confirmation, et `executer` n'agit que
sur les éléments de la recommandation montrée, chacun revérifié au moment d'agir : il existe, n'est pas un lien
symbolique, son realpath est dans sa racine permise, et son critère est toujours vrai. Rien ne se fait pendant un jeu
ni pendant une mise à jour. Les caches sont supprimés définitivement, les fichiers personnels vont à la corbeille, les
sauvegardes de jeux probables et les préfixes Proton ne sont jamais proposés."""
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

from . import commun, config, sante
from . import steam as lecteur_steam
from .majapps.outils import version_ge

# Ce que les programmes recréent seuls. Playwright n'y est pas : ses navigateurs ne reviennent qu'avec
# `npx playwright install` (Ruling V59, m8).
CACHES_REGENERABLES = [("Miniatures", "~/.cache/thumbnails"), ("pip", "~/.cache/pip"), ("npm", "~/.npm/_cacache"),
                       ("Homebrew", "~/.cache/Homebrew")]
AGE_TELECHARGEMENTS_JOURS = 90
DOSSIERS_TELECHARGEMENTS = ("Téléchargements", "Downloads")
# Extensions de sauvegardes de jeux (jeux FromSoftware, émulateurs, Bethesda…), aussi suivies de « .bak » (V54).
SAUVEGARDES = (".sl2", ".co2", ".sav", ".save", ".srm", ".state", ".ess", ".fos")
OUTILS_PROTON = "~/.local/share/Steam/compatibilitytools.d"
CONFIG_STEAM = "~/.local/share/Steam/config/config.vdf"
# Heroic et Lutris (natifs ou Flatpak) peuvent aussi viser compatibilitytools.d : une version citée dans leurs réglages
# est gardée. Seuls leurs fichiers de réglages sont lus, pas leurs gros dossiers (outils, préfixes, caches, runners).
CONFIGS_LANCEURS = ("~/.config/heroic/config.json", "~/.config/heroic/GamesConfig/*.json",
                    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic/config.json",
                    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic/GamesConfig/*.json",
                    "~/.config/lutris/**/*.yml", "~/.local/share/lutris/*.yml", "~/.local/share/lutris/games/*.yml",
                    "~/.var/app/net.lutris.Lutris/config/lutris/**/*.yml",
                    "~/.var/app/net.lutris.Lutris/data/lutris/*.yml",
                    "~/.var/app/net.lutris.Lutris/data/lutris/games/*.yml",
                    "~/.local/share/lutris/runners/*.yml", "~/.var/app/net.lutris.Lutris/data/lutris/runners/*.yml")
PROCESSUS_STEAM = ("steam", "steamwebhelper")
COMMANDE_JOURNAL = "sudo journalctl --vacuum-size=500M"
JOURNAL_MIN = 1024 ** 3                 # même seuil que le point menage:journal
JOURNAL_GARDE = 500 * 1024 ** 2         # ce que --vacuum-size=500M laisse en place
# Une session « Tout mettre à jour » (son fichier, son unité) ou une mise à jour de la nuit (maj-apps, uupd).
UNITES_MAJ_UTILISATEUR = ("centre-bazzite-maj.service", "maj-apps.service")
UNITES_MAJ_SYSTEME = ("uupd.service", "uupd-manual.service")
ETATS_ACTIFS = {"active", "activating", "deactivating", "reloading", "refreshing"}

# id : (titre, explication, mode). Le mode est celui de l'id, jamais celui lu dans stockage.json.
TEXTES = {
    "caches": ("Caches régénérables", "Supprimés définitivement : les programmes les recréent au besoin.", "supprimer"),
    "corbeille": ("Corbeille", "Vidée définitivement, sur tous les disques.", "corbeille"),
    "telechargements": ("Téléchargements de plus de 90 jours",
                        "Envoyés à la corbeille : tu peux encore les récupérer.", "corbeille"),
    # Ruling V11 : seules les refs montrées, et seulement si elles sont toujours inutilisées.
    "runtimes": ("Runtimes Flatpak inutilisés",
                 "Désinstallés : seulement ceux listés ici, s'ils sont toujours inutilisés.", "commande"),
    "shaders": ("Caches de shaders sans jeu installé",
                "Supprimés définitivement : Steam les recrée si tu réinstalles le jeu.", "supprimer"),
    "proton": ("Versions de Proton inutilisées", "Supprimées définitivement ; ProtonPlus peut les réinstaller.",
               "supprimer"),
    "journal": ("Journal système",
                "Commande à lancer toi-même dans un terminal (elle demande ton mot de passe).", "copier"),
}

LIEN, HORS, MODIFIE, UTILISE, DISPARU = (
    "lien symbolique", "hors de son dossier", "modifié depuis", "utilisé maintenant", "disparu")
SAUVEGARDE, IMPOSSIBLE = "sauvegarde de jeu probable", "suppression impossible"
NON_VERIFIABLE, NOM_ILLISIBLE = "non vérifiable", "nom illisible"
STEAM_INCERTAIN = ("Steam : la liste des jeux installés n'est pas lisible (libraryfolders.vdf ou steamapps) : aucun "
                   "cache de shaders n'est proposé.")
JEU = "Un jeu tourne : ménage reporté."
MAJ = "Une mise à jour est en cours : ménage reporté."
STEAM = "Steam est ouvert : ferme-le pour retirer des versions de Proton."
STEAM_SHADERS = "Steam est ouvert : ferme-le pour supprimer des caches de shaders."
IDS_JEUX = ("shaders", "proton")        # ce que montre la page Jeux (la page Stockage les montre aussi)
CHANGEE = "La liste a changé : rien n'a été fait."
INCONNUE = "Recommandation inconnue."
A_LA_MAIN = "Cette recommandation se fait à la main : copie la commande et lance-la dans un terminal."

REF_FLATPAK = re.compile(r"^[\w.-]+/[\w.-]+/[\w.-]+$")
LIGNE_NUMEROTEE = re.compile(r"^\s*\d+\.\s+(.*)$")
INUTILISES = ["env", "LC_ALL=C", "flatpak", "uninstall", "--unused"]
LISTE_RUNTIMES = ["env", "LC_ALL=C", "flatpak", "list", "--runtime", "--columns=ref,installation,size"]


# --- La liste montrée ---

def cibles_de(reco):
    """Les cibles d'une recommandation, dans l'ordre où la fenêtre les montre."""
    return [str(e["cible"]) for e in (reco or {}).get("elements") or [] if isinstance(e, dict) and e.get("cible")]


def elements_de(reco):
    """Les éléments d'une recommandation, tels que la fenêtre les montre (cible, libellé, taille)."""
    return [e for e in (reco or {}).get("elements") or [] if isinstance(e, dict)]


def _octets(valeur):
    try:
        return int(round(float(valeur or 0)))
    except (TypeError, ValueError):
        return None


def empreinte(elements):
    """L'empreinte d'une liste d'éléments montrés : cible, libellé et taille de chacun, dans l'ordre (Ruling V60). La
    fenêtre passe celle de la liste qu'elle a montrée, et la CLI n'agit que si stockage.json propose encore exactement
    cette liste. Les tailles sont comparées en octets entiers (la fenêtre les rend en nombres JavaScript)."""
    signature = [[str(e.get("cible")), str(e.get("libelle")), _octets(e.get("octets"))]
                 for e in elements or [] if isinstance(e, dict)]
    return hashlib.sha256(json.dumps(signature, ensure_ascii=True).encode("ascii")).hexdigest()[:16]


def _lisible(texte):
    """Le texte s'écrit-il en UTF-8 ? Un nom de fichier en octets invalides donne des « surrogates » : il ne peut ni
    s'afficher ni s'écrire dans stockage.json."""
    try:
        str(texte).encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# --- Ce qui empêche d'agir ---

def maj_en_cours(run=commun.run):
    """Une mise à jour tourne : le fichier de la session « Tout mettre à jour » existe, ou l'une de ses unités (ou
    celles de la nuit) est active. Une réponse illisible de systemctl ne compte pas comme active."""
    if (commun.ETAT / "session-en-cours.json").exists():
        return True
    actives = False
    for cmd in (["systemctl", "--user", "is-active", *UNITES_MAJ_UTILISATEUR],
                ["systemctl", "is-active", *UNITES_MAJ_SYSTEME]):
        _, sortie = run(cmd, timeout=15)
        actives = actives or any(l.strip() in ETATS_ACTIFS for l in sortie.splitlines())
    return actives


def steam_ouvert(proc=Path("/proc")):
    """Le nom d'un processus du client Steam qui tourne, ou None. Steam n'écrit config.vdf qu'à certains moments.
    `comm` est lu en octets (coupé à 15 octets, parfois au milieu d'un caractère) : un nom illisible ne fait jamais
    lever (RF-m2, comme W7)."""
    for p in Path(proc).iterdir():
        if p.name.isdigit():
            try:
                nom = (p / "comm").read_bytes().decode("utf-8", errors="replace").strip()
            except (OSError, ValueError):
                continue
            if nom in PROCESSUS_STEAM:
                return nom
    return None


# --- Chemins et revérification ---

def _chemin(home, texte):
    return Path(home) / texte.removeprefix("~/")


def _racine(home, texte):
    """Le dossier permis tel qu'il doit être une fois les liens résolus : seul le home peut en passer par un
    (/home -> /var/home). Un dossier intermédiaire qui serait un lien rend la cible « hors de son dossier »."""
    return Path(os.path.realpath(home)) / texte.removeprefix("~/")


def _ecart(chemin, permis, *, entree=True):
    """La raison d'écarter `chemin`, ou None. Il doit exister, ne pas être un lien symbolique, et son realpath doit
    être une entrée directe d'un dossier de `permis` (entree=True), ou l'un de ces dossiers (entree=False)."""
    chemin = Path(chemin)
    if chemin.is_symlink():
        return LIEN
    if not os.path.lexists(chemin):
        return DISPARU
    reel = Path(os.path.realpath(chemin))
    return None if (reel.parent if entree else reel) in permis else HORS


def est_sauvegarde(nom):
    """Le nom ressemble-t-il à une sauvegarde de jeu (SAVE0000.sl2, partie.co2, slot.sav.bak…) ?"""
    n = nom.lower()
    while n.endswith(".bak"):
        n = n[:-4]
    return n.endswith(SAUVEGARDES)


def _age(st):
    """Le moment le plus récent où le fichier a changé : une copie ou une extraction garde son mtime d'origine, mais
    son ctime dit quand il est arrivé ici."""
    return max(st.st_mtime, st.st_ctime)


def _parcourir(chemin):
    """(octets sur le disque, moment le plus récent de toute l'arborescence, contient une sauvegarde de jeu probable,
    tout a pu être lu) d'un fichier ou d'un dossier, sans suivre aucun lien ; (0, None, False, False) s'il n'existe
    pas. Un sous-dossier ou une entrée illisible rend le parcours incomplet : ce qu'il cache (une sauvegarde, un
    fichier récent) n'a pas été vu (Ruling V60)."""
    try:
        st = os.lstat(chemin)
    except OSError:
        return 0, None, False, False
    octets, recent = st.st_blocks * 512, _age(st)
    sauvegarde = not stat.S_ISDIR(st.st_mode) and est_sauvegarde(os.path.basename(chemin))
    erreurs = []
    if stat.S_ISDIR(st.st_mode):
        for racine, dossiers, fichiers in os.walk(chemin, onerror=erreurs.append):
            for nom in dossiers + fichiers:
                try:
                    s = os.lstat(os.path.join(racine, nom))
                except OSError as exc:
                    erreurs.append(exc)
                    continue
                octets += s.st_blocks * 512
                recent = max(recent, _age(s))
            sauvegarde = sauvegarde or any(est_sauvegarde(nom) for nom in fichiers)
    return octets, recent, sauvegarde, not erreurs


def _limite(maintenant):
    return (maintenant or datetime.now()).timestamp() - AGE_TELECHARGEMENTS_JOURS * 86400


def _element(cible, libelle, octets):
    return {"cible": str(cible), "libelle": libelle, "octets": octets, "taille": commun.taille(octets)}


def _phrase(n, un, plusieurs):
    return None if n == 0 else un if n == 1 else plusieurs.format(n=n)


def _joindre(*phrases):
    return " ".join(p for p in phrases if p) or None


def _non_verifiables(n):
    return _phrase(n, "Un élément qui ne peut pas être vérifié est laissé de côté.",
                   "{n} éléments qui ne peuvent pas être vérifiés sont laissés de côté.")


def _reco(id_, elements, a_copier=None, remarque=None):
    titre, explication, mode = TEXTES[id_]
    elements = sorted(elements, key=lambda e: -e["octets"])
    octets = sum(e["octets"] for e in elements)
    return {"id": id_, "titre": titre, "explication": explication, "octets": octets, "taille": commun.taille(octets),
            "mode": mode, "elements": elements, "a_copier": a_copier, "remarque": remarque}


# --- Steam : versions de Proton ---

def _bloc(d, cle):
    """Le premier bloc nommé `cle` (sans tenir compte de la casse), à n'importe quelle profondeur."""
    for k, v in d.items():
        if isinstance(v, dict):
            if k.lower() == cle.lower():
                return v
            trouve = _bloc(v, cle)
            if trouve is not None:
                return trouve
    return None


def _outils_utilises(config_vdf):
    """Les noms d'outils de CompatToolMapping (config.vdf), ou None si le bloc est introuvable."""
    bloc = _bloc(lecteur_steam.lire_vdf(config_vdf), "CompatToolMapping")
    if bloc is None:
        return None
    return {v["name"] for v in bloc.values() if isinstance(v, dict) and v.get("name")}


def _noms_internes(dossier):
    """Les noms sous lesquels l'outil se déclare à Steam (compatibilitytool.vdf), que Steam note dans
    CompatToolMapping."""
    try:
        texte = (Path(dossier) / "compatibilitytool.vdf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return set(_bloc(lecteur_steam.lire_vdf(texte), "compat_tools") or {})


def proton_inutilises(dossier, config_vdf):
    """Les dossiers GE-Proton* de `dossier` qu'aucune appli n'utilise dans CompatToolMapping (config.vdf de Steam),
    du plus ancien au plus récent. La version la plus récente est toujours gardée ; sans CompatToolMapping lisible,
    rien n'est proposé (on ne sait pas ce qui sert)."""
    utilises = _outils_utilises(config_vdf)
    if utilises is None:
        return []
    try:
        dossiers = [p for p in Path(dossier).iterdir()
                    if p.name.startswith("GE-Proton") and version_ge(p.name) and not p.is_symlink() and p.is_dir()]
    except OSError:
        return []
    if not dossiers:
        return []
    recente = max(version_ge(p.name) for p in dossiers)
    return sorted((p for p in dossiers
                   if version_ge(p.name) != recente and not ({p.name} | _noms_internes(p)) & utilises),
                  key=lambda p: version_ge(p.name))


def _reglages_lanceurs(home):
    """Le texte des réglages de Heroic et de Lutris (CONFIGS_LANCEURS), lus sans rien modifier, ou None si l'un d'eux
    est illisible : il pourrait citer n'importe quelle version."""
    textes = []
    try:
        for motif in CONFIGS_LANCEURS:
            for f in sorted(Path(home).glob(motif.removeprefix("~/"))):
                textes.append(f.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return "\n".join(textes)


def _cites_ailleurs(dossier, reglages):
    """L'outil (nom du dossier ou nom interne) est-il cité dans les réglages de Heroic ou de Lutris ? Une simple
    recherche de texte : au pire, elle garde une version de trop."""
    return any(nom in reglages for nom in {dossier.name} | _noms_internes(dossier))


def _protons(home):
    """Les versions de Proton inutilisées du home qui passent la revérification (dans leur dossier, pas un lien) :
    ni Steam (CompatToolMapping), ni Heroic, ni Lutris ne s'en servent."""
    try:
        config = _chemin(home, CONFIG_STEAM).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    reglages = _reglages_lanceurs(home)
    if reglages is None:
        return []
    permis = {_racine(home, OUTILS_PROTON)}
    return [p for p in proton_inutilises(_chemin(home, OUTILS_PROTON), config)
            if _ecart(p, permis) is None and not _cites_ailleurs(p, reglages)]


# --- Steam : caches de shaders sans jeu installé ---

def _appid_decimal(nom):
    """L'appid d'un nom de dossier de shadercache (décimal canonique, avant APPID_MAX), ou None : les raccourcis
    non-Steam et les noms inhabituels ne sont jamais des cibles."""
    if not re.fullmatch(r"[1-9][0-9]{0,9}", nom) or int(nom) >= lecteur_steam.APPID_MAX:
        return None
    return nom


def _bibliotheques_steam(home, bibliotheques):
    """Les bibliothèques Steam à lire : celles données, sinon celles de Steam et de la configuration (lues à l'appel,
    les racines de Steam résolues contre `home`)."""
    if bibliotheques is not None:
        return [Path(b) for b in bibliotheques]
    return lecteur_steam.bibliotheques(home, en_plus=config.jeux()["steam"])[0]


def _shaders(home, bibliotheques):
    """Les caches de shaders (steamapps/shadercache/<appid>) qu'aucun jeu ne justifie : D3. Un appid est installé s'il a un
    appmanifest (.tmp compris) ou un dossier downloading dans une bibliothèque, ou s'il figure dans libraryfolders.vdf
    (un disque débranché garde ses jeux). Un raccourci non-Steam (appid >= 2^31) n'est jamais proposé. Un parcours
    incomplet écarte l'élément. Si la liste des jeux installés n'est pas certaine (libraryfolders.vdf manquant, illisible
    ou coupé, steamapps illisible), rien n'est proposé et la remarque le dit (Ruling W5)."""
    installes = lecteur_steam.appids_installes(bibliotheques, home=home)
    if installes is None:
        return _reco("shaders", [], remarque=STEAM_INCERTAIN)
    elements, douteux = [], 0
    for bib in bibliotheques:
        cache = Path(bib) / "steamapps" / "shadercache"
        permis = {Path(os.path.realpath(bib)) / "steamapps" / "shadercache"}
        try:
            entrees = sorted(os.listdir(cache)) if cache.is_dir() else []
        except OSError:
            douteux += 1
            continue
        for nom in entrees:
            appid = _appid_decimal(nom)
            chemin = cache / nom
            if appid is None or appid in installes or _ecart(chemin, permis) is not None or not chemin.is_dir():
                continue
            octets, _recent, _sauvegarde, complet = _parcourir(chemin)
            if not complet:
                douteux += 1
            else:
                elements.append(_element(chemin, f"Jeu Steam {appid} ({bib})", octets))
    return _reco("shaders", elements, remarque=_non_verifiables(douteux))


# --- Flatpak : runtimes inutilisés ---

def lire_liste_runtimes(sortie):
    """Les lignes de `env LC_ALL=C flatpak list --runtime --columns=ref,installation,size` :
    [{"ref": "runtime/<id>/<arch>/<branche>", "installation": "system"|"user"|…, "octets": int}]."""
    res = []
    for ligne in sortie.splitlines():
        champs = [c.strip() for c in ligne.split("\t")]
        if len(champs) >= 3 and REF_FLATPAK.match(champs[0]) and champs[1]:
            res.append({"ref": "runtime/" + champs[0], "installation": champs[1],
                        "octets": commun.lire_taille(champs[2]) or 0})
    return res


def _lire_inutilises(sortie):
    """(id, arch ou None, branche) de chaque ligne numérotée de `env LC_ALL=C flatpak uninstall --unused`, rangée selon
    l'en-tête du tableau qui la précède (« ID Branch Op », ou « ID Arch Branch Op » quand une arch n'est pas celle par
    défaut). None si une ligne numérotée n'a pas d'en-tête lisible."""
    colonnes, res = None, []
    for ligne in sortie.splitlines():
        mots = ligne.split()
        if "ID" in mots and "Branch" in mots:
            colonnes = mots
            continue
        m = LIGNE_NUMEROTEE.match(ligne)
        if not m:
            continue
        if colonnes is None:
            return None
        valeurs = dict(zip(colonnes, m.group(1).split()))
        if not sante.ID_FLATPAK.match(valeurs.get("ID", "")) or not valeurs.get("Branch"):
            return None
        res.append((valeurs["ID"], valeurs.get("Arch"), valeurs["Branch"]))
    return res


def runtimes_inutilises(run):
    """{ref complète: {"octets", "installation"}} des runtimes que `flatpak uninstall --unused` retirerait, ou None si
    une liste est illisible. La question reçoit « n » (et flatpak répond lui-même « n » hors d'un terminal) : rien n'est
    désinstallé. L'id, l'arch et la branche viennent de cette sortie ; la ref doit figurer telle quelle dans la liste
    réelle, dans une seule installation (sinon on ne sait pas laquelle est inutilisée, et elle n'est pas prise)."""
    code, sortie = run(INUTILISES, timeout=180, entree="n\n")
    lignes = _lire_inutilises(sortie)
    if lignes is None:
        return None
    if not lignes:
        return None if code != 0 and "nothing unused" not in sortie.lower() else {}
    arch_defaut = None
    if any(arch is None for _, arch, _ in lignes):
        code, texte = run(["flatpak", "--default-arch"], timeout=30)
        arch_defaut = texte.strip()
        if code != 0 or not re.fullmatch(r"[\w-]+", arch_defaut):
            return None
    code, liste = run(LISTE_RUNTIMES, timeout=60)
    if code != 0:
        return None
    installes = {}
    for r in lire_liste_runtimes(liste):
        installes.setdefault(r["ref"], []).append(r)
    res = {}
    for id_, arch, branche in lignes:
        ref = f"runtime/{id_}/{arch or arch_defaut}/{branche}"
        if len(installes.get(ref, [])) == 1:
            r = installes[ref][0]
            res[ref] = {"octets": r["octets"], "installation": r["installation"]}
    return res


def _option_installation(nom):
    return "--system" if nom == "system" else "--user" if nom == "user" else f"--installation={nom}"


# --- Corbeille ---

def _taille_corbeille(nom, home):
    """Place d'un élément de la corbeille. gvfs nomme un élément de la corbeille du home par son nom, et celui d'un
    autre disque par le chemin complet de son fichier, « \\ » à la place de « / ». 0 si on ne le retrouve pas."""
    if nom.startswith("\\"):
        chemin = Path(nom.replace("\\", "/"))
        if "/.Trash" not in str(chemin):
            return 0
    elif "/" in nom:
        return 0
    else:
        chemin = Path(home) / ".local" / "share" / "Trash" / "files" / nom
    return _parcourir(chemin)[0]


def _corbeille(run, home):
    """Les entrées de `gio trash --list` (exactement ce que `gio trash --empty` effacerait), ou None si illisible."""
    code, sortie = run(["gio", "trash", "--list"], timeout=60)
    if code != 0:
        return None
    res = []
    for ligne in sortie.splitlines():
        uri, _, origine = ligne.partition("\t")
        uri = uri.strip()
        if uri.startswith("trash:///"):
            nom = urllib.parse.unquote(uri.removeprefix("trash:///"))
            res.append(_element(uri, origine.strip() or nom, _taille_corbeille(nom, home)))
    return res


def _signature_corbeille(elements):
    """Ce qui identifie la liste montrée : chaque entrée avec son origine et sa taille."""
    return sorted((str(e.get("cible")), str(e.get("libelle")), e.get("octets")) for e in elements)


# --- Recommandations ---

def _caches(home):
    elements = []
    for nom, texte in CACHES_REGENERABLES:
        chemin = _chemin(home, texte)
        if _ecart(chemin, {_racine(home, texte)}, entree=False) is None and chemin.is_dir():
            octets = sante.taille_dossier(chemin)
            if octets > 0:
                elements.append(_element(chemin, nom, octets))
    return _reco("caches", elements)


def _telechargements(home, maintenant):
    """Les entrées de premier niveau (ni cachées, ni liens) qui n'ont pas changé depuis plus de 90 jours dans toute leur
    arborescence (mtime et ctime). Un dossier de téléchargements qui est lui-même un lien n'est pas parcouru. Sont
    laissées de côté, et comptées : les sauvegardes de jeux probables (et les dossiers qui en contiennent), et ce qui ne
    peut pas être vérifié (sous-dossier illisible, nom qui n'est pas de l'UTF-8)."""
    limite, elements, sauvegardes, douteux = _limite(maintenant), [], 0, 0
    for nom in DOSSIERS_TELECHARGEMENTS:
        dossier, permis = Path(home) / nom, {_racine(home, nom)}
        if dossier.is_symlink() or not dossier.is_dir():
            continue
        with os.scandir(dossier) as entrees:
            for entree in entrees:
                if entree.name.startswith(".") or _ecart(entree.path, permis) is not None:
                    continue
                octets, recent, sauvegarde, complet = _parcourir(entree.path)
                if recent is None or recent >= limite:
                    continue
                if not complet or not _lisible(entree.path):
                    douteux += 1
                elif sauvegarde:
                    sauvegardes += 1
                else:
                    elements.append(_element(entree.path, entree.name, octets))
    remarque = _joindre(_phrase(sauvegardes, "Une sauvegarde de jeu probable est laissée de côté.",
                                "{n} sauvegardes de jeux probables sont laissées de côté."),
                        _non_verifiables(douteux))
    return _reco("telechargements", elements, remarque=remarque)


def _runtimes(run, controles):
    """Seulement si les contrôles (T9) ont vu des runtimes à retirer : la liste est alors relue, avec arch et branche.
    Les pilotes GL NVIDIA obsolètes encore épinglés (que --unused ne retire jamais) sont donnés à copier."""
    r = (controles or {}).get("runtimes") or {}
    if not (r.get("inutilises") or r.get("gl_obsoletes")):
        return None
    inutilises = runtimes_inutilises(run)
    if not inutilises:
        return None
    elements = [_element(ref, "{1} {3} ({2})".format(*ref.split("/")), v["octets"]) for ref, v in inutilises.items()]
    epingles = [g for g in r.get("gl_obsoletes") or [] if g not in inutilises]
    return _reco("runtimes", elements, "flatpak uninstall " + " ".join(epingles) if epingles else None)


def _journal(controles):
    journal = ((controles or {}).get("caches") or {}).get("journal")
    if not isinstance(journal, (int, float)) or journal < JOURNAL_MIN:
        return None
    return _reco("journal", [_element("journal", "Journal système", int(journal) - JOURNAL_GARDE)], COMMANDE_JOURNAL)


def recommandations(*, home=None, maintenant=None, run=commun.run, controles=None, steam=None, bibliotheques=None):
    """Les recommandations qui ont des éléments, dans l'ordre de la page. Ne fait que lire : `gio trash --list`,
    `flatpak uninstall --unused` répondu « n » et `flatpak list`. `controles` : controles.json (lu s'il est omis).
    `steam()` dit si Steam tourne (alors les versions de Proton ne sont pas proposées ; les caches de shaders, eux, le
    sont : c'est leur exécution qui attend la fermeture de Steam). `bibliotheques` : les bibliothèques Steam (par défaut,
    relues à l'appel). Une recommandation en panne est écrite sur stderr et n'empêche pas les autres."""
    home = Path(home) if home is not None else Path.home()
    if controles is None:
        controles = sante.lire_controles() or {}
    steam = steam or steam_ouvert

    def proton():
        if steam():
            return None
        return _reco("proton", [_element(p, p.name, _parcourir(p)[0]) for p in _protons(home)])

    calculs = (("caches", lambda: _caches(home)),
               ("corbeille", lambda: _reco("corbeille", _corbeille(run, home) or [])),
               ("telechargements", lambda: _telechargements(home, maintenant)),
               ("runtimes", lambda: _runtimes(run, controles)),
               ("shaders", lambda: _shaders(home, _bibliotheques_steam(home, bibliotheques))),
               ("proton", proton),
               ("journal", lambda: _journal(controles)))
    res = []
    for id_, calcul in calculs:
        try:
            reco = calcul()
            reco = reco and _sans_noms_illisibles(reco)
            if reco:
                json.dumps(reco, ensure_ascii=False).encode("utf-8")      # stockage.json devra l'écrire
        except Exception as exc:
            print(f"ménage {id_} en échec : {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if reco and reco["elements"]:
            res.append(reco)
        elif reco and reco["remarque"]:
            print(f"ménage {id_} : {reco['remarque']}", file=sys.stderr)
    return res


def _sans_noms_illisibles(reco):
    """Écarte les éléments dont la cible ou le libellé n'est pas de l'UTF-8 (un nom de fichier en octets invalides) :
    on ne saurait ni le montrer fidèlement ni l'écrire dans stockage.json, dont l'écriture échouerait alors pour tout le
    monde, relevé horaire compris. Ils sont comptés dans la remarque de la carte."""
    gardes = [e for e in reco["elements"] if _lisible(e["cible"]) and _lisible(e["libelle"])]
    ecartes = len(reco["elements"]) - len(gardes)
    if not ecartes:
        return reco
    return _reco(reco["id"], gardes, reco["a_copier"], _joindre(reco["remarque"], _non_verifiables(ecartes)))


# --- Exécution ---

def _ignorer(res, cible, raison):
    res["ignores"].append({"cible": cible, "raison": raison})


def _derniere_ligne(sortie):
    lignes = [l.strip() for l in (sortie or "").splitlines() if l.strip()]
    return lignes[-1] if lignes else "sans message"


def _vider(dossier, permis):
    """Supprime le contenu de `dossier` et garde le dossier. Ouvert sans suivre de lien (O_NOFOLLOW), son realpath est
    relu sur le descripteur même (un dossier parent remplacé entre-temps est vu), puis tout se fait relativement à ce
    descripteur : aucun lien n'est suivi, ni à la racine ni dedans. Rend la raison d'écart (dont « suppression
    impossible » s'il reste quelque chose), ou None."""
    try:
        fd = os.open(dossier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return LIEN if Path(dossier).is_symlink() else DISPARU
    try:
        if Path(os.readlink(f"/proc/self/fd/{fd}")) not in permis:
            return HORS
        with os.scandir(fd) as entrees:
            for e in list(entrees):
                try:
                    if e.is_dir(follow_symlinks=False):
                        shutil.rmtree(e.name, dir_fd=fd, ignore_errors=True)
                    else:
                        os.unlink(e.name, dir_fd=fd)
                except OSError:
                    pass
        with os.scandir(fd) as reste:
            return IMPOSSIBLE if any(True for _ in reste) else None
    finally:
        os.close(fd)


def _executer_caches(cibles, res, home, **_):
    permis = {_racine(home, texte) for _, texte in CACHES_REGENERABLES}
    for cible in cibles:
        raison = _ecart(cible, permis, entree=False)
        if raison is None and not Path(cible).is_dir():
            raison = HORS
        if raison:
            _ignorer(res, cible, raison)
            continue
        avant = sante.taille_dossier(cible)
        raison = _vider(cible, permis)
        if raison in (None, IMPOSSIBLE):
            res["liberes"] += max(0, avant - sante.taille_dossier(cible))
        if raison:
            _ignorer(res, cible, raison)
        else:
            res["faits"].append(cible)


def _executer_telechargements(cibles, res, home, maintenant, run, **_):
    permis = {_racine(home, nom) for nom in DOSSIERS_TELECHARGEMENTS}
    limite, a_jeter, tailles = _limite(maintenant), [], {}
    for cible in cibles:
        raison = _ecart(cible, permis)
        if raison is None:
            octets, recent, sauvegarde, complet = _parcourir(cible)
            raison = (DISPARU if recent is None else NON_VERIFIABLE if not complet else SAUVEGARDE if sauvegarde
                      else MODIFIE if recent >= limite else None)
        if raison:
            _ignorer(res, cible, raison)
            continue
        a_jeter.append(cible)
        tailles[cible] = octets
    if not a_jeter:
        return
    code, sortie = run(["gio", "trash", "--", *a_jeter], timeout=600)
    for cible in a_jeter:
        if os.path.lexists(cible):
            _ignorer(res, cible, IMPOSSIBLE)
        else:
            res["faits"].append(cible)
            res["liberes"] += tailles[cible]
    if code != 0 or len(res["faits"]) < len(a_jeter):
        res["erreur"] = f"La corbeille a refusé certains fichiers : {_derniere_ligne(sortie)}"


def _executer_corbeille(cibles, res, home, run, montres, **_):
    """Ruling V10 : la corbeille est relue ; si elle diffère de celle montrée (une entrée, son origine ou sa taille),
    rien n'est vidé."""
    if not cibles:
        return
    entrees = _corbeille(run, home)
    if entrees is None:
        res["erreur"] = "Impossible de relire la corbeille : rien n'a été vidé."
        return
    if _signature_corbeille(entrees) != _signature_corbeille(montres):
        for cible in cibles:
            _ignorer(res, cible, MODIFIE)
        res["erreur"] = "La corbeille a changé depuis l'affichage : rien n'a été vidé. Vérifie la nouvelle liste."
        return
    code, sortie = run(["gio", "trash", "--empty"], timeout=600)
    if code != 0:
        res["erreur"] = f"La corbeille n'a pas pu être vidée : {_derniere_ligne(sortie)}"
        return
    res["faits"] = list(cibles)
    res["liberes"] = sum(e["octets"] for e in entrees)


def _executer_runtimes(cibles, res, run, **_):
    """Ruling V11 : la liste « inutilisés » est relue ; seules les refs montrées qui y figurent encore (id, arch et
    branche) sont désinstallées, nommément et dans leur installation (jamais --unused, qui prendrait aussi ce qui n'a
    pas été montré)."""
    inutilises = runtimes_inutilises(run)
    if inutilises is None:
        res["erreur"] = "Impossible de relire les runtimes inutilisés : rien n'a été désinstallé."
        return
    par_installation = {}
    for cible in cibles:
        if cible in inutilises:
            par_installation.setdefault(inutilises[cible]["installation"], []).append(cible)
        else:
            _ignorer(res, cible, UTILISE)
    for installation, refs in par_installation.items():
        code, sortie = run(["flatpak", "uninstall", _option_installation(installation), "-y", "--noninteractive", *refs],
                           timeout=1800)
        if code != 0:
            for ref in refs:
                _ignorer(res, ref, IMPOSSIBLE)
            res["erreur"] = f"flatpak n'a pas pu tout désinstaller : {_derniere_ligne(sortie)}"
            continue
        res["faits"] += refs
        res["liberes"] += sum(inutilises[r]["octets"] for r in refs)


def _executer_shaders(cibles, res, home, bibliotheques=None, **_):
    """Chaque cible est revérifiée : les bibliothèques et les appids installés sont relus maintenant ; la cible est une
    entrée directe de steamapps/shadercache (pas un lien), son nom est un appid décimal avant APPID_MAX, et aucun jeu
    ne l'a installé depuis l'affichage."""
    bibs = _bibliotheques_steam(home, bibliotheques)
    installes = lecteur_steam.appids_installes(bibs, home=home)
    if installes is None:                       # on ne sait plus quels jeux sont installés : rien n'est supprimé
        for cible in cibles:
            _ignorer(res, cible, NON_VERIFIABLE)
        return
    permis = {Path(os.path.realpath(b)) / "steamapps" / "shadercache" for b in bibs}
    for cible in cibles:
        raison = _ecart(cible, permis)
        appid = _appid_decimal(Path(cible).name)
        if raison is None and (appid is None or not Path(cible).is_dir()):
            raison = HORS
        if raison is None and appid in installes:
            raison = UTILISE
        if raison:
            _ignorer(res, cible, raison)
            continue
        avant = _parcourir(cible)[0]
        shutil.rmtree(cible, ignore_errors=True)        # refuse un lien à la racine, ne suit aucun lien dedans
        res["liberes"] += max(0, avant - _parcourir(cible)[0])
        if os.path.lexists(cible):
            _ignorer(res, cible, IMPOSSIBLE)
        else:
            res["faits"].append(cible)


def _executer_proton(cibles, res, home, **_):
    permis = {_racine(home, OUTILS_PROTON)}
    inutilises = {str(p) for p in _protons(home)}
    for cible in cibles:
        raison = _ecart(cible, permis)
        if raison is None and not Path(cible).name.startswith("GE-Proton"):
            raison = HORS
        if raison is None and str(_chemin(home, OUTILS_PROTON) / Path(cible).name) not in inutilises:
            raison = UTILISE
        if raison:
            _ignorer(res, cible, raison)
            continue
        avant = _parcourir(cible)[0]
        shutil.rmtree(cible, ignore_errors=True)        # refuse un lien à la racine, ne suit aucun lien dedans
        res["liberes"] += max(0, avant - _parcourir(cible)[0])
        if os.path.lexists(cible):
            _ignorer(res, cible, IMPOSSIBLE)
        else:
            res["faits"].append(cible)


ACTIONS = {"caches": _executer_caches, "corbeille": _executer_corbeille, "telechargements": _executer_telechargements,
           "runtimes": _executer_runtimes, "shaders": _executer_shaders, "proton": _executer_proton}


def executer(id_, recos, *, home=None, maintenant=None, run=commun.run, jeu=commun.jeu_en_cours, maj=None,
             steam=None, bibliotheques=None):
    """Fait le ménage de la recommandation `id_` de `recos` (celles de stockage.json, telles que montrées) : seulement
    ses éléments, chacun revérifié. Rien n'est fait pendant un jeu (`jeu()`) ni une mise à jour (`maj()`, par défaut
    maj_en_cours avec ce `run`) ; les versions de Proton et les caches de shaders attendent que Steam soit fermé (`steam()`). `bibliotheques` : les
    bibliothèques Steam des caches de shaders (par défaut, relues à l'appel). Une commande à
    copier n'est jamais lancée. Rend {"id", "liberes", "faits": [cible], "ignores": [{"cible", "raison"}],
    "erreur": str|None}."""
    res = {"id": id_, "liberes": 0, "faits": [], "ignores": [], "erreur": None}
    reco = next((r for r in recos or [] if isinstance(r, dict) and r.get("id") == id_), None)
    if reco is None or id_ not in TEXTES:
        res["erreur"] = INCONNUE
        return res
    if id_ not in ACTIONS:
        res["erreur"] = A_LA_MAIN
        return res
    if jeu():
        res["erreur"] = JEU
        return res
    if (maj() if maj is not None else maj_en_cours(run)):
        res["erreur"] = MAJ
        return res
    if id_ == "proton" and (steam or steam_ouvert)():
        res["erreur"] = STEAM
        return res
    if id_ == "shaders" and (steam or steam_ouvert)():
        res["erreur"] = STEAM_SHADERS
        return res
    montres = [e for e in reco.get("elements") or [] if isinstance(e, dict) and e.get("cible")]
    cibles = []
    for cible in cibles_de(reco):
        if _lisible(cible):
            cibles.append(cible)
        else:
            _ignorer(res, cible, NOM_ILLISIBLE)
    if id_ == "corbeille" and res["ignores"]:
        res["erreur"] = "La corbeille montrée contient un nom illisible : rien n'a été vidé."
        return res
    ACTIONS[id_](cibles, res, home=Path(home) if home is not None else Path.home(), maintenant=maintenant,
                 run=run, montres=montres, bibliotheques=bibliotheques)
    return res
