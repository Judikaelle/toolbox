"""Les bibliothèques de jeux, en lecture seule : Steam, Heroic, Lutris et les dossiers d'émulateurs de la configuration.
Aucun lanceur n'est lancé ; une source illisible ou absente donne simplement moins de jeux.

Chaque lecteur rend (bibliothèques, jeux) dans les formes Bibliotheque et Jeu de jeux.json."""
import json
import os
import re
import sqlite3
import struct
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import commun, config, menage, sante, steam as steam_

HEROIC = ("~/.config/heroic", "~/.var/app/com.heroicgameslauncher.hgl/config/heroic")
BOUTIQUES = {"legendary": "Epic", "gog": "GOG", "nile": "Amazon", "zoom": "Zoom"}
LUTRIS = ("~/.local/share/lutris/pga.db", "~/.var/app/net.lutris.Lutris/data/lutris/pga.db")
IGNORES_EMULATEUR = (".png", ".jpg", ".jpeg", ".webp", ".txt", ".log", ".nfo", ".md")
INCONNUE = "Inconnue"
MOTIF_GEL = re.compile(r"^(\d{8})-(\d{6})-(GEL-)?(.+)\.txt$")
GELS_MAX = 20
GELS = "~/.local/share/freeze-jeu"
UNITES_BINAIRES = {"b": 1, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def _home(home):
    return Path(home) if home is not None else Path.home()


def _chemins(home, modeles):
    return [_home(home) / m[2:] for m in modeles]


def _iso(secondes):
    """Une date en heure locale (ISO, à la seconde) ; None si elle n'existe pas ou est absurde."""
    try:
        return datetime.fromtimestamp(int(secondes)).isoformat(timespec="seconds") if secondes else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _jeu(bibliotheque, cle, titre, type_, octets, derniere_partie, chemin):
    return {"id": f"{bibliotheque}:{cle}", "titre": titre, "bibliotheque": bibliotheque, "type": type_,
            "octets": octets, "taille": commun.taille(octets) if octets is not None else INCONNUE,
            "derniere_partie": derniere_partie, "chemin": str(chemin) if chemin is not None else None}


def _bibliotheque(id_, type_, nom, chemin, absente, liste):
    octets = sum(j["octets"] or 0 for j in liste)
    return {"id": id_, "type": type_, "nom": nom, "chemin": str(chemin) if chemin is not None else None,
            "absente": absente, "nombre": len(liste), "octets": octets, "taille": commun.taille(octets)}


# --- Steam ---

def nom_steam(chemin, volumes):
    """« Steam (<volume>) » : le volume dont le chemin est le plus long préfixe (par composants) de `chemin`, sinon
    « Steam (<chemin>) ». Le volume /var ne compte pas pour /var/mnt et /run/media : un disque qu'on n'a pas nommé ne
    s'appelle pas « Système »."""
    parts = Path(chemin).parts
    disque_monte = parts[:3] in (("/", "var", "mnt"), ("/", "run", "media"))
    meilleur = None
    for v in volumes:
        vp = Path(v.chemin).parts
        if parts[:len(vp)] != vp or (disque_monte and v.chemin == "/var"):
            continue
        if meilleur is None or len(vp) > len(Path(meilleur.chemin).parts):
            meilleur = v
    return f"Steam ({meilleur.nom if meilleur else chemin})"


def steam(bibliotheques, volumes):
    """Les bibliothèques Steam présentes et leurs jeux (les outils de Steam n'en sont pas)."""
    bibs, liste = [], []
    for chemin in bibliotheques:
        id_ = f"steam:{chemin}"
        jeux_bib = [_jeu(id_, m["appid"], m["nom"], "steam", m["octets"], _iso(m["derniere_partie"]),
                         Path(chemin) / "steamapps" / "common" / m["installdir"])
                    for m in steam_.manifestes(chemin) if not m["outil"]]
        bibs.append(_bibliotheque(id_, "steam", nom_steam(chemin, volumes), chemin, False, jeux_bib))
        liste += jeux_bib
    return bibs, liste


# --- Heroic ---

def taille_heroic(texte):
    """Octets d'une taille de Heroic (« 7.01 GiB », unités binaires), sinon d'une taille décimale (« 1.5 GB ») ;
    None si elle est illisible."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([A-Za-z]+)\s*", str(texte or ""))
    facteur = UNITES_BINAIRES.get(m.group(2).lower()) if m else None
    if facteur is None:
        return commun.lire_taille(texte)
    return round(float(m.group(1).replace(",", ".")) * facteur)


def _signaler(erreurs, source, exc):
    """Note « <source> : illisible (<type d'exception>) » dans `erreurs` (une liste, ou None : rien n'est noté)."""
    phrase = f"{source} : illisible ({type(exc).__name__})"
    if erreurs is not None and phrase not in erreurs:
        erreurs.append(phrase)


def _json(chemin, erreurs=None, source=None):
    """Le contenu JSON d'un fichier ; None s'il est absent, ou illisible (noté dans `erreurs` si `source` est donné)."""
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        if source:
            _signaler(erreurs, source, exc)
        return None


def _heure_locale_utc(texte):
    try:
        return datetime.fromisoformat(str(texte).replace("Z", "+00:00")).astimezone() \
            .replace(tzinfo=None).isoformat(timespec="seconds")
    except (ValueError, OverflowError):
        return None


def heroic(home=None, erreurs=None):
    """Les jeux Heroic installés (is_installed, avec un dossier, hors DLC), une bibliothèque par boutique qui en a au
    moins un. Un fichier illisible est noté dans `erreurs` (« Heroic : illisible (JSONDecodeError) »)."""
    par_boutique, vus = {}, set()
    for racine in _chemins(home, HEROIC):
        parties = _json(racine / "store" / "timestamp.json", erreurs, "Heroic")
        parties = parties if isinstance(parties, dict) else {}
        for fichier in sorted((racine / "store_cache").glob("*librar*.json")):
            donnees = _json(fichier, erreurs, "Heroic")
            liste = donnees.get("library") or donnees.get("games") if isinstance(donnees, dict) else donnees
            m = re.match(r"(\w+?)[_-]librar", fichier.name)
            for g in liste if isinstance(liste, list) else ():
                install = g.get("install") if isinstance(g, dict) else None
                if not isinstance(install, dict) or not g.get("is_installed") or install.get("is_dlc") \
                        or not install.get("install_path") or not isinstance(g.get("app_name"), str):
                    continue
                boutique = g.get("runner") or (m.group(1) if m else "heroic")
                if (boutique, g["app_name"]) in vus:
                    continue
                vus.add((boutique, g["app_name"]))
                id_ = f"heroic:{boutique}"
                partie = parties.get(g["app_name"])
                partie = _heure_locale_utc(partie.get("lastPlayed")) if isinstance(partie, dict) else None
                par_boutique.setdefault(boutique, []).append(_jeu(
                    id_, g["app_name"], g.get("title") or g["app_name"], "heroic",
                    taille_heroic(install.get("install_size")), partie, install["install_path"]))
    bibs = [_bibliotheque(f"heroic:{b}", "heroic", f"Heroic ({BOUTIQUES.get(b, b)})", None, False, liste)
            for b, liste in sorted(par_boutique.items())]
    return bibs, [j for liste in par_boutique.values() for j in liste]


# --- Lutris ---

def lutris(home=None, erreurs=None):
    """Les jeux installés des bases pga.db de Lutris (ouvertes en lecture seule), dans une seule bibliothèque. La taille
    est celle du dossier du jeu, inconnue sans dossier. Une base illisible est notée dans `erreurs`."""
    liste, vus, lue = [], set(), False
    for base in _chemins(home, LUTRIS):
        if not base.is_file():
            continue
        try:
            connexion = sqlite3.connect(f"file:{quote(str(base))}?mode=ro", uri=True)
            try:
                lignes = connexion.execute(
                    "select name, directory, lastplayed from games where installed = 1 order by id").fetchall()
            finally:
                connexion.close()
        except sqlite3.Error as exc:
            _signaler(erreurs, "Lutris", exc)
            continue
        lue = True
        for nom, dossier, partie in lignes:
            if not isinstance(nom, str) or (nom, dossier) in vus:
                continue
            vus.add((nom, dossier))
            existe = isinstance(dossier, str) and dossier and Path(dossier).is_dir()
            liste.append(_jeu("lutris", f"{nom}:{dossier}", nom, "lutris",
                              sante.taille_dossier(dossier) if existe else None, _iso(partie),
                              dossier if isinstance(dossier, str) and dossier else None))
    return ([_bibliotheque("lutris", "lutris", "Lutris", None, False, liste)] if lue else []), liste


# --- Émulateurs ---

def lire_sfo(octets):
    """Les entrées d'un param.sfo (format PSF) : {clé: texte ou entier}. Invalide ou coupé : {}."""
    try:
        magie, _version, debut_cles, debut_donnees, nombre = struct.unpack_from("<4sIIII", octets)
        if magie != b"\0PSF":
            return {}
        res = {}
        for i in range(nombre):
            decalage, format_, longueur, _max, donnees = struct.unpack_from("<HHIII", octets, 20 + 16 * i)
            fin_cle = octets.index(b"\0", debut_cles + decalage)
            cle = octets[debut_cles + decalage:fin_cle].decode("utf-8")
            brut = octets[debut_donnees + donnees:debut_donnees + donnees + longueur]
            if len(brut) < longueur:
                return {}
            if format_ == 0x0204:
                res[cle] = brut.split(b"\0", 1)[0].decode("utf-8")
            elif format_ == 0x0404 and longueur == 4:
                res[cle] = struct.unpack("<I", brut)[0]
        return res
    except (struct.error, ValueError):
        return {}


def titre_emulateur(chemin):
    """Le titre d'un jeu d'émulateur : sce_sys/param.json (français, sinon la langue par défaut, sinon titleName), puis
    sce_sys/param.sfo (TITLE), sinon le nom nettoyé (sans extension, sans [balises] ni (parenthèses))."""
    chemin = Path(chemin)
    param = _json(chemin / "sce_sys" / "param.json") if chemin.is_dir() else None
    if isinstance(param, dict):
        langues = param.get("localizedParameters")
        langues = langues if isinstance(langues, dict) else {}
        for langue in ("fr-FR", langues.get("defaultLanguage")):
            bloc = langues.get(langue) if isinstance(langue, str) else None
            if isinstance(bloc, dict) and isinstance(bloc.get("titleName"), str) and bloc["titleName"].strip():
                return bloc["titleName"].strip()
        if isinstance(param.get("titleName"), str) and param["titleName"].strip():
            return param["titleName"].strip()
    if chemin.is_dir():
        try:
            titre = lire_sfo((chemin / "sce_sys" / "param.sfo").read_bytes()).get("TITLE")
        except OSError:
            titre = None
        if isinstance(titre, str) and titre.strip():
            return titre.strip()
    nom = chemin.name if chemin.is_dir() else chemin.stem
    propre = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", nom)).strip()
    return propre or chemin.name


def emulateurs(liste, erreurs=None):
    """Une bibliothèque par émulateur de la configuration ([{"nom", "dossier", "extensions"}]) : chaque entrée directe
    (ni cachée, ni lien) est un jeu ; un fichier seulement si son extension convient. Dossier absent : bibliothèque
    `absente`, sans jeu. Taille : le dossier (place occupée) ou le fichier (st_blocks)."""
    bibs, jeux_ = [], []
    for e in liste:
        id_ = f"emulateur:{e['nom']}"
        dossier = Path(e["dossier"])
        trouves = []
        try:
            entrees = sorted(dossier.iterdir(), key=lambda p: p.name) if dossier.is_dir() else []
        except OSError as exc:
            _signaler(erreurs, e["nom"], exc)
            entrees = []
        for p in entrees:
            if p.name.startswith(".") or p.is_symlink():
                continue
            if p.is_dir():
                octets = sante.taille_dossier(p)
            elif p.is_file():
                suffixe = p.suffix.lower()
                if suffixe not in e["extensions"] if e.get("extensions") else suffixe in IGNORES_EMULATEUR:
                    continue
                try:
                    octets = p.lstat().st_blocks * 512
                except OSError:
                    continue
            else:
                continue
            trouves.append(_jeu(id_, p.name, titre_emulateur(p), "emulateur", octets, None, p))
        bibs.append(_bibliotheque(id_, "emulateur", e["nom"], dossier, not dossier.is_dir(), trouves))
        jeux_ += trouves
    return bibs, jeux_


# --- Doublons ---

def cle_titre(titre):
    """Le titre comparable : sans ™®© ni [balises] ni (parenthèses), sans accents ni majuscules, les suites de lettres
    et de chiffres séparées par une espace."""
    texte = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", str(titre or "").replace("\u2122", "").replace("\u00ae", "")
                   .replace("\u00a9", ""))
    texte = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", texte.casefold()))


def doublons(liste):
    """Les titres présents dans au moins deux bibliothèques différentes. `en_trop` : le total moins la plus grosse copie
    (une taille inconnue compte 0). Du plus gros `en_trop` au plus petit."""
    groupes = {}
    for j in liste:
        cle = cle_titre(j["titre"])
        if cle:
            groupes.setdefault(cle, []).append(j)
    res = []
    for copies in groupes.values():
        if len({j["bibliotheque"] for j in copies}) < 2:
            continue
        tailles = [j["octets"] or 0 for j in copies]
        en_trop = sum(tailles) - max(tailles)
        res.append({"titre": copies[0]["titre"], "jeux": [j["id"] for j in copies], "octets": sum(tailles),
                    "en_trop": en_trop, "taille_en_trop": commun.taille(en_trop)})
    return sorted(res, key=lambda d: (-d["en_trop"], d["titre"]))


# --- Préfixes Proton orphelins (jamais supprimés ici) ---

def _taille_entree(chemin):
    return sante.taille_dossier(chemin) if chemin.is_dir() else chemin.lstat().st_blocks * 512


def prefixes(bibliotheques, installes, noms):
    """Les entrées de steamapps/compatdata dont l'appid n'est pas installé (ni liens), de la plus grosse à la plus
    petite. `noms` : {chemin de la bibliothèque (texte): nom affiché} ; sans nom, « Steam (<chemin>) ». Lecture seule :
    rien n'est supprimé."""
    elements = []
    for bib in bibliotheques:
        compat = Path(bib) / "steamapps" / "compatdata"
        try:
            entrees = sorted(compat.iterdir(), key=lambda p: p.name) if compat.is_dir() else []
        except OSError:
            continue
        for p in entrees:
            if p.is_symlink() or p.name in installes:
                continue
            if re.fullmatch(r"\d+", p.name):
                if int(p.name) >= steam_.APPID_MAX:
                    nature, libelle = "non_steam", f"Raccourci non-Steam {p.name}"
                else:
                    nature, libelle = "desinstalle", f"Jeu Steam {p.name} (désinstallé)"
            else:
                nature, libelle = "inhabituel", f"{p.name} (nom inhabituel : copie ou sauvegarde ?)"
            try:
                octets = _taille_entree(p)
            except OSError:
                continue
            elements.append({"cible": str(p), "libelle": libelle, "nature": nature,
                             "bibliotheque": noms.get(str(bib), f"Steam ({bib})"), "octets": octets,
                             "taille": commun.taille(octets)})
    elements.sort(key=lambda e: -e["octets"])
    total = sum(e["octets"] for e in elements)
    return {"elements": elements, "octets": total, "taille": commun.taille(total)}


# --- Gels (captures de freeze-watch et freeze-jeu) ---

def _gel(chemin, m):
    try:
        date = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").isoformat(timespec="seconds")
        octets = chemin.stat().st_size
    except (ValueError, OSError):
        return None
    automatique, declencheur = bool(m.group(3)), None
    if automatique:
        try:
            with open(chemin, encoding="utf-8", errors="replace") as f:
                for _ in range(5):
                    ligne = f.readline()
                    if ligne.startswith("### Declencheur :"):
                        declencheur = ligne.split(":", 1)[1].strip() or None
                        break
        except OSError:
            pass
    return {"fichier": str(chemin), "date": date, "jeu": re.sub(r"\.(exe|ex|e)$", "", m.group(4), flags=re.I),
            "automatique": automatique, "declencheur": declencheur, "octets": octets, "taille": commun.taille(octets)}


def gels(dossier=None, *, limite=GELS_MAX, home=None):
    """Les captures de gel du dossier (par défaut celui de `home`), seulement les fichiers au nom attendu
    (AAAAMMJJ-HHMMSS-[GEL-]jeu.txt), de la plus récente à la plus ancienne. `nombre` et `automatiques` comptent tout ;
    `liste` garde les `limite` plus récentes."""
    dossier = Path(dossier) if dossier is not None else _home(home) / GELS[2:]
    try:
        noms = sorted((p for p in dossier.iterdir() if p.is_file() and menage._lisible(p.name)),
                      key=lambda p: p.name, reverse=True)
    except OSError:
        noms = []
    trouves = [(p, MOTIF_GEL.match(p.name)) for p in noms]
    toutes = [g for g in (_gel(p, m) for p, m in trouves if m) if g]
    toutes.sort(key=lambda g: g["date"], reverse=True)
    return {"dossier": str(dossier), "nombre": len(toutes), "automatiques": sum(g["automatique"] for g in toutes),
            "dernier": toutes[0]["date"] if toutes else None, "liste": toutes[:limite]}


# --- jeux.json ---

def fichier(dossier=None):
    return Path(dossier or commun.ETAT) / "jeux.json"


# W5 : la liste des jeux installés n'est pas certaine (un libraryfolders.vdf illisible) ; JeuxMenage.qml vise cette
# phrase exacte (copie testée).
STEAM_NON_VERIFIABLE = "Steam : illisible (bibliothèques non vérifiables)"
_ECHEC = object()           # une source qui a levé : son erreur est déjà notée


def _lisible(j):
    return all(menage._lisible(j.get(c)) for c in ("id", "titre", "chemin", "cible", "libelle", "nom") if j.get(c))


def construire(*, home=None, reglages=config.jeux, volumes=config.volumes, gels_dossier=None):
    """Tout jeux.json : les bibliothèques et leurs jeux, les doublons, les préfixes orphelins et les gels. Chaque source
    est protégée : une qui échoue devient une phrase de `erreurs` et les autres restent. Un jeu ou un préfixe dont le
    nom n'est pas de l'UTF-8 est écarté (jeux.json devra l'écrire)."""
    erreurs, bibs, liste = [], [], []

    def source(nom, calcul, defaut):
        try:
            return calcul()
        except Exception as exc:
            _signaler(erreurs, nom, exc)
            return defaut

    def ajouter(resultat):
        bibs.extend(b for b in resultat[0] if _lisible(b))
        liste.extend(j for j in resultat[1] if _lisible(j))

    options = source("Configuration", reglages, {"steam": [], "emulateurs": []})
    liste_volumes = source("Volumes", volumes, [])
    presentes = source("Steam", lambda: steam_.bibliotheques(home, en_plus=options["steam"]), ([], []))
    noms = {str(b): nom_steam(b, liste_volumes) for b in presentes[0]}
    ajouter(source("Steam", lambda: steam(presentes[0], liste_volumes), ([], [])))
    for chemin in presentes[1]:
        bibs.append(_bibliotheque(f"steam:{chemin}", "steam", nom_steam(Path(chemin), liste_volumes), chemin, True, []))
    ajouter(source("Heroic", lambda: heroic(home, erreurs), ([], [])))
    ajouter(source("Lutris", lambda: lutris(home, erreurs), ([], [])))
    for e in options["emulateurs"]:
        ajouter(source(e["nom"], lambda: emulateurs([e], erreurs), ([], [])))
    aucun = {"elements": [], "octets": 0, "taille": commun.taille(0)}
    installes = source("Préfixes", lambda: steam_.appids_installes(
        presentes[0], home=home if home is not None else Path.home()), _ECHEC)
    if installes is None:                   # bibliothèques non vérifiables : aucun préfixe n'est déclaré orphelin
        erreurs.append(STEAM_NON_VERIFIABLE)
    # RF-m6 : une exception est déjà notée (« Préfixes : illisible ») ; seul None dit que les bibliothèques ne se
    # vérifient pas.
    orphelins = aucun if installes is None or installes is _ECHEC \
        else source("Préfixes", lambda: prefixes(presentes[0], installes, noms), aucun)
    for b in bibs:                  # les comptes suivent les jeux gardés
        gardes = [j for j in liste if j["bibliotheque"] == b["id"]]
        octets = sum(j["octets"] or 0 for j in gardes)
        b.update(nombre=len(gardes), octets=octets, taille=commun.taille(octets))
    elements = [e for e in orphelins["elements"] if _lisible(e)]
    total = sum(e["octets"] for e in elements)
    return {"genere": commun.maintenant(), "bibliotheques": bibs, "jeux": liste, "doublons": doublons(liste),
            "prefixes": {"elements": elements, "octets": total, "taille": commun.taille(total)},
            "gels": source("Gels", lambda: gels(gels_dossier, home=home),
                           {"dossier": "", "nombre": 0, "automatiques": 0, "dernier": None, "liste": []}),
            "erreurs": erreurs}


def ecrire(dossier=None, **sources):
    chemin = fichier(dossier)
    commun.ecrire_json(chemin, construire(**sources))
    return chemin
