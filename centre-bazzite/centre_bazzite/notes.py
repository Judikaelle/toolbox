"""Notes de version réelles : appstream Flatpak (disque), releases GitHub de Bazzite,
historique de maj-apps, pages officielles du noyau, de NVIDIA, de Plasma et de Mesa.
Cache JSON dans CACHE/notes/. Une réussite est gardée pour de bon ; un échec réseau des sources
courantes n'est jamais mis en cache, celui d'une source officielle l'est 6 h (voir notes_pour)."""
import gzip
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

from . import commun

APPSTREAM = Path("/var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz")
URL_BAZZITE = "https://api.github.com/repos/ublue-os/bazzite/releases?per_page=30"
HISTORIQUE_MAJ_APPS = Path.home() / ".local" / "state" / "maj-apps" / "historique.jsonl"
MODULES_MAJ_APPS = ("vicinae", "ollama", "uv")
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

OFFICIELLES = ("kernel", "nvidia-driver", "plasma-workspace", "mesa-dri-drivers")
DELAI_OFFICIEL = 15
TAILLE_OFFICIELLE = 6000
RESSAI_OFFICIEL = timedelta(hours=6)
LECTURE_MAX = 2_000_000
PAGES_MAX = 4
PAGES_MAX_NOYAU = 5
NOYAU_UTILES = ("drm", "nouveau", "nvidia", "btrfs", "ext4", "exfat", "usb", "hid", "input", "bluetooth",
                "wifi", "iwlwifi", "mt76", "alsa", "sound", "x86", "nvme")
URL_NVIDIA_CATEGORIE = "https://forums.developer.nvidia.com/c/148.json"
URL_NVIDIA_FORUM = "https://forums.developer.nvidia.com"
URL_NVIDIA_PILOTES = "https://www.nvidia.com/en-us/drivers/unix/"
SOURCE_NVIDIA = "Forum NVIDIA (développeurs)"
SOURCE_PLASMA = "kde.org (annonces Plasma)"
SOURCE_MESA = "docs.mesa3d.org (notes de version)"
SOURCE_NOYAU = "kernel.org (ChangeLog)"
SOURCE_KERNELNEWBIES = "KernelNewbies"


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


# --- Notes officielles (noyau, NVIDIA, Plasma, Mesa) -------------------------------------------

_BLOCS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "ul", "ol", "li", "section", "article",
                    "main", "details", "summary", "br", "tr", "pre", "table", "blockquote", "dl", "dt", "dd",
                    "hr"))
_IGNORES = frozenset(("script", "style", "title", "head", "nav", "header", "footer", "svg", "form",
                      "noscript", "template"))
_TITRES = {f"h{i}": i for i in range(1, 7)}


class _Texte(HTMLParser):
    """HTML -> texte : un titre ou un bloc par ligne, « - » devant chaque <li>. `section` : id de
    l'élément à garder ; `racines` : sinon, premier de ces éléments (le reste de la page est écarté)."""

    def __init__(self, section=None, racines=None):
        super().__init__(convert_charrefs=True)
        self.lignes, self.cur, self.pref = [], "", ""
        self.ignore = 0
        self.permalien = False
        self.section, self.racines = section, racines
        self.actif = section is None and racines is None
        self.fini = False
        self.cible = None           # (balise, niveau de titre ou None)
        self.profondeur = 0

    def _vider(self):
        ligne = " ".join(self.cur.replace("¶", " ").split())
        ligne = re.sub(r"\s*\bCommit\.", "", ligne).strip()
        if ligne and ligne != "-":
            self.lignes.append(ligne)
        self.cur = ""

    def _demarre(self, tag, attrs):
        if self.section is not None:
            if dict(attrs).get("id") == self.section:
                self.cible = (tag, _TITRES.get(tag))
                self.actif, self.profondeur = True, 1
                return True
        elif self.racines and tag in self.racines:
            self.cible, self.actif, self.profondeur = (tag, None), True, 1
            return True
        return False

    def handle_starttag(self, tag, attrs):
        if self.fini:
            return
        if self.ignore:
            if tag in _IGNORES:
                self.ignore += 1
            return
        if not self.actif:
            if tag in _IGNORES:
                self.ignore += 1
            else:
                self._demarre(tag, attrs)
            return
        if self.cible is not None:
            balise, niveau = self.cible
            if niveau is not None:
                if tag in _TITRES and _TITRES[tag] <= niveau:
                    self._vider()
                    self.fini = True
                    return
            elif tag == balise:
                self.profondeur += 1
        if tag in _IGNORES:
            self.ignore += 1
            return
        if tag == "a" and "headerlink" in (dict(attrs).get("class") or ""):
            self.permalien = True
        if tag in _BLOCS:
            self._vider()
        if tag == "li":
            self.pref = "- "

    def handle_endtag(self, tag):
        if self.fini:
            return
        if self.ignore:
            if tag in _IGNORES:
                self.ignore -= 1
            return
        if tag == "a":
            self.permalien = False
        if not self.actif:
            return
        if tag in _BLOCS:
            self._vider()
        if tag == "li":
            self.pref = ""
        if self.cible is not None and self.cible[1] is None and tag == self.cible[0]:
            self.profondeur -= 1
            if self.profondeur == 0:
                self.fini = True

    def handle_data(self, data):
        if self.fini or self.ignore or self.permalien or not self.actif:
            return
        if not data.strip():
            if self.cur and not self.cur.endswith(" "):
                self.cur += " "
            return
        if not self.cur:
            self.cur, self.pref = self.pref, ""
        self.cur += data


def texte_html(html, *, section=None, racines=None):
    """Texte lisible d'une page HTML (voir _Texte). `section` inconnue : chaîne vide."""
    p = _Texte(section, racines)
    p.feed(html)
    p.close()
    p._vider()
    return "\n".join(p.lignes)


def _segments(v):
    """Entiers d'une version « 6.8.2 », ou None si un segment n'est pas numérique."""
    try:
        seg = [int(x) for x in v.split(".")]
    except (AttributeError, ValueError):
        return None
    return seg or None


def _pages(ident, de, vers):
    """[(url, étiquette de version)], de la plus récente à la plus ancienne (5 au plus)."""
    v = _segments(vers)
    if v is None or len(v) < 2:
        return []
    d = _segments(de) if de else None
    M, m = v[0], v[1]
    p = v[2] if len(v) > 2 else None
    meme = d is not None and len(d) >= 3 and p is not None and d[:2] == v[:2]
    if ident == "plasma-workspace":
        annonce = (f"https://kde.org/announcements/plasma/{M}/{M}.{m}.0/", f"{M}.{m}.0")
        if p is None or (d is not None and not meme):
            return [annonce]
        if meme:
            bornes = range(max(d[2] + 1, p - PAGES_MAX + 1), p + 1)
        elif p >= 1:
            bornes = [p]
        else:
            return [annonce]
        return [(f"https://kde.org/announcements/changelogs/plasma/{M}/{M}.{m}.{b - 1}-{M}.{m}.{b}/",
                 f"{M}.{m}.{b}") for b in reversed(bornes)]
    if ident == "mesa-dri-drivers":
        if p is None:
            return []
        if d is not None and not meme:
            res = [(f"https://docs.mesa3d.org/relnotes/{M}.{m}.0.html", f"{M}.{m}.0")]
            if p != 0:
                res.append((f"https://docs.mesa3d.org/relnotes/{vers}.html", vers))
            return res
        bornes = range(max(d[2] + 1, p - PAGES_MAX + 1), p + 1) if meme else [p]
        return [(f"https://docs.mesa3d.org/relnotes/{M}.{m}.{b}.html", f"{M}.{m}.{b}")
                for b in reversed(bornes)]
    if ident == "kernel":
        nb = (f"https://kernelnewbies.org/Linux_{M}.{m}", f"{M}.{m}")
        if p is None or (d is not None and not meme):
            return [nb]
        bornes = range(max(d[2] + 1, p - PAGES_MAX_NOYAU + 1), p + 1) if meme else [p]
        return [(f"https://cdn.kernel.org/pub/linux/kernel/v{M}.x/ChangeLog-{M}.{m}.{b}", f"{M}.{m}.{b}")
                for b in reversed(bornes)]
    return []


def pages_officielles(ident, de, vers):
    """URL des pages de notes à lire pour (ident, de -> vers), la plus récente d'abord."""
    return [u for u, _ in _pages(ident, de, vers)]


def _id_titre(html, texte):
    """id du premier titre dont le texte contient `texte`, ou None."""
    for m in re.finditer(r"<h([1-6])\b[^>]*?\bid=[\"']([^\"']+)[\"'][^>]*>(.*?)</h\1>", html, re.S | re.I):
        if texte in re.sub(r"<[^>]+>", "", m.group(3)):
            return m.group(2)
    return None


def _sujets_noyau(texte):
    """Sujets des commits d'un ChangeLog du noyau : doublons et « Linux X.Y.Z » écartés,
    sous-systèmes utiles d'abord."""
    sujets, vus = [], set()
    for bloc in re.split(r"(?m)^commit [0-9a-f]{7,40}\b.*$", texte)[1:]:
        for ligne in bloc.splitlines():
            if ligne.startswith("    ") and ligne.strip():
                sujet = ligne.strip()
                if not re.match(r"Linux \d", sujet) and sujet not in vus:
                    vus.add(sujet)
                    sujets.append(sujet)
                break

    def utile(sujet):
        prefixe = sujet.split(":", 1)[0].lower() if ":" in sujet else ""
        return prefixe.startswith(NOYAU_UTILES)
    return [s for s in sujets if utile(s)] + [s for s in sujets if not utile(s)]


def extraire(ident, url, texte):
    """Texte utile d'une page officielle ; chaîne vide si rien n'est reconnu."""
    if ident == "plasma-workspace":
        if "/changelogs/" in url:
            return texte_html(texte)
        return texte_html(texte, racines=("main", "article"))
    if ident == "mesa-dri-drivers":
        parties = []
        for sid in ("new-features", "bug-fixes"):
            t = texte_html(texte, section=sid)
            corps = t.splitlines()[1:]
            if corps and corps != ["- None"]:
                parties.append(t)
        return "\n\n".join(parties)
    if ident == "kernel":
        if "kernelnewbies" in url:
            sid = _id_titre(texte, "Prominent features")
            return texte_html(texte, section=sid) if sid else ""
        return "\n".join("- " + s for s in _sujets_noyau(texte))
    return ""


def _lire_page(url, ouvrir):
    req = urllib.request.Request(url, headers={"User-Agent": "health-hub"})
    with ouvrir(req, timeout=DELAI_OFFICIEL) as r:
        return r.read(LECTURE_MAX).decode("utf-8", errors="replace")


_VERSION_NVIDIA = re.compile(r"\d{3}\.\d+(\.\d+)?\b")


def notes_nvidia(de, vers, ouvrir=urllib.request.urlopen):
    """Notes d'un pilote NVIDIA d'après le fil épinglé de sa branche sur le forum développeurs :
    la section de `vers` si elle existe, sinon (branche nouvelle ou `de` inconnu) tout le premier
    message, sinon rien. Le lien du fil est gardé dans tous les cas où on l'a trouvé."""
    branche = vers.split(".")[0]
    res = {"source": SOURCE_NVIDIA, "texte": None, "lien": URL_NVIDIA_PILOTES}
    try:
        sujets = json.loads(_lire_page(URL_NVIDIA_CATEGORIE, ouvrir))["topic_list"]["topics"]
    except (OSError, ValueError, KeyError, TypeError):
        return res
    motif = f"{branche} release feedback"
    trouves = [t for t in sujets if isinstance(t, dict) and str(t.get("title", "")).lower().startswith(motif)]
    if not trouves:
        return res
    sujet = next((t for t in trouves if t.get("pinned")), trouves[0])
    res["lien"] = f"{URL_NVIDIA_FORUM}/t/{sujet.get('slug')}/{sujet.get('id')}"
    try:
        fil = json.loads(_lire_page(f"{URL_NVIDIA_FORUM}/t/{sujet.get('id')}.json", ouvrir))
        texte = texte_html(fil["post_stream"]["posts"][0]["cooked"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return res
    lignes = texte.splitlines()
    debut = next((i for i, l in enumerate(lignes) if vers in l and _VERSION_NVIDIA.match(l)), None)
    if debut is not None:
        fin = next((j for j in range(debut + 1, len(lignes))
                    if _VERSION_NVIDIA.match(lignes[j]) and vers not in lignes[j]), len(lignes))
        res["texte"] = "\n".join(lignes[debut:fin]) or None
    elif texte and (not de or de.split(".")[0] != branche):
        res["source"] = f"Forum NVIDIA (nouveautés de la branche {branche})"
        res["texte"] = texte
    return res


def _repli_officiel(ident, de, vers):
    """Source et lien d'une note officielle, sans texte."""
    v = _segments(vers) or []
    if ident == "nvidia-driver":
        return {"source": SOURCE_NVIDIA, "texte": None, "lien": URL_NVIDIA_PILOTES}
    if ident == "plasma-workspace":
        return {"source": SOURCE_PLASMA, "texte": None,
                "lien": f"https://kde.org/announcements/plasma/{v[0] if v else ''}/{vers}/"}
    if ident == "mesa-dri-drivers":
        return {"source": SOURCE_MESA, "texte": None, "lien": f"https://docs.mesa3d.org/relnotes/{vers}.html"}
    pages = _pages("kernel", de, vers)
    if len(v) >= 3 and pages and "kernelnewbies" not in pages[0][0]:
        return {"source": SOURCE_NOYAU, "texte": None, "lien": pages[0][0]}
    lien = f"https://kernelnewbies.org/Linux_{v[0]}.{v[1]}" if len(v) >= 2 else "https://kernelnewbies.org/"
    return {"source": SOURCE_KERNELNEWBIES, "texte": None, "lien": lien}


def notes_officielles(changement, ouvrir=urllib.request.urlopen):
    """NoteOfficielle {"source", "texte", "lien"} d'un paquet système ; `texte` vaut None si rien
    n'a pu être lu (le lien reste). Ne lève jamais."""
    ident, de, vers = changement.get("id"), changement.get("de"), changement.get("vers")
    res = _repli_officiel(ident, de, vers)
    try:
        if ident == "nvidia-driver":
            return notes_nvidia(de, vers, ouvrir)
        morceaux = []
        pages = _pages(ident, de, vers)
        for url, v in pages:
            try:
                t = extraire(ident, url, _lire_page(url, ouvrir)).strip()
            except Exception:           # page absente, lente ou changée de forme : on saute
                continue
            if t:
                morceaux.append((v, t))
        if not morceaux:
            return res
        if ident == "kernel" and "kernelnewbies" in pages[0][0]:
            res["source"] = SOURCE_KERNELNEWBIES
        if len(pages) == 1:
            texte = morceaux[0][1]
        else:
            texte = "\n\n".join(f"Version {v}\n{t}" for v, t in morceaux)
        res["texte"] = texte[:TAILLE_OFFICIELLE]
    except Exception:
        res["texte"] = None
    return res


def _echec_recent(en_cache, maintenant):
    try:
        return datetime.fromisoformat(maintenant) - datetime.fromisoformat(en_cache["echec"]) < RESSAI_OFFICIEL
    except (KeyError, TypeError, ValueError):
        return False


def notes_pour(changement, ouvrir=urllib.request.urlopen, *, maintenant=commun.maintenant):
    """Route un Changement vers sa source : appstream, Bazzite, maj-apps ou pages officielles
    (noyau, NVIDIA, Plasma, Mesa). None si aucune note ; un échec réseau n'est pas mis en cache.
    Exception, source officielle : le résultat garde source et lien avec `texte` None ; l'échec
    est noté dans le cache et le réseau n'est pas redemandé avant RESSAI_OFFICIEL."""
    vers = changement.get("vers")
    ident = changement.get("id")
    if not vers or not ident:
        return None
    chemin = _chemin_cache(ident, vers)
    en_cache = commun.lire_json(chemin, None)
    cat = changement.get("categorie")
    officielle = cat == "systeme" and ident in OFFICIELLES
    if isinstance(en_cache, dict) and en_cache:
        if "echec" not in en_cache:
            return en_cache
        if officielle and _echec_recent(en_cache, maintenant()):
            return {"source": en_cache.get("source"), "lien": en_cache.get("lien"), "texte": None}
    if officielle:
        res = notes_officielles(changement, ouvrir)
        if res.get("texte"):
            commun.ecrire_json(chemin, res)
        else:
            commun.ecrire_json(chemin, {"echec": maintenant(), "source": res.get("source"),
                                        "lien": res.get("lien")})
        return res
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
