"""Notes de version réelles : appstream Flatpak (disque), releases GitHub de Bazzite,
historique de maj-apps. Cache JSON dans CACHE/notes/. Un échec n'est jamais mis en cache."""
import gzip
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import commun

APPSTREAM = Path("/var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz")
URL_BAZZITE = "https://api.github.com/repos/ublue-os/bazzite/releases?per_page=30"
HISTORIQUE_MAJ_APPS = Path.home() / ".local" / "state" / "maj-apps" / "historique.jsonl"
MODULES_MAJ_APPS = ("vicinae", "ollama", "uv")
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _cle_version(v):
    cle = []
    for seg in re.split(r"[^0-9A-Za-z]+", v):
        if seg:
            cle.append((1, int(seg), "") if seg.isdigit() else (0, 0, seg))
    return cle


def comparer_versions(a, b):
    """-1, 0 ou 1 ; les segments numériques sont comparés comme des nombres."""
    ca, cb = _cle_version(a), _cle_version(b)
    return (ca > cb) - (ca < cb)


def _texte_description(desc):
    """Texte lisible d'un <description> appstream : un paragraphe ou une puce par ligne."""
    lignes = []
    for el in desc:
        if el.tag in ("ul", "ol"):
            lignes += ["- " + " ".join("".join(li.itertext()).split()) for li in el]
        else:
            lignes.append(" ".join("".join(el.itertext()).split()))
    return "\n".join(l for l in lignes if l.strip("- "))


def _composant(xml_texte, app_id):
    for _, el in ET.iterparse(_Flux(xml_texte), events=("end",)):
        if el.tag == "component" and el.findtext("id") == app_id:
            return el
        if el.tag == "component":
            el.clear()
    return None


class _Flux:
    """Flux binaire minimal sur une chaîne, pour iterparse."""
    def __init__(self, texte):
        self._b = texte.encode("utf-8")
        self._i = 0

    def read(self, n=-1):
        fin = len(self._b) if n is None or n < 0 else self._i + n
        morceau = self._b[self._i:fin]
        self._i = fin
        return morceau


def notes_appstream(xml_texte, app_id, de, vers):
    """Notes des releases strictement après `de`, jusqu'à `vers` inclus, la plus récente d'abord
    (le résumé tronque la fin). Sans `de` (appli nouvelle) : seulement la release la plus proche
    de `vers`, pas tout l'historique."""
    try:
        comp = _composant(xml_texte, app_id)
    except ET.ParseError:
        return None
    if comp is None:
        return None
    nom = next((n.text for n in comp.findall("name") if n.get(XML_LANG) is None and n.text), app_id)
    releases = []
    for rel in comp.findall("releases/release"):
        v = rel.get("version")
        desc = rel.find("description")
        if not v or desc is None:
            continue
        if de is not None and comparer_versions(v, de) <= 0:
            continue
        if comparer_versions(v, vers) > 0:
            continue
        texte = _texte_description(desc)
        if texte:
            releases.append((v, texte))
    if not releases:
        return None
    releases.sort(key=lambda r: _cle_version(r[0]), reverse=True)
    if de is None:
        releases = releases[:1]
    texte = "\n\n".join(f"Version {v}\n{t}" for v, t in releases)
    return {"source": "Flathub (appstream)", "texte": texte, "nom": nom}


def _lire_appstream(app_id):
    """XML du seul composant voulu, lu en flux dans le fichier appstream (gros). None si absent."""
    try:
        with gzip.open(APPSTREAM, "rb") as f:
            for _, el in ET.iterparse(f, events=("end",)):
                if el.tag == "component":
                    if el.findtext("id") == app_id:
                        return ET.tostring(el, encoding="unicode")
                    el.clear()
    except (OSError, EOFError, ET.ParseError):
        return None
    return None


def notes_bazzite(version, ouvrir=urllib.request.urlopen):
    """Release GitHub dont le tag est `stable-<version>` (ou `<version>`) ; testing/unstable écartés."""
    req = urllib.request.Request(URL_BAZZITE, headers={"User-Agent": "centre-bazzite"})
    with ouvrir(req, timeout=20) as r:
        releases = json.loads(r.read().decode("utf-8"))
    trouvee = None
    for rel in releases:
        tag = rel.get("tag_name", "")
        if tag.startswith(("testing-", "unstable-")):
            continue
        if tag == version or tag.endswith("-" + version):
            if tag.startswith("stable-") or trouvee is None:
                trouvee = rel
                if tag.startswith("stable-"):
                    break
    if trouvee is None:
        return None
    return {"source": "GitHub ublue-os/bazzite", "texte": trouvee.get("body") or "",
            "lien": trouvee.get("html_url")}


def notes_maj_apps(module, vers, historique=None):
    """Dernières notes consignées par maj-apps pour (module, vers)."""
    chemin = Path(historique) if historique else HISTORIQUE_MAJ_APPS
    trouve = None
    try:
        lignes = chemin.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for ligne in lignes:
        try:
            obj = json.loads(ligne)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        for c in obj.get("changements") or []:
            if c.get("module") == module and c.get("vers") == vers and c.get("notes"):
                trouve = c["notes"]
    if trouve is None:
        return None
    return {"source": "GitHub (via maj-apps)", "texte": trouve, "lien": None}


def _chemin_cache(ident, vers):
    sur = re.sub(r"[^A-Za-z0-9._-]", "_", f"{ident}@{vers}")
    return commun.CACHE / "notes" / f"{sur}.json"


def notes_pour(changement, ouvrir=urllib.request.urlopen):
    """Route un Changement vers sa source ; None si aucune note (rien n'est alors mis en cache)."""
    vers = changement.get("vers")
    ident = changement.get("id")
    if not vers or not ident:
        return None
    chemin = _chemin_cache(ident, vers)
    en_cache = commun.lire_json(chemin, None)
    if en_cache:
        return en_cache
    cat = changement.get("categorie")
    try:
        if cat == "applications":
            xml = _lire_appstream(ident)
            res = notes_appstream(xml, ident, changement.get("de"), vers) if xml else None
        elif cat == "systeme" and ident == "image":
            res = notes_bazzite(vers, ouvrir=ouvrir)
        elif cat == "outils" and ident in MODULES_MAJ_APPS:
            res = notes_maj_apps(ident, vers)
        else:
            res = None
    except (OSError, ValueError):
        return None
    if res:
        commun.ecrire_json(chemin, res)
    return res
