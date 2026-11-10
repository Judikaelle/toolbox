"""Points signalés, sourdine (« ne plus signaler jusqu'à ce que ça empire ») et couleur globale."""
import re
from datetime import datetime

from . import commun, sante as sante_mod

MIN_POURCENT = 10
MIN_GIO = 15
GROS_VOLUME_GIO = 100
USURE_MAX = 80
CHALEUR_MAX = 70
OLLAMA_HEURES = 2


def _point(id_, gravite, titre, detail, mesure=0.0, cran=1.0, action=None):
    return {"id": id_, "gravite": gravite, "titre": titre, "detail": detail,
            "mesure": float(mesure), "cran": float(cran), "action": action,
            "en_sourdine": False}


def _heures_depuis(depuis, maintenant):
    """Accepte l'ISO de commun.maintenant() ou le format systemd « Mon 2026-11-09 08:00:00 CET »."""
    if not depuis:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", str(depuis))
    if not m:
        return None
    try:
        debut = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}")
    except ValueError:
        return None
    return (maintenant - debut).total_seconds() / 3600


def _points_ssd(ssd):
    """Les identifiants suivent la nature de l'alerte (spec 7.7) : une sourdine posée sur des erreurs
    média ne masque pas un nouvel avertissement critique, ni l'usure une réserve qui s'effondre."""
    res = []
    for d in ssd or []:
        s = d.get("sante")
        if not s:
            continue
        modele = d.get("modele", "?")
        erreurs = s.get("erreurs_media") or 0
        avert = sorted({str(a) for a in s.get("avertissements") or []})
        disque = d.get("peripherique")
        commande = (f"sudo smartctl -a {disque}" if disque
                    else "sudo smartctl --scan pour trouver le disque, puis sudo smartctl -a /dev/<disque>")
        if erreurs > 0 or avert:
            nature = "+".join((["erreurs-media"] if erreurs > 0 else []) + avert)
            raisons = ([f"{erreurs} erreur(s) de média"] if erreurs > 0 else []) + \
                      ([f"avertissement critique : {', '.join(avert)}"] if avert else [])
            res.append(_point(
                f"ssd:{modele}:critique:{nature}", "echec", f"Le disque {modele} signale un problème grave",
                f"{'; '.join(raisons).capitalize()}. Sauvegarde tes données importantes sans attendre. "
                f"Détail : {commande} (à lancer dans un terminal).",
                erreurs, 1))
        usure = s.get("usure")
        reserve, seuil = s.get("reserve"), s.get("seuil_reserve")
        if usure is not None and usure >= USURE_MAX:
            res.append(_point(
                f"ssd:{modele}:usure", "attention", f"Le disque {modele} est usé à {usure} %",
                f"Usure {usure} %, réserve {reserve} % (seuil {seuil} %). "
                "Prévois un remplacement et garde une sauvegarde à jour.",
                usure, 5))
        if reserve is not None and seuil is not None and reserve < seuil:
            res.append(_point(
                f"ssd:{modele}:reserve", "attention",
                f"La réserve du disque {modele} est passée à {reserve} %",
                f"Réserve {reserve} % sous le seuil de {seuil} % (usure {usure} %). "
                "Prévois un remplacement et garde une sauvegarde à jour.",
                100 - reserve, 5))
        t = s.get("temperature")
        if t is not None and t >= CHALEUR_MAX:
            res.append(_point(
                f"ssd:{modele}:chaleur", "attention", f"Le disque {modele} chauffe : {t} °C",
                "Vérifie la ventilation du boîtier et du radiateur du disque.", t, 5))
    return res


def _go(x):
    """Go entiers, espace comme séparateur de milliers (« 3 726 »)."""
    return f"{x:,.0f}".replace(",", " ")


def _taille_go(x):
    """« 3 726 Go » ; sous 10 Go, la taille lisible (« 72 Mo », « 5,2 Go ») plutôt que « 0 Go »."""
    return f"{_go(x)} Go" if x >= 10 else commun.taille(round(x * 1024 ** 3))


def _points_volumes(volumes):
    res = []
    for v in volumes or []:
        total, libre = v.get("total_go") or 0, v.get("libre_go") or 0
        pct = v.get("pourcent_utilise")
        if pct is None and total:
            pct = 100 * (total - libre) / total
        if pct is None:
            continue
        if (100 - pct) < MIN_POURCENT or (total >= GROS_VOLUME_GIO and libre < MIN_GIO):
            nom = v.get("nom") or v.get("chemin")
            res.append(_point(
                f"volume:{v['chemin']}", "attention", f"{nom} : plus que {_taille_go(libre)} libres",
                f"Il reste {_taille_go(libre)} libres sur {_taille_go(total)}. "
                "Libère de la place avant que les mises à jour ou les jeux échouent.",
                pct, 3))
    return res


def _liste(elements, n=5):
    return ", ".join(elements[:n]) + (" …" if len(elements) > n else "")


def _derniere_reussite_uupd(uupd, maj_apps, session):
    reussites = [quand for quand, ok, _d in _evenements_maj(uupd, maj_apps, session)["uupd"] if ok]
    return max(reussites) if reussites else None


def _numeros(version):
    """« 45.20261110 » -> (45, 20261110), pour comparer deux versions de Bazzite ; None si illisible."""
    nombres = re.findall(r"\d+", str(version or ""))
    return tuple(int(n) for n in nombres) if nombres else None


def _image_nouvelle(v, deploiements):
    """La version `v` vue par les contrôles est-elle plus récente que l'image démarrée, et pas déjà en attente ?"""
    dep = deploiements or {}
    courant = (dep.get("courant") or {}).get("version")
    attente = (dep.get("en_attente") or {}).get("version")
    if v in (courant, attente):
        return False
    if attente and _numeros(v) and _numeros(attente) and _numeros(v) <= _numeros(attente):
        return False
    if courant and _numeros(v) and _numeros(courant):
        return _numeros(v) > _numeros(courant)
    return True


def _points_disponibles(c, deploiements, derniere_uupd):
    """Mises à jour disponibles (contrôles en cache) : une information, comptée dans la rubrique.
    Des contrôles antérieurs à la dernière passe réussie de uupd sont caducs : uupd a installé depuis."""
    res = []
    a_jour = derniere_uupd is None or str(c.get("date") or "") > derniere_uupd
    v = (c.get("image") or {}).get("disponible")
    if v and a_jour and _image_nouvelle(v, deploiements):
        res.append(_point(f"maj:dispo:image:{v}", "info", f"Bazzite {v} est disponible",
                          "« Tout mettre à jour » l'installe (la passe de nuit aussi) ; "
                          "elle s'applique au redémarrage suivant.", 0, 1))
    apps = list((c.get("flatpak") or {}).get("a_mettre_a_jour") or [])
    if apps and a_jour:
        n = len(apps)
        res.append(_point("maj:dispo:flatpak", "info",
                          "Une mise à jour Flatpak est disponible" if n == 1
                          else f"{n} mises à jour Flatpak sont disponibles",
                          f"À mettre à jour : {_liste(apps)}. « Tout mettre à jour » s'en charge "
                          "(la passe de nuit aussi).", n, 1))
    return res


def _points_menage(c):
    res = []
    r = c.get("runtimes") or {}
    inutilises, gl = list(r.get("inutilises") or []), list(r.get("gl_obsoletes") or [])
    if inutilises or gl:
        n = len(inutilises) + len(gl)
        details = []
        if inutilises:
            details.append(f"Inutilisés : {_liste(inutilises)}. Pour les retirer : flatpak uninstall --unused.")
        if gl:
            details.append(f"Anciens pilotes GL NVIDIA, épinglés : {_liste(gl)}. Pour les retirer : "
                           "flatpak pin --remove <ref>, puis flatpak uninstall --unused.")
        res.append(_point("menage:runtimes", "attention",
                          "Un runtime Flatpak est inutilisé" if n == 1 else f"{n} runtimes Flatpak sont inutilisés",
                          " ".join(details), n, 1))
    tel = [t for t in c.get("telechargements") or [] if isinstance(t, dict)]
    if tel:
        n = len(tel)
        lignes = [f"{t.get('nom')} ({commun.taille(t.get('octets') or 0)}, {t.get('present', 0)} % présent)"
                  for t in tel[:5]]
        res.append(_point("menage:telechargements-incomplets", "attention",
                          "Un téléchargement est incomplet" if n == 1 else f"{n} téléchargements sont incomplets",
                          f"{', '.join(lignes)}{' …' if n > 5 else ''}. "
                          f"Ils réservent {commun.taille(sum(t.get('octets') or 0 for t in tel))} : "
                          "supprime-les ou relance leur téléchargement.", n, 1))
    journal = (c.get("caches") or {}).get("journal")
    if isinstance(journal, (int, float)) and journal >= 1024 ** 3:
        res.append(_point("menage:journal", "attention", f"Le journal système occupe {commun.taille(journal)}",
                          "Réduis-le dans un terminal : sudo journalctl --vacuum-size=500M",
                          round(journal / 1024 ** 3, 2), 1))
    return res


def _unite_montage(chemin):
    """/var/mnt/DONNEES -> var-mnt-DONNEES.mount (comme systemd-escape --path)."""
    return chemin.strip("/").replace("-", "\\x2d").replace("/", "-") + ".mount"


def _points_stockage(sante):
    res = []
    noms = {chemin: nom for nom, chemin in sante_mod.volumes_suivis()}
    for chemin in sante.get("non_montes") or []:
        nom = noms.get(chemin, chemin)
        res.append(_point(f"stockage:non-monte:{chemin}", "echec", f"{nom} n'est pas monté",
                          f"{chemin} est absent : ce qui y est installé ne se lancera pas. Vérifie que le disque "
                          f"est branché, puis regarde : systemctl status {_unite_montage(chemin)}", 0, 1))
    e = sante.get("erreurs_disque") or {}
    n = e.get("nombre") or 0
    if n > 0:
        exemples = " ; ".join(e.get("exemples") or [])
        res.append(_point("stockage:erreurs-es", "echec" if n > 5 else "attention",
                          "Une erreur de disque depuis le démarrage" if n == 1
                          else f"{n} erreurs de disque depuis le démarrage",
                          "Le noyau signale des erreurs d'entrée-sortie ou de système de fichiers. "
                          "Sauvegarde tes données importantes. "
                          + (f"Exemples : {exemples}. " if exemples else "")
                          + "Le détail : journalctl -k -b", n, 1))
    return res


def _points_deploiements(deploiements):
    """Plus de deux déploiements conservés. Le déploiement en attente (mise à jour installée, redémarrage
    attendu) n'est pas compté (Ruling V38) : ce troisième-là est normal et déjà signalé par « attend un
    redémarrage ». Ce qui reste en trop, ce sont des déploiements épinglés : le détail les nomme et donne la
    commande à copier pour les désépingler (Ruling V42) ; Health Hub ne l'exécute jamais."""
    dep = deploiements or {}
    nombre = dep.get("nombre")
    if not isinstance(nombre, int):
        return []
    conserves = nombre - (1 if dep.get("en_attente") else 0)
    if conserves <= 2:
        return []
    epingles = [e for e in dep.get("epingles") or [] if isinstance(e, dict)]
    if epingles:
        noms = ", ".join(f"Bazzite {e.get('version') or '?'} (n° {e.get('position')})" for e in epingles)
        commandes = " ; ".join(f"sudo ostree admin pin --unpin {e.get('position')}" for e in epingles)
        detail = (f"Épinglés, donc jamais retirés : {noms}. Pour libérer de la place sur le disque système, "
                  f"désépingle ceux dont tu n'as plus besoin, dans un terminal : {commandes}. "
                  "Ils partiront à la mise à jour suivante.")
    else:
        detail = ("Au-delà du système actuel et du précédent, des déploiements épinglés occupent de la place sur "
                  "le disque système. Pour en désépingler un, dans un terminal : sudo ostree admin pin --unpin <n> "
                  "(n = sa position dans rpm-ostree status, à partir de 0).")
    return [_point("deploiements:trop", "attention", f"{conserves} déploiements du système sont conservés",
                   detail, conserves, 1)]


MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")
TITRES_ECHEC = {"uupd": "La mise à jour du système a échoué",
                "maj-apps": "La mise à jour des outils (maj-apps) a échoué"}
ETAPES_HORS_MAJ = {"notes": "notes de version", "resume": "résumé", "etat": "bilan de santé",
                   "extinction": "extinction"}


def _le(iso):
    try:
        d = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"le {d.day} {MOIS[d.month - 1]} à {d.hour} h {d.minute:02d}"


def _evenements_maj(uupd, maj_apps, session):
    """Exécutions terminées de chaque type de mise à jour : (quand, réussie, détail)."""
    ev = {"uupd": [], "maj-apps": []}
    for e in uupd or []:
        quand = e.get("fin") or e.get("debut")
        if e.get("succes") is not None and quand:
            ev["uupd"].append((quand, bool(e["succes"]),
                               f"Regarde le journal : journalctl -u {e.get('unite') or 'uupd.service'}"))
    if maj_apps and maj_apps.get("date"):
        ko = [str(r.get("module")) for r in maj_apps.get("resultats") or [] if r.get("etat") == "échec"]
        ev["maj-apps"].append((maj_apps["date"], not ko,
                               "En échec : " + ", ".join(ko) + ". Le rapport : maj-apps --report"))
    if session:
        quand = session.get("fin") or session.get("debut")
        for nom in ev:
            e = (session.get("etapes") or {}).get(nom) or {}
            if quand and e.get("statut") in ("fini", "echec"):
                ev[nom].append((quand, e["statut"] == "fini",
                                "Pendant « Tout mettre à jour »" + (f" : {e['detail']}" if e.get("detail") else "")
                                + ". Le détail est dans la page Mises à jour"))
    return ev


def _points_echecs(uupd, maj_apps, session):
    """Un échec de mise à jour porte son identité (type et date) : il disparaît dès qu'une exécution
    plus récente du même type réussit, et une sourdine ne masque pas l'échec suivant."""
    res = []
    for type_, liste in _evenements_maj(uupd, maj_apps, session).items():
        if not liste:
            continue
        quand, ok, detail = max(liste, key=lambda x: x[0])
        if not ok:
            res.append(_point(f"maj:echec:{type_}:{quand}", "echec", TITRES_ECHEC[type_],
                              f"Échec {_le(quand)}. {detail}. Le prochain passage la retentera.", 0, 1))
    if session and session.get("succes") is False:
        ko = [f"{ETAPES_HORS_MAJ[n]}" + (f" ({e.get('detail')})" if e.get("detail") else "")
              for n, e in (session.get("etapes") or {}).items()
              if n in ETAPES_HORS_MAJ and isinstance(e, dict) and e.get("statut") == "echec"]
        if ko:
            res.append(_point(f"session:echec:{session.get('debut')}", "info",
                              "La dernière session n'a pas tout terminé",
                              "Étapes en échec : " + ", ".join(ko) + ". Les mises à jour elles-mêmes ne sont pas en cause.",
                              0, 1))
    return res


def _points_reportes(maj_apps):
    """Ce que le dernier passage de maj-apps a mis de côté (conteneur dont l'appli est ouverte, AppImage
    qui tourne, réseau absent) reste une mise à jour disponible, jusqu'au passage qui la fait vraiment."""
    res = []
    for r in (maj_apps or {}).get("resultats") or []:
        if not isinstance(r, dict) or r.get("etat") != "reporté":
            continue
        module = str(r.get("module") or "?")
        lignes = [l.strip() for l in str(r.get("details") or "").splitlines() if "reporté" in l]
        phrases = [l if l.endswith((".", "!", "?")) else l + "." for l in lignes]
        detail = " ".join(phrases + ["Elle se fera au prochain passage de maj-apps, ou avec « Tout mettre à jour »."])
        res.append(_point(f"maj:dispo:majapps:{module}", "info",
                          str(r.get("message") or f"{module} : mise à jour reportée"), detail, 0, 1))
    return res


def points(sante, deploiements, maj_apps=None, session=None, uupd=None, maintenant=None):
    """`uupd` : exécutions récentes de uupd (journal) ; `maj_apps` : dernière ligne de résultats de
    maj-apps ; `session` : dernière session « Tout mettre à jour » archivée."""
    maintenant = maintenant or datetime.now()
    sante = sante or {}
    res = _points_echecs(uupd, maj_apps, session)
    res += _points_reportes(maj_apps)

    res += _points_ssd(sante.get("ssd"))
    res += _points_stockage(sante)

    attente = (deploiements or {}).get("en_attente")
    if attente and attente.get("version"):
        v = attente["version"]
        res.append(_point(f"redemarrage:{v}", "attention", f"Bazzite {v} attend un redémarrage",
                          "La mise à jour est installée mais ne sera active qu'après un redémarrage.",
                          0, 1, {"libelle": "Redémarrer", "commande": ["systemctl", "reboot"]}))

    c = sante.get("controles")
    c = c if isinstance(c, dict) else {}
    res += _points_disponibles(c, deploiements, _derniere_reussite_uupd(uupd, maj_apps, session))
    res += _points_volumes(sante.get("volumes"))
    if isinstance(c.get("boot"), dict):
        res += _points_volumes([c["boot"]])
    res += _points_deploiements(deploiements)
    res += _points_menage(c)

    for u in sante.get("services_en_echec") or []:
        res.append(_point(f"service:{u}", "attention", f"Le service {u} est en échec",
                          f"Regarde pourquoi : systemctl status {u}  (puis journalctl -u {u}).", 0, 1))

    o = sante.get("ollama") or {}
    if o.get("actif") and not o.get("modeles_charges"):
        h = _heures_depuis(o.get("depuis"), maintenant)
        if h is not None and h > OLLAMA_HEURES:
            res.append(_point("ollama:inactif", "attention",
                              f"Ollama tourne depuis {h:.0f} h sans modèle chargé",
                              "Le service occupe de la mémoire pour rien. Arrête-le : systemctl --user stop ollama.service",
                              h, 4, {"libelle": "Arrêter Ollama",
                                     "commande": ["systemctl", "--user", "stop", "ollama.service"]}))

    err = sante.get("erreurs_journal")
    if err:
        n = sum(e.get("nombre", 1) for e in err)
        res.append(_point("journal:erreurs", "info", f"{n} erreur(s) dans le journal système",
                          "Rien d'urgent ; consulte-les avec : journalctl -p err -b", n, 1))
    pl = sante.get("plantages")
    if pl:
        res.append(_point("plantages", "info", f"{len(pl)} plantage(s) récent(s)",
                          "Liste complète avec : coredumpctl list", len(pl), 1))
    return res


_TOUT_RELEVE = object()


# Clé des contrôles en cache dont dépend chaque point (None : vérification en échec, hors ligne…).
CLES_CONTROLES = (("maj:dispo:image:", "image"), ("maj:dispo:flatpak", "flatpak"), ("menage:runtimes", "runtimes"),
                  ("menage:telechargements", "telechargements"), ("menage:journal", "caches"))


def _controle_releve(id_, controles):
    if not isinstance(controles, dict):
        return False
    for prefixe, cle in CLES_CONTROLES:
        if id_.startswith(prefixe):
            valeur = controles.get(cle)
            return valeur is not None and (cle != "caches" or (valeur or {}).get("journal") is not None)
    return True


def releve(id_, sante):
    """La source du point `id_` a-t-elle été relevée dans `sante` ? Sinon (collecteur en échec,
    SMART illisible, volume démonté, contrôle hors ligne), son absence ne dit pas que le problème a disparu."""
    if sante is _TOUT_RELEVE:
        return True
    sante = sante if isinstance(sante, dict) else {}
    if id_.startswith(("maj:dispo:", "menage:")):
        return _controle_releve(id_, sante.get("controles"))
    if id_ == "volume:/boot":          # avant la règle générique des volumes : il vient des contrôles
        c = sante.get("controles")
        return isinstance(c, dict) and c.get("boot") is not None
    if id_.startswith("ssd:"):
        return any(isinstance(d, dict) and d.get("sante") and id_.startswith(f"ssd:{d.get('modele')}:")
                   for d in sante.get("ssd") or [])
    if id_.startswith("volume:"):
        return any(isinstance(v, dict) and v.get("chemin") == id_[len("volume:"):]
                   for v in sante.get("volumes") or [])
    for prefixe, cle in (("service:", "services_en_echec"), ("ollama:", "ollama"),
                         ("journal:", "erreurs_journal"), ("plantages", "plantages"),
                         ("stockage:erreurs", "erreurs_disque"), ("stockage:non-monte:", "non_montes")):
        if id_.startswith(prefixe):
            return sante.get(cle) is not None
    return True


def appliquer_sourdines(points_, sourdines, fichier=None, sante=_TOUT_RELEVE):
    """Marque les points en sourdine ; retire de `sourdines` (et du fichier si donné)
    celles dont la mesure a atteint enregistrée + cran, ou dont le point a disparu alors que
    sa source a bien été relevée (voir `releve`)."""
    retire = False
    presents = {p["id"] for p in points_}
    for id_ in [i for i in sourdines if i not in presents and releve(i, sante)]:
        del sourdines[id_]
        retire = True
    for p in points_:
        id_ = p["id"]
        if id_ not in sourdines:
            continue
        if p["mesure"] >= sourdines[id_] + p["cran"]:
            del sourdines[id_]
            retire = True
            p["en_sourdine"] = False
        else:
            p["en_sourdine"] = True
    if retire and fichier is not None:
        commun.ecrire_json(fichier, sourdines)
    return points_


def _fichier(fichier):
    return fichier if fichier is not None else commun.ETAT / "sourdines.json"


def points_avec_sourdines(points_, sante=_TOUT_RELEVE):
    f = _fichier(None)
    return appliquer_sourdines(points_, commun.lire_json(f, {}), f, sante)


def mettre_en_sourdine(point_id, points_, fichier=None):
    fichier = _fichier(fichier)
    for p in points_:
        if p["id"] == point_id:
            s = commun.lire_json(fichier, {})
            s[point_id] = p["mesure"]
            commun.ecrire_json(fichier, s)
            return


def lever_sourdine(point_id, fichier=None):
    fichier = _fichier(fichier)
    s = commun.lire_json(fichier, {})
    if s.pop(point_id, None) is not None:
        commun.ecrire_json(fichier, s)


def couleur(points_, en_cours):
    if en_cours:
        return "en_cours"
    actifs = [p for p in points_ if not p.get("en_sourdine") and p["gravite"] != "info"]
    if any(p["gravite"] == "echec" for p in actifs):
        return "rouge"
    return "orange" if actifs else "vert"


# Rubrique d'un point : le premier préfixe qui correspond, sinon « sante ».
RUBRIQUES = {"majs": ("maj:", "redemarrage:", "session:"), "stockage": ("volume:", "menage:", "stockage:")}


def rubrique(point_id):
    for nom, prefixes in RUBRIQUES.items():
        if str(point_id).startswith(prefixes):
            return nom
    return "sante"


# Domaine d'un point : l'onglet de la page Santé où il se range (Task 19) ; le premier préfixe qui correspond, sinon
# « systeme ». Les badges des onglets de la santé ne comptent que les points de la rubrique « sante » (Ruling V68) : ceux
# des autres rubriques (maj:, volume:, stockage:, menage:, redemarrage:, session:) restent sur leur page. Les points que
# points() produit, et leur domaine :
#   disques   : ssd:<modèle>:usure|reserve|chaleur|critique:<nature>, stockage:erreurs-es,
#               stockage:non-monte:<chemin>, volume:<chemin> (l'espace d'un volume ; son détail est dans Stockage)
#   gpu       : ollama:inactif
#   controles : ce que vérifie bazzite-health : volume:/boot, deploiements:trop, menage:runtimes,
#               menage:telechargements-incomplets, menage:journal, maj:dispo:image:<v>, maj:dispo:flatpak
#   journal   : journal:erreurs, plantages
#   systeme   : service:<unité>, redemarrage:<v>, session:echec:<début>, maj:echec:<type>:<date>
# gpu:, gel (gpu) et coredump: (journal) n'existent pas encore : ils ont leur place d'avance, comme dans la page v1.
DOMAINES = (("controles", ("volume:/boot", "deploiements:", "menage:", "maj:dispo:")),
            ("disques", ("ssd:", "stockage:", "volume:")),
            ("gpu", ("gpu:", "ollama:", "gel")),
            ("journal", ("journal:", "plantages", "coredump:")),
            ("systeme", ("service:", "redemarrage:", "session:", "maj:echec:")))


def domaine(point_id):
    for nom, prefixes in DOMAINES:
        if str(point_id).startswith(prefixes):
            return nom
    return "systeme"


def compteurs(points_):
    """Nombre de points à regarder par rubrique : hors sourdine, hors info (sauf « mise à jour disponible »)."""
    n = {"majs": 0, "sante": 0, "stockage": 0}
    for p in points_:
        if p.get("en_sourdine"):
            continue
        if p["gravite"] != "info" or str(p["id"]).startswith("maj:dispo:"):
            n[rubrique(p["id"])] += 1
    return n
