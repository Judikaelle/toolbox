"""Steam, en lecture seule : les bibliothèques (libraryfolders.vdf), les appmanifests et les appids installés.
Rien n'est écrit, aucun client n'est lancé ; un fichier illisible est ignoré."""
import os
import re
from pathlib import Path

RACINES = ("~/.local/share/Steam", "~/.var/app/com.valvesoftware.Steam/.local/share/Steam")
APPID_MAX = 2 ** 31                       # au-delà : raccourcis non-Steam
# Steam écrit /mnt/… dans sa configuration ; Bazzite monte les disques sous /var/mnt.
CORRECTIONS = (("/mnt/", "/var/mnt/"),)
# Les entrées Steam qui ne sont pas des jeux (même expression que game-runner).
OUTILS = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|Legacy Steam Runtime|SteamVR|Steam Controller)",
                    re.I)
JETON_VDF = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*')
_NOMS = {}              # {(home, appid): nom ou None} : nom_du_jeu ne relit pas l'appmanifest toutes les 5 s


def lire_vdf(texte):
    """Un fichier VDF de Steam en dictionnaires imbriqués (une clé en double garde sa dernière valeur)."""
    pile, cle = [{}], None
    for m in JETON_VDF.finditer(texte or ""):
        chaine, accolade = m.group(1), m.group(2)
        if chaine is not None:
            if cle is None:
                cle = chaine
            else:
                pile[-1][cle], cle = chaine, None
        elif accolade == "{":
            bloc = {}
            if cle is not None:
                pile[-1][cle] = bloc
            pile.append(bloc)
            cle = None
        elif accolade == "}":
            if len(pile) > 1:
                pile.pop()
            cle = None
    return pile[0]


def _equilibre(texte):
    """Vrai si les accolades du VDF sont toutes fermées (lire_vdf tolère un fichier coupé, pas ce contrôle)."""
    niveau = 0
    for m in JETON_VDF.finditer(texte or ""):
        if m.group(2) == "{":
            niveau += 1
        elif m.group(2) == "}":
            niveau -= 1
            if niveau < 0:
                return False
    return niveau == 0


def _lire(chemin):
    try:
        return Path(chemin).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _racines(home):
    base = Path(home) if home is not None else Path.home()
    res = []
    for r in RACINES:
        chemin = base / r[2:]
        if chemin.is_dir():
            res.append(chemin)
    return res


def _dossiers_vdf(home):
    """(blocs, incertain) : les blocs de bibliothèque des libraryfolders.vdf lisibles des racines,
    [{"path": str, "apps": {appid, …}}], et `incertain`, vrai si une racine existe mais que son fichier manque, est
    illisible, coupé (accolades non fermées) ou sans bloc `libraryfolders` : on ne sait alors pas toutes les
    bibliothèques qui existent (Ruling W5). L'inventaire garde les blocs lus (RF-m5) ; le ménage s'arrête à
    l'incertitude (appids_installes)."""
    blocs, incertain = [], False
    for racine in _racines(home):
        texte = _lire(racine / "steamapps" / "libraryfolders.vdf")
        dossiers = lire_vdf(texte).get("libraryfolders") if texte and _equilibre(texte) else None
        if not isinstance(dossiers, dict):
            incertain = True
            continue
        for bloc in dossiers.values():
            if isinstance(bloc, dict) and isinstance(bloc.get("path"), str) and bloc["path"]:
                apps = bloc.get("apps")
                blocs.append({"path": bloc["path"], "apps": set(apps) if isinstance(apps, dict) else set()})
    return blocs, incertain


def _resoudre(chemin, corrections):
    """Le chemin d'une bibliothèque qui a un dossier steamapps (essayé tel quel, puis avec chaque correction de
    préfixe), ou None."""
    candidats = [str(chemin)] + [str(chemin).replace(ancien, nouveau, 1)
                                 for ancien, nouveau in corrections if str(chemin).startswith(ancien)]
    for c in candidats:
        if (Path(c) / "steamapps").is_dir():
            return Path(os.path.realpath(c))
    return None


def bibliotheques(home=None, *, en_plus=(), corrections=CORRECTIONS):
    """(présentes, absentes) : les racines de Steam, les bibliothèques de libraryfolders.vdf, puis `en_plus` (config),
    sans doublon et dans cet ordre. Une présente a un dossier steamapps (chemin résolu) ; une absente est un chemin
    (texte) de libraryfolders.vdf ou de `en_plus` qui n'existe pas, par exemple un disque débranché. Une racine dont le
    libraryfolders.vdf ne se lit pas n'empêche pas de lister les bibliothèques lues dans une autre (RF-m5)."""
    sources = [*_racines(home), *(d["path"] for d in _dossiers_vdf(home)[0]), *en_plus]
    presentes, absentes, vus = [], [], set()
    for source in sources:
        reel = _resoudre(source, corrections)
        if reel is not None:
            if reel not in vus:
                vus.add(reel)
                presentes.append(reel)
        elif str(source) not in absentes:
            absentes.append(str(source))
    return presentes, absentes


def _entier(valeur):
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def manifestes(bibliotheque):
    """Les jeux d'une bibliothèque : un dict par steamapps/appmanifest_*.acf lisible (pas les .tmp). Un manifeste
    coupé, sans appid ou sans nom, est ignoré."""
    res = []
    for acf in sorted((Path(bibliotheque) / "steamapps").glob("appmanifest_*.acf")):
        texte = _lire(acf)
        if texte is None or not texte.rstrip().endswith("}"):
            continue
        etat = lire_vdf(texte).get("AppState")
        if not isinstance(etat, dict):
            continue
        appid, nom = etat.get("appid"), etat.get("name")
        if not (isinstance(appid, str) and appid.isdigit() and isinstance(nom, str) and nom):
            continue
        partie = _entier(etat.get("LastPlayed"))
        res.append({"appid": appid, "nom": nom, "installdir": str(etat.get("installdir") or nom),
                    "octets": max(0, _entier(etat.get("SizeOnDisk")) or 0), "derniere_partie": partie or None,
                    "outil": bool(OUTILS.match(nom))})
    return res


def _nom_manifeste(appid, home):
    """Le `name` de steamapps/appmanifest_<appid>.acf dans la première bibliothèque présente qui en a un entier (accolades
    fermées, même appid), ou None."""
    for bib in bibliotheques(home)[0]:
        texte = _lire(Path(bib) / "steamapps" / f"appmanifest_{appid}.acf")
        if not texte or not _equilibre(texte):
            continue
        etat = lire_vdf(texte).get("AppState")
        nom = etat.get("name") if isinstance(etat, dict) and etat.get("appid") == appid else None
        if isinstance(nom, str) and nom.strip():
            return nom.strip()
    return None


def nom_du_jeu(appid, home=None):
    """RF-I1 : le nom du jeu Steam `appid` (la valeur de SteamGameId), lu dans son appmanifest, ou None si ce n'est pas
    un jeu Steam (appid non décimal, raccourci non-Steam au-delà d'APPID_MAX) ou si aucun manifeste entier ne le nomme.
    Les bibliothèques lues sont celles de Steam (racines et libraryfolders.vdf) : Steam ne lance un jeu que depuis
    l'une d'elles. Le résultat est gardé par appid pour la vie du processus (le mode jeu demande le nom toutes les 5 s).
    Une erreur de lecture inattendue lève : l'appelant se replie (commun.jeu_en_cours)."""
    if not (isinstance(appid, str) and re.fullmatch(r"[1-9][0-9]{0,9}", appid) and int(appid) < APPID_MAX):
        return None
    cle = (str(home), appid)
    if cle not in _NOMS:
        _NOMS[cle] = _nom_manifeste(appid, home)
    return _NOMS[cle]


def appids_installes(bibliotheques, home=None):
    """Les appids connus de Steam : ceux qui ont un appmanifest_<id>.acf* (.tmp compris) ou un steamapps/downloading/<id>
    dans l'une des `bibliotheques`, et, si `home` est donné, ceux des blocs `apps` de toutes les bibliothèques de
    libraryfolders.vdf, présentes ou non (un jeu d'un disque débranché garde son cache).
    None si la liste n'est pas certaine : un libraryfolders.vdf d'une racine existante manquant, illisible, coupé ou
    sans bloc, ou un dossier steamapps (ou downloading) qui ne se lit pas autrement que par son absence."""
    res = set()
    for bib in bibliotheques:
        steamapps = Path(bib) / "steamapps"
        try:
            noms = os.listdir(steamapps)
        except FileNotFoundError:
            noms = []
        except OSError:
            return None
        try:
            telechargements = os.listdir(steamapps / "downloading")
        except FileNotFoundError:
            telechargements = []
        except OSError:
            return None
        for nom in noms:
            m = re.fullmatch(r"appmanifest_(\d+)\.acf.*", nom)
            if m:
                res.add(m.group(1))
        res.update(n for n in telechargements if n.isdigit())
    if home is not None:
        blocs, incertain = _dossiers_vdf(home)
        if incertain:                       # mode fermé (W5) : une seule racine incertaine suffit
            return None
        for d in blocs:
            res.update(d["apps"])
    return res
