"""Relevés de versions (Flatpak, brew, paquets clés, image) et différences entre deux relevés."""
from datetime import datetime, timedelta
from pathlib import Path

from . import commun, rpmostree

ETAT = commun.ETAT
BREW = "/home/linuxbrew/.linuxbrew/bin/brew"
PAQUETS_SYSTEME = {"kernel": "Noyau", "nvidia-driver": "Pilote NVIDIA",
                   "plasma-workspace": "Plasma", "mesa-dri-drivers": "Mesa"}
# Conservation : tout ce qui a moins de 48 h, puis un relevé par jour (le dernier) pendant 60 jours,
# et jamais le relevé de référence de la dernière visite (visites.json "releve").
GARDER_TOUT = timedelta(hours=48)
GARDER_UN_PAR_JOUR = timedelta(days=60)


def lire_flatpak(texte):
    """application, version, branche, installation (séparés par des tabulations)."""
    res = {}
    for ligne in texte.splitlines():
        champs = ligne.split("\t")
        if not champs[0].strip():
            continue
        version = champs[1].strip() if len(champs) > 1 else ""
        branche = champs[2].strip() if len(champs) > 2 else ""
        res[champs[0].strip()] = version or branche
    return res


def lire_brew(texte):
    res = {}
    for ligne in texte.splitlines():
        mots = ligne.split()
        if len(mots) >= 2:
            res[mots[0]] = mots[-1]
    return res


def lire_rpm(texte):
    res = {}
    for ligne in texte.splitlines():
        mots = ligne.split()
        if len(mots) == 2:
            res.setdefault(mots[0], mots[1])
    return res


def _source(cmd, lire, tolerer_echec=False):
    """Versions lues par `lire`, ou None si la commande a échoué : une source illisible ne doit pas
    faire croire que tout a été retiré (puis réinstallé au relevé suivant)."""
    code, texte = commun.run(cmd)
    if code != 0 and not tolerer_echec:
        return None
    lu = lire(texte)
    return lu if lu or code == 0 else None


def relever():
    courant = rpmostree.etat_deploiements().get("courant")
    return {
        "date": commun.maintenant(),
        "image": courant.get("version") if courant else None,
        # rpm -q sort en erreur s'il manque un des paquets : les autres restent valables.
        "paquets": _source(["rpm", "-q", "--qf", "%{NAME} %{VERSION}\\n", *PAQUETS_SYSTEME], lire_rpm,
                           tolerer_echec=True),
        "flatpak": _source(["flatpak", "list", "--app", "--columns=application,version,branch,installation"],
                           lire_flatpak),
        "brew": _source([BREW, "list", "--versions"], lire_brew),
    }


def _dossier():
    return Path(ETAT) / "releves"


def _date(texte):
    try:
        return datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def _reference():
    visites = commun.lire_json(Path(ETAT) / "visites.json", {})
    return visites.get("releve") if isinstance(visites, dict) else None


def _elaguer(maintenant):
    reference, du_jour, retirer = _reference(), {}, []
    for f in sorted(_dossier().glob("*.json")):
        d = _date(f.stem)
        if d is None or f.stem == reference or maintenant - d <= GARDER_TOUT:
            continue
        if maintenant - d <= GARDER_UN_PAR_JOUR:
            if d.date() in du_jour:
                retirer.append(du_jour[d.date()])
            du_jour[d.date()] = f           # liste triée : le plus récent du jour reste
        else:
            retirer.append(f)
    for f in retirer:
        f.unlink(missing_ok=True)


def enregistrer(releve):
    chemin = _dossier() / f"{releve['date']}.json"
    commun.ecrire_json(chemin, releve)
    _elaguer(_date(releve["date"]) or datetime.now())
    return chemin


def releve_du(date_iso):
    """Le relevé enregistré à cette date exacte (référence d'une visite), ou None."""
    if not date_iso:
        return None
    r = commun.lire_json(_dossier() / f"{date_iso}.json", None)
    return r if isinstance(r, dict) and r.get("date") else None


def _releves():
    """Tous les relevés lisibles, du plus ancien au plus récent."""
    res = []
    for f in sorted(_dossier().glob("*.json")):
        r = commun.lire_json(f, None)
        if isinstance(r, dict) and r.get("date"):
            res.append(r)
    return res


def releve_avant(date_iso):
    candidats = [r for r in _releves() if r["date"] <= date_iso]
    return candidats[-1] if candidats else None


def plus_ancien_releve():
    tous = _releves()
    return tous[0] if tous else None


def dernier_releve():
    tous = _releves()
    return tous[-1] if tous else None


def _comparer(categorie, avant, apres, noms=None):
    noms = noms or {}
    for cle in sorted(set(avant) | set(apres)):
        de, vers = avant.get(cle), apres.get(cle)
        if de != vers:
            yield {"categorie": categorie, "id": cle, "nom": noms.get(cle, cle),
                   "de": de, "vers": vers}


def differences(avant, apres):
    """Changements entre deux relevés ; une source absente (None) d'un côté n'est pas comparée."""
    res = []
    image_avant, image_apres = avant.get("image"), apres.get("image")
    if image_avant is not None and image_apres is not None and image_avant != image_apres:
        res.append({"categorie": "systeme", "id": "image", "nom": "Bazzite",
                    "de": image_avant, "vers": image_apres})
    for categorie, cle, noms in (("systeme", "paquets", PAQUETS_SYSTEME), ("applications", "flatpak", None),
                                 ("outils", "brew", None)):
        if avant.get(cle) is not None and apres.get(cle) is not None:
            res += _comparer(categorie, avant[cle], apres[cle], noms)
    return res
