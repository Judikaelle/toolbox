"""Configuration locale de Health Hub : ce qui est propre à un PC (volumes suivis, AppImages et conteneurs distrobox de
maj-apps, textes d'« Optimiser mes disques », contexte du résumé des notes de version). Elle vit dans
~/.config/health-hub/config.toml, jamais dans le dépôt ; config.exemple.toml en documente chaque clé.

Le fichier est relu à chaque appel (`chemin=None` : CHEMIN). Absent, ce sont les valeurs neutres ci-dessous ; illisible
(TOML invalide, pas de l'UTF-8, droits), aussi, avec un avertissement sur stderr ; une entrée mal formée est ignorée
avec un avertissement, les autres restent. Rien ici ne lève jamais d'exception."""
import os
import sys
import tomllib
from collections import namedtuple
from pathlib import Path

CHEMIN = Path.home() / ".config" / "health-hub" / "config.toml"

# attendu : doit être monté (sinon le point « non monté ») ; facultatif : peut être débranché sans rien signaler
# (l'emporte sur attendu).
Volume = namedtuple("Volume", "nom chemin attendu facultatif")
VOLUMES_PAR_DEFAUT = (Volume("Système", "/var", False, False), Volume("Home", "/var/home", False, False))
CONTEXTE_PAR_DEFAUT = "l'utilisateur, sous Bazzite (KDE Plasma, Wayland)"


def _avertir(message):
    print(f"Health Hub, configuration : {message}", file=sys.stderr)


def lire(chemin=None):
    """Le contenu du fichier (dict) ; {} s'il est absent, ou illisible (avec un avertissement)."""
    chemin = Path(chemin) if chemin is not None else CHEMIN
    try:
        with open(chemin, "rb") as fichier:
            return tomllib.load(fichier)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:     # TOMLDecodeError et UnicodeDecodeError sont des ValueError
        _avertir(f"{chemin} illisible, valeurs par défaut : {exc}")
        return {}


def _section(donnees, *cles):
    """donnees[cle1][cle2]… s'il s'agit bien de tables ; sinon {} (avec un avertissement si la clé existe)."""
    for cle in cles:
        valeur = donnees.get(cle, {}) if isinstance(donnees, dict) else {}
        if not isinstance(valeur, dict):
            _avertir(f"« {cle} » ignoré : une table était attendue")
            return {}
        donnees = valeur
    return donnees


def _liste(donnees, cle):
    valeur = donnees.get(cle, [])
    if not isinstance(valeur, list):
        _avertir(f"« {cle} » ignoré : une liste était attendue")
        return []
    return valeur


def _texte(table, cle, defaut=""):
    valeur = table.get(cle)
    return valeur if isinstance(valeur, str) and valeur.strip() else defaut


def _chemin_utilisateur(texte):
    """« ~/x » et « x » (relatif) désignent ~/x ; un chemin absolu reste tel quel."""
    p = Path(os.path.expanduser(texte))
    return p if p.is_absolute() else Path.home() / p


def volumes(chemin=None):
    """Les volumes suivis : Système (/var) et Home (/var/home), puis ceux de [[volumes]] dans leur ordre. Une entrée qui a
    le chemin d'un volume par défaut le remplace à sa place (son nom, ses drapeaux)."""
    liste = list(VOLUMES_PAR_DEFAUT)
    for e in _liste(lire(chemin), "volumes"):
        if not isinstance(e, dict) or not isinstance(e.get("chemin"), str) or not e["chemin"].startswith("/"):
            _avertir(f"volume ignoré (il faut un chemin absolu) : {e!r}")
            continue
        chemin_v = os.path.normpath(e["chemin"])
        v = Volume(_texte(e, "nom", Path(chemin_v).name or chemin_v), chemin_v,
                   e.get("attendu") is True, e.get("facultatif") is True)
        place = next((i for i, x in enumerate(liste) if x.chemin == chemin_v), None)
        if place is None:
            liste.append(v)
        else:
            liste[place] = v
    return liste


def appimages(chemin=None):
    """Les AppImages suivies par maj-apps ([[majapps.appimages]]) : clé (nom dans l'état), nom affiché, dépôt GitHub,
    motif (expression régulière) du fichier de la release, dossier, fichier installé (nom fixe `fichier`, ou glob
    `motif_fichier`), fichiers .desktop dont les lignes Exec pointent vers l'AppImage. Aucune par défaut."""
    res = []
    for e in _liste(_section(lire(chemin), "majapps"), "appimages"):
        fichier = (e.get("motif_fichier") or e.get("fichier")) if isinstance(e, dict) else None
        desktop = e.get("desktop", []) if isinstance(e, dict) else None
        if not isinstance(e, dict) or not all(isinstance(e.get(c), str) and e[c]
                                              for c in ("cle", "depot", "motif_asset", "dossier")) \
                or not isinstance(fichier, str) or not fichier or not isinstance(desktop, list) \
                or not all(isinstance(d, str) for d in desktop):
            _avertir(f"AppImage ignorée (il faut cle, depot, motif_asset, dossier et fichier ou motif_fichier) : {e!r}")
            continue
        res.append({"cle": e["cle"], "nom": _texte(e, "nom", e["cle"]), "depot": e["depot"],
                    "motif_asset": e["motif_asset"], "dossier": _chemin_utilisateur(e["dossier"]),
                    "fichier": fichier, "desktop": [_chemin_utilisateur(d) for d in desktop]})
    return res


def distrobox_exclus(chemin=None):
    """{conteneur: raison} : les conteneurs que maj-apps ne met jamais à jour. Aucun par défaut."""
    res = {}
    for nom, raison in _section(lire(chemin), "majapps", "distrobox", "exclure").items():
        if isinstance(raison, str):
            res[nom] = raison
        else:
            _avertir(f"conteneur exclu ignoré (il faut une raison écrite) : {nom}")
    return res


def distrobox_applis(chemin=None):
    """{conteneur: (processus, nom affiché)} : les conteneurs dont la mise à jour attend que leur appli soit fermée."""
    res = {}
    for nom, appli in _section(lire(chemin), "majapps", "distrobox", "applis").items():
        if isinstance(appli, list) and len(appli) == 2 and all(isinstance(x, str) and x for x in appli):
            res[nom] = tuple(appli)
        else:
            _avertir(f"appli de conteneur ignorée (il faut [\"processus\", \"Nom affiché\"]) : {nom}")
    return res


def optimiser(chemin=None):
    """Les réglages d'« Optimiser mes disques » : `liberer` (option B : {"volume", "phrase", "conseil"} ou None),
    `fusionner` (option D : deux noms de volumes ou None), `idee` ("" par défaut) et `recommandation` (None : celle que
    Health Hub écrit d'après les options présentes)."""
    o = _section(lire(chemin), "optimiser")
    liberer = o.get("liberer")
    if liberer is not None and not (isinstance(liberer, dict) and _texte(liberer, "volume")):
        _avertir("optimiser.liberer ignoré : il faut au moins « volume »")
        liberer = None
    fusionner = o.get("fusionner")
    if fusionner is not None and not (isinstance(fusionner, list) and len(fusionner) == 2
                                      and all(isinstance(x, str) and x for x in fusionner)):
        _avertir("optimiser.fusionner ignoré : il faut deux noms de volumes")
        fusionner = None
    return {"liberer": {"volume": liberer["volume"], "phrase": _texte(liberer, "phrase"),
                        "conseil": _texte(liberer, "conseil", None)} if liberer else None,
            "fusionner": tuple(fusionner) if fusionner else None,
            "idee": _texte(o, "idee"), "recommandation": _texte(o, "recommandation", None)}


def contexte_resume(chemin=None):
    """Qui lit les résumés des notes de version, tel que le modèle Ollama le lit : « Tu résumes … pour <contexte>. »"""
    return _texte(_section(lire(chemin), "resume"), "contexte", CONTEXTE_PAR_DEFAUT)
