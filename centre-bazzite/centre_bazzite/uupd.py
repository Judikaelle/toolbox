"""Suivi de uupd : progression lue dans le journal JSON, unité active, lancement, exécutions passées."""
import json
from datetime import datetime

from . import commun

UNITES = ("uupd.service", "uupd-manual.service")
ID_DEBUT = "7d4958e842da4a758f6c1cdc7b36dcc5"   # « Starting … » de systemd
ID_FIN = "39f53479d3a045ac8e11786248231fbf"     # « Finished / Failed … » (JOB_RESULT)


def _entier(valeur, defaut=0):
    return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) else defaut


def lire_progression(lignes):
    etapes, glob = {}, 0
    termine, succes = False, None
    for ligne in lignes:
        try:
            d = json.loads(ligne)
        except (TypeError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        module = d.get("module")
        msg = d.get("msg")
        if msg == "Updates Completed Successfully":
            termine, succes, glob = True, True, 100
            continue
        if isinstance(d.get("overall"), int):
            glob = max(0, min(100, d["overall"]))
        if not module:
            if d.get("level") == "ERROR":
                termine, succes = True, False
            continue
        if d.get("level") == "DEBUG" and not d.get("status"):
            continue
        e = etapes.setdefault(module, {"titre": d.get("title") or module,
                                       "statut": "attente", "progression": 0})
        if d.get("title") and e["titre"] == module:
            e["titre"] = d["title"]
        statut = d.get("status")
        if statut in ("starting", "running") and e["statut"] != "echec":
            e["statut"] = "en_cours"
            e["progression"] = _entier(d.get("step_progress"), e["progression"])
        elif statut == "finished":
            if e["statut"] != "echec":
                ok = d.get("exit_code", 0) == 0
                e["statut"] = "fini" if ok else "echec"
                e["progression"] = 100 if ok else e["progression"]
        if "exit_code" in d and d["exit_code"] != 0:
            e["statut"] = "echec"
        if d.get("level") == "ERROR":
            e["statut"] = "echec"
    return {"etapes": etapes, "global": glob, "termine": termine, "succes": succes}


def unite_active():
    for unite in UNITES:
        code, texte = commun.run(["systemctl", "is-active", unite])
        if texte.strip() in ("active", "activating"):
            return unite
    return None


def lancer():
    code, _ = commun.run(["systemctl", "start", "--no-block", "uupd-manual.service"])
    return code == 0


def lignes_depuis(unite, depuis):
    code, texte = commun.run(["journalctl", "-u", unite, "-o", "cat", "--since", depuis,
                              "--no-pager"], timeout=60)
    return texte.splitlines() if code == 0 else []


def _iso(microsecondes):
    try:
        return datetime.fromtimestamp(int(microsecondes) / 1e6).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def executions_depuis(depuis):
    cmd = ["journalctl", "-o", "json", "--since", depuis, "--no-pager"]
    for u in UNITES:
        cmd += ["-u", u]
    code, texte = commun.run(cmd, timeout=60)
    if code != 0:
        return []
    ouvertes, resultat = {}, []
    for ligne in texte.splitlines():
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        unite = d.get("UNIT")
        if unite not in UNITES or d.get("_SYSTEMD_UNIT") != "init.scope":
            continue
        quand = _iso(d.get("__REALTIME_TIMESTAMP"))
        if d.get("MESSAGE_ID") == ID_DEBUT:
            ouvertes[unite] = quand
        elif d.get("MESSAGE_ID") == ID_FIN:
            resultat.append({"unite": unite, "debut": ouvertes.pop(unite, None), "fin": quand,
                             "succes": d.get("JOB_RESULT") == "done"})
    for unite, debut in ouvertes.items():
        resultat.append({"unite": unite, "debut": debut, "fin": None, "succes": None})
    return sorted(resultat, key=lambda r: r["debut"] or r["fin"] or "")
