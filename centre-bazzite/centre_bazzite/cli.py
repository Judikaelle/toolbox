"""Interface en ligne de commande de Health Hub (appelée par la fenêtre et le widget)."""
import argparse
import json
import os
import signal
import sys
from pathlib import Path

from . import analyse, commun, etat, hebdo, inventaire, jeux, menage, notes, points, resume, sante, session, stockage, taches
from . import modejeu   # mode jeu (Task 5) ; bureau (dbus) n'est importé que par `modejeu service`

BIN = Path(__file__).resolve().parent.parent / "bin" / "centre-bazzite"
UNITE = "centre-bazzite-maj"
DEJA_EN_COURS = "Une mise à jour est déjà en cours."
ANALYSE_DEJA_EN_COURS = "Une analyse est déjà en cours."
CODE_JEU = 75       # comme maj-apps : reporté parce qu'un jeu tourne
CONTROLES_HEURES = 20

# --- Mode jeu (Task 5) ---
# D10 : les commandes lourdes du relevé horaire, reportées pendant un jeu (HEALTH_HUB_RELEVE=1, réglage « taches »).
LOURDES = ("releve", "controles", "stockage", "jeux", "analyser")
RESTAURER = {"rien": "Aucune partie à restaurer.",
             "service_actif": "Le service du mode jeu s'en occupe.",
             "jeu_en_cours": "Un jeu tourne encore : restauration à la fin de la partie.",
             "restaure": "Mode jeu : bureau remis comme avant.",
             "redemarrage": "Le PC a redémarré depuis : rien à remettre.",
             "inconnu": "État du service du mode jeu inconnu : rien n'est touché."}
TITRE_RESTAURER = "Remettre le bureau comme avant"
# statut de la tâche du panneau Activité : « fini » seulement quand le bureau est comme avant (ou rien à remettre)
STATUT_RESTAURER = {"jeu_en_cours": "interrompu", "service_actif": "interrompu", "inconnu": "echec"}
# --- fin mode jeu ---


def _parser():
    p = argparse.ArgumentParser(prog="centre-bazzite", description="Health Hub : mises à jour et santé.")
    sous = p.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("etat", help="affiche l'état actuel")
    c.add_argument("--json", action="store_true", help="affiche etat.json tel quel")
    c = sous.add_parser("rafraichir", help="recalcule l'état")
    c.add_argument("--leger", action="store_true", help="sans refaire les mesures de santé")
    sous.add_parser("releve", help="enregistre un relevé des versions installées")
    for nom, aide in (("maj", "lance la mise à jour complète en arrière-plan"),
                      ("_session", argparse.SUPPRESS)):
        c = sous.add_parser(nom, help=aide)
        c.add_argument("--eteindre", action="store_true", help="éteint l'ordinateur à la fin (après 60 s annulables)")
        if nom == "maj":
            c.add_argument("--meme-si-jeu", action="store_true",
                           help="lance la mise à jour même si un jeu tourne (sinon, elle est refusée)")
    sous.add_parser("resumer", help="résume les changements depuis ta dernière visite")
    sous.add_parser("annuler-extinction", help="annule l'extinction programmée")
    for nom in ("sourdine", "sans-sourdine"):
        c = sous.add_parser(nom, help="met un point en sourdine" if nom == "sourdine" else "lève la sourdine d'un point")
        c.add_argument("id", help="identifiant du point")
    sous.add_parser("vu", help="marque l'état comme vu")
    sous.add_parser("redemarrer", help="redémarre l'ordinateur")
    c = sous.add_parser("taches", help="liste les tâches du panneau Activité")
    c.add_argument("--effacer", action="store_true", help="efface les tâches terminées")
    c.add_argument("--json", action="store_true", help="affiche les tâches en JSON")
    c = sous.add_parser("controles", help="refait les contrôles lents (mises à jour disponibles, ménage, stockage)")
    c.add_argument("--si-perime", action="store_true",
                   help=f"seulement si les derniers contrôles ont plus de {CONTROLES_HEURES} h")
    sous.add_parser("stockage", help="relève les disques et leurs volumes (stockage.json)")
    sous.add_parser("jeux", help="relève les bibliothèques de jeux, doublons, préfixes orphelins et gels (jeux.json)")
    c = sous.add_parser("analyser", help="analyse des volumes en arrière-plan avec LinStat (catégories, gros dossiers)")
    c.add_argument("chemins", nargs="*", help="volumes à analyser (par défaut : les volumes montés)")
    c.add_argument("--si-perime", action="store_true",
                   help=f"seulement les volumes dont l'analyse a plus de {analyse.AGE_MAX_JOURS} jours "
                        "ou a été interrompue par un jeu")
    c.add_argument("--arreter", action="store_true",
                   help=f"arrête l'analyse en cours (pas de relance automatique pendant "
                        f"{analyse.PAUSE_APRES_ARRET_H} h)")
    c = sous.add_parser("_analyser", help=argparse.SUPPRESS)
    c.add_argument("chemins", nargs="+")
    c = sous.add_parser("menage", help="fait le ménage d'une recommandation de la page Stockage (après confirmation)")
    c.add_argument("id", help="identifiant de la recommandation (caches, corbeille, telechargements, runtimes, shaders, proton)")
    c.add_argument("--empreinte", required=True,
                   help="empreinte des éléments montrés par la fenêtre (cible, libellé, taille) : rien n'est fait "
                        "si la liste a changé depuis")
    c = sous.add_parser("bilan", help="bilan de la semaine (notification du lundi)")
    g = c.add_mutually_exclusive_group()
    g.add_argument("--report", action="store_true", help="affiche le dernier bilan sans le recalculer")
    g.add_argument("--json", action="store_true", help="recalcule et affiche le bilan en JSON")
    g.add_argument("--quiet", action="store_true", help="recalcule sans notifier")
    # --- Mode jeu (Task 5) ---
    c = sous.add_parser("modejeu", help="mode jeu automatique : état, service, réglages, restauration")
    c.add_argument("action", nargs="?", default="etat", choices=("etat", "service", "regler", "restaurer"),
                   help="etat (par défaut) ; service : la boucle de health-hub-modejeu ; regler CLE oui|non ; "
                        "restaurer : remet le bureau comme avant si le service n'est plus là")
    c.add_argument("arguments", nargs="*", help=f"pour regler : la clé ({', '.join(modejeu.CLES)}), puis oui ou non")
    c.add_argument("--si-orphelin", action="store_true",
                   help="restaurer seulement si le service du mode jeu ne tourne pas (c'est toujours vérifié)")
    # --- fin mode jeu ---
    return p


def _changements_visite():
    donnees = commun.lire_json(commun.ETAT / "etat.json", {})
    res, vus = [], set()
    for entree in ((donnees.get("depuis_visite") or {}).get("chronologie") or []):
        for c in entree.get("changements") or []:
            cle = (c.get("id"), c.get("vers"))
            if cle not in vus:
                vus.add(cle)
                res.append(c)
    return res


def _bilan(a, ecrire_etat):
    if a.report:
        chemin = commun.ETAT / "bilan-hebdo.txt"
        print(chemin.read_text(encoding="utf-8") if chemin.exists() else "Aucun bilan pour l'instant.")
        return 0
    sante.ecrire_controles()
    ecrire_etat()
    bilan = hebdo.construire()
    hebdo.ecrire(bilan)
    ecrire_etat()       # la page Santé lit le bilan dans etat.json : il doit y figurer aussitôt
    if a.json:
        print(json.dumps(bilan, ensure_ascii=False, indent=2))
    elif not a.quiet:
        hebdo.notifier(bilan)
    return 0


def _volumes_a_analyser(chemins, montes):
    """Les chemins demandés (par défaut les volumes montés), sans doublon et sans volume non monté : un volume
    connu doit figurer parmi `montes` ; un autre chemin (disque ajouté) doit être un point de montage."""
    connus = {chemin for _, chemin in sante.volumes_suivis()}
    res = []
    for chemin in [os.path.normpath(c) for c in chemins] if chemins else montes:
        if chemin in res:
            continue
        if chemin in montes or (chemin not in connus and os.path.ismount(chemin)):
            res.append(chemin)
        else:
            print(f"{chemin} n'est pas monté : ignoré.", file=sys.stderr)
    return res


def _arreter_analyse(run):
    """`analyser --arreter` : le marqueur dit au superviseur que son SIGTERM vient de toi, puis l'unité est arrêtée
    (`systemctl stop` attend la fin du superviseur). Le marqueur ne reste jamais derrière : sinon le prochain arrêt
    par la fin de session passerait pour une demande."""
    unite = f"{analyse.UNITE}.service"
    if run(["systemctl", "--user", "is-active", unite])[0] != 0:
        print("Aucune analyse en cours.")
        return 0
    marqueur = analyse.marqueur_arret()
    marqueur.parent.mkdir(parents=True, exist_ok=True)
    marqueur.write_text(commun.maintenant() + "\n", encoding="utf-8")
    code, texte = run(["systemctl", "--user", "stop", unite])
    marqueur.unlink(missing_ok=True)
    if code != 0:
        print(texte.strip() or f"systemctl stop a échoué (code {code}).", file=sys.stderr)
        return 1
    print("Analyse arrêtée.")
    return 0


def _republier_stockage():
    """Réécrit stockage.json, pour qu'une page Stockage ouverte suive l'analyse. Ne lève jamais : un relevé qui échoue
    ne doit ni faire échouer l'analyse ni masquer un arrêt."""
    try:
        print(stockage.ecrire())
    except Exception as exc:
        print(f"stockage.json non republié : {exc}", file=sys.stderr)


def _superviser_analyse(chemins, jeu):
    """`_analyser`, dans l'unité health-hub-analyse : stockage.json republié après chaque volume, puis à la fin, y
    compris après « Arrêter » (le SIGTERM devient un SystemExit qui passe par le `finally`)."""
    etat_superviseur = {}
    analyse.poser_arret(etat_superviseur)       # SIGTERM : bouton « Arrêter », fin de session, extinction
    try:
        analyse.superviser(chemins, jeu=jeu, etat=etat_superviseur, apres_volume=_republier_stockage)
    finally:
        _republier_stockage()


def _analyser(a, run, jeu, volumes):
    if a.arreter:
        return _arreter_analyse(run)
    chemins = _volumes_a_analyser(a.chemins, [v["chemin"] for v in volumes()])
    if a.si_perime:
        chemins = [c for c in chemins if analyse.perime(c)]
    if not chemins:
        print("Aucune analyse à lancer.")
        return 0
    if a.si_perime and analyse.charger_linstat() is None:
        # le relevé horaire ne lance pas une analyse vouée à l'échec ; le bouton « Analyser » montre l'échec
        print("LinStat est absent ou a changé : aucune analyse automatique.")
        return 0
    if jeu():
        print("Un jeu tourne : analyse reportée.", file=sys.stderr)
        # le relevé horaire (--si-perime) ne doit pas passer en échec pendant une partie (V4)
        return 0 if a.si_perime else CODE_JEU
    code, texte = run(["systemd-run", "--user", f"--unit={analyse.UNITE}", "--collect", "--property=Type=exec",
                       str(BIN), "_analyser"] + chemins)
    if code != 0 and ("already loaded" in texte or "already exists" in texte):
        print(ANALYSE_DEJA_EN_COURS)
        return 0
    if code != 0:
        print(texte.strip(), file=sys.stderr)
        return code
    print("Analyse lancée : " + ", ".join(chemins) + ".")
    return 0


def _bilan_menage(id_, res):
    """Le détail d'une tâche de ménage finie : ce qui a été laissé de côté, puis ce qui est parti."""
    taille = commun.taille(res["liberes"])
    fin = f"{taille} envoyés à la corbeille" if id_ == "telechargements" else f"{taille} libérés"
    n = len(res["ignores"])
    if not n:
        return fin
    raisons = ", ".join(sorted({i["raison"] for i in res["ignores"]}))
    return f"{n} laissé{'s' if n > 1 else ''} de côté ({raisons}). {fin}"


def _menage(a, run, jeu):
    """Ménage d'une recommandation de stockage.json, seulement si sa liste est celle que la fenêtre a montrée
    (`--empreinte`) : une tâche du panneau Activité, puis stockage.json republié (la liste montrée suit ce qui reste)."""
    donnees = commun.lire_json(stockage.fichier(), {})
    recos = (donnees.get("recommandations") if isinstance(donnees, dict) else None) or []
    reco = next((r for r in recos if isinstance(r, dict) and r.get("id") == a.id), None)
    if reco is None:
        print(menage.INCONNUE, file=sys.stderr)
        return 2
    id_tache = taches.debuter("menage", a.id, reco.get("titre") or a.id)
    if a.empreinte != menage.empreinte(menage.elements_de(reco)):
        # stockage.json a été réécrit depuis l'affichage : la liste relue n'est pas celle qui a été confirmée.
        res = {"liberes": 0, "faits": [], "ignores": [], "erreur": menage.CHANGEE}
    else:
        try:
            res = menage.executer(a.id, recos, run=run, jeu=jeu)
        except Exception as exc:        # la tâche ne doit jamais rester « en cours »
            res = {"liberes": 0, "faits": [], "ignores": [],
                   "erreur": f"Le ménage a échoué : {type(exc).__name__}: {exc}"}
    for cible in res["faits"]:
        taches.avancer(id_tache, ligne=f"Fait : {cible}")
    for i in res["ignores"]:
        taches.avancer(id_tache, ligne=f"Laissé : {i['cible']} ({i['raison']})")
    if res["erreur"]:
        taches.terminer(id_tache, "echec", res["erreur"])
    else:
        taches.terminer(id_tache, "fini", _bilan_menage(a.id, res))
    _republier_stockage()
    return 1 if res["erreur"] else 0


# --- Mode jeu (Task 5) ---
def _republier_etat(ecrire_leger):
    try:
        ecrire_leger()
    except Exception as exc:
        print(f"etat.json non republié : {exc}", file=sys.stderr)


def _modejeu(a, *, run, jeu, ecrire_leger, bureau):
    if a.action == "service":
        if bureau is None:
            from .bureau import BureauDBus as bureau
        mode = modejeu.ModeJeu(bureau(), jeu=jeu, run=run, publier=ecrire_leger)
        # D7 : un SIGTERM (fin de session, relance d'install.sh, extinction) devient un SystemExit qui passe par le
        # `finally` : les maintiens tombent, la partie reste notée et la reprise décide. Seulement ici.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        try:
            modejeu.servir(mode)
        finally:
            mode.suspendre()
        return 0
    if a.action == "regler":
        if len(a.arguments) != 2:
            print("Usage : centre-bazzite modejeu regler CLE oui|non", file=sys.stderr)
            return 2
        cle, valeur = a.arguments
        if cle not in modejeu.CLES:
            print(f"Réglage inconnu : {cle} ({', '.join(modejeu.CLES)}).", file=sys.stderr)
            return 2
        if valeur not in ("oui", "non"):
            print(f"Valeur inconnue : {valeur} (oui ou non).", file=sys.stderr)
            return 2
        modejeu.regler(cle, valeur == "oui")
        print(f"Mode jeu : {cle} = {valeur}.")
        _republier_etat(ecrire_leger)
        return 0
    if a.action == "restaurer":
        # UI-m2 : lancée par la fenêtre (sans --si-orphelin), la remise du bureau est une tâche du panneau Activité :
        # la fenêtre y lit sa fin et sa phrase. Le relevé horaire (--si-orphelin) n'en crée pas.
        id_tache = None
        if not a.si_orphelin:
            try:
                id_tache = taches.debuter("modejeu", "restaurer", TITRE_RESTAURER)
            except Exception as exc:    # disque plein : la remise du bureau passe avant sa tâche
                print(f"Tâche du panneau Activité impossible à écrire ({type(exc).__name__}: {exc})",
                      file=sys.stderr)
        try:
            resultat = modejeu.restaurer(si_orphelin=a.si_orphelin, run=run, jeu=jeu)
        except Exception as exc:        # la tâche ne doit jamais rester « en cours »
            if id_tache is None:
                raise
            message = f"La remise du bureau a échoué : {type(exc).__name__}: {exc}"
            _terminer_tache(id_tache, "echec", message)
            print(message, file=sys.stderr)
            return 1
        print(RESTAURER[resultat])
        if resultat in ("restaure", "redemarrage"):        # W8-m8 : sinon rien n'a changé
            _republier_etat(ecrire_leger)
        if id_tache is not None:        # après etat.json : la fenêtre relit tout à la fin de la tâche
            _terminer_tache(id_tache, STATUT_RESTAURER.get(resultat, "fini"), RESTAURER[resultat])
        return 0
    resume_ = modejeu.resume()          # etat (Task 6) : la phrase du résumé, puis celle de la dernière partie (P13)
    print(resume_["phrase"])
    if resume_["derniere"]:
        print(resume_["derniere"]["phrase"])
    return 0


def _terminer_tache(id_tache, statut, detail):
    """Finit la tâche de la remise du bureau ; un disque plein ne change pas l'issue de la remise."""
    try:
        taches.terminer(id_tache, statut, detail)
    except Exception as exc:
        print(f"Tâche du panneau Activité impossible à finir ({type(exc).__name__}: {exc})", file=sys.stderr)


def _pause_du_releve(cmd, environ, jeu):
    """D10 : le nom du jeu si cette commande du relevé horaire attend la fin de la partie, sinon None. Jamais hors du
    relevé (fenêtre, terminal) ; des réglages illisibles ne reportent rien."""
    if environ.get("HEALTH_HUB_RELEVE") != "1" or (cmd not in LOURDES and cmd != "rafraichir"):
        return None
    try:
        return modejeu.taches_en_pause(jeu=jeu)
    except Exception as exc:
        print(f"Mode jeu : réglages illisibles, rien n'est reporté ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None
# --- fin mode jeu ---


def main(argv=None, *, run=commun.run, notes_pour=notes.notes_pour, resumer=resume.resumer,
         ecrire_etat=etat.ecrire, ecrire_leger=None, jeu=commun.jeu_en_cours, volumes=sante.volumes,
         ecrire_jeux=jeux.ecrire, bureau=None, environ=os.environ):
    ecrire_leger = ecrire_leger or session._ecrire_leger
    a = _parser().parse_args(argv)
    cmd = a.commande
    # --- Mode jeu (Task 5) : relevé horaire pendant un jeu ---
    en_pause = _pause_du_releve(cmd, environ, jeu)
    if en_pause and cmd in LOURDES:
        print(f"Mode jeu : {cmd} reportée pendant {en_pause}.")
        return 0
    if en_pause and cmd == "rafraichir":
        a.leger = True
    # --- fin mode jeu ---
    if cmd == "etat":
        chemin = commun.ETAT / "etat.json"
        if not chemin.exists():
            ecrire_etat()
        donnees = commun.lire_json(chemin, {})
        if a.json:
            print(json.dumps(donnees, ensure_ascii=False, indent=2))
        else:
            print(donnees.get("phrase", ""))
            print(donnees.get("phrase2", ""))
    elif cmd == "rafraichir":
        ecrire_leger() if a.leger else ecrire_etat()
    elif cmd == "releve":
        print(inventaire.enregistrer(inventaire.relever()))
    elif cmd == "maj":
        nom_jeu = None if a.meme_si_jeu else jeu()
        if nom_jeu:
            print(f"Un jeu tourne ({nom_jeu}) : mise à jour non lancée.", file=sys.stderr)
            try:
                ecrire_leger()      # les interfaces voient le jeu tout de suite et proposent d'attendre
            except Exception as exc:
                print(exc, file=sys.stderr)
            return CODE_JEU
        lancer = ["systemd-run", "--user", f"--unit={UNITE}", "--collect", "--property=Type=exec",
                  str(BIN), "_session"] + (["--eteindre"] if a.eteindre else [])
        code, texte = run(lancer)
        if code != 0 and ("already loaded" in texte or "already exists" in texte):
            print(DEJA_EN_COURS)
            return 0
        if code != 0:
            print(texte.strip(), file=sys.stderr)
            return code
        print("Mise à jour lancée.")
    elif cmd == "_session":
        session.executer(a.eteindre, deps=session.Dependances())
    elif cmd == "resumer":
        changements = _changements_visite()
        if changements:
            session.resumer_changements(changements, notes_pour=notes_pour, resumer=resumer, jeu=jeu)
        ecrire_etat()
    elif cmd == "annuler-extinction":
        (commun.ETAT / "annuler-extinction").parent.mkdir(parents=True, exist_ok=True)
        (commun.ETAT / "annuler-extinction").touch()
    elif cmd in ("sourdine", "sans-sourdine"):
        if cmd == "sourdine":
            pts = commun.lire_json(commun.ETAT / "etat.json", {}).get("points") or []
            points.mettre_en_sourdine(a.id, pts)
        else:
            points.lever_sourdine(a.id)
        ecrire_etat()
    elif cmd == "vu":
        etat.marquer_vu()
        ecrire_leger()
    elif cmd == "redemarrer":
        return run(["systemctl", "reboot"])[0]
    elif cmd == "taches":
        if a.effacer:
            print(f"{taches.effacer_terminees()} tâche(s) effacée(s).")
        elif a.json:
            print(json.dumps(taches.lister(), ensure_ascii=False, indent=2))
        else:
            for t in taches.lister():
                print(f"{t['statut']:<10} {t['titre']} {t.get('detail') or ''}".rstrip())
    elif cmd == "controles":
        if a.si_perime and not sante.controles_perimes(CONTROLES_HEURES):
            print(f"Contrôles de moins de {CONTROLES_HEURES} h : rien à refaire.")
        else:
            print(sante.ecrire_controles())
        ecrire_leger()
    elif cmd == "stockage":
        print(stockage.ecrire())
    elif cmd == "jeux":
        print(ecrire_jeux())
    elif cmd == "analyser":
        return _analyser(a, run, jeu, volumes)
    elif cmd == "_analyser":
        _superviser_analyse(a.chemins, jeu)
    elif cmd == "menage":
        return _menage(a, run, jeu)
    elif cmd == "bilan":
        return _bilan(a, ecrire_etat)
    elif cmd == "modejeu":
        return _modejeu(a, run=run, jeu=jeu, ecrire_leger=ecrire_leger, bureau=bureau)
    return 0


if __name__ == "__main__":
    sys.exit(main())
