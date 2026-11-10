"""Stockage : les disques physiques et leurs volumes (lsblk + espace libre), avec le résumé en cache de la dernière
analyse de chaque volume (LinStat) et les recommandations de ménage, écrits dans stockage.json.
Ne fait que lire (lsblk, statvfs, caches, listes de la corbeille et de Flatpak) : rien n'est monté, déplacé ni
supprimé ici ; le ménage lui-même passe par `centre-bazzite menage <id>`, après confirmation."""
import functools
import json
import shutil
from pathlib import Path

from . import analyse, commun, menage, optimiser as moteur_optimiser, sante

COLONNES_LSBLK = "NAME,TYPE,START,SIZE,FSTYPE,LABEL,MOUNTPOINTS,TRAN,MODEL,RM"
GIO = 1024 ** 3
GROSSE_PARTITION = 2 * GIO              # en dessous, une partition ne compte pas pour la position (EFI, /boot…)
SEUIL_ROUGE = 0.05                      # moins de 5 % libres : le volume est en échec (règle de référence)
IGNORES = frozenset({"/boot", "/boot/efi", "[SWAP]"})
DOSSIERS_EXTERNES = ("/var/mnt/", "/run/media/")
TRANSPORTS = {"nvme": "NVMe", "sata": "SATA", "ata": "SATA", "usb": "USB"}


def fichier(dossier=None):
    return Path(dossier or commun.ETAT) / "stockage.json"


def _lsblk():
    code, sortie = commun.run(["lsblk", "-J", "-b", "-o", COLONNES_LSBLK])
    if code != 0:
        raise RuntimeError(sortie.strip())
    return sortie


def _montages(noeud):
    """Les montages de la partition et de tous ses descendants (volume chiffré, LVM…)."""
    res = [m for m in noeud.get("mountpoints") or [] if m]
    for enfant in noeud.get("children") or []:
        res += _montages(enfant)
    return res


def lire_lsblk(json_texte):
    """Les disques de type `disk` (zram et loop exclus) avec leurs partitions."""
    res = []
    for d in json.loads(json_texte).get("blockdevices") or []:
        if d.get("type") != "disk" or str(d.get("name", "")).startswith(("zram", "loop")):
            continue
        res.append({"nom": d["name"], "taille": d.get("size") or 0, "transport": d.get("tran"),
                    "modele": (d.get("model") or "").strip(), "amovible": bool(d.get("rm")),
                    "partitions": [{"nom": p["name"], "debut": p.get("start") or 0, "taille": p.get("size") or 0,
                                    "fs": p.get("fstype"), "label": p.get("label"), "montages": _montages(p)}
                                   for p in d.get("children") or []]})
    return res


def _chemin_du_volume(montages, noms):
    """Le montage qui désigne le volume : un volume connu (`noms`, ceux de la configuration), sinon un dossier de
    montage d'un disque ajouté."""
    for m in montages:
        if m in noms:
            return m
    return next((m for m in montages if m.startswith(DOSSIERS_EXTERNES) and m not in IGNORES), None)


def _nom_du_volume(chemin, label, noms):
    return noms.get(chemin) or label or Path(chemin).name


def _etat(libre_go, total_go, chemin, alertes):
    """Règle de référence de la jauge (copiée dans AccueilPage.qml, etatVolume) : « echec » sous 5 % libres,
    « attention » si le point volume:<chemin> est actif, sinon « ok »."""
    if total_go > 0 and libre_go / total_go < SEUIL_ROUGE:
        return "echec"
    return "attention" if f"volume:{chemin}" in alertes else "ok"


def _position(partition, grosses):
    """Place sur le disque : première, dernière ou entre les deux (None s'il n'y a pas de quoi comparer)."""
    if len(grosses) < 2 or partition not in grosses:
        return None
    rang = grosses.index(partition)
    return "debut" if rang == 0 else "fin" if rang == len(grosses) - 1 else "milieu"


def _to(octets):
    """Taille d'un disque en To décimaux (le fabricant compte en 10^12) : « 2 », « 0,5 »."""
    to = round(octets / 1e12, 1)
    return (f"{to:.1f}".rstrip("0").rstrip(".") if to else "0").replace(".", ",")


def _titre(disque, interne):
    if interne:
        transport = TRANSPORTS.get(str(disque["transport"]).lower(), str(disque["transport"] or "").upper())
        precision = f"{transport} {_to(disque['taille'])} To" if transport else f"{_to(disque['taille'])} To"
        return f"Disque interne ({precision})"
    return "Disque externe (SSD USB)" if "SSD" in disque["modele"].upper() else "Disque externe (USB)"


def disques(lsblk, volumes, *, alertes=frozenset(), mesurer=shutil.disk_usage):
    """Un disque par disque physique qui a au moins un volume monté. `volumes` : les volumes déjà mesurés par la
    santé ; un volume qui n'y figure pas (clé USB, disque ajouté) est mesuré avec `mesurer`."""
    mesures = {v["chemin"]: v for v in volumes}
    noms = {chemin: nom for nom, chemin in sante.volumes_suivis()}
    res = []
    for d in lsblk:
        grosses = sorted((p for p in d["partitions"] if p["taille"] >= GROSSE_PARTITION), key=lambda p: p["debut"])
        liste = []
        for p in sorted(d["partitions"], key=lambda p: p["debut"]):
            chemin = _chemin_du_volume(p["montages"], noms)
            if chemin is None:
                continue
            nom = _nom_du_volume(chemin, p["label"], noms)
            m = mesures.get(chemin) or sante.espace(nom, chemin, mesurer(chemin))
            liste.append({"nom": nom, "chemin": chemin, "fs": p["fs"], "libre_go": m["libre_go"],
                          "total_go": m["total_go"], "pourcent_utilise": m["pourcent_utilise"],
                          "position": _position(p, grosses),
                          "etat": _etat(m["libre_go"], m["total_go"], chemin, alertes)})
        if liste:
            interne = d["transport"] != "usb" and not d["amovible"]
            res.append({"id": d["nom"], "titre": _titre(d, interne), "modele": d["modele"],
                        "interne": interne, "volumes": liste})
    res.sort(key=lambda x: not x["interne"])         # les disques internes d'abord (tri stable)
    return res


def _alertes(etat):
    """Les points de volume actifs (hors sourdine) de etat.json."""
    return frozenset(p["id"] for p in (etat or {}).get("points") or []
                     if isinstance(p, dict) and str(p.get("id")).startswith("volume:") and not p.get("en_sourdine"))


def construire(dossier=None, *, lsblk=_lsblk, volumes=sante.volumes, etat=None, analyses=None,
               linstat=analyse.etat_linstat, recommandations=None, optimiser=moteur_optimiser.construire):
    """Chaque source est injectable : `lsblk()` rend le JSON de lsblk, `volumes()` les volumes mesurés,
    `etat` le contenu d'etat.json, `analyses(chemin)` le résumé en cache d'un volume (ou None), `linstat()`
    l'état de LinStat, `recommandations()` les recommandations de ménage, `optimiser(disques)` les options « Optimiser mes disques ». etat.json, controles.json et les
    résumés sont lus dans `dossier` (par défaut le dossier d'état)."""
    if etat is None:
        etat = commun.lire_json(Path(dossier or commun.ETAT) / "etat.json", {})
    if analyses is None:
        analyses = functools.partial(analyse.lire_analyse, dossier=dossier)
    if recommandations is None:
        controles = sante.lire_controles(Path(dossier or commun.ETAT) / "controles.json") or {}
        recommandations = functools.partial(menage.recommandations, controles=controles)
    liste = disques(lire_lsblk(lsblk()), volumes(), alertes=_alertes(etat))
    return {"genere": commun.maintenant(), "disques": liste, "linstat": linstat(),
            "analyses": {v["chemin"]: analyses(v["chemin"]) for d in liste for v in d["volumes"]},
            "recommandations": recommandations(), "optimiser": optimiser(liste)}


def ecrire(dossier=None, **sources):
    chemin = fichier(dossier)
    commun.ecrire_json(chemin, construire(dossier, **sources))
    return chemin
