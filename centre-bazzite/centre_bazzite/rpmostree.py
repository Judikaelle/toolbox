"""Lecture de rpm-ostree : déploiements (courant / en attente / précédent) et diff de paquets."""
import json
import re
from datetime import datetime

from centre_bazzite import commun

_SECTIONS = {"Upgraded:": "mis_a_jour", "Downgraded:": "mis_a_jour",
             "Added:": "ajoutes", "Removed:": "retires"}
_MAJ = re.compile(r"^\s+(\S+)\s+(\S+)\s+->\s+(\S+)\s*$")


def _version(dep):
    return {"version": dep.get("version", "")}


def lire_status(json_texte):
    """Renvoie {"courant", "en_attente", "precedent", "nombre", "epingles"} depuis `rpm-ostree status --json`.
    `epingles` : [{"position", "version"}], la position étant celle de `rpm-ostree status` (à partir de 0),
    celle qu'attend `ostree admin pin --unpin`."""
    deploiements = json.loads(json_texte).get("deployments", [])
    boote = next((d for d in deploiements if d.get("booted")), None)
    resultat = {"courant": None, "en_attente": None, "precedent": None, "nombre": len(deploiements),
                "epingles": [{"position": i, "version": d.get("version", "")}
                             for i, d in enumerate(deploiements) if d.get("pinned")]}
    if boote is None:
        return resultat
    ts = boote.get("timestamp")
    resultat["courant"] = {
        "version": boote.get("version", ""),
        "horodatage": datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None,
    }
    for d in deploiements:
        if d is boote:
            continue
        plus_recent = d.get("timestamp", 0) > (ts or 0)
        if d.get("staged") or plus_recent:
            if resultat["en_attente"] is None:
                resultat["en_attente"] = _version(d)
        elif resultat["precedent"] is None:
            resultat["precedent"] = _version(d)
    return resultat


def _deploiements_bruts():
    code, sortie = commun.run(["rpm-ostree", "status", "--json"], timeout=60)
    if code != 0:
        return None
    try:
        return json.loads(sortie).get("deployments", [])
    except ValueError:
        return None


def etat_deploiements():
    code, sortie = commun.run(["rpm-ostree", "status", "--json"], timeout=60)
    vide = {"courant": None, "en_attente": None, "precedent": None}
    if code != 0:
        return vide
    try:
        return lire_status(sortie)
    except ValueError:
        return vide


def lire_db_diff(texte):
    """Format bloc : sections Upgraded/Downgraded/Added/Removed, lignes `  nom de -> vers`."""
    resultat = {"mis_a_jour": [], "ajoutes": [], "retires": []}
    cle = None
    for ligne in texte.splitlines():
        if ligne.strip() in _SECTIONS and not ligne.startswith(" "):
            cle = _SECTIONS[ligne.strip()]
            continue
        if cle is None or not ligne.startswith(" ") or not ligne.strip():
            continue
        if cle == "mis_a_jour":
            m = _MAJ.match(ligne)
            if m:
                resultat[cle].append((m.group(1), m.group(2), m.group(3)))
        else:
            resultat[cle].append(ligne.strip())
    return resultat


def diff_en_attente():
    """Diff courant → en attente ; None s'il n'y a pas de déploiement en attente."""
    deploiements = _deploiements_bruts()
    if not deploiements:
        return None
    boote = next((d for d in deploiements if d.get("booted")), None)
    if boote is None:
        return None
    attente = next((d for d in deploiements if d is not boote and
                    (d.get("staged") or d.get("timestamp", 0) > boote.get("timestamp", 0))), None)
    if attente is None:
        return None
    cache = commun.CACHE / f"dbdiff-{boote['checksum'][:12]}-{attente['checksum'][:12]}.json"
    en_cache = commun.lire_json(cache, None)
    if en_cache is not None:
        en_cache["mis_a_jour"] = [tuple(x) for x in en_cache["mis_a_jour"]]
        return en_cache
    code, sortie = commun.run(["rpm-ostree", "db", "diff",
                               boote["checksum"], attente["checksum"]], timeout=120)
    if code != 0:
        return None
    resultat = lire_db_diff(sortie)
    commun.ecrire_json(cache, resultat)
    return resultat
