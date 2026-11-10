"""Résumé des notes de version par Ollama (jamais pendant un jeu, service remis dans son état)."""
import hashlib
import http.client
import json
import socket
import threading
import time
import urllib.parse
import urllib.request

from . import commun, config
from .commun import jeu_en_cours

MODELE_RESUME = "glm-4.7-flash"
URL = "http://127.0.0.1:11434"
DELAI_APPEL = 180
INTERVALLE_JEU = 2.0      # pendant la génération, un jeu qui démarre est repéré en 2 s au plus
LIMITE_NOTES = 3000

# Le lecteur des résumés ({contexte}) vient de la configuration locale ([resume] contexte).
CONSIGNES = (
    "Tu résumes des notes de version pour {contexte}.\n"
    "Règles : écris en français ; une ou deux phrases par élément ; uniquement à partir des notes "
    "fournies, n'invente rien ; si les notes ne disent rien d'utile, écris "
    "« Corrections et améliorations mineures. » ; signale ce qui touche le GPU NVIDIA, KDE/Wayland, "
    "les jeux ou une action à faire.\n"
    "Réponds uniquement en JSON : un objet {{id: résumé}}."
)


def construire_prompt(elements):
    blocs = [CONSIGNES.format(contexte=config.contexte_resume())]
    for e in elements:
        notes = (e.get("notes") or "")[:LIMITE_NOTES]
        blocs.append(f"id : {e['id']}\nnom : {e['nom']}\n{e.get('de') or '(nouveau)'} → "
                     f"{e.get('vers') or '(supprimé)'}\nnotes :\n{notes}")
    ids = ", ".join(f'"{e["id"]}"' for e in elements)
    blocs.append(f"Clés attendues dans l'objet JSON, exactement : {ids}.")
    return "\n\n".join(blocs)


def lire_reponse(texte):
    """Extrait l'objet JSON {id: résumé} d'une réponse ; {} si rien d'exploitable."""
    texte = texte or ""
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin < debut:
        return {}
    try:
        obj = json.loads(texte[debut:fin + 1])
    except ValueError:
        return {}
    if not isinstance(obj, dict):
        return {}
    return {str(k): v.strip() for k, v in obj.items() if isinstance(v, str) and v.strip()}


_APPELS = []     # connexions HTTP en cours vers Ollama, que _couper_appel peut interrompre


def _appeler_ollama(corps):
    adresse = urllib.parse.urlsplit(URL)
    conn = http.client.HTTPConnection(adresse.hostname, adresse.port, timeout=DELAI_APPEL)
    _APPELS.append(conn)
    try:
        conn.request("POST", "/api/generate", body=json.dumps(corps).encode(),
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            raise OSError(f"Ollama répond HTTP {r.status}")
        return json.loads(r.read().decode("utf-8")).get("response", "")
    finally:
        _APPELS.remove(conn)
        conn.close()


def _couper_appel():
    """Coupe la connexion : Ollama abandonne alors la génération en cours."""
    for conn in list(_APPELS):
        try:
            if conn.sock is not None:
                conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class JeuLance(Exception):
    """Un jeu a démarré pendant le résumé : il est abandonné."""


def _sous_surveillance(fonction, jeu, interrompre, intervalle):
    """Exécute fonction() dans un fil ; si un jeu démarre entre-temps, appelle interrompre()
    et lève JeuLance sans attendre la fin (la VRAM ne déborde pas en RAM chez NVIDIA)."""
    resultat = {}

    def travail():
        try:
            resultat["valeur"] = fonction()
        except BaseException as exc:
            resultat["erreur"] = exc

    fil = threading.Thread(target=travail, daemon=True)
    fil.start()
    while True:
        fil.join(intervalle)
        if not fil.is_alive():
            break
        if jeu():
            interrompre()
            raise JeuLance()
    if "erreur" in resultat:
        raise resultat["erreur"]
    return resultat["valeur"]


class _ServiceOllama:
    UNITE = "ollama.service"

    def etait_actif(self):
        code, _ = commun.run(["systemctl", "--user", "is-active", self.UNITE], timeout=15)
        return code == 0

    def demarrer(self):
        code, sortie = commun.run(["systemctl", "--user", "start", self.UNITE], timeout=30)
        if code != 0:
            raise RuntimeError(f"Ollama ne démarre pas : {sortie.strip()}")
        fin = time.monotonic() + 30
        while time.monotonic() < fin:
            try:
                with urllib.request.urlopen(URL + "/api/tags", timeout=2):
                    return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("Ollama ne répond pas après 30 s")

    def arreter(self):
        commun.run(["systemctl", "--user", "stop", self.UNITE], timeout=30)

    def decharger(self):
        """Décharge le modèle tout de suite (service laissé allumé : il tournait déjà)."""
        corps = json.dumps({"model": MODELE_RESUME, "keep_alive": 0}).encode()
        req = urllib.request.Request(URL + "/api/generate", data=corps,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except OSError:
            pass


def _chemin_cache(notes):
    return commun.CACHE / "resumes" / (hashlib.sha1(notes.encode("utf-8")).hexdigest() + ".json")


def resumer(elements, *, jeu=jeu_en_cours, appeler=_appeler_ollama, service=None,
            couper=_couper_appel, intervalle=INTERVALLE_JEU):
    """{id: résumé en français}, ou None si un jeu tourne (au départ ou pendant la génération),
    si Ollama est absent ou en cas d'erreur."""
    if jeu():
        return None
    service = service if service is not None else _ServiceOllama()
    resultat, a_faire = {}, []
    for e in elements:
        mis = commun.lire_json(_chemin_cache(e.get("notes") or ""), {}).get("resume")
        if isinstance(mis, str) and mis:
            resultat[e["id"]] = mis
        else:
            a_faire.append(e)
    if not a_faire:
        return resultat
    try:
        deja_actif = service.etait_actif()

        def interrompre():
            couper()
            if deja_actif:
                service.decharger()     # sinon le service, démarré par nous, est arrêté ci-dessous

        try:
            if not deja_actif:
                service.demarrer()
            if jeu():                   # un jeu a pu démarrer pendant le démarrage du service
                return None
            corps = {"model": MODELE_RESUME, "prompt": construire_prompt(a_faire),
                     "stream": False, "format": "json", "keep_alive": 0}
            lus = lire_reponse(_sous_surveillance(lambda: appeler(corps), jeu, interrompre, intervalle))
        finally:
            if not deja_actif:
                service.arreter()
    except Exception:
        return None
    for e in a_faire:
        if e["id"] in lus:
            resultat[e["id"]] = lus[e["id"]]
            commun.ecrire_json(_chemin_cache(e.get("notes") or ""), {"resume": lus[e["id"]]})
    return resultat or None
